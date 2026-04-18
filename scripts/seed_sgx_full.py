#!/usr/bin/env python3
"""
seed_sgx_full.py — Full SGX setup using Yahoo Finance.

1. Get all active SGX tickers from Yahoo
2. Seed ticker_universe + stock_directory (en)
3. Backfill 5 years daily OHLCV → datapai.prices
"""
import sys
import time
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.lib.db_helpers import get_conn, upsert_daily_rows
from scripts.lib.log_setup import setup_logging

logger = setup_logging("seed_sgx_full")

# Known SGX ticker codes (alphanumeric, ~700 listed)
# SGX uses short codes like D05, O39, U11, Z74, C6L, A17U
# Common patterns: single letter + 2 digits, or letter + digit + letter/digit + optional U
SGX_KNOWN_CODES = [
    # STI components + large caps
    "D05", "O39", "U11", "Z74", "C6L", "9CI", "A17U", "S58", "BN4", "H78",
    "Y92", "F34", "S63", "V03", "BS6", "M44U", "N2IU", "ME8U", "S68", "CC3",
    "C52", "G13", "U96", "S51", "J36", "C09", "U14", "S08", "T39", "E5H",
    "AWX", "C38U", "J37", "HMN", "SK6U", "BUOU", "AU8U", "K71U", "T82U",
    "UD1U", "AJBU", "CLR", "CY6U", "DHLU", "JYEU", "Q5T", "RW0U", "S56",
    # Popular mid-caps
    "BHK", "AGS", "AIY", "AZR", "BAI", "BCJ", "BDX", "BEC", "BGO", "BKW",
    "BLA", "BMA", "BQF", "BTG", "BTJ", "BTM", "BTP", "BTX", "BVA", "C07",
    "C09", "C2PU", "C31", "C41", "C52", "C61U", "C70", "C76", "C8R", "C9Q",
    "D01", "D03", "D07", "E5H", "EB5", "EMI", "F03", "F10", "F13", "F17",
    "G07", "G13", "G20", "G92", "H02", "H07", "H13", "H15", "H22", "H30",
    "H78", "J69U", "K03", "K6S", "K71U", "L02", "L38", "M01", "M04", "M11",
    "N03", "N21", "NC2", "NO4", "O10", "O32", "O5RU", "OV8", "P15", "P34",
    "P40U", "Q01", "RE4", "RF1U", "RQ1", "S07", "S20", "S23", "S27", "S35",
    "S41", "S43", "S44", "S45", "S56", "S59", "S61", "S69", "S71", "T09",
    "T13", "T14", "T55", "T6I", "T7X", "U06", "U09", "U10", "U13", "U14",
    "U77", "U9E", "VC2", "W05", "X01",
]


def step1_find_valid_tickers():
    """Test which SGX codes are valid on Yahoo Finance."""
    logger.info("Step 1: Scanning %d SGX codes...", len(SGX_KNOWN_CODES))
    unique_codes = list(set(SGX_KNOWN_CODES))
    valid = []

    for i in range(0, len(unique_codes), 10):
        batch = unique_codes[i:i+10]
        syms = [f"{c}.SI" for c in batch]
        try:
            raw = yf.download(" ".join(syms), period="5d", interval="1d",
                              progress=False, group_by="ticker", threads=False)
            if raw is not None and not raw.empty:
                avail = set(raw.columns.get_level_values(0))
                for s in syms:
                    su = s.upper()
                    if su in avail:
                        df = raw[su]
                        if hasattr(df.columns, "get_level_values"):
                            try: df.columns = df.columns.get_level_values(-1)
                            except: pass
                        if "Close" in df.columns and df["Close"].dropna().shape[0] > 0:
                            valid.append(s.replace(".SI", ""))
        except Exception as e:
            if "RateLimit" in str(e) or "429" in str(e):
                logger.warning("Rate limited, sleeping 60s...")
                time.sleep(180)
        time.sleep(5)

    logger.info("Found %d valid SGX tickers", len(valid))
    return valid


