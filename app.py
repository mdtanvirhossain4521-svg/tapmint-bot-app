import os
import sqlite3
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from database import get_conn, init_db

app = FastAPI(title="TapMint Mini App")

# --- কনফিগারেশন ---
BASE_TASK_POINTS = 10            # প্রতি লিংক টাস্কে বেস পয়েন্ট
DAILY_CHECKIN_POINTS = 10        # ডেইলি চেক-ইন বোনাস
MINING_PULSE_POINTS = 5          # মাইনিং পালস বোনাস
MINING_PULSE_COOLDOWN_SEC = 1800 # ৩০ মিনিট (১৮০০ সেকেন্ড) পরপর মাইনিং পালস
QUIZ_POINTS = 10                 # কুইজ সঠিক উত্তরে পয়েন্ট
MYSTERY_BOX_MAX_POINTS = 15      # মিস্ট্রি বক্স সর্বোচ্চ বেস পয়েন্ট
SESSION_BONUS_POINTS = 25        # একটি সেশনের সব ৫টি লিংক শেষ করলে বোনাস

GAME_REWARD_POINTS = {
    "game_catch_dodge": 10,
    "game_merge_2048": 12,
    "game_snake": 12,
}

REF_BONUS_PCT = 5                # প্রতি অ্যাক্টিভ রেফারেলে +৫% বোনাস
MAX_REF_BONUS_PCT = 30           # সর্বোচ্চ রেফারেল বোনাস ৩০%
ACTIVE_REF_TASK_REQ = 3          # রেফারেল অ্যাক্টিভ হতে কমপক্ষে ৩টি টাস্ক করতে হবে
POINTS_PER_BDT = 10              # ১০ পয়েন্ট = ১ টাকা
POINTS_PER_USD = 1000            # ১,০০০ পয়েন্ট = ১ ডলার ($১ = ১০০ টাকা)
MIN_WITHDRAW_POINTS = 1000       # রেফার ছাড়াই মিনিমাম উইথড্র ১,০০০ পয়েন্ট
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "change-this-admin-key")

SESSION_TASKS = {
    "session_1": [
        {"code": "task_1", "title": "Daily Reward #01", "subtitle": "Quick Partner Visit", "url": "https://asiafilm.org/4/2da793d72cd322b49d8bb9d66fc974e7"},
        {"code": "task_2", "title": "Quick Check-in #02", "subtitle": "Featured Offer", "url": "https://asiafilm.org/4/3bd5bca9029900a8d0d2bb526ebd7214"},
        {"code": "task_3", "title": "Bonus Mission #03", "subtitle": "Sponsored Spot", "url": "https://asiafilm.org/4/224868d40ac462d276354c5696553960"},
        {"code": "task_4", "title": "Spotlight Deal #04", "subtitle": "Partner Promo", "url": "https://asiafilm.org/4/2a16c7d7870cf593884b4976629a6156"},
        {"code": "task_5", "title": "Reward Drop #05", "subtitle": "Daily Mission", "url": "https://asiafilm.org/4/4f3af0df8bb071b2232440532691af67"},
    ],
    "session_2": [
        {"code": "task_6", "title": "Daily Reward #06", "subtitle": "Quick Partner Visit", "url": "https://asiafilm.org/4/5909d9fd3d02125d0447b6d1702377d7"},
        {"code": "task_7", "title": "Quick Check-in #07", "subtitle": "Featured Offer", "url": "https://asiafilm.org/4/c75201a3ea80e241a6008c8f503e0855"},
        {"code": "task_8", "title": "Bonus Mission #08", "subtitle": "Sponsored Spot", "url": "https://asiafilm.org/4/9b1be208097bfdbce8298db933df0875"},
        {"code": "task_9", "title": "Spotlight Deal #09", "subtitle": "Partner Promo", "url": "https://asiafilm.org/4/5bac8f36e93727dc1e10c13f28ad12ba"},
        {"code": "task_10", "title": "Reward Drop #10", "subtitle": "Daily Mission", "url": "https://asiafilm.org/4/948938a94d72df36b23ba9f97ef3bfff"},
    ],
    "session_3": [
        {"code": "task_11", "title": "Daily Reward #11", "subtitle": "Partner Spotlight", "url": "https://uplcm.com/4/12351466"},
        {"code": "task_12", "title": "Quick Check-in #12", "subtitle": "Reward Check", "url": "https://uplcm.com/4/12351467"},
        {"code": "task_13", "title": "Bonus Mission #13", "subtitle": "Featured Promo", "url": "https://uplcm.com/4/12351468"},
        {"code": "task_14", "title": "Spotlight Deal #14", "subtitle": "Daily Offer", "url": "https://uplcm.com/4/12351473"},
        {"code": "task_15", "title": "Reward Drop #15", "subtitle": "Sponsor Mission", "url": "https://uplcm.com/4/12351474"},
    ],
    "session_4": [
        {"code": "task_16", "title": "Daily Reward #16", "subtitle": "Partner Spotlight", "url": "https://uplcm.com/4/12351475"},
        {"code": "task_17", "title": "Quick Check-in #17", "subtitle": "Reward Check", "url": "https://uplcm.com/4/12351476"},
        {"code": "task_18", "title": "Bonus Mission #18", "subtitle": "Featured Promo", "url": "https://uplcm.com/4/12351477"},
        {"code": "task_19", "title": "Spotlight Deal #19", "subtitle": "Daily Offer", "url": "https://uplcm.com/4/12351478"},
        {"code": "task_20", "title": "Reward Drop #20", "subtitle": "Sponsor Mission", "url": "https://uplcm.com/4/12351479"},
    ],
}

ALL_TASK_CODES = {
    item["code"]
    for tasks in SESSION_TASKS.values()
    for item in tasks
}


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def ensure_extra_tables():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            claim_key TEXT NOT NULL,
            claim_date TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            UNIQUE(telegram_id, claim_key, claim_date)
        )
        """
    )
    conn.commit()
    conn.close()


def has_claimed_today(cur: sqlite3.Cursor, telegram_id: int, claim_key: str) -> bool:
    row = cur.execute(
        """
        SELECT 1 FROM user_claims
        WHERE telegram_id = ? AND claim_key = ? AND claim_date = ?
        """,
        (telegram_id, claim_key, today_str()),
    ).fetchone()
    return row is not None


def record_claim(cur: sqlite3.Cursor, telegram_id: int, claim_key: str):
    cur.execute(
        """
        INSERT OR IGNORE INTO user_claims (telegram_id, claim_key, claim_date, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (telegram_id, claim_key, today_str(), now_ts()),
    )


def calc_earned_points(active_referrals: int, base_pts: int) -> tuple[int, int]:
    bonus_pct = min(active_referrals * REF_BONUS_PCT, MAX_REF_BONUS_PCT)
    earned = max(1, round(base_pts * (1 + bonus_pct / 100)))
    return earned, bonus_pct


def apply_referral_activation(cur: sqlite3.Cursor, user_row: sqlite3.Row, new_tasks_count: int):
    if (
        user_row["referred_by"]
        and user_row["referral_counted"] == 0
        and new_tasks_count >= ACTIVE_REF_TASK_REQ
    ):
        cur.execute(
            """
            UPDATE users
            SET active_referrals = active_referrals + 1
            WHERE telegram_id = ?
            """,
            (user_row["referred_by"],),
        )
        cur.execute(
            """
            UPDATE users
            SET referral_counted = 1
            WHERE telegram_id = ?
            """,
            (user_row["telegram_id"],),
        )


def build_state_payload(cur: sqlite3.Cursor, telegram_id: int) -> dict:
    user = cur.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    day = today_str()
    ts = now_ts()

    claimed_rows = cur.execute(
        """
        SELECT claim_key, created_at FROM user_claims
        WHERE telegram_id = ? AND claim_date = ?
        """,
        (telegram_id, day),
    ).fetchall()
    claimed_today = {r["claim_key"] for r in claimed_rows}

    last_pulse = cur.execute(
        """
        SELECT created_at FROM user_claims
        WHERE telegram_id = ? AND claim_key = 'mining_pulse'
        ORDER BY id DESC LIMIT 1
        """,
        (telegram_id,),
    ).fetchone()

    pulse_remaining_sec = 0
    if last_pulse:
        elapsed = ts - int(last_pulse["created_at"])
        if elapsed < MINING_PULSE_COOLDOWN_SEC:
            pulse_remaining_sec = MINING_PULSE_COOLDOWN_SEC - elapsed

    completed_today_tasks = [c for c in claimed_today if c in ALL_TASK_CODES]

    session_status = {}
    for s_key, items in SESSION_TASKS.items():
        codes = [x["code"] for x in items]
        done_cnt = sum(1 for c in codes if c in claimed_today)
        session_status[s_key] = {
            "done": done_cnt,
            "total": len(codes),
            "all_done": done_cnt == len(codes),
            "bonus_claimed": f"session_bonus_{s_key}" in claimed_today,
        }

    done_games = [g for g in GAME_REWARD_POINTS if g in claimed_today]

    return {
        "user": dict(user),
        "today_completed_count": len(completed_today_tasks),
        "completed_today_codes": completed_today_tasks,
        "daily_checkin_done": "daily_checkin" in claimed_today,
        "quiz_done": "quick_quiz" in claimed_today,
        "mystery_box_done": "mystery_box" in claimed_today,
        "done_games": done_games,
        "pulse_remaining_sec": pulse_remaining_sec,
        "sessions": session_status,
    }


