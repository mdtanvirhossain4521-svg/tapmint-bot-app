<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>TapMint</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  body {
    background: radial-gradient(circle at 50% 8%, #152b30 0%, #091114 58%, #05090b 100%);
    color: #f1f5f9;
    min-height: 100vh;
    padding-bottom: 94px;
  }
  .phone-frame { max-width: 430px; margin: 0 auto; padding: 10px 14px 20px; }
  .tg-top {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 4px 12px;
  }
  .tg-brand { font-size: 19px; font-weight: 800; color: #f8fafc; display: flex; align-items: center; gap: 6px; }
  .tg-badge {
    width: 17px; height: 17px; border-radius: 50%; background: #38bdf8; color: #062230;
    font-size: 11px; font-weight: 900; display: inline-flex; align-items: center; justify-content: center;
  }
  .tg-sub { font-size: 11px; color: #64748b; margin-top: 1px; }
  .card {
    background: linear-gradient(180deg, rgba(23, 38, 44, 0.94) 0%, rgba(12, 21, 25, 0.97) 100%);
    border: 1px solid rgba(148, 163, 184, 0.15);
    border-radius: 18px;
    padding: 14px;
    margin-bottom: 11px;
    box-shadow: 0 12px 24px rgba(0, 0, 0, 0.48), inset 0 1px 0 rgba(255, 255, 255, 0.06);
  }
  .page { display: none; }
  .page.active { display: block; }

  /* Balance & Boost */
  .bal-wrap { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .bal-left { display: flex; align-items: center; gap: 12px; }
  .gold-coin {
    width: 44px; height: 44px; border-radius: 50%;
    background: radial-gradient(circle at 30% 28%, #fef08a 0%, #f59e0b 55%, #b45309 100%);
    border: 2px solid #fde68a;
    box-shadow: 0 5px 14px rgba(245, 158, 11, 0.35), inset 0 2px 4px rgba(255, 255, 255, 0.65);
    display: flex; align-items: center; justify-content: center;
    font-weight: 900; font-size: 18px; color: #78350f; flex-shrink: 0;
  }
  .muted { color: #94a3b8; font-size: 12px; }
  .pts-big { font-size: 26px; font-weight: 800; color: #ffffff; line-height: 1.15; }
  .boost-btn {
    background: rgba(16, 185, 129, 0.16); border: 1px solid rgba(52, 211, 153, 0.45);
    color: #34d399; font-weight: 700; font-size: 12px; padding: 6px 10px; border-radius: 10px;
  }

  /* Day 3/7 */
  .day-row { display: flex; align-items: center; justify-content: space-between; }
  .dots-row { display: flex; gap: 7px; }
  .dot-c {
    width: 22px; height: 22px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 800;
  }
  .dot-c.ok { background: #10b981; color: #052e16; }
  .dot-c.no { background: rgba(148, 163, 184, 0.14); color: #64748b; border: 1px solid rgba(148, 163, 184, 0.22); }

  /* Spin Wheel with labels */
  .spin-head { display: flex; justify-content: space-between; align-items: flex-start; }
  .wheel-stage { position: relative; width: 248px; height: 248px; margin: 12px auto 12px; display: flex; align-items: center; justify-content: center; }
  .pointer-top {
    position: absolute; top: -6px; left: 50%; transform: translateX(-50%); z-index: 8;
    width: 0; height: 0; border-left: 11px solid transparent; border-right: 11px solid transparent;
    border-top: 21px solid #facc15; filter: drop-shadow(0 3px 4px rgba(0, 0, 0, 0.65));
  }
  .wheel-rim {
    width: 238px; height: 238px; border-radius: 50%; padding: 7px;
    background: radial-gradient(circle at 30% 25%, #475569, #0f172a);
    border: 2px solid rgba(250, 204, 21, 0.45);
    box-shadow: 0 12px 26px rgba(0, 0, 0, 0.65);
    position: relative;
  }
  .wheel-rotor {
    width: 100%; height: 100%; border-radius: 50%; position: relative;
    background: conic-gradient(
      #10b981 0deg 51.4deg,
      #eab308 51.4deg 102.8deg,
      #f97316 102.8deg 154.2deg,
      #06b6d4 154.2deg 205.6deg,
      #22c55e 205.6deg 257deg,
      #ec4899 257deg 308.4deg,
      #8b5cf6 308.4deg 360deg
    );
    transition: transform 2.5s cubic-bezier(0.16, 0.88, 0.22, 1);
    overflow: hidden;
  }
  .slice-lbl {
    position: absolute; left: 50%; top: 50%;
    transform-origin: 0 0;
    font-size: 11px; font-weight: 800; color: #ffffff;
    text-shadow: 0 1px 3px rgba(0, 0, 0, 0.8);
    white-space: nowrap; pointer-events: none;
  }
  .spin-hub {
    position: absolute; z-index: 9; width: 68px; height: 68px; border-radius: 50%;
    background: radial-gradient(circle at 35% 30%, #334155, #0f172a);
    border: 3px solid #facc15; color: #ffffff; font-weight: 900; font-size: 13px;
    line-height: 1.15; text-align: center; cursor: pointer;
    box-shadow: 0 6px 14px rgba(0, 0, 0, 0.7);
  }
  .btn-green {
    width: 100%; border: none; border-radius: 14px; padding: 13px 16px;
    background: linear-gradient(180deg, #4ade80 0%, #22c55e 100%);
    color: #052e16; font-weight: 800; font-size: 15px; cursor: pointer;
    box-shadow: 0 6px 18px rgba(34, 197, 94, 0.28);
  }
  .btn-green:disabled { opacity: 0.45; cursor: not-allowed; }

  .home-link-card {
    display: flex; align-items: center; justify-content: space-between;
    background: linear-gradient(180deg, rgba(23, 38, 44, 0.92), rgba(12, 21, 25, 0.97));
    border: 1px solid rgba(148, 163, 184, 0.15); border-radius: 16px;
    padding: 13px 14px; margin-bottom: 10px; cursor: pointer;
  }
  .sq-icon {
    width: 36px; height: 36px; border-radius: 11px;
    background: rgba(52, 211, 153, 0.12); border: 1px solid rgba(52, 211, 153, 0.26);
    display: flex; align-items: center; justify-content: center; font-size: 17px; flex-shrink: 0;
  }

  /* Sessions & Tasks */
  .sess-5 { display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; margin-bottom: 12px; }
  .sess-pill {
    background: rgba(15, 25, 29, 0.95); border: 1px solid rgba(148, 163, 184, 0.16);
    border-radius: 12px; padding: 8px 3px; text-align: center; cursor: pointer;
  }
  .sess-pill.active { border-color: #34d399; background: rgba(16, 185, 129, 0.14); }
  .sess-pill.locked { opacity: 0.72; }
  .sess-n { font-size: 11px; font-weight: 800; color: #f8fafc; }
  .sess-st { font-size: 10px; color: #94a3b8; margin-top: 3px; line-height: 1.25; }
  .sess-pill.active .sess-st { color: #34d399; font-weight: 700; }

  .row-card {
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
    background: rgba(15, 25, 29, 0.94); border: 1px solid rgba(148, 163, 184, 0.15);
    border-radius: 16px; padding: 12px; margin-bottom: 10px;
  }
  .wait-badge {
    display: inline-block; margin-top: 5px; font-size: 11px; font-weight: 600;
    color: #fbbf24; background: rgba(245, 158, 11, 0.14);
    border: 1px solid rgba(245, 158, 11, 0.28); padding: 3px 8px; border-radius: 8px;
  }
  .open-btn {
    background: linear-gradient(180deg, #4ade80, #22c55e); color: #052e16;
    border: none; border-radius: 12px; padding: 9px 14px; font-weight: 800;
    font-size: 12px; cursor: pointer; white-space: nowrap;
  }
  .alert-box {
    background: rgba(120, 53, 15, 0.28); border: 1px solid rgba(245, 158, 11, 0.36);
    color: #fde68a; border-radius: 14px; padding: 11px 12px; font-size: 12px;
    line-height: 1.45; margin-top: 10px;
  }

  /* Mining */
  .m-top-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }
  .m-stat {
    background: rgba(15, 25, 29, 0.94); border: 1px solid rgba(148, 163, 184, 0.15);
    border-radius: 14px; padding: 10px 12px; display: flex; align-items: center; gap: 10px;
  }
  .coin-pedestal {
    width: 118px; height: 118px; margin: 4px auto 4px; border-radius: 50%;
    background: radial-gradient(circle at 30% 25%, #fef08a 0%, #eab308 58%, #92400e 100%);
    border: 4px solid #fde68a; box-shadow: 0 12px 26px rgba(234, 179, 8, 0.28);
    display: flex; align-items: center; justify-content: center;
  }
  .coin-leaf {
    width: 88px; height: 88px; border-radius: 50%;
    background: radial-gradient(circle at 35% 30%, #34d399, #0f766e);
    display: flex; align-items: center; justify-content: center; font-size: 40px;
    box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.4);
  }
  .pedestal-glow {
    width: 164px; height: 28px; margin: -6px auto 12px; border-radius: 50%;
    background: radial-gradient(ellipse at center, rgba(45, 212, 191, 0.55) 0%, rgba(16, 185, 129, 0.12) 65%, transparent 100%);
    border-top: 2px solid rgba(94, 234, 212, 0.75);
  }
  .active-box {
    background: rgba(15, 25, 29, 0.94); border: 1px solid rgba(148, 163, 184, 0.16);
    border-radius: 16px; padding: 12px; margin-bottom: 12px;
  }
  .active-lbl { font-size: 11px; font-weight: 800; color: #2dd4bf; letter-spacing: 0.6px; }
  .active-clock { font-size: 28px; font-weight: 800; color: #ffffff; margin-top: 2px; }

  /* Games */
  .g-icon {
    width: 56px; height: 56px; border-radius: 14px;
    background: linear-gradient(145deg, #1e293b, #0f172a);
    border: 1px solid rgba(148, 163, 184, 0.24);
    display: flex; align-items: center; justify-content: center; font-size: 25px; flex-shrink: 0;
  }

  /* Wallet */
  .pin-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 10px 0 6px; }
  .pin-box {
    height: 44px; border-radius: 12px; background: rgba(9, 17, 20, 0.92);
    border: 1px solid rgba(148, 163, 184, 0.24);
    display: flex; align-items: center; justify-content: center; font-size: 20px; color: #34d399;
  }
  .pay-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 8px 0 12px; }
  .pay-btn {
    background: rgba(15, 25, 29, 0.92); border: 1px solid rgba(148, 163, 184, 0.18);
    color: #cbd5e1; border-radius: 12px; padding: 10px 6px; font-weight: 700; font-size: 13px; cursor: pointer;
  }
  .pay-btn.active { background: linear-gradient(180deg, #4ade80, #22c55e); color: #052e16; border-color: #86efac; }
  .inp {
    width: 100%; background: rgba(9, 17, 20, 0.92); border: 1px solid rgba(148, 163, 184, 0.22);
    color: #ffffff; border-radius: 12px; padding: 11px 12px; font-size: 14px; margin-bottom: 10px;
  }

  /* Bottom Nav: Home -> Tasks -> Mining -> Games -> Refer -> Wallet */
  .bnav {
    position: fixed; bottom: 0; left: 0; right: 0; z-index: 40;
    background: rgba(10, 18, 22, 0.97); backdrop-filter: blur(12px);
    border-top: 1px solid rgba(148, 163, 184, 0.14); padding: 6px 8px 10px;
  }
  .bnav-inner { max-width: 430px; margin: 0 auto; display: grid; grid-template-columns: repeat(6, 1fr); gap: 4px; }
  .bnav-item {
    border: none; background: transparent; color: #94a3b8; border-radius: 12px;
    padding: 6px 2px; cursor: pointer; text-align: center; font-size: 11px; font-weight: 600;
  }
  .bnav-item.active {
    background: linear-gradient(180deg, #4ade80, #22c55e);
    color: #052e16; font-weight: 800; box-shadow: 0 4px 12px rgba(34, 197, 94, 0.35);
  }
  .bnav-item span { display: block; font-size: 16px; margin-bottom: 2px; }
  .toast {
    position: fixed; top: 14px; left: 50%; transform: translateX(-50%); z-index: 95;
    background: #132a30; border: 1px solid #34d399; color: #ecfdf5;
    padding: 10px 16px; border-radius: 12px; font-size: 13px; font-weight: 700; display: none;
  }
</style>
</head>
<body>
<div class="toast" id="toast"></div>
<div class="phone-frame">
  <div class="tg-top">
    <div>
      <div class="tg-brand">TapMint <span class="tg-badge">✓</span></div>
      <div class="tg-sub">bot</div>
    </div>
    <div class="muted" style="font-weight:700;" id="hdr-pts">0 PTS</div>
  </div>

  <!-- HOME -->
  <section class="page active" id="page-home">
    <div class="card">
      <div class="bal-wrap">
        <div class="bal-left">
          <div class="gold-coin">1</div>
          <div>
            <div class="muted">Available Balance</div>
            <div class="pts-big" id="home-bal">0 PTS</div>
          </div>
        </div>
        <div class="boost-btn">+15% Boost</div>
      </div>
    </div>

    <div class="card" style="padding:11px 14px;">
      <div class="day-row">
        <div style="font-weight:700;font-size:14px;">Day 3/7</div>
        <div class="dots-row">
          <div class="dot-c ok">✓</div>
          <div class="dot-c ok">✓</div>
          <div class="dot-c ok">✓</div>
          <div class="dot-c no">✓</div>
          <div class="dot-c no">✓</div>
          <div class="dot-c no">✓</div>
          <div class="dot-c no">✓</div>
        </div>
      </div>
    </div>

    <div class="card" style="text-align:center;">
      <div class="spin-head">
        <div style="text-align:left;">
          <div style="font-size:16px;font-weight:800;">Daily Spin & Win</div>
          <div class="muted" style="margin-top:2px;">ডেইলি স্পিন হুইল • সর্বোচ্চ ১৫ PTS</div>
        </div>
        <div style="text-align:right;">
          <div class="muted" style="font-size:11px;">Max Reward:</div>
          <div style="font-size:14px;font-weight:800;color:#fbbf24;">15 PTS</div>
        </div>
      </div>

      <div class="wheel-stage">
        <div class="pointer-top"></div>
        <div class="wheel-rim">
          <div class="wheel-rotor" id="wheel-rotor">
            <div class="slice-lbl" style="transform: rotate(-64deg) translate(56px, -6px);">1 PTS</div>
            <div class="slice-lbl" style="transform: rotate(-13deg) translate(56px, -6px);">2 PTS</div>
            <div class="slice-lbl" style="transform: rotate(38deg) translate(54px, -6px);">5 PTS</div>
            <div class="slice-lbl" style="transform: rotate(90deg) translate(50px, -6px);">10 PTS</div>
            <div class="slice-lbl" style="transform: rotate(141deg) translate(46px, -6px);">15 PTS</div>
            <div class="slice-lbl" style="transform: rotate(192deg) translate(42px, -6px);">Bonus</div>
            <div class="slice-lbl" style="transform: rotate(244deg) translate(38px, -6px);">Try Again</div>
          </div>
        </div>
        <button class="spin-hub" onclick="doSpin()">SPIN<br/>NOW</button>
      </div>

      <div id="spin-msg" style="font-size:13px;font-weight:800;color:#34d399;min-height:18px;margin-bottom:8px;"></div>
      <button class="btn-green" id="spin-btn" onclick="doSpin()">SPIN NOW</button>
      <div id="spin-status" class="muted" style="margin-top:10px;">1 Spin Available Today</div>
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

  <!-- TASKS CENTER -->
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

  <!-- MINING -->
  <section class="page" id="page-mining">
    <div style="text-align:center;margin-bottom:12px;">
      <div style="font-size:20px;font-weight:800;">TapMint Mining</div>
      <div class="muted" style="margin-top:2px;">প্রতি ২ ঘণ্টা পরপর মাইনিং • দিনে সর্বোচ্চ ৬ বার</div>
    </div>

    <div class="m-top-grid">
      <div class="m-stat">
        <div style="font-size:18px;">📅</div>
        <div>
          <div class="muted" style="font-size:11px;">Today's Claims:</div>
          <div style="font-size:14px;font-weight:800;" id="m-claims">0 / 6</div>
        </div>
      </div>
      <div class="m-stat">
        <div style="font-size:18px;">⚡</div>
        <div>
          <div class="muted" style="font-size:11px;">Mining Rate:</div>
          <div style="font-size:14px;font-weight:800;">~6 PTS / Session</div>
        </div>
      </div>
    </div>

    <div class="card" style="text-align:center;">
      <div class="coin-pedestal"><div class="coin-leaf">🌿</div></div>
      <div class="pedestal-glow"></div>
      <div class="active-box">
        <div class="active-lbl" id="m-badge">MINING ACTIVE</div>
        <div class="active-clock" id="m-clock">00:00:00</div>
      </div>
      <div class="muted" style="margin-bottom:12px;">Earn 5 to 10 PTS each claim</div>
      <button class="btn-green" id="m-btn" onclick="doMining()">READY TO CLAIM</button>
    </div>

    <div class="alert-box" style="background:rgba(30,41,59,0.55);border-color:rgba(148,163,184,0.25);color:#cbd5e1;">
      🕒 ২ ঘণ্টা পরপর মাইনিং • দিনে সর্বোচ্চ ৬ বার ক্লেম করা যাবে • পয়েন্ট সরাসরি ওয়ালেটে যোগ হবে
    </div>
  </section>

  <!-- GAMES ARENA -->
  <section class="page" id="page-games">
    <div style="text-align:center;margin-bottom:14px;">
      <div style="font-size:20px;font-weight:800;">Games Arena</div>
      <div class="muted" style="margin-top:3px;">
        গেম খেলে পয়েন্ট ক্লেম করুন (অবশ্যই খেলার পর পয়েন্ট পাওয়ার জন্য অ্যাড দেখতে হবে)
      </div>
    </div>
    <div id="game-rows"></div>
    <div class="alert-box">
      🎮 প্রতিটি গেম শেষ করার পর পয়েন্ট পেতে অ্যাড দেখা বাধ্যতামূলক
    </div>
  </section>

  <!-- REFER -->
  <section class="page" id="page-refer">
    <div class="card">
      <div style="font-size:18px;font-weight:800;margin-bottom:12px;">Referral Center</div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;text-align:center;margin-bottom:12px;">
        <div style="background:rgba(9,17,20,0.85);padding:10px;border-radius:12px;">
          <div style="font-size:18px;font-weight:800;" id="ref-cnt">0</div>
          <div class="muted" style="font-size:11px;">Total Referrals</div>
        </div>
        <div style="background:rgba(9,17,20,0.85);padding:10px;border-radius:12px;">
          <div style="font-size:18px;font-weight:800;" id="ref-act">0</div>
          <div class="muted" style="font-size:11px;">Active Referrals</div>
        </div>
        <div style="background:rgba(9,17,20,0.85);padding:10px;border-radius:12px;">
          <div style="font-size:18px;font-weight:800;color:#34d399;" id="ref-pts">0</div>
          <div class="muted" style="font-size:11px;">Current Bonus</div>
        </div>
      </div>
      <input class="inp" id="ref-url" readonly />
      <button class="btn-green" onclick="copyRef()">Copy Referral Link</button>
    </div>
  </section>

  <!-- WALLET & WITHDRAW -->
  <section class="page" id="page-wallet">
    <div style="margin-bottom:12px;">
      <div style="font-size:20px;font-weight:800;">Wallet & Withdraw</div>
      <div class="muted" style="margin-top:2px;" id="w-sub">সর্বনিম্ন উইথড্র পয়েন্ট হলে উইথড্র নিতে পারবেন</div>
    </div>

    <div class="card" style="text-align:center;">
      <div class="muted" style="margin-bottom:6px;">Available Balance</div>
      <div style="display:flex;align-items:center;justify-content:center;gap:10px;">
        <div class="gold-coin" style="width:36px;height:36px;font-size:15px;">1</div>
        <div style="font-size:26px;font-weight:800;" id="w-bal">0 PTS</div>
      </div>
    </div>

    <div class="card" style="padding:12px 14px;">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
        <div>
          <div style="font-size:13px;font-weight:700;color:#34d399;" id="w-conn">Wallet Not Connected</div>
          <div class="muted" style="font-size:11px;margin-top:2px;" id="w-ver">Connect wallet & set 4-digit PIN</div>
        </div>
        <button class="pay-btn" style="padding:7px 12px;" onclick="toggleWForm()">Change Wallet</button>
      </div>
      <div id="w-form" style="display:none;margin-top:12px;padding-top:12px;border-top:1px solid rgba(148,163,184,0.14);">
        <input class="inp" id="w-acc" placeholder="Wallet Number / Binance Address" />
        <input class="inp" id="w-pin-set" type="password" maxlength="4" placeholder="Set 4-Digit PIN" />
        <button class="btn-green" onclick="saveW()">Save Wallet & PIN</button>
      </div>
    </div>

    <div class="card" style="text-align:center;">
      <div style="font-size:13px;font-weight:700;">Enter 4-Digit PIN to Confirm Withdraw</div>
      <div class="pin-4">
        <div class="pin-box" id="p0">•</div>
        <div class="pin-box" id="p1">•</div>
        <div class="pin-box" id="p2">•</div>
        <div class="pin-box" id="p3">•</div>
      </div>
      <div class="muted" style="font-size:11px;margin-top:6px;">ওয়ালেট কানেক্ট করার সময় সেট করা ৪ সংখ্যার পিন দিন।</div>
      <input class="inp" style="margin-top:10px;text-align:center;letter-spacing:8px;" id="w-pin-confirm" type="password" maxlength="4" placeholder="••••" oninput="paintPin()" />
    </div>

    <div class="card">
      <div style="font-size:13px;font-weight:700;">Payment Method</div>
      <div class="pay-3">
        <button class="pay-btn active" id="pm-bKash" onclick="setPay('bKash')">bKash</button>
        <button class="pay-btn" id="pm-Nagad" onclick="setPay('Nagad')">Nagad</button>
        <button class="pay-btn" id="pm-Binance USDT" onclick="setPay('Binance USDT')">Binance USDT</button>
      </div>

      <div style="font-size:13px;font-weight:700;margin-bottom:6px;" id="w-pts-lbl">Points to Withdraw</div>
      <input class="inp" id="w-pts-val" type="number" placeholder="1,000" />
      <div class="muted" style="font-size:11px;line-height:1.45;margin-bottom:12px;" id="w-fee-txt">
        উইথড্র রিকোয়েস্ট সাবমিট করলে নির্ধারিত ফি কেটে নেওয়া হবে।<br/>
        *Binance withdrawals incur standard network fees.
      </div>
      <button class="btn-green" onclick="reqWithdraw()">
        Send Withdraw Request
        <div style="font-size:11px;font-weight:600;opacity:0.88;margin-top:1px;">Processing fee applied</div>
      </button>
    </div>
  </section>
</div>

<!-- 3D BOTTOM NAV: Home -> Tasks -> Mining -> Games -> Refer -> Wallet -->
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
const USER = qp.get("user_id") || "user_1001";
const NAME = qp.get("username") || "TapMintUser";
const REF = qp.get("ref") || "";

let ST = null;
let SESS = 1;
let PAY = "bKash";
let DEG = 0;

function notify(t) {
  const el = document.getElementById("toast");
  el.textContent = t;
  el.style.display = "block";
  clearTimeout(window._nt);
  window._nt = setTimeout(() => { el.style.display = "none"; }, 2800);
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
  });
  syncWCopy();
}

function syncWCopy() {
  if (!ST) return;
  const wr = ST.withdraw_rules;
  document.getElementById("w-sub").textContent = `সর্বনিম্ন ${wr.general_min_pts} PTS হলে উইথড্র নিতে পারবেন`;
  if (PAY === "Binance USDT") {
    document.getElementById("w-pts-lbl").textContent = `Points to Withdraw (Min ${wr.binance_min_pts} PTS)`;
    document.getElementById("w-fee-txt").innerHTML =
      `উইথড্র রিকোয়েস্ট সাবমিট করলে নির্ধারিত ফি কেটে নেওয়া হবে।<br/>*Binance USDT minimum $${wr.binance_min_usdt_rule} equivalent & standard network fees apply.`;
  } else {
    document.getElementById("w-pts-lbl").textContent = `Points to Withdraw (Min ${wr.general_min_pts})`;
    document.getElementById("w-fee-txt").innerHTML =
      `উইথড্র রিকোয়েস্ট সাবমিট করলে নির্ধারিত ফি কেটে নেওয়া হবে।<br/>*Binance withdrawals incur standard network fees.`;
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

function draw() {
  if (!ST) return;
  const b = ST.user.pts_balance;
  document.getElementById("hdr-pts").textContent = b.toLocaleString() + " PTS";
  document.getElementById("home-bal").textContent = b.toLocaleString() + " PTS";
  document.getElementById("w-bal").textContent = b.toLocaleString() + " PTS";

  const used = ST.spin.spins_used_today;
  document.getElementById("spin-btn").disabled = used >= ST.spin.max_daily;
  document.getElementById("spin-status").textContent = used >= ST.spin.max_daily
    ? `Next free spin in: ${fmtTime(ST.spin.next_spin_at)}`
    : "1 Spin Available Today";

  const clm = ST.mining.claims_today;
  const maxC = ST.mining.max_daily;
  const activeM = ST.mining.next_claim_at && new Date() < new Date(ST.mining.next_claim_at);
  document.getElementById("m-claims").textContent = `${clm} / ${maxC}`;
  document.getElementById("m-clock").textContent = activeM ? fmtTime(ST.mining.next_claim_at) : "00:00:00";
  document.getElementById("m-badge").textContent = activeM ? "MINING ACTIVE" : "MINING READY";
  document.getElementById("home-m-txt").textContent = activeM ? `${fmtTime(ST.mining.next_claim_at)} left` : "Ready to claim";

  const mb = document.getElementById("m-btn");
  if (clm >= maxC) {
    mb.disabled = true;
    mb.textContent = "DAILY LIMIT REACHED (6/6)";
  } else if (activeM) {
    mb.disabled = true;
    mb.textContent = `Next claim in ${fmtTime(ST.mining.next_claim_at)}`;
  } else {
    mb.disabled = false;
    mb.textContent = "READY TO CLAIM";
  }

  const doneS = ST.task_sessions.filter(x => x.completed_count >= 20).length;
  document.getElementById("home-t-txt").textContent = `${doneS}/5 Completed`;

  drawSessions();
  drawTasks();
  drawGames();

  document.getElementById("ref-cnt").textContent = ST.referral.total_referrals;
  document.getElementById("ref-act").textContent = ST.referral.active_referrals;
  document.getElementById("ref-pts").textContent = ST.referral.current_bonus_pts;
  document.getElementById("ref-url").value = `${window.location.origin}/?ref=${encodeURIComponent(USER)}`;

  if (ST.wallet.connected) {
    document.getElementById("w-conn").textContent =
      `Connected Wallet: ${ST.wallet.method} (${ST.wallet.masked_target})`;
    document.getElementById("w-ver").textContent = "● Connected & Verified";
    setPay(ST.wallet.method);
  }
  syncWCopy();
}

function drawSessions() {
  const wrap = document.getElementById("sess-5");
  wrap.innerHTML = "";
  for (const s of ST.task_sessions) {
    const el = document.createElement("div");
    el.className = "sess-pill" + (s.session_num === SESS ? " active" : "") + (s.is_locked ? " locked" : "");
    el.innerHTML = `
      <div class="sess-n">Session ${s.session_num}</div>
      <div class="sess-st">${s.is_locked ? "🔒 Locked<br/>" + fmtTime(s.locked_until) : (s.session_num === SESS ? "● Active<br/>20 Tasks" : s.completed_count + "/20")}</div>
    `;
    el.onclick = () => { SESS = s.session_num; drawSessions(); drawTasks(); };
    wrap.appendChild(el);
  }
}

function drawTasks() {
  const cur = ST.task_sessions.find(x => x.session_num === SESS);
  const done = cur ? cur.completed_count : 0;
  document.getElementById("sess-title").textContent = `Session ${SESS}: 20 Tasks (${done}/20 Completed)`;

  const list = document.getElementById("task-rows");
  list.innerHTML = "";
  if (cur && cur.is_locked) {
    list.innerHTML = `<div class="card" style="text-align:center;color:#fbbf24;font-size:13px;">
      Session ${SESS} Locked (${fmtTime(cur.locked_until)} বাকি)
    </div>`;
    return;
  }

  for (let i = 1; i <= 20; i++) {
    const ico = i % 2 === 1 ? "🔗" : "🪙";
    const row = document.createElement("div");
    row.className = "row-card";
    row.innerHTML = `
      <div style="display:flex;align-items:center;gap:12px;">
        <div class="g-icon" style="width:42px;height:42px;font-size:18px;">${ico}</div>
        <div>
          <div style="font-weight:700;font-size:14px;">Task ${String(i).padStart(2, "0")}</div>
          <div style="font-size:12px;color:#34d399;font-weight:700;">Reward: +2 PTS</div>
          <div class="wait-badge">🕒 8-10s Wait Required</div>
        </div>
      </div>
      <button class="open-btn" id="ot-${SESS}-${i}" onclick="startTask(${SESS},${i})">Open Task</button>
    `;
    list.appendChild(row);
  }
}

async function startTask(sNum, tNum) {
  const btn = document.getElementById(`ot-${sNum}-${tNum}`);
  btn.disabled = true;
  const op = await fetch("/api/task/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER, username: NAME, session_num: sNum, task_num: tNum })
  }).then(r => r.json());
  if (!op.ok) {
    notify(op.error || "Cannot open task");
    btn.disabled = false;
    return;
  }
  if (op.launch_url) window.open(op.launch_url, "_blank", "noopener,noreferrer");
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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: USER, username: NAME, session_num: sNum, task_num: tNum })
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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER, username: NAME })
  }).then(x => x.json());
  if (!r.ok) return notify(r.error || "Spin not ready");

  DEG += 1080 + Math.floor(Math.random() * 280);
  document.getElementById("wheel-rotor").style.transform = `rotate(${DEG}deg)`;
  document.getElementById("spin-msg").textContent = `${r.slot} (+${r.pts_earned} PTS)`;
  setTimeout(async () => {
    notify(`+${r.pts_earned} PTS added!`);
    await loadApp();
  }, 2500);
}

async function doMining() {
  const r = await fetch("/api/mining/claim", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER, username: NAME })
  }).then(x => x.json());
  if (r.ok) {
    notify(`+${r.pts_earned} PTS mined!`);
    await loadApp();
  } else {
    notify(r.error || "Mining not ready");
  }
}

function drawGames() {
  const arr = [
    { ico: "🕹", title: "Tap Surge Combo", tgt: "Score Target: 50+", pts: 5 },
    { ico: "👾", title: "Catch & Dodge 3D", tgt: "Score Target: 20+", pts: 5 },
    { ico: "🔢", title: "Number Merge 2048", tgt: "Target: 512+ Tile", pts: 6 },
    { ico: "🐍", title: "Neon Snake Arcade", tgt: "Score Target: 30+", pts: 5 },
  ];
  const box = document.getElementById("game-rows");
  box.innerHTML = "";
  for (const g of arr) {
    const el = document.createElement("div");
    el.className = "row-card";
    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:12px;">
        <div class="g-icon">${g.ico}</div>
        <div>
          <div style="font-weight:800;font-size:15px;">${g.title}</div>
          <div class="muted">${g.tgt}</div>
          <div style="font-size:12px;color:#34d399;font-weight:700;">Reward: +${g.pts} PTS (Ad Required)</div>
          <div style="font-size:11px;color:#64748b;margin-top:2px;">বিজ্ঞাপন দেখার পর পয়েন্ট অ্যাকাউন্টে যোগ হবে</div>
        </div>
      </div>
      <button class="open-btn" onclick="runGame('${g.title}',${g.pts})">Play Fullscreen</button>
    `;
    box.appendChild(el);
  }
}

async function runGame(name, pts) {
  const st = await fetch("/api/game/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER, username: NAME, game_name: name, reward_pts: pts })
  }).then(x => x.json());
  if (!st.ok) return notify(st.error);

  notify("গেম চলছে... পয়েন্ট পেতে অ্যাড দেখুন");
  setTimeout(async () => {
    await fetch("/api/game/ad-complete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: USER, session_token: st.session_token })
    });
    const cl = await fetch("/api/game/claim", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: USER, session_token: st.session_token })
    }).then(x => x.json());
    if (cl.ok) {
      notify(`+${cl.pts_earned} PTS earned!`);
      await loadApp();
    } else {
      notify(cl.error || "Ad required");
    }
  }, 3200);
}

function copyRef() {
  const el = document.getElementById("ref-url");
  el.select();
  navigator.clipboard?.writeText(el.value);
  notify("Referral link copied");
}

async function saveW() {
  const acc = document.getElementById("w-acc").value.trim();
  const pin = document.getElementById("w-pin-set").value.trim();
  const r = await fetch("/api/wallet/connect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER, username: NAME, method: PAY, account_target: acc, pin })
  }).then(x => x.json());
  if (r.ok) {
    document.getElementById("w-pin-set").value = "";
    document.getElementById("w-form").style.display = "none";
    notify("Wallet & 4-digit PIN saved");
    await loadApp();
  } else {
    notify(r.error || "Failed");
  }
}

async function reqWithdraw() {
  const val = parseInt(document.getElementById("w-pts-val").value || "0", 10);
  const pin = document.getElementById("w-pin-confirm").value.trim();
  const r = await fetch("/api/withdraw/request", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER, requested_pts: val, pin, method: PAY })
  }).then(x => x.json());
  if (r.ok) {
    document.getElementById("w-pin-confirm").value = "";
    paintPin();
    notify(`Withdraw #${r.withdraw_id} sent`);
    await loadApp();
  } else {
    notify(r.error || "Withdraw failed");
  }
}

async function loadApp() {
  const q = new URLSearchParams({ user_id: USER, username: NAME, ref: REF });
  const r = await fetch("/api/user/bootstrap?" + q.toString()).then(x => x.json());
  if (r.ok) {
    ST = r;
    draw();
  }
}

setInterval(() => {
  if (ST) {
    const activeM = ST.mining.next_claim_at && new Date() < new Date(ST.mining.next_claim_at);
    if (activeM) {
      document.getElementById("m-clock").textContent = fmtTime(ST.mining.next_claim_at);
      document.getElementById("home-m-txt").textContent = `${fmtTime(ST.mining.next_claim_at)} left`;
    }
  }
}, 1000);

loadApp();
</script>
</body>
</html>
