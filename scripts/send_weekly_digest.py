#!/usr/bin/env python3
"""
scripts/send_weekly_digest.py
─────────────────────────────────────────────────────────────────────────────
Send weekly portfolio digest emails via AWS SES.

For each user with digest_weekly=true AND email channel enabled:
  - Query their watchlist stocks
  - Pull latest price, weekly change%, AI signal, key support/resistance
  - Build HTML email with i18n
  - Send via SES

Env:
  AWS_REGION             — SES region (default: ap-southeast-1)
  AWS_ACCESS_KEY_ID      — (or use IAM role)
  AWS_SECRET_ACCESS_KEY  — (or use IAM role)
  DATAPAI_SES_FROM_EMAIL — sender email (must be SES-verified)
  DATAPAI_APP_URL        — base URL for unsubscribe links (default: https://datap.ai)
"""
import sys
import os
import logging
from pathlib import Path

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
logger = logging.getLogger("weekly_digest")


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


def _get_watchlist_digest(conn, user_id: str) -> list[dict]:
    """
    Get watchlist stocks with latest price, weekly change, and AI signal.
    Returns list of dicts.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                w.symbol,
                w.exchange,
                COALESCE(w.name, sd.name_en, w.symbol) AS stock_name,
                ti.close AS price,
                ti.change_pct AS daily_change,
                ss.direction AS signal,
                ss.confidence,
                ti.ema_20 AS key_level
            FROM datapai.watchlist w
            LEFT JOIN datapai.stock_directory sd
                ON sd.ticker = w.symbol AND sd.exchange = w.exchange
            LEFT JOIN LATERAL (
                SELECT close, change_pct, ema_20
                FROM datapai.ta_indicators
                WHERE ticker = w.symbol AND exchange = w.exchange
                    AND timeframe = 'daily'
                ORDER BY trade_date DESC
                LIMIT 1
            ) ti ON TRUE
            LEFT JOIN datapai.stock_synthesis ss
                ON ss.ticker = w.symbol AND ss.exchange = w.exchange
            WHERE w.user_id = %s
            ORDER BY w.symbol
        """, (user_id,))

        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _get_weekly_change(conn, ticker: str, exchange: str) -> float | None:
    """Calculate weekly price change percentage."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT close
            FROM datapai.ta_indicators
            WHERE ticker = %s AND exchange = %s AND timeframe = 'daily'
            ORDER BY trade_date DESC
            LIMIT 6
        """, (ticker, exchange))
        rows = cur.fetchall()
        if len(rows) >= 2:
            latest = rows[0][0]
            oldest = rows[-1][0]
            if oldest and oldest > 0:
                return ((latest - oldest) / oldest) * 100
    return None


def _build_html_email(conn, lang: str, stocks: list[dict], user_id: str,
                      weekly_changes: dict) -> str:
    """Build HTML email body with i18n labels."""
    app_url = os.getenv("DATAPAI_APP_URL", "https://datap.ai")

    subject_label = _get_label(conn, lang, "notif.weekly_digest_subject")
    stock_label = _get_label(conn, lang, "notif.digest_stock")
    price_label = _get_label(conn, lang, "notif.digest_price")
    change_label = _get_label(conn, lang, "notif.digest_change")
    signal_label = _get_label(conn, lang, "notif.digest_signal")
    unsub_label = _get_label(conn, lang, "notif.unsubscribe")

    rows_html = ""
    for s in stocks:
        ticker = s["symbol"]
        exchange = s["exchange"]
        name = s["stock_name"] or ticker
        price = s.get("price")
        signal = s.get("signal") or "—"
        key_level = s.get("key_level")

        weekly_chg = weekly_changes.get((ticker, exchange))
        chg_str = f"{weekly_chg:+.1f}%" if weekly_chg is not None else "—"
        chg_color = "#22c55e" if (weekly_chg or 0) >= 0 else "#ef4444"

        price_str = f"${price:,.2f}" if price else "—"
        key_str = f"${key_level:,.2f}" if key_level else "—"

        signal_color = "#22c55e" if signal == "BUY" else "#ef4444" if signal == "SELL" else "#6b7280"

        rows_html += f"""
        <tr>
            <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">
                <strong>{ticker}</strong><br>
                <span style="color:#6b7280;font-size:12px;">{name} ({exchange})</span>
            </td>
            <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;">
                {price_str}
            </td>
            <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;color:{chg_color};">
                {chg_str}
            </td>
            <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:center;">
                <span style="color:{signal_color};font-weight:bold;">{signal}</span>
            </td>
            <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;">
                {key_str}
            </td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:640px;margin:0 auto;padding:20px;color:#1f2937;">
    <div style="text-align:center;padding:20px 0;">
        <h1 style="color:#1e40af;margin:0;font-size:24px;">{subject_label}</h1>
    </div>

    <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <thead>
            <tr style="background:#f3f4f6;">
                <th style="padding:10px 12px;text-align:left;">{stock_label}</th>
                <th style="padding:10px 12px;text-align:right;">{price_label}</th>
                <th style="padding:10px 12px;text-align:right;">{change_label}</th>
                <th style="padding:10px 12px;text-align:center;">{signal_label}</th>
                <th style="padding:10px 12px;text-align:right;">EMA20</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>

    {f'<p style="color:#6b7280;font-size:12px;text-align:center;margin-top:8px;">{len(stocks)} stocks in watchlist</p>' if stocks else '<p style="text-align:center;color:#6b7280;">No stocks in watchlist</p>'}

    <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;">

    <p style="color:#9ca3af;font-size:11px;text-align:center;">
        This is an automated digest from DataPAI. AI signals are for informational purposes only
        and do not constitute financial advice.<br>
        <a href="{app_url}/settings/notifications?action=unsubscribe&uid={user_id}"
           style="color:#6b7280;">{unsub_label}</a>
    </p>
</body>
</html>"""

    return html