HTML_CONTENT = """<!DOCTYPE html>
<html lang="bn">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>TapMint • Mining, Tasks & Games</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {
      --bg-dark: #0b1120;
      --card-bg: #131e32;
      --card-soft: #182337;
      --primary: #10b981;
      --primary-hover: #059669;
      --accent: #38bdf8;
      --danger: #ef4444;
      --text-white: #ffffff;
      --text-muted: #94a3b8;
      --border-color: #1e293b;
      --glow-emerald: rgba(16, 185, 129, 0.16);
    }
    body {
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      background: var(--bg-dark);
      color: var(--text-white);
      margin: 0;
      padding: 0 0 82px 0;
      box-sizing: border-box;
      user-select: none;
    }
    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 16px;
      border-bottom: 1px solid var(--border-color);
      background: rgba(11, 17, 32, 0.9);
      backdrop-filter: blur(10px);
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .header-logo {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .logo-icon {
      width: 28px;
      height: 28px;
      background: var(--primary);
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: bold;
      color: #04130e;
      box-shadow: 0 0 10px var(--primary);
    }
    .header-title {
      font-size: 17px;
      font-weight: 700;
    }
    .verified-badge {
      color: var(--primary);
      font-size: 14px;
    }
    .container {
      padding: 16px;
    }
    .tab-content {
      display: none;
    }
    .tab-content.active {
      display: block;
    }
    .card {
      background: var(--card-bg);
      border-radius: 16px;
      padding: 16px;
      margin-bottom: 14px;
      border: 1px solid var(--border-color);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.22);
    }
    .hero-card {
      background: linear-gradient(135deg, #132237 0%, #0d1b2d 100%);
      border: 1px solid rgba(16, 185, 129, 0.3);
      box-shadow: 0 0 16px var(--glow-emerald);
      text-align: center;
    }
    .balance-label {
      font-size: 12px;
      color: var(--text-muted);
    }
    .balance-points {
      font-size: 32px;
      font-weight: 800;
      margin: 8px 0;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
    }
    .balance-currency {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: center;
      gap: 8px;
      margin-bottom: 10px;
      font-size: 13px;
      font-weight: 600;
    }
    .currency-pill {
      background: rgba(56, 189, 248, 0.12);
      color: var(--accent);
      padding: 4px 10px;
      border-radius: 999px;
      border: 1px solid rgba(56, 189, 248, 0.25);
    }
    .currency-pill.bdt {
      background: rgba(16, 185, 129, 0.12);
      color: var(--primary);
      border: 1px solid rgba(16, 185, 129, 0.25);
    }
    .badge-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: center;
      margin-top: 8px;
    }
    .badge-pill {
      background: rgba(16, 185, 129, 0.15);
      color: var(--primary);
      padding: 4px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }
    .grid-stats {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-bottom: 14px;
    }
    .stat-box {
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 12px;
      text-align: center;
    }
    .stat-box-title {
      font-size: 12px;
      color: var(--text-muted);
      margin-bottom: 4px;
    }
    .stat-box-value {
      font-size: 16px;
      font-weight: 700;
    }
    .progress-bar-bg {
      background: #1e293b;
      height: 8px;
      border-radius: 999px;
      overflow: hidden;
      margin-top: 8px;
    }
    .progress-bar-fill {
      background: var(--primary);
      height: 100%;
      width: 0%;
      border-radius: 999px;
      transition: width 0.3s ease;
    }
    .session-grid {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 6px;
      margin-bottom: 14px;
    }
    .session-card {
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 10px;
      padding: 8px 4px;
      text-align: center;
      cursor: pointer;
    }
    .session-card.active {
      border-color: var(--primary);
      background: rgba(16, 185, 129, 0.14);
    }
    .session-card-title {
      font-size: 11px;
      font-weight: 700;
    }
    .session-card-sub {
      font-size: 10px;
      color: var(--text-muted);
      margin-top: 2px;
    }
    .task-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      background: var(--card-soft);
      border: 1px solid var(--border-color);
      padding: 12px;
      border-radius: 12px;
      margin-bottom: 8px;
    }
    .task-info {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .task-title {
      font-size: 13px;
      font-weight: 700;
    }
    .task-sub {
      font-size: 11px;
      color: var(--text-muted);
    }
    .task-reward {
      font-size: 11px;
      color: var(--primary);
      font-weight: 600;
    }
    .action-btn {
      background: var(--primary);
      color: #04130e;
      border: none;
      padding: 8px 12px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }
    .action-btn:hover {
      background: var(--primary-hover);
    }
    .action-btn.done, .action-btn:disabled {
      background: #1e293b;
      color: var(--text-muted);
      border: 1px solid #334155;
      cursor: default;
    }
    .action-btn.done {
      color: var(--primary);
      border-color: rgba(16, 185, 129, 0.35);
    }
    .box-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-top: 8px;
    }
    .box-choice {
      background: var(--card-soft);
      border: 1px solid #334155;
      border-radius: 10px;
      padding: 12px 6px;
      text-align: center;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
    }
    .quiz-opts {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-top: 8px;
    }
    /* Games Arena */
    .game-arena {
      background: #0c1628;
      border: 1px solid #26354d;
      border-radius: 14px;
      padding: 12px;
      margin-top: 10px;
    }
    .game-hud {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 12px;
      color: var(--accent);
      font-weight: 700;
      margin-bottom: 8px;
    }
    .catch-canvas {
      position: relative;
      width: 100%;
      height: 220px;
      background: #080f1c;
      border: 1px solid #1e293b;
      border-radius: 10px;
      overflow: hidden;
      touch-action: none;
    }
    .catch-item {
      position: absolute;
      width: 28px;
      height: 28px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 13px;
      font-weight: 800;
      transform: translate(-50%, -50%);
    }
    .catch-coin {
      background: rgba(16, 185, 129, 0.25);
      border: 1.5px solid var(--primary);
      color: var(--primary);
    }
    .catch-bomb {
      background: rgba(239, 68, 68, 0.25);
      border: 1.5px solid var(--danger);
      color: #fca5a5;
    }
    .catch-basket {
      position: absolute;
      bottom: 8px;
      width: 64px;
      height: 16px;
      background: linear-gradient(90deg, var(--primary), var(--accent));
      border-radius: 999px;
      transform: translateX(-50%);
      left: 50%;
    }
    .merge-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin: 8px 0;
    }
    .merge-tile {
      height: 58px;
      background: #132036;
      border: 1px solid #253652;
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 18px;
      font-weight: 800;
      color: #e2e8f0;
    }
    .merge-tile.val-2 { background: #16324f; color: #7dd3fc; }
    .merge-tile.val-4 { background: #143d48; color: #5eead4; }
    .merge-tile.val-8 { background: #124838; color: #34d399; }
    .merge-tile.val-16 { background: #1e4b2b; color: #a7f3d0; }
    .merge-tile.val-32, .merge-tile.val-64, .merge-tile.val-128 {
      background: #059669;
      color: #ffffff;
    }
    .dpad {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 6px;
      max-width: 190px;
      margin: 8px auto 0 auto;
    }
    .dpad-btn {
      background: #1e293b;
      color: #fff;
      border: 1px solid #334155;
      border-radius: 8px;
      padding: 8px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
    }
    .snake-grid {
      display: grid;
      grid-template-columns: repeat(9, 1fr);
      gap: 2px;
      background: #080f1c;
      border: 1px solid #1e293b;
      border-radius: 10px;
      padding: 6px;
      margin: 8px auto;
      max-width: 270px;
    }
    .snake-cell {
      aspect-ratio: 1 / 1;
      background: #101b2e;
      border-radius: 3px;
    }
    .snake-cell.body {
      background: var(--primary);
    }
    .snake-cell.head {
      background: #6ee7b7;
    }
    .snake-cell.food {
      background: #f59e0b;
      border-radius: 50%;
    }
    .input-group {
      margin-bottom: 12px;
    }
    .input-label {
      font-size: 12px;
      color: var(--text-muted);
      margin-bottom: 4px;
      display: block;
    }
    input {
      width: 100%;
      padding: 10px;
      border-radius: 8px;
      border: 1px solid #334155;
      background: #0f172a;
      color: #fff;
      box-sizing: border-box;
      font-size: 13px;
    }
    .method-selector {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-bottom: 12px;
    }
    .method-btn {
      background: #1e293b;
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 9px 6px;
      text-align: center;
      cursor: pointer;
      font-size: 12px;
      font-weight: 700;
      color: var(--text-muted);
    }
    .method-btn.active {
      border-color: var(--primary);
      background: rgba(16, 185, 129, 0.12);
      color: var(--primary);
    }
    .submit-btn {
      background: var(--primary);
      color: #04130e;
      border: none;
      padding: 12px;
      border-radius: 10px;
      width: 100%;
      font-weight: 700;
      font-size: 13px;
      cursor: pointer;
    }
    .rules-list {
      padding-left: 18px;
      margin: 0;
      font-size: 12px;
      color: var(--text-muted);
      line-height: 1.65;
    }
    .status-box {
      margin-top: 10px;
      padding: 9px;
      border-radius: 8px;
      background: #0f172a;
      color: var(--accent);
      font-size: 12px;
      text-align: center;
    }
    .nav-bar {
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      background: #0d1527;
      border-top: 1px solid var(--border-color);
      display: flex;
      justify-content: space-around;
      padding: 8px 0;
      z-index: 100;
    }
    .nav-item {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 3px;
      color: var(--text-muted);
      font-size: 11px;
      cursor: pointer;
      flex: 1;
    }
    .nav-item.active {
      color: var(--primary);
      font-weight: 700;
    }
    .nav-icon {
      font-size: 17px;
    }
  </style>
</head>
<body>

  <div class="header">
    <div class="header-logo">
      <div class="logo-icon">T</div>
      <div class="header-title">TapMint <span class="verified-badge">✓</span></div>
    </div>
    <div style="font-size: 12px; color: var(--text-muted);">bot</div>
  </div>

  <div class="container">

    <!-- === HOME TAB === -->
    <div id="tab-home" class="tab-content active">
      <div class="card hero-card">
        <div class="balance-label">Total Balance / মোট ব্যালেন্স</div>
        <div class="balance-points">
          <span>🪙</span> <span id="home-points">0</span> <span style="font-size: 15px; color: var(--text-muted);">PTS</span>
        </div>
        <div class="balance-currency">
          <span class="currency-pill" id="home-usd">$0.00 USD</span>
          <span class="currency-pill bdt" id="home-bdt">৳০.০০ BDT</span>
        </div>
        <div class="badge-row">
          <span class="badge-pill" id="home-bonus-badge">★ Referral Bonus: +0%</span>
          <span class="badge-pill" style="background: rgba(56, 189, 248, 0.15); color: var(--accent);">● TapMint Live</span>
        </div>
      </div>

      <div class="grid-stats">
        <div class="stat-box">
          <div class="stat-box-title">Today's Tasks</div>
          <div class="stat-box-value" id="home-tasks">0 / 20</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-title">Active Referrals</div>
          <div class="stat-box-value" id="home-refs">0 Friends</div>
        </div>
      </div>

      <div class="card">
        <div style="display: flex; justify-content: space-between; font-size: 12px;">
          <span>Daily Mission Progress</span>
          <span id="home-progress-text">0%</span>
        </div>
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" id="home-progress-bar"></div>
        </div>
      </div>

      <div class="card">
        <h3 style="margin: 0 0 10px 0; font-size: 14px;">Daily Boosters</h3>

        <div class="task-item">
          <div class="task-info">
            <span class="task-title">Daily Check-in</span>
            <span class="task-sub">প্রতিদিন একবার বোনাস নিন</span>
            <span class="task-reward">+10 PTS (Base)</span>
          </div>
          <button class="action-btn" id="btn-checkin" onclick="claimCheckin()">Claim</button>
        </div>

        <div class="task-item">
          <div class="task-info">
            <span class="task-title">Mining Pulse</span>
            <span class="task-sub" id="pulse-sub">প্রতি ৩০ মিনিট পরপর পালস ক্লেম</span>
            <span class="task-reward">+5 PTS (Base)</span>
          </div>
          <button class="action-btn" id="btn-pulse" onclick="claimPulse()">Pulse</button>
        </div>
      </div>
    </div>

    <!-- === TASKS TAB (Sessions 01-04 + Games Session + Quiz + Mystery Box) === -->
    <div id="tab-tasks" class="tab-content">
      <div style="margin-bottom: 10px;">
        <h3 style="margin: 0 0 3px 0; font-size: 16px;">Sessions & Games</h3>
        <p style="margin: 0; font-size: 12px; color: var(--text-muted);">সেশন ১–৪ এর কাজ অথবা আলাদা Games সেশন খেলুন</p>
      </div>

      <div class="session-grid">
        <div class="session-card active" id="sc-session_1" onclick="selectSession('session_1')">
          <div class="session-card-title">Sess 01</div>
          <div class="session-card-sub" id="sc-sub-session_1">0/5</div>
        </div>
        <div class="session-card" id="sc-session_2" onclick="selectSession('session_2')">
          <div class="session-card-title">Sess 02</div>
          <div class="session-card-sub" id="sc-sub-session_2">0/5</div>
        </div>
        <div class="session-card" id="sc-session_3" onclick="selectSession('session_3')">
          <div class="session-card-title">Sess 03</div>
          <div class="session-card-sub" id="sc-sub-session_3">0/5</div>
        </div>
        <div class="session-card" id="sc-session_4" onclick="selectSession('session_4')">
          <div class="session-card-title">Sess 04</div>
          <div class="session-card-sub" id="sc-sub-session_4">0/5</div>
        </div>
        <div class="session-card" id="sc-games" onclick="selectSession('games')">
          <div class="session-card-title">Games</div>
          <div class="session-card-sub" id="sc-sub-games">0/3</div>
        </div>
      </div>

      <!-- Task Sessions 1-4 -->
      <div class="card" id="task-session-panel">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
          <h4 style="margin: 0; font-size: 14px;" id="active-session-heading">Session 01 Missions</h4>
          <button class="action-btn" id="btn-session-bonus" onclick="claimSessionBonus()">Bonus (+25)</button>
        </div>
        <div id="session-tasks-container"></div>
      </div>

      <!-- Separate Games Session -->
      <div id="games-session-panel" style="display: none;">
        <!-- Game 1: Catch & Dodge -->
        <div class="card">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
              <h4 style="margin: 0; font-size: 14px;">Catch & Dodge</h4>
              <div style="font-size: 11px; color: var(--text-muted);">কয়েন (+) ধরুন, লাল বোম (✕) এড়ান • লক্ষ্য: ৬ স্কোর (+10 PTS)</div>
            </div>
            <button class="action-btn" id="btn-start-catch" onclick="startCatchGame()">Play</button>
          </div>
          <div class="game-arena">
            <div class="game-hud">
              <span>Score: <span id="catch-score">0</span></span>
              <span>Time: <span id="catch-time">20s</span></span>
              <span id="catch-reward-badge">Reward: +10 PTS</span>
            </div>
            <div class="catch-canvas" id="catch-canvas" ontouchmove="moveBasketTouch(event)" onmousemove="moveBasketMouse(event)">
              <div class="catch-basket" id="catch-basket"></div>
            </div>
            <div style="display: flex; gap: 8px; margin-top: 8px;">
              <button class="dpad-btn" style="flex: 1;" onclick="nudgeBasket(-28)">◀ Left</button>
              <button class="dpad-btn" style="flex: 1;" onclick="nudgeBasket(28)">Right ▶</button>
            </div>
          </div>
        </div>

        <!-- Game 2: Number Merge 2048 -->
        <div class="card">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
              <h4 style="margin: 0; font-size: 14px;">Number Merge 2048</h4>
              <div style="font-size: 11px; color: var(--text-muted);">একই নম্বর মার্জ করে ৩২+ টাইল বা ৪০ স্কোর করুন (+12 PTS)</div>
            </div>
            <button class="action-btn" id="btn-start-merge" onclick="initMergeGame()">Reset</button>
          </div>
          <div class="game-arena">
            <div class="game-hud">
              <span>Merge Score: <span id="merge-score">0</span></span>
              <span>Max Tile: <span id="merge-max">2</span></span>
              <span id="merge-reward-badge">Reward: +12 PTS</span>
            </div>
            <div class="merge-grid" id="merge-grid"></div>
            <div class="dpad">
              <div></div>
              <button class="dpad-btn" onclick="moveMerge('up')">▲</button>
              <div></div>
              <button class="dpad-btn" onclick="moveMerge('left')">◀</button>
              <button class="dpad-btn" onclick="moveMerge('down')">▼</button>
              <button class="dpad-btn" onclick="moveMerge('right')">▶</button>
            </div>
          </div>
        </div>

        <!-- Game 3: Snake -->
        <div class="card">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
              <h4 style="margin: 0; font-size: 14px;">Snake Arcade</h4>
              <div style="font-size: 11px; color: var(--text-muted);">খাবার খেয়ে ৫ স্কোর করুন, দেয়াল ও নিজের শরীর বাঁচান (+12 PTS)</div>
            </div>
            <button class="action-btn" id="btn-start-snake" onclick="startSnakeGame()">Start</button>
          </div>
          <div class="game-arena">
            <div class="game-hud">
              <span>Snake Score: <span id="snake-score">0</span></span>
              <span id="snake-status-hud">Ready</span>
              <span id="snake-reward-badge">Reward: +12 PTS</span>
            </div>
            <div class="snake-grid" id="snake-grid"></div>
            <div class="dpad">
              <div></div>
              <button class="dpad-btn" onclick="setSnakeDir(0, -1)">▲</button>
              <div></div>
              <button class="dpad-btn" onclick="setSnakeDir(-1, 0)">◀</button>
              <button class="dpad-btn" onclick="setSnakeDir(0, 1)">▼</button>
              <button class="dpad-btn" onclick="setSnakeDir(1, 0)">▶</button>
            </div>
          </div>
        </div>
      </div>

      <!-- Quick Quiz -->
      <div class="card">
        <h4 style="margin: 0 0 6px 0; font-size: 14px;">Quick Quiz (+10 PTS Base)</h4>
        <div style="font-size: 12px; color: var(--text-muted);">প্রশ্ন: ১০ পয়েন্ট সমান কত বাংলাদেশী টাকা?</div>
        <div class="quiz-opts">
          <button class="action-btn" onclick="answerQuiz('1')">১ টাকা</button>
          <button class="action-btn" onclick="answerQuiz('10')">১০ টাকা</button>
        </div>
        <div style="font-size: 11px; color: var(--primary); margin-top: 6px;" id="quiz-status"></div>
      </div>

      <!-- Mystery Box -->
      <div class="card">
        <h4 style="margin: 0 0 4px 0; font-size: 14px;">Mystery Box (Up to +15 PTS Base)</h4>
        <div style="font-size: 12px; color: var(--text-muted);">আজকের জন্য একটি বক্স বেছে নিন:</div>
        <div class="box-grid">
          <div class="box-choice" onclick="openMysteryBox(1)">🎁 Box 1</div>
          <div class="box-choice" onclick="openMysteryBox(2)">🎁 Box 2</div>
          <div class="box-choice" onclick="openMysteryBox(3)">🎁 Box 3</div>
        </div>
        <div style="font-size: 11px; color: var(--primary); margin-top: 8px;" id="box-status"></div>
      </div>
    </div>

    <!-- === REFER TAB === -->
    <div id="tab-refer" class="tab-content">
      <div style="margin-bottom: 12px; text-align: center;">
        <h3 style="margin: 0 0 4px 0; font-size: 16px;">Invite & Earn</h3>
        <p style="margin: 0; font-size: 12px; color: var(--text-muted);">প্রতিটি অ্যাক্টিভ রেফারেলে +৫% বোনাস (সর্বোচ্চ ৩০%)</p>
      </div>

      <div class="grid-stats">
        <div class="stat-box">
          <div class="stat-box-title">Active Referrals</div>
          <div class="stat-box-value" id="refer-active-count">0</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-title">Current Bonus</div>
          <div class="stat-box-value" id="refer-bonus-pct">+0%</div>
        </div>
      </div>

      <div class="card">
        <div class="input-group">
          <label class="input-label">Your Referral Link</label>
          <input id="refLink" readonly />
        </div>
        <button class="submit-btn" onclick="copyRefLink()">Copy Referral Link</button>
        <div id="refer-status" class="status-box" style="display: none;"></div>
      </div>

      <div class="card">
        <h4 style="margin: 0 0 8px 0; font-size: 13px;">নিয়মাবলী</h4>
        <ol class="rules-list">
          <li>আপনার রেফারেল লিংক বন্ধুদের সাথে শেয়ার করুন।</li>
          <li>বন্ধু জয়েন করে কমপক্ষে ৩টি টাস্ক শেষ করলে সে অ্যাক্টিভ রেফারেল হিসেবে গণ্য হবে।</li>
          <li>প্রতিটি অ্যাক্টিভ রেফারেলে আপনার টাস্ক বোনাস +৫% করে বাড়বে (সর্বোচ্চ ৩০%)।</li>
        </ol>
      </div>
    </div>

    <!-- === WALLET TAB === -->
    <div id="tab-wallet" class="tab-content">
      <div style="margin-bottom: 12px;">
        <h3 style="margin: 0 0 4px 0; font-size: 16px;">Wallet & Withdraw</h3>
        <p style="margin: 0; font-size: 12px; color: var(--text-muted);">মিনিমাম উইথড্র: ১,০০০ PTS (৳১০০ টাকা / $১.০০ USD)</p>
      </div>

      <div class="card hero-card">
        <div class="balance-label">Available Balance</div>
        <div class="balance-points">
          <span>🪙</span> <span id="wallet-points">0</span> <span style="font-size: 15px; color: var(--text-muted);">PTS</span>
        </div>
        <div class="balance-currency">
          <span class="currency-pill" id="wallet-usd">$0.00 USD</span>
          <span class="currency-pill bdt" id="wallet-bdt">৳০.০০ BDT</span>
        </div>
        <div style="font-size: 11px; color: var(--text-muted);">১০ পয়েন্ট = ১ টাকা | ১,০০০ পয়েন্ট = ১ ডলার</div>
      </div>

      <div class="card">
        <label class="input-label">Payment Method</label>
        <div class="method-selector">
          <div class="method-btn active" id="method-bkash" onclick="selectMethod('bkash')">bKash</div>
          <div class="method-btn" id="method-nagad" onclick="selectMethod('nagad')">Nagad</div>
          <div class="method-btn" id="method-binance" onclick="selectMethod('binance_usdt')">Binance USDT</div>
        </div>

        <div class="input-group">
          <label class="input-label" id="account-label">bKash Number</label>
          <input id="accountInfo" placeholder="017xxxxxxxx" />
        </div>

        <div class="input-group">
          <label class="input-label">Points to Withdraw (Min 1000)</label>
          <input id="withdrawPoints" type="number" placeholder="1000" />
        </div>

        <button class="submit-btn" onclick="submitWithdraw()">Send Withdraw Request</button>
        <div id="withdraw-status" class="status-box">রেডি</div>
      </div>
    </div>

  </div>

  <!-- === BOTTOM NAVIGATION === -->
  <div class="nav-bar">
    <div class="nav-item active" id="nav-home" onclick="switchTab('home')">
      <span class="nav-icon">🏠</span>
      <span>Home</span>
    </div>
    <div class="nav-item" id="nav-tasks" onclick="switchTab('tasks')">
      <span class="nav-icon">📋</span>
      <span>Tasks</span>
    </div>
    <div class="nav-item" id="nav-refer" onclick="switchTab('refer')">
      <span class="nav-icon">👥</span>
      <span>Refer</span>
    </div>
    <div class="nav-item" id="nav-wallet" onclick="switchTab('wallet')">
      <span class="nav-icon">👛</span>
      <span>Wallet</span>
    </div>
  </div>

  <script>
    const tg = window.Telegram.WebApp;
    tg.expand();

    const tgUser = tg.initDataUnsafe?.user || { id: 100001, username: "test_user" };
    const startParam = tg.initDataUnsafe?.start_param || null;
    const botUsername = "tapmint99_bot";

    const SESSION_DATA = {
      session_1: {
        label: "Session 01 Missions",
        items: [
          { code: "task_1", title: "Daily Reward #01", sub: "Quick Partner Visit", url: "https://asiafilm.org/4/2da793d72cd322b49d8bb9d66fc974e7" },
          { code: "task_2", title: "Quick Check-in #02", sub: "Featured Offer", url: "https://asiafilm.org/4/3bd5bca9029900a8d0d2bb526ebd7214" },
          { code: "task_3", title: "Bonus Mission #03", sub: "Sponsored Spot", url: "https://asiafilm.org/4/224868d40ac462d276354c5696553960" },
          { code: "task_4", title: "Spotlight Deal #04", sub: "Partner Promo", url: "https://asiafilm.org/4/2a16c7d7870cf593884b4976629a6156" },
          { code: "task_5", title: "Reward Drop #05", sub: "Daily Mission", url: "https://asiafilm.org/4/4f3af0df8bb071b2232440532691af67" }
        ]
      },
      session_2: {
        label: "Session 02 Missions",
        items: [
          { code: "task_6", title: "Daily Reward #06", sub: "Quick Partner Visit", url: "https://asiafilm.org/4/5909d9fd3d02125d0447b6d1702377d7" },
          { code: "task_7", title: "Quick Check-in #07", sub: "Featured Offer", url: "https://asiafilm.org/4/c75201a3ea80e241a6008c8f503e0855" },
          { code: "task_8", title: "Bonus Mission #08", sub: "Sponsored Spot", url: "https://asiafilm.org/4/9b1be208097bfdbce8298db933df0875" },
          { code: "task_9", title: "Spotlight Deal #09", sub: "Partner Promo", url: "https://asiafilm.org/4/5bac8f36e93727dc1e10c13f28ad12ba" },
          { code: "task_10", title: "Reward Drop #10", sub: "Daily Mission", url: "https://asiafilm.org/4/948938a94d72df36b23ba9f97ef3bfff" }
        ]
      },
      session_3: {
        label: "Session 03 Missions",
        items: [
          { code: "task_11", title: "Daily Reward #11", sub: "Partner Spotlight", url: "https://uplcm.com/4/12351466" },
          { code: "task_12", title: "Quick Check-in #12", sub: "Reward Check", url: "https://uplcm.com/4/12351467" },
          { code: "task_13", title: "Bonus Mission #13", sub: "Featured Promo", url: "https://uplcm.com/4/12351468" },
          { code: "task_14", title: "Spotlight Deal #14", sub: "Daily Offer", url: "https://uplcm.com/4/12351473" },
          { code: "task_15", title: "Reward Drop #15", sub: "Sponsor Mission", url: "https://uplcm.com/4/12351474" }
        ]
      },
      session_4: {
        label: "Session 04 Missions",
        items: [
          { code: "task_16", title: "Daily Reward #16", sub: "Partner Spotlight", url: "https://uplcm.com/4/12351475" },
          { code: "task_17", title: "Quick Check-in #17", sub: "Reward Check", url: "https://uplcm.com/4/12351476" },
          { code: "task_18", title: "Bonus Mission #18", sub: "Featured Promo", url: "https://uplcm.com/4/12351477" },
          { code: "task_19", title: "Spotlight Deal #19", sub: "Daily Offer", url: "https://uplcm.com/4/12351478" },
          { code: "task_20", title: "Reward Drop #20", sub: "Sponsor Mission", url: "https://uplcm.com/4/12351479" }
        ]
      }
    };

    let currentSession = "session_1";
    let selectedPaymentMethod = "bkash";
    let latestState = null;

    document.getElementById("refLink").value = `https://t.me/${botUsername}?start=${tgUser.id}`;

    function notifyUser(msg) {
      if (tg.showAlert) {
        tg.showAlert(msg);
      } else {
        alert(msg);
      }
    }

    function switchTab(tabId) {
      document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
      document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));
      document.getElementById(`tab-${tabId}`).classList.add("active");
      document.getElementById(`nav-${tabId}`).classList.add("active");
    }

    function selectSession(sessKey) {
      currentSession = sessKey;
      ["session_1", "session_2", "session_3", "session_4", "games"].forEach(k => {
        document.getElementById(`sc-${k}`).classList.toggle("active", k === sessKey);
      });
      const isGames = sessKey === "games";
      document.getElementById("task-session-panel").style.display = isGames ? "none" : "block";
      document.getElementById("games-session-panel").style.display = isGames ? "block" : "none";
      if (!isGames) renderSessionTasks();
    }

    function selectMethod(method) {
      selectedPaymentMethod = method;
      document.getElementById("method-bkash").classList.toggle("active", method === "bkash");
      document.getElementById("method-nagad").classList.toggle("active", method === "nagad");
      document.getElementById("method-binance").classList.toggle("active", method === "binance_usdt");

      const label = document.getElementById("account-label");
      const input = document.getElementById("accountInfo");
      if (method === "bkash") {
        label.innerText = "bKash Number";
        input.placeholder = "017xxxxxxxx";
      } else if (method === "nagad") {
        label.innerText = "Nagad Number";
        input.placeholder = "017xxxxxxxx";
      } else {
        label.innerText = "Binance USDT Address";
        input.placeholder = "TRC20 or BEP20 Wallet Address";
      }
    }

    function formatBDT(pts) {
      return `৳${(pts / 10).toFixed(2)} BDT`;
    }

    function formatUSD(pts) {
      return `$${(pts / 1000).toFixed(2)} USD`;
    }

    function renderSessionTasks() {
      if (currentSession === "games") return;
      const container = document.getElementById("session-tasks-container");
      document.getElementById("active-session-heading").innerText = SESSION_DATA[currentSession].label;

      const doneCodes = new Set(latestState?.completed_today_codes || []);
      const sInfo = latestState?.sessions?.[currentSession] || { all_done: false, bonus_claimed: false };

      container.innerHTML = SESSION_DATA[currentSession].items.map(item => {
        const isDone = doneCodes.has(item.code);
        return `
          <div class="task-item">
            <div class="task-info">
              <span class="task-title">${item.title}</span>
              <span class="task-sub">${item.sub}</span>
              <span class="task-reward">+10 PTS (Base)</span>
            </div>
            <button class="action-btn ${isDone ? "done" : ""}" ${isDone ? "disabled" : ""} onclick="doTask('${item.code}', '${item.url}')">
              ${isDone ? "Done ✓" : "Start"}
            </button>
          </div>
        `;
      }).join("");

      const bonusBtn = document.getElementById("btn-session-bonus");
      if (sInfo.bonus_claimed) {
        bonusBtn.innerText = "Claimed ✓";
        bonusBtn.className = "action-btn done";
        bonusBtn.disabled = true;
      } else if (!sInfo.all_done) {
        bonusBtn.innerText = "Locked (+25)";
        bonusBtn.className = "action-btn";
        bonusBtn.disabled = true;
      } else {
        bonusBtn.innerText = "Bonus (+25)";
        bonusBtn.className = "action-btn";
        bonusBtn.disabled = false;
      }
    }

    function renderAll(state) {
      latestState = state;
      const u = state.user;
      const pts = u.points;
      const bdtText = formatBDT(pts);
      const usdText = formatUSD(pts);
      const bonusPct = Math.min(u.active_referrals * 5, 30);

      document.getElementById("home-points").innerText = pts.toLocaleString();
      document.getElementById("home-bdt").innerText = bdtText;
      document.getElementById("home-usd").innerText = usdText;
      document.getElementById("home-tasks").innerText = `${state.today_completed_count} / 20`;
      document.getElementById("home-refs").innerText = `${u.active_referrals} Friends`;
      document.getElementById("home-bonus-badge").innerText = `★ Referral Bonus: +${bonusPct}%`;

      const pct = Math.min(Math.round((state.today_completed_count / 20) * 100), 100);
      document.getElementById("home-progress-text").innerText = `${pct}%`;
      document.getElementById("home-progress-bar").style.width = `${pct}%`;

      document.getElementById("refer-active-count").innerText = u.active_referrals;
      document.getElementById("refer-bonus-pct").innerText = `+${bonusPct}%`;

      document.getElementById("wallet-points").innerText = pts.toLocaleString();
      document.getElementById("wallet-bdt").innerText = bdtText;
      document.getElementById("wallet-usd").innerText = usdText;

      const ciBtn = document.getElementById("btn-checkin");
      ciBtn.innerText = state.daily_checkin_done ? "Done ✓" : "Claim";
      ciBtn.className = `action-btn ${state.daily_checkin_done ? "done" : ""}`;
      ciBtn.disabled = state.daily_checkin_done;

      const pBtn = document.getElementById("btn-pulse");
      const pSub = document.getElementById("pulse-sub");
      if (state.pulse_remaining_sec > 0) {
        const mins = Math.ceil(state.pulse_remaining_sec / 60);
        pBtn.innerText = `${mins}m`;
        pBtn.disabled = true;
        pSub.innerText = `পরবর্তী পালস ${mins} মিনিট পর`;
      } else {
        pBtn.innerText = "Pulse";
        pBtn.disabled = false;
        pSub.innerText = "প্রতি ৩০ মিনিট পরপর পালস ক্লেম";
      }

      ["session_1", "session_2", "session_3", "session_4"].forEach(k => {
        const s = state.sessions?.[k] || { done: 0, total: 5 };
        document.getElementById(`sc-sub-${k}`).innerText = `${s.done}/${s.total}`;
      });

      const doneGames = new Set(state.done_games || []);
      document.getElementById("sc-sub-games").innerText = `${doneGames.size}/3`;
      if (doneGames.has("game_catch_dodge")) {
        document.getElementById("catch-reward-badge").innerText = "Claimed ✓";
      }
      if (doneGames.has("game_merge_2048")) {
        document.getElementById("merge-reward-badge").innerText = "Claimed ✓";
      }
      if (doneGames.has("game_snake")) {
        document.getElementById("snake-reward-badge").innerText = "Claimed ✓";
      }

      if (state.quiz_done) {
        document.getElementById("quiz-status").innerText = "আজকের কুইজ সম্পন্ন হয়েছে ✓";
      }
      if (state.mystery_box_done) {
        document.getElementById("box-status").innerText = "আজকের মিস্ট্রি বক্স খোলা হয়েছে ✓";
      }

      renderSessionTasks();
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
      renderAll(data);
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
        renderAll(data.state);
        notifyUser(`+${data.earned_points} PTS যোগ হয়েছে!`);
      } else {
        notifyUser(data.detail || "সমস্যা হয়েছে");
      }
    }

    async function claimCheckin() {
      const res = await fetch("/api/daily-checkin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ telegram_id: tgUser.id })
      });
      const data = await res.json();
      if (res.ok) {
        renderAll(data.state);
        notifyUser(`Daily Check-in: +${data.earned_points} PTS`);
      } else {
        notifyUser(data.detail || "সমস্যা হয়েছে");
      }
    }

    async function claimPulse() {
      const res = await fetch("/api/mining-pulse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ telegram_id: tgUser.id })
      });
      const data = await res.json();
      if (res.ok) {
        renderAll(data.state);
        notifyUser(`Mining Pulse: +${data.earned_points} PTS`);
      } else {
        notifyUser(data.detail || "এখনো সময় হয়নি");
      }
    }

    async function claimSessionBonus() {
      const res = await fetch("/api/session-bonus", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ telegram_id: tgUser.id, session_key: currentSession })
      });
      const data = await res.json();
      if (res.ok) {
        renderAll(data.state);
        notifyUser(`Session Bonus: +${data.earned_points} PTS`);
      } else {
        notifyUser(data.detail || "সমস্যা হয়েছে");
      }
    }

    async function answerQuiz(ans) {
      const res = await fetch("/api/quiz-claim", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ telegram_id: tgUser.id, answer: ans })
      });
      const data = await res.json();
      if (res.ok) {
        renderAll(data.state);
        document.getElementById("quiz-status").innerText = `সঠিক উত্তর! +${data.earned_points} PTS যোগ হয়েছে।`;
      } else {
        document.getElementById("quiz-status").innerText = data.detail || "ভুল উত্তর বা আজকের সুযোগ শেষ";
      }
    }

    async function openMysteryBox(boxNum) {
      const res = await fetch("/api/mystery-box", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ telegram_id: tgUser.id, box_number: boxNum })
      });
      const data = await res.json();
      if (res.ok) {
        renderAll(data.state);
        document.getElementById("box-status").innerText = `Box ${boxNum} থেকে +${data.earned_points} PTS পেয়েছেন!`;
      } else {
        document.getElementById("box-status").innerText = data.detail || "আজকের বক্স খোলা হয়ে গেছে";
      }
    }

    async function claimGameWin(gameCode, winMsg) {
      if ((latestState?.done_games || []).includes(gameCode)) {
        notifyUser(winMsg + " (আজকের রিওয়ার্ড ইতিমধ্যে নেওয়া হয়েছে)");
        return;
      }
      const res = await fetch("/api/game-reward", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ telegram_id: tgUser.id, game_code: gameCode })
      });
      const data = await res.json();
      if (res.ok) {
        renderAll(data.state);
        notifyUser(`${winMsg} +${data.earned_points} PTS যোগ হয়েছে!`);
      } else {
        notifyUser(data.detail || winMsg);
      }
    }

    // --- GAME 1: CATCH & DODGE ---
    let catchTimerId = null;
    let catchCountdownId = null;
    let catchRunning = false;
    let catchScore = 0;
    let catchTimeLeft = 20;
    let basketX = 50; // %
    let fallingObjs = [];

    function setBasketPos(pct) {
      basketX = Math.max(12, Math.min(88, pct));
      document.getElementById("catch-basket").style.left = `${basketX}%`;
    }

    function nudgeBasket(deltaPx) {
      const canvas = document.getElementById("catch-canvas");
      const width = canvas.clientWidth || 300;
      const pctDelta = (deltaPx / width) * 100;
      setBasketPos(basketX + pctDelta);
    }

    function moveBasketTouch(e) {
      if (!e.touches.length) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const pct = ((e.touches[0].clientX - rect.left) / rect.width) * 100;
      setBasketPos(pct);
    }

    function moveBasketMouse(e) {
      if (e.buttons !== 1) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const pct = ((e.clientX - rect.left) / rect.width) * 100;
      setBasketPos(pct);
    }

    function startCatchGame() {
      clearInterval(catchTimerId);
      clearInterval(catchCountdownId);
      document.querySelectorAll(".catch-item").forEach(el => el.remove());

      catchRunning = true;
      catchScore = 0;
      catchTimeLeft = 20;
      fallingObjs = [];
      document.getElementById("catch-score").innerText = "0";
      document.getElementById("catch-time").innerText = "20s";

      let tick = 0;
      catchTimerId = setInterval(() => {
        if (!catchRunning) return;
        tick += 1;
        if (tick % 14 === 0) {
          const isBomb = Math.random() < 0.34;
          const obj = {
            x: 12 + Math.random() * 76,
            y: 6,
            speed: 2.3 + Math.random() * 1.4,
            isBomb,
            el: document.createElement("div")
          };
          obj.el.className = `catch-item ${isBomb ? "catch-bomb" : "catch-coin"}`;
          obj.el.innerText = isBomb ? "✕" : "+";
          document.getElementById("catch-canvas").appendChild(obj.el);
          fallingObjs.push(obj);
        }

        const nextObjs = [];
        for (const o of fallingObjs) {
          o.y += o.speed;
          o.el.style.left = `${o.x}%`;
          o.el.style.top = `${o.y}%`;

          const hitBasket = o.y >= 82 && o.y <= 93 && Math.abs(o.x - basketX) <= 14;
          if (hitBasket) {
            o.el.remove();
            if (o.isBomb) {
              catchScore = Math.max(0, catchScore - 2);
            } else {
              catchScore += 1;
            }
            document.getElementById("catch-score").innerText = String(catchScore);
          } else if (o.y < 102) {
            nextObjs.push(o);
          } else {
            o.el.remove();
          }
        }
        fallingObjs = nextObjs;
      }, 40);

      catchCountdownId = setInterval(() => {
        catchTimeLeft -= 1;
        document.getElementById("catch-time").innerText = `${catchTimeLeft}s`;
        if (catchTimeLeft <= 0) {
          catchRunning = false;
          clearInterval(catchTimerId);
          clearInterval(catchCountdownId);
          document.querySelectorAll(".catch-item").forEach(el => el.remove());
          if (catchScore >= 6) {
            claimGameWin("game_catch_dodge", `Catch & Dodge সম্পন্ন (${catchScore} স্কোর)!`);
          } else {
            notifyUser(`রাউন্ড শেষ! স্কোর: ${catchScore} (কমপক্ষে ৬ স্কোর লাগবে)`);
          }
        }
      }, 1000);
    }

    // --- GAME 2: NUMBER MERGE 2048 (3x3) ---
    let mergeBoard = [];
    let mergeScore = 0;
    let mergeRewardSent = false;

    function spawnMergeTile() {
      const empty = [];
      for (let r = 0; r < 3; r++) {
        for (let c = 0; c < 3; c++) {
          if (mergeBoard[r][c] === 0) empty.push([r, c]);
        }
      }
      if (!empty.length) return;
      const [r, c] = empty[Math.floor(Math.random() * empty.length)];
      mergeBoard[r][c] = Math.random() < 0.8 ? 2 : 4;
    }

    function initMergeGame() {
      mergeBoard = [
        [0, 0, 0],
        [0, 0, 0],
        [0, 0, 0]
      ];
      mergeScore = 0;
      mergeRewardSent = false;
      spawnMergeTile();
      spawnMergeTile();
      renderMergeBoard();
    }

    function renderMergeBoard() {
      const grid = document.getElementById("merge-grid");
      let maxVal = 2;
      let html = "";
      for (let r = 0; r < 3; r++) {
        for (let c = 0; c < 3; c++) {
          const v = mergeBoard[r][c];
          if (v > maxVal) maxVal = v;
          html += `<div class="merge-tile ${v ? "val-" + v : ""}">${v || ""}</div>`;
        }
      }
      grid.innerHTML = html;
      document.getElementById("merge-score").innerText = String(mergeScore);
      document.getElementById("merge-max").innerText = String(maxVal);

      if (!mergeRewardSent && (maxVal >= 32 || mergeScore >= 40)) {
        mergeRewardSent = true;
        claimGameWin("game_merge_2048", `Number Merge লক্ষ্য পূরণ (Max ${maxVal})!`);
      }
    }

    function slideAndMergeLine(line) {
      const nums = line.filter(x => x !== 0);
      const out = [];
      let i = 0;
      while (i < nums.length) {
        if (i + 1 < nums.length && nums[i] === nums[i + 1]) {
          const merged = nums[i] * 2;
          mergeScore += merged;
          out.push(merged);
          i += 2;
        } else {
          out.push(nums[i]);
          i += 1;
        }
      }
      while (out.length < 3) out.push(0);
      return out;
    }

    function moveMerge(dir) {
      const prev = JSON.stringify(mergeBoard);
      if (dir === "left") {
        for (let r = 0; r < 3; r++) mergeBoard[r] = slideAndMergeLine(mergeBoard[r]);
      } else if (dir === "right") {
        for (let r = 0; r < 3; r++) mergeBoard[r] = slideAndMergeLine([...mergeBoard[r]].reverse()).reverse();
      } else if (dir === "up") {
        for (let c = 0; c < 3; c++) {
          const col = [mergeBoard[0][c], mergeBoard[1][c], mergeBoard[2][c]];
          const res = slideAndMergeLine(col);
          for (let r = 0; r < 3; r++) mergeBoard[r][c] = res[r];
        }
      } else if (dir === "down") {
        for (let c = 0; c < 3; c++) {
          const col = [mergeBoard[2][c], mergeBoard[1][c], mergeBoard[0][c]];
          const res = slideAndMergeLine(col);
          for (let r = 0; r < 3; r++) mergeBoard[2 - r][c] = res[r];
        }
      }

      if (JSON.stringify(mergeBoard) !== prev) {
        spawnMergeTile();
        renderMergeBoard();
      }
    }

    // --- GAME 3: SNAKE (9x9) ---
    const SNAKE_SIZE = 9;
    let snakeLoopId = null;
    let snakeBody = [];
    let snakeDir = { x: 1, y: 0 };
    let snakeFood = { x: 6, y: 4 };
    let snakeScore = 0;
    let snakeRewardSent = false;

    function randomFood() {
      while (true) {
        const fx = Math.floor(Math.random() * SNAKE_SIZE);
        const fy = Math.floor(Math.random() * SNAKE_SIZE);
        if (!snakeBody.some(s => s.x === fx && s.y === fy)) {
          return { x: fx, y: fy };
        }
      }
    }

    function renderSnakeGrid() {
      const grid = document.getElementById("snake-grid");
      let html = "";
      for (let y = 0; y < SNAKE_SIZE; y++) {
        for (let x = 0; x < SNAKE_SIZE; x++) {
          let cls = "snake-cell";
          if (snakeBody[0]?.x === x && snakeBody[0]?.y === y) cls += " head";
          else if (snakeBody.slice(1).some(s => s.x === x && s.y === y)) cls += " body";
          else if (snakeFood.x === x && snakeFood.y === y) cls += " food";
          html += `<div class="${cls}"></div>`;
        }
      }
      grid.innerHTML = html;
      document.getElementById("snake-score").innerText = String(snakeScore);
    }

    function setSnakeDir(dx, dy) {
      if (dx === -snakeDir.x && dy === -snakeDir.y) return;
      snakeDir = { x: dx, y: dy };
    }

    function startSnakeGame() {
      clearInterval(snakeLoopId);
      snakeBody = [{ x: 3, y: 4 }, { x: 2, y: 4 }, { x: 1, y: 4 }];
      snakeDir = { x: 1, y: 0 };
      snakeScore = 0;
      snakeRewardSent = false;
      snakeFood = randomFood();
      document.getElementById("snake-status-hud").innerText = "Playing";
      renderSnakeGrid();

      snakeLoopId = setInterval(() => {
        const head = snakeBody[0];
        const nx = head.x + snakeDir.x;
        const ny = head.y + snakeDir.y;

        const hitWall = nx < 0 || ny < 0 || nx >= SNAKE_SIZE || ny >= SNAKE_SIZE;
        const hitSelf = snakeBody.some(seg => seg.x === nx && seg.y === ny);

        if (hitWall || hitSelf) {
          clearInterval(snakeLoopId);
          document.getElementById("snake-status-hud").innerText = "Game Over";
          notifyUser(`Snake গেম ওভার! স্কোর: ${snakeScore}`);
          return;
        }

        const newHead = { x: nx, y: ny };
        snakeBody.unshift(newHead);

        if (nx === snakeFood.x && ny === snakeFood.y) {
          snakeScore += 1;
          snakeFood = randomFood();
          if (!snakeRewardSent && snakeScore >= 5) {
            snakeRewardSent = true;
            clearInterval(snakeLoopId);
            document.getElementById("snake-status-hud").innerText = "Won ✓";
            claimGameWin("game_snake", `Snake লক্ষ্য পূরণ (${snakeScore} স্কোর)!`);
          }
        } else {
          snakeBody.pop();
        }
        renderSnakeGrid();
      }, 240);
    }

    function copyRefLink() {
      const input = document.getElementById("refLink");
      input.select();
      navigator.clipboard?.writeText(input.value);
      const status = document.getElementById("refer-status");
      status.style.display = "block";
      status.innerText = "রেফারেল লিংক কপি হয়েছে!";
      setTimeout(() => status.style.display = "none", 2500);
    }

    async function submitWithdraw() {
      const account_info = document.getElementById("accountInfo").value;
      const points = Number(document.getElementById("withdrawPoints").value);
      const status = document.getElementById("withdraw-status");

      const res = await fetch("/api/withdraw", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          telegram_id: tgUser.id,
          method: selectedPaymentMethod,
          account_info,
          points
        })
      });
      const data = await res.json();
      if (res.ok) {
        renderAll(data.state);
        status.innerText = `উইথড্র রিকোয়েস্ট জমা হয়েছে (৳${data.amount_bdt} টাকা)।`;
        document.getElementById("accountInfo").value = "";
        document.getElementById("withdrawPoints").value = "";
      } else {
        status.innerText = data.detail || "সমস্যা হয়েছে";
      }
    }

    initMergeGame();
    renderSnakeGrid();
    initApp();
  </script>
</body>
</html>"""


