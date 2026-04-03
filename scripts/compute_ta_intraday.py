#!/usr/bin/env python3
"""
scripts/compute_ta_intraday.py
─────────────────────────────────────────────────────────────────────────────
Pre-compute TA indicators for the 30-minute timeframe and store them in
datapai.ta_indicators.

Runs every 30 minutes during market hours (same cadence as refresh_ohlcv_intraday.py).
Reads bars from datapai.ohlcv_intraday, computes all indicators on the latest
bar, and upserts a single row per ticker into ta_indicators.

Cron schedule (EC2, UTC):
  # US market hours 09:30–16:00 ET = 13:30–20:00 UTC (5 min after refresh)
  5,35 13-20 * * 1-5   datapai python3 /app/scripts/compute_ta_intraday.py --exchange US

  # ASX market hours 10:00–16:00 AEDT = 23:00–06:00 UTC
  5,35 23    * * 0-4   datapai python3 /app/scripts/compute_ta_intraday.py --exchange ASX
  5,35 0-6   * * 1-5   datapai python3 /app/scripts/compute_ta_intraday.py --exchange ASX

Usage:
    python3 scripts/compute_ta_intraday.py --exchange US
    python3 scripts/compute_ta_intraday.py --exchange ASX
    python3 scripts/compute_ta_intraday.py --exchange US --tickers AAPL,MSFT
    python3 scripts/compute_ta_intraday.py --exchange US --dry-run
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib.log_setup import setup_logging
from scripts.lib.ta_compute import TF_30M, compute_and_store, fetch_intraday_bars
from scripts.lib.ticker_loader import load_monitored_tickers

logger = setup_logging("compute_ta_intraday")

_SLEEP_BETWEEN = 0.1   # seconds between tickers (DB reads only — light)


def run(
    exchange: str,
    tickers: list[str] | None = None,
    dry_run: bool = False,
) -> None:
    source = "polygon" if exchange == "US" else "yahoo"
    logger.info("── TA Compute 30m  exchange=%s  dry_run=%s ──", exchange, dry_run)

    universe = tickers or load_monitored_tickers(exchange=exchange)
    if not universe:
        logger.warning("No tickers to process — exiting")
        return

    logger.info("Processing %d tickers [%s]", len(universe), exchange)

    total_rows = 0
    skipped    = 0

    for i, ticker in enumerate(universe):
        # ASX tickers stored with .AX suffix in ohlcv_intraday
        store_ticker = ticker if exchange == "US" else (
            ticker if ticker.endswith(".AX") else f"{ticker}.AX"
        )

        df = fetch_intraday_bars(store_ticker, exchange, lookback_days=10)
        if df is None or df.empty:
            logger.debug("No intraday bars for %s — skip", store_ticker)
            skipped += 1
            continue

        n = compute_and_store(df, store_ticker, exchange, TF_30M, source, dry_run)
        total_rows += n

        if i < len(universe) - 1:
            time.sleep(_SLEEP_BETWEEN)

    logger.info(
        "TA 30m complete — exchange=%s  tickers=%d  rows=%d  skipped=%d%s",
        exchange, len(universe) - skipped, total_rows, skipped,
        " [DRY RUN]" if dry_run else "",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Pre-compute 30m TA indicators")
    ap.add_argument("--exchange", required=True)
    ap.add_argument("--tickers", default="", help="Comma-separated override list")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    override = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if args.tickers else None
    )
    run(exchange=args.exchange, tickers=override, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
