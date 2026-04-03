#!/usr/bin/env python3
"""
compute_priority_tickers.py — Build the smart priority list for fundamental analysis.

Scans screener_metrics + watchlist to find stocks that MATTER:
  P1: Watchlist (always — user cares about these)
  P2: Oversold bounce candidates (RSI ≤ 30, good volume, not penny)
  P3: Momentum leaders (top gainers with volume confirmation)
  P4: Deep value (50%+ off 52w high, still liquid)
  P5: Breakout (MACD bullish + volume surge)

Target: ~200-300 tickers. Runs daily before compute_fundamental_lite.
Expired entries auto-cleaned. Watchlist entries never expire.

Usage:
    python scripts/compute_priority_tickers.py --exchange US
    python scripts/compute_priority_tickers.py --exchange ASX
    python scripts/compute_priority_tickers.py --exchange ALL
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import List, Tuple

import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def get_conn():
    return psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "postgres"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", ""),
    )


# ── Priority bucket queries ──────────────────────────────────────────────────
# Each returns: (ticker, exchange, priority, reason, source, expires_interval)

BUCKET_QUERIES = {
    "watchlist": {
        "priority": 1,
        "source": "watchlist",
        "expires": None,  # never expires
        "sql": """
            SELECT DISTINCT w.symbol AS ticker, w.exchange
            FROM datapai.watchlist w
            JOIN datapai.screener_metrics s ON s.ticker = w.symbol AND s.exchange = w.exchange
            WHERE w.exchange = %(exchange)s
              AND s.latest_close IS NOT NULL
        """,
        "reason": "User watchlist",
    },

    "oversold_bounce": {
        "priority": 2,
        "source": "screener_oversold",
        "expires": "7 days",
        "sql": """
            SELECT ticker, exchange FROM datapai.screener_metrics
            WHERE exchange = %(exchange)s
              AND rsi_14 <= 30
              AND avg_volume_20d >= 50000
              AND latest_close >= CASE WHEN %(exchange)s = 'ASX' THEN 0.50 ELSE 5.0 END
              AND trade_date::date >= CURRENT_DATE - INTERVAL '5 days'
            ORDER BY rsi_14 ASC
            LIMIT 100
        """,
        "reason": "RSI oversold bounce candidate",
    },

    "momentum_leaders": {
        "priority": 3,
        "source": "screener_momentum",
        "expires": "7 days",
        "sql": """
            SELECT ticker, exchange FROM datapai.screener_metrics
            WHERE exchange = %(exchange)s
              AND change_1m_pct >= 15
              AND avg_volume_20d >= 50000
              AND latest_close >= CASE WHEN %(exchange)s = 'ASX' THEN 0.50 ELSE 5.0 END
              AND volume_ratio >= 0.8
              AND trade_date::date >= CURRENT_DATE - INTERVAL '5 days'
            ORDER BY change_1m_pct DESC
            LIMIT 80
        """,
        "reason": "Strong 1M momentum with volume",
    },

    "deep_value": {
        "priority": 4,
        "source": "screener_deep_value",
        "expires": "14 days",
        "sql": """
            SELECT ticker, exchange FROM datapai.screener_metrics
            WHERE exchange = %(exchange)s
              AND pct_from_52w_high <= -40
              AND avg_volume_20d >= 30000
              AND latest_close >= CASE WHEN %(exchange)s = 'ASX' THEN 0.50 ELSE 3.0 END
              AND trade_date::date >= CURRENT_DATE - INTERVAL '5 days'
            ORDER BY pct_from_52w_high ASC
            LIMIT 80
        """,
        "reason": "40%+ off 52-week high, still liquid",
    },

    "breakout": {
        "priority": 5,
        "source": "screener_breakout",
        "expires": "5 days",
        "sql": """
            SELECT ticker, exchange FROM datapai.screener_metrics
            WHERE exchange = %(exchange)s
              AND macd_trend = 'BULLISH'
              AND volume_ratio >= 2.0
              AND avg_volume_20d >= 30000
              AND latest_close >= CASE WHEN %(exchange)s = 'ASX' THEN 0.50 ELSE 5.0 END
              AND trade_date::date >= CURRENT_DATE - INTERVAL '5 days'
            ORDER BY volume_ratio DESC
            LIMIT 60
        """,
        "reason": "MACD bullish + 2x volume surge",
    },

    "golden_cross_quality": {
        "priority": 5,
        "source": "screener_golden_cross",
        "expires": "14 days",
        "sql": """
            SELECT ticker, exchange FROM datapai.screener_metrics
            WHERE exchange = %(exchange)s
              AND golden_cross = true
              AND rsi_14 BETWEEN 40 AND 65
              AND avg_volume_20d >= 50000
              AND latest_close >= CASE WHEN %(exchange)s = 'ASX' THEN 1.0 ELSE 10.0 END
              AND trade_date::date >= CURRENT_DATE - INTERVAL '5 days'
            ORDER BY avg_volume_20d DESC
            LIMIT 50
        """,
        "reason": "Golden cross + healthy RSI + liquid",
    },
}


UPSERT_SQL = """
INSERT INTO datapai.priority_tickers (ticker, exchange, priority, reason, source, expires_at)
VALUES (%(ticker)s, %(exchange)s, %(priority)s, %(reason)s, %(source)s,
        CASE WHEN %(expires)s IS NULL THEN NULL
             ELSE NOW() + %(expires)s::interval END)