class AuthPayload(BaseModel):
    telegram_id: int
    username: str | None = None
    referrer_id: int | None = None


class UserOnlyPayload(BaseModel):
    telegram_id: int


class TaskCompletePayload(BaseModel):
    telegram_id: int
    task_code: str


class SessionBonusPayload(BaseModel):
    telegram_id: int
    session_key: str


class QuizPayload(BaseModel):
    telegram_id: int
    answer: str


class MysteryBoxPayload(BaseModel):
    telegram_id: int
    box_number: int


class GameRewardPayload(BaseModel):
    telegram_id: int
    game_code: str


class WithdrawPayload(BaseModel):
    telegram_id: int
    method: str
    account_info: str
    points: int


class AdminActionPayload(BaseModel):
    secret: str
    withdrawal_id: int
    action: str


@app.on_event("startup")
def startup():
    init_db()
    ensure_extra_tables()


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

    state = build_state_payload(cur, payload.telegram_id)
    conn.close()
    return state


@app.post("/api/complete-task")
def complete_task(payload: TaskCompletePayload):
    if payload.task_code not in ALL_TASK_CODES:
        raise HTTPException(status_code=400, detail="Invalid task")

    conn = get_conn()
    cur = conn.cursor()

    user = cur.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (payload.telegram_id,)
    ).fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    if has_claimed_today(cur, payload.telegram_id, payload.task_code):
        conn.close()
        raise HTTPException(status_code=400, detail="আজকের জন্য এই টাস্কটি সম্পন্ন হয়েছে")

    earned, bonus_pct = calc_earned_points(user["active_referrals"], BASE_TASK_POINTS)
    new_tasks = user["completed_tasks"] + 1
    new_points = user["points"] + earned

    cur.execute(
        "UPDATE users SET points = ?, completed_tasks = ? WHERE telegram_id = ?",
        (new_points, new_tasks, payload.telegram_id),
    )
    cur.execute(
        "INSERT INTO task_logs (telegram_id, task_code, earned_points) VALUES (?, ?, ?)",
        (payload.telegram_id, payload.task_code, earned),
    )
    record_claim(cur, payload.telegram_id, payload.task_code)

    refreshed = cur.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (payload.telegram_id,)
    ).fetchone()
    apply_referral_activation(cur, refreshed, new_tasks)

    conn.commit()
    state = build_state_payload(cur, payload.telegram_id)
    conn.close()

    return {"earned_points": earned, "bonus_pct": bonus_pct, "state": state}


