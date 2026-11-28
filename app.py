import hashlib
import hmac
import json
import os
import random
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

from flask import Flask, jsonify, request

app = Flask(__name__)

DB_PATH = os.environ.get("TAPMINT_DB_PATH", "tapmint.db")
ADMIN_KEY = os.environ.get("TAPMINT_ADMIN_KEY", "TAPMINT_ADMIN_99")
MASTER_REF = os.environ.get("TAPMINT_MASTER_REF", "ref_tapmint99bot")
SECRET_SALT = os.environ.get("TAPMINT_SECRET_SALT", "tapmint_secret_salt_2026")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

GENERAL_MIN_WITHDRAW_PTS = 1500
BINANCE_MIN_WITHDRAW_PTS = 15000
BINANCE_PTS_PER_USD = 3000
BINANCE_MIN_USDT_EQUIVALENT = 5
WITHDRAW_FEE_RATE = 0.05
BINANCE_NETWORK_FEE_PTS = 50
DEFAULT_TASK_REWARD_PTS = 1
DEFAULT_GAME_REWARD_PTS = 2
GAME_AD_MIN_WAIT_SEC = 8.0

WEAK_PINS = {
    "0000", "1111", "2222", "3333", "4444", "5555",
    "6666", "7777", "8888", "9999", "1234", "4321",
    "1122", "2211", "1212", "2020", "2024", "2025", "2026",
}

BD_MOBILE_RE = re.compile(r"^01[3-9]\d{8}$")
BEP20_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
TRC20_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
BINANCE_PAY_ID_RE = re.compile(r"^\d{6,12}$")

ADSTERRA_LINKS = [
    "https://asiafilm.org/4/2da793d72cd322b49d8bb9d66fc974e7",
    "https://asiafilm.org/4/3bd5bca9029900a8d0d2bb526ebd7214",
    "https://asiafilm.org/4/224868d40ac462d276354c5696553960",
    "https://asiafilm.org/4/2a16c7d7870cf593884b4976629a6156",
    "https://asiafilm.org/4/4f3af0df8bb071b2232440532691af67",
    "https://asiafilm.org/4/5909d9fd3d02125d0447b6d1702377d7",
    "https://asiafilm.org/4/c75201a3ea80e241a6008c8f503e0855",
    "https://asiafilm.org/4/9b1be208097bfdbce8298db933df0875",
    "https://asiafilm.org/4/5bac8f36e93727dc1e10c13f28ad12ba",
    "https://asiafilm.org/4/948938a94d72df36b23ba9f97ef3bfff",
]

MONETAG_LINKS = [
    "https://uplcm.com/4/12351466",
    "https://uplcm.com/4/12351467",
    "https://uplcm.com/4/12351468",
    "https://uplcm.com/4/12351473",
    "https://uplcm.com/4/12351474",
    "https://uplcm.com/4/12351475",
    "https://uplcm.com/4/12351476",
    "https://uplcm.com/4/12351477",
    "https://uplcm.com/4/12351478",
    "https://uplcm.com/4/12351479",
]

ALL_AD_LINKS = ADSTERRA_LINKS + MONETAG_LINKS

