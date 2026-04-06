#!/usr/bin/env python3
"""
scripts/sync_intraday_to_daily.py
─────────────────────────────────────────────────────────────────────────────
End-of-day rollup: aggregate today's intraday bars into datapai.prices,
then clean up old intraday data for that market only (keep 3 days).

Pipeline role
─────────────
  During the day  : intraday_runner.py → ohlcv_intraday_{exchange} (5m bars)
  End of day      : THIS SCRIPT
     1. Aggregate intraday → O/H/L/C/V per ticker for today
     2. Upsert into datapai.prices
     3. Delete bars older than 3 days FOR THIS EXCHANGE ONLY

Why keep 3 days?
  - Markets operate in different timezones; wiping all data hurts others
  - Users should see latest intraday data off-hours (evenings, weekends)
  - 3 days covers Friday → Monday (weekend visibility)

Usage:
    python3 scripts/sync_intraday_to_daily.py --exchange US
    python3 scripts/sync_intraday_to_daily.py --exchange ASX
    python3 scripts/sync_intraday_to_daily.py --exchange US --date 2026-03-14
    python3 scripts/sync_intraday_to_daily.py --exchange US --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib.db_helpers import get_conn, upsert_daily_rows
from scripts.lib.log_setup import setup_logging

logger = setup_logging("sync_intraday_to_daily")


# ── SQL ───────────────────────────────────────────────────────────────────────

# Map exchange → per-market intraday table
_INTRADAY_TABLES = {
    "US": "ohlcv_intraday_us", "ASX": "ohlcv_intraday_asx",
    "HKEX": "ohlcv_intraday_hkex", "HOSE": "ohlcv_intraday_hose",
    "SET": "ohlcv_intraday_set", "KLSE": "ohlcv_intraday_klse",
    "IDX": "ohlcv_intraday_idx", "SSE": "ohlcv_intraday_sse",
    "SZSE": "ohlcv_intraday_szse", "LSE": "ohlcv_intraday_lse",
}

# Days of intraday data to keep (covers Friday → Monday)
_KEEP_DAYS = 3


def _intraday_table(exchange: str) -> str:
    tbl = _INTRADAY_TABLES.get(exchange.upper())
    if not tbl:
        raise ValueError(f"Unknown exchange for intraday: {exchange}")
    return f"datapai.{tbl}"


# Aggregate intraday bars into daily O/H/L/C/V.
_AGG_SQL_TPL = """
SELECT
    ticker,
    exchange,
    source,
    (ARRAY_AGG(open  ORDER BY ts ASC))[1]                    AS open,
    MAX(high)                                                 AS high,
    MIN(low)                                                  AS low,
    (ARRAY_AGG(close ORDER BY ts DESC))[1]                   AS close,
    SUM(volume)                                               AS volume
FROM {table}
WHERE ts::date = %(trade_date)s
GROUP BY ticker, exchange, source
HAVING COUNT(*) >= 2
"""

# Delete bars older than N days for this market only
_CLEANUP_SQL_TPL = "DELETE FROM {table} WHERE ts < NOW() - INTERVAL '%s days'"


# ── Core logic ────────────────────────────────────────────────────────────────

def rollup(exchange: str, trade_date: date, dry_run: bool = False) -> int:
    """
    Aggregate today's intraday bars for `exchange` into datapai.prices.
    Returns the number of tickers rolled up.
    """
    table = _intraday_table(exchange)
    logger.info("── EOD rollup  exchange=%s  table=%s  date=%s  dry_run=%s ──",
                exchange, table, trade_date, dry_run)

    agg_sql = _AGG_SQL_TPL.format(table=table)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(agg_sql, {"trade_date": trade_date})
            agg_rows = cur.fetchall()

    if not agg_rows:
        logger.warning("No intraday bars found for %s on %s — nothing to roll up",
                       exchange, trade_date)
        return 0

    logger.info("Aggregated %d tickers from ohlcv_intraday", len(agg_rows))

    # Build tuples for upsert_daily_rows:
    # (ticker, trade_date, open, high, low, close, adj_close, volume, exchange, source)
    daily_rows = []
    for r in agg_rows:
        ticker, exch, source, open_, high, low, close, volume = (
            r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]
        )
        if close is None:
            continue
        # adj_close = close (intraday bars are not split-adjusted;
        # the nightly refresh_ohlcv_daily.py will overwrite with the
        # split/dividend-adjusted value from Yahoo/Polygon after market close)
        daily_rows.append((ticker, trade_date, open_, high, low, close, close, volume,
                           exch, source))

    if not daily_rows:
        logger.warning("All aggregated rows had null close — skipping")
        return 0

    if dry_run:
        logger.info("[DRY RUN] Would upsert %d rows into datapai.prices", len(daily_rows))
        for r in daily_rows[:5]:
            logger.info("  sample: ticker=%s  open=%.4f  high=%.4f  low=%.4f  close=%.4f",
                        r[0], r[2] or 0, r[3] or 0, r[4] or 0, r[5] or 0)
        return len(daily_rows)

    upsert_daily_rows(daily_rows, batch_label=f"{exchange} {trade_date} EOD")
    logger.info("Upserted %d daily rows for %s on %s", len(daily_rows), exchange, trade_date)
    return len(daily_rows)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    all_exchanges = list(_INTRADAY_TABLES.keys())
    ap = argparse.ArgumentParser(
        description="EOD rollup: ohlcv_intraday_{exchange} → prices (no cleanup — archive+truncate happens at market open)"
    )
    ap.add_argument("--exchange", choices=all_exchanges, required=True,
                    help="Exchange to roll up")
    ap.add_argument("--date", default="",
                    help="Trade date to roll up (YYYY-MM-DD, default: today)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Log actions without writing to DB")
    args = ap.parse_args()

    trade_date = (
        date.fromisoformat(args.date) if args.date
        else date.today()
    )

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    logger.info("=" * 60)
    logger.info("sync_intraday_to_daily  exchange=%s  date=%s  dry_run=%s",
                args.exchange, trade_date, args.dry_run)
    logger.info("=" * 60)

    n = rollup(args.exchange, trade_date, dry_run=args.dry_run)

    if n == 0:
        logger.warning("No rows rolled up")

    logger.info("EOD rollup complete — %d tickers written to prices", n)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
