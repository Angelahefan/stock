#!/usr/bin/env python3
"""
Seed HKEX tickers from scan results (produced by scan_hkex.py on EC2).

Reads /tmp/hkex_valid_tickers.json and enriches with company names from yfinance,
then upserts into ticker_universe + stock_directory.

Usage (on EC2):
    PGHOST=localhost PGUSER=postgres PGPASSWORD=postgres python3 seed_hkex_from_scan.py
"""
import json
import os
import sys
import time

import psycopg2
import psycopg2.extras
import yfinance as yf


def get_company_name(yf_symbol: str) -> str:
    """Try to get company name from yfinance. Returns ticker code if fails."""
    try:
        tk = yf.Ticker(yf_symbol)
        info = tk.info or {}
        name = info.get("longName") or info.get("shortName") or ""
        if name:
            return name[:200]
    except Exception:
        pass
    return yf_symbol.replace(".HK", "")


def main():
    scan_file = "/tmp/hkex_valid_tickers.json"
    if not os.path.exists(scan_file):
        print(f"ERROR: {scan_file} not found. Run scan_hkex.py first.")
        sys.exit(1)

    with open(scan_file) as f:
        valid_tickers = json.load(f)

    print(f"Loading {len(valid_tickers)} valid HKEX tickers from scan results")

    # Check what we already have in DB
    conn = psycopg2.connect(
        host=os.environ.get('PGHOST', 'localhost'),
        port=int(os.environ.get('PGPORT', '5432')),
        dbname=os.environ.get('PGDATABASE', 'postgres'),
        user=os.environ.get('PGUSER', 'postgres'),
        password=os.environ.get('PGPASSWORD', 'postgres'),
    )

    with conn.cursor() as cur:
        cur.execute("SELECT ticker FROM datapai.ticker_universe WHERE exchange = 'HKEX'")
        existing = {r[0] for r in cur.fetchall()}

    new_tickers = {sym: price for sym, price in valid_tickers.items() if sym.replace(".HK", "") not in existing}
    print(f"Already in DB: {len(existing)}, New to add: {len(new_tickers)}")

    if not new_tickers:
        print("Nothing new to add.")
        conn.close()
        return

    # Enrich with company names (batch — slow but one-time)
    print(f"Enriching {len(new_tickers)} new tickers with company names...")
    enriched = {}
    for i, (sym, price) in enumerate(new_tickers.items()):
        code = sym.replace(".HK", "")
        name = get_company_name(sym)
        enriched[code] = {"yf_symbol": sym, "name": name, "price": price}
        if (i + 1) % 50 == 0:
            print(f"  Enriched {i + 1}/{len(new_tickers)}")
            time.sleep(1)  # rate limit

    # Upsert into DB
    with conn.cursor() as cur:
        # 1. ticker_universe
        rows = [
            (code, 'HKEX', data['yf_symbol'], data['name'], True, 'yfinance_scan')
            for code, data in enriched.items()
        ]
        psycopg2.extras.execute_values(cur, """
            INSERT INTO datapai.ticker_universe (ticker, exchange, yf_symbol, company_name, is_active, source)
            VALUES %s
            ON CONFLICT (ticker, exchange) DO UPDATE SET
                yf_symbol = EXCLUDED.yf_symbol,
                company_name = EXCLUDED.company_name,
                is_active = EXCLUDED.is_active,
                source = EXCLUDED.source,
                updated_at = NOW()
        """, rows, page_size=200)
        print(f"Upserted {len(rows)} tickers into ticker_universe")

        # 2. stock_directory (English names)
        dir_rows = [(code, data['name'], 'HKEX', 'en') for code, data in enriched.items()]
        psycopg2.extras.execute_values(cur, """
            INSERT INTO datapai.stock_directory (symbol, name, exchange, lang)
            VALUES %s
            ON CONFLICT (symbol, exchange, lang) DO UPDATE SET name = EXCLUDED.name
        """, dir_rows, page_size=200)
        print(f"Upserted {len(dir_rows)} rows into stock_directory")

        conn.commit()
    conn.close()

    print(f"Done! Total HKEX tickers now: {len(existing) + len(enriched)}")


if __name__ == '__main__':
    main()
