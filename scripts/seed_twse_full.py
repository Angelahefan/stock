#!/usr/bin/env python3
"""
seed_twse_full.py — Full TWSE setup using FinMind API (free, no rate limit).

1. Get ALL active TWSE tickers + company names from FinMind
2. Seed ticker_universe + stock_directory (en, zh-TW, zh)
3. Backfill 5 years daily OHLCV from FinMind → datapai.prices
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.lib.db_helpers import get_conn, upsert_daily_rows
from scripts.lib.log_setup import setup_logging

logger = setup_logging("seed_twse_full")

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"


def finmind_get(dataset, **params):
    """Fetch from FinMind API."""
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{FINMIND_BASE}?dataset={dataset}&{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read().decode("utf-8"))


def step1_get_all_tickers():
    """Get all TWSE tickers + Chinese names from FinMind."""
    logger.info("Step 1: Fetching all TWSE tickers from FinMind...")
    data = finmind_get("TaiwanStockInfo")
    stocks = data.get("data", [])
    # Filter to TWSE listed (type=twse), exclude ETFs and special securities
    twse = [s for s in stocks if s.get("type") == "twse"
            and len(s.get("stock_id", "")) == 4
            and s["stock_id"].isdigit()]
    logger.info("Found %d TWSE tickers", len(twse))
    return twse


def step2_seed_db(tickers):
    """Seed ticker_universe + stock_directory."""
    from psycopg2.extras import execute_values
    logger.info("Step 2: Seeding %d tickers into DB...", len(tickers))

    # Deduplicate by stock_id (FinMind may return duplicates)
    seen = set()
    unique_tickers = []
    for t in tickers:
        if t["stock_id"] not in seen:
            seen.add(t["stock_id"])
            unique_tickers.append(t)
    logger.info("  Deduped: %d → %d unique tickers", len(tickers), len(unique_tickers))
    tickers = unique_tickers

    tu_rows = [(t["stock_id"], f"{t['stock_id']}.TW", "TWSE", True, False) for t in tickers]
    dir_rows = []
    for t in tickers:
        sid = t["stock_id"]
        name_zh = t.get("stock_name", sid)
        sector = t.get("industry_category", None)
        dir_rows.append((sid, name_zh, "TWSE", sector, "zh-TW"))
        dir_rows.append((sid, name_zh, "TWSE", sector, "zh"))
        dir_rows.append((sid, name_zh, "TWSE", sector, "en"))

    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO datapai.ticker_universe (ticker, yf_symbol, exchange, is_active, is_featured)
                VALUES %s
                ON CONFLICT (ticker, exchange) DO UPDATE SET yf_symbol = EXCLUDED.yf_symbol, is_active = true
            """, tu_rows)
            logger.info("  ticker_universe: %d rows", len(tu_rows))

            execute_values(cur, """
                INSERT INTO datapai.stock_directory (symbol, name, exchange, sector, lang)
                VALUES %s
                ON CONFLICT (symbol, exchange, lang) DO UPDATE SET
                    name = EXCLUDED.name,
                    sector = COALESCE(EXCLUDED.sector, datapai.stock_directory.sector)
            """, dir_rows)
            logger.info("  stock_directory: %d rows", len(dir_rows))


def step3_backfill_prices(tickers):
    """Backfill 5 years daily OHLCV from FinMind."""
    logger.info("Step 3: Backfilling 5yr prices for %d tickers...", len(tickers))
    total = 0

    for i, t in enumerate(tickers):
        sid = t["stock_id"]
        try:
            data = finmind_get("TaiwanStockPrice", data_id=sid,
                               start_date="2021-03-31", end_date="2026-03-31")
            bars = data.get("data", [])
            if not bars:
                continue

            rows = []
            for b in bars:
                c = float(b.get("close", 0))
                if c == 0:
                    continue
                rows.append((
                    sid, b["date"],
                    float(b.get("open") or c),
                    float(b.get("max") or c),
                    float(b.get("min") or c),
                    c, c,
                    int(b.get("Trading_Volume") or 0),
                    "TWSE", "finmind",
                ))

            if rows:
                upsert_daily_rows(rows, batch_label=f"TWSE {sid}")
                total += len(rows)

        except Exception as e:
            logger.warning("  %s failed: %s", sid, e)

        if (i + 1) % 50 == 0:
            logger.info("  Progress: %d/%d tickers, %d rows", i + 1, len(tickers), total)
            time.sleep(1)

    logger.info("Backfilled %d price rows total", total)


def main():
    tickers = step1_get_all_tickers()
    step2_seed_db(tickers)
    step3_backfill_prices(tickers)
    logger.info("=== ALL DONE ===")


if __name__ == "__main__":
    main()
