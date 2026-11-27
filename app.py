import hashlib
import hmac
import os
import random
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

# ==============================================================================
# CONFIGURATION & POLICY CONSTANTS (NO FIAT CONVERSION SHOWN TO USERS)
# ==============================================================================
DB_PATH = os.environ.get("TAPMINT_DB", "tapmint.db")
ADMIN_SECRET = os.environ.get("TAPMINT_ADMIN_KEY", "TAPMINT_ADMIN_99_SECRET")
MASTER_AFFILIATE_CODE = os.environ.get("TAPMINT_MASTER_REF", "TAPMINT_MASTER_99")

MIN_WITHDRAW_PTS = int(os.environ.get("MIN_WITHDRAW_PTS", "1500"))
BINANCE_MIN_USDT = 5.0
PTS_PER_USDT_INTERNAL = float(os.environ.get("PTS_PER_USDT_INTERNAL", "3000"))
DEFAULT_FEE_RATE = float(os.environ.get("DEFAULT_FEE_RATE", "0.05"))
BINANCE_NETWORK_FEE_PTS = int(os.environ.get("BINANCE_NETWORK_FEE_PTS", "150"))

TASK_MIN_WAIT_SEC = 8.0
TASK_MAX_WAIT_SEC = 10.0
TASK_SESSION_SIZE = 20
TASK_LOCK_HOURS = 2
MINING_COOLDOWN_HOURS = 2
MINING_MAX_DAILY_CLAIMS = 6
SPIN_MAX_DAILY = 1
SPIN_COOLDOWN_HOURS = 24
REFERRAL_BONUS_PTS = 10
MAX_PIN_ATTEMPTS = 5
PIN_LOCK_MINUTES = 15

# ব্যাকএন্ডে স্মার্ট লিংক ম্যাপ করা থাকলেও ইউজার UI-তে অ্যাড নেটওয়ার্কের নাম দেখানো হবে না
SMART_LINK_POOL = [
    "https://example.com/smart-offer-1",
    "https://example.com/smart-offer-2",
    "https://example.com/smart-offer-3",
]


# ==============================================================================
# TIME & SECURITY HELPERS
# ==============================================================================
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def hash_pin(pin: str) -> str:
    return hashlib.sha256(f"tapmint_pin::{pin.strip()}".encode("utf-8")).hexdigest()


