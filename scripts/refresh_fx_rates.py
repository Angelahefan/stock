#!/usr/bin/env python3
"""
scripts/refresh_fx_rates.py
─────────────────────────────────────────────────────────────────────────────
Fetches daily FX rates from Yahoo Finance and stores in datapai.fx_rates_daily.

All rates are stored as USD base: 1 USD = X local currency.
GBX (pence) is computed as GBP rate * 100.

Usage:
    python3 scripts/refresh_fx_rates.py                 # last 5 days
    python3 scripts/refresh_fx_rates.py --period 1y     # backfill 1 year
    python3 scripts/refresh_fx_rates.py --dry-run       # show without saving
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib.db_helpers import get_conn
from scripts.lib.log_setup import setup_logging

logger = logging.getLogger(__name__)

# ── Yahoo FX tickers ─────────────────────────────────────────────────────────
# These give us: 1 <CURRENCY> = X USD (inverted from what we want)
# We invert to get: 1 USD = X <CURRENCY>
#
# For pairs like AUDUSD=X, Yahoo gives "1 AUD = X USD"
# We want "1 USD = X AUD", so we invert: rate = 1 / yahoo_rate
#
# Exception: for pairs like USDVND=X, Yahoo gives "1 USD = X VND" directly.

YAHOO_PAIRS = {
    "AUDUSD=X":  {"quote": "AUD", "invert": True},
    "HKDUSD=X":  {"quote": "HKD", "invert": True},
    "CNY=X":     {"quote": "CNY", "invert": False},   # USDCNY
    "VND=X":     {"quote": "VND", "invert": False},   # USDVND
    "THB=X":     {"quote": "THB", "invert": False},   # USDTHB
    "MYR=X":     {"quote": "MYR", "invert": False},   # USDMYR
    "IDR=X":     {"quote": "IDR", "invert": False},   # USDIDR
    "GBPUSD=X":  {"quote": "GBP", "invert": True},
    "JPY=X":     {"quote": "JPY", "invert": False},   # USDJPY
    "TWD=X":     {"quote": "TWD", "invert": False},   # USDTWD
    "SGD=X":     {"quote": "SGD", "invert": False},   # USDSGD
}


def fetch_fx_rates(period: str = "5d") -> pd.DataFrame:
    """Download FX rates from Yahoo Finance and normalize to USD base."""
    tickers = list(YAHOO_PAIRS.keys())
    logger.info(f"Downloading FX rates for {len(tickers)} pairs, period={period}")

    # Download all at once
    raw = yf.download(tickers, period=period, auto_adjust=True, progress=False)

    if raw.empty:
        logger.warning("No FX data returned from Yahoo Finance")
        return pd.DataFrame()

    rows = []

    for yahoo_ticker, meta in YAHOO_PAIRS.items():
        quote_currency = meta["quote"]
        invert = meta["invert"]

        try:
            # yf.download with multiple tickers returns MultiIndex columns
            if isinstance(raw.columns, pd.MultiIndex):
                closes = raw[("Close", yahoo_ticker)].dropna()
            else:
                closes = raw["Close"].dropna()

            for date_idx, rate_val in closes.items():
                rate = float(rate_val)
                if rate <= 0:
                    continue

                # Convert to USD base: 1 USD = X local currency
                usd_rate = (1.0 / rate) if invert else rate
                trade_date = pd.Timestamp(date_idx).strftime("%Y-%m-%d")

                rows.append({
                    "base_currency": "USD",
                    "quote_currency": quote_currency,
                    "rate": round(usd_rate, 6),
                    "trade_date": trade_date,
                    "source": "yahoo",
                })

                # Also compute GBX = GBP * 100 (pence)
                if quote_currency == "GBP":
                    rows.append({
                        "base_currency": "USD",
                        "quote_currency": "GBX",
                        "rate": round(usd_rate * 100, 4),
                        "trade_date": trade_date,
                        "source": "yahoo",
                    })

        except Exception as e:
            logger.warning(f"Failed to process {yahoo_ticker}: {e}")
            continue

    # Add USD→USD = 1.0 for every date
    if rows:
        dates = sorted(set(r["trade_date"] for r in rows))
        for d in dates:
            rows.append({
                "base_currency": "USD",
                "quote_currency": "USD",
                "rate": 1.0,
                "trade_date": d,
                "source": "static",
            })

    df = pd.DataFrame(rows)
    logger.info(f"Fetched {len(df)} FX rate rows for {df['quote_currency'].nunique()} currencies")
    return df


def upsert_fx_rates(df: pd.DataFrame) -> int:
    """Upsert FX rates into datapai.fx_rates_daily."""
    if df.empty:
        return 0

    count = 0
    with get_conn() as conn:
        cur = conn.cursor()
        try:
            for _, row in df.iterrows():
                cur.execute("""
                    INSERT INTO datapai.fx_rates_daily (base_currency, quote_currency, rate, trade_date, source)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (base_currency, quote_currency, trade_date)
                    DO UPDATE SET rate = EXCLUDED.rate, source = EXCLUDED.source
                """, (row["base_currency"], row["quote_currency"], row["rate"], row["trade_date"], row["source"]))
                count += 1
            logger.info(f"Upserted {count} FX rate rows")
        finally:
            cur.close()

    return count


def main():
    parser = argparse.ArgumentParser(description="Refresh FX rates from Yahoo Finance")
    parser.add_argument("--period", default="5d",
                        help="yfinance period: 5d, 1mo, 3mo, 6mo, 1y, 2y, max")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and display without saving to DB")
    args = parser.parse_args()

    setup_logging("refresh_fx_rates")

    df = fetch_fx_rates(period=args.period)
    if df.empty:
        logger.error("No FX data fetched. Exiting.")
        sys.exit(1)

    if args.dry_run:
        print(df.to_string(index=False))
        print(f"\n{len(df)} rows (dry-run, not saved)")
        return

    count = upsert_fx_rates(df)
    logger.info(f"Done. {count} rows upserted to datapai.fx_rates_daily")


if __name__ == "__main__":
    main()
