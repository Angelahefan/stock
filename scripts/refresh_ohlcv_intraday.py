#!/usr/bin/env python3
"""
scripts/refresh_ohlcv_intraday.py
─────────────────────────────────────────────────────────────────────────────
30-minute intraday bar refresh for monitored universe (~200 tickers).

Cron schedule (EC2, UTC):
  # US market hours 09:30–16:00 ET = 13:30–20:00 UTC
  */30 13-20 * * 1-5   datapai python3 /app/scripts/refresh_ohlcv_intraday.py --exchange US
  # ASX market hours 10:00–16:00 AEDT = 23:00–06:00 UTC (spans midnight)
  */30 23    * * 0-4   datapai python3 /app/scripts/refresh_ohlcv_intraday.py --exchange ASX
  */30 0-6   * * 1-5   datapai python3 /app/scripts/refresh_ohlcv_intraday.py --exchange ASX

Data sources:
  US  → Polygon API (POLYGON_KEY) first, yfinance fallback
  ASX → yfinance only (Polygon doesn't cover ASX)

Writes to datapai.ohlcv_intraday.
Purges rows older than 60 days at end of each run.

Usage:
    python3 scripts/refresh_ohlcv_intraday.py --exchange US
    python3 scripts/refresh_ohlcv_intraday.py --exchange ASX
    python3 scripts/refresh_ohlcv_intraday.py --exchange US --dry-run
    python3 scripts/refresh_ohlcv_intraday.py --exchange US --tickers AAPL,MSFT,NVDA
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib.db_helpers import (
    df_to_intraday_rows,
    purge_old_intraday,
    upsert_intraday_rows,
)
from scripts.lib.log_setup import setup_logging
from scripts.lib.ticker_loader import load_monitored_tickers

logger = setup_logging("refresh_ohlcv_intraday")

_SLEEP_BETWEEN = 0.5    # seconds between ticker requests (intraday = individual calls)
_MAX_RETRIES   = 3
_BACKOFF_BASE  = 2.0
_BACKOFF_MAX   = 30.0
_PURGE_DAYS    = 60


# ── Polygon ───────────────────────────────────────────────────────────────────

_POLYGON_KEY = os.getenv("POLYGON_KEY") or os.getenv("POLYGON_API_KEY")
_POLYGON_BASE = "https://api.polygon.io/v2/aggs/ticker"


def _polygon_30m(ticker: str, lookback_days: int = 2) -> Optional[pd.DataFrame]:
    """
    Fetch 30m bars from Polygon for a US ticker.
    Returns DataFrame[Open,High,Low,Close,Volume] with UTC DatetimeIndex.
    Returns None on any error.
    """
    if not _POLYGON_KEY:
        return None

    now  = datetime.now(timezone.utc)
    from_dt = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    to_dt   = now.strftime("%Y-%m-%d")

    url = (
        f"{_POLYGON_BASE}/{ticker.upper()}/range/30/minute/{from_dt}/{to_dt}"
        f"?adjusted=true&sort=asc&limit=1000&apiKey={_POLYGON_KEY}"
    )

    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 429:
            logger.warning("Polygon rate limit — sleeping 10s")
            time.sleep(10)
            resp = requests.get(url, timeout=15)

        resp.raise_for_status()
        data = resp.json()
        results = data.get("results")
        if not results:
            return None

        df = pd.DataFrame(results)
        df["ts"] = pd.to_datetime(df["t"], unit="ms", utc=True)
        df = df.set_index("ts")
        df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        df = df[["open", "high", "low", "close", "volume"]]
        return df

    except Exception as exc:
        logger.warning("Polygon 30m failed for %s: %s", ticker, exc)
        return None


# ── yfinance 30m ──────────────────────────────────────────────────────────────

def _yahoo_30m(ticker_with_suffix: str, lookback_days: int = 2) -> Optional[pd.DataFrame]:
    """
    Fetch 30m bars from yfinance.
    yfinance limits 30m history to ~60 days.
    """
    try:
        raw = yf.download(
            ticker_with_suffix,
            period=f"{min(lookback_days, 5)}d",
            interval="30m",
            auto_adjust=True,
            prepost=False,
            progress=False,
            threads=False,
        )
        if raw is None or raw.empty:
            return None

        # Flatten MultiIndex if present
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        raw.columns = [c.lower() for c in raw.columns]
        return raw

    except Exception as exc:
        logger.warning("yfinance 30m failed for %s: %s", ticker_with_suffix, exc)
        return None


# ── Per-ticker fetch with fallback ────────────────────────────────────────────

def fetch_30m(ticker: str, exchange: str, lookback_days: int = 2) -> Optional[pd.DataFrame]:
    """
    Fetch 30m bars — Polygon first (US only), yfinance fallback.
    ticker: full symbol including .AX suffix if ASX.
    """
    if exchange == "US":
        # Polygon is clean, reliable, and already paid for
        df = _polygon_30m(ticker, lookback_days)
        if df is not None and not df.empty:
            return df
        logger.debug("Polygon returned nothing for %s — falling back to yfinance", ticker)

    # yfinance for ASX (and US fallback)
    return _yahoo_30m(ticker, lookback_days)


# ── Main ──────────────────────────────────────────────────────────────────────

def run(
    exchange: str,
    tickers: Optional[list[str]] = None,
    lookback_days: int = 2,
    dry_run: bool = False,
) -> None:
    logger.info("── Intraday Refresh  exchange=%s  dry_run=%s ──", exchange, dry_run)

    if tickers:
        universe = tickers
        logger.info("Using CLI-specified tickers: %d", len(universe))
    else:
        universe = load_monitored_tickers(exchange=exchange)
        logger.info("Monitored tickers for %s: %d", exchange, len(universe))

    if not universe:
        logger.warning("No tickers to process — exiting")
        return

    total_rows    = 0
    total_tickers = 0
    failed        = []

    for i, ticker in enumerate(universe):
        # Determine source and suffix
        if exchange == "ASX" and not ticker.endswith(".AX"):
            ticker_full = f"{ticker}.AX"
        else:
            ticker_full = ticker

        source = "polygon" if exchange == "US" and _POLYGON_KEY else "yahoo"

        # Retry loop
        df = None
        for attempt in range(_MAX_RETRIES):
            df = fetch_30m(ticker_full, exchange, lookback_days)
            if df is not None and not df.empty:
                break
            if attempt < _MAX_RETRIES - 1:
                wait = min(_BACKOFF_BASE ** (attempt + 1), _BACKOFF_MAX)
                logger.debug("Retry %d for %s in %.1fs", attempt + 1, ticker_full, wait)
                time.sleep(wait)

        if df is None or df.empty:
            logger.warning("No 30m data for %s", ticker_full)
            failed.append(ticker_full)
            continue

        rows = df_to_intraday_rows(df, ticker_full, exchange, source)
        if rows:
            if not dry_run:
                upsert_intraday_rows(rows, ticker_full)
                total_rows += len(rows)
            total_tickers += 1

        # Rate-limit sleep (Polygon: don't hammer; yfinance: be polite)
        if i < len(universe) - 1:
            time.sleep(_SLEEP_BETWEEN)

    # Purge old bars
    if not dry_run:
        purge_old_intraday(days=_PURGE_DAYS)

    logger.info(
        "Intraday Refresh complete — exchange=%s  tickers=%d  rows=%d%s",
        exchange, total_tickers, total_rows, " [DRY RUN]" if dry_run else "",
    )
    if failed:
        logger.warning("No data for %d tickers: %s", len(failed), failed[:10])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="30m intraday bar refresh for monitored universe")
    p.add_argument("--exchange", required=True)
    p.add_argument("--tickers", default="", help="Comma-separated override ticker list")
    p.add_argument("--days", type=int, default=2, help="Lookback days (default: 2)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    override_tickers = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if args.tickers else None
    )

    run(
        exchange=args.exchange,
        tickers=override_tickers,
        lookback_days=args.days,
        dry_run=args.dry_run,
    )