@app.post("/api/daily-checkin")
def daily_checkin(payload: UserOnlyPayload):
    conn = get_conn()
    cur = conn.cursor()

    user = cur.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (payload.telegram_id,)
    ).fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    if has_claimed_today(cur, payload.telegram_id, "daily_checkin"):
        conn.close()
        raise HTTPException(status_code=400, detail="আজকের ডেইলি চেক-ইন নেওয়া হয়ে গেছে")

    earned, _ = calc_earned_points(user["active_referrals"], DAILY_CHECKIN_POINTS)
    cur.execute(
        "UPDATE users SET points = points + ? WHERE telegram_id = ?",
        (earned, payload.telegram_id),
    )
    record_claim(cur, payload.telegram_id, "daily_checkin")
    conn.commit()

    state = build_state_payload(cur, payload.telegram_id)
    conn.close()
    return {"earned_points": earned, "state": state}


@app.post("/api/mining-pulse")
def mining_pulse(payload: UserOnlyPayload):
    conn = get_conn()
    cur = conn.cursor()

    user = cur.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (payload.telegram_id,)
    ).fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    last_pulse = cur.execute(
        """
        SELECT created_at FROM user_claims
        WHERE telegram_id = ? AND claim_key = 'mining_pulse'
        ORDER BY id DESC LIMIT 1
        """,
        (payload.telegram_id,),
    ).fetchone()

    ts = now_ts()
    if last_pulse and (ts - int(last_pulse["created_at"])) < MINING_PULSE_COOLDOWN_SEC:
        rem_min = max(1, (MINING_PULSE_COOLDOWN_SEC - (ts - int(last_pulse["created_at"]))) // 60)
        conn.close()
        raise HTTPException(status_code=400, detail=f"পরবর্তী পালস {rem_min} মিনিট পর পাবেন")

    earned, _ = calc_earned_points(user["active_referrals"], MINING_PULSE_POINTS)
    cur.execute(
        "UPDATE users SET points = points + ? WHERE telegram_id = ?",
        (earned, payload.telegram_id),
    )
    cur.execute(
        """
        INSERT INTO user_claims (telegram_id, claim_key, claim_date, created_at)
        VALUES (?, 'mining_pulse', ?, ?)
        """,
        (payload.telegram_id, today_str(), ts),
    )
    conn.commit()

    state = build_state_payload(cur, payload.telegram_id)
    conn.close()
    return {"earned_points": earned, "state": state}


@app.post("/api/session-bonus")
def session_bonus(payload: SessionBonusPayload):
    if payload.session_key not in SESSION_TASKS:
        raise HTTPException(status_code=400, detail="Invalid session")

    conn = get_conn()
    cur = conn.cursor()

    user = cur.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (payload.telegram_id,)
    ).fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    bonus_key = f"session_bonus_{payload.session_key}"
    if has_claimed_today(cur, payload.telegram_id, bonus_key):
        conn.close()
        raise HTTPException(status_code=400, detail="এই সেশনের বোনাস আজ নেওয়া হয়েছে")

    day = today_str()
    claimed_today = {
        r["claim_key"]
        for r in cur.execute(
            "SELECT claim_key FROM user_claims WHERE telegram_id = ? AND claim_date = ?",
            (payload.telegram_id, day),
        ).fetchall()
    }
    needed_codes = [x["code"] for x in SESSION_TASKS[payload.session_key]]
    if not all(c in claimed_today for c in needed_codes):
        conn.close()
        raise HTTPException(status_code=400, detail="আগে এই সেশনের সব টাস্ক শেষ করুন")

    earned, _ = calc_earned_points(user["active_referrals"], SESSION_BONUS_POINTS)
    cur.execute(
        "UPDATE users SET points = points + ? WHERE telegram_id = ?",
        (earned, payload.telegram_id),
    )
    record_claim(cur, payload.telegram_id, bonus_key)
    conn.commit()

    state = build_state_payload(cur, payload.telegram_id)
    conn.close()
    return {"earned_points": earned, "state": state}


