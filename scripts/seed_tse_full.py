#!/usr/bin/env python3
"""
seed_tse_full.py — Full TSE (Japan) setup using Yahoo Finance.
Discovers active tickers, seeds DB, backfills 5 years daily OHLCV.
Slow batches (10 tickers, 5s sleep) to avoid Yahoo rate limits.
"""
import sys
import time
from pathlib import Path
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.lib.db_helpers import get_conn, upsert_daily_rows
from scripts.lib.log_setup import setup_logging

logger = setup_logging("seed_tse_full")

# Major TSE ticker ranges (4-digit codes)
# Prime Market: 1000-9999 (most active between 1300-9990)
TSE_RANGES = [
    (1301, 1450), (1500, 1600), (1700, 1900), (1900, 2000),
    (2100, 2300), (2400, 2600), (2700, 2900), (2900, 3100),
    (3100, 3400), (3400, 3600), (3600, 3900), (3900, 4100),
    (4100, 4300), (4300, 4600), (4600, 4800), (4900, 5100),
    (5100, 5400), (5700, 5900), (6000, 6200), (6200, 6400),
    (6400, 6600), (6700, 6900), (6900, 7200), (7200, 7500),
    (7700, 8000), (8000, 8300), (8300, 8600), (8600, 8800),
    (9000, 9200), (9400, 9600), (9600, 9800), (9900, 10000),
]


def scan_valid_tickers():
    all_codes = []
    for s, e in TSE_RANGES:
        all_codes.extend(range(s, e))
    logger.info("Scanning %d potential TSE codes...", len(all_codes))
    valid = []
    for i in range(0, len(all_codes), 10):
        batch = [f"{c}.T" for c in all_codes[i:i+10]]
        try:
            raw = yf.download(" ".join(batch), period="5d", interval="1d",
                              progress=False, group_by="ticker", threads=False)
            if raw is not None and not raw.empty:
                avail = set(raw.columns.get_level_values(0))
                for s in batch:
                    su = s.upper()
                    if su in avail:
                        df = raw[su]
                        if hasattr(df.columns, "get_level_values"):
                            try: df.columns = df.columns.get_level_values(-1)
                            except: pass
                        if "Close" in df.columns and df["Close"].dropna().shape[0] > 0:
                            valid.append(s.replace(".T", ""))
        except Exception as e:
            if "RateLimit" in str(e) or "429" in str(e):
                logger.warning("Rate limited at %d, sleeping 180s...", i)
                time.sleep(180)
        if (i // 10) % 20 == 0:
            logger.info("  Scanned %d/%d, found %d valid", i, len(all_codes), len(valid))
        time.sleep(5)
    logger.info("Found %d valid TSE tickers", len(valid))
    return valid


def seed_db(valid):
    from psycopg2.extras import execute_values
    logger.info("Seeding %d tickers...", len(valid))
    tu_rows = [(t, f"{t}.T", "TSE", True, False) for t in valid]
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO datapai.ticker_universe (ticker, yf_symbol, exchange, is_active, is_featured)
                VALUES %s ON CONFLICT (ticker, exchange) DO UPDATE SET yf_symbol = EXCLUDED.yf_symbol, is_active = true
            """, tu_rows)
    logger.info("  ticker_universe: %d rows", len(tu_rows))

    # Fetch company names
    dir_rows = []
    for i, code in enumerate(valid):
        try:
            t = yf.Ticker(f"{code}.T")
            info = t.info
            name = info.get("longName") or info.get("shortName") or code
            sector = info.get("sector")
            dir_rows.append((code, name, "TSE", sector, "en"))
            dir_rows.append((code, name, "TSE", sector, "ja"))
            dir_rows.append((code, name, "TSE", sector, "zh"))
            dir_rows.append((code, name, "TSE", sector, "zh-TW"))
        except:
            pass
        if (i + 1) % 50 == 0 and dir_rows:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    execute_values(cur, """
                        INSERT INTO datapai.stock_directory (symbol, name, exchange, sector, lang)
                        VALUES %s ON CONFLICT (symbol, exchange, lang) DO UPDATE SET
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
                    VALUES %s ON CONFLICT (symbol, exchange, lang) DO UPDATE SET
                        name = EXCLUDED.name, sector = COALESCE(EXCLUDED.sector, datapai.stock_directory.sector)
                """, dir_rows)


def backfill_prices(valid):
    logger.info("Backfilling 5yr prices for %d tickers...", len(valid))
    total = 0
    for i in range(0, len(valid), 20):
        batch = valid[i:i+20]
        syms = [f"{t}.T" for t in batch]
        sym_map = {f"{t}.T".upper(): t for t in batch}
        try:
            raw = yf.download(" ".join(syms), period="5y", interval="1d",
                              auto_adjust=True, progress=False, group_by="ticker", threads=False)
            if raw is None or raw.empty: continue
            rows = []
            avail = set(raw.columns.get_level_values(0))
            for s in syms:
                su = s.upper()
                if su not in avail: continue
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
                                 float(row.get("Low") or cv), cv, cv, int(row.get("Volume") or 0), "TSE", "yfinance"))
            if rows:
                upsert_daily_rows(rows, batch_label=f"TSE 5y batch {i//20+1}")
                total += len(rows)
        except Exception as e:
            if "RateLimit" in str(e) or "429" in str(e):
                logger.warning("Rate limited, sleeping 180s...")
                time.sleep(180)
        if (i // 20 + 1) % 10 == 0:
            logger.info("  Backfill: %d/%d, %d rows", i + 20, len(valid), total)
        time.sleep(5)
    logger.info("Backfilled %d price rows", total)


def main():
    valid = scan_valid_tickers()
    seed_db(valid)
    backfill_prices(valid)
    logger.info("=== ALL DONE ===")


if __name__ == "__main__":
    main()
