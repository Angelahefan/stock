#!/usr/bin/env python3
"""
scripts/refresh_ohlcv_daily.py
─────────────────────────────────────────────────────────────────────────────
Daily delta refresh of OHLCV for US stocks.

Cron: 15 23 * * 1-5   (6:15 PM ET, after US market closes at 4:00 PM ET)

Fetches the last 3 trading days via yfinance for all US tickers.
Batches of 500 tickers. Sleeps 1–2 s between batches.
UPSERT into datapai.prices — safe to re-run.

Usage:
    python3 scripts/refresh_ohlcv_daily.py                # normal run
    python3 scripts/refresh_ohlcv_daily.py --dry-run      # download, no DB write
    python3 scripts/refresh_ohlcv_daily.py --no-cache     # force ticker list refresh
    python3 scripts/refresh_ohlcv_daily.py --days 5       # fetch last N days
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib.db_helpers import df_to_daily_rows, get_latest_dates, upsert_daily_rows, get_conn
from scripts.lib.log_setup import setup_logging
from scripts.lib.ticker_loader import load_us_tickers

logger = setup_logging("refresh_ohlcv_daily")

_BATCH_SIZE  = 500
_SLEEP_MIN   = 1.0
_SLEEP_MAX   = 2.5
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0
_BACKOFF_MAX  = 60.0


def _days_to_period(days: int) -> str:
    if days <= 5:
        return "5d"
    if days <= 10:
        return "1mo"
    return "1mo"


def _download_batch_retry(tickers: list[str], period: str) -> dict[str, pd.DataFrame]:
    for attempt in range(_MAX_RETRIES):
        try:
            raw = yf.download(
                tickers=" ".join(tickers),
                period=period,
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                prepost=False,
                progress=False,
                threads=False,
            )
            if raw is None or raw.empty:
                raise ValueError("empty result")

            if len(tickers) == 1:
                return {tickers[0].upper(): raw}

            result = {}
            available = set(raw.columns.get_level_values(0))
            for sym in tickers:
                sym_up = sym.upper()
                try:
                    if sym_up in available:
                        df = raw[sym_up]
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.get_level_values(-1)
                        if not df.empty:
                            result[sym_up] = df
                except (KeyError, TypeError):
                    pass
            return result

        except Exception as exc:
            if attempt < _MAX_RETRIES - 1:
                wait = min(_BACKOFF_BASE ** (attempt + 1), _BACKOFF_MAX) + random.uniform(0, 1)
                logger.warning("Batch error (attempt %d): %s — retry in %.1fs", attempt + 1, exc, wait)
                time.sleep(wait)
            else:
                logger.error("Gave up on batch %s…%s: %s", tickers[0], tickers[-1], exc)
    return {}


def _load_us_from_universe() -> list[str]:
    """Load active US tickers from datapai.ticker_universe."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT yf_symbol FROM datapai.ticker_universe
                    WHERE exchange = 'US' AND is_active = TRUE
                    ORDER BY ticker
                """)
                tickers = [r[0] for r in cur.fetchall()]
        return tickers
    except Exception as e:
        logger.warning("Failed to load from ticker_universe: %s — falling back to API", e)
        return []


def run(days: int = 3, dry_run: bool = False, use_cache: bool = True,
        batch_num: int | None = None, total_batches: int | None = None) -> None:
    logger.info("── US Daily Refresh  days=%d  dry_run=%s  batch=%s/%s ──",
                days, dry_run, batch_num, total_batches)

    # Try ticker_universe table first (database-driven), fall back to API
    tickers = _load_us_from_universe()
    if tickers:
        logger.info("US tickers loaded from ticker_universe: %d", len(tickers))
    else:
        tickers = load_us_tickers(use_cache=use_cache)
        logger.info("US tickers loaded from NASDAQ API: %d", len(tickers))

    # Parallel batch support: split ticker list for parallel DAG workers
    if batch_num is not None and total_batches is not None and total_batches > 1:
        chunk_size = len(tickers) // total_batches + 1
        start = batch_num * chunk_size
        end = min(start + chunk_size, len(tickers))
        tickers = tickers[start:end]
        logger.info("Batch %d/%d: tickers %d–%d (%d tickers)",
                    batch_num, total_batches, start, end - 1, len(tickers))

    period  = _days_to_period(days)
    batches = [tickers[i:i + _BATCH_SIZE] for i in range(0, len(tickers), _BATCH_SIZE)]
    logger.info("Processing %d batches of ≤%d tickers (period=%s)", len(batches), _BATCH_SIZE, period)

    total_rows  = 0
    total_tickers = 0

    for idx, batch in enumerate(batches, 1):
        logger.info("Batch %d/%d  (%d tickers  %s → %s)", idx, len(batches), len(batch), batch[0], batch[-1])
        data = _download_batch_retry(batch, period)

        rows = []
        for sym, df in data.items():
            r = df_to_daily_rows(df, sym, "US", "yahoo")
            rows.extend(r)
            if r:
                total_tickers += 1

        logger.info("  → %d tickers with data, %d rows", len(data), len(rows))

        if rows and not dry_run:
            upsert_daily_rows(rows, f"US daily batch {idx}")
            total_rows += len(rows)

        if idx < len(batches):
            time.sleep(random.uniform(_SLEEP_MIN, _SLEEP_MAX))

    logger.info("US Daily Refresh complete — %d tickers, %d rows upserted%s",
                total_tickers, total_rows, " [DRY RUN]" if dry_run else "")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Daily US OHLCV refresh for datapai.prices")
    p.add_argument("--days", type=int, default=3, help="Trading days to fetch (default: 3)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--batch-num", type=int, default=None, help="Batch index (0-based) for parallel workers")
    p.add_argument("--total-batches", type=int, default=None, help="Total number of parallel workers")
    args = p.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    run(days=args.days, dry_run=args.dry_run, use_cache=not args.no_cache,
        batch_num=args.batch_num, total_batches=args.total_batches)
