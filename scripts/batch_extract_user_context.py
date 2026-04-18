#!/usr/bin/env python3
"""
batch_extract_user_context.py — Nightly LLM-based user context extraction
═══════════════════════════════════════════════════════════════════════════

Scans today's chat messages and extracts user preferences/context using LLM.
Runs as an Airflow nightly task (after market close).

Key optimization: concatenates ALL of a user's daily messages into 1 LLM call.
  - 15K active users × 4 msgs each = 60K messages
  - Without concat: 60K LLM calls (~5 hours, ~$68/mo)
  - With concat:    15K LLM calls (~25 min, ~$17/mo)
  - With self-ref filter: ~5K LLM calls (~8 min, ~$6/mo)

Usage:
    python scripts/batch_extract_user_context.py
    python scripts/batch_extract_user_context.py --days 3  # backfill last 3 days
"""
import argparse
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("batch_user_context")


def get_conn():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DATAPAI_PG_HOST", os.getenv("PGHOST", "localhost")),
        port=int(os.getenv("DATAPAI_PG_PORT", os.getenv("PGPORT", "5432"))),
        dbname=os.getenv("DATAPAI_PG_DB", os.getenv("PGDATABASE", "postgres")),
        user=os.getenv("DATAPAI_PG_USER", os.getenv("PGUSER", "postgres")),
        password=os.getenv("DATAPAI_PG_PASSWORD", os.getenv("PGPASSWORD", "postgres")),
    )


def get_messages_grouped_by_user(conn, since_date) -> dict[str, list[str]]:
    """
    Get user messages grouped by user_id.
    Only includes: paid users + new users (< 7 days old).
    Free long-term users already have keyword-extracted context — skip LLM.

    Returns {user_id: [msg1, msg2, ...]} — already filtered and ordered.
    """
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT cs.user_id::text, cm.content
            FROM datapai.chat_messages cm
            JOIN datapai.chat_sessions cs ON cs.id = cm.session_id
            WHERE cm.role = 'user'
              AND cm.created_at >= %s
              AND cs.user_id != 0
              AND LENGTH(cm.content) >= 15
              AND (
                -- Paid users: always extract (worth the cost)
                EXISTS (
                    SELECT 1 FROM datapai.users u
                    WHERE u.id::text = cs.user_id::text
                      AND u.plan NOT IN ('watch', '')
                      AND u.plan IS NOT NULL
                )
                OR
                -- New users (< 7 days): still learning about them
                EXISTS (
                    SELECT 1 FROM datapai.users u
                    WHERE u.id::text = cs.user_id::text
                      AND u.created_at > NOW() - INTERVAL '7 days'
                )
              )
            ORDER BY cm.created_at
        """, (since_date,))
        rows = cur.fetchall()

    by_user: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        by_user[r["user_id"]].append(r["content"])
    return dict(by_user)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=1, help="Process messages from last N days")
    args = parser.parse_args()

    since = date.today() - timedelta(days=args.days)
    log.info("Extracting user context from messages since %s", since)

    conn = get_conn()
    by_user = get_messages_grouped_by_user(conn, since)
    conn.close()

    total_messages = sum(len(msgs) for msgs in by_user.values())
    if not by_user:
        log.info("No messages to process")
        return

    log.info("Found %d messages across %d users", total_messages, len(by_user))

    from agents.stock_chat.user_context import extract_user_context_batch

    total_extracted = 0
    total_calls = 0
    skipped = 0
    start = time.time()

    for i, (user_id, messages) in enumerate(by_user.items()):
        if i > 0 and i % 100 == 0:
            elapsed = time.time() - start
            log.info("  Progress: %d/%d users, %d extracted, %d LLM calls, %.0fs elapsed",
                     i, len(by_user), total_extracted, total_calls, elapsed)

        # Single LLM call with all messages concatenated
        n = extract_user_context_batch(user_id, messages)
        if n > 0:
            total_extracted += n
            total_calls += 1
            log.info("  User %s: %d items from %d messages", user_id[:8], n, len(messages))
        elif n == 0:
            # Check if it was skipped (no self-ref) or just no new context
            total_calls += 1  # still made the call unless filtered
        skipped += (1 if n == 0 else 0)

    elapsed = time.time() - start
    log.info("═══ DONE ═══")
    log.info("  Users: %d processed, %d had new context", len(by_user), len(by_user) - skipped)
    log.info("  Messages: %d total (1 LLM call per user, not per message)", total_messages)
    log.info("  Extracted: %d context items", total_extracted)
    log.info("  Time: %.0fs (%.1f users/sec)", elapsed, len(by_user) / elapsed if elapsed > 0 else 0)


if __name__ == "__main__":
    main()
