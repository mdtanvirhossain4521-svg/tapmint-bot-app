import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
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

HTML_CONTENT = """<!DOCTYPE html>
<html lang="bn">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>TapMint • Mining & Tasks</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    body { font-family: Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 16px; }
    .card { background: #1e293b; border-radius: 12px; padding: 16px; margin-bottom: 14px; border: 1px solid #334155; }
    .header-brand { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
    .badge { background: #064e3b; color: #34d399; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: bold; }
    .section-tag { display: inline-block; font-size: 12px; padding: 3px 8px; border-radius: 6px; background: #334155; color: #e2e8f0; margin-bottom: 6px; }
    button { background: #10b981; color: #fff; border: none; padding: 10px 14px; border-radius: 8px; cursor: pointer; width: 100%; margin-top: 8px; font-weight: bold; font-size: 14px; }
    button:hover { background: #059669; }
    button.monetag-btn { background: #0284c7; }
    button.monetag-btn:hover { background: #0369a1; }
    input, select { width: 100%; padding: 10px; margin-top: 8px; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: #fff; box-sizing: border-box; }
    .small { font-size: 13px; color: #94a3b8; line-height: 1.5; }
    .status-box { margin-top: 10px; padding: 10px; border-radius: 8px; background: #0f172a; color: #38bdf8; font-size: 13px; }
  </style>
</head>
<body>
  <div class="card">
    <div class="header-brand">
      <h2 style="margin:0;">TapMint</h2>
      <span class="badge">Mining & Tasks</span>
    </div>
    <p>পয়েন্ট: <strong id="points">0</strong></p>
    <p>সম্পন্ন টাস্ক: <strong id="tasks">0</strong></p>
    <p>অ্যাক্টিভ রেফারেল: <strong id="refs">0</strong></p>
    <p class="small">রেফার না করলেও মিনিমাম পয়েন্ট হলে উইথড্র করতে পারবেন। রেফার করলে টাস্ক বোনাস বাড়বে।</p>
  </div>

  <div class="card">
    <h3>ডেইলি টাস্ক (মোট ২০টি লিংক)</h3>
    <p class="small">প্রতিটি লিংক ভিজিট করে ফিরে এলে সার্ভার থেকে পয়েন্ট যোগ হবে।</p>

    <span class="section-tag">Adsterra Smart Links (১ – ১০)</span>
    <button onclick="doTask('adsterra_1', 'https://asiafilm.org/4/2da793d72cd322b49d8bb9d66fc974e7')">টাস্ক ১: স্মার্ট লিংক ভিজিট (+পয়েন্ট)</button>
    <button onclick="doTask('adsterra_2', 'https://asiafilm.org/4/3bd5bca9029900a8d0d2bb526ebd7214')">টাস্ক ২: স্মার্ট লিংক ভিজিট (+পয়েন্ট)</button>
    <button onclick="doTask('adsterra_3', 'https://asiafilm.org/4/224868d40ac462d276354c5696553960')">টাস্ক ৩: স্মার্ট লিংক ভিজিট (+পয়েন্ট)</button>
    <button onclick="doTask('adsterra_4', 'https://asiafilm.org/4/2a16c7d7870cf593884b4976629a6156')">টাস্ক ৪: স্মার্ট লিংক ভিজিট (+পয়েন্ট)</button>
    <button onclick="doTask('adsterra_5', 'https://asiafilm.org/4/4f3af0df8bb071b2232440532691af67')">টাস্ক ৫: স্মার্ট লিংক ভিজিট (+পয়েন্ট)</button>
    <button onclick="doTask('adsterra_6', 'https://asiafilm.org/4/5909d9fd3d02125d0447b6d1702377d7')">টাস্ক ৬: স্মার্ট লিংক ভিজিট (+পয়েন্ট)</button>
    <button onclick="doTask('adsterra_7', 'https://asiafilm.org/4/c75201a3ea80e241a6008c8f503e0855')">টাস্ক ৭: স্মার্ট লিংক ভিজিট (+পয়েন্ট)</button>
    <button onclick="doTask('adsterra_8', 'https://asiafilm.org/4/9b1be208097bfdbce8298db933df0875')">টাস্ক ৮: স্মার্ট লিংক ভিজিট (+পয়েন্ট)</button>
    <button onclick="doTask('adsterra_9', 'https://asiafilm.org/4/5bac8f36e93727dc1e10c13f28ad12ba')">টাস্ক ৯: স্মার্ট লিংক ভিজিট (+পয়েন্ট)</button>
    <button onclick="doTask('adsterra_10', 'https://asiafilm.org/4/948938a94d72df36b23ba9f97ef3bfff')">টাস্ক ১০: স্মার্ট লিংক ভিজিট (+পয়েন্ট)</button>

    <div style="margin-top: 14px;">
      <span class="section-tag">Monetag Links (১১ – ২০)</span>
    </div>
    <button class="monetag-btn" onclick="doTask('monetag_11', 'https://uplcm.com/4/12351466')">টাস্ক ১১: Monetag লিংক ভিজিট (+পয়েন্ট)</button>
    <button class="monetag-btn" onclick="doTask('monetag_12', 'https://uplcm.com/4/12351467')">টাস্ক ১২: Monetag লিংক ভিজিট (+পয়েন্ট)</button>
    <button class="monetag-btn" onclick="doTask('monetag_13', 'https://uplcm.com/4/12351468')">টাস্ক ১৩: Monetag লিংক ভিজিট (+পয়েন্ট)</button>
    <button class="monetag-btn" onclick="doTask('monetag_14', 'https://uplcm.com/4/12351473')">টাস্ক ১৪: Monetag লিংক ভিজিট (+পয়েন্ট)</button>
    <button class="monetag-btn" onclick="doTask('monetag_15', 'https://uplcm.com/4/12351474')">টাস্ক ১৫: Monetag লিংক ভিজিট (+পয়েন্ট)</button>
    <button class="monetag-btn" onclick="doTask('monetag_16', 'https://uplcm.com/4/12351475')">টাস্ক ১৬: Monetag লিংক ভিজিট (+পয়েন্ট)</button>
    <button class="monetag-btn" onclick="doTask('monetag_17', 'https://uplcm.com/4/12351476')">টাস্ক ১৭: Monetag লিংক ভিজিট (+পয়েন্ট)</button>
    <button class="monetag-btn" onclick="doTask('monetag_18', 'https://uplcm.com/4/12351477')">টাস্ক ১৮: Monetag লিংক ভিজিট (+পয়েন্ট)</button>
    <button class="monetag-btn" onclick="doTask('monetag_19', 'https://uplcm.com/4/12351478')">টাস্ক ১৯: Monetag লিংক ভিজিট (+পয়েন্ট)</button>
    <button class="monetag-btn" onclick="doTask('monetag_20', 'https://uplcm.com/4/12351479')">টাস্ক ২০: Monetag লিংক ভিজিট (+পয়েন্ট)</button>
  </div>

  <div class="card">
    <h3>রেফারেল লিংক</h3>
    <input id="refLink" readonly />
    <button onclick="copyRefLink()">রেফারেল লিংক কপি করুন</button>
  </div>

  <div class="card">
    <h3>উইথড্র (bKash / Nagad / Binance USDT)</h3>
    <select id="method">
      <option value="bkash">bKash</option>
      <option value="nagad">Nagad</option>
      <option value="binance_usdt">Binance (USDT)</option>
    </select>
    <input id="accountInfo" placeholder="বিকাশ/নগদ নম্বর বা Binance USDT অ্যাড্রেস" />
    <input id="withdrawPoints" type="number" placeholder="কত পয়েন্ট তুলতে চান (যেমন 1000)" />
    <button onclick="submitWithdraw()">উইথড্র রিকোয়েস্ট পাঠান</button>
    <div id="statusMsg" class="status-box">রেডি</div>
  </div>

  <script>
    const tg = window.Telegram.WebApp;
    tg.expand();

    const tgUser = tg.initDataUnsafe?.user || { id: 100001, username: "test_user" };
    const startParam = tg.initDataUnsafe?.start_param || null;
    const botUsername = "tapmint99_bot";

    document.getElementById("refLink").value =
      `https://t.me/${botUsername}?start=${tgUser.id}`;

    function setStatus(msg) {
      document.getElementById("statusMsg").innerText = msg;
    }

    function copyRefLink() {
      const input = document.getElementById("refLink");
      input.select();
      navigator.clipboard?.writeText(input.value);
      setStatus("রেফারেল লিংক কপি হয়েছে!");
    }

    async function initApp() {
      const res = await fetch("/api/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          telegram_id: tgUser.id,
          username: tgUser.username,
          referrer_id: startParam ? Number(startParam) : null
        })
      });
      const data = await res.json();
      renderUser(data);
    }

    function renderUser(u) {
      document.getElementById("points").innerText = u.points;
      document.getElementById("tasks").innerText = u.completed_tasks;
      document.getElementById("refs").innerText = u.active_referrals;
    }

    async function doTask(taskCode, url) {
      window.open(url, "_blank");
      const res = await fetch("/api/complete-task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ telegram_id: tgUser.id, task_code: taskCode })
      });
      const data = await res.json();
      if (res.ok) {
        renderUser(data.user);
        setStatus(`+${data.earned_points} পয়েন্ট যোগ হয়েছে (${data.bonus_pct}% রেফারেল বোনাসসহ)।`);
      }
    }

    async function submitWithdraw() {
      const method = document.getElementById("method").value;
      const account_info = document.getElementById("accountInfo").value;
      const points = Number(document.getElementById("withdrawPoints").value);

      const res = await fetch("/api/withdraw", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ telegram_id: tgUser.id, method, account_info, points })
      });
      const data = await res.json();
      if (res.ok) {
        renderUser(data.user);
        setStatus(`উইথড্র রিকোয়েস্ট জমা হয়েছে (${data.amount_bdt} টাকা সমতুল্য)।`);
      } else {
        setStatus(data.detail || "সমস্যা হয়েছে");
      }
    }

    initApp();
  </script>
</body>
</html>"""


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


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(content=HTML_CONTENT)


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