ON CONFLICT (ticker, exchange, source)
DO UPDATE SET
    priority = EXCLUDED.priority,
    reason = EXCLUDED.reason,
    expires_at = EXCLUDED.expires_at,
    added_at = NOW()
"""


def run(exchange: str):
    conn = get_conn()
    t0 = time.time()

    # Step 1: Clean expired entries
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM datapai.priority_tickers
            WHERE exchange = %s AND expires_at IS NOT NULL AND expires_at < NOW()
        """, (exchange,))
        expired = cur.rowcount
        if expired:
            log.info("Cleaned %d expired entries for %s", expired, exchange)
    conn.commit()

    # Step 2: Run each bucket query and upsert
    total_added = 0
    for bucket_name, cfg in BUCKET_QUERIES.items():
        with conn.cursor() as cur:
            cur.execute(cfg["sql"], {"exchange": exchange})
            rows = cur.fetchall()

        count = 0
        for ticker, ex in rows:
            with conn.cursor() as cur:
                cur.execute(UPSERT_SQL, {
                    "ticker": ticker,
                    "exchange": ex,
                    "priority": cfg["priority"],
                    "reason": cfg["reason"],
                    "source": cfg["source"],
                    "expires": cfg["expires"],
                })
            count += 1
        conn.commit()

        log.info("  %-25s P%d: %d tickers", bucket_name, cfg["priority"], count)
        total_added += count

    # Step 3: Summary
    with conn.cursor() as cur:
        cur.execute("""
            SELECT priority, COUNT(DISTINCT (ticker, exchange)) as cnt
            FROM datapai.priority_tickers
            WHERE exchange = %s
            GROUP BY priority ORDER BY priority
        """, (exchange,))
        for p, cnt in cur.fetchall():
            log.info("  Priority %d: %d unique tickers", p, cnt)

        cur.execute("""
            SELECT COUNT(DISTINCT (ticker, exchange))
            FROM datapai.priority_tickers WHERE exchange = %s
        """, (exchange,))
        unique_total = cur.fetchone()[0]

    elapsed = time.time() - t0
    log.info("=== %s: %d unique priority tickers (from %d entries) in %.1fs ===",
             exchange, unique_total, total_added, elapsed)

    conn.close()
    return unique_total


def main():
    parser = argparse.ArgumentParser(description="Compute priority ticker list")
    parser.add_argument("--exchange", default="ALL", help="US, ASX, or ALL")
    args = parser.parse_args()

    exchanges = ["US", "ASX"] if args.exchange.upper() == "ALL" else [args.exchange.upper()]
    grand_total = 0
    for ex in exchanges:
        grand_total += run(ex)
    log.info("Grand total: %d priority tickers", grand_total)


if __name__ == "__main__":
    main()
