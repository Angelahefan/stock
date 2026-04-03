#!/usr/bin/env python3
"""
scripts/refresh_ohlcv_daily.py
─────────────────────────────────────────────────────────────────────────────
Generic daily delta refresh of OHLCV — works for ANY exchange.

Loads tickers from datapai.ticker_universe by exchange, downloads via yfinance,
UPSERTs into datapai.prices. Auto-deactivates delisted tickers.

Usage:
    python3 scripts/refresh_ohlcv_daily.py --exchange HKEX
    python3 scripts/refresh_ohlcv_daily.py --exchange SET --days 5
    python3 scripts/refresh_ohlcv_daily.py --exchange IDX --dry-run
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

# ── Exchange config ─────────────────────────────────────────────────────────
# batch_size: smaller for international markets (yfinance slower with suffixed tickers)
EXCHANGE_CONFIG = {
    "HKEX": {"batch_size": 200, "sleep_min": 1.5, "sleep_max": 3.0},
    "SET":  {"batch_size": 200, "sleep_min": 1.5, "sleep_max": 3.0},
    "KLSE": {"batch_size": 200, "sleep_min": 1.5, "sleep_max": 3.0},
    "IDX":  {"batch_size": 200, "sleep_min": 1.5, "sleep_max": 3.0},
    "HOSE": {"batch_size": 200, "sleep_min": 1.5, "sleep_max": 3.0},
    "ASX":  {"batch_size": 200, "sleep_min": 1.5, "sleep_max": 3.0},
    "US":   {"batch_size": 500, "sleep_min": 1.0, "sleep_max": 2.5},
    "LSE":  {"batch_size": 200, "sleep_min": 1.5, "sleep_max": 3.0},
    "SSE":  {"batch_size": 200, "sleep_min": 1.5, "sleep_max": 3.0},
    "SZSE": {"batch_size": 200, "sleep_min": 1.5, "sleep_max": 3.0},
}

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
                logging.warning("Batch error (attempt %d): %s — retry in %.1fs", attempt + 1, exc, wait)
                time.sleep(wait)
            else:
                logging.error("Gave up: %s", exc)
    return {}


def _load_tickers_from_universe(exchange: str) -> list[str]:
    """Load active tickers from datapai.ticker_universe by exchange (returns yf_symbol)."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT yf_symbol FROM datapai.ticker_universe
                    WHERE exchange = %s AND is_active = TRUE
                    ORDER BY ticker
                """, (exchange,))
                tickers = [r[0] for r in cur.fetchall()]
        return tickers
    except Exception as e:
        logging.error("Failed to load tickers for %s from ticker_universe: %s", exchange, e)
        return []


def _get_yf_suffix(exchange: str) -> str:
    """Return yfinance suffix for an exchange (used to strip when marking delisted)."""
    return {
        "HKEX": ".HK", "SET": ".BK", "KLSE": ".KL", "IDX": ".JK",
        "HOSE": ".VN", "ASX": ".AX", "US": "", "LSE": ".L",
        "SSE": ".SS", "SZSE": ".SZ",
    }.get(exchange, "")


def _mark_delisted(failed_tickers: list[str], exchange: str) -> int:
    """Mark tickers as inactive in ticker_universe when yfinance returns no data."""
    if not failed_tickers:
        return 0
    suffix = _get_yf_suffix(exchange)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                base_tickers = [t.replace(suffix, "").upper() for t in failed_tickers] if suffix else [t.upper() for t in failed_tickers]
                cur.execute("""
                    UPDATE datapai.ticker_universe
                    SET is_active = FALSE, source = 'delisted_yf', updated_at = NOW()
                    WHERE exchange = %s AND ticker = ANY(%s) AND is_active = TRUE
                """, (exchange, base_tickers))
                count = cur.rowcount
            conn.commit()
        if count:
            logging.info("Auto-deactivated %d delisted %s tickers", count, exchange)
        return count
    except Exception as e:
        logging.warning("Failed to mark delisted tickers: %s", e)
        return 0


def run(exchange: str, days: int = 3, dry_run: bool = False) -> None:
    logger = setup_logging(f"refresh_ohlcv_{exchange.lower()}")
    cfg = EXCHANGE_CONFIG.get(exchange, {"batch_size": 200, "sleep_min": 1.5, "sleep_max": 3.0})

    logger.info("── %s Daily Refresh  days=%d  dry_run=%s ──", exchange, days, dry_run)

    tickers = _load_tickers_from_universe(exchange)
    if not tickers:
        logger.error("No tickers found for %s in ticker_universe — aborting", exchange)
        sys.exit(1)

    logger.info("%s tickers loaded from ticker_universe: %d (active)", exchange, len(tickers))

    period  = _days_to_period(days)
    batch_size = cfg["batch_size"]
    batches = [tickers[i:i + batch_size] for i in range(0, len(tickers), batch_size)]
    logger.info("Processing %d batches of ≤%d tickers (period=%s)", len(batches), batch_size, period)

    total_rows    = 0
    total_tickers = 0
    all_failed    = []

    for idx, batch in enumerate(batches, 1):
        logger.info("Batch %d/%d  (%d tickers  %s → %s)",
                     idx, len(batches), len(batch), batch[0], batch[-1])
        data = _download_batch_retry(batch, period)

        # Detect failed/delisted tickers
        returned = {k.upper() for k in data.keys()}
        for sym in batch:
            if sym.upper() not in returned:
                all_failed.append(sym)

        rows = []
        for sym, df in data.items():
            r = df_to_daily_rows(df, sym, exchange, "yahoo")
            rows.extend(r)
            if r:
                total_tickers += 1

        logger.info("  → %d tickers with data, %d rows", len(data), len(rows))

        if rows and not dry_run:
            upsert_daily_rows(rows, f"{exchange} daily batch {idx}")
            total_rows += len(rows)

        if idx < len(batches):
            time.sleep(random.uniform(cfg["sleep_min"], cfg["sleep_max"]))

    # Auto-deactivate tickers that consistently fail
    if all_failed and not dry_run:
        logger.info("Failed tickers (possibly delisted): %d — %s",
                     len(all_failed), ", ".join(all_failed[:20]) + ("..." if len(all_failed) > 20 else ""))
        _mark_delisted(all_failed, exchange)

    logger.info("%s Daily Refresh complete — %d tickers, %d rows upserted, %d failed%s",
                exchange, total_tickers, total_rows, len(all_failed), " [DRY RUN]" if dry_run else "")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Generic daily OHLCV refresh for any exchange")
    p.add_argument("--exchange", required=True, help="Exchange code: HKEX, SET, KLSE, IDX, HOSE, ASX, US")
    p.add_argument("--days", type=int, default=3, help="Trading days to fetch (default: 3)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    run(exchange=args.exchange.upper(), days=args.days, dry_run=args.dry_run)