def step2_seed_db(valid):
    """Seed ticker_universe + stock_directory."""
    from psycopg2.extras import execute_values
    logger.info("Step 2: Seeding %d tickers...", len(valid))

    tu_rows = [(t, f"{t}.SI", "SGX", True, False) for t in valid]

    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO datapai.ticker_universe (ticker, yf_symbol, exchange, is_active, is_featured)
                VALUES %s
                ON CONFLICT (ticker, exchange) DO UPDATE SET yf_symbol = EXCLUDED.yf_symbol, is_active = true
            """, tu_rows)
            logger.info("  ticker_universe: %d rows", len(tu_rows))

    # Fetch company names from Yahoo
    dir_rows = []
    for i, code in enumerate(valid):
        try:
            t = yf.Ticker(f"{code}.SI")
            info = t.info
            name = info.get("longName") or info.get("shortName") or code
            sector = info.get("sector")
            dir_rows.append((code, name, "SGX", sector, "en"))
        except:
            pass
        if (i + 1) % 30 == 0 and dir_rows:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    execute_values(cur, """
                        INSERT INTO datapai.stock_directory (symbol, name, exchange, sector, lang)
                        VALUES %s
                        ON CONFLICT (symbol, exchange, lang) DO UPDATE SET
                            name = EXCLUDED.name, sector = COALESCE(EXCLUDED.sector, datapai.stock_directory.sector)
                    """, dir_rows)
            logger.info("  stock_directory: %d/%d", i + 1, len(valid))
            dir_rows = []
        time.sleep(0.5)

    if dir_rows:
        with get_conn() as conn:
            with conn.cursor() as cur:
                execute_values(cur, """
                    INSERT INTO datapai.stock_directory (symbol, name, exchange, sector, lang)
                    VALUES %s
                    ON CONFLICT (symbol, exchange, lang) DO UPDATE SET
                        name = EXCLUDED.name, sector = COALESCE(EXCLUDED.sector, datapai.stock_directory.sector)
                """, dir_rows)

    logger.info("  stock_directory done")


def step3_backfill_prices(valid):
    """Download 5 years daily OHLCV."""
    logger.info("Step 3: Backfilling 5yr prices for %d tickers...", len(valid))
    total = 0

    for i in range(0, len(valid), 20):
        batch = valid[i:i+20]
        syms = [f"{t}.SI" for t in batch]
        sym_map = {f"{t}.SI".upper(): t for t in batch}
        try:
            raw = yf.download(" ".join(syms), period="5y", interval="1d",
                              auto_adjust=True, progress=False, group_by="ticker", threads=False)
            if raw is None or raw.empty:
                continue
            rows = []
            avail = set(raw.columns.get_level_values(0))
            for s in syms:
                su = s.upper()
                if su not in avail:
                    continue
                db_t = sym_map[su]
                df = raw[su]
                if hasattr(df.columns, "get_level_values"):
                    try: df.columns = df.columns.get_level_values(-1)
                    except: pass
                for ts, row in df.iterrows():
                    c = row.get("Close")
                    if c is None: continue
                    cv = float(c)
                    if cv == 0: continue
                    td = ts.strftime("%Y-%m-%d")
                    rows.append((db_t, td, float(row.get("Open") or cv), float(row.get("High") or cv),
                                 float(row.get("Low") or cv), cv, cv, int(row.get("Volume") or 0), "SGX", "yfinance"))
            if rows:
                upsert_daily_rows(rows, batch_label=f"SGX 5y batch {i//20+1}")
                total += len(rows)
        except Exception as e:
            if "RateLimit" in str(e) or "429" in str(e):
                logger.warning("Rate limited, sleeping 60s...")
                time.sleep(180)
        if (i // 20 + 1) % 5 == 0:
            logger.info("  Backfill: %d/%d, %d rows", i + 20, len(valid), total)
        time.sleep(5)

    logger.info("Backfilled %d price rows", total)


def main():
    valid = step1_find_valid_tickers()
    step2_seed_db(valid)
    step3_backfill_prices(valid)
    logger.info("=== ALL DONE ===")


if __name__ == "__main__":
    main()
