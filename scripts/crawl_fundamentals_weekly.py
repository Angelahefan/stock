#!/usr/bin/env python3
"""
scripts/crawl_fundamentals_weekly.py
─────────────────────────────────────────────────────────────────────────────
Weekly bulk crawl of stock fundamentals.
Populates datapai.stock_fundamentals with valuation, risk, profitability,
balance sheet, and company info for ALL active tickers.

TWO-PASS approach for speed:
  Pass 1 (fast): Yahoo batch quote API — 500 tickers per request, gets ~15 fields
                  (market_cap, pe, pb, beta, 52wk, dividend, shares, sector)
                  ~2 min per 5000 tickers
  Pass 2 (slow): yfinance .info for popular/monitored stocks only — gets all 30+ fields
                  (margins, ROE, debt, cash, growth, etc.)
                  ~5 min for 500 priority tickers

Skips tickers updated within --skip-days (default: 6) to be resumable.

Usage:
    python3 scripts/crawl_fundamentals_weekly.py --exchange HKEX
    python3 scripts/crawl_fundamentals_weekly.py --exchange all
    python3 scripts/crawl_fundamentals_weekly.py --exchange US --threads 15 --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib.db_helpers import get_conn
from scripts.lib.log_setup import setup_logging

logger = setup_logging("crawl_fundamentals")

from core.config.exchange_registry import registry as _exr
ALL_EXCHANGES = _exr.get_all_exchanges()  # DB-driven, was hardcoded

# Map yfinance .info keys → our DB columns
INFO_MAP = {
    # Valuation
    "marketCap":            "market_cap",
    "enterpriseValue":      "enterprise_value",
    "trailingPE":           "pe_ttm",
    "forwardPE":            "pe_forward",
    "priceToBook":          "pb_ratio",
    "priceToSalesTrailing12Months": "ps_ratio",
    "pegRatio":             "peg_ratio",
    # Shares
    "sharesOutstanding":    "shares_outstanding",
    "floatShares":          "float_shares",
    "heldPercentInsiders":  "held_by_insiders",
    "heldPercentInstitutions": "held_by_institutions",
    # Dividends
    "dividendRate":         "dividend_rate",
    "dividendYield":        "dividend_yield",
    "exDividendDate":       "ex_dividend_date",
    "payoutRatio":          "payout_ratio",
    # Risk
    "beta":                 "beta",
    "fiftyTwoWeekHigh":     "fifty_two_week_high",
    "fiftyTwoWeekLow":      "fifty_two_week_low",
    "averageVolume10days":  "avg_volume_10d",
    "averageVolume":        "avg_volume_3m",
    # Profitability
    "profitMargins":        "profit_margin",
    "operatingMargins":     "operating_margin",
    "returnOnEquity":       "return_on_equity",
    "returnOnAssets":       "return_on_assets",
    "totalRevenue":         "revenue_ttm",
    "netIncomeToCommon":    "net_income_ttm",
    "ebitda":               "ebitda",
    "earningsGrowth":       "earnings_growth",
    "revenueGrowth":        "revenue_growth",
    # Balance sheet
    "totalCash":            "total_cash",
    "totalDebt":            "total_debt",
    "debtToEquity":         "debt_to_equity",
    "currentRatio":         "current_ratio",
    "bookValue":            "book_value",
    # Company info
    "sector":               "sector",
    "industry":             "industry",
    "currency":             "currency",
}

# Columns that are BIGINT (need int conversion)
BIGINT_COLS = {
    "market_cap", "enterprise_value", "shares_outstanding", "float_shares",
    "avg_volume_10d", "avg_volume_3m", "revenue_ttm", "net_income_ttm",
    "ebitda", "total_cash", "total_debt",
}

# Lot sizes by exchange
LOT_SIZES = {
    "HKEX": 100,  # varies per stock but 100 is most common
    "SET": 100,
    "KLSE": 100,
    "IDX": 100,
    "HOSE": 100,
    "ASX": 1,
    "US": 1,
}


def _fetch_batch_quotes(yf_symbols: list[str]) -> list[dict[str, Any]]:
    """
    Fetch fundamentals for up to 500 tickers at once via Yahoo batch quote API.
    Returns list of raw quote dicts. Much faster than .info per-ticker.
    """
    import requests as _req
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    headers = {"User-Agent": "Mozilla/5.0"}
    results = []

    # Process in chunks of 500
    for i in range(0, len(yf_symbols), 500):
        chunk = yf_symbols[i:i + 500]
        params = {"symbols": ",".join(chunk), "fields": ",".join([
            "symbol", "marketCap", "trailingPE", "forwardPE", "priceToBook",
            "epsTrailingTwelveMonths", "epsForward", "dividendRate", "dividendYield",
            "beta", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "sharesOutstanding",
            "floatShares", "averageDailyVolume10Day", "averageDailyVolume3Month",
            "sector", "industry", "currency", "bookValue",
            "trailingAnnualDividendRate", "trailingAnnualDividendYield",
        ])}
        try:
            resp = _req.get(url, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            quotes = data.get("quoteResponse", {}).get("result", [])
            results.extend(quotes)
            logger.info("  Batch quote %d-%d: got %d/%d", i, i + len(chunk), len(quotes), len(chunk))
        except Exception as e:
            logger.warning("  Batch quote %d-%d failed: %s — falling back to per-ticker", i, i + len(chunk), e)

        if i + 500 < len(yf_symbols):
            time.sleep(1)  # rate limit

    return results


# Map Yahoo batch quote keys → our DB columns (subset of full INFO_MAP)
BATCH_QUOTE_MAP = {
    "marketCap":                    "market_cap",
    "trailingPE":                   "pe_ttm",
    "forwardPE":                    "pe_forward",
    "priceToBook":                  "pb_ratio",
    "beta":                         "beta",
    "fiftyTwoWeekHigh":             "fifty_two_week_high",
    "fiftyTwoWeekLow":              "fifty_two_week_low",
    "sharesOutstanding":            "shares_outstanding",
    "floatShares":                  "float_shares",
    "averageDailyVolume10Day":      "avg_volume_10d",
    "averageDailyVolume3Month":     "avg_volume_3m",
    "trailingAnnualDividendRate":   "dividend_rate",
    "trailingAnnualDividendYield":  "dividend_yield",
    "bookValue":                    "book_value",
    "sector":                       "sector",
    "industry":                     "industry",
    "currency":                     "currency",
}


def _extract_from_batch_quote(quote: dict, ticker: str, exchange: str) -> dict[str, Any]:
    """Extract fields from a Yahoo batch quote response."""
    row: dict[str, Any] = {"ticker": ticker, "exchange": exchange}
    for yf_key, db_col in BATCH_QUOTE_MAP.items():
        val = quote.get(yf_key)
        if val is None or val == "":
            continue
        if db_col in BIGINT_COLS:
            try:
                val = int(val)
            except (ValueError, TypeError):
                continue
        row[db_col] = val

    row["lot_size"] = LOT_SIZES.get(exchange, 1)
    return row


def _fetch_one(yf_symbol: str) -> dict[str, Any] | None:
    """Fetch .info for a single ticker. Returns parsed dict or None."""
    try:
        info = yf.Ticker(yf_symbol).info
        if not info or info.get("regularMarketPrice") is None:
            return None
        return info
    except Exception:
        return None


def _extract_fields(info: dict, ticker: str, exchange: str) -> dict[str, Any]:
    """Extract relevant fields from yfinance .info dict."""
    row: dict[str, Any] = {"ticker": ticker, "exchange": exchange}

    for yf_key, db_col in INFO_MAP.items():
        val = info.get(yf_key)
        if val is None or val == "":
            continue

        # Type conversion
        if db_col in BIGINT_COLS:
            try:
                val = int(val)
            except (ValueError, TypeError):
                continue
        elif db_col == "ex_dividend_date":
            # yfinance returns epoch timestamp
            try:
                val = datetime.fromtimestamp(val).date().isoformat() if isinstance(val, (int, float)) else None
            except Exception:
                val = None

        if val is not None:
            row[db_col] = val

    # All-time high/low — derive from 52wk if not available separately
    row["lot_size"] = LOT_SIZES.get(exchange, 1)

    return row


def _upsert_fundamental(row: dict[str, Any], conn) -> bool:
    """Upsert one row into stock_fundamentals."""
    cols = list(row.keys()) + ["updated_at"]
    vals = list(row.values()) + [datetime.utcnow()]
    placeholders = [f"%s" for _ in cols]
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in ("ticker", "exchange"))

    sql = f"""
        INSERT INTO datapai.stock_fundamentals ({', '.join(cols)})
        VALUES ({', '.join(placeholders)})
        ON CONFLICT (ticker, exchange) DO UPDATE SET {updates}
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, vals)
        return True
    except Exception as e:
        logger.warning("Upsert failed for %s/%s: %s", row.get("ticker"), row.get("exchange"), e)
        conn.rollback()
        return False