def make_ad_token(user_id: str, context_tag: str, issued_ts: int) -> str:
    raw = f"{user_id}|{context_tag}|{issued_ts}".encode("utf-8")
    return hmac.new(ADMIN_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


# ==============================================================================
# DATABASE INITIALIZATION
# ==============================================================================
def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT DEFAULT '',
                pts_balance INTEGER NOT NULL DEFAULT 0 CHECK (pts_balance >= 0),
                referred_by TEXT DEFAULT '',
                referral_rewarded INTEGER NOT NULL DEFAULT 0,
                is_blocked INTEGER NOT NULL DEFAULT 0,
                pin_failed_attempts INTEGER NOT NULL DEFAULT 0,
                pin_locked_until TEXT,
                joined_at TEXT NOT NULL,
                last_active_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS wallets (
                user_id TEXT PRIMARY KEY,
                method TEXT NOT NULL CHECK (method IN ('bKash', 'Nagad', 'Binance USDT')),
                account_target TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                is_verified INTEGER NOT NULL DEFAULT 1,
                connected_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS spin_state (
                user_id TEXT PRIMARY KEY,
                spins_used_today INTEGER NOT NULL DEFAULT 0,
                daily_date TEXT NOT NULL,
                next_spin_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS task_sessions (
                user_id TEXT NOT NULL,
                session_num INTEGER NOT NULL CHECK (session_num BETWEEN 1 AND 5),
                completed_count INTEGER NOT NULL DEFAULT 0 CHECK (completed_count BETWEEN 0 AND 20),
                locked_until TEXT,
                PRIMARY KEY (user_id, session_num),
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS active_task_starts (
                user_id TEXT NOT NULL,
                session_num INTEGER NOT NULL,
                task_num INTEGER NOT NULL,
                started_at_ts INTEGER NOT NULL,
                PRIMARY KEY (user_id, session_num, task_num),
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS mining_state (
                user_id TEXT PRIMARY KEY,
                claims_today INTEGER NOT NULL DEFAULT 0 CHECK (claims_today BETWEEN 0 AND 6),
                daily_date TEXT NOT NULL,
                next_claim_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS game_sessions (
                session_token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                game_name TEXT NOT NULL,
                reward_pts INTEGER NOT NULL,
                started_at_ts INTEGER NOT NULL,
                ad_completed INTEGER NOT NULL DEFAULT 0,
                claimed INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS earning_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                source TEXT NOT NULL CHECK (source IN ('spin', 'task', 'mining', 'game', 'referral')),
                detail TEXT NOT NULL,
                pts_earned INTEGER NOT NULL CHECK (pts_earned >= 0),
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                method TEXT NOT NULL CHECK (method IN ('bKash', 'Nagad', 'Binance USDT')),
                account_target TEXT NOT NULL,
                requested_pts INTEGER NOT NULL CHECK (requested_pts > 0),
                fee_pts INTEGER NOT NULL CHECK (fee_pts >= 0),
                net_pts INTEGER NOT NULL CHECK (net_pts >= 0),
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
                admin_note TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                processed_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS note_khata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_type TEXT NOT NULL CHECK (entry_type IN ('payout', 'ad_revenue', 'fee_summary', 'adjustment')),
                withdraw_id INTEGER,
                user_id TEXT,
                pts_amount INTEGER NOT NULL DEFAULT 0,
                fee_pts INTEGER NOT NULL DEFAULT 0,
                actual_payout_bdt REAL NOT NULL DEFAULT 0.0,
                actual_payout_usdt REAL NOT NULL DEFAULT 0.0,
                est_ad_revenue REAL NOT NULL DEFAULT 0.0,
                note_text TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            """
        )


def ensure_user(conn: sqlite3.Connection, user_id: str, username: str = "", ref_code: str = "") -> sqlite3.Row:
    clean_uid = str(user_id).strip()
    now_dt = utc_now()
    now_str = now_dt.isoformat()
    today_str = now_dt.strftime("%Y-%m-%d")

    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (clean_uid,)).fetchone()
    clean_ref = str(ref_code).strip()
    if clean_ref == clean_uid:
        clean_ref = ""

    if not row:
        conn.execute(
            """
            INSERT INTO users (
                user_id, username, pts_balance, referred_by, referral_rewarded,
                is_blocked, pin_failed_attempts, pin_locked_until, joined_at, last_active_at
            ) VALUES (?, ?, 0, ?, 0, 0, 0, NULL, ?, ?)
            """,
            (clean_uid, username.strip(), clean_ref, now_str, now_str),
        )
        for s in range(1, 6):
            conn.execute(
                """
                INSERT OR IGNORE INTO task_sessions (user_id, session_num, completed_count, locked_until)
                VALUES (?, ?, 0, NULL)
                """,
                (clean_uid, s),
            )
        conn.execute(
            """
            INSERT OR IGNORE INTO spin_state (user_id, spins_used_today, daily_date, next_spin_at)
            VALUES (?, 0, ?, NULL)
            """,
            (clean_uid, today_str),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO mining_state (user_id, claims_today, daily_date, next_claim_at)
            VALUES (?, 0, ?, NULL)
            """,
            (clean_uid, today_str),
        )

        # রেফারার থাকলে (মাস্টার লিংক বা সাধারণ ইউজার রেফার) বোনাস লগ ও ক্রেডিট
        if clean_ref and clean_ref != MASTER_AFFILIATE_CODE:
            ref_user = conn.execute("SELECT user_id, is_blocked FROM users WHERE user_id = ?", (clean_ref,)).fetchone()
            if ref_user and not ref_user["is_blocked"]:
                conn.execute(
                    "UPDATE users SET pts_balance = pts_balance + ? WHERE user_id = ?",
                    (REFERRAL_BONUS_PTS, clean_ref),
                )
                conn.execute(
                    """
                    INSERT INTO earning_logs (user_id, source, detail, pts_earned, created_at)
                    VALUES (?, 'referral', ?, ?, ?)
                    """,
                    (clean_ref, f"Referral bonus from user {clean_uid}", REFERRAL_BONUS_PTS, now_str),
                )
                conn.execute(
                    "UPDATE users SET referral_rewarded = 1 WHERE user_id = ?",
                    (clean_uid,),
                )
    else:
        conn.execute(
            """
            UPDATE users
            SET last_active_at = ?, username = CASE WHEN ? != '' THEN ? ELSE username END
            WHERE user_id = ?
            """,
            (now_str, username.strip(), username.strip(), clean_uid),
        )

    return conn.execute("SELECT * FROM users WHERE user_id = ?", (clean_uid,)).fetchone()


def credit_pts_tx(conn: sqlite3.Connection, user_id: str, source: str, detail: str, pts: int) -> tuple[bool, str]:
    u = conn.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not u:
        return False, "User not found"
    if u["is_blocked"]:
        return False, "Account restricted"
    if pts < 0:
        return False, "Invalid points"

    if pts > 0:
        conn.execute(
            "UPDATE users SET pts_balance = pts_balance + ? WHERE user_id = ?",
            (pts, user_id),
        )
    conn.execute(
        """
        INSERT INTO earning_logs (user_id, source, detail, pts_earned, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, source, detail, pts, iso_now()),
    )
    return True, "Credited"


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-Admin-Key") or request.args.get("admin_key", "")
        if not key or not hmac.compare_digest(key, ADMIN_SECRET):
            return jsonify({"ok": False, "error": "Unauthorized admin access"}), 401
        return f(*args, **kwargs)

    return decorated


def mask_target(target: str) -> str:
    t = target.strip()
    if len(t) <= 6:
        return t
    return f"{t[:3]}••••{t[-4:]}"


# ==============================================================================
# HEALTH & USER STATE SNAPSHOT API
# ==============================================================================
@app.route("/health")
def health():
    return jsonify({"ok": True, "service": "TapMint", "utc_time": iso_now()})


@app.route("/api/user/bootstrap")
def api_user_bootstrap():
    user_id = str(request.args.get("user_id", "")).strip()
    username = str(request.args.get("username", "")).strip()
    ref_code = str(request.args.get("ref", "")).strip()
    if not user_id:
        return jsonify({"ok": False, "error": "user_id is required"}), 400

    now = utc_now()
    today_str = now.strftime("%Y-%m-%d")

    with get_db() as conn:
        user = ensure_user(conn, user_id, username, ref_code)
        if user["is_blocked"]:
            return jsonify({"ok": False, "error": "Account is blocked"}), 403

        wallet = conn.execute(
            "SELECT method, account_target, is_verified, connected_at FROM wallets WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        spin = conn.execute("SELECT * FROM spin_state WHERE user_id = ?", (user_id,)).fetchone()
        spins_used = spin["spins_used_today"] if (spin and spin["daily_date"] == today_str) else 0
        next_spin_at = spin["next_spin_at"] if spin else None

        mining = conn.execute("SELECT * FROM mining_state WHERE user_id = ?", (user_id,)).fetchone()
        claims_today = mining["claims_today"] if (mining and mining["daily_date"] == today_str) else 0
        next_claim_at = mining["next_claim_at"] if mining else None

        sessions = []
        s_rows = conn.execute(
            "SELECT session_num, completed_count, locked_until FROM task_sessions WHERE user_id = ? ORDER BY session_num ASC",
            (user_id,),
        ).fetchall()
        for r in s_rows:
            comp = r["completed_count"]
            lock_u = r["locked_until"]
            is_locked = False
            if lock_u:
                if now < datetime.fromisoformat(lock_u):
                    is_locked = True
                else:
                    conn.execute(
                        "UPDATE task_sessions SET completed_count = 0, locked_until = NULL WHERE user_id = ? AND session_num = ?",
                        (user_id, r["session_num"]),
                    )
                    comp = 0
                    lock_u = None
            sessions.append({
                "session_num": r["session_num"],
                "completed_count": comp,
                "total_tasks": TASK_SESSION_SIZE,
                "is_locked": is_locked,
                "locked_until": lock_u,
            })

        total_refs = conn.execute("SELECT COUNT(*) AS c FROM users WHERE referred_by = ?", (user_id,)).fetchone()["c"]
        active_refs = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE referred_by = ? AND pts_balance > 0", (user_id,)
        ).fetchone()["c"]

        binance_min_pts = max(MIN_WITHDRAW_PTS, int(round(BINANCE_MIN_USDT * PTS_PER_USDT_INTERNAL)))

    return jsonify({
        "ok": True,
        "user": {
            "user_id": user["user_id"],
            "username": user["username"],
            "pts_balance": user["pts_balance"],
        },
        "wallet": {
            "connected": bool(wallet),
            "method": wallet["method"] if wallet else None,
            "masked_target": mask_target(wallet["account_target"]) if wallet else None,
            "is_verified": bool(wallet["is_verified"]) if wallet else False,
        },
        "spin": {
            "spins_used_today": spins_used,
            "max_daily": SPIN_MAX_DAILY,
            "next_spin_at": next_spin_at,
            "max_reward_pts": 15,
        },
        "mining": {
            "claims_today": claims_today,
            "max_daily": MINING_MAX_DAILY_CLAIMS,
            "cooldown_hours": MINING_COOLDOWN_HOURS,
            "next_claim_at": next_claim_at,
            "reward_range": "5-10 PTS",
        },
        "task_sessions": sessions,
        "referral": {
            "total_referrals": total_refs,
            "active_referrals": active_refs,
            "current_bonus_pts": total_refs * REFERRAL_BONUS_PTS,
            "referral_code": f"REF_{user_id}",
        },
        "withdraw_rules": {
            "general_min_pts": MIN_WITHDRAW_PTS,
            "binance_min_pts": binance_min_pts,
            "binance_min_usdt_rule": BINANCE_MIN_USDT,
            "fee_rate_percent": int(DEFAULT_FEE_RATE * 100),
            "binance_network_fee_pts": BINANCE_NETWORK_FEE_PTS,
        },
    })


# ==============================================================================
# 1) DAILY SPIN WHEEL (HOME)
# ==============================================================================
@app.route("/api/spin", methods=["POST"])
def api_spin():
    data = request.get_json(silent=True) or {}
    user_id = str(data.get("user_id", "")).strip()
    username = str(data.get("username", "")).strip()
    if not user_id:
        return jsonify({"ok": False, "error": "user_id is required"}), 400

    now = utc_now()
    today_str = now.strftime("%Y-%m-%d")

    with get_db() as conn:
        user = ensure_user(conn, user_id, username)
        if user["is_blocked"]:
            return jsonify({"ok": False, "error": "Account restricted"}), 403

        sp = conn.execute("SELECT * FROM spin_state WHERE user_id = ?", (user_id,)).fetchone()
        used_today = sp["spins_used_today"] if (sp and sp["daily_date"] == today_str) else 0
        if sp and sp["next_spin_at"] and now < datetime.fromisoformat(sp["next_spin_at"]):
            return jsonify({
                "ok": False,
                "error": "Daily spin cooldown active",
                "next_spin_at": sp["next_spin_at"],
            }), 429

        if used_today >= SPIN_MAX_DAILY:
            next_sp = sp["next_spin_at"] if (sp and sp["next_spin_at"]) else (now + timedelta(hours=SPIN_COOLDOWN_HOURS)).isoformat()
            return jsonify({"ok": False, "error": "Daily spin limit reached", "next_spin_at": next_sp}), 429

        # সর্বোচ্চ 15 PTS, তবে টপ প্রাইজের চান্স খুবই কম (0.5%)
        wheel_pool = (
            [("1 PTS", 1)] * 450
            + [("2 PTS", 2)] * 280
            + [("5 PTS", 5)] * 120
            + [("10 PTS", 10)] * 20
            + [("15 PTS", 15)] * 5
            + [("Try Again", 0)] * 75
            + [("Bonus", 3)] * 50
        )
        slot_label, reward_pts = random.choice(wheel_pool)
        next_spin_str = (now + timedelta(hours=SPIN_COOLDOWN_HOURS)).isoformat()

        conn.execute(
            """
            INSERT INTO spin_state (user_id, spins_used_today, daily_date, next_spin_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                spins_used_today = excluded.spins_used_today,
                daily_date = excluded.daily_date,
                next_spin_at = excluded.next_spin_at
            """,
            (user_id, used_today + 1, today_str, next_spin_str),
        )

        ok, msg = credit_pts_tx(conn, user_id, "spin", f"Daily Spin ({slot_label})", reward_pts)
        if not ok:
            return jsonify({"ok": False, "error": msg}), 403

        bal = conn.execute("SELECT pts_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()["pts_balance"]

    return jsonify({
        "ok": True,
        "slot": slot_label,
        "pts_earned": reward_pts,
        "pts_balance": bal,
        "next_spin_at": next_spin_str,
    })


# ==============================================================================
# 2) TASKS CENTER (5 SESSIONS x 20 TASKS, 8-10s WAIT, 2h ROLLING LOCK)
# ==============================================================================
@app.route("/api/task/open", methods=["POST"])
def api_task_open():
    data = request.get_json(silent=True) or {}
    user_id = str(data.get("user_id", "")).strip()
    username = str(data.get("username", "")).strip()
    session_num = int(data.get("session_num", 0))
    task_num = int(data.get("task_num", 0))

    if not user_id or session_num not in range(1, 6) or task_num not in range(1, 21):
        return jsonify({"ok": False, "error": "Invalid session or task number"}), 400

    now = utc_now()
    now_ts = int(time.time())

    with get_db() as conn:
        user = ensure_user(conn, user_id, username)
        if user["is_blocked"]:
            return jsonify({"ok": False, "error": "Account restricted"}), 403

        s_row = conn.execute(
            "SELECT * FROM task_sessions WHERE user_id = ? AND session_num = ?",
            (user_id, session_num),
        ).fetchone()
        if s_row and s_row["locked_until"]:
            lock_dt = datetime.fromisoformat(s_row["locked_until"])
            if now < lock_dt:
                return jsonify({
                    "ok": False,
                    "error": "Session locked for 2 hours",
                    "locked_until": s_row["locked_until"],
                }), 423
            conn.execute(
                "UPDATE task_sessions SET completed_count = 0, locked_until = NULL WHERE user_id = ? AND session_num = ?",
                (user_id, session_num),
            )

        conn.execute(
            """
            INSERT INTO active_task_starts (user_id, session_num, task_num, started_at_ts)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, session_num, task_num) DO UPDATE SET started_at_ts = excluded.started_at_ts
            """,
            (user_id, session_num, task_num, now_ts),
        )

    # স্মার্ট লিংক ব্যাকএন্ডে ম্যাপ করা; ফ্রন্টএন্ডে কোনো অ্যাড নেটওয়ার্ক নাম দেখানো হবে না
    smart_url = SMART_LINK_POOL[(session_num + task_num) % len(SMART_LINK_POOL)]
    return jsonify({
        "ok": True,
        "session_num": session_num,
        "task_num": task_num,
        "wait_min_seconds": TASK_MIN_WAIT_SEC,
        "wait_max_seconds": TASK_MAX_WAIT_SEC,
        "started_at_ts": now_ts,
        "launch_url": smart_url,
    })


@app.route("/api/task/complete", methods=["POST"])
def api_task_complete():
    data = request.get_json(silent=True) or {}
    user_id = str(data.get("user_id", "")).strip()
    username = str(data.get("username", "")).strip()
    session_num = int(data.get("session_num", 0))
    task_num = int(data.get("task_num", 0))

    if not user_id or session_num not in range(1, 6) or task_num not in range(1, 21):
        return jsonify({"ok": False, "error": "Invalid session or task number"}), 400

    now = utc_now()
    now_ts = int(time.time())

    with get_db() as conn:
        user = ensure_user(conn, user_id, username)
        if user["is_blocked"]:
            return jsonify({"ok": False, "error": "Account restricted"}), 403

        s_row = conn.execute(
            "SELECT * FROM task_sessions WHERE user_id = ? AND session_num = ?",
            (user_id, session_num),
        ).fetchone()
        if s_row and s_row["locked_until"] and now < datetime.fromisoformat(s_row["locked_until"]):
            return jsonify({
                "ok": False,
                "error": "Session is currently locked for 2 hours",
                "locked_until": s_row["locked_until"],
            }), 423

        start_row = conn.execute(
            """
            SELECT started_at_ts FROM active_task_starts
            WHERE user_id = ? AND session_num = ? AND task_num = ?
            """,
            (user_id, session_num, task_num),
        ).fetchone()
        if not start_row:
            return jsonify({"ok": False, "error": "Open task first before completing"}), 400

        elapsed = now_ts - int(start_row["started_at_ts"])
        if elapsed < TASK_MIN_WAIT_SEC:
            remaining = round(TASK_MIN_WAIT_SEC - elapsed, 1)
            return jsonify({
                "ok": False,
                "error": f"Wait at least {int(TASK_MIN_WAIT_SEC)}-{int(TASK_MAX_WAIT_SEC)} seconds ({remaining}s left)",
            }), 400

        conn.execute(
            "DELETE FROM active_task_starts WHERE user_id = ? AND session_num = ? AND task_num = ?",
            (user_id, session_num, task_num),
        )

        current_completed = s_row["completed_count"] if s_row else 0
        if s_row and s_row["locked_until"] and now >= datetime.fromisoformat(s_row["locked_until"]):
            current_completed = 0

        new_completed = current_completed + 1
        locked_until_str = None
        if new_completed >= TASK_SESSION_SIZE:
            locked_until_str = (now + timedelta(hours=TASK_LOCK_HOURS)).isoformat()
            conn.execute(
                """
                UPDATE task_sessions
                SET completed_count = ?, locked_until = ?
                WHERE user_id = ? AND session_num = ?
                """,
                (TASK_SESSION_SIZE, locked_until_str, user_id, session_num),
            )
        else:
            conn.execute(
                """
                UPDATE task_sessions
                SET completed_count = ?, locked_until = NULL
                WHERE user_id = ? AND session_num = ?
                """,
                (new_completed, user_id, session_num),
            )

        reward_pts = random.choice([1, 2])
        ok, msg = credit_pts_tx(conn, user_id, "task", f"Session {session_num} - Task {task_num:02d}", reward_pts)
        if not ok:
            return jsonify({"ok": False, "error": msg}), 403

        bal = conn.execute("SELECT pts_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()["pts_balance"]

    return jsonify({
        "ok": True,
        "pts_earned": reward_pts,
        "pts_balance": bal,
        "session_num": session_num,
        "completed_count": new_completed,
        "session_locked": bool(locked_until_str),
        "locked_until": locked_until_str,
    })


# ==============================================================================
# 3) MINING (EVERY 2 HOURS, MAX 6 CLAIMS/DAY, 5-10 PTS MOSTLY 5-7 PTS)
# ==============================================================================
@app.route("/api/mining/claim", methods=["POST"])
def api_mining_claim():
    data = request.get_json(silent=True) or {}
    user_id = str(data.get("user_id", "")).strip()
    username = str(data.get("username", "")).strip()
    if not user_id:
        return jsonify({"ok": False, "error": "user_id is required"}), 400

    now = utc_now()
    today_str = now.strftime("%Y-%m-%d")

    with get_db() as conn:
        user = ensure_user(conn, user_id, username)
        if user["is_blocked"]:
            return jsonify({"ok": False, "error": "Account restricted"}), 403

        m = conn.execute("SELECT * FROM mining_state WHERE user_id = ?", (user_id,)).fetchone()
        claims_today = m["claims_today"] if (m and m["daily_date"] == today_str) else 0

        if claims_today >= MINING_MAX_DAILY_CLAIMS:
            return jsonify({
                "ok": False,
                "error": f"Daily limit of {MINING_MAX_DAILY_CLAIMS} mining claims reached",
            }), 429

        if m and m["next_claim_at"] and now < datetime.fromisoformat(m["next_claim_at"]):
            return jsonify({
                "ok": False,
                "error": "Mining cooldown active (2 hours between claims)",
                "next_claim_at": m["next_claim_at"],
            }), 425

        # 5 থেকে 10 PTS এর মধ্যে 5-7 PTS এর ওয়েটেজ সবচেয়ে বেশি
        reward_pts = random.choices([5, 6, 7, 8, 9, 10], weights=[32, 30, 22, 8, 5, 3], k=1)[0]
        new_claims = claims_today + 1
        next_claim_str = (now + timedelta(hours=MINING_COOLDOWN_HOURS)).isoformat()

        conn.execute(
            """
            INSERT INTO mining_state (user_id, claims_today, daily_date, next_claim_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                claims_today = excluded.claims_today,
                daily_date = excluded.daily_date,
                next_claim_at = excluded.next_claim_at
            """,
            (user_id, new_claims, today_str, next_claim_str),
        )

        ok, msg = credit_pts_tx(conn, user_id, "mining", f"Mining Claim #{new_claims}/{MINING_MAX_DAILY_CLAIMS}", reward_pts)
        if not ok:
            return jsonify({"ok": False, "error": msg}), 403

        bal = conn.execute("SELECT pts_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()["pts_balance"]

    return jsonify({
        "ok": True,
        "pts_earned": reward_pts,
        "pts_balance": bal,
        "claims_today": new_claims,
        "max_daily": MINING_MAX_DAILY_CLAIMS,
        "next_claim_at": next_claim_str,
    })


# ==============================================================================
# 4) GAMES ARENA (TARGET + MANDATORY AD BEFORE CLAIM)
# ==============================================================================
@app.route("/api/game/start", methods=["POST"])
def api_game_start():
    data = request.get_json(silent=True) or {}
    user_id = str(data.get("user_id", "")).strip()
    username = str(data.get("username", "")).strip()
    game_name = str(data.get("game_name", "Arcade Game")).strip()
    reward_pts = max(1, min(int(data.get("reward_pts", 5)), 10))

    if not user_id:
        return jsonify({"ok": False, "error": "user_id is required"}), 400

    now_ts = int(time.time())
    token = make_ad_token(user_id, f"{game_name}:{now_ts}", now_ts)[:24]

    with get_db() as conn:
        user = ensure_user(conn, user_id, username)
        if user["is_blocked"]:
            return jsonify({"ok": False, "error": "Account restricted"}), 403
        conn.execute(
            """
            INSERT INTO game_sessions (session_token, user_id, game_name, reward_pts, started_at_ts, ad_completed, claimed)
            VALUES (?, ?, ?, ?, ?, 0, 0)
            """,
            (token, user_id, game_name, reward_pts, now_ts),
        )

    return jsonify({
        "ok": True,
        "session_token": token,
        "game_name": game_name,
        "reward_pts": reward_pts,
    })


@app.route("/api/game/ad-complete", methods=["POST"])
def api_game_ad_complete():
    data = request.get_json(silent=True) or {}
    token = str(data.get("session_token", "")).strip()
    user_id = str(data.get("user_id", "")).strip()
    if not token or not user_id:
        return jsonify({"ok": False, "error": "session_token and user_id required"}), 400

    with get_db() as conn:
        gs = conn.execute(
            "SELECT * FROM game_sessions WHERE session_token = ? AND user_id = ?",
            (token, user_id),
        ).fetchone()
        if not gs:
            return jsonify({"ok": False, "error": "Game session not found"}), 404
        if gs["claimed"]:
            return jsonify({"ok": False, "error": "Reward already claimed"}), 400
        if int(time.time()) - int(gs["started_at_ts"]) < 3:
            return jsonify({"ok": False, "error": "Play session too short"}), 400

        conn.execute("UPDATE game_sessions SET ad_completed = 1 WHERE session_token = ?", (token,))

    return jsonify({"ok": True, "ad_completed": True, "session_token": token})


@app.route("/api/game/claim", methods=["POST"])
def api_game_claim():
    data = request.get_json(silent=True) or {}
    token = str(data.get("session_token", "")).strip()
    user_id = str(data.get("user_id", "")).strip()
    if not token or not user_id:
        return jsonify({"ok": False, "error": "session_token and user_id required"}), 400

    with get_db() as conn:
        gs = conn.execute(
            "SELECT * FROM game_sessions WHERE session_token = ? AND user_id = ?",
            (token, user_id),
        ).fetchone()
        if not gs:
            return jsonify({"ok": False, "error": "Game session not found"}), 404
        if gs["claimed"]:
            return jsonify({"ok": False, "error": "Already claimed"}), 400
        if not gs["ad_completed"]:
            return jsonify({"ok": False, "error": "Ad viewing is mandatory before claiming points"}), 400

        conn.execute("UPDATE game_sessions SET claimed = 1 WHERE session_token = ?", (token,))
        ok, msg = credit_pts_tx(
            conn, user_id, "game", f"{gs['game_name']} (Ad Verified)", int(gs["reward_pts"])
        )
        if not ok:
            return jsonify({"ok": False, "error": msg}), 403

        bal = conn.execute("SELECT pts_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()["pts_balance"]

    return jsonify({
        "ok": True,
        "pts_earned": int(gs["reward_pts"]),
        "pts_balance": bal,
    })


# ==============================================================================
# 5) REFERRAL SYSTEM (USER VIEW ONLY; MASTER AFFILIATE IS IN ADMIN PANEL)
# ==============================================================================
@app.route("/api/refer/summary")
def api_refer_summary():
    user_id = str(request.args.get("user_id", "")).strip()
    if not user_id:
        return jsonify({"ok": False, "error": "user_id is required"}), 400

    with get_db() as conn:
        ensure_user(conn, user_id)
        total_refs = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE referred_by = ?", (user_id,)
        ).fetchone()["c"]
        active_refs = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE referred_by = ? AND pts_balance > 0", (user_id,)
        ).fetchone()["c"]

    return jsonify({
        "ok": True,
        "total_referrals": total_refs,
        "active_referrals": active_refs,
        "current_bonus_pts": total_refs * REFERRAL_BONUS_PTS,
        "referral_code": f"REF_{user_id}",
    })


# ==============================================================================
# 6) WALLET CONNECT (4-DIGIT PIN) & WITHDRAW REQUEST
# ==============================================================================
@app.route("/api/wallet/connect", methods=["POST"])
def api_wallet_connect():
    data = request.get_json(silent=True) or {}
    user_id = str(data.get("user_id", "")).strip()
    username = str(data.get("username", "")).strip()
    method = str(data.get("method", "")).strip()
    account_target = str(data.get("account_target", "")).strip()
    pin = str(data.get("pin", "")).strip()

    if not user_id:
        return jsonify({"ok": False, "error": "user_id is required"}), 400
    if method not in {"bKash", "Nagad", "Binance USDT"}:
        return jsonify({"ok": False, "error": "Invalid payment method"}), 400
    if len(account_target) < 5:
        return jsonify({"ok": False, "error": "Valid wallet number or address required"}), 400
    if not (pin.isdigit() and len(pin) == 4):
        return jsonify({"ok": False, "error": "4-digit numeric PIN is required"}), 400

    now_str = iso_now()
    with get_db() as conn:
        user = ensure_user(conn, user_id, username)
        if user["is_blocked"]:
            return jsonify({"ok": False, "error": "Account restricted"}), 403

        conn.execute(
            """
            INSERT INTO wallets (user_id, method, account_target, pin_hash, is_verified, connected_at)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                method = excluded.method,
                account_target = excluded.account_target,
                pin_hash = excluded.pin_hash,
                is_verified = 1,
                connected_at = excluded.connected_at
            """,
            (user_id, method, account_target, hash_pin(pin), now_str),
        )
        conn.execute(
            "UPDATE users SET pin_failed_attempts = 0, pin_locked_until = NULL WHERE user_id = ?",
            (user_id,),
        )

    return jsonify({
        "ok": True,
        "wallet": {
            "connected": True,
            "method": method,
            "masked_target": mask_target(account_target),
            "is_verified": True,
        },
    })


@app.route("/api/withdraw/request", methods=["POST"])
def api_withdraw_request():
    data = request.get_json(silent=True) or {}
    user_id = str(data.get("user_id", "")).strip()
    pin = str(data.get("pin", "")).strip()
    requested_pts = int(data.get("requested_pts", 0))
    method_req = str(data.get("method", "")).strip()

    if not user_id or not (pin.isdigit() and len(pin) == 4):
        return jsonify({"ok": False, "error": "Valid 4-digit PIN is required"}), 400
    if requested_pts <= 0:
        return jsonify({"ok": False, "error": "Invalid PTS amount"}), 400

    now = utc_now()
    now_str = now.isoformat()

    with get_db() as conn:
        user = ensure_user(conn, user_id)
        if user["is_blocked"]:
            return jsonify({"ok": False, "error": "Account restricted"}), 403

        if user["pin_locked_until"] and now < datetime.fromisoformat(user["pin_locked_until"]):
            return jsonify({
                "ok": False,
                "error": "Too many wrong PIN attempts. Try again later.",
                "pin_locked_until": user["pin_locked_until"],
            }), 429

        wallet = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
        if not wallet or not wallet["is_verified"]:
            return jsonify({"ok": False, "error": "Wallet must be connected and verified first"}), 400

        if not hmac.compare_digest(hash_pin(pin), wallet["pin_hash"]):
            attempts = int(user["pin_failed_attempts"]) + 1
            lock_str = (now + timedelta(minutes=PIN_LOCK_MINUTES)).isoformat() if attempts >= MAX_PIN_ATTEMPTS else None
            conn.execute(
                "UPDATE users SET pin_failed_attempts = ?, pin_locked_until = ? WHERE user_id = ?",
                (attempts, lock_str, user_id),
            )
            return jsonify({"ok": False, "error": "Incorrect 4-digit PIN"}), 403

        conn.execute(
            "UPDATE users SET pin_failed_attempts = 0, pin_locked_until = NULL WHERE user_id = ?",
            (user_id,),
        )

        method = method_req if method_req in {"bKash", "Nagad", "Binance USDT"} else wallet["method"]
        min_needed_pts = MIN_WITHDRAW_PTS
        if method == "Binance USDT":
            binance_min_pts = int(round(BINANCE_MIN_USDT * PTS_PER_USDT_INTERNAL))
            min_needed_pts = max(MIN_WITHDRAW_PTS, binance_min_pts)

        if requested_pts < min_needed_pts:
            return jsonify({
                "ok": False,
                "error": f"Minimum {min_needed_pts} PTS required for {method}",
            }), 400

        if int(user["pts_balance"]) < requested_pts:
            return jsonify({"ok": False, "error": "Insufficient PTS balance"}), 400

        fee_pts = int(round(requested_pts * DEFAULT_FEE_RATE))
        if method == "Binance USDT":
            fee_pts += BINANCE_NETWORK_FEE_PTS
        fee_pts = min(fee_pts, requested_pts)
        net_pts = requested_pts - fee_pts

        conn.execute(
            "UPDATE users SET pts_balance = pts_balance - ? WHERE user_id = ?",
            (requested_pts, user_id),
        )
        cur = conn.execute(
            """
            INSERT INTO withdrawals (
                user_id, method, account_target, requested_pts, fee_pts, net_pts, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (user_id, method, wallet["account_target"], requested_pts, fee_pts, net_pts, now_str),
        )
        wid = cur.lastrowid
        new_bal = conn.execute("SELECT pts_balance FROM users WHERE user_id = ?", (user_id,)).fetchone()["pts_balance"]

    return jsonify({
        "ok": True,
        "withdraw_id": wid,
        "method": method,
        "requested_pts": requested_pts,
        "fee_pts": fee_pts,
        "net_pts": net_pts,
        "status": "pending",
        "pts_balance": new_bal,
    })


# ==============================================================================
# 7) 3D ADMIN PANEL API & "নোট খাতা" LEDGER
# ==============================================================================
@app.route("/api/admin/overview")
@admin_required
def api_admin_overview():
    with get_db() as conn:
        total_users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        active_users = conn.execute("SELECT COUNT(*) AS c FROM users WHERE pts_balance > 0").fetchone()["c"]
        total_circulating_pts = conn.execute(
            "SELECT COALESCE(SUM(pts_balance), 0) AS s FROM users"
        ).fetchone()["s"]

        users_list = conn.execute(
            """
            SELECT user_id, username, pts_balance, referred_by, is_blocked, joined_at, last_active_at
            FROM users ORDER BY last_active_at DESC LIMIT 100
            """
        ).fetchall()

        live_feed = conn.execute(
            """
            SELECT e.id, e.user_id, u.username, e.source, e.detail, e.pts_earned, e.created_at
            FROM earning_logs e
            LEFT JOIN users u ON u.user_id = e.user_id
            ORDER BY e.id DESC LIMIT 80
            """
        ).fetchall()

        wallets_list = conn.execute(
            """
            SELECT w.user_id, u.username, w.method, w.account_target, w.is_verified, w.connected_at
            FROM wallets w
            LEFT JOIN users u ON u.user_id = w.user_id
            ORDER BY w.connected_at DESC
            """
        ).fetchall()

        withdrawals_list = conn.execute(
            """
            SELECT id, user_id, method, account_target, requested_pts, fee_pts, net_pts,
                   status, admin_note, created_at, processed_at
            FROM withdrawals ORDER BY id DESC LIMIT 100
            """
        ).fetchall()

        master_referrals = conn.execute(
            """
            SELECT user_id, username, pts_balance, joined_at
            FROM users WHERE referred_by = ? ORDER BY joined_at DESC
            """,
            (MASTER_AFFILIATE_CODE,),
        ).fetchall()

        khata_entries = conn.execute(
            "SELECT * FROM note_khata ORDER BY id DESC"
        ).fetchall()

        khata_summary = conn.execute(
            """
            SELECT
                COUNT(DISTINCT CASE WHEN entry_type = 'payout' THEN user_id END) AS paid_users_count,
                COUNT(CASE WHEN entry_type = 'payout' THEN 1 END) AS total_payout_count,
                COALESCE(SUM(CASE WHEN entry_type = 'payout' THEN pts_amount ELSE 0 END), 0) AS total_withdrawn_pts,
                COALESCE(SUM(fee_pts), 0) AS total_fee_pts,
                COALESCE(SUM(actual_payout_bdt), 0.0) AS total_payout_bdt,
                COALESCE(SUM(actual_payout_usdt), 0.0) AS total_payout_usdt,
                COALESCE(SUM(est_ad_revenue), 0.0) AS total_est_ad_revenue
            FROM note_khata
            """
        ).fetchone()

    return jsonify({
        "ok": True,
        "master_affiliate": {
            "code": MASTER_AFFILIATE_CODE,
            "direct_users_count": len(master_referrals),
            "users": [dict(r) for r in master_referrals],
        },
        "stats": {
            "total_users": total_users,
            "active_users": active_users,
            "total_circulating_pts": total_circulating_pts,
        },
        "users": [dict(r) for r in users_list],
        "live_earning_feed": [dict(r) for r in live_feed],
        "wallets": [dict(r) for r in wallets_list],
        "withdrawals": [dict(r) for r in withdrawals_list],
        "note_khata_summary": dict(khata_summary),
        "note_khata_entries": [dict(r) for r in khata_entries],
    })


@app.route("/api/admin/withdraw/<int:withdraw_id>/decide", methods=["POST"])
@admin_required
def api_admin_withdraw_decide(withdraw_id: int):
    data = request.get_json(silent=True) or {}
    decision = str(data.get("decision", "")).strip().lower()
    actual_payout_bdt = float(data.get("actual_payout_bdt", 0.0))
    actual_payout_usdt = float(data.get("actual_payout_usdt", 0.0))
    est_ad_revenue = float(data.get("est_ad_revenue", 0.0))
    note_text = str(data.get("note_text", "")).strip()

    if decision not in {"approve", "reject"}:
        return jsonify({"ok": False, "error": "decision must be 'approve' or 'reject'"}), 400

    now_str = iso_now()
    with get_db() as conn:
        w = conn.execute("SELECT * FROM withdrawals WHERE id = ?", (withdraw_id,)).fetchone()
        if not w:
            return jsonify({"ok": False, "error": "Withdrawal request not found"}), 404
        if w["status"] != "pending":
            return jsonify({"ok": False, "error": f"Already {w['status']}"}), 400

        if decision == "approve":
            conn.execute(
                """
                UPDATE withdrawals
                SET status = 'approved', processed_at = ?, admin_note = ?
                WHERE id = ?
                """,
                (now_str, note_text, withdraw_id),
            )
            conn.execute(
                """
                INSERT INTO note_khata (
                    entry_type, withdraw_id, user_id, pts_amount, fee_pts,
                    actual_payout_bdt, actual_payout_usdt, est_ad_revenue, note_text, created_at
                ) VALUES ('payout', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    withdraw_id,
                    w["user_id"],
                    w["requested_pts"],
                    w["fee_pts"],
                    actual_payout_bdt,
                    actual_payout_usdt,
                    est_ad_revenue,
                    note_text or f"Approved {w['method']} (#{withdraw_id})",
                    now_str,
                ),
            )
        else:
            conn.execute(
                "UPDATE users SET pts_balance = pts_balance + ? WHERE user_id = ?",
                (w["requested_pts"], w["user_id"]),
            )
            conn.execute(
                """
                UPDATE withdrawals
                SET status = 'rejected', processed_at = ?, admin_note = ?
                WHERE id = ?
                """,
                (now_str, note_text, withdraw_id),
            )

    return jsonify({"ok": True, "withdraw_id": withdraw_id, "status": "approved" if decision == "approve" else "rejected"})


@app.route("/api/admin/khata/entry", methods=["POST"])
@admin_required
def api_admin_khata_entry():
    data = request.get_json(silent=True) or {}
    entry_type = str(data.get("entry_type", "ad_revenue")).strip()
    if entry_type not in {"payout", "ad_revenue", "fee_summary", "adjustment"}:
        entry_type = "ad_revenue"

    pts_amount = int(data.get("pts_amount", 0))
    fee_pts = int(data.get("fee_pts", 0))
    actual_payout_bdt = float(data.get("actual_payout_bdt", 0.0))
    actual_payout_usdt = float(data.get("actual_payout_usdt", 0.0))
    est_ad_revenue = float(data.get("est_ad_revenue", 0.0))
    note_text = str(data.get("note_text", "")).strip()

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO note_khata (
                entry_type, withdraw_id, user_id, pts_amount, fee_pts,
                actual_payout_bdt, actual_payout_usdt, est_ad_revenue, note_text, created_at
            ) VALUES (?, NULL, 'ADMIN', ?, ?, ?, ?, ?, ?, ?)
            """,
            (entry_type, pts_amount, fee_pts, actual_payout_bdt, actual_payout_usdt, est_ad_revenue, note_text, iso_now()),
        )

    return jsonify({"ok": True, "message": "নোট খাতায় হিসাব সংরক্ষিত হয়েছে"})


@app.route("/api/admin/user/<user_id>/block", methods=["POST"])
@admin_required
def api_admin_user_block(user_id: str):
    data = request.get_json(silent=True) or {}
    blocked = 1 if bool(data.get("blocked", True)) else 0
    with get_db() as conn:
        ensure_user(conn, user_id)
        conn.execute("UPDATE users SET is_blocked = ? WHERE user_id = ?", (blocked, user_id))
    return jsonify({"ok": True, "user_id": user_id, "is_blocked": bool(blocked)})


# ==============================================================================
# 3D MINI-APP UI (HOME -> TASKS -> MINING -> GAMES -> REFER -> WALLET)
# ==============================================================================
MINI_APP_HTML = """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>TapMint</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: system-ui, -apple-system, sans-serif; }
  body {
    background: radial-gradient(circle at top, #122426 0%, #070d10 75%);
    color: #eef6f5;
    min-height: 100vh;
    padding-bottom: 92px;
  }
  .wrap { max-width: 480px; margin: 0 auto; padding: 16px; }
  .top-bar {
    display: flex; align-items: center; justify-content: space-between;
    background: rgba(19, 34, 38, 0.9); border: 1px solid rgba(110, 231, 183, 0.16);
    border-radius: 18px; padding: 12px 16px; margin-bottom: 14px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.45);
  }
  .brand { font-weight: 800; font-size: 18px; letter-spacing: 0.4px; }
  .pts-pill {
    background: linear-gradient(145deg, #163b34, #0d221e);
    border: 1px solid #34d399; border-radius: 999px;
    padding: 6px 12px; font-weight: 700; font-size: 14px; color: #6ee7b7;
  }
  .card-3d {
    background: linear-gradient(160deg, rgba(24, 42, 47, 0.95), rgba(12, 22, 26, 0.95));
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 20px; padding: 16px; margin-bottom: 14px;
    box-shadow: 0 12px 24px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.08);
  }
  .page { display: none; }
  .page.active { display: block; }
  .btn-3d {
    width: 100%; border: none; border-radius: 14px; padding: 12px 16px;
    font-weight: 700; font-size: 15px; cursor: pointer; color: #051611;
    background: linear-gradient(180deg, #4ade80, #16a34a);
    box-shadow: 0 5px 0 #14532d, 0 10px 18px rgba(0,0,0,0.4);
    transition: transform 0.08s ease;
  }
  .btn-3d:active { transform: translateY(3px); box-shadow: 0 2px 0 #14532d; }
  .btn-3d:disabled { opacity: 0.5; cursor: not-allowed; }
  .grid-5 { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin-bottom: 12px; }
  .sess-box {
    background: #0e1b1f; border: 1px solid rgba(255,255,255,0.1);
    border-radius: 12px; padding: 8px 4px; text-align: center; font-size: 11px; cursor: pointer;
  }
  .sess-box.active-s { border-color: #34d399; box-shadow: 0 0 12px rgba(52,211,153,0.25); }
  .task-item {
    display: flex; align-items: center; justify-content: space-between;
    background: #0d191d; border: 1px solid rgba(255,255,255,0.07);
    border-radius: 14px; padding: 10px 12px; margin-bottom: 8px;
  }
  .small-btn {
    background: #22c55e; color: #051611; border: none; border-radius: 10px;
    padding: 8px 12px; font-weight: 700; font-size: 12px; cursor: pointer;
  }
  .mining-leaf-3d {
    width: 124px; height: 124px; margin: 14px auto; border-radius: 50%;
    background: radial-gradient(circle at 30% 30%, #fef08a, #eab308 45%, #0f766e 100%);
    border: 4px solid #facc15;
    box-shadow: 0 12px 28px rgba(234, 179, 8, 0.35), inset 0 4px 12px rgba(255,255,255,0.45);
    display: flex; align-items: center; justify-content: center;
  }
  .leaf-shape {
    width: 58px; height: 74px;
    background: linear-gradient(135deg, #6ee7b7, #10b981);
    border-radius: 0 70% 0 70%;
    transform: rotate(-18deg);
    box-shadow: inset 0 0 10px rgba(255,255,255,0.5);
  }
  .input-box {
    width: 100%; background: #0a1417; border: 1px solid rgba(255,255,255,0.14);
    color: #fff; border-radius: 12px; padding: 10px 12px; margin-bottom: 10px; font-size: 14px;
  }
  .method-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 10px; }
  .method-btn {
    background: #0d191d; color: #cbd5e1; border: 1px solid rgba(255,255,255,0.12);
    border-radius: 12px; padding: 9px 6px; font-weight: 700; font-size: 12px; cursor: pointer;
  }
  .method-btn.selected { background: #14532d; border-color: #4ade80; color: #fff; }
  .bottom-nav-3d {
    position: fixed; bottom: 0; left: 0; right: 0;
    background: rgba(9, 17, 20, 0.96); backdrop-filter: blur(12px);
    border-top: 1px solid rgba(255,255,255,0.1);
    padding: 8px 10px 12px; z-index: 50;
  }
  .nav-inner {
    max-width: 480px; margin: 0 auto;
    display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px;
  }
  .nav-tile-3d {
    background: linear-gradient(180deg, #1b2d33, #101c20);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 12px; padding: 7px 2px; text-align: center;
    cursor: pointer; color: #94a3b8; font-size: 10px; font-weight: 700;
    box-shadow: 0 4px 0 #070d10; transition: all 0.1s ease;
  }
  .nav-tile-3d.active-nav {
    background: linear-gradient(180deg, #34d399, #15803d);
    color: #04130e; border-color: #86efac;
    box-shadow: 0 4px 0 #14532d, 0 0 14px rgba(52, 211, 153, 0.45);
    transform: translateY(-2px);
  }
  .nav-ico { display: block; font-size: 15px; margin-bottom: 2px; }
  .toast {
    position: fixed; top: 14px; left: 50%; transform: translateX(-50%);
    background: #132a2e; border: 1px solid #34d399; color: #ecfdf5;
    padding: 10px 16px; border-radius: 12px; font-size: 13px; font-weight: 600;
    z-index: 100; display: none; box-shadow: 0 10px 25px rgba(0,0,0,0.6);
  }
</style>
</head>
<body>
<div class="toast" id="toast"></div>
<div class="wrap">
  <div class="top-bar">
    <div class="brand">TapMint</div>
    <div class="pts-pill"><span id="hdr-pts">0</span> PTS</div>
  </div>

  <!-- 1. HOME PAGE -->
  <section class="page active" id="page-home">
    <div class="card-3d">
      <div style="font-size:13px; color:#94a3b8;">Available Balance</div>
      <div style="font-size:28px; font-weight:800; margin:4px 0;"><span id="home-pts">0</span> PTS</div>
    </div>
    <div class="card-3d" style="text-align:center;">
      <div style="font-weight:700; font-size:16px;">Daily Spin & Win</div>
      <div style="font-size:12px; color:#94a3b8; margin:4px 0 12px;">Max Reward: 15 PTS</div>
      <div id="spin-result-box" style="font-size:15px; font-weight:800; color:#6ee7b7; min-height:24px; margin-bottom:10px;"></div>
      <button class="btn-3d" id="btn-spin" onclick="doSpin()">SPIN NOW</button>
      <div id="spin-timer" style="font-size:12px; color:#94a3b8; margin-top:10px;"></div>
    </div>
  </section>

  <!-- 2. TASKS CENTER -->
  <section class="page" id="page-tasks">
    <div class="card-3d">
      <div style="font-weight:800; font-size:18px; text-align:center; margin-bottom:12px;">Tasks Center</div>
      <div class="grid-5" id="session-tabs"></div>
      <div style="font-size:12px; color:#cbd5e1; text-align:center; margin-bottom:12px;">
        প্রতি সেশনের ২০টি টাস্ক শেষ করলে ২ ঘণ্টার জন্য লক হবে ও পরবর্তী সেশন খুলবে।
      </div>
      <div id="tasks-list"></div>
    </div>
  </section>

  <!-- 3. MINING PAGE -->
  <section class="page" id="page-mining">
    <div class="card-3d" style="text-align:center;">
      <div style="font-weight:800; font-size:18px;">TapMint Mining</div>
      <div style="font-size:12px; color:#94a3b8; margin-top:4px;">প্রতি ২ ঘণ্টা পরপর মাইনিং • দিনে সর্বোচ্চ ৬ বার</div>
      <div class="mining-leaf-3d"><div class="leaf-shape"></div></div>
      <div id="mining-status" style="font-size:14px; font-weight:700; margin-bottom:6px;">Ready to Claim (5-10 PTS)</div>
      <div id="mining-claims-info" style="font-size:12px; color:#94a3b8; margin-bottom:12px;">Today's Claims: 0 / 6</div>
      <button class="btn-3d" id="btn-mining" onclick="doMiningClaim()">CLAIM MINING</button>
    </div>
  </section>

  <!-- 4. GAMES ARENA -->
  <section class="page" id="page-games">
    <div class="card-3d">
      <div style="font-weight:800; font-size:18px; text-align:center; margin-bottom:6px;">Games Arena</div>
      <div style="font-size:12px; color:#94a3b8; text-align:center; margin-bottom:14px;">
        গেম শেষ করার পর পয়েন্ট পেতে অ্যাড দেখা বাধ্যতামূলক
      </div>
      <div id="games-list"></div>
    </div>
  </section>

  <!-- 5. REFER PAGE -->
  <section class="page" id="page-refer">
    <div class="card-3d">
      <div style="font-weight:800; font-size:18px; margin-bottom:12px;">Referral Center</div>
      <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:8px; text-align:center; margin-bottom:14px;">
        <div style="background:#0d191d; padding:10px; border-radius:12px;">
          <div style="font-size:18px; font-weight:800;" id="ref-total">0</div>
          <div style="font-size:11px; color:#94a3b8;">Total Referrals</div>
        </div>
        <div style="background:#0d191d; padding:10px; border-radius:12px;">
          <div style="font-size:18px; font-weight:800;" id="ref-active">0</div>
          <div style="font-size:11px; color:#94a3b8;">Active Referrals</div>
        </div>
        <div style="background:#0d191d; padding:10px; border-radius:12px;">
          <div style="font-size:18px; font-weight:800; color:#6ee7b7;" id="ref-bonus">0</div>
          <div style="font-size:11px; color:#94a3b8;">Current Bonus</div>
        </div>
      </div>
      <input class="input-box" id="ref-link-box" readonly />
      <button class="btn-3d" onclick="copyRefLink()">Copy Referral Link</button>
    </div>
  </section>

  <!-- 6. WALLET & WITHDRAW -->
  <section class="page" id="page-wallet">
    <div class="card-3d">
      <div style="font-weight:800; font-size:18px; margin-bottom:4px;">Wallet & Withdraw</div>
      <div id="withdraw-min-note" style="font-size:12px; color:#94a3b8; margin-bottom:12px;"></div>

      <div style="background:#0d191d; padding:10px 12px; border-radius:12px; margin-bottom:12px; font-size:13px;">
        Status: <strong id="wallet-status-txt" style="color:#fbbf24;">Not Connected</strong>
      </div>

      <div class="method-row">
        <button class="method-btn selected" id="m-bKash" onclick="selectMethod('bKash')">bKash</button>
        <button class="method-btn" id="m-Nagad" onclick="selectMethod('Nagad')">Nagad</button>
        <button class="method-btn" id="m-Binance USDT" onclick="selectMethod('Binance USDT')">Binance USDT</button>
      </div>

      <input class="input-box" id="wallet-target-input" placeholder="Wallet Number / Binance Address" />
      <input class="input-box" id="wallet-pin-input" type="password" maxlength="4" placeholder="Set / Enter 4-Digit PIN" />
      <button class="btn-3d" style="margin-bottom:14px;" onclick="connectWallet()">Save Wallet & 4-Digit PIN</button>

      <hr style="border-color:rgba(255,255,255,0.08); margin:12px 0;" />

      <input class="input-box" id="withdraw-pts-input" type="number" placeholder="Points to Withdraw (PTS)" />
      <input class="input-box" id="withdraw-pin-input" type="password" maxlength="4" placeholder="Enter 4-Digit PIN to Confirm" />
      <div id="binance-extra-note" style="font-size:11px; color:#94a3b8; margin-bottom:10px;"></div>
      <button class="btn-3d" onclick="submitWithdraw()">Send Withdraw Request</button>
    </div>
  </section>
</div>

<!-- 3D BOTTOM NAVIGATION: Home -> Tasks -> Mining -> Games -> Refer -> Wallet -->
<nav class="bottom-nav-3d">
  <div class="nav-inner">
    <div class="nav-tile-3d active-nav" id="nav-home" onclick="switchPage('home')"><span class="nav-ico">🏠</span>Home</div>
    <div class="nav-tile-3d" id="nav-tasks" onclick="switchPage('tasks')"><span class="nav-ico">📋</span>Tasks</div>
    <div class="nav-tile-3d" id="nav-mining" onclick="switchPage('mining')"><span class="nav-ico">🌿</span>Mining</div>
    <div class="nav-tile-3d" id="nav-games" onclick="switchPage('games')"><span class="nav-ico">🎮</span>Games</div>
    <div class="nav-tile-3d" id="nav-refer" onclick="switchPage('refer')"><span class="nav-ico">👥</span>Refer</div>
    <div class="nav-tile-3d" id="nav-wallet" onclick="switchPage('wallet')"><span class="nav-ico">👛</span>Wallet</div>
  </div>
</nav>

<script>
const params = new URLSearchParams(window.location.search);
const USER_ID = params.get("user_id") || "demo_user_101";
const USERNAME = params.get("username") || "TapMintUser";
const REF_CODE = params.get("ref") || "";

let STATE = null;
let ACTIVE_SESSION = 1;
let SELECTED_METHOD = "bKash";
const TASK_TIMERS = {};

function showToast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.style.display = "block";
  clearTimeout(window._toastT);
  window._toastT = setTimeout(() => { el.style.display = "none"; }, 2800);
}

function switchPage(pageName) {
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".nav-tile-3d").forEach(n => n.classList.remove("active-nav"));
  document.getElementById("page-" + pageName).classList.add("active");
  document.getElementById("nav-" + pageName).classList.add("active-nav");
}

function selectMethod(m) {
  SELECTED_METHOD = m;
  document.querySelectorAll(".method-btn").forEach(b => b.classList.remove("selected"));
  document.getElementById("m-" + m).classList.add("selected");
  updateWithdrawRulesText();
}

function updateWithdrawRulesText() {
  if (!STATE) return;
  const r = STATE.withdraw_rules;
  document.getElementById("withdraw-min-note").textContent =
    `সর্বনিম্ন ${r.general_min_pts} PTS হলে উইথড্র নিতে পারবেন`;
  if (SELECTED_METHOD === "Binance USDT") {
    document.getElementById("binance-extra-note").textContent =
      `Binance USDT উইথড্রর জন্য সর্বনিম্ন $${r.binance_min_usdt_rule} সমতুল্য (${r.binance_min_pts} PTS) প্রয়োজন এবং বাইনান্স নেটওয়ার্ক ফি প্রযোজ্য।`;
  } else {
    document.getElementById("binance-extra-note").textContent =
      `উইথড্র রিকোয়েস্ট সাবমিট করলে নির্ধারিত প্রসেসিং ফি কেটে নেওয়া হবে।`;
  }
}

function renderAll() {
  if (!STATE) return;
  const pts = STATE.user.pts_balance;
  document.getElementById("hdr-pts").textContent = pts;
  document.getElementById("home-pts").textContent = pts;

  // Spin
  const spUsed = STATE.spin.spins_used_today;
  const spBtn = document.getElementById("btn-spin");
  spBtn.disabled = spUsed >= STATE.spin.max_daily;
  document.getElementById("spin-timer").textContent = STATE.spin.next_spin_at
    ? `Next spin window: ${new Date(STATE.spin.next_spin_at).toLocaleTimeString()}`
    : `${STATE.spin.max_daily - spUsed} Spin Available Today`;

  // Mining
  document.getElementById("mining-claims-info").textContent =
    `Today's Claims: ${STATE.mining.claims_today} / ${STATE.mining.max_daily}`;
  const mBtn = document.getElementById("btn-mining");
  if (STATE.mining.claims_today >= STATE.mining.max_daily) {
    mBtn.disabled = true;
    document.getElementById("mining-status").textContent = "Daily Mining Limit Reached (6/6)";
  } else if (STATE.mining.next_claim_at && new Date() < new Date(STATE.mining.next_claim_at)) {
    mBtn.disabled = true;
    document.getElementById("mining-status").textContent =
      `Cooldown Active (${new Date(STATE.mining.next_claim_at).toLocaleTimeString()})`;
  } else {
    mBtn.disabled = false;
    document.getElementById("mining-status").textContent = "Ready to Claim (5-10 PTS)";
  }

  // Tasks
  renderSessionTabs();
  renderTasksList();

  // Games
  renderGamesList();

  // Refer
  document.getElementById("ref-total").textContent = STATE.referral.total_referrals;
  document.getElementById("ref-active").textContent = STATE.referral.active_referrals;
  document.getElementById("ref-bonus").textContent = STATE.referral.current_bonus_pts;
  const baseUrl = window.location.origin + window.location.pathname;
  document.getElementById("ref-link-box").value = `${baseUrl}?ref=${encodeURIComponent(USER_ID)}`;

  // Wallet
  if (STATE.wallet.connected) {
    document.getElementById("wallet-status-txt").textContent =
      `Connected: ${STATE.wallet.method} (${STATE.wallet.masked_target})`;
    document.getElementById("wallet-status-txt").style.color = "#6ee7b7";
    selectMethod(STATE.wallet.method);
  }
  updateWithdrawRulesText();
}

function renderSessionTabs() {
  const wrap = document.getElementById("session-tabs");
  wrap.innerHTML = "";
  for (const s of STATE.task_sessions) {
    const div = document.createElement("div");
    div.className = "sess-box" + (s.session_num === ACTIVE_SESSION ? " active-s" : "");
    div.innerHTML = `<div>S${s.session_num}</div><div>${s.is_locked ? "🔒 2h" : s.completed_count + "/20"}</div>`;
    div.onclick = () => { ACTIVE_SESSION = s.session_num; renderSessionTabs(); renderTasksList(); };
    wrap.appendChild(div);
  }
}

function renderTasksList() {
  const list = document.getElementById("tasks-list");
  list.innerHTML = "";
  const sObj = STATE.task_sessions.find(x => x.session_num === ACTIVE_SESSION);
  if (sObj && sObj.is_locked) {
    list.innerHTML = `<div style="text-align:center; padding:16px; color:#fbbf24; font-size:13px;">
      Session ${ACTIVE_SESSION} Locked until ${new Date(sObj.locked_until).toLocaleTimeString()}
    </div>`;
    return;
  }
  for (let t = 1; t <= 20; t++) {
    const row = document.createElement("div");
    row.className = "task-item";
    row.innerHTML = `
      <div>
        <div style="font-weight:700; font-size:13px;">Task ${String(t).padStart(2, "0")}</div>
        <div style="font-size:11px; color:#94a3b8;">8-10s Wait Required</div>
      </div>
      <button class="small-btn" id="tbtn-${ACTIVE_SESSION}-${t}" onclick="openAndCompleteTask(${ACTIVE_SESSION}, ${t})">Open Task</button>
    `;
    list.appendChild(row);
  }
}

async function openAndCompleteTask(sessionNum, taskNum) {
  const btn = document.getElementById(`tbtn-${sessionNum}-${taskNum}`);
  btn.disabled = true;
  const openRes = await fetch("/api/task/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER_ID, username: USERNAME, session_num: sessionNum, task_num: taskNum })
  }).then(r => r.json());

  if (!openRes.ok) {
    showToast(openRes.error || "Cannot open task");
    btn.disabled = false;
    return;
  }
  if (openRes.launch_url) {
    window.open(openRes.launch_url, "_blank", "noopener,noreferrer");
  }
  let left = 9;
  btn.textContent = `${left}s`;
  const iv = setInterval(async () => {
    left -= 1;
    if (left > 0) {
      btn.textContent = `${left}s`;
    } else {
      clearInterval(iv);
      btn.textContent = "Claiming...";
      const doneRes = await fetch("/api/task/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: USER_ID, username: USERNAME, session_num: sessionNum, task_num: taskNum })
      }).then(r => r.json());
      if (doneRes.ok) {
        showToast(`+${doneRes.pts_earned} PTS added!`);
        await loadBootstrap();
      } else {
        showToast(doneRes.error || "Task failed");
        btn.disabled = false;
        btn.textContent = "Open Task";
      }
    }
  }, 1000);
}

async function doSpin() {
  const res = await fetch("/api/spin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER_ID, username: USERNAME })
  }).then(r => r.json());
  if (res.ok) {
    document.getElementById("spin-result-box").textContent = `${res.slot} (+${res.pts_earned} PTS)`;
    showToast(`Spin Result: ${res.slot}`);
    await loadBootstrap();
  } else {
    showToast(res.error || "Spin unavailable");
  }
}

async function doMiningClaim() {
  const res = await fetch("/api/mining/claim", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER_ID, username: USERNAME })
  }).then(r => r.json());
  if (res.ok) {
    showToast(`Mining Claimed: +${res.pts_earned} PTS`);
    await loadBootstrap();
  } else {
    showToast(res.error || "Mining unavailable");
  }
}

function renderGamesList() {
  const games = [
    { name: "Tap Surge Combo", target: "Score Target: 50+", pts: 5 },
    { name: "Catch & Dodge 3D", target: "Score Target: 20+", pts: 5 },
    { name: "Number Merge 2048", target: "Target: 512+ Tile", pts: 6 },
    { name: "Neon Snake Arcade", target: "Score Target: 30+", pts: 5 },
  ];
  const box = document.getElementById("games-list");
  box.innerHTML = "";
  for (const g of games) {
    const div = document.createElement("div");
    div.className = "task-item";
    div.innerHTML = `
      <div>
        <div style="font-weight:700; font-size:14px;">${g.name}</div>
        <div style="font-size:11px; color:#94a3b8;">${g.target} • +${g.pts} PTS (Ad Required)</div>
      </div>
      <button class="small-btn" onclick="playAndClaimGame('${g.name}', ${g.pts})">Play & Claim</button>
    `;
    box.appendChild(div);
  }
}

async function playAndClaimGame(gameName, rewardPts) {
  const st = await fetch("/api/game/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER_ID, username: USERNAME, game_name: gameName, reward_pts: rewardPts })
  }).then(r => r.json());
  if (!st.ok) return showToast(st.error);

  showToast("Playing & watching mandatory ad...");
  setTimeout(async () => {
    await fetch("/api/game/ad-complete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: USER_ID, session_token: st.session_token })
    });
    const cl = await fetch("/api/game/claim", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: USER_ID, session_token: st.session_token })
    }).then(r => r.json());
    if (cl.ok) {
      showToast(`+${cl.pts_earned} PTS earned from ${gameName}!`);
      await loadBootstrap();
    } else {
      showToast(cl.error || "Claim failed");
    }
  }, 3200);
}

function copyRefLink() {
  const el = document.getElementById("ref-link-box");
  el.select();
  navigator.clipboard?.writeText(el.value);
  showToast("Referral link copied");
}

async function connectWallet() {
  const target = document.getElementById("wallet-target-input").value.trim();
  const pin = document.getElementById("wallet-pin-input").value.trim();
  const res = await fetch("/api/wallet/connect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: USER_ID, username: USERNAME,
      method: SELECTED_METHOD, account_target: target, pin: pin
    })
  }).then(r => r.json());
  if (res.ok) {
    document.getElementById("wallet-pin-input").value = "";
    showToast("Wallet & 4-digit PIN saved");
    await loadBootstrap();
  } else {
    showToast(res.error || "Failed to connect wallet");
  }
}

async function submitWithdraw() {
  const reqPts = parseInt(document.getElementById("withdraw-pts-input").value || "0", 10);
  const pin = document.getElementById("withdraw-pin-input").value.trim();
  const res = await fetch("/api/withdraw/request", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: USER_ID, requested_pts: reqPts, pin: pin, method: SELECTED_METHOD
    })
  }).then(r => r.json());
  if (res.ok) {
    document.getElementById("withdraw-pin-input").value = "";
    showToast(`Withdraw #${res.withdraw_id} submitted (Fee: ${res.fee_pts} PTS)`);
    await loadBootstrap();
  } else {
    showToast(res.error || "Withdraw failed");
  }
}

async function loadBootstrap() {
  const q = new URLSearchParams({ user_id: USER_ID, username: USERNAME, ref: REF_CODE });
  const res = await fetch("/api/user/bootstrap?" + q.toString()).then(r => r.json());
  if (res.ok) {
    STATE = res;
    renderAll();
  } else {
    showToast(res.error || "Failed to load user state");
  }
}

loadBootstrap();
</script>
</body>
</html>
"""


ADMIN_3D_HTML = """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>TapMint 3D Admin & নোট খাতা</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: system-ui, -apple-system, sans-serif; }
  body { background: #070d12; color: #eef6f7; padding: 18px; }
  .container { max-width: 1120px; margin: 0 auto; }
  .panel-3d {
    background: linear-gradient(155deg, #132229, #0b1318);
    border: 1px solid rgba(52, 211, 153, 0.22);
    border-radius: 18px; padding: 16px; margin-bottom: 16px;
    box-shadow: 0 14px 28px rgba(0,0,0,0.55);
  }
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 16px; }
  .stat-card {
    background: linear-gradient(180deg, #172b33, #0e1a1f);
    border: 1px solid rgba(255,255,255,0.09); border-radius: 16px; padding: 14px;
    box-shadow: 0 6px 0 #05090c;
  }
  .stat-val { font-size: 22px; font-weight: 800; color: #6ee7b7; margin-top: 6px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 10px; }
  th, td { border-bottom: 1px solid rgba(255,255,255,0.08); padding: 8px; text-align: left; }
  th { color: #94a3b8; font-size: 12px; }
  input, select, button {
    background: #091216; color: #fff; border: 1px solid rgba(255,255,255,0.16);
    border-radius: 10px; padding: 8px 10px; font-size: 13px;
  }
  button { background: #16a34a; border: none; font-weight: 700; cursor: pointer; }
  .btn-rej { background: #dc2626; }
  .row-flex { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
</style>
</head>
<body>
<div class="container">
  <div class="panel-3d">
    <h2 style="margin-bottom:10px;">TapMint 3D Admin Panel & নোট খাতা</h2>
    <div class="row-flex">
      <input id="adm-key" type="password" placeholder="Enter Admin Key" style="min-width:240px;" />
      <button onclick="loadAdminData()">Load 3D Panel</button>
      <span id="master-ref-badge" style="color:#fde047; font-weight:700; margin-left:auto;"></span>
    </div>
  </div>

  <div class="stats-grid" id="khata-summary-cards"></div>

  <div class="panel-3d">
    <h3>নোট খাতা — নতুন হিসাব / অ্যাড রেভিনিউ নোট যোগ করুন</h3>
    <div class="row-flex" style="margin-top:10px;">
      <select id="k-type">
        <option value="ad_revenue">Ad Revenue</option>
        <option value="fee_summary">Fee Summary</option>
        <option value="adjustment">Adjustment</option>
      </select>
      <input id="k-pts" type="number" placeholder="PTS Volume" />
      <input id="k-fee" type="number" placeholder="Fee PTS" />
      <input id="k-bdt" type="number" step="0.01" placeholder="Payout BDT" />
      <input id="k-usdt" type="number" step="0.01" placeholder="Payout USDT" />
      <input id="k-ad" type="number" step="0.01" placeholder="Est. Ad Revenue" />
      <input id="k-note" type="text" placeholder="নোট লিখুন..." style="flex:1; min-width:180px;" />
      <button onclick="addKhataEntry()">Save to নোট খাতা</button>
    </div>
    <table>
      <thead>
        <tr><th>ID</th><th>Type</th><th>User</th><th>PTS</th><th>Fee PTS</th><th>BDT</th><th>USDT</th><th>Ad Rev</th><th>Note</th><th>Time</th></tr>
      </thead>
      <tbody id="khata-tbody"></tbody>
    </table>
  </div>

  <div class="panel-3d">
    <h3>Withdraw Requests</h3>
    <table>
      <thead>
        <tr><th>ID</th><th>User</th><th>Method</th><th>Target</th><th>Req PTS</th><th>Fee</th><th>Net</th><th>Status</th><th>Action</th></tr>
      </thead>
      <tbody id="wd-tbody"></tbody>
    </table>
  </div>

  <div class="panel-3d">
    <h3>Live PTS Earning Feed (Spin / Tasks / Mining / Games / Refer)</h3>
    <table>
      <thead>
        <tr><th>ID</th><th>User</th><th>Source</th><th>Detail</th><th>+PTS</th><th>Time</th></tr>
      </thead>
      <tbody id="feed-tbody"></tbody>
    </table>
  </div>
</div>

<script>
function getKey() {
  return document.getElementById("adm-key").value.trim();
}

async function loadAdminData() {
  const key = getKey();
  const res = await fetch("/api/admin/overview", { headers: { "X-Admin-Key": key } }).then(r => r.json());
  if (!res.ok) return alert(res.error || "Unauthorized");

  document.getElementById("master-ref-badge").textContent =
    `Master Affiliate Code: ${res.master_affiliate.code} (${res.master_affiliate.direct_users_count} users)`;

  const ks = res.note_khata_summary;
  document.getElementById("khata-summary-cards").innerHTML = `
    <div class="stat-card"><div>Total Users</div><div class="stat-val">${res.stats.total_users}</div></div>
    <div class="stat-card"><div>Paid Users (নোট খাতা)</div><div class="stat-val">${ks.paid_users_count}</div></div>
    <div class="stat-card"><div>Total Withdrawn PTS</div><div class="stat-val">${ks.total_withdrawn_pts}</div></div>
    <div class="stat-card"><div>Total Fee PTS</div><div class="stat-val">${ks.total_fee_pts}</div></div>
    <div class="stat-card"><div>Est. Ad Revenue</div><div class="stat-val">${Number(ks.total_est_ad_revenue).toFixed(2)}</div></div>
  `;

  document.getElementById("khata-tbody").innerHTML = res.note_khata_entries.map(e => `
    <tr>
      <td>${e.id}</td><td>${e.entry_type}</td><td>${e.user_id || "-"}</td>
      <td>${e.pts_amount}</td><td>${e.fee_pts}</td>
      <td>${Number(e.actual_payout_bdt).toFixed(2)}</td><td>${Number(e.actual_payout_usdt).toFixed(2)}</td>
      <td>${Number(e.est_ad_revenue).toFixed(2)}</td><td>${e.note_text || ""}</td><td>${e.created_at}</td>
    </tr>
  `).join("");

  document.getElementById("wd-tbody").innerHTML = res.withdrawals.map(w => `
    <tr>
      <td>${w.id}</td><td>${w.user_id}</td><td>${w.method}</td><td>${w.account_target}</td>
      <td>${w.requested_pts}</td><td>${w.fee_pts}</td><td>${w.net_pts}</td><td>${w.status}</td>
      <td>
        ${w.status === "pending" ? `
          <button onclick="decideWithdraw(${w.id}, 'approve')">Approve</button>
          <button class="btn-rej" onclick="decideWithdraw(${w.id}, 'reject')">Reject</button>
        ` : (w.admin_note || "-")}
      </td>
    </tr>
  `).join("");

  document.getElementById("feed-tbody").innerHTML = res.live_earning_feed.map(f => `
    <tr>
      <td>${f.id}</td><td>${f.user_id}</td><td>${f.source}</td>
      <td>${f.detail}</td><td>+${f.pts_earned}</td><td>${f.created_at}</td>
    </tr>
  `).join("");
}

async function decideWithdraw(wid, decision) {
  let bdt = 0, usdt = 0, ad = 0, note = "";
  if (decision === "approve") {
    bdt = parseFloat(prompt("Actual BDT paid (0 if USDT):", "0") || "0");
    usdt = parseFloat(prompt("Actual USDT paid (0 if BDT):", "0") || "0");
    ad = parseFloat(prompt("Estimated Ad Revenue for this batch:", "0") || "0");
    note = prompt("Note খাতা remark:", "") || "";
  } else {
    note = prompt("Reject reason:", "Returned to PTS balance") || "";
  }
  const res = await fetch(`/api/admin/withdraw/${wid}/decide`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Admin-Key": getKey() },
    body: JSON.stringify({
      decision, actual_payout_bdt: bdt, actual_payout_usdt: usdt, est_ad_revenue: ad, note_text: note
    })
  }).then(r => r.json());
  alert(res.ok ? `Status: ${res.status}` : res.error);
  loadAdminData();
}

async function addKhataEntry() {
  const res = await fetch("/api/admin/khata/entry", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Admin-Key": getKey() },
    body: JSON.stringify({
      entry_type: document.getElementById("k-type").value,
      pts_amount: parseInt(document.getElementById("k-pts").value || "0", 10),
      fee_pts: parseInt(document.getElementById("k-fee").value || "0", 10),
      actual_payout_bdt: parseFloat(document.getElementById("k-bdt").value || "0"),
      actual_payout_usdt: parseFloat(document.getElementById("k-usdt").value || "0"),
      est_ad_revenue: parseFloat(document.getElementById("k-ad").value || "0"),
      note_text: document.getElementById("k-note").value.trim()
    })
  }).then(r => r.json());
  alert(res.ok ? res.message : res.error);
  loadAdminData();
}
</script>
</body>
</html>
"""


@app.route("/")
def serve_mini_app():
    return render_template_string(MINI_APP_HTML)


@app.route("/admin")
def serve_admin_panel():
    return render_template_string(ADMIN_3D_HTML)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
