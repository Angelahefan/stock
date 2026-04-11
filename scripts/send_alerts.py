#!/usr/bin/env python3
"""
scripts/send_alerts.py
─────────────────────────────────────────────────────────────────────────────
Check for signal changes (BUY/SELL flips) on watchlist stocks and fan out
alerts to subscribed users via multiple channels:

  1. Telegram  — DM via @datapai_stock_bot (wired 2026-04-11, Phase 4A)
  2. Expo Push — mobile app notifications (wired 2026-04-11, Phase 4A)
  3. Email     — existing SMTP channel (optional fallback, not yet in this script)

Runs via Airflow every 30 min during market hours.

Logic:
  1. Find stocks where overall_signal changed (stock_synthesis.direction)
     by comparing current vs previous notification_log entries.
  2. For each CHANNEL:
     - Telegram: query usr_notification_prefs WHERE channel='telegram' AND enabled.
                 Fetch each user's watchlist, match against changed signals,
                 honor max_daily, send via Telegram Bot API, log to notification_log.
     - Push:     query user_devices JOIN watchlist for active devices grouped by user.
                 Honor a default max_daily=5, send batched to Expo Push Service
                 (one POST per user with all their device tokens), log to notification_log.
  3. Each channel has its own max_daily budget (independent). A user with both
     telegram and push enabled gets alerts on both — each counted separately.

Env:
  TELEGRAM_BOT_TOKEN — required for Telegram alerts (skipped if unset)
  EXPO_ACCESS_TOKEN  — optional, only for self-hosted Expo Push or paid rate limits.
                      Not needed for the default public Expo Push Service.
"""
from __future__ import annotations  # Py3.8 compat for `list[dict]` etc.
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


# ─────────────────────────────────────────────────────────────────────────
# framework_db direct writer — bypasses the stock_db FDW for write paths
# that hit user-facing tables (notification_log, user_devices).
#
# Why: postgres_fdw parameterizes everything, so it can't forward DEFAULT
# keywords or honor remote-side column defaults for columns the local FDW
# alias didn't specifically opt out of. The upshot: any INSERT via the FDW
# that doesn't provide every column ends up sending NULL for the missing
# ones, bypassing remote DEFAULT gen_random_uuid() / nextval(...) / NOW().
#
# Fix: when we need to WRITE to a user-facing table, open a direct
# connection to framework_db (port 5433). READS continue through the stock_db
# FDW because they're fast and don't hit this gotcha.
# ─────────────────────────────────────────────────────────────────────────
import psycopg2 as _psycopg2

_framework_conn = None

def _get_framework_conn():
    """Lazy direct connection to framework_db (datapai_auth_db on port 5433).
    Reuses a single connection for the duration of the process."""
    global _framework_conn
    if _framework_conn is None or _framework_conn.closed:
        _framework_conn = _psycopg2.connect(
            host=os.getenv("AUTH_DB_HOST", "localhost"),
            port=int(os.getenv("AUTH_DB_PORT", "5433")),
            dbname=os.getenv("AUTH_DB_NAME", "datapai_auth_db"),
            user=os.getenv("AUTH_DB_USER", "auth_service"),
            password=os.getenv("AUTH_DB_PASSWORD", ""),
        )
        _framework_conn.autocommit = True
    return _framework_conn


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


