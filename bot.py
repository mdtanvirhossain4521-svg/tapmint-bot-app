import os
from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from database import get_conn, init_db

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-app-url.example.com")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_db()
    tg_user = update.effective_user
    if not tg_user:
        return

    referrer_id = None
    if context.args:
        try:
            ref_candidate = int(context.args[0])
            if ref_candidate != tg_user.id:
                referrer_id = ref_candidate
        except ValueError:
            referrer_id = None

    conn = get_conn()
    cur = conn.cursor()

    existing = cur.execute(
        "SELECT telegram_id FROM users WHERE telegram_id = ?", (tg_user.id,)
    ).fetchone()

    if not existing:
        valid_ref = None
        if referrer_id:
            ref_row = cur.execute(
                "SELECT telegram_id FROM users WHERE telegram_id = ?", (referrer_id,)
            ).fetchone()
            if ref_row:
                valid_ref = referrer_id

        cur.execute(
            """
            INSERT INTO users (telegram_id, username, referred_by)
            VALUES (?, ?, ?)
            """,
            (tg_user.id, tg_user.username or "", valid_ref),
        )
        conn.commit()

    conn.close()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                text="TapMint মিনি অ্যাপ ওপেন করুন",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        ]
    ])

    await update.message.reply_text(
        "TapMint-এ স্বাগতম! নিচের বাটন থেকে মিনি অ্যাপ ওপেন করে কাজ শুরু করুন।\n"
        "• রেফার না করলেও মিনিমাম পয়েন্ট হলে উইথড্র করতে পারবেন।\n"
        "• রেফার করলে অ্যাক্টিভ রেফারেল অনুযায়ী বোনাস বাড়বে।",
        reply_markup=keyboard,
    )


def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN":
        print("BOT_TOKEN সেট করুন।")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()


if __name__ == "__main__":
    main()