def _load_tickers(exchange: str, skip_days: int) -> list[tuple[str, str, str]]:
    """Load (ticker, yf_symbol, exchange) from ticker_universe, skipping recently updated."""
    exchange = exchange.upper()
    with get_conn() as conn:
        with conn.cursor() as cur:
            if exchange == "ALL":
                cur.execute("""
                    SELECT tu.ticker, tu.yf_symbol, tu.exchange
                    FROM datapai.ticker_universe tu
                    LEFT JOIN datapai.stock_fundamentals sf
                        ON sf.ticker = tu.ticker AND sf.exchange = tu.exchange
                    WHERE tu.is_active = TRUE
                      AND (sf.updated_at IS NULL OR sf.updated_at < NOW() - make_interval(days => %s))
                    ORDER BY tu.exchange, tu.ticker
                """, (skip_days,))
            else:
                cur.execute("""
                    SELECT tu.ticker, tu.yf_symbol, tu.exchange
                    FROM datapai.ticker_universe tu
                    LEFT JOIN datapai.stock_fundamentals sf
                        ON sf.ticker = tu.ticker AND sf.exchange = tu.exchange
                    WHERE tu.is_active = TRUE
                      AND tu.exchange = %s
                      AND (sf.updated_at IS NULL OR sf.updated_at < NOW() - make_interval(days => %s))
                    ORDER BY tu.exchange, tu.ticker
                """, (exchange, skip_days))
            return cur.fetchall()