def _count_sent_today(conn, user_id: str, channel: str = "telegram") -> int:
    """Count alerts sent today for a user on a specific channel.

    Phase 4A (2026-04-11): parameterized to support independent daily budgets
    per channel. Push users have their own max_daily (default 5) separate from
    telegram users (default 3).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM datapai.notification_log "
            "WHERE user_id = %s AND channel = %s "
            "AND sent_at >= CURRENT_DATE AND status = 'sent'",
            (user_id, channel),
        )
        return cur.fetchone()[0]


def _log_notification(conn, user_id: str, channel: str, ticker: str, exchange: str,
                      message_type: str, status: str, error_detail: str = None):
    """Write to datapai.notification_log — via a DIRECT framework_db connection,
    bypassing the stock_db FDW alias.

    The `conn` parameter is kept for backward compatibility with the call sites
    (which pass the stock_db pool conn) but this function now opens its own
    framework_db connection via _get_framework_conn() and writes directly. The
    stock_db FDW alias to notification_log cannot be written through because
    postgres_fdw always sends the full column list, bypassing remote DEFAULT
    clauses (see module-level comment on _get_framework_conn).
    """
    fw = _get_framework_conn()
    with fw.cursor() as cur:
        cur.execute(
            "INSERT INTO datapai.notification_log "
            "(user_id, channel, ticker, exchange, message_type, status, error_detail) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (user_id, channel, ticker, exchange, message_type, status, error_detail),
        )


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


# ─────────────────────────────────────────────────────────────────────────
# Phase 4A — Expo Push Notifications
# ─────────────────────────────────────────────────────────────────────────

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def _get_push_users_and_devices(conn) -> list[dict]:
    """
    Return users with at least one active push device, plus their devices.

    Each element is a dict:
      {
        "user_id": "...",             # matches datapai.users.id AND datapai.user_devices.user_id
        "plan":    "watch",           # from datapai.users.plan, fallback 'watch'
        "devices": [
          {"id": uuid, "token": "ExponentPushToken[...]", "platform": "ios", "device_name": "..."},
          ...
        ],
        "lang": "en",                 # from datapai.users.preferred_lang, fallback 'en'
      }

    NOTE: this deliberately does NOT query usr_notification_prefs. In the Phase 4A
    design, the opt-in signal for push is simply "user has an active row in
    user_devices with a non-null expo_push_token". The mobile app registering a
    device IS the opt-in — because the OS already required the user to grant
    notification permission to get a token in the first place.

    The user's plan is joined in so the caller can apply plan-specific daily
    budgets (Phase 4B enhancement — replaces the old hardcoded 5/day).
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                d.user_id,
                d.id::text,
                d.expo_push_token,
                d.platform,
                d.device_name,
                COALESCE(u.preferred_lang, 'en') AS lang,
                COALESCE(u.plan, 'watch')       AS plan
            FROM datapai.user_devices d
            LEFT JOIN datapai.users u ON u.id = d.user_id
            WHERE d.disabled_at IS NULL
              AND d.expo_push_token IS NOT NULL
              AND d.expo_push_token <> ''
            ORDER BY d.user_id, d.last_seen_at DESC
        """)
        rows = cur.fetchall()

    users_map: dict[str, dict] = {}
    for user_id, device_id, token, platform, device_name, lang, plan in rows:
        if user_id not in users_map:
            users_map[user_id] = {
                "user_id": user_id,
                "plan": plan,
                "devices": [],
                "lang": lang,
            }
        users_map[user_id]["devices"].append({
            "id": device_id,
            "token": token,
            "platform": platform,
            "device_name": device_name,
        })
    return list(users_map.values())


def _load_push_daily_limits(conn) -> dict[str, int]:
    """
    Load plan-specific push notification daily limits from sys_common_config.

    Table: datapai.sys_common_config, config_type='push_limits'
    Keys:  '{plan_id}_daily_limit' (e.g. 'watch_daily_limit') + 'default_daily_limit'

    Returns a dict like:
      {
        "watch":        5,
        "individual":   20,
        "professional": 50,
        "business":     100,
        "_default":     5,  # fallback for unknown plans
      }

    Called once per send_alerts.py invocation. If the config table is
    unreachable or empty, falls back to a conservative {_default: 5}.
    """
    limits: dict[str, int] = {}
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT config_key, config_value
                FROM datapai.sys_common_config
                WHERE config_type = 'push_limits'
                  AND (effective_from IS NULL OR effective_from <= CURRENT_DATE)
                  AND (effective_to   IS NULL OR effective_to   >  CURRENT_DATE)
            """)
            for key, value in cur.fetchall():
                # 'watch_daily_limit' -> plan_id 'watch'
                # 'default_daily_limit' -> sentinel '_default'
                if key == "default_daily_limit":
                    plan_id = "_default"
                elif key.endswith("_daily_limit"):
                    plan_id = key[: -len("_daily_limit")]
                else:
                    continue
                try:
                    limits[plan_id] = int(value)
                except (TypeError, ValueError):
                    logger.warning("push_limits.%s has non-int value %r, skipping", key, value)
    except Exception as e:
        logger.warning("failed to load push_limits config, using defaults: %s", e)

    # Safety net — always have a sane _default even if config is empty
    if "_default" not in limits:
        limits["_default"] = 5
    return limits


