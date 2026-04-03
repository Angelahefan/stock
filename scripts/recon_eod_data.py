#!/usr/bin/env python3
"""
scripts/recon_eod_data.py
─────────────────────────────────────────────────────────────────────────────
EOD Data Reconciliation — checks for missing price data and backfills gaps.

Runs after all EOD jobs complete. For each exchange:
  1. Checks last N trading days for gaps (missing dates or low ticker counts)
  2. If gaps found, triggers backfill via refresh_ohlcv_daily.py
  3. Logs results for monitoring

Usage:
    python3 scripts/recon_eod_data.py --region asia    # ASX + HKEX + SET + KLSE + IDX + HOSE
    python3 scripts/recon_eod_data.py --region us      # US only
    python3 scripts/recon_eod_data.py --region all     # everything
    python3 scripts/recon_eod_data.py --region asia --dry-run
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib.db_helpers import get_conn
from scripts.lib.log_setup import setup_logging

logger = setup_logging("recon_eod_data")

# ── Exchange groups (DB-driven) ────────────────────────────────────────────
from core.config.exchange_registry import registry as _exr
ASIA_EXCHANGES = _exr.get_exchanges_by_region("asia")
US_EXCHANGES = _exr.get_exchanges_by_region("us")

# Minimum expected ticker counts per exchange (rough floor — ~70% of universe)
# If a day has fewer tickers than this, it's flagged as a gap
MIN_TICKER_COUNTS = {
    "US": 5000,
    "ASX": 1200,
    "HKEX": 2000,
    "SET": 300,
    "KLSE": 700,
    "IDX": 400,
    "HOSE": 250,
}

# How many trading days back to check
LOOKBACK_DAYS = 5

# Market holidays / weekend logic — skip Sat/Sun
WEEKDAYS = {0, 1, 2, 3, 4}  # Mon-Fri


def _get_expected_trading_days(lookback: int = LOOKBACK_DAYS) -> list[date]:
    """Return last N weekdays (approximate trading days)."""
    days = []
    d = date.today() - timedelta(days=1)  # start from yesterday
    while len(days) < lookback:
        if d.weekday() in WEEKDAYS:
            days.append(d)
        d -= timedelta(days=1)
    return sorted(days)


def _get_actual_data(exchanges: list[str], since: date) -> dict[str, dict[str, int]]:
    """
    Query actual data counts per exchange per date.
    Returns: {exchange: {date_str: ticker_count}}
    """
    result: dict[str, dict[str, int]] = {ex: {} for ex in exchanges}
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT exchange, trade_date::date::text, COUNT(DISTINCT ticker)
                    FROM datapai.prices
                    WHERE exchange = ANY(%s)
                      AND trade_date::date >= %s
                    GROUP BY exchange, trade_date::date
                    ORDER BY exchange, trade_date::date
                """, (exchanges, since.isoformat()))
                for row in cur.fetchall():
                    ex, dt, cnt = row
                    result[ex][dt] = cnt
    except Exception as e:
        logger.error("Failed to query prices: %s", e)
    return result


def _backfill_exchange(exchange: str, days: int = 5, dry_run: bool = False) -> bool:
    """Run refresh_ohlcv_daily.py --exchange X --days N to backfill."""
    script = Path(__file__).parent / "refresh_ohlcv_daily.py"
    cmd = [sys.executable, str(script), "--exchange", exchange, "--days", str(days)]
    if dry_run:
        cmd.append("--dry-run")

    logger.info("Backfilling %s (days=%d) %s", exchange, days, "[DRY RUN]" if dry_run else "")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=3600,  # 1hr max per exchange
            cwd=str(Path(__file__).parent.parent),
        )
        if result.returncode == 0:
            logger.info("Backfill %s succeeded", exchange)
            return True
        else:
            logger.error("Backfill %s failed (exit %d): %s", exchange, result.returncode, result.stderr[-500:])
            return False
    except subprocess.TimeoutExpired:
        logger.error("Backfill %s timed out after 1 hour", exchange)
        return False
    except Exception as e:
        logger.error("Backfill %s error: %s", exchange, e)
        return False


def recon(exchanges: list[str], dry_run: bool = False) -> dict[str, dict]:
    """
    Run reconciliation for given exchanges.
    Returns summary: {exchange: {status, missing_dates, low_dates, backfilled}}
    """
    expected_days = _get_expected_trading_days(LOOKBACK_DAYS)
    since = expected_days[0]
    logger.info("── EOD Recon  exchanges=%s  checking %s → %s ──",
                ",".join(exchanges), since, expected_days[-1])

    actual = _get_actual_data(exchanges, since)
    summary: dict[str, dict] = {}

    for ex in exchanges:
        ex_data = actual.get(ex, {})
        min_count = MIN_TICKER_COUNTS.get(ex, 100)

        missing_dates = []
        low_dates = []

        for d in expected_days:
            ds = d.isoformat()
            count = ex_data.get(ds, 0)
            if count == 0:
                missing_dates.append(ds)
            elif count < min_count:
                low_dates.append(f"{ds}({count})")

        needs_backfill = len(missing_dates) > 0 or len(low_dates) > 0
        backfilled = False

        if needs_backfill:
            logger.warning(
                "%s GAPS FOUND — missing: %s, low: %s",
                ex,
                missing_dates or "none",
                low_dates or "none",
            )
            backfilled = _backfill_exchange(ex, days=LOOKBACK_DAYS + 2, dry_run=dry_run)
        else:
            logger.info("%s OK — all %d days have ≥%d tickers", ex, len(expected_days), min_count)

        summary[ex] = {
            "status": "OK" if not needs_backfill else ("BACKFILLED" if backfilled else "GAP"),
            "missing_dates": missing_dates,
            "low_dates": low_dates,
            "backfilled": backfilled,
        }

    # Final summary
    logger.info("── Recon Summary ──")
    for ex, s in summary.items():
        logger.info("  %s: %s  missing=%d  low=%d  backfilled=%s",
                     ex, s["status"], len(s["missing_dates"]), len(s["low_dates"]), s["backfilled"])

    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="EOD data reconciliation and gap backfill")
    ap.add_argument("--region", required=True, choices=["asia", "us", "all"],
                    help="Which exchanges to reconcile")
    ap.add_argument("--dry-run", action="store_true", help="Check gaps but don't backfill")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    if args.region == "asia":
        exchanges = ASIA_EXCHANGES
    elif args.region == "us":
        exchanges = US_EXCHANGES
    else:
        exchanges = ASIA_EXCHANGES + US_EXCHANGES

    summary = recon(exchanges, dry_run=args.dry_run)

    # Exit with error if any exchange has unfixed gaps
    unfixed = [ex for ex, s in summary.items() if s["status"] == "GAP"]
    if unfixed:
        logger.error("Unfixed gaps remain: %s", unfixed)
        sys.exit(1)


if __name__ == "__main__":
    main()
