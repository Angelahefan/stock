#!/usr/bin/env python3
"""
scripts/sync_postgres_to_s3_oneoff.py
─────────────────────────────────────────────────────────────────────────────
One-off full historical dump: PostgreSQL → S3 raw layer (Parquet).

Reads ALL rows from datapai.prices and datapai.ohlcv_intraday in monthly
batches and writes Hive-partitioned Parquet to S3:

    s3://codepais3/stock/raw/prices/exchange=US/year=2021/month=01/part-0000.parquet
    s3://codepais3/stock/raw/ohlcv_intraday/exchange=ASX/year=2024/month=06/part-0000.parquet

Run ONCE after bootstrap completes.  Use --resume to skip months already
in S3.  Use --dry-run to test without writing.

After this script finishes, run sync_snowflake_iceberg.py to load the
raw Parquet into Snowflake managed Iceberg (bronze layer).

Usage:
    python3 scripts/sync_postgres_to_s3_oneoff.py
    python3 scripts/sync_postgres_to_s3_oneoff.py --resume
    python3 scripts/sync_postgres_to_s3_oneoff.py --dry-run
    python3 scripts/sync_postgres_to_s3_oneoff.py --table prices
    python3 scripts/sync_postgres_to_s3_oneoff.py --table intraday

Env vars:
    DATAPAI_PG_* (same as db_helpers.py)
    AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_DEFAULT_REGION
    S3_BUCKET / S3_RAW_PREFIX
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib.db_helpers import get_conn
from scripts.lib.log_setup import setup_logging, get_log_path
from scripts.lib.s3_helpers import (
    delete_prices_partition,
    delete_intraday_partition,
    list_raw_partitions,
    write_intraday_partition,
    write_prices_partition,
)

logger = setup_logging("sync_postgres_to_s3_oneoff")

_CHUNK_ROWS = 500_000   # rows per DB fetch (keeps memory reasonable)


# ── DB queries ─────────────────────────────────────────────────────────────

def _get_prices_months(exchange: str) -> list[tuple[int, int]]:
    """Return sorted list of (year, month) present in datapai.prices."""
    sql = """
        SELECT DISTINCT
            EXTRACT(YEAR  FROM trade_date::date)::INT AS yr,
            EXTRACT(MONTH FROM trade_date::date)::INT AS mo
        FROM datapai.prices
        WHERE open IS NOT NULL
          AND exchange = %s
        ORDER BY yr, mo;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (exchange,))
            return [(r[0], r[1]) for r in cur.fetchall()]


def _get_intraday_months(exchange: str) -> list[tuple[int, int]]:
    sql = """
        SELECT DISTINCT
            EXTRACT(YEAR  FROM ts::timestamptz)::INT AS yr,
            EXTRACT(MONTH FROM ts::timestamptz)::INT AS mo
        FROM datapai.ohlcv_intraday
        WHERE exchange = %s
        ORDER BY yr, mo;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (exchange,))
            return [(r[0], r[1]) for r in cur.fetchall()]


def _fetch_prices_month(exchange: str, year: int, month: int) -> pd.DataFrame:
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
    # Coerce types so pyarrow schema matches
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["volume"]     = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
    return df


def _fetch_intraday_month(exchange: str, year: int, month: int) -> pd.DataFrame:
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
    # Coerce types so pyarrow schema matches
    df["ts"]     = pd.to_datetime(df["ts"], utc=True)
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
    return df


# ── Main sync ──────────────────────────────────────────────────────────────

def sync_prices(
    exchanges: list[str],
    resume: bool,
    dry_run: bool,
) -> None:
    logger.info("── Prices sync  exchanges=%s  resume=%s  dry_run=%s ──",
                exchanges, resume, dry_run)

    # Existing S3 partitions (for resume)
    existing = set()
    if resume:
        for p in list_raw_partitions("prices"):
            existing.add((p["exchange"], p["year"], p["month"]))
        logger.info("Resume mode: %d existing S3 partitions found", len(existing))

    total_rows = 0
    for exchange in exchanges:
        months = _get_prices_months(exchange)
        logger.info("Exchange %s: %d months to sync", exchange, len(months))

        for year, month in months:
            key = (exchange.upper(), year, month)
            if resume and key in existing:
                logger.info("  SKIP %s %d-%02d (already in S3)", exchange, year, month)
                continue

            df = _fetch_prices_month(exchange, year, month)
            if df.empty:
                continue

            if not dry_run:
                delete_prices_partition(exchange, year, month)

            write_prices_partition(df, exchange, year, month, dry_run=dry_run)
            total_rows += len(df)
            logger.info("  %s %d-%02d → %d rows", exchange, year, month, len(df))

    logger.info("Prices sync complete — %d total rows written", total_rows)


def sync_intraday(
    exchanges: list[str],
    resume: bool,
    dry_run: bool,
) -> None:
    logger.info("── Intraday sync  exchanges=%s ──", exchanges)

    existing = set()
    if resume:
        for p in list_raw_partitions("ohlcv_intraday"):
            existing.add((p["exchange"], p["year"], p["month"]))

    total_rows = 0
    for exchange in exchanges:
        months = _get_intraday_months(exchange)
        logger.info("Exchange %s: %d months to sync", exchange, len(months))

        for year, month in months:
            key = (exchange.upper(), year, month)
            if resume and key in existing:
                logger.info("  SKIP %s %d-%02d", exchange, year, month)
                continue

            df = _fetch_intraday_month(exchange, year, month)
            if df.empty:
                continue

            if not dry_run:
                delete_intraday_partition(exchange, year, month)

            write_intraday_partition(df, exchange, year, month, dry_run=dry_run)
            total_rows += len(df)

    logger.info("Intraday sync complete — %d rows", total_rows)


# ── CLI ─────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="One-off full sync: PostgreSQL → S3 raw Parquet"
    )
    p.add_argument("--exchanges", default="US,ASX",
                   help="Comma-separated exchanges (default: US,ASX)")
    p.add_argument("--table", choices=["prices", "intraday", "all"], default="all",
                   help="Which table to sync (default: all)")
    p.add_argument("--resume", action="store_true",
                   help="Skip months already present in S3")
    p.add_argument("--dry-run", action="store_true",
                   help="Query DB but do not write to S3")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    logger.info("═" * 70)
    logger.info("Log: %s", get_log_path("sync_postgres_to_s3_oneoff"))
    logger.info("One-off Postgres → S3 sync  table=%s  exchanges=%s",
                args.table, args.exchanges)
    logger.info("═" * 70)

    exchanges = [e.strip().upper() for e in args.exchanges.split(",") if e.strip()]

    try:
        if args.table in ("prices", "all"):
            sync_prices(exchanges, resume=args.resume, dry_run=args.dry_run)
        if args.table in ("intraday", "all"):
            sync_intraday(exchanges, resume=args.resume, dry_run=args.dry_run)

        logger.info("═" * 70)
        logger.info("Sync complete%s", " [DRY RUN]" if args.dry_run else "")
        logger.info("Next step: python3 scripts/sync_snowflake_iceberg.py --mode full")
        logger.info("═" * 70)

    except Exception as e:
        logger.exception("FATAL: sync crashed — %s\n%s", e, traceback.format_exc())
        raise
