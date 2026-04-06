#!/usr/bin/env python3
"""
scripts/sync_postgres_to_s3_daily.py
─────────────────────────────────────────────────────────────────────────────
Daily delta sync: PostgreSQL → S3 raw layer (Parquet).

Fetches the last N days of OHLCV from Postgres and overwrites the
corresponding S3 raw partitions.  Designed to run after the daily
OHLCV refresh scripts (refresh_ohlcv_daily.py / refresh_ohlcv_asx.py).

Cron (run after both exchanges close + OHLCV refresh finishes):
    30 23 * * 1-5   root  cd /app && python3 scripts/sync_postgres_to_s3_daily.py

After this runs, sync_snowflake_iceberg.py --mode delta should also run
to load the new Parquet into Snowflake Iceberg (bronze layer).

Usage:
    python3 scripts/sync_postgres_to_s3_daily.py               # last 3 days
    python3 scripts/sync_postgres_to_s3_daily.py --days 7
    python3 scripts/sync_postgres_to_s3_daily.py --dry-run
    python3 scripts/sync_postgres_to_s3_daily.py --table prices
"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib.db_helpers import get_conn
from scripts.lib.log_setup import setup_logging
from scripts.lib.s3_helpers import (
    delete_intraday_partition,
    delete_prices_partition,
    write_intraday_partition,
    write_prices_partition,
)

logger = setup_logging("sync_postgres_to_s3_daily")


def _affected_months(days: int) -> list[tuple[int, int]]:
    """Return (year, month) tuples covering the last N calendar days."""
    today = date.today()
    start = today - timedelta(days=days)
    months = set()
    cur = start
    while cur <= today:
        months.add((cur.year, cur.month))
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)  # next month
    return sorted(months)


def _fetch_prices_month_recent(
    exchange: str, year: int, month: int, since_date: date
) -> pd.DataFrame:
    """Fetch prices for a month, but only rows on or after since_date."""
    sql = """
        SELECT ticker, trade_date::text, open, high, low, close, adj_close,
               volume::bigint, exchange, source
        FROM datapai.prices
        WHERE open IS NOT NULL
          AND exchange = %s
          AND EXTRACT(YEAR  FROM trade_date::date) = %s
          AND EXTRACT(MONTH FROM trade_date::date) = %s
          AND trade_date::date >= %s
        ORDER BY ticker, trade_date;
    """
    with get_conn() as conn:
        df = pd.read_sql_query(sql, conn, params=(exchange, year, month, since_date))
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["volume"]     = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
    return df


def _fetch_prices_full_month(exchange: str, year: int, month: int) -> pd.DataFrame:
    """Fetch ALL prices for a month (to rewrite the full partition)."""
    sql = """
        SELECT ticker, trade_date::text, open, high, low, close, adj_close,
               volume::bigint, exchange, source
        FROM datapai.prices
        WHERE open IS NOT NULL
          AND exchange = %s
          AND EXTRACT(YEAR  FROM trade_date::date) = %s
          AND EXTRACT(MONTH FROM trade_date::date) = %s
        ORDER BY ticker, trade_date;
    """
    with get_conn() as conn:
        df = pd.read_sql_query(sql, conn, params=(exchange, year, month))
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["volume"]     = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
    return df


def _fetch_intraday_full_month(exchange: str, year: int, month: int) -> pd.DataFrame:
    sql = """
        SELECT ticker, ts::text, open, high, low, close,
               volume::bigint, exchange, source
        FROM datapai.ohlcv_intraday
        WHERE exchange = %s
          AND EXTRACT(YEAR  FROM ts::timestamptz) = %s
          AND EXTRACT(MONTH FROM ts::timestamptz) = %s
        ORDER BY ticker, ts;
    """
    with get_conn() as conn:
        df = pd.read_sql_query(sql, conn, params=(exchange, year, month))
    df["ts"]     = pd.to_datetime(df["ts"], utc=True)
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
    return df


def sync_prices_delta(
    exchanges: list[str],
    days: int,
    dry_run: bool,
) -> None:
    logger.info("── Daily prices delta  exchanges=%s  days=%d  dry_run=%s",
                exchanges, days, dry_run)

    since = date.today() - timedelta(days=days)
    months = _affected_months(days)
    total_rows = 0

    for exchange in exchanges:
        for year, month in months:
            # Rewrite the full month partition so it stays consistent
            df = _fetch_prices_full_month(exchange, year, month)
            if df.empty:
                continue

            if not dry_run:
                delete_prices_partition(exchange, year, month)

            write_prices_partition(df, exchange, year, month, dry_run=dry_run)
            total_rows += len(df)
            logger.info("  prices  %s  %d-%02d → %d rows", exchange, year, month, len(df))

    logger.info("Daily prices delta complete — %d rows written", total_rows)


def sync_intraday_delta(
    exchanges: list[str],
    days: int,
    dry_run: bool,
) -> None:
    logger.info("── Daily intraday delta  exchanges=%s  days=%d", exchanges, days)

    months = _affected_months(days)
    total_rows = 0

    for exchange in exchanges:
        for year, month in months:
            df = _fetch_intraday_full_month(exchange, year, month)
            if df.empty:
                continue

            if not dry_run:
                delete_intraday_partition(exchange, year, month)

            write_intraday_partition(df, exchange, year, month, dry_run=dry_run)
            total_rows += len(df)

    logger.info("Daily intraday delta complete — %d rows written", total_rows)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Daily delta sync: Postgres → S3 raw Parquet")
    p.add_argument("--exchanges", default="US,ASX")
    p.add_argument("--days", type=int, default=3,
                   help="Number of recent days to sync (default: 3)")
    p.add_argument("--table", choices=["prices", "intraday", "all"], default="all")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


# ── Analytics tables (ta_indicators, fundamental, etc.) ──────────────────────

ANALYTICS_TABLES = {
    "ta_indicators": {
        "sql": """
            SELECT * FROM datapai.ta_indicators
            WHERE exchange = %s AND trade_date >= CURRENT_DATE - %s
            ORDER BY ticker, timeframe, ts
        """,
        "params": lambda exchange, days: (exchange, days),
    },
    "ta_signals": {
        "sql": """
            SELECT * FROM datapai.ta_signals
            WHERE exchange = %s
            ORDER BY ticker, generated_at DESC
        """,
        "params": lambda exchange, days: (exchange,),
    },
    "fundamental_snapshot": {
        "sql": """
            SELECT * FROM datapai.fundamental_snapshot
            WHERE exchange = %s
            ORDER BY ticker
        """,
        "params": lambda exchange, days: (exchange,),
    },
    "fundamental_history": {
        "sql": """
            SELECT * FROM datapai.fundamental_history
            WHERE exchange = %s
            ORDER BY ticker, period_end DESC
        """,
        "params": lambda exchange, days: (exchange,),
    },
    "analyses": {
        "sql": """
            SELECT a.*, s.ticker, s.url
            FROM datapai.analyses a
            JOIN datapai.snapshots s ON a.snapshot_new_id = s.id
            ORDER BY s.ticker, a.id DESC
        """,
        "params": lambda exchange, days: (),
        "no_exchange_filter": True,
    },
    "stock_synthesis": {
        "sql": """
            SELECT * FROM datapai.stock_synthesis
            WHERE exchange = %s
            ORDER BY ticker, computed_at DESC
        """,
        "params": lambda exchange, days: (exchange,),
    },
    "broker_ratings": {
        "sql": """
            SELECT * FROM datapai.broker_ratings
            ORDER BY ticker
        """,
        "params": lambda exchange, days: (),
        "no_exchange_filter": True,
    },
}


def sync_analytics_tables(
    exchanges: list[str],
    days: int,
    dry_run: bool,
) -> None:
    """Sync analytics tables to S3 (full overwrite per exchange)."""
    from scripts.lib.s3_helpers import delete_generic_table, write_generic_table

    logger.info("── Analytics tables sync  exchanges=%s  dry_run=%s", exchanges, dry_run)
    total_rows = 0

    for table_name, config in ANALYTICS_TABLES.items():
        if config.get("no_exchange_filter"):
            # Tables without exchange column — sync once
            sql = config["sql"]
            params = config["params"]("", days)
            try:
                with get_conn() as conn:
                    df = pd.read_sql_query(sql, conn, params=params if params else None)
            except Exception as exc:
                logger.warning("Failed to fetch %s: %s", table_name, exc)
                continue

            if df.empty:
                continue

            if not dry_run:
                delete_generic_table(table_name, "ALL")
            write_generic_table(df, table_name, "ALL", dry_run=dry_run)
            total_rows += len(df)
            logger.info("  %s  ALL → %d rows", table_name, len(df))
        else:
            for exchange in exchanges:
                sql = config["sql"]
                params = config["params"](exchange, days)
                try:
                    with get_conn() as conn:
                        df = pd.read_sql_query(sql, conn, params=params)
                except Exception as exc:
                    logger.warning("Failed to fetch %s/%s: %s", table_name, exchange, exc)
                    continue

                if df.empty:
                    continue

                if not dry_run:
                    delete_generic_table(table_name, exchange)
                write_generic_table(df, table_name, exchange, dry_run=dry_run)
                total_rows += len(df)
                logger.info("  %s  %s → %d rows", table_name, exchange, len(df))

    logger.info("Analytics tables sync complete — %d rows written", total_rows)


if __name__ == "__main__":
    args = _parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    logger.info("Daily S3 delta sync  exchanges=%s  days=%d  table=%s",
                args.exchanges, args.days, args.table)

    exchanges = [e.strip().upper() for e in args.exchanges.split(",") if e.strip()]

    try:
        if args.table in ("prices", "all"):
            sync_prices_delta(exchanges, days=args.days, dry_run=args.dry_run)
        if args.table in ("intraday", "all"):
            sync_intraday_delta(exchanges, days=args.days, dry_run=args.dry_run)

        sync_analytics_tables(exchanges, days=args.days, dry_run=args.dry_run)
        logger.info("Daily S3 sync complete%s", " [DRY RUN]" if args.dry_run else "")
        logger.info("Next: python3 scripts/sync_snowflake_iceberg.py --mode delta --days %d", args.days)

    except Exception as e:
        logger.exception("FATAL: daily S3 sync crashed — %s\n%s", e, traceback.format_exc())
        raise


