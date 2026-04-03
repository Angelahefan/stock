#!/usr/bin/env python3
"""
scripts/send_alerts.py
─────────────────────────────────────────────────────────────────────────────
Check for signal changes (BUY/SELL flips) on watchlist stocks and send
Telegram alerts to subscribed users.

Runs via Airflow every 30 min during market hours.

Logic:
  1. Find stocks where overall_signal changed (stock_synthesis.direction)
     by comparing current vs previous notification_log entries.
  2. For each user with that stock in their watchlist:
     - Check notification prefs (enabled, alert_signal, max_daily)
     - Send Telegram message if not throttled
     - Log to notification_log

Env:
  TELEGRAM_BOT_TOKEN — for sending messages
"""
import sys
import os
import logging
from pathlib import Path
from datetime import date

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
logger = logging.getLogger("send_alerts")


def _get_label(conn, lang: str, key: str) -> str:
    """Fetch i18n label, fallback to English."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT text FROM datapai.sys_lang_labels WHERE label_key = %s AND lang = %s",
            (key, lang),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            "SELECT text FROM datapai.sys_lang_labels WHERE label_key = %s AND lang = 'en'",
            (key,),
        )
        row = cur.fetchone()
        return row[0] if row else key


def _get_signal_changes(conn) -> list[dict]:
    """
    Find stocks where the AI signal (stock_synthesis.direction) has changed
    since the last alert was sent for that ticker.

    Returns list of {ticker, exchange, new_direction, old_direction, confidence, thesis}.
    """
    with conn.cursor() as cur:
        # Get current signals for all watchlisted stocks
        cur.execute("""
            SELECT DISTINCT
                ss.ticker,
                ss.exchange,
                ss.direction,
                ss.confidence,
                ss.thesis
            FROM datapai.stock_synthesis ss
            INNER JOIN datapai.watchlist w ON w.symbol = ss.ticker AND w.exchange = ss.exchange
            WHERE ss.direction IS NOT NULL
        """)
        current_signals = {(r[0], r[1]): {
            "ticker": r[0], "exchange": r[1],
            "direction": r[2], "confidence": r[3], "thesis": r[4],
        } for r in cur.fetchall()}

        if not current_signals:
            return []

        # Get most recent alert per ticker to detect changes
        cur.execute("""
            SELECT DISTINCT ON (ticker, exchange)
                ticker, exchange, message_type,
                -- Extract old direction from the log
                -- We store direction in message_type as 'signal_alert:BUY' etc.
                CASE
                    WHEN message_type LIKE 'signal_alert:%'
                    THEN split_part(message_type, ':', 2)
                    ELSE NULL
                END AS last_direction
            FROM datapai.notification_log
            WHERE message_type LIKE 'signal_alert%'
            ORDER BY ticker, exchange, sent_at DESC
        """)
        last_signals = {(r[0], r[1]): r[3] for r in cur.fetchall()}

    changes = []
    for (ticker, exchange), sig in current_signals.items():
        old_dir = last_signals.get((ticker, exchange))
        new_dir = sig["direction"]
        # Signal changed (or first time seeing this ticker)
        if old_dir is not None and old_dir != new_dir:
            changes.append({
                **sig,
                "old_direction": old_dir,
                "new_direction": new_dir,
            })

    return changes


def _count_sent_today(conn, user_id: str) -> int:
    """Count alerts sent today for a user on telegram channel."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM datapai.notification_log "
            "WHERE user_id = %s AND channel = 'telegram' "
            "AND sent_at >= CURRENT_DATE AND status = 'sent'",
            (user_id,),
        )
        return cur.fetchone()[0]


def _log_notification(conn, user_id: str, channel: str, ticker: str, exchange: str,
                      message_type: str, status: str, error_detail: str = None):
    """Write to notification_log."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO datapai.notification_log "
            "(user_id, channel, ticker, exchange, message_type, status, error_detail) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (user_id, channel, ticker, exchange, message_type, status, error_detail),
        )
    conn.commit()


def _send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    """Send a Telegram message via HTTP API. Returns True on success."""
    import urllib.request
    import urllib.parse
    import json

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }).encode()

    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except Exception as e:
        logger.error("Telegram send failed for chat_id %s: %s", chat_id, e)
        return False


def main():
    from scripts.lib.db_helpers import get_conn

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set — skipping Telegram alerts")
        return

    with get_conn() as conn:
        # 1. Find signal changes
        changes = _get_signal_changes(conn)
        if not changes:
            logger.info("No signal changes detected — nothing to send")
            return

        logger.info("Detected %d signal changes", len(changes))

        # 2. Get all telegram-enabled users
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, telegram_chat_id, alert_signal, max_daily, lang "
                "FROM datapai.usr_notification_prefs "
                "WHERE channel = 'telegram' AND enabled = TRUE "
                "AND telegram_chat_id IS NOT NULL AND alert_signal = TRUE"
            )
            users = cur.fetchall()

        if not users:
            logger.info("No users with telegram alerts enabled")
            return

        logger.info("Processing alerts for %d users", len(users))

        sent_count = 0
        throttled_count = 0

        for user_id, chat_id, alert_signal, max_daily, lang in users:
            lang = lang or "en"

            # Check daily limit
            sent_today = _count_sent_today(conn, user_id)
            if sent_today >= max_daily:
                logger.debug("User %s throttled (%d/%d)", user_id, sent_today, max_daily)
                continue

            # Get user's watchlist
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT symbol, exchange FROM datapai.watchlist WHERE user_id = %s",
                    (user_id,),
                )
                watchlist = {(r[0], r[1]) for r in cur.fetchall()}

            remaining = max_daily - sent_today

            for change in changes:
                if remaining <= 0:
                    throttled_count += 1
                    break

                ticker = change["ticker"]
                exchange = change["exchange"]

                if (ticker, exchange) not in watchlist:
                    continue

                # Build message
                title = _get_label(conn, lang, "notif.signal_alert_title")
                changed_tpl = _get_label(conn, lang, "notif.signal_changed")
                conf_label = _get_label(conn, lang, "notif.confidence")

                old_dir = change["old_direction"]
                new_dir = change["new_direction"]
                confidence = change.get("confidence")

                msg_lines = [
                    f"{title}",
                    f"",
                    f"*{ticker}* ({exchange})",
                    changed_tpl.format(old=old_dir, new=new_dir),
                ]
                if confidence is not None:
                    msg_lines.append(f"{conf_label}: {confidence:.0%}")
                if change.get("thesis"):
                    # Truncate thesis to avoid overly long messages
                    thesis = change["thesis"][:200]
                    if len(change["thesis"]) > 200:
                        thesis += "..."
                    msg_lines.append(f"\n_{thesis}_")

                text = "\n".join(msg_lines)

                success = _send_telegram_message(bot_token, chat_id, text)
                msg_type = f"signal_alert:{new_dir}"

                if success:
                    _log_notification(conn, user_id, "telegram", ticker, exchange,
                                      msg_type, "sent")
                    sent_count += 1
                    remaining -= 1
                else:
                    _log_notification(conn, user_id, "telegram", ticker, exchange,
                                      msg_type, "failed", "Telegram API error")

        logger.info(
            "Alert run complete: %d sent, %d throttled, %d signal changes, %d eligible users",
            sent_count, throttled_count, len(changes), len(users),
        )


if __name__ == "__main__":
    main()