TASK_SCHEDULE_100 = []
for _idx in range(100):
    if _idx % 2 == 0:
        provider = "Adsterra"
        url = ADSTERRA_LINKS[(_idx // 2) % len(ADSTERRA_LINKS)]
    else:
        provider = "Monetag"
        url = MONETAG_LINKS[(_idx // 2) % len(MONETAG_LINKS)]
    TASK_SCHEDULE_100.append({"task_index": _idx + 1, "provider": provider, "url": url})


def get_task_ad_info(session_num: int, task_num: int) -> dict:
    flat_idx = max(0, min(99, (session_num - 1) * 20 + (task_num - 1)))
    return TASK_SCHEDULE_100[flat_idx]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now_utc().isoformat()


def parse_iso(val: str):
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def hash_pin(pin: str) -> str:
    msg = f"{SECRET_SALT}:pin:{pin}".encode("utf-8")
    return hmac.new(SECRET_SALT.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def make_security_hash(user_id: str, action: str, amount: int, ts_iso: str) -> str:
    raw = f"{user_id}|{action}|{amount}|{ts_iso}".encode("utf-8")
    return hmac.new(SECRET_SALT.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def categorize_source(source_type: str) -> str:
    s = (source_type or "").lower()
    if s.startswith("task_"):
        return "task"
    if s.startswith("game"):
        return "game"
    if s.startswith("mining"):
        return "mining"
    if s.startswith("spin"):
        return "spin"
    if "ref" in s:
        return "refer"
    return "other"


def verify_telegram_init_data(init_data: str) -> tuple[bool, dict | None]:
    """
    Validates Telegram Mini App initData using HMAC-SHA256 when TELEGRAM_BOT_TOKEN is set.
    Also parses user object if present.
    """
    if not init_data:
        return False, None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return False, None

    user_obj = None
    raw_user = pairs.get("user")
    if raw_user:
        try:
            user_obj = json.loads(raw_user)
        except Exception:
            user_obj = None

    received_hash = pairs.pop("hash", "")
    if not received_hash:
        return False, user_obj

    auth_date_raw = pairs.get("auth_date")
    if auth_date_raw and auth_date_raw.isdigit():
        auth_dt = datetime.fromtimestamp(int(auth_date_raw), tz=timezone.utc)
        if (now_utc() - auth_dt).total_seconds() > 86400:
            return False, user_obj

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))

    if TELEGRAM_BOT_TOKEN:
        secret_key = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
        calc_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if hmac.compare_digest(calc_hash, received_hash):
            return True, user_obj
        return False, user_obj

    # If TELEGRAM_BOT_TOKEN is not set in env, accept structured Telegram user payload
    if user_obj and str(user_obj.get("id", "")).isdigit():
        return True, user_obj
    return False, user_obj


def resolve_identity(req, data: dict | None = None) -> dict:
    """
    Resolves authenticated identity from Telegram initData / tg_id / user_id.
    """
    payload = data or {}
    init_data = (
        req.headers.get("X-Telegram-Init-Data")
        or req.args.get("init_data")
        or payload.get("init_data")
        or ""
    ).strip()

    tg_id_raw = (
        req.headers.get("X-Telegram-Id")
        or req.args.get("tg_id")
        or payload.get("tg_id")
        or ""
    ).strip()

    req_uid = (
        req.headers.get("X-User-Id")
        or req.args.get("user_id")
        or payload.get("user_id")
        or ""
    ).strip()

    req_name = (
        req.headers.get("X-Username")
        or req.args.get("username")
        or payload.get("username")
        or ""
    ).strip()

    is_tg_sig_valid, tg_user = verify_telegram_init_data(init_data)

    if tg_user and str(tg_user.get("id", "")).isdigit():
        tg_id = str(tg_user["id"])
        first_name = (tg_user.get("first_name") or "").strip()
        last_name = (tg_user.get("last_name") or "").strip()
        tg_handle = (tg_user.get("username") or "").strip()
        full_name = f"{first_name} {last_name}".strip() or (f"@{tg_handle}" if tg_handle else f"TG_{tg_id}")
        return {
            "user_id": f"tg_{tg_id}",
            "telegram_id": tg_id,
            "telegram_username": tg_handle,
            "username": full_name[:64],
            "is_telegram_verified": True if is_tg_sig_valid else True,
            "auth_mode": "telegram_verified" if is_tg_sig_valid else "telegram_webapp",
        }

    if tg_id_raw.isdigit():
        clean_name = req_name or f"TG_{tg_id_raw}"
        return {
            "user_id": f"tg_{tg_id_raw}",
            "telegram_id": tg_id_raw,
            "telegram_username": "",
            "username": clean_name[:64],
            "is_telegram_verified": True,
            "auth_mode": "telegram_id",
        }

    if req_uid:
        clean_uid = re.sub(r"[^a-zA-Z0-9_@-]", "", req_uid)[:64] or "user_1001"
        parsed_tg = clean_uid[3:] if clean_uid.startswith("tg_") and clean_uid[3:].isdigit() else ""
        return {
            "user_id": clean_uid,
            "telegram_id": parsed_tg,
            "telegram_username": "",
            "username": (req_name or clean_uid)[:64],
            "is_telegram_verified": bool(parsed_tg),
            "auth_mode": "account_session",
        }

    return {
        "user_id": "user_1001",
        "telegram_id": "",
        "telegram_username": "",
        "username": (req_name or "TapMintUser")[:64],
        "is_telegram_verified": False,
        "auth_mode": "guest_fallback",
    }


def validate_wallet_credentials(method: str, target: str, pin: str) -> tuple[bool, str, str]:
    """
    Strictly validates payment method, account number/address, and 4-digit PIN.
    Returns (is_valid, error_message, normalized_target).
    """
    m = (method or "").strip()
    t = (target or "").strip()
    p = (pin or "").strip()

    if m not in ("bKash", "Nagad", "Binance USDT"):
        return False, "সঠিক পেমেন্ট মেথড নির্বাচন করুন (bKash, Nagad বা Binance USDT)।", ""

    if not p.isdigit() or len(p) != 4:
        return False, "পিন অবশ্যই ৪ সংখ্যার (0–9) হতে হবে।", ""

    if p in WEAK_PINS or len(set(p)) == 1:
        return False, "দুর্বল বা সাধারণ পিন (যেমন 0000, 1111, 1234) গ্রহণযোগ্য নয়। শক্তিশালী ৪ ডিজিটের পিন দিন।", ""

    if m in ("bKash", "Nagad"):
        digits_only = re.sub(r"[\s\-+]", "", t)
        if digits_only.startswith("880") and len(digits_only) == 13:
            digits_only = "0" + digits_only[3:]
        if not BD_MOBILE_RE.match(digits_only):
            return (
                False,
                f"ভ্যালিড {m} নম্বর দিন (১১ ডিজিট, শুরু ০১৩ থেকে ০১৯ এর মধ্যে হতে হবে)।",
                "",
            )
        return True, "", digits_only

    # Binance USDT validation: BEP20 address, TRC20 address, or Binance Pay ID
    if BEP20_RE.match(t):
        return True, "", t.lower()
    if TRC20_RE.match(t):
        return True, "", t
    if BINANCE_PAY_ID_RE.match(t):
        return True, "", t

    return (
        False,
        "ভ্যালিড Binance USDT অ্যাড্রেস (TRC20 'T...' / BEP20 '0x...') অথবা ৬–১২ ডিজিটের Binance Pay ID দিন।",
        "",
    )


def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                telegram_id TEXT DEFAULT '',
                telegram_username TEXT DEFAULT '',
                is_telegram_verified INTEGER NOT NULL DEFAULT 0,
                username TEXT NOT NULL,
                referred_by TEXT DEFAULT '',
                is_master_ref INTEGER DEFAULT 0,
                pts_balance INTEGER NOT NULL DEFAULT 0,
                total_earned_pts INTEGER NOT NULL DEFAULT 0,
                total_withdrawn_pts INTEGER NOT NULL DEFAULT 0,
                ad_revenue_tier3_units INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS site_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                maintenance_mode INTEGER NOT NULL DEFAULT 0,
                allow_new_users INTEGER NOT NULL DEFAULT 1,
                task_reward_pts INTEGER NOT NULL DEFAULT 1,
                game_reward_pts INTEGER NOT NULL DEFAULT 2,
                referral_bonus_pts INTEGER NOT NULL DEFAULT 25,
                announcement_text TEXT NOT NULL DEFAULT 'TapMint Live Rewards Hub Active',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS wallets (
                user_id TEXT PRIMARY KEY,
                method TEXT NOT NULL DEFAULT 'bKash',
                account_target TEXT NOT NULL DEFAULT '',
                pin_hash TEXT NOT NULL DEFAULT '',
                is_connected INTEGER NOT NULL DEFAULT 0,
                is_verified INTEGER NOT NULL DEFAULT 0,
                verified_at TEXT DEFAULT '',
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS earning_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                pts_delta INTEGER NOT NULL,
                ad_tier TEXT NOT NULL DEFAULT 'tier3',
                security_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                session_num INTEGER NOT NULL,
                completed_count INTEGER NOT NULL DEFAULT 0,
                is_locked INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT DEFAULT '',
                UNIQUE(user_id, session_num)
            );

            CREATE TABLE IF NOT EXISTS completed_tasks (
                user_id TEXT NOT NULL,
                session_num INTEGER NOT NULL,
                task_num INTEGER NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY(user_id, session_num, task_num)
            );

            CREATE TABLE IF NOT EXISTS active_task_starts (
                user_id TEXT NOT NULL,
                session_num INTEGER NOT NULL,
                task_num INTEGER NOT NULL,
                opened_at TEXT NOT NULL,
                launch_url TEXT NOT NULL,
                PRIMARY KEY(user_id, session_num, task_num)
            );

            CREATE TABLE IF NOT EXISTS mining_state (
                user_id TEXT PRIMARY KEY,
                day_key TEXT NOT NULL,
                claims_today INTEGER NOT NULL DEFAULT 0,
                last_claim_at TEXT DEFAULT '',
                next_claim_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS game_sessions (
                session_token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                game_name TEXT NOT NULL,
                reward_pts INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                ad_started_at TEXT DEFAULT '',
                ad_verified INTEGER NOT NULL DEFAULT 0,
                ad_verified_at TEXT DEFAULT '',
                claimed INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS spin_state (
                user_id TEXT PRIMARY KEY,
                day_key TEXT NOT NULL,
                spins_used_today INTEGER NOT NULL DEFAULT 0,
                spin_streak_days INTEGER NOT NULL DEFAULT 0,
                last_spin_at TEXT DEFAULT '',
                next_spin_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                method TEXT NOT NULL,
                account_target TEXT NOT NULL,
                requested_pts INTEGER NOT NULL,
                fee_pts INTEGER NOT NULL,
                net_pts INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                security_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                reviewed_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS note_khata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_type TEXT NOT NULL,
                ref_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                method TEXT NOT NULL,
                gross_pts INTEGER NOT NULL,
                fee_pts INTEGER NOT NULL,
                net_pts INTEGER NOT NULL,
                reserve_balance_pts INTEGER NOT NULL,
                note_text TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

        ucols = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "telegram_id" not in ucols:
            conn.execute("ALTER TABLE users ADD COLUMN telegram_id TEXT DEFAULT ''")
        if "telegram_username" not in ucols:
            conn.execute("ALTER TABLE users ADD COLUMN telegram_username TEXT DEFAULT ''")
        if "is_telegram_verified" not in ucols:
            conn.execute("ALTER TABLE users ADD COLUMN is_telegram_verified INTEGER NOT NULL DEFAULT 0")

        wcols = [r["name"] for r in conn.execute("PRAGMA table_info(wallets)").fetchall()]
        if "is_verified" not in wcols:
            conn.execute("ALTER TABLE wallets ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0")
        if "verified_at" not in wcols:
            conn.execute("ALTER TABLE wallets ADD COLUMN verified_at TEXT DEFAULT ''")

        conn.execute(
            """
            INSERT OR IGNORE INTO site_settings (
                id, maintenance_mode, allow_new_users, task_reward_pts,
                game_reward_pts, referral_bonus_pts, announcement_text, updated_at
            ) VALUES (1, 0, 1, ?, ?, 25, 'TapMint Live Rewards Hub Active', ?)
            """,
            (DEFAULT_TASK_REWARD_PTS, DEFAULT_GAME_REWARD_PTS, iso_now()),
        )

        cols = [r["name"] for r in conn.execute("PRAGMA table_info(spin_state)").fetchall()]
        if "spin_streak_days" not in cols:
            conn.execute("ALTER TABLE spin_state ADD COLUMN spin_streak_days INTEGER NOT NULL DEFAULT 0")
        gcols = [r["name"] for r in conn.execute("PRAGMA table_info(game_sessions)").fetchall()]
        if "ad_started_at" not in gcols:
            conn.execute("ALTER TABLE game_sessions ADD COLUMN ad_started_at TEXT DEFAULT ''")
        conn.commit()
    finally:
        conn.close()


def get_site_settings(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT * FROM site_settings WHERE id = 1").fetchone()
    if not row:
        return {
            "maintenance_mode": 0,
            "allow_new_users": 1,
            "task_reward_pts": DEFAULT_TASK_REWARD_PTS,
            "game_reward_pts": DEFAULT_GAME_REWARD_PTS,
            "referral_bonus_pts": 25,
            "announcement_text": "TapMint Live Rewards Hub Active",
        }
    return dict(row)


def get_reserve_balance_pts(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(
            CASE
                WHEN entry_type IN ('tier3_ad_inflow', 'withdraw_fee_inflow') THEN net_pts
                WHEN entry_type = 'withdraw_approved_outflow' THEN -net_pts
                ELSE 0
            END
        ), 0) AS bal
        FROM note_khata
        """
    ).fetchone()
    return int(row["bal"] or 0)


def ensure_user_from_identity(conn: sqlite3.Connection, ident: dict, ref: str = "") -> bool:
    clean_uid = (ident.get("user_id") or "user_1001").strip()[:64]
    tg_id = (ident.get("telegram_id") or "").strip()[:32]
    tg_handle = (ident.get("telegram_username") or "").strip()[:64]
    is_tg_ver = 1 if ident.get("is_telegram_verified") else 0
    clean_name = (ident.get("username") or "TapMintUser").strip()[:64]
    clean_ref = (ref or "").strip()[:64]
    ts = iso_now()
    day_key = now_utc().strftime("%Y-%m-%d")
    settings = get_site_settings(conn)

    existing = conn.execute("SELECT user_id, referred_by FROM users WHERE user_id = ?", (clean_uid,)).fetchone()
    if not existing:
        if int(settings.get("allow_new_users", 1)) == 0:
            return False
        is_master = 1 if clean_ref == MASTER_REF else 0
        ref_val = clean_ref if clean_ref and clean_ref != clean_uid else ""
        conn.execute(
            """
            INSERT INTO users (
                user_id, telegram_id, telegram_username, is_telegram_verified,
                username, referred_by, is_master_ref, pts_balance,
                total_earned_pts, total_withdrawn_pts, ad_revenue_tier3_units,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, ?, ?)
            """,
            (clean_uid, tg_id, tg_handle, is_tg_ver, clean_name, ref_val, is_master, ts, ts),
        )
        if ref_val and ref_val != MASTER_REF:
            parent = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (ref_val,)).fetchone()
            if parent:
                bonus_pts = max(1, int(settings.get("referral_bonus_pts", 25)))
                s_hash = make_security_hash(ref_val, "referral_bonus", bonus_pts, ts)
                conn.execute(
                    "UPDATE users SET pts_balance = pts_balance + ?, total_earned_pts = total_earned_pts + ?, updated_at = ? WHERE user_id = ?",
                    (bonus_pts, bonus_pts, ts, ref_val),
                )
                conn.execute(
                    "INSERT INTO earning_logs (user_id, source_type, pts_delta, ad_tier, security_hash, created_at) VALUES (?, 'referral_bonus', ?, 'tier3', ?, ?)",
                    (ref_val, bonus_pts, s_hash, ts),
                )
    else:
        conn.execute(
            """
            UPDATE users
            SET username = ?,
                telegram_id = CASE WHEN ? != '' THEN ? ELSE telegram_id END,
                telegram_username = CASE WHEN ? != '' THEN ? ELSE telegram_username END,
                is_telegram_verified = CASE WHEN ? = 1 THEN 1 ELSE is_telegram_verified END,
                updated_at = ?
            WHERE user_id = ?
            """,
            (clean_name, tg_id, tg_id, tg_handle, tg_handle, is_tg_ver, ts, clean_uid),
        )

    conn.execute(
        """
        INSERT OR IGNORE INTO wallets (user_id, method, account_target, pin_hash, is_connected, is_verified, verified_at, updated_at)
        VALUES (?, 'bKash', '', '', 0, 0, '', ?)
        """,
        (clean_uid, ts),
    )

    for s_num in range(1, 6):
        conn.execute(
            """
            INSERT OR IGNORE INTO task_sessions (user_id, session_num, completed_count, is_locked, locked_until)
            VALUES (?, ?, 0, 0, '')
            """,
            (clean_uid, s_num),
        )

    conn.execute(
        """
        INSERT OR IGNORE INTO mining_state (user_id, day_key, claims_today, last_claim_at, next_claim_at)
        VALUES (?, ?, 0, '', '')
        """,
        (clean_uid, day_key),
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO spin_state (user_id, day_key, spins_used_today, spin_streak_days, last_spin_at, next_spin_at)
        VALUES (?, ?, 0, 0, '', '')
        """,
        (clean_uid, day_key),
    )

    m_row = conn.execute("SELECT day_key FROM mining_state WHERE user_id = ?", (clean_uid,)).fetchone()
    if m_row and m_row["day_key"] != day_key:
        conn.execute("UPDATE mining_state SET day_key = ?, claims_today = 0 WHERE user_id = ?", (day_key, clean_uid))

    s_row = conn.execute("SELECT day_key, spin_streak_days FROM spin_state WHERE user_id = ?", (clean_uid,)).fetchone()
    if s_row and s_row["day_key"] != day_key:
        prev_dt = parse_iso(s_row["day_key"] + "T00:00:00+00:00")
        cur_dt_mid = parse_iso(day_key + "T00:00:00+00:00")
        streak_val = int(s_row["spin_streak_days"] or 0)
        if prev_dt and cur_dt_mid and (cur_dt_mid - prev_dt).days > 1:
            streak_val = 0
        if streak_val >= 7:
            streak_val = 0
        conn.execute(
            "UPDATE spin_state SET day_key = ?, spins_used_today = 0, spin_streak_days = ? WHERE user_id = ?",
            (day_key, streak_val, clean_uid),
        )

    sess_rows = conn.execute(
        "SELECT id, session_num, is_locked, locked_until FROM task_sessions WHERE user_id = ? AND is_locked = 1",
        (clean_uid,),
    ).fetchall()
    cur_dt = now_utc()
    for sr in sess_rows:
        lu = parse_iso(sr["locked_until"])
        if lu and cur_dt >= lu:
            conn.execute(
                "UPDATE task_sessions SET is_locked = 0, locked_until = '', completed_count = 0 WHERE id = ?",
                (sr["id"],),
            )
            conn.execute(
                "DELETE FROM completed_tasks WHERE user_id = ? AND session_num = ?",
                (clean_uid, int(sr["session_num"])),
            )
    return True


def get_unlocked_session(sessions_rows) -> int:
    for s in sessions_rows:
        if int(s["is_locked"]) == 0:
            return int(s["session_num"])
    return 1


def credit_user_pts(conn: sqlite3.Connection, user_id: str, source_type: str, pts: int, tier3_units: int = 1) -> str:
    ts = iso_now()
    s_hash = make_security_hash(user_id, source_type, pts, ts)
    conn.execute(
        """
        UPDATE users
        SET pts_balance = pts_balance + ?,
            total_earned_pts = total_earned_pts + ?,
            ad_revenue_tier3_units = ad_revenue_tier3_units + ?,
            updated_at = ?
        WHERE user_id = ?
        """,
        (pts, pts, tier3_units, ts, user_id),
    )
    conn.execute(
        """
        INSERT INTO earning_logs (user_id, source_type, pts_delta, ad_tier, security_hash, created_at)
        VALUES (?, ?, ?, 'tier3', ?, ?)
        """,
        (user_id, source_type, pts, s_hash, ts),
    )
    return s_hash


def mask_target(target: str) -> str:
    t = (target or "").strip()
    if not t:
        return "Not Set"
    if len(t) <= 6:
        return t
    return f"{t[:3]}••••{t[-4:]}"


def build_bootstrap(conn: sqlite3.Connection, user_id: str) -> dict:
    u = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    w = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
    m = conn.execute("SELECT * FROM mining_state WHERE user_id = ?", (user_id,)).fetchone()
    sp = conn.execute("SELECT * FROM spin_state WHERE user_id = ?", (user_id,)).fetchone()
    sessions = conn.execute(
        "SELECT session_num, completed_count, is_locked, locked_until FROM task_sessions WHERE user_id = ? ORDER BY session_num ASC",
        (user_id,),
    ).fetchall()
    done_rows = conn.execute(
        "SELECT session_num, task_num FROM completed_tasks WHERE user_id = ?",
        (user_id,),
    ).fetchall()

    done_map = {}
    for dr in done_rows:
        done_map.setdefault(int(dr["session_num"]), []).append(int(dr["task_num"]))

    unlocked_sess = get_unlocked_session(sessions)

    total_refs = conn.execute("SELECT COUNT(*) AS c FROM users WHERE referred_by = ?", (user_id,)).fetchone()["c"]
    active_refs = conn.execute(
        """
        SELECT COUNT(*) AS c FROM users u
        WHERE u.referred_by = ?
          AND (SELECT COUNT(*) FROM completed_tasks ct WHERE ct.user_id = u.user_id) >= 5
        """,
        (user_id,),
    ).fetchone()["c"]
    ref_bonus = conn.execute(
        "SELECT COALESCE(SUM(pts_delta), 0) AS s FROM earning_logs WHERE user_id = ? AND source_type = 'referral_bonus'",
        (user_id,),
    ).fetchone()["s"]

    return {
        "ok": True,
        "user": {
            "user_id": u["user_id"],
            "telegram_id": u["telegram_id"] or "",
            "telegram_username": u["telegram_username"] or "",
            "is_telegram_verified": bool(u["is_telegram_verified"]),
            "username": u["username"],
            "pts_balance": int(u["pts_balance"]),
            "total_earned_pts": int(u["total_earned_pts"]),
        },
        "wallet": {
            "connected": bool(w["is_connected"]),
            "verified": bool(w["is_verified"]),
            "method": w["method"],
            "masked_target": mask_target(w["account_target"]),
        },
        "spin": {
            "max_daily": 1,
            "spins_used_today": int(sp["spins_used_today"]),
            "spin_streak_days": int(sp["spin_streak_days"] or 0),
            "next_spin_at": sp["next_spin_at"] or "",
        },
        "mining": {
            "max_daily": 6,
            "claims_today": int(m["claims_today"]),
            "next_claim_at": m["next_claim_at"] or "",
        },
        "unlocked_session": unlocked_sess,
        "task_sessions": [
            {
                "session_num": int(s["session_num"]),
                "completed_count": int(s["completed_count"]),
                "is_locked": bool(s["is_locked"]),
                "is_unlocked": (int(s["is_locked"]) == 0 and int(s["session_num"]) == unlocked_sess),
                "locked_until": s["locked_until"] or "",
                "completed_tasks": sorted(done_map.get(int(s["session_num"]), [])),
            }
            for s in sessions
        ],
        "referral": {
            "total_referrals": int(total_refs),
            "active_referrals": int(active_refs),
            "current_bonus_pts": int(ref_bonus),
        },
        "withdraw_rules": {
            "general_min_pts": GENERAL_MIN_WITHDRAW_PTS,
            "binance_min_pts": BINANCE_MIN_WITHDRAW_PTS,
            "binance_pts_per_usd": BINANCE_PTS_PER_USD,
            "binance_min_usdt_rule": BINANCE_MIN_USDT_EQUIVALENT,
            "fee_rate": WITHDRAW_FEE_RATE,
            "binance_network_fee_pts": BINANCE_NETWORK_FEE_PTS,
        },
    }


def require_admin(req) -> bool:
    key = (req.headers.get("X-Admin-Key") or req.args.get("admin_key") or "").strip()
    if not key and req.is_json:
        key = str((req.get_json(silent=True) or {}).get("admin_key") or "").strip()
    return bool(key) and hmac.compare_digest(key, ADMIN_KEY)


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "service": "tapmint", "time": iso_now()})


@app.route("/api/user/bootstrap")
def api_bootstrap():
    ref = (request.args.get("ref") or "").strip()
    ident = resolve_identity(request)
    conn = get_conn()
    try:
        settings = get_site_settings(conn)
        if int(settings.get("maintenance_mode", 0)) == 1:
            return jsonify({"ok": False, "error": "Site is under admin maintenance"}), 503
        ok = ensure_user_from_identity(conn, ident, ref)
        if not ok:
            return jsonify({"ok": False, "error": "New user registration paused by admin"}), 403
        conn.commit()
        return jsonify(build_bootstrap(conn, ident["user_id"]))
    finally:
        conn.close()


@app.route("/api/spin", methods=["POST"])
def api_spin():
    data = request.get_json(silent=True) or {}
    ident = resolve_identity(request, data)
    user_id = ident["user_id"]
    conn = get_conn()
    try:
        ensure_user_from_identity(conn, ident)
        sp = conn.execute("SELECT * FROM spin_state WHERE user_id = ?", (user_id,)).fetchone()
        if int(sp["spins_used_today"]) >= 1:
            return jsonify({"ok": False, "error": "Daily spin already used today"}), 400

        outcomes = [
            ("1 PTS", 1, 26),
            ("3 PTS", 3, 22),
            ("4 PTS", 4, 18),
            ("6 PTS", 6, 12),
            ("8 PTS", 8, 7),
            ("10 PTS", 10, 4),
            ("Try Again", 0, 11),
        ]
        labels = [x[0] for x in outcomes]
        pts_vals = [x[1] for x in outcomes]
        weights = [x[2] for x in outcomes]
        idx = random.choices(range(len(outcomes)), weights=weights, k=1)[0]
        slot_label = labels[idx]
        pts_earned = int(pts_vals[idx])

        prev_streak = int(sp["spin_streak_days"] or 0)
        new_streak = 1 if prev_streak >= 7 else prev_streak + 1

        ts = iso_now()
        next_at = (now_utc() + timedelta(hours=24)).isoformat()
        conn.execute(
            """
            UPDATE spin_state
            SET spins_used_today = spins_used_today + 1,
                spin_streak_days = ?,
                last_spin_at = ?,
                next_spin_at = ?
            WHERE user_id = ?
            """,
            (new_streak, ts, next_at, user_id),
        )
        if pts_earned > 0:
            credit_user_pts(conn, user_id, "daily_spin", pts_earned, tier3_units=1)
        conn.commit()
        return jsonify({
            "ok": True,
            "slot": slot_label,
            "slot_index": idx,
            "pts_earned": pts_earned,
            "spin_streak_days": new_streak,
            "next_spin_at": next_at,
        })
    finally:
        conn.close()


@app.route("/api/task/open", methods=["POST"])
def api_task_open():
    data = request.get_json(silent=True) or {}
    ident = resolve_identity(request, data)
    user_id = ident["user_id"]
    s_num = int(data.get("session_num") or 1)
    t_num = int(data.get("task_num") or 1)
    if s_num < 1 or s_num > 5 or t_num < 1 or t_num > 20:
        return jsonify({"ok": False, "error": "Invalid session or task number"}), 400

    conn = get_conn()
    try:
        ensure_user_from_identity(conn, ident)
        sessions = conn.execute(
            "SELECT session_num, completed_count, is_locked, locked_until FROM task_sessions WHERE user_id = ? ORDER BY session_num ASC",
            (user_id,),
        ).fetchall()
        unlocked_sess = get_unlocked_session(sessions)
        sess = next((x for x in sessions if int(x["session_num"]) == s_num), None)
        if not sess or int(sess["is_locked"]) == 1 or s_num != unlocked_sess:
            return jsonify({"ok": False, "error": f"Session {s_num} is currently locked"}), 400

        already = conn.execute(
            "SELECT 1 FROM completed_tasks WHERE user_id = ? AND session_num = ? AND task_num = ?",
            (user_id, s_num, t_num),
        ).fetchone()
        if already:
            return jsonify({"ok": False, "error": "Task already completed"}), 400

        ts = iso_now()
        ad_info = get_task_ad_info(s_num, t_num)
        launch_url = ad_info["url"]
        conn.execute(
            """
            INSERT INTO active_task_starts (user_id, session_num, task_num, opened_at, launch_url)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, session_num, task_num)
            DO UPDATE SET opened_at = excluded.opened_at, launch_url = excluded.launch_url
            """,
            (user_id, s_num, t_num, ts, launch_url),
        )
        conn.commit()
        return jsonify({
            "ok": True,
            "wait_seconds_min": 8,
            "wait_seconds_max": 10,
            "launch_url": launch_url,
            "provider": ad_info["provider"],
        })
    finally:
        conn.close()


@app.route("/api/task/complete", methods=["POST"])
def api_task_complete():
    data = request.get_json(silent=True) or {}
    ident = resolve_identity(request, data)
    user_id = ident["user_id"]
    s_num = int(data.get("session_num") or 1)
    t_num = int(data.get("task_num") or 1)

    conn = get_conn()
    try:
        ensure_user_from_identity(conn, ident)
        settings = get_site_settings(conn)
        reward_pts = max(1, int(settings.get("task_reward_pts", DEFAULT_TASK_REWARD_PTS)))
        sessions = conn.execute(
            "SELECT session_num, completed_count, is_locked, locked_until FROM task_sessions WHERE user_id = ? ORDER BY session_num ASC",
            (user_id,),
        ).fetchall()
        unlocked_sess = get_unlocked_session(sessions)
        sess = next((x for x in sessions if int(x["session_num"]) == s_num), None)
        if not sess or int(sess["is_locked"]) == 1 or s_num != unlocked_sess:
            return jsonify({"ok": False, "error": "Session locked"}), 400

        already = conn.execute(
            "SELECT 1 FROM completed_tasks WHERE user_id = ? AND session_num = ? AND task_num = ?",
            (user_id, s_num, t_num),
        ).fetchone()
        if already:
            return jsonify({"ok": False, "error": "Task already completed"}), 400

        st = conn.execute(
            "SELECT * FROM active_task_starts WHERE user_id = ? AND session_num = ? AND task_num = ?",
            (user_id, s_num, t_num),
        ).fetchone()
        if not st:
            return jsonify({"ok": False, "error": "Open the task first"}), 400

        opened_dt = parse_iso(st["opened_at"])
        elapsed = (now_utc() - opened_dt).total_seconds() if opened_dt else 0
        if elapsed < 8.0:
            return jsonify({"ok": False, "error": f"Wait at least 8-10s ({int(8 - elapsed)}s left)"}), 400

        ts = iso_now()
        conn.execute(
            "DELETE FROM active_task_starts WHERE user_id = ? AND session_num = ? AND task_num = ?",
            (user_id, s_num, t_num),
        )
        conn.execute(
            "INSERT OR IGNORE INTO completed_tasks (user_id, session_num, task_num, completed_at) VALUES (?, ?, ?, ?)",
            (user_id, s_num, t_num, ts),
        )

        new_cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM completed_tasks WHERE user_id = ? AND session_num = ?",
            (user_id, s_num),
        ).fetchone()["c"]

        credit_user_pts(conn, user_id, f"task_s{s_num}_t{t_num}", reward_pts, tier3_units=1)

        session_locked_now = False
        if new_cnt >= 20:
            lock_until = (now_utc() + timedelta(hours=2)).isoformat()
            conn.execute(
                "UPDATE task_sessions SET completed_count = 20, is_locked = 1, locked_until = ? WHERE user_id = ? AND session_num = ?",
                (lock_until, user_id, s_num),
            )
            session_locked_now = True
        else:
            conn.execute(
                "UPDATE task_sessions SET completed_count = ? WHERE user_id = ? AND session_num = ?",
                (new_cnt, user_id, s_num),
            )

        conn.commit()
        return jsonify({
            "ok": True,
            "pts_earned": reward_pts,
            "completed_in_session": int(new_cnt),
            "session_locked": session_locked_now,
        })
    finally:
        conn.close()


@app.route("/api/mining/claim", methods=["POST"])
def api_mining_claim():
    data = request.get_json(silent=True) or {}
    ident = resolve_identity(request, data)
    user_id = ident["user_id"]
    conn = get_conn()
    try:
        ensure_user_from_identity(conn, ident)
        m = conn.execute("SELECT * FROM mining_state WHERE user_id = ?", (user_id,)).fetchone()
        claims_today = int(m["claims_today"])
        if claims_today >= 6:
            return jsonify({"ok": False, "error": "Max 6 mining claims per day reached"}), 400

        next_dt = parse_iso(m["next_claim_at"])
        if next_dt and now_utc() < next_dt:
            return jsonify({"ok": False, "error": "Mining cooldown active (every 2 hours)"}), 400

        pts_earned = random.choices([5, 6, 7, 8, 9, 10], weights=[32, 30, 20, 9, 5, 4], k=1)[0]
        ts = iso_now()
        next_claim_at = (now_utc() + timedelta(hours=2)).isoformat()
        conn.execute(
            "UPDATE mining_state SET claims_today = claims_today + 1, last_claim_at = ?, next_claim_at = ? WHERE user_id = ?",
            (ts, next_claim_at, user_id),
        )
        credit_user_pts(conn, user_id, "mining_claim", pts_earned, tier3_units=1)
        conn.commit()
        return jsonify({
            "ok": True,
            "pts_earned": pts_earned,
            "claims_today": claims_today + 1,
            "next_claim_at": next_claim_at,
        })
    finally:
        conn.close()


@app.route("/api/game/start", methods=["POST"])
def api_game_start():
    data = request.get_json(silent=True) or {}
    ident = resolve_identity(request, data)
    user_id = ident["user_id"]
    game_name = (data.get("game_name") or "Tap Surge Combo").strip()[:64]
    ad_url = random.choice(ALL_AD_LINKS)

    conn = get_conn()
    try:
        ensure_user_from_identity(conn, ident)
        settings = get_site_settings(conn)
        g_pts = max(1, int(settings.get("game_reward_pts", DEFAULT_GAME_REWARD_PTS)))
        token = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO game_sessions (session_token, user_id, game_name, reward_pts, started_at, ad_started_at, ad_verified, claimed)
            VALUES (?, ?, ?, ?, ?, '', 0, 0)
            """,
            (token, user_id, game_name, g_pts, iso_now()),
        )
        conn.commit()
        return jsonify({
            "ok": True,
            "session_token": token,
            "reward_pts": g_pts,
            "ad_required": True,
            "ad_url": ad_url,
            "wait_seconds_min": 8,
            "wait_seconds_max": 10,
        })
    finally:
        conn.close()


@app.route("/api/game/ad-open", methods=["POST"])
def api_game_ad_open():
    data = request.get_json(silent=True) or {}
    ident = resolve_identity(request, data)
    user_id = ident["user_id"]
    token = (data.get("session_token") or "").strip()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM game_sessions WHERE session_token = ? AND user_id = ?",
            (token, user_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Game session not found"}), 404
        ad_start = row["ad_started_at"] or iso_now()
        conn.execute(
            "UPDATE game_sessions SET ad_started_at = ? WHERE session_token = ?",
            (ad_start, token),
        )
        conn.commit()
        return jsonify({"ok": True, "ad_started_at": ad_start, "wait_seconds_min": 8, "wait_seconds_max": 10})
    finally:
        conn.close()


@app.route("/api/game/ad-complete", methods=["POST"])
def api_game_ad_complete():
    data = request.get_json(silent=True) or {}
    ident = resolve_identity(request, data)
    user_id = ident["user_id"]
    token = (data.get("session_token") or "").strip()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM game_sessions WHERE session_token = ? AND user_id = ?",
            (token, user_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Game session not found"}), 404
        ad_start_dt = parse_iso(row["ad_started_at"])
        if not ad_start_dt:
            return jsonify({"ok": False, "error": "Ad not launched yet"}), 400
        elapsed = (now_utc() - ad_start_dt).total_seconds()
        if elapsed < GAME_AD_MIN_WAIT_SEC:
            rem = max(1, int(GAME_AD_MIN_WAIT_SEC - elapsed + 0.99))
            return jsonify({"ok": False, "error": f"অ্যাডে ৮-১০ সেকেন্ড অপেক্ষা করুন ({rem}s বাকি)"}), 400

        conn.execute(
            "UPDATE game_sessions SET ad_verified = 1, ad_verified_at = ? WHERE session_token = ?",
            (iso_now(), token),
        )
        conn.commit()
        return jsonify({"ok": True, "ad_verified": True})
    finally:
        conn.close()


@app.route("/api/game/claim", methods=["POST"])
def api_game_claim():
    data = request.get_json(silent=True) or {}
    ident = resolve_identity(request, data)
    user_id = ident["user_id"]
    token = (data.get("session_token") or "").strip()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM game_sessions WHERE session_token = ? AND user_id = ?",
            (token, user_id),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Game session not found"}), 404
        if int(row["claimed"]) == 1:
            return jsonify({"ok": False, "error": "Reward already claimed"}), 400
        ad_start_dt = parse_iso(row["ad_started_at"])
        if not ad_start_dt:
            return jsonify({"ok": False, "error": "আগে অ্যাড খুলুন ও ৮-১০ সেকেন্ড অপেক্ষা করুন"}), 400
        elapsed = (now_utc() - ad_start_dt).total_seconds()
        if elapsed < GAME_AD_MIN_WAIT_SEC:
            rem = max(1, int(GAME_AD_MIN_WAIT_SEC - elapsed + 0.99))
            return jsonify({"ok": False, "error": f"আরও {rem} সেকেন্ড অপেক্ষা করে ফিরে আসুন"}), 400

        pts_earned = int(row["reward_pts"] or DEFAULT_GAME_REWARD_PTS)
        conn.execute(
            "UPDATE game_sessions SET ad_verified = 1, ad_verified_at = ?, claimed = 1 WHERE session_token = ?",
            (iso_now(), token),
        )
        credit_user_pts(conn, user_id, f"game:{row['game_name']}", pts_earned, tier3_units=1)
        conn.commit()
        return jsonify({"ok": True, "pts_earned": pts_earned})
    finally:
        conn.close()


@app.route("/api/wallet/connect", methods=["POST"])
def api_wallet_connect():
    data = request.get_json(silent=True) or {}
    ident = resolve_identity(request, data)
    user_id = ident["user_id"]
    method = (data.get("method") or "bKash").strip()
    raw_target = (data.get("account_target") or "").strip()
    pin = (data.get("pin") or "").strip()

    is_valid, err_msg, norm_target = validate_wallet_credentials(method, raw_target, pin)
    if not is_valid:
        return jsonify({"ok": False, "error": err_msg}), 400

    conn = get_conn()
    try:
        ensure_user_from_identity(conn, ident)

        dup = conn.execute(
            """
            SELECT user_id FROM wallets
            WHERE LOWER(account_target) = LOWER(?) AND is_connected = 1 AND user_id != ?
            """,
            (norm_target, user_id),
        ).fetchone()
        if dup:
            return jsonify({
                "ok": False,
                "error": "এই ওয়ালেট নম্বর/অ্যাড্রেসটি ইতিমধ্যে অন্য একটি অ্যাকাউন্টে ভেরিফায়েড আছে।"
            }), 409

        ts = iso_now()
        conn.execute(
            """
            UPDATE wallets
            SET method = ?, account_target = ?, pin_hash = ?, is_connected = 1, is_verified = 1, verified_at = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (method, norm_target, hash_pin(pin), ts, ts, user_id),
        )
        conn.commit()
        return jsonify({
            "ok": True,
            "verified": True,
            "method": method,
            "masked_target": mask_target(norm_target),
        })
    finally:
        conn.close()


@app.route("/api/withdraw/request", methods=["POST"])
def api_withdraw_request():
    data = request.get_json(silent=True) or {}
    ident = resolve_identity(request, data)
    user_id = ident["user_id"]
    method = (data.get("method") or "bKash").strip()
    req_pts = int(data.get("requested_pts") or 0)
    pin = (data.get("pin") or "").strip()

    conn = get_conn()
    try:
        ensure_user_from_identity(conn, ident)
        u = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        w = conn.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,)).fetchone()

        if not w or int(w["is_connected"]) != 1 or int(w["is_verified"]) != 1 or not w["pin_hash"]:
            return jsonify({"ok": False, "error": "আগে বৈধ পেমেন্ট ওয়ালেট ও পিন ভেরিফাই করুন।"}), 400
        if not hmac.compare_digest(w["pin_hash"], hash_pin(pin)):
            return jsonify({"ok": False, "error": "ভুল ৪-ডিজিট পিন! সঠিক পিন দিন।"}), 400

        if method != w["method"]:
            return jsonify({
                "ok": False,
                "error": f"আপনার ভেরিফায়েড ওয়ালেট মেথড হলো {w['method']}। {w['method']} নির্বাচন করুন।"
            }), 400

        if method == "Binance USDT":
            min_req = BINANCE_MIN_WITHDRAW_PTS
            if req_pts < min_req:
                return jsonify({
                    "ok": False,
                    "error": f"Binance উইথড্রতে সর্বনিম্ন {min_req:,} PTS (৫ ডলার) প্রয়োজন"
                }), 400
        else:
            min_req = GENERAL_MIN_WITHDRAW_PTS
            if req_pts < min_req:
                return jsonify({
                    "ok": False,
                    "error": f"সর্বনিম্ন {min_req:,} PTS প্রয়োজন"
                }), 400

        if req_pts > int(u["pts_balance"]):
            return jsonify({"ok": False, "error": "Insufficient PTS balance"}), 400

        pct_fee = int(round(req_pts * WITHDRAW_FEE_RATE))
        net_fee = BINANCE_NETWORK_FEE_PTS if method == "Binance USDT" else 0
        total_fee = min(req_pts - 1, pct_fee + net_fee)
        net_pts = req_pts - total_fee
        usd_value = round(req_pts / BINANCE_PTS_PER_USD, 2) if method == "Binance USDT" else 0.0

        ts = iso_now()
        s_hash = make_security_hash(user_id, f"withdraw:{method}", req_pts, ts)
        conn.execute(
            "UPDATE users SET pts_balance = pts_balance - ?, updated_at = ? WHERE user_id = ?",
            (req_pts, ts, user_id),
        )
        cur = conn.execute(
            """
            INSERT INTO withdrawals (
                user_id, method, account_target, requested_pts, fee_pts, net_pts,
                status, security_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (user_id, method, w["account_target"], req_pts, total_fee, net_pts, s_hash, ts),
        )
        wid = cur.lastrowid
        conn.commit()
        return jsonify({
            "ok": True,
            "withdraw_id": wid,
            "requested_pts": req_pts,
            "fee_pts": total_fee,
            "net_pts": net_pts,
            "usd_value": usd_value,
            "status": "pending",
        })
    finally:
        conn.close()


@app.route("/api/admin/overview")
def api_admin_overview():
    if not require_admin(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    conn = get_conn()
    try:
        reserve_pts = get_reserve_balance_pts(conn)
        settings = get_site_settings(conn)

        all_users = conn.execute(
            """
            SELECT u.*, w.method AS wallet_method, w.account_target AS wallet_target,
                   w.is_connected AS wallet_connected, w.is_verified AS wallet_verified,
                   (SELECT COUNT(*) FROM completed_tasks ct WHERE ct.user_id = u.user_id) AS tasks_done
            FROM users u
            LEFT JOIN wallets w ON w.user_id = u.user_id
            ORDER BY u.total_earned_pts DESC, u.pts_balance DESC
            """
        ).fetchall()

        total_users = len(all_users)
        active_cutoff = now_utc() - timedelta(minutes=15)
        active_users_count = 0
        total_earned_pts_all = 0
        total_circulating_pts = 0
        hardworking_users = []
        saved_wallets = []

        for u in all_users:
            upd_dt = parse_iso(u["updated_at"])
            is_online = bool(upd_dt and upd_dt >= active_cutoff)
            if is_online:
                active_users_count += 1
            total_earned_pts_all += int(u["total_earned_pts"] or 0)
            total_circulating_pts += int(u["pts_balance"] or 0)

            hardworking_users.append({
                "user_id": u["user_id"],
                "telegram_id": u["telegram_id"] or "",
                "is_telegram_verified": bool(u["is_telegram_verified"]),
                "username": u["username"],
                "total_earned_pts": int(u["total_earned_pts"] or 0),
                "pts_balance": int(u["pts_balance"] or 0),
                "tasks_done": int(u["tasks_done"] or 0),
                "is_online": is_online,
                "updated_at": u["updated_at"],
            })

            if int(u["wallet_connected"] or 0) == 1 and (u["wallet_target"] or "").strip():
                saved_wallets.append({
                    "user_id": u["user_id"],
                    "telegram_id": u["telegram_id"] or "",
                    "username": u["username"],
                    "method": u["wallet_method"],
                    "account_target": u["wallet_target"],
                    "verified": bool(u["wallet_verified"]),
                    "pts_balance": int(u["pts_balance"] or 0),
                    "updated_at": u["updated_at"],
                })

        offline_users_count = max(0, total_users - active_users_count)

        source_totals = {"task": 0, "game": 0, "mining": 0, "spin": 0, "refer": 0, "other": 0}
        log_rows = conn.execute(
            "SELECT source_type, SUM(pts_delta) AS total_pts FROM earning_logs GROUP BY source_type"
        ).fetchall()
        for lr in log_rows:
            cat = categorize_source(lr["source_type"])
            source_totals[cat] = source_totals.get(cat, 0) + int(lr["total_pts"] or 0)

        live_feed_rows = conn.execute(
            """
            SELECT el.id, el.user_id, COALESCE(u.username, el.user_id) AS username,
                   el.source_type, el.pts_delta, el.created_at
            FROM earning_logs el
            LEFT JOIN users u ON u.user_id = el.user_id
            ORDER BY el.id DESC LIMIT 40
            """
        ).fetchall()
        live_earnings = []
        for lf in live_feed_rows:
            live_earnings.append({
                "id": lf["id"],
                "user_id": lf["user_id"],
                "username": lf["username"],
                "source_type": lf["source_type"],
                "category": categorize_source(lf["source_type"]),
                "pts_delta": int(lf["pts_delta"] or 0),
                "created_at": lf["created_at"],
            })

        master_ref_count = conn.execute("SELECT COUNT(*) AS c FROM users WHERE is_master_ref = 1").fetchone()["c"]
        tier3_units = conn.execute("SELECT COALESCE(SUM(ad_revenue_tier3_units), 0) AS s FROM users").fetchone()["s"]
        pending_w = conn.execute(
            "SELECT * FROM withdrawals WHERE status = 'pending' ORDER BY id DESC"
        ).fetchall()
        ledger = conn.execute(
            "SELECT * FROM note_khata ORDER BY id DESC LIMIT 100"
        ).fetchall()

        base_host = request.host_url.rstrip("/")
        master_affiliate_link = f"{base_host}/?ref={MASTER_REF}"

        return jsonify({
            "ok": True,
            "reserve_balance_pts": reserve_pts,
            "total_users": total_users,
            "active_users": active_users_count,
            "offline_users": offline_users_count,
            "total_earned_pts_all": total_earned_pts_all,
            "total_circulating_pts": total_circulating_pts,
            "source_totals": source_totals,
            "live_earnings": live_earnings,
            "hardworking_users": hardworking_users[:25],
            "saved_wallets": saved_wallets,
            "master_affiliate": {
                "code": MASTER_REF,
                "link": master_affiliate_link,
                "users_count": int(master_ref_count),
            },
            "site_settings": settings,
            "tier3_ad_units": int(tier3_units),
            "pending_withdrawals": [dict(r) for r in pending_w],
            "note_khata": [dict(r) for r in ledger],
        })
    finally:
        conn.close()


@app.route("/api/admin/site-control", methods=["POST"])
def api_admin_site_control():
    if not require_admin(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    conn = get_conn()
    try:
        cur = get_site_settings(conn)
        maint = 1 if int(data.get("maintenance_mode", cur["maintenance_mode"])) else 0
        allow_new = 1 if int(data.get("allow_new_users", cur["allow_new_users"])) else 0
        t_pts = max(1, min(100, int(data.get("task_reward_pts", cur["task_reward_pts"]))))
        g_pts = max(1, min(100, int(data.get("game_reward_pts", cur["game_reward_pts"]))))
        r_pts = max(1, min(1000, int(data.get("referral_bonus_pts", cur["referral_bonus_pts"]))))
        ann = str(data.get("announcement_text", cur["announcement_text"])).strip()[:200] or cur["announcement_text"]

        conn.execute(
            """
            UPDATE site_settings
            SET maintenance_mode = ?, allow_new_users = ?, task_reward_pts = ?,
                game_reward_pts = ?, referral_bonus_pts = ?, announcement_text = ?, updated_at = ?
            WHERE id = 1
            """,
            (maint, allow_new, t_pts, g_pts, r_pts, ann, iso_now()),
        )
        conn.commit()
        return jsonify({"ok": True, "site_settings": get_site_settings(conn)})
    finally:
        conn.close()


@app.route("/api/admin/user-balance", methods=["POST"])
def api_admin_user_balance():
    if not require_admin(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    uid = (data.get("user_id") or "").strip()
    delta = int(data.get("delta_pts") or 0)
    if not uid or delta == 0:
        return jsonify({"ok": False, "error": "Valid user_id and non-zero delta_pts required"}), 400

    conn = get_conn()
    try:
        u = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
        if not u:
            return jsonify({"ok": False, "error": "User not found"}), 404
        new_bal = max(0, int(u["pts_balance"]) + delta)
        earned_add = max(0, delta)
        ts = iso_now()
        conn.execute(
            """
            UPDATE users
            SET pts_balance = ?, total_earned_pts = total_earned_pts + ?, updated_at = ?
            WHERE user_id = ?
            """,
            (new_bal, earned_add, ts, uid),
        )
        conn.execute(
            """
            INSERT INTO earning_logs (user_id, source_type, pts_delta, ad_tier, security_hash, created_at)
            VALUES (?, 'admin_adjust', ?, 'tier3', ?, ?)
            """,
            (uid, delta, make_security_hash(uid, "admin_adjust", delta, ts), ts),
        )
        conn.commit()
        return jsonify({"ok": True, "user_id": uid, "new_balance": new_bal})
    finally:
        conn.close()


@app.route("/api/admin/note-khata/add", methods=["POST"])
def api_admin_khata_add():
    if not require_admin(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    entry_type = (data.get("entry_type") or "tier3_ad_inflow").strip()
    if entry_type not in ("tier3_ad_inflow", "withdraw_fee_inflow", "withdraw_approved_outflow"):
        return jsonify({"ok": False, "error": "Invalid entry type"}), 400

    gross_pts = max(0, int(data.get("gross_pts") or 0))
    fee_pts = max(0, int(data.get("fee_pts") or 0))
    net_pts = max(0, int(data.get("net_pts") or gross_pts))
    user_id = (data.get("user_id") or "ADMIN_LEDGER").strip()
    method = (data.get("method") or "Tier3Ad").strip()
    note_text = (data.get("note_text") or "নোট খাতা এন্ট্রি").strip()[:200]

    conn = get_conn()
    try:
        current_res = get_reserve_balance_pts(conn)
        delta = net_pts if entry_type != "withdraw_approved_outflow" else -net_pts
        new_res = current_res + delta
        ts = iso_now()
        conn.execute(
            """
            INSERT INTO note_khata (
                entry_type, ref_id, user_id, method, gross_pts, fee_pts, net_pts,
                reserve_balance_pts, note_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (entry_type, f"NK-{uuid.uuid4().hex[:8]}", user_id, method, gross_pts, fee_pts, net_pts, new_res, note_text, ts),
        )
        conn.commit()
        return jsonify({"ok": True, "reserve_balance_pts": new_res})
    finally:
        conn.close()


@app.route("/api/admin/withdraw/review", methods=["POST"])
def api_admin_withdraw_review():
    if not require_admin(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    wid = int(data.get("withdraw_id") or 0)
    decision = (data.get("decision") or "").strip().lower()
    if decision not in ("approve", "reject"):
        return jsonify({"ok": False, "error": "Decision must be approve or reject"}), 400

    conn = get_conn()
    try:
        w = conn.execute("SELECT * FROM withdrawals WHERE id = ?", (wid,)).fetchone()
        if not w:
            return jsonify({"ok": False, "error": "Withdraw request not found"}), 404
        if w["status"] != "pending":
            return jsonify({"ok": False, "error": "Already reviewed"}), 400

        ts = iso_now()
        if decision == "reject":
            conn.execute(
                "UPDATE users SET pts_balance = pts_balance + ?, updated_at = ? WHERE user_id = ?",
                (int(w["requested_pts"]), ts, w["user_id"]),
            )
            conn.execute(
                "UPDATE withdrawals SET status = 'rejected', reviewed_at = ? WHERE id = ?",
                (ts, wid),
            )
            conn.commit()
            return jsonify({"ok": True, "withdraw_id": wid, "status": "rejected"})

        conn.execute(
            "UPDATE withdrawals SET status = 'approved', reviewed_at = ? WHERE id = ?",
            (ts, wid),
        )
        conn.execute(
            "UPDATE users SET total_withdrawn_pts = total_withdrawn_pts + ?, updated_at = ? WHERE user_id = ?",
            (int(w["requested_pts"]), ts, w["user_id"]),
        )

        fee_pts = int(w["fee_pts"])
        net_pts = int(w["net_pts"])
        gross_pts = int(w["requested_pts"])

        res_after_fee = get_reserve_balance_pts(conn) + fee_pts
        conn.execute(
            """
            INSERT INTO note_khata (
                entry_type, ref_id, user_id, method, gross_pts, fee_pts, net_pts,
                reserve_balance_pts, note_text, created_at
            ) VALUES ('withdraw_fee_inflow', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (f"WD-{wid}", w["user_id"], w["method"], gross_pts, fee_pts, fee_pts, res_after_fee, f"উইথড্র ফি লগ (#{wid})", ts),
        )

        res_after_out = res_after_fee - net_pts
        conn.execute(
            """
            INSERT INTO note_khata (
                entry_type, ref_id, user_id, method, gross_pts, fee_pts, net_pts,
                reserve_balance_pts, note_text, created_at
            ) VALUES ('withdraw_approved_outflow', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (f"WD-{wid}", w["user_id"], w["method"], gross_pts, fee_pts, net_pts, res_after_out, f"উইথড্র অনুমোদিত পেআউট (#{wid})", ts),
        )
        conn.commit()
        return jsonify({"ok": True, "withdraw_id": wid, "status": "approved", "reserve_balance_pts": res_after_out})
    finally:
        conn.close()


MINI_APP_HTML = """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>TapMint</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  body {
    background: radial-gradient(circle at 50% 4%, #1b383f 0%, #0b1418 54%, #05080b 100%);
    color: #f1f5f9;
    min-height: 100vh;
    padding-bottom: 108px;
  }
  .phone-frame { max-width: 430px; margin: 0 auto; padding: 10px 14px 20px; }
  .tg-top {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 4px 12px; gap: 8px;
  }
  .tg-brand { font-size: 19px; font-weight: 800; color: #f8fafc; display: flex; align-items: center; gap: 6px; }
  .tg-badge {
    width: 18px; height: 18px; border-radius: 50%; background: #38bdf8; color: #052230;
    font-size: 11px; font-weight: 900; display: inline-flex; align-items: center; justify-content: center;
    box-shadow: 0 2px 8px rgba(56, 189, 248, 0.45);
  }
  .tg-sub { font-size: 11px; color: #94a3b8; margin-top: 2px; }
  .acct-pill {
    font-size: 11px; font-weight: 700; color: #a7f3d0;
    background: rgba(16, 185, 129, 0.14); border: 1px solid rgba(52, 211, 153, 0.35);
    padding: 4px 9px; border-radius: 999px; white-space: nowrap;
  }

  .card-3d {
    background: linear-gradient(175deg, rgba(28, 48, 55, 0.96) 0%, rgba(15, 26, 31, 0.98) 55%, rgba(10, 18, 22, 0.99) 100%);
    border: 1px solid rgba(148, 163, 184, 0.2);
    border-bottom: 3px solid rgba(4, 9, 12, 0.9);
    border-radius: 19px;
    padding: 14px;
    margin-bottom: 11px;
    box-shadow: 0 14px 28px rgba(0, 0, 0, 0.58), inset 0 1.5px 0 rgba(255, 255, 255, 0.11);
  }
  .page { display: none; }
  .page.active { display: block; }

  .bal-wrap { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .bal-left { display: flex; align-items: center; gap: 12px; }

  @keyframes coinShine {
    0%, 72% { transform: translateX(-165%) rotate(25deg); opacity: 0; }
    82% { opacity: 0.9; }
    100% { transform: translateX(185%) rotate(25deg); opacity: 0; }
  }
  .pts-coin-3d {
    position: relative;
    width: 54px; height: 54px; border-radius: 50%;
    background: radial-gradient(circle at 28% 20%, #fffbeb 0%, #fde047 26%, #eab308 58%, #9a3412 92%, #451a03 100%);
    border: 2.5px solid #fef08a;
    box-shadow:
      0 9px 20px rgba(245, 158, 11, 0.45),
      0 4px 0 #78350f,
      0 0 18px rgba(250, 204, 21, 0.28),
      inset 0 2px 4px rgba(255, 255, 255, 0.85),
      inset 0 -3px 6px rgba(120, 53, 15, 0.75);
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0; overflow: hidden;
  }
  .pts-coin-3d::after {
    content: "";
    position: absolute; top: -35%; left: -35%; width: 52%; height: 170%;
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.65), transparent);
    animation: coinShine 3.6s infinite;
    pointer-events: none;
  }
  .pts-coin-inner {
    width: 42px; height: 42px; border-radius: 50%;
    background: radial-gradient(circle at 35% 25%, #fbbf24 0%, #d97706 65%, #78350f 100%);
    border: 1.5px dashed rgba(254, 249, 195, 0.75);
    box-shadow: inset 0 2px 5px rgba(0, 0, 0, 0.55);
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    line-height: 1;
  }
  .pts-coin-star {
    font-size: 8px; color: #fef9c3; letter-spacing: 0.5px; margin-bottom: 1px;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.7);
  }
  .pts-coin-txt {
    font-size: 11px; font-weight: 900; color: #fffbeb; letter-spacing: 0.4px;
    text-shadow: 0 1.5px 2px rgba(69, 26, 3, 0.95);
  }
  .pts-coin-3d.sm { width: 42px; height: 42px; }
  .pts-coin-3d.sm .pts-coin-inner { width: 32px; height: 32px; }
  .pts-coin-3d.sm .pts-coin-star { font-size: 7px; }
  .pts-coin-3d.sm .pts-coin-txt { font-size: 9.5px; }

  .muted { color: #94a3b8; font-size: 12px; }
  .pts-big { font-size: 27px; font-weight: 800; color: #ffffff; line-height: 1.15; letter-spacing: -0.3px; }
  .boost-btn {
    background: linear-gradient(180deg, rgba(16, 185, 129, 0.25), rgba(6, 78, 59, 0.45));
    border: 1px solid rgba(52, 211, 153, 0.55);
    border-bottom: 2px solid rgba(4, 120, 87, 0.85);
    color: #34d399; font-weight: 800; font-size: 12px; padding: 6px 11px; border-radius: 11px;
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.35);
  }

  .day-row { display: flex; align-items: center; justify-content: space-between; }
  .dots-row { display: flex; gap: 6px; }
  .dot-c {
    width: 23px; height: 23px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 900;
  }
  .dot-c.ok {
    background: linear-gradient(180deg, #4ade80, #16a34a);
    color: #052e16; border: 1px solid #bbf7d0;
    box-shadow: 0 3px 9px rgba(34, 197, 94, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.5);
  }
  .dot-c.no {
    background: rgba(15, 23, 42, 0.72); color: #475569;
    border: 1px solid rgba(148, 163, 184, 0.2);
    box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.55);
  }

  .spin-head { display: flex; justify-content: space-between; align-items: flex-start; }
  .wheel-stage {
    position: relative; width: 274px; height: 274px;
    margin: 14px auto 12px; display: flex; align-items: center; justify-content: center;
  }
  .pointer-top {
    position: absolute; top: -9px; left: 50%; transform: translateX(-50%); z-index: 12;
    width: 0; height: 0;
    border-left: 13px solid transparent; border-right: 13px solid transparent;
    border-top: 24px solid #facc15;
    filter: drop-shadow(0 4px 6px rgba(0, 0, 0, 0.8));
  }
  .wheel-bezel {
    width: 260px; height: 260px; border-radius: 50%; padding: 8px;
    background: radial-gradient(circle at 30% 22%, #64748b, #1e293b 58%, #090d14 100%);
    border: 2.5px solid rgba(250, 204, 21, 0.72);
    box-shadow: 0 16px 32px rgba(0, 0, 0, 0.78), 0 5px 0 #090d14, 0 0 26px rgba(250, 204, 21, 0.16);
    position: relative;
  }
  .wheel-rotor {
    width: 100%; height: 100%; border-radius: 50%; position: relative;
    transition: transform 2.5s cubic-bezier(0.16, 0.88, 0.22, 1);
    overflow: hidden;
  }
  .wheel-svg { width: 100%; height: 100%; display: block; }
  .spin-hub {
    position: absolute; z-index: 11; width: 70px; height: 70px; border-radius: 50%;
    background: radial-gradient(circle at 32% 26%, #475569, #0f172a 78%);
    border: 3px solid #facc15; color: #ffffff; font-weight: 900; font-size: 12px;
    line-height: 1.15; text-align: center; cursor: pointer;
    box-shadow: 0 8px 18px rgba(0, 0, 0, 0.8), 0 3px 0 #78350f, inset 0 1px 2px rgba(255, 255, 255, 0.35);
  }
  .btn-3d-green {
    width: 100%; border: 1px solid #86efac; border-bottom: 4px solid #15803d;
    border-radius: 15px; padding: 12px 16px;
    background: linear-gradient(180deg, #4ade80 0%, #22c55e 65%, #16a34a 100%);
    color: #052e16; font-weight: 800; font-size: 15px; cursor: pointer;
    box-shadow: 0 9px 22px rgba(34, 197, 94, 0.38), inset 0 1.5px 0 rgba(255, 255, 255, 0.6);
    transition: transform 0.08s ease;
  }
  .btn-3d-green:active { transform: translateY(2px); border-bottom-width: 2px; }
  .btn-3d-green:disabled { opacity: 0.45; cursor: not-allowed; }

  .btn-3d-blue {
    width: 100%; border: 1px solid #7dd3fc; border-bottom: 4px solid #0369a1;
    border-radius: 15px; padding: 12px 14px;
    background: linear-gradient(180deg, #38bdf8 0%, #0284c7 70%, #0369a1 100%);
    color: #f8fafc; font-weight: 800; font-size: 14px; cursor: pointer;
    box-shadow: 0 9px 20px rgba(2, 132, 199, 0.36), inset 0 1.5px 0 rgba(255, 255, 255, 0.45);
    transition: transform 0.08s ease;
  }
  .btn-3d-blue:active { transform: translateY(2px); border-bottom-width: 2px; }

  .home-link-card {
    display: flex; align-items: center; justify-content: space-between;
    background: linear-gradient(175deg, rgba(28, 48, 55, 0.95), rgba(12, 21, 26, 0.99));
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-bottom: 3px solid rgba(5, 10, 14, 0.9);
    border-radius: 17px; padding: 13px 14px; margin-bottom: 10px; cursor: pointer;
    box-shadow: 0 10px 20px rgba(0, 0, 0, 0.48), inset 0 1px 0 rgba(255, 255, 255, 0.08);
  }
  .sq-icon {
    width: 40px; height: 40px; border-radius: 12px;
    background: linear-gradient(180deg, rgba(52, 211, 153, 0.22), rgba(15, 23, 42, 0.85));
    border: 1px solid rgba(52, 211, 153, 0.35);
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.2);
    display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0;
  }

  .sess-5 { display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; margin-bottom: 12px; }
  .sess-pill {
    background: linear-gradient(180deg, rgba(35, 52, 64, 0.94), rgba(19, 30, 38, 0.98));
    border: 1px solid rgba(148, 163, 184, 0.24);
    border-bottom: 4px solid rgba(8, 14, 19, 0.95);
    border-radius: 14px; padding: 8px 3px; text-align: center; cursor: pointer;
    box-shadow: 0 8px 16px rgba(0, 0, 0, 0.55), inset 0 1px 0 rgba(255, 255, 255, 0.12);
  }
  .sess-pill.active {
    border: 1.5px solid #a7f3d0; border-bottom: 4px solid #10b981;
    background: linear-gradient(180deg, #6ee7b7 0%, #34d399 55%, #10b981 100%);
    box-shadow: 0 0 22px rgba(52, 211, 153, 0.55), 0 8px 18px rgba(16, 185, 129, 0.4), inset 0 1.5px 0 rgba(255, 255, 255, 0.7);
  }
  .sess-pill.locked { opacity: 0.72; }
  .sess-n { font-size: 11px; font-weight: 800; color: #e2e8f0; }
  .sess-st { font-size: 10px; color: #94a3b8; margin-top: 3px; line-height: 1.25; }
  .sess-pill.active .sess-n { color: #052e16; font-weight: 900; }
  .sess-pill.active .sess-st { color: #064e3b; font-weight: 800; }

  .row-card-3d {
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
    background: linear-gradient(175deg, rgba(24, 41, 48, 0.96), rgba(12, 21, 26, 0.99));
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-bottom: 3px solid rgba(5, 10, 14, 0.9);
    border-radius: 17px; padding: 12px; margin-bottom: 10px;
    box-shadow: 0 10px 20px rgba(0, 0, 0, 0.48), inset 0 1px 0 rgba(255, 255, 255, 0.08);
  }
  .row-card-3d.done-card {
    border-color: rgba(52, 211, 153, 0.35);
    background: linear-gradient(175deg, rgba(16, 54, 47, 0.65), rgba(11, 21, 25, 0.98));
  }
  .t-badge-ico {
    width: 44px; height: 44px; border-radius: 13px;
    background: linear-gradient(180deg, #1e293b, #0f172a);
    border: 1px solid rgba(148, 163, 184, 0.24);
    box-shadow: 0 5px 12px rgba(0, 0, 0, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.14);
    display: flex; align-items: center; justify-content: center; font-size: 19px; flex-shrink: 0;
  }
  .wait-badge {
    display: inline-block; margin-top: 5px; font-size: 11px; font-weight: 600;
    color: #fbbf24; background: rgba(120, 53, 15, 0.38);
    border: 1px solid rgba(245, 158, 11, 0.36); padding: 3px 8px; border-radius: 8px;
  }
  .done-badge {
    display: inline-block; margin-top: 5px; font-size: 11px; font-weight: 800;
    color: #4ade80; background: rgba(20, 83, 45, 0.45);
    border: 1px solid rgba(74, 222, 128, 0.45); padding: 3px 9px; border-radius: 8px;
  }
  .open-btn-3d {
    background: linear-gradient(180deg, #6ee7b7 0%, #34d399 65%, #10b981 100%);
    color: #052e16; border: 1px solid #a7f3d0; border-bottom: 4px solid #059669;
    border-radius: 13px; padding: 9px 14px; font-weight: 900;
    font-size: 12px; cursor: pointer; white-space: nowrap;
    box-shadow: 0 0 16px rgba(52, 211, 153, 0.35), 0 6px 14px rgba(0, 0, 0, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.65);
  }
  .open-btn-3d:active { transform: translateY(2px); border-bottom-width: 2px; }
  .done-btn-3d {
    background: rgba(22, 101, 52, 0.35); color: #4ade80;
    border: 1px solid rgba(74, 222, 128, 0.5); border-radius: 12px;
    padding: 8px 12px; font-weight: 800; font-size: 12px; white-space: nowrap;
  }
  .alert-box {
    background: rgba(120, 53, 15, 0.26); border: 1px solid rgba(245, 158, 11, 0.38);
    color: #fde68a; border-radius: 14px; padding: 11px 12px; font-size: 12px;
    line-height: 1.45; margin-top: 10px;
    box-shadow: 0 6px 14px rgba(0, 0, 0, 0.35);
  }

  .m-top-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }
  .m-stat {
    background: linear-gradient(175deg, rgba(24, 41, 48, 0.96), rgba(12, 21, 26, 0.99));
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-bottom: 3px solid rgba(5, 10, 14, 0.9);
    border-radius: 15px; padding: 10px 12px; display: flex; align-items: center; gap: 10px;
    box-shadow: 0 8px 18px rgba(0, 0, 0, 0.45);
  }
  .mining-stage-card {
    position: relative;
    background: radial-gradient(circle at 50% 34%, rgba(20, 83, 68, 0.42) 0%, rgba(12, 23, 28, 0.96) 62%, rgba(8, 15, 19, 0.99) 100%);
    border: 1px solid rgba(148, 163, 184, 0.2);
    border-bottom: 3px solid rgba(4, 9, 12, 0.92);
    border-radius: 20px; padding: 16px 14px 15px; margin-bottom: 12px;
    box-shadow: 0 14px 28px rgba(0, 0, 0, 0.62), inset 0 1px 0 rgba(255, 255, 255, 0.1);
    text-align: center; overflow: hidden;
  }
  .coin-stage { position: relative; width: 200px; height: 170px; margin: 0 auto 8px; }
  .sparkle {
    position: absolute; color: #fde047; font-weight: 900;
    text-shadow: 0 0 10px rgba(250, 204, 21, 0.85); pointer-events: none;
  }
  .coin-pedestal {
    position: relative; z-index: 3;
    width: 128px; height: 128px; margin: 2px auto 0; border-radius: 50%;
    background: radial-gradient(circle at 28% 20%, #fef9c3 0%, #facc15 44%, #ca8a04 78%, #713f12 100%);
    border: 3.5px solid #fef08a;
    box-shadow: 0 14px 26px rgba(0, 0, 0, 0.72), 0 4px 0 #713f12, inset 0 2px 6px rgba(255, 255, 255, 0.78);
    display: flex; align-items: center; justify-content: center;
  }
  .coin-leaf {
    width: 96px; height: 96px; border-radius: 50%;
    background: radial-gradient(circle at 32% 26%, #2dd4bf, #0f766e 74%, #064e3b 100%);
    border: 2px solid rgba(153, 246, 228, 0.55);
    display: flex; align-items: center; justify-content: center; font-size: 44px;
    box-shadow: inset 0 3px 10px rgba(0, 0, 0, 0.55);
  }
  .pedestal-disc-top {
    position: relative; z-index: 2;
    width: 162px; height: 34px; margin: -8px auto 0; border-radius: 50%;
    background: radial-gradient(ellipse at center, rgba(45, 212, 191, 0.82) 0%, rgba(13, 148, 136, 0.35) 68%, transparent 100%);
    border: 1.5px solid rgba(153, 246, 228, 0.75);
    box-shadow: 0 0 22px rgba(45, 212, 191, 0.45);
  }
  .pedestal-disc-base {
    position: relative; z-index: 1;
    width: 118px; height: 22px; margin: -12px auto 4px; border-radius: 50%;
    background: linear-gradient(180deg, #1e293b 0%, #090d12 100%);
    border: 1px solid rgba(94, 234, 212, 0.45);
    box-shadow: 0 8px 16px rgba(0, 0, 0, 0.85);
  }
  .active-box {
    background: rgba(8, 15, 19, 0.94); border: 1px solid rgba(148, 163, 184, 0.22);
    border-radius: 16px; padding: 11px 14px; margin-bottom: 10px;
    box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.7);
  }
  .active-lbl { font-size: 11px; font-weight: 800; color: #2dd4bf; letter-spacing: 0.7px; }
  .active-clock { font-size: 28px; font-weight: 800; color: #ffffff; margin-top: 2px; }
  .progress-line { font-size: 12px; color: #cbd5e1; margin-bottom: 11px; font-weight: 600; }
  .m-claim-btn {
    width: 100%; border: 1px solid #a7f3d0; border-bottom: 4px solid #059669;
    border-radius: 15px; padding: 11px 14px;
    background: linear-gradient(180deg, #6ee7b7 0%, #34d399 60%, #10b981 100%);
    color: #052e16; font-weight: 800; cursor: pointer;
    box-shadow: 0 0 20px rgba(52, 211, 153, 0.42), 0 9px 20px rgba(0, 0, 0, 0.5), inset 0 1.5px 0 rgba(255, 255, 255, 0.65);
  }
  .m-claim-btn:disabled { opacity: 0.88; cursor: not-allowed; }
  .m-claim-main { font-size: 14px; font-weight: 900; line-height: 1.2; }
  .m-claim-sub { font-size: 11px; font-weight: 700; opacity: 0.9; margin-top: 2px; }
  .m-note-warm {
    background: linear-gradient(180deg, rgba(66, 53, 33, 0.78), rgba(45, 36, 23, 0.86));
    border: 1px solid rgba(217, 167, 96, 0.32);
    color: #f3e8d2; border-radius: 14px; padding: 11px 12px; font-size: 12px;
    line-height: 1.45; box-shadow: 0 6px 14px rgba(0, 0, 0, 0.38);
  }

  .g-3d-card {
    display: flex; align-items: center; justify-content: space-between; gap: 11px;
    background: linear-gradient(175deg, rgba(31, 50, 58, 0.96) 0%, rgba(15, 26, 31, 0.99) 55%, rgba(10, 17, 21, 1) 100%);
    border: 1px solid rgba(148, 163, 184, 0.22);
    border-bottom: 4px solid rgba(4, 9, 12, 0.95);
    border-radius: 18px; padding: 13px; margin-bottom: 11px;
    box-shadow: 0 12px 24px rgba(0, 0, 0, 0.6), inset 0 1.5px 0 rgba(255, 255, 255, 0.12);
  }
  .g-3d-thumb {
    width: 62px; height: 62px; border-radius: 16px;
    background: linear-gradient(155deg, #2d3e54 0%, #111b24 68%, #070c10 100%);
    border: 1.5px solid rgba(148, 163, 184, 0.32);
    border-bottom: 4px solid #04070a;
    box-shadow: 0 8px 16px rgba(0, 0, 0, 0.65), inset 0 2px 3px rgba(255, 255, 255, 0.18);
    display: flex; align-items: center; justify-content: center; font-size: 28px; flex-shrink: 0;
  }
  .g-play-3d {
    background: linear-gradient(180deg, #6ee7b7 0%, #34d399 62%, #10b981 100%);
    color: #052e16; border: 1px solid #a7f3d0; border-bottom: 4px solid #059669;
    border-radius: 13px; padding: 10px 13px; font-weight: 900;
    font-size: 12px; cursor: pointer; white-space: nowrap;
    box-shadow: 0 0 18px rgba(52, 211, 153, 0.38), 0 7px 16px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.65);
  }
  .g-play-3d:active { transform: translateY(2px); border-bottom-width: 2px; }
  .g-notice-warm {
    background: linear-gradient(180deg, rgba(66, 53, 33, 0.78), rgba(45, 36, 23, 0.86));
    border: 1px solid rgba(217, 167, 96, 0.32);
    color: #f3e8d2; border-radius: 14px; padding: 11px 12px; font-size: 12px;
    line-height: 1.45; margin-top: 8px;
    box-shadow: 0 6px 14px rgba(0, 0, 0, 0.38);
  }

  .ref-stat-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 12px; }
  .ref-stat-card {
    background: linear-gradient(175deg, rgba(28, 46, 54, 0.96), rgba(12, 21, 26, 0.99));
    border: 1px solid rgba(148, 163, 184, 0.2);
    border-bottom: 3px solid rgba(4, 9, 12, 0.92);
    border-radius: 16px; padding: 12px 6px; text-align: center;
    box-shadow: 0 10px 20px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.1);
  }
  .ref-ico-3d {
    width: 34px; height: 34px; margin: 0 auto 7px; border-radius: 10px;
    background: linear-gradient(180deg, rgba(250, 204, 21, 0.18), rgba(15, 23, 42, 0.88));
    border: 1px solid rgba(250, 204, 21, 0.32);
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.16);
    display: flex; align-items: center; justify-content: center; font-size: 16px;
  }
  .ref-link-inp {
    width: 100%; background: rgba(7, 13, 17, 0.95);
    border: 1px solid rgba(148, 163, 184, 0.22);
    color: #e2e8f0; border-radius: 12px; padding: 11px 12px;
    font-size: 12px; margin-bottom: 11px;
    box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.65);
  }
  .ref-btn-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .ref-rules-card {
    background: linear-gradient(175deg, rgba(26, 43, 50, 0.96), rgba(12, 20, 25, 0.99));
    border: 1px solid rgba(148, 163, 184, 0.2);
    border-bottom: 3px solid rgba(4, 9, 12, 0.92);
    border-radius: 18px; padding: 14px;
    box-shadow: 0 12px 24px rgba(0, 0, 0, 0.54), inset 0 1px 0 rgba(255, 255, 255, 0.09);
  }
  .ref-rule-item {
    font-size: 12px; color: #cbd5e1; line-height: 1.5; margin-top: 8px;
  }

  .modal-bg {
    position: fixed; inset: 0; z-index: 80;
    background: rgba(3, 8, 11, 0.92); backdrop-filter: blur(8px);
    display: none; align-items: center; justify-content: center; padding: 14px;
  }
  .modal-bg.open { display: flex; }
  .modal-box {
    width: 100%; max-width: 400px;
    background: linear-gradient(175deg, #1b313a 0%, #0d181d 100%);
    border: 1px solid rgba(148, 163, 184, 0.28); border-bottom: 4px solid #05090c;
    border-radius: 20px; padding: 16px;
    box-shadow: 0 20px 44px rgba(0, 0, 0, 0.85), inset 0 1px 0 rgba(255, 255, 255, 0.14);
  }
  .game-arena-box {
    position: relative; width: 100%; height: 240px; border-radius: 15px;
    background: radial-gradient(circle at 50% 35%, #16323b 0%, #081216 100%);
    border: 1px solid rgba(52, 211, 153, 0.32); overflow: hidden;
    margin: 10px 0 12px; user-select: none; touch-action: manipulation;
  }

  .pin-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 10px 0 6px; }
  .pin-box {
    height: 46px; border-radius: 12px; background: rgba(9, 17, 20, 0.95);
    border: 1px solid rgba(148, 163, 184, 0.25);
    border-bottom: 2px solid rgba(4, 8, 11, 0.9);
    box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.65);
    display: flex; align-items: center; justify-content: center; font-size: 20px; color: #34d399;
    cursor: pointer;
  }
  .pay-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 8px 0 12px; }
  .pay-btn-3d {
    background: linear-gradient(180deg, rgba(35, 52, 64, 0.94), rgba(18, 29, 37, 0.98));
    border: 1px solid rgba(148, 163, 184, 0.24);
    border-bottom: 4px solid rgba(7, 12, 16, 0.95);
    color: #e2e8f0; border-radius: 13px; padding: 10px 6px; font-weight: 700; font-size: 13px; cursor: pointer;
    box-shadow: 0 7px 14px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.12);
  }
  .pay-btn-3d.active {
    background: linear-gradient(180deg, #6ee7b7 0%, #34d399 58%, #10b981 100%);
    color: #052e16; font-weight: 900; border-color: #a7f3d0; border-bottom: 4px solid #059669;
    box-shadow: 0 0 20px rgba(52, 211, 153, 0.48), 0 7px 16px rgba(16, 185, 129, 0.35), inset 0 1.5px 0 rgba(255, 255, 255, 0.7);
  }
  .inp {
    width: 100%; background: rgba(9, 17, 20, 0.95); border: 1px solid rgba(148, 163, 184, 0.22);
    color: #ffffff; border-radius: 12px; padding: 11px 12px; font-size: 14px; margin-bottom: 10px;
    box-shadow: inset 0 2px 5px rgba(0, 0, 0, 0.55);
  }

  .bnav {
    position: fixed; bottom: 0; left: 0; right: 0; z-index: 40;
    background: linear-gradient(180deg, rgba(16, 26, 33, 0.97) 0%, rgba(9, 15, 20, 0.99) 100%);
    backdrop-filter: blur(14px);
    border-top: 1px solid rgba(148, 163, 184, 0.16);
    padding: 8px 8px 11px;
    box-shadow: 0 -10px 26px rgba(0, 0, 0, 0.75);
  }
  .bnav-inner { max-width: 430px; margin: 0 auto; display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px; align-items: end; }
  .bnav-item {
    background: linear-gradient(180deg, rgba(36, 54, 67, 0.92) 0%, rgba(20, 31, 40, 0.98) 100%);
    border: 1px solid rgba(148, 163, 184, 0.24);
    border-bottom: 4px solid rgba(7, 12, 16, 0.95);
    color: #cbd5e1;
    border-radius: 14px;
    padding: 7px 2px 6px;
    cursor: pointer;
    text-align: center;
    font-size: 11px;
    font-weight: 700;
    box-shadow: 0 7px 14px rgba(0, 0, 0, 0.55), inset 0 1px 0 rgba(255, 255, 255, 0.12);
    transition: all 0.14s ease;
  }
  .bnav-item span {
    display: block;
    font-size: 17px;
    margin-bottom: 2px;
    line-height: 1.1;
  }
  .bnav-item.active {
    background: linear-gradient(180deg, #6ee7b7 0%, #34d399 56%, #10b981 100%);
    color: #052e16;
    font-weight: 900;
    border: 1.5px solid #a7f3d0;
    border-bottom: 4px solid #059669;
    transform: translateY(-5px);
    box-shadow:
      0 0 24px rgba(52, 211, 153, 0.65),
      0 10px 20px rgba(16, 185, 129, 0.45),
      inset 0 1.5px 0 rgba(255, 255, 255, 0.75);
  }
  .toast {
    position: fixed; top: 14px; left: 50%; transform: translateX(-50%); z-index: 95;
    background: #132a30; border: 1px solid #34d399; color: #ecfdf5;
    padding: 10px 16px; border-radius: 12px; font-size: 13px; font-weight: 700; display: none;
  }
</style>
</head>
<body>
<div class="toast" id="toast"></div>

<div class="modal-bg" id="game-modal">
  <div class="modal-box">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <div>
        <div style="font-size:17px;font-weight:800;" id="gm-title">Game</div>
        <div style="font-size:12px;color:#34d399;font-weight:700;" id="gm-target">Target: 75+ • Reward: +2 PTS</div>
      </div>
      <button class="pay-btn-3d" style="padding:6px 10px;" onclick="closeGameModal()">✕</button>
    </div>

    <div id="gm-play-stage">
      <div style="display:flex;justify-content:space-between;font-size:12px;color:#cbd5e1;margin-top:8px;">
        <span id="gm-score-lbl">Score: 0</span>
        <span id="gm-time-lbl">Time: 16s</span>
      </div>
      <div class="game-arena-box" id="gm-arena"></div>
      <div id="gm-ctrl-bar" style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:8px;"></div>
      <button class="btn-3d-green" id="gm-action-btn" onclick="handleGameStageButton()">Restart Game</button>
    </div>

    <div id="gm-ad-stage" style="display:none;text-align:center;padding:8px 0;">
      <div style="font-size:12px;font-weight:800;color:#fbbf24;letter-spacing:0.6px;">AUTO AD LAUNCHED • 8–10s WAIT</div>
      <div style="font-size:16px;font-weight:800;margin-top:4px;">টার্গেট সম্পন্ন! অ্যাড খুলেছে — ৮–১০ সেকেন্ড অপেক্ষা করে ফিরে আসুন</div>
      <div style="background:rgba(8,15,19,0.92);border:1px solid rgba(52,211,153,0.38);border-radius:14px;padding:14px;margin:12px 0;">
        <div style="font-size:12px;color:#cbd5e1;margin-bottom:8px;">অ্যাড পপআপ ব্লক হলে নিচের বাটনে চাপুন:</div>
        <a id="gm-ad-link" href="#" target="_blank" rel="noopener noreferrer" onclick="relaunchGameAd()"
           style="display:inline-block;background:rgba(56,189,248,0.2);border:1px solid #38bdf8;color:#7dd3fc;padding:8px 13px;border-radius:10px;font-size:12px;font-weight:700;text-decoration:none;">
          🔗 Open Ad Link Again
        </a>
        <div style="font-size:21px;font-weight:900;color:#4ade80;margin-top:10px;" id="gm-ad-timer">Wait: 9s</div>
        <div style="font-size:11px;color:#94a3b8;margin-top:4px;" id="gm-ad-hint">অ্যাড থেকে ব্যাক আসলে রিওয়ার্ড ক্লেম করতে পারবেন</div>
      </div>
      <button class="btn-3d-green" id="gm-claim-btn" disabled onclick="claimGameReward()">Claim +2 PTS</button>
    </div>
  </div>
</div>

<div class="phone-frame">
  <div class="tg-top">
    <div>
      <div class="tg-brand">TapMint <span class="tg-badge">✓</span></div>
      <div class="tg-sub" id="acct-sub">Checking Telegram Account...</div>
    </div>
    <div style="text-align:right;">
      <div class="acct-pill" id="acct-badge">Auto-Verified</div>
      <div class="muted" style="font-weight:700;margin-top:3px;" id="hdr-pts">0 PTS</div>
    </div>
  </div>

  <section class="page active" id="page-home">
    <div class="card-3d" style="padding:11px 14px;">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
        <div>
          <div style="font-size:13px;font-weight:800;color:#ffffff;" id="prof-name">TapMint Account</div>
          <div class="muted" style="font-size:11px;margin-top:2px;" id="prof-meta">Telegram ID: — • Account: —</div>
        </div>
        <div class="acct-pill" id="prof-ver-pill">✓ Verified</div>
      </div>
    </div>

    <div class="card-3d">
      <div class="bal-wrap">
        <div class="bal-left">
          <div class="pts-coin-3d">
            <div class="pts-coin-inner">
              <div class="pts-coin-star">✦✦✦</div>
              <div class="pts-coin-txt">PTS</div>
            </div>
          </div>
          <div>
            <div class="muted">Available Balance</div>
            <div class="pts-big" id="home-bal">0 PTS</div>
          </div>
        </div>
        <div class="boost-btn">+15% Boost</div>
      </div>
    </div>

    <div class="card-3d" style="padding:11px 14px;">
      <div class="day-row">
        <div style="font-weight:700;font-size:14px;" id="day-streak-lbl">Day 0/7</div>
        <div class="dots-row" id="day-dots"></div>
      </div>
    </div>

    <div class="card-3d" style="text-align:center;">
      <div class="spin-head">
        <div style="text-align:left;">
          <div style="font-size:16px;font-weight:800;">Daily Spin & Win</div>
          <div class="muted" style="margin-top:2px;">ডেইলি স্পিন হুইল • সর্বোচ্চ ১০ PTS</div>
        </div>
        <div style="text-align:right;">
          <div class="muted" style="font-size:11px;">Max Reward:</div>
          <div style="font-size:14px;font-weight:800;color:#fbbf24;">10 PTS</div>
        </div>
      </div>

      <div class="wheel-stage">
        <div class="pointer-top"></div>
        <div class="wheel-bezel">
          <div class="wheel-rotor" id="wheel-rotor">
            <svg class="wheel-svg" viewBox="0 0 240 240">
              <g id="wheel-slices"></g>
              <circle cx="120" cy="120" r="115" fill="none" stroke="rgba(255,255,255,0.22)" stroke-width="2" />
            </svg>
          </div>
        </div>
        <button class="spin-hub" onclick="doSpin()">SPIN<br/>NOW</button>
      </div>

      <div id="spin-msg" style="font-size:13px;font-weight:800;color:#34d399;min-height:18px;margin-bottom:8px;"></div>
      <button class="btn-3d-green" id="spin-btn" onclick="doSpin()">SPIN NOW</button>
      <div id="spin-countdown" style="font-size:12px;font-weight:700;color:#fbbf24;margin-top:9px;min-height:16px;"></div>
      <div id="spin-status" class="muted" style="margin-top:4px;">1 Spin Available Today</div>
    </div>

    <div class="home-link-card" onclick="goPage('mining')">
      <div style="display:flex;align-items:center;gap:12px;">
        <div class="sq-icon">⛏</div>
        <div>
          <div style="font-weight:700;font-size:14px;">Active Mining</div>
          <div class="muted" id="home-m-txt">Ready to claim</div>
        </div>
      </div>
      <div style="color:#64748b;font-size:18px;">›</div>
    </div>

    <div class="home-link-card" onclick="goPage('tasks')">
      <div style="display:flex;align-items:center;gap:12px;">
        <div class="sq-icon">📋</div>
        <div>
          <div style="font-weight:700;font-size:14px;">Daily Task Sessions</div>
          <div class="muted" id="home-t-txt">0/5 Completed</div>
        </div>
      </div>
      <div style="color:#64748b;font-size:18px;">›</div>
    </div>
  </section>

  <section class="page" id="page-tasks">
    <div style="text-align:center;font-size:20px;font-weight:800;margin-bottom:12px;">Tasks Center</div>
    <div class="sess-5" id="sess-5"></div>
    <div style="text-align:center;font-size:12px;color:#cbd5e1;margin-bottom:14px;">
      প্রতি সেশনের ২০টি টাস্ক শেষ করলে ২ ঘণ্টার জন্য লক হবে ও পরবর্তী সেশন খুলবে।
    </div>
    <div id="sess-title" style="font-size:15px;font-weight:800;margin-bottom:10px;">Session 1: 20 Tasks (0/20 Completed)</div>
    <div id="task-rows"></div>
    <div class="alert-box">
      ⚠ সতর্কতা: টাস্ক খোলার পর কমপক্ষে ৮-১০ সেকেন্ড অপেক্ষা করতে হবে, অন্যথায় পয়েন্ট যুক্ত হবে না।
    </div>
  </section>

  <section class="page" id="page-mining">
    <div style="text-align:center;margin-bottom:12px;">
      <div style="font-size:20px;font-weight:800;">TapMint Mining</div>
      <div class="muted" style="margin-top:2px;">প্রতি ২ ঘণ্টা পরপর মাইনিং • দিনে সর্বোচ্চ ৬ বার</div>
    </div>

    <div class="m-top-grid">
      <div class="m-stat">
        <div style="font-size:19px;">📅</div>
        <div>
          <div class="muted" style="font-size:11px;">Today's Claims:</div>
          <div style="font-size:14px;font-weight:800;" id="m-claims">0 / 6</div>
        </div>
      </div>
      <div class="m-stat">
        <div style="font-size:19px;">⏱</div>
        <div>
          <div class="muted" style="font-size:11px;">Mining Rate:</div>
          <div style="font-size:14px;font-weight:800;">~6 PTS / Session</div>
        </div>
      </div>
    </div>

    <div class="mining-stage-card">
      <div class="coin-stage">
        <span class="sparkle" style="top:8px;right:34px;font-size:14px;">✦</span>
        <span class="sparkle" style="top:34px;left:28px;font-size:11px;">✦</span>
        <span class="sparkle" style="bottom:48px;right:24px;font-size:12px;">✦</span>
        <div class="coin-pedestal"><div class="coin-leaf">🌿</div></div>
        <div class="pedestal-disc-top"></div>
        <div class="pedestal-disc-base"></div>
      </div>

      <div class="active-box">
        <div class="active-lbl" id="m-badge">MINING ACTIVE</div>
        <div style="display:flex;align-items:center;justify-content:space-between;margin-top:2px;">
          <div class="active-clock" id="m-clock">00:00:00</div>
          <div style="width:26px;height:26px;border-radius:50%;border:3.5px solid #2dd4bf;border-top-color:transparent;"></div>
        </div>
      </div>

      <div class="progress-line" id="m-progress">Mining Progress: 100% • Earn 5 to 10 PTS each claim</div>

      <button class="m-claim-btn" id="m-btn" onclick="doMining()">
        <div class="m-claim-main" id="m-btn-main">READY TO CLAIM (+7 PTS)</div>
        <div class="m-claim-sub" id="m-btn-sub">Claim available now</div>
      </button>
    </div>

    <div class="m-note-warm">
      🕒 ২ ঘণ্টা পরপর মাইনিং • দিনে সর্বোচ্চ ৬ বার ক্লেম করা যাবে • পয়েন্ট সরাসরি ওয়ালেটে যোগ হবে
    </div>
  </section>

  <section class="page" id="page-games">
    <div style="text-align:center;margin-bottom:14px;">
      <div style="font-size:20px;font-weight:800;">Games Arena</div>
      <div class="muted" style="margin-top:3px;">
        হার্ড গেম চ্যালেঞ্জ শেষ করলে অটোমেটিক অ্যাড খুলবে • ৮–১০ সেকেন্ড পর ফিরে এলে +2 PTS
      </div>
    </div>
    <div id="game-rows"></div>
    <div class="g-notice-warm">
      🎮 টার্গেট পূরণ হলে অটোমেটিক অ্যাড ওপেন হবে; ৮–১০ সেকেন্ড অপেক্ষা করে ব্যাক আসলে রিওয়ার্ড সাকসেস হবে
    </div>
  </section>

  <section class="page" id="page-refer">
    <div style="text-align:center;margin-bottom:14px;">
      <div style="font-size:21px;font-weight:800;">Invite & Earn</div>
      <div class="muted" style="margin-top:3px;">বন্ধুদের আমন্ত্রণ জানান ও লাইফটাইম কমিশন পান</div>
    </div>

    <div class="ref-stat-3">
      <div class="ref-stat-card">
        <div class="ref-ico-3d">👥</div>
        <div style="font-size:11px;color:#cbd5e1;font-weight:600;">Total Referrals</div>
        <div style="font-size:19px;font-weight:800;color:#ffffff;margin-top:2px;" id="ref-cnt">0</div>
        <div style="font-size:10px;color:#64748b;margin-top:2px;">মোট রেফার</div>
      </div>
      <div class="ref-stat-card">
        <div class="ref-ico-3d">🏅</div>
        <div style="font-size:11px;color:#cbd5e1;font-weight:600;">Active Referrals</div>
        <div style="font-size:19px;font-weight:800;color:#ffffff;margin-top:2px;" id="ref-act">0</div>
        <div style="font-size:10px;color:#64748b;margin-top:2px;">৫+ টাস্ক সম্পন্ন</div>
      </div>
      <div class="ref-stat-card">
        <div class="ref-ico-3d">✖</div>
        <div style="font-size:11px;color:#cbd5e1;font-weight:600;">Current Bonus</div>
        <div style="font-size:15px;font-weight:800;color:#4ade80;margin-top:4px;" id="ref-pts">+15% Boost</div>
        <div style="font-size:10px;color:#64748b;margin-top:3px;">টাস্ক বোনাস</div>
      </div>
    </div>

    <div class="card-3d">
      <div style="font-size:14px;font-weight:800;margin-bottom:8px;">3D Referral Link</div>
      <input class="ref-link-inp" id="ref-url" readonly />
      <div class="ref-btn-pair">
        <button class="btn-3d-green" style="padding:11px 10px;font-size:13px;" onclick="copyRef()">📋 Copy Link</button>
        <button class="btn-3d-blue" style="padding:11px 10px;font-size:13px;" onclick="shareTelegram()">✈ Share on Telegram</button>
      </div>
    </div>

    <div class="ref-rules-card">
      <div style="font-size:15px;font-weight:800;color:#ffffff;">নিয়মাবলী & শর্ত</div>
      <div class="ref-rule-item">1. আপনার লিংক বন্ধুদের সাথে শেয়ার করুন।</div>
      <div class="ref-rule-item">2. বন্ধু জয়েন করে কমপক্ষে ৫টি টাস্ক শেষ করলে অ্যাক্টিভ গণ্য হবে।</div>
      <div class="ref-rule-item">3. প্রতিটি অ্যাক্টিভ রেফারেলে +৫% বোনাস (সর্বোচ্চ ৩০%) ও ২য় স্তরের কমিশন।</div>
    </div>
  </section>

  <section class="page" id="page-wallet">
    <div style="margin-bottom:12px;">
      <div style="font-size:20px;font-weight:800;">Wallet & Withdraw</div>
      <div class="muted" style="margin-top:2px;" id="w-sub">সর্বনিম্ন ১,৫০০ PTS হলে উইথড্র নিতে পারবেন • বাইনান্সে ১৫,০০০ PTS ($5)</div>
    </div>

    <div class="card-3d" style="text-align:center;">
      <div class="muted" style="margin-bottom:6px;">Available Balance</div>
      <div style="display:flex;align-items:center;justify-content:center;gap:10px;">
        <div class="pts-coin-3d sm">
          <div class="pts-coin-inner">
            <div class="pts-coin-star">✦✦✦</div>
            <div class="pts-coin-txt">PTS</div>
          </div>
        </div>
        <div style="font-size:26px;font-weight:800;" id="w-bal">0 PTS</div>
      </div>
    </div>

    <div class="card-3d" style="padding:12px 14px;">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
        <div>
          <div style="font-size:13px;font-weight:700;color:#34d399;" id="w-conn">Wallet Not Connected</div>
          <div class="muted" style="font-size:11px;margin-top:2px;" id="w-ver">ভ্যালিড অ্যাকাউন্ট নম্বর/অ্যাড্রেস ও ৪-ডিজিট পিন দিয়ে ভেরিফাই করুন</div>
        </div>
        <button class="pay-btn-3d" style="padding:7px 12px;" onclick="toggleWForm()">Verify Wallet</button>
      </div>
      <div id="w-form" style="display:none;margin-top:12px;padding-top:12px;border-top:1px solid rgba(148, 163, 184, 0.14);">
        <div style="font-size:12px;font-weight:700;color:#cbd5e1;margin-bottom:4px;">Select Valid Payment Method</div>
        <div class="pay-3" style="margin:6px 0 10px;">
          <button type="button" class="pay-btn-3d active" id="wm-bKash" onclick="setPay('bKash')">bKash</button>
          <button type="button" class="pay-btn-3d" id="wm-Nagad" onclick="setPay('Nagad')">Nagad</button>
          <button type="button" class="pay-btn-3d" id="wm-Binance USDT" onclick="setPay('Binance USDT')">Binance USDT</button>
        </div>
        <input class="inp" id="w-acc" placeholder="017XXXXXXXX (১১ ডিজিট বৈধ নম্বর)" />
        <input class="inp" id="w-pin-set" type="password" maxlength="4" inputmode="numeric" placeholder="Set Strong 4-Digit PIN (e.g. 5829)" />
        <div class="muted" style="font-size:11px;margin-bottom:10px;" id="w-rule-hint">
          • bKash/Nagad: ১১ ডিজিট (013–019) • সাধারণ পিন (0000, 1111, 1234) নিষিদ্ধ
        </div>
        <button class="btn-3d-green" onclick="saveW()">Verify & Save Wallet</button>
      </div>
    </div>

    <div class="card-3d" style="text-align:center;">
      <div style="font-size:13px;font-weight:700;">Enter 4-Digit PIN to Confirm Withdraw</div>
      <div class="pin-4" onclick="focusPinInput()">
        <div class="pin-box" id="p0">•</div>
        <div class="pin-box" id="p1">•</div>
        <div class="pin-box" id="p2">•</div>
        <div class="pin-box" id="p3">•</div>
      </div>
      <div class="muted" style="font-size:11px;margin-top:6px;">ওয়ালেট ভেরিফাই করার সময় সেট করা ৪ সংখ্যার পিন দিন।</div>
      <input id="w-pin-confirm" type="password" maxlength="4" inputmode="numeric" oninput="paintPin()"
        style="opacity:0;position:absolute;pointer-events:none;height:1px;width:1px;" />
    </div>

    <div class="card-3d">
      <div style="font-size:13px;font-weight:700;">Payment Method</div>
      <div class="pay-3">
        <button class="pay-btn-3d active" id="pm-bKash" onclick="setPay('bKash')">bKash</button>
        <button class="pay-btn-3d" id="pm-Nagad" onclick="setPay('Nagad')">Nagad</button>
        <button class="pay-btn-3d" id="pm-Binance USDT" onclick="setPay('Binance USDT')">Binance USDT</button>
      </div>

      <div style="font-size:13px;font-weight:700;margin-bottom:6px;" id="w-pts-lbl">Points to Withdraw (Min 1,500)</div>
      <input class="inp" id="w-pts-val" type="number" placeholder="1,500" />
      <div class="muted" style="font-size:11px;line-height:1.45;margin-bottom:12px;" id="w-fee-txt">
        উইথড্র রিকোয়েস্ট সাবমিট করলে নির্ধারিত ফি কেটে নেওয়া হবে।<br/>
        *Binance withdrawals require min 15,000 PTS ($5) & incur standard network fees.
      </div>
      <button class="btn-3d-green" onclick="reqWithdraw()">
        Send Withdraw Request
        <div style="font-size:11px;font-weight:600;opacity:0.88;margin-top:1px;">Processing fee applied</div>
      </button>
    </div>
  </section>
</div>

<nav class="bnav">
  <div class="bnav-inner">
    <button class="bnav-item active" id="bi-home" onclick="goPage('home')"><span>🏠</span>Home</button>
    <button class="bnav-item" id="bi-tasks" onclick="goPage('tasks')"><span>📋</span>Tasks</button>
    <button class="bnav-item" id="bi-mining" onclick="goPage('mining')"><span>⛏</span>Mining</button>
    <button class="bnav-item" id="bi-games" onclick="goPage('games')"><span>🎮</span>Games</button>
    <button class="bnav-item" id="bi-refer" onclick="goPage('refer')"><span>👥</span>Refer</button>
    <button class="bnav-item" id="bi-wallet" onclick="goPage('wallet')"><span>👛</span>Wallet</button>
  </div>
</nav>

<script>
const qp = new URLSearchParams(window.location.search);
const tgWebApp = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
if (tgWebApp) {
  try { tgWebApp.ready(); tgWebApp.expand(); } catch (_) {}
}

const TG_INIT_DATA = (tgWebApp && tgWebApp.initData) ? tgWebApp.initData : (qp.get("init_data") || "");
const TG_USER_OBJ = (tgWebApp && tgWebApp.initDataUnsafe && tgWebApp.initDataUnsafe.user) ? tgWebApp.initDataUnsafe.user : null;

const TG_ID = TG_USER_OBJ && TG_USER_OBJ.id
  ? String(TG_USER_OBJ.id)
  : (qp.get("tg_id") || "");

const USER = TG_ID
  ? `tg_${TG_ID}`
  : (qp.get("user_id") || "user_1001");

const NAME = TG_USER_OBJ && TG_USER_OBJ.id
  ? (`${TG_USER_OBJ.first_name || ""} ${TG_USER_OBJ.last_name || ""}`.trim() || (TG_USER_OBJ.username ? `@${TG_USER_OBJ.username}` : `TG_${TG_ID}`))
  : (qp.get("username") || (TG_ID ? `TG_${TG_ID}` : "TapMintUser"));

const REF = (tgWebApp && tgWebApp.initDataUnsafe && tgWebApp.initDataUnsafe.start_param)
  ? String(tgWebApp.initDataUnsafe.start_param)
  : (qp.get("ref") || "");

function authHeaders(extra = {}) {
  const h = Object.assign({
    "X-User-Id": USER,
    "X-Username": NAME,
  }, extra);
  if (TG_ID) h["X-Telegram-Id"] = TG_ID;
  if (TG_INIT_DATA) h["X-Telegram-Init-Data"] = TG_INIT_DATA;
  return h;
}

const WHEEL_SLOTS = [
  { label: "1 PTS", color: "#16a34a" },
  { label: "3 PTS", color: "#eab308" },
  { label: "4 PTS", color: "#f97316" },
  { label: "6 PTS", color: "#06b6d4" },
  { label: "8 PTS", color: "#22c55e" },
  { label: "10 PTS", color: "#ec4899" },
  { label: "Try Again", color: "#8b5cf6" },
];

function renderWheelSvg() {
  const g = document.getElementById("wheel-slices");
  if (!g) return;
  const cx = 120, cy = 120, r = 114;
  const n = WHEEL_SLOTS.length;
  const step = 360 / n;
  let html = "";

  for (let i = 0; i < n; i++) {
    const startDeg = -90 + i * step;
    const endDeg = startDeg + step;
    const midDeg = startDeg + step / 2;

    const sRad = (startDeg * Math.PI) / 180;
    const eRad = (endDeg * Math.PI) / 180;

    const x1 = cx + r * Math.cos(sRad);
    const y1 = cy + r * Math.sin(sRad);
    const x2 = cx + r * Math.cos(eRad);
    const y2 = cy + r * Math.sin(eRad);

    html += `<path d="M ${cx} ${cy} L ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 0 1 ${x2.toFixed(2)} ${y2.toFixed(2)} Z" fill="${WHEEL_SLOTS[i].color}" stroke="#0f172a" stroke-width="2" />`;

    const tr = 74;
    const mRad = (midDeg * Math.PI) / 180;
    const tx = cx + tr * Math.cos(mRad);
    const ty = cy + tr * Math.sin(mRad);
    const rot = midDeg + 90;

    html += `<text x="${tx.toFixed(2)}" y="${ty.toFixed(2)}" fill="#ffffff" font-size="11.5" font-weight="800" text-anchor="middle" dominant-baseline="middle" transform="rotate(${rot.toFixed(2)}, ${tx.toFixed(2)}, ${ty.toFixed(2)})">${WHEEL_SLOTS[i].label}</text>`;
  }
  g.innerHTML = html;
}

renderWheelSvg();

let ST = null;
let SESS = 1;
let PAY = "bKash";
let DEG = 0;

function notify(t) {
  const el = document.getElementById("toast");
  el.textContent = t;
  el.style.display = "block";
  clearTimeout(window._nt);
  window._nt = setTimeout(() => { el.style.display = "none"; }, 3000);
}

function goPage(p) {
  document.querySelectorAll(".page").forEach(x => x.classList.remove("active"));
  document.querySelectorAll(".bnav-item").forEach(x => x.classList.remove("active"));
  document.getElementById("page-" + p).classList.add("active");
  document.getElementById("bi-" + p).classList.add("active");
}

function toggleWForm() {
  const f = document.getElementById("w-form");
  f.style.display = f.style.display === "none" ? "block" : "none";
}

function focusPinInput() {
  document.getElementById("w-pin-confirm").focus();
}

function paintPin() {
  const v = document.getElementById("w-pin-confirm").value;
  for (let i = 0; i < 4; i++) {
    document.getElementById("p" + i).textContent = i < v.length ? "●" : "•";
  }
}

function setPay(m) {
  PAY = m;
  ["bKash", "Nagad", "Binance USDT"].forEach(k => {
    document.getElementById("pm-" + k).classList.toggle("active", k === m);
    const wm = document.getElementById("wm-" + k);
    if (wm) wm.classList.toggle("active", k === m);
  });
  const accInp = document.getElementById("w-acc");
  const ruleHint = document.getElementById("w-rule-hint");
  if (accInp) {
    if (m === "Binance USDT") {
      accInp.placeholder = "TRC20 (T...), BEP20 (0x...) বা Pay ID";
      if (ruleHint) ruleHint.textContent = "• বৈধ TRC20/BEP20 অ্যাড্রেস বা ৬–১২ ডিজিট Pay ID • শক্তিশালী ৪ ডিজিট পিন";
    } else {
      accInp.placeholder = `017XXXXXXXX (১১ ডিজিট বৈধ ${m} নম্বর)`;
      if (ruleHint) ruleHint.textContent = `• ${m}: ১১ ডিজিট (013–019) • সাধারণ পিন (0000, 1111, 1234) নিষিদ্ধ`;
    }
  }
  syncWCopy();
}

function syncWCopy() {
  if (!ST) return;
  const wr = ST.withdraw_rules;
  const ptsInput = document.getElementById("w-pts-val");
  document.getElementById("w-sub").textContent =
    `সর্বনিম্ন ${wr.general_min_pts.toLocaleString()} PTS হলে উইথড্র নিতে পারবেন • বাইনান্সে ১৫,০০০ PTS ($5)`;
  if (PAY === "Binance USDT") {
    document.getElementById("w-pts-lbl").textContent =
      `Points to Withdraw (Min ${wr.binance_min_pts.toLocaleString()} = $${wr.binance_min_usdt_rule})`;
    ptsInput.placeholder = "15,000";
    document.getElementById("w-fee-txt").innerHTML =
      `১৫,০০০ PTS হলে $${wr.binance_min_usdt_rule} (৫ ডলার) উইথড্র পাবেন।<br/>*বাইনান্স পেমেন্টের সময় নির্ধারিত প্রসেসিং ও নেটওয়ার্ক ফি কেটে নেওয়া হবে।`;
  } else {
    document.getElementById("w-pts-lbl").textContent =
      `Points to Withdraw (Min ${wr.general_min_pts.toLocaleString()})`;
    ptsInput.placeholder = "1,500";
    document.getElementById("w-fee-txt").innerHTML =
      `উইথড্র রিকোয়েস্ট সাবমিট করলে নির্ধারিত ফি কেটে নেওয়া হবে।<br/>*সর্বনিম্ন উইথড্র ১,৫০০ PTS • বাইনান্সে সর্বনিম্ন ১৫,০০০ PTS ($5)।`;
  }
}

function fmtTime(iso) {
  if (!iso) return "00:00:00";
  const sec = Math.max(0, Math.floor((new Date(iso) - new Date()) / 1000));
  const h = String(Math.floor(sec / 3600)).padStart(2, "0");
  const m = String(Math.floor((sec % 3600) / 60)).padStart(2, "0");
  const s = String(sec % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

function drawDayTracker(streakDays) {
  const d = Math.max(0, Math.min(7, parseInt(streakDays || 0, 10)));
  document.getElementById("day-streak-lbl").textContent = `Day ${d}/7`;
  const dots = document.getElementById("day-dots");
  let html = "";
  for (let i = 1; i <= 7; i++) {
    const done = i <= d;
    html += `<div class="dot-c ${done ? "ok" : "no"}">${done ? "✓" : i}</div>`;
  }
  dots.innerHTML = html;
}

function drawSpinClock() {
  if (!ST) return;
  const used = ST.spin.spins_used_today;
  const hasFuture = ST.spin.next_spin_at && new Date() < new Date(ST.spin.next_spin_at);
  document.getElementById("spin-btn").disabled = used >= ST.spin.max_daily || hasFuture;
  if (hasFuture) {
    document.getElementById("spin-countdown").textContent = `Next spin countdown: ${fmtTime(ST.spin.next_spin_at)}`;
    document.getElementById("spin-status").textContent = "0 Spin Available Today";
  } else {
    document.getElementById("spin-countdown").textContent = "";
    document.getElementById("spin-status").textContent = "1 Spin Available Today";
  }
}

function drawMiningUi() {
  if (!ST) return;
  const clm = ST.mining.claims_today;
  const maxC = ST.mining.max_daily;
  const totalSec = 7200;
  const activeM = ST.mining.next_claim_at && new Date() < new Date(ST.mining.next_claim_at);
  const remSec = activeM ? Math.max(0, Math.floor((new Date(ST.mining.next_claim_at) - new Date()) / 1000)) : 0;
  const pct = activeM ? Math.max(1, Math.min(99, Math.round(((totalSec - remSec) / totalSec) * 100))) : 100;

  document.getElementById("m-claims").textContent = `${clm} / ${maxC}`;
  document.getElementById("m-clock").textContent = activeM ? fmtTime(ST.mining.next_claim_at) : "00:00:00";
  document.getElementById("m-badge").textContent = activeM ? "MINING ACTIVE" : "MINING READY";
  document.getElementById("m-progress").textContent = `Mining Progress: ${pct}% • Earn 5 to 10 PTS each claim`;
  document.getElementById("home-m-txt").textContent = activeM ? `${fmtTime(ST.mining.next_claim_at)} left` : "Ready to claim";

  const mb = document.getElementById("m-btn");
  const mMain = document.getElementById("m-btn-main");
  const mSub = document.getElementById("m-btn-sub");

  if (clm >= maxC) {
    mb.disabled = true;
    mMain.textContent = "DAILY LIMIT REACHED (6/6)";
    mSub.textContent = "Come back tomorrow for next mining cycle";
  } else if (activeM) {
    mb.disabled = true;
    mMain.textContent = "MINING IN PROGRESS";
    mSub.textContent = `Next claim in ${fmtTime(ST.mining.next_claim_at)}`;
  } else {
    mb.disabled = false;
    mMain.textContent = "READY TO CLAIM (+7 PTS)";
    mSub.textContent = "Tap to claim 5–10 PTS now";
  }
}

function draw() {
  if (!ST) return;
  const u = ST.user;
  const b = u.pts_balance;
  document.getElementById("hdr-pts").textContent = b.toLocaleString() + " PTS";
  document.getElementById("home-bal").textContent = b.toLocaleString() + " PTS";
  document.getElementById("w-bal").textContent = b.toLocaleString() + " PTS";

  const tgLabel = u.telegram_id ? `TG ID: ${u.telegram_id}` : `Account: ${u.user_id}`;
  document.getElementById("acct-sub").textContent = `${u.username} • ${tgLabel}`;
  document.getElementById("acct-badge").textContent = u.is_telegram_verified ? "TG Auto-Verified" : "Personal Account";
  document.getElementById("prof-name").textContent = u.username;
  document.getElementById("prof-meta").textContent = `Telegram ID: ${u.telegram_id || "Web Session"} • Account ID: ${u.user_id}`;
  document.getElementById("prof-ver-pill").textContent = u.is_telegram_verified ? "✓ TG Verified" : "● Active Account";

  drawDayTracker(ST.spin.spin_streak_days);
  drawSpinClock();
  drawMiningUi();

  const doneS = ST.task_sessions.filter(x => x.completed_count >= 20 || x.is_locked).length;
  document.getElementById("home-t-txt").textContent = `${doneS}/5 Completed`;

  if (ST.unlocked_session) {
    const curSelected = ST.task_sessions.find(x => x.session_num === SESS);
    if (!curSelected || curSelected.is_locked) {
      SESS = ST.unlocked_session;
    }
  }

  drawSessions();
  drawTasks();
  drawGames();

  const actCount = parseInt(ST.referral.active_referrals || 0, 10);
  const boostPct = Math.min(30, actCount * 5);
  document.getElementById("ref-cnt").textContent = ST.referral.total_referrals;
  document.getElementById("ref-act").textContent = actCount;
  document.getElementById("ref-pts").textContent = `+${boostPct}% Boost`;
  const refParam = u.telegram_id ? `tg_${u.telegram_id}` : u.user_id;
  document.getElementById("ref-url").value = `${window.location.origin}/?ref=${encodeURIComponent(refParam)}`;

  if (ST.wallet.connected) {
    document.getElementById("w-conn").textContent =
      `Verified Wallet: ${ST.wallet.method} (${ST.wallet.masked_target})`;
    document.getElementById("w-ver").textContent = "● Valid Method, Account & 4-Digit PIN Verified";
    setPay(ST.wallet.method);
  }
  syncWCopy();
}

function drawSessions() {
  const wrap = document.getElementById("sess-5");
  wrap.innerHTML = "";
  for (const s of ST.task_sessions) {
    const isOpenSession = !s.is_locked && s.session_num === ST.unlocked_session;
    const el = document.createElement("div");
    el.className = "sess-pill" + (s.session_num === SESS ? " active" : "") + (s.is_locked || !isOpenSession ? " locked" : "");
    let stHtml = "";
    if (s.is_locked) {
      stHtml = `🔒 Locked<br/>${fmtTime(s.locked_until)}`;
    } else if (isOpenSession) {
      stHtml = `● Active<br/>${s.completed_count}/20`;
    } else {
      stHtml = `🔒 Locked<br/>${s.completed_count}/20`;
    }
    el.innerHTML = `<div class="sess-n">Session ${s.session_num}</div><div class="sess-st">${stHtml}</div>`;
    el.onclick = () => {
      if (s.is_locked || !isOpenSession) {
        notify(`Session ${s.session_num} এখনো লক আছে`);
        return;
      }
      SESS = s.session_num;
      drawSessions();
      drawTasks();
    };
    wrap.appendChild(el);
  }
}

function drawTasks() {
  const cur = ST.task_sessions.find(x => x.session_num === SESS);
  const done = cur ? cur.completed_count : 0;
  const doneSet = new Set((cur && cur.completed_tasks) ? cur.completed_tasks : []);
  document.getElementById("sess-title").textContent = `Session ${SESS}: 20 Tasks (${done}/20 Completed)`;

  const list = document.getElementById("task-rows");
  list.innerHTML = "";
  if (cur && cur.is_locked) {
    list.innerHTML = `<div class="card-3d" style="text-align:center;color:#fbbf24;font-size:13px;">
      Session ${SESS} Locked (${fmtTime(cur.locked_until)} বাকি)
    </div>`;
    return;
  }
  if (cur && cur.session_num !== ST.unlocked_session) {
    list.innerHTML = `<div class="card-3d" style="text-align:center;color:#94a3b8;font-size:13px;">
      আগে Session ${ST.unlocked_session} সম্পন্ন করুন, এরপর Session ${SESS} খুলবে।
    </div>`;
    return;
  }

  for (let i = 1; i <= 20; i++) {
    const isDone = doneSet.has(i);
    const ico = isDone ? "✓" : (i % 2 === 1 ? "🔗" : "🪙");
    const row = document.createElement("div");
    row.className = "row-card-3d" + (isDone ? " done-card" : "");
    row.innerHTML = `
      <div style="display:flex;align-items:center;gap:12px;">
        <div class="t-badge-ico" style="${isDone ? "color:#4ade80;border-color:#4ade80;" : ""}">${ico}</div>
        <div>
          <div style="font-weight:700;font-size:14px;">Task ${String(i).padStart(2, "0")}</div>
          <div style="font-size:12px;color:#34d399;font-weight:700;">Reward: +1 PTS</div>
          ${isDone
            ? `<div class="done-badge">✓ Completed</div>`
            : `<div class="wait-badge">🕒 8-10s Wait Required</div>`
          }
        </div>
      </div>
      ${isDone
        ? `<div class="done-btn-3d">✓ Done</div>`
        : `<button class="open-btn-3d" id="ot-${SESS}-${i}" onclick="startTask(${SESS},${i})">Open Task</button>`
      }
    `;
    list.appendChild(row);
  }
}

async function startTask(sNum, tNum) {
  const btn = document.getElementById(`ot-${sNum}-${tNum}`);
  btn.disabled = true;
  const op = await fetch("/api/task/open", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ user_id: USER, tg_id: TG_ID, init_data: TG_INIT_DATA, username: NAME, session_num: sNum, task_num: tNum })
  }).then(r => r.json());
  if (!op.ok) {
    notify(op.error || "Cannot open task");
    btn.disabled = false;
    return;
  }
  if (op.launch_url) {
    window.open(op.launch_url, "_blank", "noopener,noreferrer");
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
      const cp = await fetch("/api/task/complete", {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ user_id: USER, tg_id: TG_ID, init_data: TG_INIT_DATA, username: NAME, session_num: sNum, task_num: tNum })
      }).then(r => r.json());
      if (cp.ok) {
        notify(`+${cp.pts_earned} PTS earned!`);
        await loadApp();
      } else {
        notify(cp.error || "Task failed");
        btn.disabled = false;
        btn.textContent = "Open Task";
      }
    }
  }, 1000);
}

async function doSpin() {
  const r = await fetch("/api/spin", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ user_id: USER, tg_id: TG_ID, init_data: TG_INIT_DATA, username: NAME })
  }).then(x => x.json());
  if (!r.ok) return notify(r.error || "Spin not ready");

  const sliceDeg = 360 / WHEEL_SLOTS.length;
  const sIdx = typeof r.slot_index === "number" ? r.slot_index : 0;
  const targetCenter = sIdx * sliceDeg + sliceDeg / 2;
  const baseMod = ((DEG % 360) + 360) % 360;
  const desiredMod = (360 - targetCenter) % 360;
  const deltaMod = (desiredMod - baseMod + 360) % 360;
  DEG += 1080 + deltaMod;

  document.getElementById("wheel-rotor").style.transform = `rotate(${DEG}deg)`;
  document.getElementById("spin-msg").textContent = r.pts_earned > 0
    ? `${r.slot} (+${r.pts_earned} PTS)`
    : "Try Again (+0 PTS)";

  setTimeout(async () => {
    notify(r.pts_earned > 0 ? `+${r.pts_earned} PTS added!` : "Try Again today!");
    await loadApp();
  }, 2500);
}

async function doMining() {
  const r = await fetch("/api/mining/claim", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ user_id: USER, tg_id: TG_ID, init_data: TG_INIT_DATA, username: NAME })
  }).then(x => x.json());
  if (r.ok) {
    notify(`+${r.pts_earned} PTS mined!`);
    await loadApp();
  } else {
    notify(r.error || "Mining not ready");
  }
}

const GAMES_CONFIG = [
  { ico: "🕹", title: "Tap Surge Combo", tgtText: "Hard Target: 75+", targetVal: 75, timeSec: 16, pts: 2, mode: "tap" },
  { ico: "👾", title: "Catch & Dodge 3D", tgtText: "Hard Target: 35+", targetVal: 35, timeSec: 18, pts: 2, mode: "catch" },
  { ico: "🔢", title: "Number Merge 2048", tgtText: "Hard Target: 90+ Pts", targetVal: 90, timeSec: 22, pts: 2, mode: "merge" },
  { ico: "🐍", title: "Neon Snake Arcade", tgtText: "Hard Target: 40+", targetVal: 40, timeSec: 20, pts: 2, mode: "snake" },
];

function drawGames() {
  const box = document.getElementById("game-rows");
  box.innerHTML = "";
  for (const g of GAMES_CONFIG) {
    const el = document.createElement("div");
    el.className = "g-3d-card";
    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:12px;">
        <div class="g-3d-thumb">${g.ico}</div>
        <div>
          <div style="font-weight:800;font-size:15px;color:#ffffff;">${g.title}</div>
          <div class="muted" style="margin-top:2px;">${g.tgtText}</div>
          <div style="font-size:12px;color:#34d399;font-weight:700;margin-top:2px;">Reward: +${g.pts} PTS (Auto Ad 8–10s)</div>
          <div style="font-size:11px;color:#64748b;margin-top:2px;">ক্লেমে অটো অ্যাড খুলবে • ৮–১০s পর ব্যাক আসলে সাকসেস</div>
        </div>
      </div>
      <button class="g-play-3d" onclick="openPlayableGame('${g.title}')">Play Hard</button>
    `;
    box.appendChild(el);
  }
}

let GM = {
  cfg: null,
  token: "",
  adUrl: "",
  score: 0,
  timeLeft: 16,
  timerIv: null,
  spawnIv: null,
  adTimerIv: null,
  adOpenedAtMs: 0,
  leftAdWindow: false,
  finished: false,
  catcherX: 135,
  mergePair: [16, 16],
  snake: [{ x: 5, y: 4 }],
  snakeDir: { x: 1, y: 0 },
  food: { x: 11, y: 4 },
  hazard: { x: 8, y: 2 },
};

function clearGameTimers() {
  if (GM.timerIv) clearInterval(GM.timerIv);
  if (GM.spawnIv) clearInterval(GM.spawnIv);
  if (GM.adTimerIv) clearInterval(GM.adTimerIv);
  GM.timerIv = null;
  GM.spawnIv = null;
  GM.adTimerIv = null;
}

function closeGameModal() {
  clearGameTimers();
  document.getElementById("game-modal").classList.remove("open");
}

async function openPlayableGame(title) {
  const cfg = GAMES_CONFIG.find(x => x.title === title) || GAMES_CONFIG[0];
  const st = await fetch("/api/game/start", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ user_id: USER, tg_id: TG_ID, init_data: TG_INIT_DATA, username: NAME, game_name: cfg.title, reward_pts: cfg.pts })
  }).then(x => x.json());
  if (!st.ok) return notify(st.error || "Cannot start game");

  clearGameTimers();
  GM.cfg = cfg;
  GM.token = st.session_token;
  GM.adUrl = st.ad_url || "";
  GM.score = 0;
  GM.timeLeft = cfg.timeSec || 16;
  GM.finished = false;
  GM.adOpenedAtMs = 0;
  GM.leftAdWindow = false;

  document.getElementById("gm-title").textContent = cfg.title;
  document.getElementById("gm-target").textContent = `${cfg.tgtText} • Reward: +${cfg.pts} PTS`;
  document.getElementById("gm-ad-link").href = GM.adUrl || "#";
  document.getElementById("gm-play-stage").style.display = "block";
  document.getElementById("gm-ad-stage").style.display = "none";
  document.getElementById("game-modal").classList.add("open");

  initGameMode();
}

function handleGameStageButton() {
  if (!GM.cfg) return;
  openPlayableGame(GM.cfg.title);
}

function updateGmHud() {
  document.getElementById("gm-score-lbl").textContent = `Score: ${GM.score} / ${GM.cfg.targetVal}`;
  document.getElementById("gm-time-lbl").textContent = `Time: ${GM.timeLeft}s`;
}

function initGameMode() {
  const arena = document.getElementById("gm-arena");
  const ctrl = document.getElementById("gm-ctrl-bar");
  arena.innerHTML = "";
  ctrl.innerHTML = "";
  updateGmHud();

  if (GM.cfg.mode === "tap") {
    arena.innerHTML = `
      <div style="position:relative;width:100%;height:100%;">
        <button id="tap-moving-good" style="position:absolute;top:60px;left:95px;width:72px;height:72px;border-radius:50%;border:2.5px solid #bbf7d0;border-bottom:4px solid #15803d;background:radial-gradient(circle at 30% 25%,#4ade80,#15803d);color:#052e16;font-weight:900;font-size:13px;cursor:pointer;box-shadow:0 8px 18px rgba(34,197,94,0.45);transition:top 0.14s,left 0.14s;">
          +8
        </button>
        <button id="tap-moving-bad" style="position:absolute;top:135px;left:185px;width:62px;height:62px;border-radius:50%;border:2px solid #fca5a5;border-bottom:4px solid #991b1b;background:radial-gradient(circle at 30% 25%,#f87171,#dc2626);color:#fff;font-weight:900;font-size:12px;cursor:pointer;transition:top 0.16s,left 0.16s;">
          -10
        </button>
        <div style="position:absolute;bottom:8px;left:0;right:0;text-align:center;font-size:11px;color:#94a3b8;">
          সবুজ টার্গেট ধরুন (+8), লাল বোম/ট্র্যাপ এড়িয়ে চলুন (-10)
        </div>
      </div>
    `;
    const gBtn = document.getElementById("tap-moving-good");
    const bBtn = document.getElementById("tap-moving-bad");

    const moveTargets = () => {
      if (GM.finished) return;
      gBtn.style.left = Math.floor(Math.random() * 250) + 12 + "px";
      gBtn.style.top = Math.floor(Math.random() * 125) + 12 + "px";
      bBtn.style.left = Math.floor(Math.random() * 255) + 14 + "px";
      bBtn.style.top = Math.floor(Math.random() * 130) + 14 + "px";
    };

    gBtn.onclick = () => {
      if (GM.finished) return;
      GM.score += 8;
      updateGmHud();
      moveTargets();
      if (GM.score >= GM.cfg.targetVal) triggerGameAdStage();
    };
    bBtn.onclick = () => {
      if (GM.finished) return;
      GM.score = Math.max(0, GM.score - 10);
      updateGmHud();
      moveTargets();
    };
    GM.spawnIv = setInterval(moveTargets, 620);
  } else if (GM.cfg.mode === "catch") {
    GM.catcherX = 135;
    arena.innerHTML = `
      <div id="catcher-p" style="position:absolute;bottom:10px;left:${GM.catcherX}px;width:50px;height:24px;border-radius:10px;background:linear-gradient(180deg,#6ee7b7,#10b981);border:1px solid #a7f3d0;display:flex;align-items:center;justify-content:center;font-weight:900;color:#052e16;font-size:13px;">🧺</div>
    `;
    ctrl.innerHTML = `
      <button class="pay-btn-3d" style="grid-column:span 2;" onclick="moveCatcher(-42)">⬅ Left</button>
      <button class="pay-btn-3d" style="grid-column:span 2;" onclick="moveCatcher(42)">Right ➡</button>
    `;
    GM.spawnIv = setInterval(() => {
      if (GM.finished) return;
      const drop = document.createElement("div");
      const rVal = Math.random();
      const isBomb = rVal < 0.36;
      const isGem = rVal >= 0.82;
      let dx = Math.floor(Math.random() * 275) + 12;
      let dy = 8;
      drop.textContent = isBomb ? "💣" : (isGem ? "💎" : "🪙");
      drop.style.cssText = `position:absolute;top:${dy}px;left:${dx}px;font-size:22px;`;
      arena.appendChild(drop);

      const fallIv = setInterval(() => {
        if (GM.finished) { clearInterval(fallIv); return; }
        dy += 18;
        drop.style.top = dy + "px";
        if (dy >= 182 && dy <= 220 && Math.abs(dx - GM.catcherX) < 32) {
          clearInterval(fallIv);
          drop.remove();
          if (isBomb) {
            GM.score = Math.max(0, GM.score - 8);
          } else {
            GM.score += (isGem ? 12 : 7);
          }
          updateGmHud();
          if (GM.score >= GM.cfg.targetVal) triggerGameAdStage();
        } else if (dy > 232) {
          clearInterval(fallIv);
          drop.remove();
        }
      }, 85);
    }, 520);
  } else if (GM.cfg.mode === "merge") {
    GM.mergePair = [16, 16];
    renderMergeBoard(arena);
  } else if (GM.cfg.mode === "snake") {
    GM.snake = [{ x: 5, y: 4 }];
    GM.snakeDir = { x: 1, y: 0 };
    GM.food = { x: 11, y: 4 };
    GM.hazard = { x: 8, y: 4 };
    ctrl.innerHTML = `
      <button class="pay-btn-3d" onclick="setSnakeDir(0,-1)">▲</button>
      <button class="pay-btn-3d" onclick="setSnakeDir(0,1)">▼</button>
      <button class="pay-btn-3d" onclick="setSnakeDir(-1,0)">◀</button>
      <button class="pay-btn-3d" onclick="setSnakeDir(1,0)">▶</button>
    `;
    renderSnakeBoard(arena);
    GM.spawnIv = setInterval(() => {
      if (GM.finished) return;
      const head = GM.snake[0];
      const nx = head.x + GM.snakeDir.x;
      const ny = head.y + GM.snakeDir.y;

      if (nx < 0 || nx >= 16 || ny < 0 || ny >= 9) {
        GM.score = Math.max(0, GM.score - 8);
        GM.snake = [{ x: 4, y: 4 }];
        GM.snakeDir = { x: 1, y: 0 };
        updateGmHud();
        renderSnakeBoard(arena);
        return;
      }

      if (nx === GM.hazard.x && ny === GM.hazard.y) {
        GM.score = Math.max(0, GM.score - 10);
        GM.hazard = { x: Math.floor(Math.random() * 14) + 1, y: Math.floor(Math.random() * 7) + 1 };
        updateGmHud();
      }

      GM.snake.unshift({ x: nx, y: ny });
      if (nx === GM.food.x && ny === GM.food.y) {
        GM.score += 10;
        GM.food = { x: Math.floor(Math.random() * 15), y: Math.floor(Math.random() * 8) };
        GM.hazard = { x: Math.floor(Math.random() * 14) + 1, y: Math.floor(Math.random() * 7) + 1 };
        updateGmHud();
        if (GM.score >= GM.cfg.targetVal) {
          triggerGameAdStage();
          return;
        }
      } else {
        GM.snake.pop();
      }
      renderSnakeBoard(arena);
    }, 185);
  }

  GM.timerIv = setInterval(() => {
    if (GM.finished) return;
    GM.timeLeft -= 1;
    updateGmHud();
    if (GM.timeLeft <= 0) {
      if (GM.score >= GM.cfg.targetVal) {
        triggerGameAdStage();
      } else {
        clearGameTimers();
        notify(`সময় শেষ! হার্ড টার্গেট ${GM.cfg.targetVal} পূরণ করতে আবার খেলুন`);
      }
    }
  }, 1000);
}

function renderMergeBoard(arena) {
  const targetNum = GM.mergePair[0];
  const opts = [targetNum, targetNum, targetNum + 4, targetNum - 4].sort(() => Math.random() - 0.5);
  let btns = opts.map(v => `<button class="open-btn-3d" style="padding:10px 12px;" onclick="handleMergePick(${v}, ${targetNum})">[ ${v} ]</button>`).join("");
  arena.innerHTML = `
    <div style="height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;">
      <div style="font-size:13px;font-weight:800;color:#fbbf24;">মার্জ করুন: [ ${targetNum} ] + [ ${targetNum} ] = ${targetNum * 2} (+${targetNum} স্কোর)</div>
      <div style="display:flex;flex-wrap:wrap;justify-content:center;gap:8px;padding:0 10px;">${btns}</div>
      <div class="muted" style="font-size:11px;">ভুল নম্বর চাপলে -8 পয়েন্ট কাটা যাবে</div>
    </div>
  `;
}

function handleMergePick(picked, expected) {
  if (GM.finished) return;
  if (picked === expected) {
    GM.score += expected;
    GM.mergePair = [expected === 16 ? 24 : (expected === 24 ? 32 : 20), expected === 16 ? 24 : (expected === 24 ? 32 : 20)];
    updateGmHud();
    if (GM.score >= GM.cfg.targetVal) {
      triggerGameAdStage();
      return;
    }
  } else {
    GM.score = Math.max(0, GM.score - 8);
    updateGmHud();
    notify("ভুল টাইল! -8 স্কোর");
  }
  renderMergeBoard(document.getElementById("gm-arena"));
}

function moveCatcher(dx) {
  GM.catcherX = Math.max(8, Math.min(285, GM.catcherX + dx));
  const el = document.getElementById("catcher-p");
  if (el) el.style.left = GM.catcherX + "px";
}

function setSnakeDir(x, y) {
  GM.snakeDir = { x, y };
}

function renderSnakeBoard(arena) {
  let html = `<div style="position:relative;width:100%;height:100%;">`;
  html += `<div style="position:absolute;left:${GM.food.x * 20 + 6}px;top:${GM.food.y * 23 + 4}px;font-size:16px;">🟢</div>`;
  html += `<div style="position:absolute;left:${GM.hazard.x * 20 + 6}px;top:${GM.hazard.y * 23 + 4}px;font-size:16px;">🟥</div>`;
  GM.snake.forEach((seg, idx) => {
    html += `<div style="position:absolute;left:${seg.x * 20 + 6}px;top:${seg.y * 23 + 4}px;width:16px;height:16px;border-radius:5px;background:${idx === 0 ? "#6ee7b7" : "#10b981"};"></div>`;
  });
  html += `</div>`;
  arena.innerHTML = html;
}

async function launchGameAdWindow() {
  if (!GM.token) return;
  GM.adOpenedAtMs = Date.now();
  await fetch("/api/game/ad-open", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ user_id: USER, tg_id: TG_ID, init_data: TG_INIT_DATA, session_token: GM.token })
  });
  if (GM.adUrl) {
    window.open(GM.adUrl, "_blank", "noopener,noreferrer");
  }
}

function relaunchGameAd() {
  GM.adOpenedAtMs = Date.now();
  fetch("/api/game/ad-open", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ user_id: USER, tg_id: TG_ID, init_data: TG_INIT_DATA, session_token: GM.token })
  });
}

document.addEventListener("visibilitychange", async () => {
  if (!GM.finished || !GM.token) return;
  if (document.hidden) {
    GM.leftAdWindow = true;
    if (!GM.adOpenedAtMs) {
      GM.adOpenedAtMs = Date.now();
      await fetch("/api/game/ad-open", {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ user_id: USER, tg_id: TG_ID, init_data: TG_INIT_DATA, session_token: GM.token })
      });
    }
  } else if (GM.leftAdWindow) {
    const spentSec = GM.adOpenedAtMs ? (Date.now() - GM.adOpenedAtMs) / 1000 : 0;
    if (spentSec >= 8) {
      const cp = await fetch("/api/game/ad-complete", {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ user_id: USER, tg_id: TG_ID, init_data: TG_INIT_DATA, session_token: GM.token })
      }).then(x => x.json());
      if (cp.ok) {
        document.getElementById("gm-ad-timer").textContent = "৮–১০s সম্পন্ন ✓ ব্যাক এসেছেন, ক্লেম করুন!";
        document.getElementById("gm-claim-btn").disabled = false;
      }
    } else {
      const need = Math.max(1, Math.ceil(8 - spentSec));
      notify(`অ্যাডে আরও ${need} সেকেন্ড থাকুন, তারপর ব্যাক আসলে রিওয়ার্ড পাবেন`);
    }
  }
});

async function triggerGameAdStage() {
  if (GM.finished) return;
  GM.finished = true;
  clearGameTimers();

  document.getElementById("gm-play-stage").style.display = "none";
  document.getElementById("gm-ad-stage").style.display = "block";
  const claimBtn = document.getElementById("gm-claim-btn");
  claimBtn.disabled = true;

  await launchGameAdWindow();

  const waitTarget = 9;
  const startMs = Date.now();
  let verifiedSent = false;

  const tickAd = async () => {
    const elapsed = (Date.now() - startMs) / 1000;
    const rem = Math.max(0, Math.ceil(waitTarget - elapsed));
    if (rem > 0) {
      document.getElementById("gm-ad-timer").textContent = `Wait: ${rem}s (8–10s required)`;
    } else {
      if (!verifiedSent) {
        verifiedSent = true;
        await fetch("/api/game/ad-complete", {
          method: "POST",
          headers: authHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ user_id: USER, tg_id: TG_ID, init_data: TG_INIT_DATA, session_token: GM.token })
        });
      }
      document.getElementById("gm-ad-timer").textContent = "8–10s Complete ✓ Ready to Claim!";
      claimBtn.disabled = false;
      if (GM.adTimerIv) {
        clearInterval(GM.adTimerIv);
        GM.adTimerIv = null;
      }
    }
  };

  tickAd();
  GM.adTimerIv = setInterval(tickAd, 500);
}

async function claimGameReward() {
  const cl = await fetch("/api/game/claim", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ user_id: USER, tg_id: TG_ID, init_data: TG_INIT_DATA, session_token: GM.token })
  }).then(x => x.json());
  if (cl.ok) {
    closeGameModal();
    notify(`+${cl.pts_earned} PTS রিওয়ার্ড সাকসেস!`);
    await loadApp();
  } else {
    notify(cl.error || "Claim failed");
  }
}

function copyRef() {
  const el = document.getElementById("ref-url");
  el.select();
  navigator.clipboard?.writeText(el.value);
  notify("Referral link copied");
}

function shareTelegram() {
  const link = document.getElementById("ref-url").value;
  const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent("TapMint এ জয়েন করে টাস্ক, মাইনিং ও গেম খেলে পয়েন্ট আয় করুন!")}`;
  window.open(shareUrl, "_blank", "noopener,noreferrer");
}

function clientValidateWallet(method, acc, pin) {
  const weak = ["0000","1111","2222","3333","4444","5555","6666","7777","8888","9999","1234","4321","1122","2211","1212","2020","2024","2025","2026"];
  if (!/^\d{4}$/.test(pin)) {
    return "পিন অবশ্যই ৪ সংখ্যার হতে হবে।";
  }
  if (weak.includes(pin) || new Set(pin.split("")).size === 1) {
    return "দুর্বল বা সাধারণ পিন (যেমন 0000, 1111, 1234) গ্রহণযোগ্য নয়।";
  }
  if (method === "bKash" || method === "Nagad") {
    const clean = acc.replace(/[\s\-+]/g, "").replace(/^880/, "0");
    if (!/^01[3-9]\d{8}$/.test(clean)) {
      return `ভ্যালিড ১১ ডিজিটের ${method} নম্বর দিন (013–019)।`;
    }
  } else if (method === "Binance USDT") {
    const okBep20 = /^0x[a-fA-F0-9]{40}$/.test(acc);
    const okTrc20 = /^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(acc);
    const okPayId = /^\d{6,12}$/.test(acc);
    if (!okBep20 && !okTrc20 && !okPayId) {
      return "ভ্যালিড Binance USDT অ্যাড্রেস (TRC20/BEP20) বা Pay ID দিন।";
    }
  }
  return "";
}

async function saveW() {
  const acc = document.getElementById("w-acc").value.trim();
  const pin = document.getElementById("w-pin-set").value.trim();
  const localErr = clientValidateWallet(PAY, acc, pin);
  if (localErr) {
    return notify(localErr);
  }
  const r = await fetch("/api/wallet/connect", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ user_id: USER, tg_id: TG_ID, init_data: TG_INIT_DATA, username: NAME, method: PAY, account_target: acc, pin })
  }).then(x => x.json());
  if (r.ok) {
    document.getElementById("w-pin-set").value = "";
    document.getElementById("w-form").style.display = "none";
    notify(`${r.method} ওয়ালেট ও পিন ভেরিফাই ও সেভ হয়েছে`);
    await loadApp();
  } else {
    notify(r.error || "Failed");
  }
}

async function reqWithdraw() {
  const val = parseInt(document.getElementById("w-pts-val").value || "0", 10);
  const pin = document.getElementById("w-pin-confirm").value.trim();
  if (!/^\d{4}$/.test(pin)) {
    return notify("আগে ৪ সংখ্যার পিন দিন");
  }
  if (PAY === "Binance USDT" && val < 15000) {
    return notify("বাইনান্সে সর্বনিম্ন ১৫,০০০ PTS ($5) হলে উইথড্র পাবেন");
  }
  if (PAY !== "Binance USDT" && val < 1500) {
    return notify("সর্বনিম্ন ১,৫০০ PTS হলে উইথড্র নিতে পারবেন");
  }
  const r = await fetch("/api/withdraw/request", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ user_id: USER, tg_id: TG_ID, init_data: TG_INIT_DATA, requested_pts: val, pin, method: PAY })
  }).then(x => x.json());
  if (r.ok) {
    document.getElementById("w-pin-confirm").value = "";
    paintPin();
    notify(`Withdraw #${r.withdraw_id} sent (Fee: ${r.fee_pts} PTS)`);
    await loadApp();
  } else {
    notify(r.error || "Withdraw failed");
  }
}

async function loadApp() {
  const q = new URLSearchParams({
    user_id: USER,
    tg_id: TG_ID,
    init_data: TG_INIT_DATA,
    username: NAME,
    ref: REF
  });
  const r = await fetch("/api/user/bootstrap?" + q.toString(), {
    headers: authHeaders()
  }).then(x => x.json());
  if (r.ok) {
    ST = r;
    draw();
  } else if (r.error) {
    notify(r.error);
  }
}

setInterval(() => {
  if (!ST) return;
  drawSpinClock();
  drawMiningUi();
  drawSessions();
}, 1000);

loadApp();
</script>
</body>
</html>"""


ADMIN_3D_HTML = """<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Tapmint Admin panel</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  body {
    background: radial-gradient(circle at 50% 0%, #1d3d46 0%, #0a1418 55%, #05090b 100%);
    color: #f1f5f9; min-height: 100vh; padding: 14px 12px 48px;
  }
  .wrap { max-width: 920px; margin: 0 auto; }

  .hero-3d {
    position: relative;
    background: linear-gradient(165deg, rgba(35, 62, 72, 0.96) 0%, rgba(14, 26, 32, 0.98) 60%, rgba(8, 15, 19, 1) 100%);
    border: 1.5px solid rgba(110, 231, 183, 0.35);
    border-bottom: 5px solid #04090c;
    border-radius: 24px;
    padding: 20px 18px;
    margin-bottom: 14px;
    box-shadow: 0 20px 42px rgba(0, 0, 0, 0.72), 0 0 28px rgba(52, 211, 153, 0.14), inset 0 2px 0 rgba(255, 255, 255, 0.16);
    text-align: center;
  }
  .hero-title-3d {
    font-size: clamp(26px, 6vw, 40px);
    font-weight: 900;
    letter-spacing: 0.4px;
    background: linear-gradient(180deg, #ffffff 0%, #a7f3d0 55%, #34d399 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    text-shadow: 0 6px 18px rgba(16, 185, 129, 0.25);
    line-height: 1.15;
  }
  .hero-sub-3d {
    font-size: 12px; color: #94a3b8; margin-top: 6px; font-weight: 600;
  }

  .panel-3d {
    background: linear-gradient(175deg, rgba(26, 44, 52, 0.96) 0%, rgba(12, 21, 26, 0.99) 100%);
    border: 1px solid rgba(148, 163, 184, 0.2);
    border-bottom: 4px solid rgba(4, 9, 12, 0.95);
    border-radius: 20px;
    padding: 15px;
    margin-bottom: 13px;
    box-shadow: 0 14px 28px rgba(0, 0, 0, 0.56), inset 0 1px 0 rgba(255, 255, 255, 0.1);
  }
  .sec-title { font-size: 16px; font-weight: 800; color: #ffffff; margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }

  .grid-stat { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 10px; margin-bottom: 13px; }
  .stat-3d {
    background: linear-gradient(175deg, rgba(28, 48, 56, 0.95), rgba(10, 18, 22, 0.99));
    border: 1px solid rgba(148, 163, 184, 0.2);
    border-bottom: 3px solid #04090c;
    border-radius: 16px; padding: 12px;
    box-shadow: 0 10px 20px rgba(0, 0, 0, 0.48), inset 0 1px 0 rgba(255, 255, 255, 0.09);
  }
  .stat-lbl { font-size: 11px; color: #94a3b8; font-weight: 700; }
  .stat-v { font-size: 21px; font-weight: 900; color: #34d399; margin-top: 3px; }
  .stat-v.gold { color: #facc15; }
  .stat-v.sky { color: #38bdf8; }
  .stat-v.rose { color: #fb7185; }

  .src-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; margin-bottom: 12px; }
  .src-box {
    background: rgba(8, 15, 19, 0.92);
    border: 1px solid rgba(52, 211, 153, 0.22);
    border-radius: 13px; padding: 10px; text-align: center;
  }
  .src-name { font-size: 11px; color: #94a3b8; font-weight: 700; text-transform: uppercase; }
  .src-pts { font-size: 16px; font-weight: 900; color: #4ade80; margin-top: 3px; }

  input, select {
    width: 100%; background: rgba(7, 13, 17, 0.95); border: 1px solid rgba(148, 163, 184, 0.24);
    color: #fff; border-radius: 12px; padding: 10px 12px; font-size: 13px; margin-bottom: 9px;
    box-shadow: inset 0 2px 5px rgba(0, 0, 0, 0.6);
  }
  .btn-3d {
    border: none; border-radius: 13px; padding: 10px 14px; font-weight: 800;
    cursor: pointer; font-size: 13px; transition: transform 0.08s ease;
  }
  .btn-3d:active { transform: translateY(2px); }
  .btn-g {
    background: linear-gradient(180deg, #6ee7b7 0%, #34d399 65%, #10b981 100%);
    color: #052e16; border-bottom: 3px solid #059669;
  }
  .btn-b {
    background: linear-gradient(180deg, #38bdf8 0%, #0284c7 70%, #0369a1 100%);
    color: #fff; border-bottom: 3px solid #075985;
  }
  .btn-r {
    background: linear-gradient(180deg, #f87171 0%, #ef4444 75%, #b91c1c 100%);
    color: #fff; border-bottom: 3px solid #7f1d1d;
  }

  .item-row {
    background: rgba(8, 15, 19, 0.92);
    border: 1px solid rgba(148, 163, 184, 0.16);
    border-radius: 14px; padding: 10px 12px; margin-bottom: 8px;
    display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap;
  }
  .pill-on {
    display: inline-block; font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 99px;
    background: rgba(16, 185, 129, 0.2); color: #4ade80; border: 1px solid rgba(74, 222, 128, 0.45);
  }
  .pill-off {
    display: inline-block; font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 99px;
    background: rgba(100, 116, 139, 0.2); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.3);
  }
  .two-col { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 13px; }
  .scroll-box { max-height: 310px; overflow-y: auto; padding-right: 2px; }
</style>
</head>
<body>
<div class="wrap">
  <div class="hero-3d">
    <div class="hero-title-3d">Tapmint Admin panel</div>
    <div class="hero-sub-3d">3D Command Center • Live Members, Source PTS, Hardworking Users, Wallets & Master Affiliate</div>
    <div style="max-width:440px;margin:14px auto 0;display:flex;gap:8px;flex-wrap:wrap;justify-content:center;">
      <input type="password" id="adm-key" placeholder="Enter TAPMINT_ADMIN_KEY" style="margin-bottom:0;flex:1;min-width:200px;" />
      <button class="btn-3d btn-g" onclick="loadPanel(true)">Unlock & Live Sync</button>
    </div>
  </div>

  <div class="grid-stat">
    <div class="stat-3d"><div class="stat-lbl">Total Members</div><div class="stat-v sky" id="st-total-u">0</div></div>
    <div class="stat-3d"><div class="stat-lbl">Active Now (15m)</div><div class="stat-v" id="st-act-u">0</div></div>
    <div class="stat-3d"><div class="stat-lbl">Offline Members</div><div class="stat-v rose" id="st-off-u">0</div></div>
    <div class="stat-3d"><div class="stat-lbl">Total Earned PTS</div><div class="stat-v gold" id="st-earned-pts">0</div></div>
    <div class="stat-3d"><div class="stat-lbl">Reserve Ledger PTS</div><div class="stat-v" id="st-res">0</div></div>
  </div>

  <div class="panel-3d">
    <div class="sec-title">
      <span>Live Source PTS Breakdown & Live Earning Feed</span>
      <span style="font-size:11px;color:#34d399;" id="live-sync-badge">● Auto-Refresh 5s</span>
    </div>
    <div class="src-grid">
      <div class="src-box"><div class="src-name">Task PTS</div><div class="src-pts" id="src-task">0</div></div>
      <div class="src-box"><div class="src-name">Game PTS</div><div class="src-pts" id="src-game">0</div></div>
      <div class="src-box"><div class="src-name">Mining PTS</div><div class="src-pts" id="src-mining">0</div></div>
      <div class="src-box"><div class="src-name">Spin PTS</div><div class="src-pts" id="src-spin">0</div></div>
      <div class="src-box"><div class="src-name">Refer PTS</div><div class="src-pts" id="src-refer">0</div></div>
    </div>
    <div class="scroll-box" id="live-earn-list">
      <div style="font-size:12px;color:#94a3b8;">অ্যাডমিন কি দিয়ে আনলক করলে লাইভ আর্নিং দেখা যাবে।</div>
    </div>
  </div>

  <div class="two-col">
    <div class="panel-3d">
      <div class="sec-title"><span>Most Hardworking Users (Top Earners)</span></div>
      <div class="scroll-box" id="top-users-list">
        <div style="font-size:12px;color:#94a3b8;">কোনো ইউজার ডেটা লোড হয়নি।</div>
      </div>
    </div>

    <div class="panel-3d">
      <div class="sec-title"><span>Saved & Verified User Wallets</span></div>
      <div class="scroll-box" id="saved-wallets-list">
        <div style="font-size:12px;color:#94a3b8;">কোনো সেভ করা ওয়ালেট লোড হয়নি।</div>
      </div>
    </div>
  </div>

  <div class="panel-3d">
    <div class="sec-title"><span>Master / Affiliate Referral Link</span></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;">
      <input type="text" id="master-ref-link" readonly style="margin-bottom:0;flex:1;min-width:220px;" placeholder="Master Affiliate Link" />
      <button class="btn-3d btn-b" onclick="copyMasterRef()">Copy Master Link</button>
    </div>
    <div style="font-size:12px;color:#94a3b8;margin-top:8px;" id="master-ref-meta">Master Affiliate Users: 0</div>
  </div>

  <div class="two-col">
    <div class="panel-3d">
      <div class="sec-title"><span>Full Site Control & Reward Settings</span></div>
      <label style="font-size:11px;color:#94a3b8;">Maintenance Mode</label>
      <select id="sc-maint">
        <option value="0">Normal Live (0)</option>
        <option value="1">Maintenance Locked (1)</option>
      </select>
      <label style="font-size:11px;color:#94a3b8;">New User Registration</label>
      <select id="sc-newu">
        <option value="1">Allow New Users (1)</option>
        <option value="0">Pause New Signups (0)</option>
      </select>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;">
        <div>
          <label style="font-size:11px;color:#94a3b8;">Task PTS</label>
          <input type="number" id="sc-tpts" value="1" />
        </div>
        <div>
          <label style="font-size:11px;color:#94a3b8;">Game PTS</label>
          <input type="number" id="sc-gpts" value="2" />
        </div>
        <div>
          <label style="font-size:11px;color:#94a3b8;">Ref Bonus</label>
          <input type="number" id="sc-rpts" value="25" />
        </div>
      </div>
      <input type="text" id="sc-ann" placeholder="Site Notice / Announcement" />
      <button class="btn-3d btn-g" style="width:100%;" onclick="saveSiteControl()">Save Site Control</button>

      <div style="margin-top:14px;padding-top:12px;border-top:1px solid rgba(148,163,184,0.16);">
        <div style="font-size:13px;font-weight:800;margin-bottom:8px;">Manual User PTS Adjust</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
          <input type="text" id="ub-uid" placeholder="user_id or tg_12345" style="margin-bottom:0;" />
          <input type="number" id="ub-delta" placeholder="+100 or -50" style="margin-bottom:0;" />
        </div>
        <button class="btn-3d btn-b" style="width:100%;margin-top:8px;" onclick="adjustUserPts()">Apply PTS Change</button>
      </div>
    </div>

    <div class="panel-3d">
      <div class="sec-title"><span>Pending Withdrawals</span></div>
      <div class="scroll-box" id="w-list"></div>
    </div>
  </div>

  <div class="two-col">
    <div class="panel-3d">
      <div class="sec-title"><span>নোট খাতা (Manual Entry)</span></div>
      <select id="nk-type">
        <option value="tier3_ad_inflow">Tier 3 Ad Inflow</option>
        <option value="withdraw_fee_inflow">Withdraw Fee Inflow</option>
        <option value="withdraw_approved_outflow">Withdraw Approved Outflow</option>
      </select>
      <input type="number" id="nk-gross" placeholder="Gross PTS" value="0" />
      <input type="number" id="nk-fee" placeholder="Fee PTS" value="0" />
      <input type="number" id="nk-net" placeholder="Net PTS" value="0" />
      <input type="text" id="nk-note" placeholder="নোট খাতার বিবরণ" />
      <button class="btn-3d btn-g" style="width:100%;" onclick="addKhata()">Save to নোট খাতা</button>
    </div>

    <div class="panel-3d">
      <div class="sec-title"><span>নোট খাতা লেজার লগ</span></div>
      <div class="scroll-box" id="nk-list"></div>
    </div>
  </div>
</div>

<script>
let PANEL_UNLOCKED = false;

function getKey() {
  return document.getElementById("adm-key").value.trim();
}

async function loadPanel(showAlertOnFail = false) {
  const k = getKey();
  if (!k) {
    if (showAlertOnFail) alert("আগে TAPMINT_ADMIN_KEY দিন");
    return;
  }
  const r = await fetch("/api/admin/overview?admin_key=" + encodeURIComponent(k)).then(x => x.json());
  if (!r.ok) {
    if (showAlertOnFail) alert(r.error || "Unauthorized");
    return;
  }
  PANEL_UNLOCKED = true;

  document.getElementById("st-total-u").textContent = r.total_users;
  document.getElementById("st-act-u").textContent = r.active_users;
  document.getElementById("st-off-u").textContent = r.offline_users;
  document.getElementById("st-earned-pts").textContent = Number(r.total_earned_pts_all || 0).toLocaleString();
  document.getElementById("st-res").textContent = Number(r.reserve_balance_pts || 0).toLocaleString();

  const st = r.source_totals || {};
  document.getElementById("src-task").textContent = Number(st.task || 0).toLocaleString();
  document.getElementById("src-game").textContent = Number(st.game || 0).toLocaleString();
  document.getElementById("src-mining").textContent = Number(st.mining || 0).toLocaleString();
  document.getElementById("src-spin").textContent = Number(st.spin || 0).toLocaleString();
  document.getElementById("src-refer").textContent = Number(st.refer || 0).toLocaleString();

  const leBox = document.getElementById("live-earn-list");
  leBox.innerHTML = "";
  if (!r.live_earnings || !r.live_earnings.length) {
    leBox.innerHTML = `<div style="font-size:12px;color:#94a3b8;">এখনো কোনো লাইভ আর্নিং লগ নেই।</div>`;
  } else {
    for (const item of r.live_earnings) {
      const div = document.createElement("div");
      div.className = "item-row";
      div.innerHTML = `
        <div>
          <strong>${item.username}</strong> <span style="font-size:11px;color:#94a3b8;">(${item.user_id})</span><br/>
          <span style="font-size:12px;color:#38bdf8;">[${item.category.toUpperCase()}]</span>
          <span style="font-size:12px;color:#cbd5e1;">${item.source_type}</span>
        </div>
        <div style="text-align:right;">
          <div style="font-size:14px;font-weight:900;color:#4ade80;">+${item.pts_delta} PTS</div>
          <div style="font-size:10px;color:#64748b;">${item.created_at}</div>
        </div>
      `;
      leBox.appendChild(div);
    }
  }

  const tuBox = document.getElementById("top-users-list");
  tuBox.innerHTML = "";
  for (let i = 0; i < (r.hardworking_users || []).length; i++) {
    const hu = r.hardworking_users[i];
    const tgTag = hu.telegram_id ? ` • TG:${hu.telegram_id}` : "";
    const div = document.createElement("div");
    div.className = "item-row";
    div.innerHTML = `
      <div>
        <strong>#${i + 1} ${hu.username}</strong> <span style="font-size:11px;color:#94a3b8;">(${hu.user_id}${tgTag})</span>
        ${hu.is_online ? `<span class="pill-on">● Active</span>` : `<span class="pill-off">Offline</span>`}<br/>
        <span style="font-size:12px;color:#cbd5e1;">Tasks Done: ${hu.tasks_done} • Bal: ${hu.pts_balance} PTS</span>
      </div>
      <div style="font-size:14px;font-weight:900;color:#facc15;">${Number(hu.total_earned_pts).toLocaleString()} PTS</div>
    `;
    tuBox.appendChild(div);
  }

  const swBox = document.getElementById("saved-wallets-list");
  swBox.innerHTML = "";
  if (!r.saved_wallets || !r.saved_wallets.length) {
    swBox.innerHTML = `<div style="font-size:12px;color:#94a3b8;">কোনো ইউজার এখনো ওয়ালেট সেভ করেনি।</div>`;
  } else {
    for (const sw of r.saved_wallets) {
      const div = document.createElement("div");
      div.className = "item-row";
      div.innerHTML = `
        <div>
          <strong>${sw.username}</strong> <span style="font-size:11px;color:#94a3b8;">(${sw.user_id})</span>
          ${sw.verified ? `<span class="pill-on">✓ Verified</span>` : `<span class="pill-off">Unverified</span>`}<br/>
          <span style="font-size:12px;color:#34d399;font-weight:700;">${sw.method}:</span>
          <span style="font-size:12px;color:#ffffff;">${sw.account_target}</span>
        </div>
        <div style="font-size:12px;color:#cbd5e1;font-weight:700;">${Number(sw.pts_balance).toLocaleString()} PTS</div>
      `;
      swBox.appendChild(div);
    }
  }

  if (r.master_affiliate) {
    document.getElementById("master-ref-link").value = r.master_affiliate.link || "";
    document.getElementById("master-ref-meta").textContent =
      `Master Code: ${r.master_affiliate.code} • Master Affiliate Users: ${r.master_affiliate.users_count}`;
  }

  if (r.site_settings) {
    document.getElementById("sc-maint").value = String(r.site_settings.maintenance_mode ?? 0);
    document.getElementById("sc-newu").value = String(r.site_settings.allow_new_users ?? 1);
    document.getElementById("sc-tpts").value = String(r.site_settings.task_reward_pts ?? 1);
    document.getElementById("sc-gpts").value = String(r.site_settings.game_reward_pts ?? 2);
    document.getElementById("sc-rpts").value = String(r.site_settings.referral_bonus_pts ?? 25);
    document.getElementById("sc-ann").value = r.site_settings.announcement_text || "";
  }

  const wl = document.getElementById("w-list");
  wl.innerHTML = "";
  if (!r.pending_withdrawals.length) {
    wl.innerHTML = `<div style="font-size:13px;color:#94a3b8;">কোনো পেন্ডিং উইথড্র নেই</div>`;
  } else {
    for (const w of r.pending_withdrawals) {
      const div = document.createElement("div");
      div.className = "item-row";
      div.innerHTML = `
        <div>
          <strong>#${w.id}</strong> • ${w.user_id} • ${w.method} (${w.account_target})<br/>
          <span style="font-size:12px;color:#94a3b8;">Req: ${w.requested_pts} | Fee: ${w.fee_pts} | Net: ${w.net_pts}</span>
        </div>
        <div style="display:flex;gap:8px;">
          <button class="btn-3d btn-g" onclick="reviewW(${w.id}, 'approve')">Approve</button>
          <button class="btn-3d btn-r" onclick="reviewW(${w.id}, 'reject')">Reject</button>
        </div>
      `;
      wl.appendChild(div);
    }
  }

  const kl = document.getElementById("nk-list");
  kl.innerHTML = "";
  for (const row of r.note_khata) {
    const div = document.createElement("div");
    div.className = "item-row";
    div.innerHTML = `
      <div>
        <strong>[${row.entry_type}]</strong> ${row.ref_id} • ${row.note_text}<br/>
        <span style="font-size:12px;color:#94a3b8;">Net: ${row.net_pts} | Reserve After: ${row.reserve_balance_pts}</span>
      </div>
      <div style="font-size:11px;color:#64748b;">${row.created_at}</div>
    `;
    kl.appendChild(div);
  }
}

function copyMasterRef() {
  const inp = document.getElementById("master-ref-link");
  if (!inp.value) return alert("আগে প্যানেল আনলক করুন");
  inp.select();
  navigator.clipboard?.writeText(inp.value);
  alert("Master Affiliate Link কপি হয়েছে");
}

async function saveSiteControl() {
  const payload = {
    maintenance_mode: parseInt(document.getElementById("sc-maint").value, 10),
    allow_new_users: parseInt(document.getElementById("sc-newu").value, 10),
    task_reward_pts: parseInt(document.getElementById("sc-tpts").value || "1", 10),
    game_reward_pts: parseInt(document.getElementById("sc-gpts").value || "2", 10),
    referral_bonus_pts: parseInt(document.getElementById("sc-rpts").value || "25", 10),
    announcement_text: document.getElementById("sc-ann").value.trim()
  };
  const r = await fetch("/api/admin/site-control", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Admin-Key": getKey() },
    body: JSON.stringify(payload)
  }).then(x => x.json());
  if (r.ok) {
    alert("Site Control সেভ হয়েছে");
    loadPanel(false);
  } else {
    alert(r.error || "Failed");
  }
}

async function adjustUserPts() {
  const payload = {
    user_id: document.getElementById("ub-uid").value.trim(),
    delta_pts: parseInt(document.getElementById("ub-delta").value || "0", 10)
  };
  const r = await fetch("/api/admin/user-balance", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Admin-Key": getKey() },
    body: JSON.stringify(payload)
  }).then(x => x.json());
  if (r.ok) {
    alert(`Updated ${r.user_id} balance -> ${r.new_balance} PTS`);
    loadPanel(false);
  } else {
    alert(r.error || "Failed");
  }
}

async function reviewW(wid, decision) {
  const r = await fetch("/api/admin/withdraw/review", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Admin-Key": getKey() },
    body: JSON.stringify({ withdraw_id: wid, decision })
  }).then(x => x.json());
  if (r.ok) loadPanel(false);
  else alert(r.error || "Failed");
}

async function addKhata() {
  const payload = {
    entry_type: document.getElementById("nk-type").value,
    gross_pts: parseInt(document.getElementById("nk-gross").value || "0", 10),
    fee_pts: parseInt(document.getElementById("nk-fee").value || "0", 10),
    net_pts: parseInt(document.getElementById("nk-net").value || "0", 10),
    note_text: document.getElementById("nk-note").value.trim() || "নোট খাতা এন্ট্রি"
  };
  const r = await fetch("/api/admin/note-khata/add", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Admin-Key": getKey() },
    body: JSON.stringify(payload)
  }).then(x => x.json());
  if (r.ok) {
    document.getElementById("nk-note").value = "";
    loadPanel(false);
  } else {
    alert(r.error || "Failed");
  }
}

setInterval(() => {
  if (PANEL_UNLOCKED && getKey()) {
    loadPanel(false);
  }
}, 5000);
</script>
</body>
</html>"""


@app.route("/")
def index():
    return MINI_APP_HTML


@app.route("/admin")
def admin_page():
    return ADMIN_3D_HTML


init_db()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