def _send_expo_push(
    tokens: list[str],
    title: str,
    body: str,
    data: dict | None = None,
    sound: str = "default",
) -> tuple[bool, str]:
    """
    Send a single push message to one or more Expo push tokens (all for the
    same user — batched per request to minimize API round-trips).

    Returns (ok: bool, error_detail: str).

    Expo's HTTP API accepts either a single message object OR an array of
    objects. We POST an array so multiple tokens for the same user go in one
    request. Response is always an array of "tickets" (one per token).

    We consider the call a success if EVERY ticket is status='ok'. If any
    ticket is status='error', we log the first error detail.

    Expo token format: "ExponentPushToken[xxxxxxxxxxxxxx]"
    """
    import urllib.request
    import urllib.error
    import json

    if not tokens:
        return False, "no tokens"

    messages = [
        {
            "to": t,
            "title": title,
            "body": body,
            "data": data or {},
            "sound": sound,
            "priority": "high",
            "channelId": "signal-alerts",  # Android notification channel
        }
        for t in tokens
    ]

    payload = json.dumps(messages).encode()
    req = urllib.request.Request(
        EXPO_PUSH_URL,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode() if e.fp else ""
        logger.error("Expo push HTTP %d for %d tokens: %s", e.code, len(tokens), body_txt[:300])
        return False, f"HTTP {e.code}: {body_txt[:200]}"
    except Exception as e:
        logger.error("Expo push failed for %d tokens: %s", len(tokens), e)
        return False, f"network error: {e}"

    # Expo wraps all tickets in a top-level "data" key.
    # When a SINGLE message is posted as an object, data is a single ticket.
    # When an ARRAY is posted, data is an array of tickets.
    tickets = result.get("data", [])
    if isinstance(tickets, dict):
        tickets = [tickets]

    if not tickets:
        return False, f"no tickets returned: {result}"

    any_error = False
    first_error = ""
    for ticket in tickets:
        if ticket.get("status") != "ok":
            any_error = True
            if not first_error:
                first_error = ticket.get("message") or ticket.get("details", {}).get("error") or "unknown"

    if any_error:
        return False, first_error
    return True, ""


def _disable_invalid_push_token(conn, token: str, reason: str) -> None:
    """When Expo tells us a token is invalid (DeviceNotRegistered, etc.),
    soft-delete it so we stop trying to send to it.

    Uses a direct framework_db connection (same reason as _log_notification —
    user_devices is a foreign table on stock_db and the remote-default issue
    affects UPDATEs on disabled_at too if we tried to set NULL somewhere).
    """
    fw = _get_framework_conn()
    with fw.cursor() as cur:
        cur.execute(
            "UPDATE datapai.user_devices SET disabled_at = NOW() "
            "WHERE expo_push_token = %s AND disabled_at IS NULL",
            (token,),
        )
    logger.info("Disabled invalid expo push token (%s): %s", reason, token[:30] + "...")


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

        # ─────────────────────────────────────────────────────────────────
        # Phase 4A — Expo Push loop
        # Parallel structure to the Telegram loop above. Uses the same
        # signal-change list. Opt-in is implicit: if a user has an active
        # user_devices row, they're opted in (OS permission was granted).
        #
        # Phase 4B enhancement: daily budget is plan-driven. Free (watch)
        # users get 5/day, paying tiers get more. Loaded once from
        # datapai.sys_common_config (config_type='push_limits').
        # ─────────────────────────────────────────────────────────────────
        push_limits = _load_push_daily_limits(conn)
        logger.info("Push daily limits by plan: %s", push_limits)

        push_users = _get_push_users_and_devices(conn)
        push_sent_count = 0
        push_throttled_count = 0
        push_user_count = len(push_users)

        if push_users:
            logger.info("Processing push alerts for %d users", push_user_count)

        for pu in push_users:
            user_id = pu["user_id"]
            devices = pu["devices"]
            lang = pu["lang"] or "en"
            plan = pu.get("plan") or "watch"
            tokens = [d["token"] for d in devices]

            # Plan-specific daily budget — fallback chain:
            # user's plan → _default in config → hardcoded 5
            user_max_daily = push_limits.get(plan, push_limits.get("_default", 5))

            # Daily budget check — push has its own bucket per user
            sent_today = _count_sent_today(conn, user_id, channel="push")
            if sent_today >= user_max_daily:
                logger.debug("Push user %s (plan=%s) throttled (%d/%d)",
                             user_id, plan, sent_today, user_max_daily)
                continue

            # Get user's watchlist (same query as telegram loop)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT symbol, exchange FROM datapai.watchlist WHERE user_id = %s",
                    (user_id,),
                )
                watchlist = {(r[0], r[1]) for r in cur.fetchall()}

            if not watchlist:
                continue

            remaining = user_max_daily - sent_today

            for change in changes:
                if remaining <= 0:
                    push_throttled_count += 1
                    break

                ticker = change["ticker"]
                exchange = change["exchange"]

                if (ticker, exchange) not in watchlist:
                    continue

                # Build push payload. Short and scannable — push notifications
                # show on lock screen so <120 chars for title+body is ideal.
                old_dir = change["old_direction"]
                new_dir = change["new_direction"]
                confidence = change.get("confidence")

                title = f"{ticker} {new_dir}"  # e.g. "BHP.AX BUY"
                body_parts = [f"{old_dir} → {new_dir}"]
                if confidence is not None:
                    body_parts.append(f"{confidence:.0%} confidence")
                body = "  ·  ".join(body_parts)

                # Data payload — mobile app uses this to deep-link on tap.
                data_payload = {
                    "type": "signal_alert",
                    "ticker": ticker,
                    "exchange": exchange,
                    "direction": new_dir,
                    "confidence": confidence,
                    "deep_link": f"/ticker/{ticker}?exchange={exchange}",
                }

                success, error_detail = _send_expo_push(
                    tokens=tokens,
                    title=title,
                    body=body,
                    data=data_payload,
                )
                msg_type = f"signal_alert:{new_dir}"

                if success:
                    _log_notification(conn, user_id, "push", ticker, exchange,
                                      msg_type, "sent")
                    push_sent_count += 1
                    remaining -= 1
                else:
                    _log_notification(conn, user_id, "push", ticker, exchange,
                                      msg_type, "failed", error_detail[:400])
                    # If Expo says the token is invalid, disable it so we stop
                    # hammering the same dead token.
                    if "DeviceNotRegistered" in error_detail or "InvalidCredentials" in error_detail:
                        for t in tokens:
                            _disable_invalid_push_token(conn, t, error_detail[:50])

        logger.info(
            "Telegram run: %d sent, %d throttled, %d signal changes, %d eligible users",
            sent_count, throttled_count, len(changes), len(users),
        )
        logger.info(
            "Push run:     %d sent, %d throttled, %d signal changes, %d eligible users",
            push_sent_count, push_throttled_count, len(changes), push_user_count,
        )


if __name__ == "__main__":
    main()
