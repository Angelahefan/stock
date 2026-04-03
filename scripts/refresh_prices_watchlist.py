#!/usr/bin/env python3
"""
scripts/refresh_prices_watchlist.py
─────────────────────────────────────────────────────────────────────────────
Refresh daily OHLCV prices for ONLY:
  1. Homepage universe stocks (lib/universe.ts)
  2. All watchlist stocks from all users

Does NOT scan the full 7000+ US stock universe.
Designed to run via Airflow every day after market close.
"""
import sys
import os
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
if (PROJECT_ROOT / ".env.dev").exists():
    load_dotenv(PROJECT_ROOT / ".env.dev")
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("refresh_prices_watchlist")

# Homepage universe (hardcoded to avoid parsing TS)
US_UNIVERSE = [
    "ACMR", "AEHR", "ATRC", "CRVL", "ERII", "FLNC", "GATO", "HIMS",
    "IIIV", "KTOS", "LBRT", "MARA", "MGNI", "MNDY", "NOVA", "NTST",
    "PHAT", "PRTS", "SHYF", "TMDX",
]

ASX_UNIVERSE = [
    "BHP", "CBA", "CSL", "NAB", "ANZ", "WBC", "WES", "MQG", "TLS",
    "WOW", "RIO", "FMG", "TWE", "GMG", "STO", "ORG", "WDS", "QAN",
]


def get_watchlist_tickers():
    """Fetch distinct (symbol, exchange) from all users' watchlists."""
    from scripts.lib.db_helpers import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT symbol, exchange FROM datapai.watchlist")
            return [(row[0], row[1]) for row in cur.fetchall()]


def refresh_prices(tickers: list, exchange: str):
    """Download latest 5d prices from yfinance and upsert into datapai.prices."""
    import yfinance as yf
    from scripts.lib.db_helpers import get_conn

    if not tickers:
        return

    # yfinance needs exchange-specific suffixes
    from core.config.exchange_registry import registry
    yf_map = {}
    for t in tickers:
        suffix = registry.get_suffix(exchange)
        yf_map[f"{t}{suffix}"] = t

    yf_tickers = list(yf_map.keys())
    logger.info("Downloading %d %s tickers: %s", len(yf_tickers), exchange, ", ".join(yf_tickers[:20]))

    try:
        data = yf.download(yf_tickers, period="5d", progress=False, group_by="ticker", threads=True)
    except Exception as e:
        logger.error("yfinance download failed: %s", e)
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            updated = 0

            for yf_ticker, db_ticker in yf_map.items():
                try:
                    if len(yf_tickers) == 1:
                        df = data  # single ticker: no multi-level columns
                    else:
                        if yf_ticker not in data.columns.get_level_values(0):
                            continue
                        df = data[yf_ticker]

                    if df.empty:
                        continue

                    for idx, row in df.iterrows():
                        date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
                        close_val = row.get("Close")
                        vol_val = row.get("Volume")
                        if close_val is None or (hasattr(close_val, '__iter__') and len(close_val) == 0):
                            continue
                        close = float(close_val.iloc[0]) if hasattr(close_val, "iloc") else float(close_val)
                        vol = int(vol_val.iloc[0]) if hasattr(vol_val, "iloc") else int(vol_val) if vol_val is not None else 0

                        # Store ASX tickers with .AX suffix to match existing convention
                        store_ticker = yf_ticker if exchange == "ASX" else db_ticker
                        cur.execute(
                            """INSERT INTO datapai.prices (ticker, trade_date, close, volume)
                               VALUES (%s, %s, %s, %s)
                               ON CONFLICT (ticker, trade_date) DO UPDATE SET close=%s, volume=%s""",
                            (store_ticker, date_str, close, vol, close, vol),
                        )
                        updated += 1

                except Exception as e:
                    logger.warning("Failed to process %s: %s", yf_ticker, str(e)[:200])

    logger.info("Upserted %d price rows for %s exchange", updated, exchange)


def main():
    # Collect all unique tickers
    watchlist = get_watchlist_tickers()
    wl_us = {t for t, ex in watchlist if ex != "ASX"}
    wl_asx = {t for t, ex in watchlist if ex == "ASX"}

    all_us = sorted(set(US_UNIVERSE) | wl_us)
    all_asx = sorted(set(ASX_UNIVERSE) | wl_asx)

    logger.info("Refreshing prices: %d US tickers, %d ASX tickers", len(all_us), len(all_asx))
    logger.info("US: %s", ", ".join(all_us))
    logger.info("ASX: %s", ", ".join(all_asx))

    refresh_prices(all_us, "US")
    refresh_prices(all_asx, "ASX")

    logger.info("Done — all watchlist + universe prices refreshed")


if __name__ == "__main__":
    main()
