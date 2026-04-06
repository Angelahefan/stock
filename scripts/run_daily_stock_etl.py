#!/usr/bin/env python3
"""
scripts/run_daily_stock_etl.py
──────────────────────────────────────────────────────────────────────────────
Daily delta ETL orchestrator: Postgres → S3 raw → Snowflake Iceberg.

This script is the *downstream* half of the stock data pipeline.  The upstream
API-to-Postgres refreshes run on their own cron schedules:
  - refresh_ohlcv_daily.py   →  US stocks,   cron: 15 23 * * 1-5 UTC
  - refresh_ohlcv_asx.py     →  ASX stocks,  cron: 15  6 * * 1-5 UTC

This orchestrator runs *after* both refreshes complete:
  cron: 30 0 * * 2-6          ← 00:30 UTC Tue-Sat (covers Mon-Fri trading day)

Pipeline steps executed here:
  1. sync_postgres_to_s3_daily.py   [Postgres → S3 raw Parquet, last N days]
  2. sync_s3_to_snowflake.py        [S3 raw → Snowflake permanent tables, delta]

Logs (rotating 10 MB × 5 files):
  /var/log/datapai/daily_stock_etl.log          ← this script (step markers)
  /var/log/datapai/sync_postgres_to_s3_daily.log ← step 1 details
  /var/log/datapai/sync_s3_to_snowflake.log      ← step 2 details

Usage:
  python3 scripts/run_daily_stock_etl.py
  python3 scripts/run_daily_stock_etl.py --days 5 --exchanges US,ASX
  python3 scripts/run_daily_stock_etl.py --dry-run
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

# Allow `from lib.xxx import` when run from any working directory
sys.path.insert(0, str(Path(__file__).parent))

from lib.log_setup import setup_logging

log = setup_logging("daily_stock_etl")
SCRIPT_DIR = Path(__file__).parent


# ── helpers ──────────────────────────────────────────────────────────────────

def _run_step(label: str, cmd: list, dry_run: bool) -> bool:
    """Run one subprocess step.  Returns True on success, False on failure."""
    log.info("── %s ──", label)
    log.info("CMD: %s", " ".join(str(c) for c in cmd))
    if dry_run:
        log.info("DRY-RUN: skipped")
        return True
    t0 = time.time()
    # Do NOT capture output — each child script writes its own rotating log
    # via log_setup; stdout/stderr go to syslog / cron MAILTO on EC2.
    result = subprocess.run(cmd)
    elapsed = time.time() - t0
    if result.returncode == 0:
        log.info("%s → OK  (%.1fs)", label, elapsed)
        return True
    log.error("%s → FAILED  rc=%d  (%.1fs)", label, result.returncode, elapsed)
    return False


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Daily stock ETL: Postgres → S3 raw → Snowflake Iceberg"
    )
    ap.add_argument(
        "--days", type=int, default=3,
        help="Look-back window for delta sync in days (default: 3)"
    )
    ap.add_argument(
        "--exchanges", default="US,ASX",
        help="Comma-separated exchanges to sync (default: US,ASX)"
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Log steps without executing them"
    )
    args = ap.parse_args()

    py = sys.executable

    steps = [
        (
            "sync_postgres_to_s3_daily  [Postgres → S3 raw]",
            [
                py, str(SCRIPT_DIR / "sync_postgres_to_s3_daily.py"),
                "--days",      str(args.days),
                "--exchanges", args.exchanges,
            ],
        ),
        (
            "sync_s3_to_snowflake --mode delta  [S3 raw → Snowflake]",
            [
                py, str(SCRIPT_DIR / "sync_s3_to_snowflake.py"),
                "--mode",      "delta",
                "--days",      str(args.days),
                "--exchanges", args.exchanges,
            ],
        ),
    ]

    log.info("=" * 60)
    log.info(
        "daily_stock_etl  started  (days=%d  exchanges=%s  dry_run=%s)",
        args.days, args.exchanges, args.dry_run,
    )
    log.info("=" * 60)

    for label, cmd in steps:
        if not _run_step(label, cmd, args.dry_run):
            log.error("Pipeline aborted at step: %s", label)
            sys.exit(1)
        log.info("-" * 60)

    log.info("daily_stock_etl  completed successfully")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
