import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from database import get_conn, init_db

app = FastAPI(title="TapMint Mini App")

# --- লাভ ও রিওয়ার্ড কনফিগারেশন (আপনার অ্যাড রেভিনিউ অনুযায়ী ঠিক করবেন) ---
BASE_TASK_POINTS = 10          # প্রতি টাস্কে বেস পয়েন্ট
REF_BONUS_PCT = 5            # প্রতি অ্যাক্টিভ রেফারেলে +5% বোনাস
MAX_REF_BONUS_PCT = 30       # সর্বোচ্চ রেফারেল বোনাস ক্যাপ 30%
ACTIVE_REF_TASK_REQ = 3      # রেফারেল "অ্যাক্টিভ" হতে নতুন ইউজারকে 3টি টাস্ক করতে হবে
POINTS_PER_BDT = 10          # 10 পয়েন্ট = 1 টাকা
MIN_WITHDRAW_POINTS = 1000   # রেফার ছাড়াই মিনিমাম উইথড্র 1000 পয়েন্ট
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "change-this-admin-key")


class AuthPayload(BaseModel):
    telegram_id: int
    username: str | None = None
    referrer_id: int | None = None


class TaskCompletePayload(BaseModel):
    telegram_id: int
    task_code: str


class WithdrawPayload(BaseModel):
    telegram_id: int
    method: str        # "bkash", "nagad", "binance_usdt"
    account_info: str  # নম্বর বা USDT ওয়ালেট অ্যাড্রেস
    points: int


class AdminActionPayload(BaseModel):
    secret: str
    withdrawal_id: int
    action: str  # "approve" বা "reject"


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def home():
    return FileResponse("templates/index.html")


@app.post("/api/auth")
def auth_user(payload: AuthPayload):
    conn = get_conn()
    cur = conn.cursor()

    user = cur.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (payload.telegram_id,)
    ).fetchone()

    if not user:
        ref_id = None
        if payload.referrer_id and payload.referrer_id != payload.telegram_id:
            ref_exists = cur.execute(
                "SELECT telegram_id FROM users WHERE telegram_id = ?",
                (payload.referrer_id,),
            ).fetchone()
            if ref_exists:
                ref_id = payload.referrer_id

        cur.execute(
            """
            INSERT INTO users (telegram_id, username, referred_by)
            VALUES (?, ?, ?)
            """,
            (payload.telegram_id, payload.username or "", ref_id),
        )
        conn.commit()
        user = cur.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (payload.telegram_id,)
        ).fetchone()

    conn.close()
    return dict(user)


@app.post("/api/complete-task")
def complete_task(payload: TaskCompletePayload):
    conn = get_conn()
    cur = conn.cursor()

    user = cur.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (payload.telegram_id,)
    ).fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    bonus_pct = min(user["active_referrals"] * REF_BONUS_PCT, MAX_REF_BONUS_PCT)
    earned = round(BASE_TASK_POINTS * (1 + bonus_pct / 100))

    new_tasks = user["completed_tasks"] + 1
    new_points = user["points"] + earned

    cur.execute(
        """
        UPDATE users
        SET points = ?, completed_tasks = ?
        WHERE telegram_id = ?
        """,
        (new_points, new_tasks, payload.telegram_id),
    )

    cur.execute(
        """
        INSERT INTO task_logs (telegram_id, task_code, earned_points)
        VALUES (?, ?, ?)
        """,
        (payload.telegram_id, payload.task_code, earned),
    )

    if (
        user["referred_by"]
        and user["referral_counted"] == 0
        and new_tasks >= ACTIVE_REF_TASK_REQ
    ):
        cur.execute(
            """
            UPDATE users
            SET active_referrals = active_referrals + 1
            WHERE telegram_id = ?
            """,
            (user["referred_by"],),
        )
        cur.execute(
            """
            UPDATE users
            SET referral_counted = 1
            WHERE telegram_id = ?
            """,
            (payload.telegram_id,),
        )

    conn.commit()
    updated = cur.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (payload.telegram_id,)
    ).fetchone()
    conn.close()

    return {
        "earned_points": earned,
        "bonus_pct": bonus_pct,
        "user": dict(updated),
    }


@app.post("/api/withdraw")
def request_withdraw(payload: WithdrawPayload):
    if payload.method not in {"bkash", "nagad", "binance_usdt"}:
        raise HTTPException(status_code=400, detail="Invalid payment method")

    if not payload.account_info.strip():
        raise HTTPException(status_code=400, detail="Account info required")

    if payload.points < MIN_WITHDRAW_POINTS:
        raise HTTPException(
            status_code=400,
            detail=f"Minimum withdraw is {MIN_WITHDRAW_POINTS} points",
        )

    conn = get_conn()
    cur = conn.cursor()

    user = cur.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (payload.telegram_id,)
    ).fetchone()
    if not user or user["points"] < payload.points:
        conn.close()
        raise HTTPException(status_code=400, detail="Insufficient points")

    amount_bdt = round(payload.points / POINTS_PER_BDT, 2)

    cur.execute(
        """
        UPDATE users
        SET points = points - ?
        WHERE telegram_id = ?
        """,
        (payload.points, payload.telegram_id),
    )

    cur.execute(
        """
        INSERT INTO withdrawals (telegram_id, method, account_info, points_used, amount_bdt)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            payload.telegram_id,
            payload.method,
            payload.account_info.strip(),
            payload.points,
            amount_bdt,
        ),
    )

    conn.commit()
    updated = cur.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (payload.telegram_id,)
    ).fetchone()
    conn.close()

    return {
        "message": "Withdraw request submitted for manual review",
        "amount_bdt": amount_bdt,
        "user": dict(updated),
    }


@app.get("/api/admin/withdrawals")
def list_withdrawals(secret: str):
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM withdrawals ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/admin/withdrawals/action")
def handle_withdrawal_action(payload: AdminActionPayload):
    if payload.secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if payload.action not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Invalid action")

    conn = get_conn()
    cur = conn.cursor()

    w = cur.execute(
        "SELECT * FROM withdrawals WHERE id = ?", (payload.withdrawal_id,)
    ).fetchone()
    if not w:
        conn.close()
        raise HTTPException(status_code=404, detail="Withdrawal not found")

    if w["status"] != "pending":
        conn.close()
        raise HTTPException(status_code=400, detail="Already processed")

    if payload.action == "approve":
        cur.execute(
            "UPDATE withdrawals SET status = 'approved' WHERE id = ?",
            (payload.withdrawal_id,),
        )
    else:
        cur.execute(
            "UPDATE users SET points = points + ? WHERE telegram_id = ?",
            (w["points_used"], w["telegram_id"]),
        )
        cur.execute(
            "UPDATE withdrawals SET status = 'rejected' WHERE id = ?",
            (payload.withdrawal_id,),
        )

    conn.commit()
    conn.close()
    return {"status": "ok", "withdrawal_id": payload.withdrawal_id, "action": payload.action}