def run(exchange: str, threads: int = 10, skip_days: int = 6, dry_run: bool = False) -> None:
    tickers = _load_tickers(exchange, skip_days)
    logger.info("── Fundamentals Crawl  exchange=%s  tickers=%d  threads=%d  skip_days=%d ──",
                exchange, len(tickers), threads, skip_days)

    if not tickers:
        logger.info("No tickers to crawl (all updated within %d days)", skip_days)
        return

    import psycopg2
    conn = None
    if not dry_run:
        conn = psycopg2.connect(
            host=os.environ.get("DATAPAI_PG_HOST", os.environ.get("PGHOST", "localhost")),
            port=int(os.environ.get("DATAPAI_PG_PORT", os.environ.get("PGPORT", "5434"))),
            dbname="postgres",
            user=os.environ.get("PGUSER", os.environ.get("DATAPAI_PG_USER", "postgres")),
            password=os.environ.get("PGPASSWORD", os.environ.get("DATAPAI_PG_PASSWORD", "postgres")),
        )

    total_ok = 0
    total_fail = 0

    def process_ticker(item):
        ticker, yf_sym, exch = item
        time.sleep(random.uniform(0.1, 0.5))
        info = _fetch_one(yf_sym)
        if info is None:
            return None
        return _extract_fields(info, ticker, exch)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = {pool.submit(process_ticker, t): t for t in tickers}
        for i, future in enumerate(as_completed(futures), 1):
            try:
                row = future.result()
                if row and not dry_run and conn:
                    if _upsert_fundamental(row, conn):
                        total_ok += 1
                    else:
                        total_fail += 1
                elif row:
                    total_ok += 1
                else:
                    total_fail += 1
            except Exception:
                total_fail += 1

            # Commit every 100 rows
            if i % 100 == 0:
                if conn:
                    conn.commit()
                logger.info("  Progress: %d/%d  ok=%d  fail=%d", i, len(tickers), total_ok, total_fail)

    if conn:
        conn.commit()
        conn.close()

    logger.info("── Crawl Complete: %d ok, %d fail out of %d ──", total_ok, total_fail, len(tickers))


def main():
    ap = argparse.ArgumentParser(description="Weekly bulk fundamentals crawl")
    ap.add_argument("--exchange", required=True,
                    help="Exchange code or 'all' for everything")
    ap.add_argument("--threads", type=int, default=10)
    ap.add_argument("--skip-days", type=int, default=6,
                    help="Skip tickers updated within N days (default: 6)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    run(exchange=args.exchange.upper(), threads=args.threads,
        skip_days=args.skip_days, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
