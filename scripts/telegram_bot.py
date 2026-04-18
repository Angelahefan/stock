#!/usr/bin/env python3
"""
scripts/telegram_bot.py
─────────────────────────────────────────────────────────────────────────────
DataPAI Telegram Bot — links user accounts and provides watchlist status.

Commands:
  /start <token>  — Link Telegram account using a token from the website
  /stop           — Unlink Telegram account
  /status         — Show linked watchlist stocks

Env:
  TELEGRAM_BOT_TOKEN  — Bot token from @BotFather

Run:
  python3 scripts/telegram_bot.py
  (or via shell wrapper: bash scripts/run_telegram_bot.sh)
"""
import sys
import os
import logging
import asyncio
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
if (PROJECT_ROOT / ".env.dev").exists():
    load_dotenv(PROJECT_ROOT / ".env.dev")
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("telegram_bot")

# ── Telegram imports ──────────────────────────────────────────────────────
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ── DB helpers ────────────────────────────────────────────────────────────
from scripts.lib.db_helpers import get_conn


def _get_label(lang: str, key: str) -> str:
    """Fetch i18n label from DB, fallback to English."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT text FROM datapai.sys_lang_labels WHERE label_key = %s AND lang = %s",
                (key, lang),
            )
            row = cur.fetchone()
            if row:
                return row[0]
            # fallback to English
            cur.execute(
                "SELECT text FROM datapai.sys_lang_labels WHERE label_key = %s AND lang = 'en'",
                (key,),
            )
            row = cur.fetchone()
            return row[0] if row else key


# ── /start <token> ────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Link Telegram account using a website-generated token."""
    chat_id = str(update.effective_chat.id)
    args = context.args or []

    if not args:
        await update.message.reply_text(
            "Welcome to DataPAI Alerts!\n\n"
            "To link your account, go to your DataPAI settings page, "
            "generate a Telegram link token, then send:\n"
            "/start <your_token>"
        )
        return

    token = args[0].strip()

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Validate token
            cur.execute(
                "SELECT user_id FROM datapai.telegram_link_tokens "
                "WHERE token = %s AND used_at IS NULL",
                (token,),
            )
            row = cur.fetchone()
            if not row:
                await update.message.reply_text(
                    "Invalid or expired token. Please generate a new one from your DataPAI settings."
                )
                return

            user_id = row[0]

            # Mark token as used
            cur.execute(
                "UPDATE datapai.telegram_link_tokens SET used_at = NOW() WHERE token = %s",
                (token,),
            )

            # Upsert notification prefs for telegram channel
            cur.execute(
                """
                INSERT INTO datapai.usr_notification_prefs
                    (user_id, channel, enabled, telegram_chat_id)
                VALUES (%s, 'telegram', FALSE, %s)
                ON CONFLICT (user_id, channel) DO UPDATE SET
                    telegram_chat_id = EXCLUDED.telegram_chat_id,
                    updated_at = NOW()
                """,
                (user_id, chat_id),
            )
            conn.commit()

            # Get user's preferred language
            cur.execute(
                "SELECT lang FROM datapai.usr_notification_prefs "
                "WHERE user_id = %s AND channel = 'telegram'",
                (user_id,),
            )
            lang_row = cur.fetchone()
            lang = lang_row[0] if lang_row else "en"

    msg = _get_label(lang, "notif.bot_linked")
    msg += "\n\nNote: Alerts are currently disabled. Enable them from your DataPAI settings."
    await update.message.reply_text(msg)
    logger.info("Linked user %s to chat_id %s", user_id, chat_id)


# ── /stop ─────────────────────────────────────────────────────────────────
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unlink Telegram account."""
    chat_id = str(update.effective_chat.id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, lang FROM datapai.usr_notification_prefs "
                "WHERE channel = 'telegram' AND telegram_chat_id = %s",
                (chat_id,),
            )
            row = cur.fetchone()
            if not row:
                await update.message.reply_text("No account is linked to this chat.")
                return

            user_id, lang = row[0], row[1] or "en"

            cur.execute(
                "UPDATE datapai.usr_notification_prefs "
                "SET telegram_chat_id = NULL, enabled = FALSE, updated_at = NOW() "
                "WHERE user_id = %s AND channel = 'telegram'",
                (user_id,),
            )
            conn.commit()

    msg = _get_label(lang, "notif.bot_unlinked")
    await update.message.reply_text(msg)
    logger.info("Unlinked user %s from chat_id %s", user_id, chat_id)


# ── /status ───────────────────────────────────────────────────────────────
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show linked watchlist stocks and alert status."""
    chat_id = str(update.effective_chat.id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, enabled, alert_signal, alert_price, digest_weekly, max_daily "
                "FROM datapai.usr_notification_prefs "
                "WHERE channel = 'telegram' AND telegram_chat_id = %s",
                (chat_id,),
            )
            pref = cur.fetchone()
            if not pref:
                await update.message.reply_text("No account linked. Use /start <token> to link.")
                return

            user_id, enabled, alert_signal, alert_price, digest_weekly, max_daily = pref

            # Get watchlist
            cur.execute(
                "SELECT w.symbol, w.exchange, w.name "
                "FROM datapai.watchlist w WHERE w.user_id = %s ORDER BY w.symbol",
                (user_id,),
            )
            stocks = cur.fetchall()

            # Get today's sent count
            cur.execute(
                "SELECT COUNT(*) FROM datapai.notification_log "
                "WHERE user_id = %s AND channel = 'telegram' "
                "AND sent_at >= CURRENT_DATE AND status = 'sent'",
                (user_id,),
            )
            sent_today = cur.fetchone()[0]

    lines = [
        f"📊 *DataPAI Alert Status*",
        f"",
        f"Alerts enabled: {'✅ Yes' if enabled else '❌ No'}",
        f"Signal alerts: {'✅' if alert_signal else '❌'}",
        f"Price alerts: {'✅' if alert_price else '❌'}",
        f"Weekly digest: {'✅' if digest_weekly else '❌'}",
        f"Sent today: {sent_today}/{max_daily}",
        f"",
        f"*Watchlist ({len(stocks)} stocks):*",
    ]

    if stocks:
        for symbol, exchange, name in stocks:
            display = f"{symbol} ({exchange})"
            if name:
                display += f" — {name}"
            lines.append(f"  • {display}")
    else:
        lines.append("  (empty — add stocks on datap.ai)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set — cannot start bot")
        sys.exit(1)

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("status", cmd_status))

    logger.info("DataPAI Telegram bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