@app.post("/api/quiz-claim")
def quiz_claim(payload: QuizPayload):
    conn = get_conn()
    cur = conn.cursor()

    user = cur.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (payload.telegram_id,)
    ).fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    if has_claimed_today(cur, payload.telegram_id, "quick_quiz"):
        conn.close()
        raise HTTPException(status_code=400, detail="আজকের কুইজ সম্পন্ন হয়েছে")

    if payload.answer.strip() != "1":
        conn.close()
        raise HTTPException(status_code=400, detail="সঠিক উত্তর নয় (১০ পয়েন্ট = ১ টাকা)")

    earned, _ = calc_earned_points(user["active_referrals"], QUIZ_POINTS)
    cur.execute(
        "UPDATE users SET points = points + ? WHERE telegram_id = ?",
        (earned, payload.telegram_id),
    )
    record_claim(cur, payload.telegram_id, "quick_quiz")
    conn.commit()

    state = build_state_payload(cur, payload.telegram_id)
    conn.close()
    return {"earned_points": earned, "state": state}


@app.post("/api/mystery-box")
def mystery_box(payload: MysteryBoxPayload):
    if payload.box_number not in {1, 2, 3}:
        raise HTTPException(status_code=400, detail="Invalid box")

    conn = get_conn()
    cur = conn.cursor()

    user = cur.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (payload.telegram_id,)
    ).fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    if has_claimed_today(cur, payload.telegram_id, "mystery_box"):
        conn.close()
        raise HTTPException(status_code=400, detail="আজকের মিস্ট্রি বক্স খোলা হয়ে গেছে")

    box_rewards = {1: 5, 2: 10, 3: MYSTERY_BOX_MAX_POINTS}
    base_pts = box_rewards[payload.box_number]
    earned, _ = calc_earned_points(user["active_referrals"], base_pts)

    cur.execute(
        "UPDATE users SET points = points + ? WHERE telegram_id = ?",
        (earned, payload.telegram_id),
    )
    record_claim(cur, payload.telegram_id, "mystery_box")
    conn.commit()

    state = build_state_payload(cur, payload.telegram_id)
    conn.close()
    return {"earned_points": earned, "state": state}


