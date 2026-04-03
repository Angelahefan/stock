#!/usr/bin/env python3
"""
scripts/refresh_ohlcv_asx.py
─────────────────────────────────────────────────────────────────────────────
Daily delta refresh of OHLCV for ASX stocks.

Cron: 15 6 * * 1-5   (6:15 AM UTC = 4:15 PM AEDT, after ASX closes 4:00 PM AEDT)

Fetches last 3 trading days via yfinance for all ASX tickers (.AX suffix).
Batches of 200 tickers. Sleeps 1.5–3 s between batches.
UPSERT into datapai.prices exchange='ASX' — safe to re-run.

ASX note:
  yfinance .AX tickers return OHLCV in AUD.
  auto_adjust=True: prices adjusted for dividends and splits.
  There is no Polygon equivalent for ASX — yfinance only.

Usage:
    python3 scripts/refresh_ohlcv_asx.py                  # normal run
    python3 scripts/refresh_ohlcv_asx.py --dry-run        # no DB write
    python3 scripts/refresh_ohlcv_asx.py --days 5         # fetch N days
"""
from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib.db_helpers import df_to_daily_rows, upsert_daily_rows, get_conn
from scripts.lib.log_setup import setup_logging
from scripts.lib.ticker_loader import load_asx_tickers

logger = setup_logging("refresh_ohlcv_asx")

_BATCH_SIZE   = 200      # ASX tickers: smaller batches (yfinance can be slower for .AX)
_SLEEP_MIN    = 1.5
_SLEEP_MAX    = 3.0
_MAX_RETRIES  = 3
_BACKOFF_BASE = 2.0
_BACKOFF_MAX  = 60.0


def _days_to_period(days: int) -> str:
    if days <= 5:
        return "5d"
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
                raise ValueError("empty")

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
                logger.error("Gave up: %s", exc)
    return {}


def _load_asx_from_universe() -> list[str]:
    """Load active ASX tickers from datapai.ticker_universe (yf_symbol with .AX suffix)."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT yf_symbol FROM datapai.ticker_universe
                    WHERE exchange = 'ASX' AND is_active = TRUE
                    ORDER BY ticker
                """)
                tickers = [r[0] for r in cur.fetchall()]
        return tickers
    except Exception as e:
        logger.warning("Failed to load from ticker_universe: %s — falling back to hardcoded", e)
        return []


def _mark_delisted(failed_tickers: list[str]) -> int:
    """Mark tickers as inactive in ticker_universe when yfinance says 'possibly delisted'."""
    if not failed_tickers:
        return 0
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Strip .AX suffix to get base ticker
                base_tickers = [t.replace(".AX", "").upper() for t in failed_tickers]
                cur.execute("""
                    UPDATE datapai.ticker_universe
                    SET is_active = FALSE, source = 'delisted_yf', updated_at = NOW()
                    WHERE exchange = 'ASX' AND ticker = ANY(%s) AND is_active = TRUE
                """, (base_tickers,))
                count = cur.rowcount
            conn.commit()
        if count:
            logger.info("Auto-deactivated %d delisted ASX tickers in ticker_universe", count)
        return count
    except Exception as e:
        logger.warning("Failed to mark delisted tickers: %s", e)
        return 0


def run(days: int = 3, dry_run: bool = False, use_cache: bool = True) -> None:
    logger.info("── ASX Daily Refresh  days=%d  dry_run=%s ──", days, dry_run)

    # Try ticker_universe table first (database-driven), fall back to hardcoded
    tickers = _load_asx_from_universe()
    if tickers:
        logger.info("ASX tickers loaded from ticker_universe: %d (active only)", len(tickers))
    else:
        tickers = load_asx_tickers(use_cache=use_cache)
        logger.info("ASX tickers loaded from hardcoded list: %d", len(tickers))

    period  = _days_to_period(days)
    batches = [tickers[i:i + _BATCH_SIZE] for i in range(0, len(tickers), _BATCH_SIZE)]
    logger.info("Processing %d batches of ≤%d tickers (period=%s)", len(batches), _BATCH_SIZE, period)

    total_rows    = 0
    total_tickers = 0
    all_failed    = []       # collect tickers that yfinance reports as delisted

    for idx, batch in enumerate(batches, 1):
        logger.info(
            "Batch %d/%d  (%d tickers  %s → %s)",
            idx, len(batches), len(batch), batch[0], batch[-1],
        )
        data = _download_batch_retry(batch, period)

        # Detect failed/delisted tickers (in batch but not in data)
        returned = {k.upper() for k in data.keys()}
        for sym in batch:
            if sym.upper() not in returned:
                all_failed.append(sym)

        rows = []
        for sym, df in data.items():
            r = df_to_daily_rows(df, sym, "ASX", "yahoo")
            rows.extend(r)
            if r:
                total_tickers += 1

        logger.info("  → %d tickers with data, %d rows", len(data), len(rows))

        if rows and not dry_run:
            upsert_daily_rows(rows, f"ASX daily batch {idx}")
            total_rows += len(rows)

        if idx < len(batches):
            time.sleep(random.uniform(_SLEEP_MIN, _SLEEP_MAX))

    # Auto-deactivate tickers that consistently fail (likely delisted)
    if all_failed and not dry_run:
        logger.info("Failed tickers (possibly delisted): %d — %s",
                     len(all_failed), ", ".join(all_failed[:20]) + ("..." if len(all_failed) > 20 else ""))
        _mark_delisted(all_failed)

    logger.info("ASX Daily Refresh complete — %d tickers, %d rows upserted, %d failed%s",
                total_tickers, total_rows, len(all_failed), " [DRY RUN]" if dry_run else "")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Daily ASX OHLCV refresh for datapai.prices")
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    args = p.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    run(days=args.days, dry_run=args.dry_run, use_cache=not args.no_cache)
