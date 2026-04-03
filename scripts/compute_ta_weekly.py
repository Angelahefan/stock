#!/usr/bin/env python3
"""
scripts/compute_ta_weekly.py
─────────────────────────────────────────────────────────────────────────────
Pre-compute weekly TA indicators and store them in datapai.ta_indicators.

Weekly bars are derived by resampling daily OHLCV from datapai.prices
(using pandas W-FRI: weeks end on Friday).

Cron schedule (EC2, UTC):
  # Run Sunday at 01:00 UTC (after US Friday market closes)
  0 1 * * 0   datapai python3 /app/scripts/compute_ta_weekly.py --exchange US
  0 1 * * 0   datapai python3 /app/scripts/compute_ta_weekly.py --exchange ASX

Usage:
    python3 scripts/compute_ta_weekly.py --exchange US
    python3 scripts/compute_ta_weekly.py --exchange ASX
    python3 scripts/compute_ta_weekly.py --exchange US --tickers AAPL,MSFT
    python3 scripts/compute_ta_weekly.py --exchange US --full-refresh
    python3 scripts/compute_ta_weekly.py --exchange US --dry-run
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib.log_setup import setup_logging
from scripts.lib.ta_compute import (
    TF_1W,
    compute_and_store,
    fetch_daily_bars,
    get_latest_ts,
    resample_daily_to_weekly,
)
from scripts.lib.ticker_loader import load_monitored_tickers

logger = setup_logging("compute_ta_weekly")

_SLEEP_BETWEEN = 0.05
# Need enough daily bars to produce 200 weekly bars for EMA200:
# 200 weeks × 5 trading days/week ≈ 1000 days + some buffer
_LOOKBACK_DAYS = 1200


def run(
    exchange: str,
    tickers: list[str] | None = None,
    full_refresh: bool = False,
    dry_run: bool = False,
) -> None:
    source = "polygon" if exchange == "US" else "yahoo"
    logger.info(
        "── TA Compute 1w  exchange=%s  full_refresh=%s  dry_run=%s ──",
        exchange, full_refresh, dry_run,
    )

    universe = tickers or load_monitored_tickers(exchange=exchange)
    if not universe:
        logger.warning("No tickers to process — exiting")
        return

    logger.info("Processing %d tickers [%s]", len(universe), exchange)

    total_rows = 0
    skipped    = 0

    for i, ticker in enumerate(universe):
        daily_df = fetch_daily_bars(ticker, exchange, lookback_days=_LOOKBACK_DAYS)
        if daily_df is None or daily_df.empty:
            logger.debug("No daily bars for %s — skip", ticker)
            skipped += 1
            continue

        weekly_df = resample_daily_to_weekly(daily_df)
        if weekly_df is None or weekly_df.empty:
            logger.debug("Not enough data to resample weekly for %s — skip", ticker)
            skipped += 1
            continue

        # Incremental: drop bars already stored
        if not full_refresh:
            latest = get_latest_ts(ticker, exchange, TF_1W)
            if latest is not None:
                cutoff = latest.date()
                weekly_df = weekly_df[weekly_df.index.date > cutoff]  # type: ignore
                if weekly_df.empty:
                    logger.debug("No new weekly bars for %s — skip", ticker)
                    skipped += 1
                    continue
                # Re-fetch full history for warm-up, recompute only new bars
                full_weekly = resample_daily_to_weekly(
                    fetch_daily_bars(ticker, exchange, lookback_days=_LOOKBACK_DAYS)
                )
                if full_weekly is not None:
                    n = _compute_new_bars_only(
                        full_weekly, weekly_df, ticker, exchange, TF_1W, source, dry_run
                    )
                    total_rows += n
                    if i < len(universe) - 1:
                        time.sleep(_SLEEP_BETWEEN)
                    continue

        n = compute_and_store(weekly_df, ticker, exchange, TF_1W, source, dry_run)
        total_rows += n

        if i < len(universe) - 1:
            time.sleep(_SLEEP_BETWEEN)

    logger.info(
        "TA 1w complete — exchange=%s  tickers=%d  rows=%d  skipped=%d%s",
        exchange, len(universe) - skipped, total_rows, skipped,
        " [DRY RUN]" if dry_run else "",
    )


def _compute_new_bars_only(full_df, new_bars_df, ticker, exchange, timeframe, source, dry_run):
    from agents.technical_analysis import calc_indicators
    from scripts.lib.db_helpers import upsert_ta_indicators
    from scripts.lib.ta_compute import _to_utc_datetime, indicators_to_row

    rows = []
    new_indices = set(new_bars_df.index)

    for i in range(len(full_df)):
        bar_idx = full_df.index[i]
        if bar_idx not in new_indices:
            continue
        if i < 1:
            continue
        sub_df = full_df.iloc[: i + 1]
        try:
            ind = calc_indicators(sub_df)
        except Exception as exc:
            logger.debug("calc_indicators failed %s %s: %s", ticker, bar_idx, exc)
            continue
        ts_dt      = _to_utc_datetime(bar_idx)
        trade_date = ts_dt.date()
        rows.append(indicators_to_row(ind, ticker, exchange, timeframe, ts_dt, trade_date, source))

    if not rows:
        return 0
    if dry_run:
        logger.info("[DRY RUN] Would upsert %d weekly rows for %s", len(rows), ticker)
        return len(rows)
    upsert_ta_indicators(rows, batch_label=f"{ticker} {timeframe} incremental")
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Pre-compute weekly TA indicators")
    ap.add_argument("--exchange", required=True)
    ap.add_argument("--tickers", default="", help="Comma-separated override list")
    ap.add_argument("--full-refresh", action="store_true",
                    help="Recompute and overwrite all historical bars")
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
    run(
        exchange=args.exchange,
        tickers=override,
        full_refresh=args.full_refresh,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
