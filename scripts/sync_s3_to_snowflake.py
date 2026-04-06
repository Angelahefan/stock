#!/usr/bin/env python3
"""
scripts/sync_s3_to_snowflake.py
─────────────────────────────────────────────────────────────────────────────
Snowflake stock table setup + data loading from S3 raw stage.

Pipeline:
    S3 raw Parquet  ──COPY──►  Snowflake permanent tables
    (written by Python)         (DATAPAI.STOCK schema)

Tables:
    DATAPAI.STOCK.PRICES          — daily OHLCV
    DATAPAI.STOCK.OHLCV_INTRADAY  — 30-minute bars

Setup (one-time — preferred via dbt):
    # Infrastructure (schema, storage integration, stage):
    cd /path/to/dbt-demo
    export SNOWFLAKE_ROLE=ACCOUNTADMIN
    dbt run-operation create_stock_infra

    # Create tables via dbt (schema-as-code):
    dbt run --select stock.*

    # Or use Python fallback (--mode setup):
    python3 scripts/sync_s3_to_snowflake.py --mode setup

Full load (run after sync_postgres_to_s3_oneoff.py):
    python3 scripts/sync_s3_to_snowflake.py --mode full

Daily delta (run after sync_postgres_to_s3_daily.py):
    python3 scripts/sync_s3_to_snowflake.py --mode delta --days 3

Pre-requisites:
    pip install snowflake-connector-python pyarrow boto3

Env vars:
    # Snowflake (existing in .bash_profile)
    SNOWFLAKE_ACCOUNT      e.g. AORKUCF-CV45422.ap-southeast-2.aws
    SNOWFLAKE_USER         e.g. AIRBYTE_USER
    SNOWFLAKE_PASSWORD
    SNOWFLAKE_WAREHOUSE    default: DATAPAI_WAREHOUSE
    SNOWFLAKE_DATABASE     default: DATAPAI
    SNOWFLAKE_ROLE         default: AIRBYTE_ROLE  (use ACCOUNTADMIN for setup)
    SNOWFLAKE_S3_ROLE_ARN  IAM role ARN Snowflake uses to access S3
                           (required for --mode setup)

    # AWS (EC2 uses IAM instance role — no keys needed)
    AWS_DEFAULT_REGION     default: ap-southeast-2

    # S3
    S3_BUCKET_STOCK        default: codepais3
"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib.log_setup import setup_logging
from scripts.lib.s3_helpers import list_raw_partitions
from scripts.lib.snowflake_helpers import (
    execute,
    get_row_counts,
    get_sf_conn,
    load_intraday_from_stage,
    load_prices_from_stage,
    setup_snowflake,
)

logger = setup_logging("sync_s3_to_snowflake")


def _affected_months(days: int) -> list[tuple[int, int]]:
    today = date.today()
    start = today - timedelta(days=days)
    months = set()
    cur = start
    while cur <= today:
        months.add((cur.year, cur.month))
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return sorted(months)


# ── Modes ──────────────────────────────────────────────────────────────────

def mode_setup(conn) -> None:
    """Create schema, storage integration, stage, and stock tables."""
    setup_snowflake(conn)


def mode_full(conn, exchanges: list[str], dry_run: bool) -> None:
    """
    Full load: iterate all existing S3 raw partitions and load into Snowflake.
    Idempotent — deletes + reloads each partition.
    """
    logger.info("=== Full Snowflake load  exchanges=%s ===", exchanges)
    total_prices = 0
    total_intraday = 0

    for table, loader in [
        ("prices",        load_prices_from_stage),
        ("ohlcv_intraday", load_intraday_from_stage),
    ]:
        partitions = list_raw_partitions(table)
        for p in partitions:
            if p["exchange"].upper() not in [e.upper() for e in exchanges]:
                continue
            if dry_run:
                logger.info("[DRY RUN] Would load %s  %s  %d-%02d",
                            table, p["exchange"], p["year"], p["month"])
                continue
            n = loader(conn, p["exchange"], p["year"], p["month"])
            if table == "prices":
                total_prices += n
            else:
                total_intraday += n

    if not dry_run:
        counts = get_row_counts(conn)
        logger.info("Snowflake totals → prices=%d  intraday=%d",
                    counts["prices"], counts["ohlcv_intraday"])
    logger.info("=== Full load complete ===")


def mode_delta(conn, exchanges: list[str], days: int, dry_run: bool) -> None:
    """
    Delta load: reload only the S3 partitions touched by the last N days.
    """
    logger.info("=== Delta Snowflake load  days=%d  exchanges=%s ===",
                days, exchanges)
    months = _affected_months(days)
    total = 0

    for exchange in exchanges:
        for year, month in months:
            for table, loader in [
                ("prices",        load_prices_from_stage),
                ("ohlcv_intraday", load_intraday_from_stage),
            ]:
                if dry_run:
                    logger.info("[DRY RUN] Would reload %s  %s  %d-%02d",
                                table, exchange, year, month)
                    continue
                n = loader(conn, exchange, year, month)
                total += n

    if not dry_run:
        counts = get_row_counts(conn)
        logger.info("After delta → prices=%d  intraday=%d",
                    counts["prices"], counts["ohlcv_intraday"])
    logger.info("=== Delta load complete  %d rows refreshed ===", total)


def mode_status(conn) -> None:
    """Print current Snowflake stock table row counts."""
    counts = get_row_counts(conn)
    logger.info("Snowflake stock status:")
    logger.info("  STOCK.PRICES          : %d rows", counts["prices"])
    logger.info("  STOCK.OHLCV_INTRADAY  : %d rows", counts["ohlcv_intraday"])

    # Show per-exchange breakdown
    from scripts.lib.snowflake_helpers import SF_DATABASE, SF_ICEBERG_SCHEMA as schema
    db = SF_DATABASE
    rows = execute(conn, f"""
        SELECT exchange,
               COUNT(*) AS rows,
               COUNT(DISTINCT ticker) AS tickers,
               MIN(trade_date) AS earliest,
               MAX(trade_date) AS latest
        FROM {db}.{schema}.PRICES
        GROUP BY exchange ORDER BY exchange;
    """)
    for r in rows:
        logger.info("  prices  %-5s  rows=%-8d  tickers=%-5d  %s → %s",
                    r["exchange"], r["rows"], r["tickers"], r["earliest"], r["latest"])


# ── CLI ─────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="S3 raw Parquet → Snowflake permanent tables"
    )
    p.add_argument(
        "--mode",
        choices=["setup", "full", "delta", "status"],
        default="delta",
        help=(
            "setup  = create schema + storage integration + stage + tables (run once)\n"
            "full   = load all S3 raw partitions into Snowflake\n"
            "delta  = reload last N days only\n"
            "status = print row counts"
        ),
    )
    p.add_argument("--exchanges", default="US,ASX")
    p.add_argument("--days", type=int, default=3,
                   help="Days to cover in delta mode (default: 3)")
    p.add_argument("--dry-run", action="store_true",
                   help="Log actions but do not execute Snowflake SQL")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    logger.info("═" * 70)
    logger.info("sync_s3_to_snowflake  mode=%s  exchanges=%s",
                args.mode, args.exchanges)
    logger.info("═" * 70)

    exchanges = [e.strip().upper() for e in args.exchanges.split(",") if e.strip()]

    try:
        with get_sf_conn() as conn:
            if args.mode == "setup":
                mode_setup(conn)
            elif args.mode == "full":
                mode_full(conn, exchanges, dry_run=args.dry_run)
            elif args.mode == "delta":
                mode_delta(conn, exchanges, days=args.days, dry_run=args.dry_run)
            elif args.mode == "status":
                mode_status(conn)

        logger.info("═" * 70)
        logger.info("Done%s", " [DRY RUN]" if args.dry_run else "")
        logger.info("═" * 70)

    except Exception as e:
        logger.exception("FATAL: Snowflake sync crashed — %s\n%s", e, traceback.format_exc())
        raise