@app.post("/api/game-reward")
def game_reward(payload: GameRewardPayload):
    if payload.game_code not in GAME_REWARD_POINTS:
        raise HTTPException(status_code=400, detail="Invalid game")

    conn = get_conn()
    cur = conn.cursor()

    user = cur.execute(
        "SELECT * FROM users WHERE telegram_id = ?", (payload.telegram_id,)
    ).fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    if has_claimed_today(cur, payload.telegram_id, payload.game_code):
        conn.close()
        raise HTTPException(status_code=400, detail="আজকের গেম রিওয়ার্ড নেওয়া হয়ে গেছে")

    earned, _ = calc_earned_points(user["active_referrals"], GAME_REWARD_POINTS[payload.game_code])
    cur.execute(
        "UPDATE users SET points = points + ? WHERE telegram_id = ?",
        (earned, payload.telegram_id),
    )
    record_claim(cur, payload.telegram_id, payload.game_code)
    conn.commit()

    state = build_state_payload(cur, payload.telegram_id)
    conn.close()
    return {"earned_points": earned, "state": state}


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
        "UPDATE users SET points = points - ? WHERE telegram_id = ?",
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

    state = build_state_payload(cur, payload.telegram_id)
    conn.close()

    return {
        "message": "Withdraw request submitted for manual review",
        "amount_bdt": amount_bdt,
        "state": state,
    }


@app.get("/api/admin/withdrawals")
def list_withdrawals(secret: str):
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    conn = get_conn()
    rows = conn.execute("SELECT * FROM withdrawals ORDER BY id DESC").fetchall()
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
