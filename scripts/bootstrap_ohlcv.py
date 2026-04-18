#!/usr/bin/env python3
"""
scripts/bootstrap_ohlcv.py
─────────────────────────────────────────────────────────────────────────────
One-time bulk load of 5-year daily OHLCV for ~9,000 US + ASX stocks.

Strategy (anti-block / rate-limit safe):
  • yfinance multi-ticker batch download — fewer HTTP connections
  • Batch size 200 tickers → ~45 batches per exchange
  • Random sleep 2–5 s between batches (jitter avoids pattern detection)
  • Exponential backoff (2x, max 120s) on any fetch failure
  • --resume flag: skips tickers already in DB (idempotent re-runs)
  • Progress saved to cache/bootstrap_progress.json — survives interruptions

Usage:
    # Full bootstrap (first run)
    python3 scripts/bootstrap_ohlcv.py

    # Only US stocks
    python3 scripts/bootstrap_ohlcv.py --exchanges US

    # Only ASX stocks
    python3 scripts/bootstrap_ohlcv.py --exchanges ASX

    # Resume after interruption (skips already-loaded tickers)
    python3 scripts/bootstrap_ohlcv.py --resume

    # Custom history window
    python3 scripts/bootstrap_ohlcv.py --years 3

    # Dry-run (download but don't write to DB)
    python3 scripts/bootstrap_ohlcv.py --dry-run

    # Force refresh ticker list from API
    python3 scripts/bootstrap_ohlcv.py --no-cache

Env vars (same as agents/stock_chat/db.py):
    DATAPAI_PG_HOST / PG_PORT / PG_DB / PG_USER / PG_PASSWORD
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib.db_helpers import (
    df_to_daily_rows,
    get_conn,
    get_latest_dates,
    upsert_daily_rows,
)
from scripts.lib.log_setup import setup_logging, get_log_path
from scripts.lib.ticker_loader import load_asx_tickers, load_us_tickers, load_vietnam_tickers

logger = setup_logging("bootstrap_ohlcv")

# ── Config ────────────────────────────────────────────────────────────────────
_CACHE_DIR      = Path(__file__).parent / "cache"
_CACHE_DIR.mkdir(exist_ok=True)
_PROGRESS_FILE  = _CACHE_DIR / "bootstrap_progress.json"

_BATCH_SIZE     = 200      # tickers per yfinance multi-download
_SLEEP_MIN      = 2.0      # minimum sleep between batches (seconds)
_SLEEP_MAX      = 5.0      # maximum sleep between batches (seconds)
_MAX_RETRIES    = 4        # per-batch retries before giving up
_BACKOFF_BASE   = 2.0      # exponential backoff base
_BACKOFF_MAX    = 120.0    # maximum backoff cap (seconds)


# ── yfinance helpers ──────────────────────────────────────────────────────────

def _yf_period(years: int) -> str:
    """Map years → yfinance period string."""
    if years <= 1:
        return "1y"
    if years <= 2:
        return "2y"
    if years <= 5:
        return "5y"
    return "max"


def _download_batch(
    tickers: list[str],
    years: int,
    attempt: int = 0,
) -> dict[str, pd.DataFrame]:
    """
    Download a batch of tickers using yfinance.download() (single HTTP session).

    Returns dict {ticker: DataFrame} or {} on failure.

    Anti-block notes:
      • yfinance.download(group_by='ticker') fetches all in one session
      • auto_adjust=True: returns split/div-adjusted OHLCV — no extra calls
      • progress=False: disables tqdm noise in logs
      • threads=False: avoids parallel requests that trigger rate limits
        (single-threaded is slower but far less likely to get blocked)
    """
    period = _yf_period(years)
    try:
        raw = yf.download(
            tickers=" ".join(tickers),
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            prepost=False,
            progress=False,
            threads=False,       # ← single-threaded: kinder to Yahoo
        )
        if raw is None or raw.empty:
            return {}

        result: dict[str, pd.DataFrame] = {}

        if len(tickers) == 1:
            # Single-ticker: yfinance returns flat columns
            sym = tickers[0].upper()
            result[sym] = raw
        else:
            # Multi-ticker with group_by='ticker':
            #   yfinance >=0.2 returns MultiIndex where level 0 = Ticker, level 1 = Price
            #   Direct access raw[sym] is the most robust approach
            available = set(raw.columns.get_level_values(0))
            for sym in tickers:
                sym_up = sym.upper()
                try:
                    if sym_up in available:
                        df = raw[sym_up]
                        # Flatten if still MultiIndex (e.g. single-Price sub-index)
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.get_level_values(-1)
                        if not df.empty:
                            result[sym_up] = df
                except (KeyError, TypeError):
                    pass

        return result

    except Exception as exc:
        logger.warning("Batch download failed (attempt %d): %s", attempt + 1, exc)
        return {}


def _download_with_retry(
    tickers: list[str],
    years: int,
) -> dict[str, pd.DataFrame]:
    """Retry wrapper with exponential backoff + jitter."""
    for attempt in range(_MAX_RETRIES):
        result = _download_batch(tickers, years, attempt)
        if result:
            return result

        if attempt < _MAX_RETRIES - 1:
            delay = min(_BACKOFF_BASE ** (attempt + 1), _BACKOFF_MAX)
            jitter = random.uniform(0, delay * 0.3)
            wait   = delay + jitter
            logger.warning(
                "Retry %d/%d in %.1fs — batch %s…%s",
                attempt + 1, _MAX_RETRIES - 1,
                wait, tickers[0], tickers[-1],
            )
            time.sleep(wait)

    logger.error("Gave up on batch %s…%s after %d attempts", tickers[0], tickers[-1], _MAX_RETRIES)
    return {}


# ── Progress tracking ─────────────────────────────────────────────────────────

def _load_progress() -> set[str]:
    if _PROGRESS_FILE.exists():
        data = json.loads(_PROGRESS_FILE.read_text())
        return set(data.get("done", []))
    return set()


def _save_progress(done: set[str]) -> None:
    _PROGRESS_FILE.write_text(json.dumps({"done": sorted(done)}))


# ── Main ──────────────────────────────────────────────────────────────────────

def bootstrap(
    exchanges: list[str],
    years: int,
    dry_run: bool,
    resume: bool,
    use_cache: bool,
    ticker_file: str | None = None,
) -> None:
    logger.info("═" * 70)
    logger.info("Log file: %s", get_log_path("bootstrap_ohlcv"))
    logger.info("Bootstrap OHLCV  exchanges=%s  years=%d  dry_run=%s  resume=%s",
                exchanges, years, dry_run, resume)
    logger.info("═" * 70)

    # Load already-completed tickers if resuming
    done_set: set[str] = _load_progress() if resume else set()
    if resume and done_set:
        logger.info("Resume mode: %d tickers already completed, skipping", len(done_set))

    total_rows    = 0
    total_tickers = 0
    failed_tickers: list[str] = []

    for exchange in exchanges:
        logger.info("── Exchange: %s ──────────────────────────────────────", exchange)

        # Load ticker universe
        if ticker_file:
            from scripts.lib.ticker_loader import load_tickers_from_file
            suffix = {"ASX": ".AX", "HOSE": ".VN", "HNX": ".VN", "HKEX": ".HK", "SET": ".BK", "KLSE": ".KL", "IDX": ".JK"}.get(exchange, "")
            tickers = load_tickers_from_file(ticker_file, suffix=suffix)
            logger.info("Tickers from file %s: %d", ticker_file, len(tickers))
        elif exchange == "US":
            tickers = load_us_tickers(use_cache=use_cache)
        elif exchange == "ASX":
            tickers = load_asx_tickers(use_cache=use_cache)
        elif exchange == "HOSE":
            tickers = load_vietnam_tickers(use_cache=use_cache)
        else:
            # Generic: load from ticker_universe DB table (works for HKEX, SET, KLSE, IDX, etc.)
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT yf_symbol FROM datapai.ticker_universe "
                            "WHERE exchange = %s AND is_active = TRUE ORDER BY ticker",
                            (exchange,),
                        )
                        tickers = [r[0] for r in cur.fetchall()]
                if not tickers:
                    logger.warning("No tickers found in ticker_universe for %s — skipping", exchange)
                    continue
                logger.info("Loaded %d tickers from ticker_universe for %s", len(tickers), exchange)
            except Exception as exc:
                logger.error("Failed to load tickers for %s: %s — skipping", exchange, exc)
                continue

        logger.info("Ticker universe for %s: %d tickers", exchange, len(tickers))

        # Optionally get latest dates from DB to skip already-fresh rows
        if resume:
            # Remove already-done tickers
            tickers = [t for t in tickers if t not in done_set]
            logger.info("After resume filter: %d tickers remaining", len(tickers))

        # Split into batches
        batches = [tickers[i:i + _BATCH_SIZE] for i in range(0, len(tickers), _BATCH_SIZE)]
        logger.info("Processing %d batches of ≤%d tickers", len(batches), _BATCH_SIZE)

        for batch_idx, batch in enumerate(batches, 1):
            logger.info(
                "[%s] Batch %d/%d  tickers=%d  (%s → %s)",
                exchange, batch_idx, len(batches), len(batch),
                batch[0], batch[-1],
            )

            data = _download_with_retry(batch, years)

            if not data:
                logger.warning("Empty result for batch %d — adding to failed list", batch_idx)
                failed_tickers.extend(batch)
                continue

            rows = []
            fetched_count = 0
            source = "yahoo"

            for sym, df in data.items():
                ticker_rows = df_to_daily_rows(df, sym, exchange, source)
                rows.extend(ticker_rows)
                if ticker_rows:
                    fetched_count += 1
                    done_set.add(sym)

            logger.info(
                "[%s] Batch %d — got data for %d/%d tickers → %d rows",
                exchange, batch_idx, fetched_count, len(batch), len(rows),
            )

            if rows and not dry_run:
                upsert_daily_rows(rows, f"{exchange} batch {batch_idx}")
                total_rows += len(rows)

            total_tickers += fetched_count

            # Save progress periodically (every 5 batches)
            if batch_idx % 5 == 0:
                _save_progress(done_set)

            # Anti-block sleep between batches
            if batch_idx < len(batches):
                sleep_time = random.uniform(_SLEEP_MIN, _SLEEP_MAX)
                logger.debug("Sleeping %.1fs before next batch...", sleep_time)
                time.sleep(sleep_time)

        # Save progress after each exchange
        _save_progress(done_set)

    # Retry failed tickers individually
    if failed_tickers:
        logger.info("Retrying %d failed tickers individually...", len(failed_tickers))
        for sym in failed_tickers:
            exchange = "ASX" if sym.endswith(".AX") else ("HOSE" if sym.endswith(".VN") else ("HKEX" if sym.endswith(".HK") else ("SET" if sym.endswith(".BK") else ("KLSE" if sym.endswith(".KL") else "US"))))
            data = _download_with_retry([sym], years)
            if data:
                df = data.get(sym.upper()) or next(iter(data.values()), None)
                if df is not None:
                    rows = df_to_daily_rows(df, sym, exchange, "yahoo")
                    if rows and not dry_run:
                        upsert_daily_rows(rows, f"retry {sym}")
                        total_rows += len(rows)
                    total_tickers += 1
                    done_set.add(sym)
            time.sleep(random.uniform(1.0, 3.0))

    _save_progress(done_set)

    logger.info("═" * 70)
    logger.info("Bootstrap complete!")
    logger.info("  Tickers with data : %d", total_tickers)
    logger.info("  Total rows upserted: %d", total_rows)
    if failed_tickers:
        logger.warning("  Failed (gave up)   : %d — see logs", len(failed_tickers))
    if dry_run:
        logger.info("  DRY RUN — no data written to DB")
    logger.info("═" * 70)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bootstrap 5-year daily OHLCV for 9K US + ASX stocks into datapai.prices"
    )
    p.add_argument(
        "--exchanges", default="US,ASX",
        help="Comma-separated exchange list: US,ASX  (default: US,ASX)",
    )
    p.add_argument(
        "--years", type=int, default=5,
        help="Years of history to load (default: 5)",
    )
    p.add_argument(
        "--resume", action="store_true",
        help="Skip tickers already saved in cache/bootstrap_progress.json",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Download data but do not write to DB",
    )
    p.add_argument(
        "--no-cache", action="store_true",
        help="Force-refresh ticker lists from NASDAQ/ASX APIs",
    )
    p.add_argument(
        "--ticker-file", default=None,
        help="Load tickers from a file instead of API (one per line or CSV first column)",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    # Load .env if present (local development)
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    exchanges = [e.strip().upper() for e in args.exchanges.split(",") if e.strip()]

    # Wrap in top-level try/except so ALL crashes are logged to file,
    # not just printed to stderr (which is lost when running inside screen).
    import traceback
    try:
        bootstrap(
            exchanges=exchanges,
            years=args.years,
            dry_run=args.dry_run,
            resume=args.resume,
            use_cache=not args.no_cache,
            ticker_file=args.ticker_file,
        )
    except Exception as e:
        logger.exception("FATAL: bootstrap crashed — %s\n%s", e, traceback.format_exc())
        raise