def _send_ses_email(to_email: str, subject: str, html_body: str, from_email: str) -> bool:
    """Send email via AWS SES. Returns True on success."""
    import boto3
    from botocore.exceptions import ClientError

    region = os.getenv("AWS_REGION", "ap-southeast-1")

    try:
        client = boto3.client("ses", region_name=region)
        resp = client.send_email(
            Source=from_email,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html_body, "Charset": "UTF-8"}},
            },
        )
        logger.debug("SES sent to %s: MessageId=%s", to_email, resp["MessageId"])
        return True
    except ClientError as e:
        logger.error("SES error for %s: %s", to_email, e.response["Error"]["Message"])
        return False
    except Exception as e:
        logger.error("SES unexpected error for %s: %s", to_email, e)
        return False


def _log_notification(conn, user_id: str, channel: str, message_type: str,
                      status: str, error_detail: str = None):
    """Write to notification_log."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO datapai.notification_log "
            "(user_id, channel, ticker, exchange, message_type, status, error_detail) "
            "VALUES (%s, %s, NULL, NULL, %s, %s, %s)",
            (user_id, channel, message_type, status, error_detail),
        )
    conn.commit()


def main():
    from scripts.lib.db_helpers import get_conn

    from_email = os.getenv("DATAPAI_SES_FROM_EMAIL")
    if not from_email:
        logger.warning("DATAPAI_SES_FROM_EMAIL not set — skipping weekly digest")
        return

    with get_conn() as conn:
        # Get all users with email digest enabled
        with conn.cursor() as cur:
            cur.execute("""
                SELECT np.user_id, u.email, np.lang
                FROM datapai.usr_notification_prefs np
                INNER JOIN datapai.users u ON u.id = np.user_id
                WHERE np.channel = 'email'
                    AND np.enabled = TRUE
                    AND np.digest_weekly = TRUE
                    AND u.email IS NOT NULL
            """)
            users = cur.fetchall()

        if not users:
            logger.info("No users with email digest enabled")
            return

        logger.info("Sending weekly digest to %d users", len(users))
        sent = 0
        failed = 0

        for user_id, email, lang in users:
            lang = lang or "en"

            try:
                # Get watchlist data
                stocks = _get_watchlist_digest(conn, user_id)
                if not stocks:
                    logger.debug("User %s has empty watchlist, skipping", user_id)
                    continue

                # Calculate weekly changes
                weekly_changes = {}
                for s in stocks:
                    chg = _get_weekly_change(conn, s["symbol"], s["exchange"])
                    weekly_changes[(s["symbol"], s["exchange"])] = chg

                # Build email
                subject = _get_label(conn, lang, "notif.weekly_digest_subject")
                html = _build_html_email(conn, lang, stocks, user_id, weekly_changes)

                # Send
                success = _send_ses_email(email, subject, html, from_email)

                if success:
                    _log_notification(conn, user_id, "email", "weekly_digest", "sent")
                    sent += 1
                else:
                    _log_notification(conn, user_id, "email", "weekly_digest", "failed",
                                      "SES send error")
                    failed += 1

            except Exception as e:
                logger.error("Error processing digest for user %s: %s", user_id, e)
                _log_notification(conn, user_id, "email", "weekly_digest", "failed", str(e))
                failed += 1

        logger.info("Weekly digest complete: %d sent, %d failed out of %d eligible",
                     sent, failed, len(users))


if __name__ == "__main__":
    main()
