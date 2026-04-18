#!/usr/bin/env python3
"""
Seed China A-shares tickers (SSE + SZSE) into datapai.ticker_universe and stock_directory.

SSE (Shanghai Stock Exchange):
  - Main Board: 600xxx.SS, 601xxx.SS, 603xxx.SS
  - STAR Market (科创板): 688xxx.SS
  - Ranges: 600000-605000, 688000-689999

SZSE (Shenzhen Stock Exchange):
  - Main Board: 000xxx.SZ, 001xxx.SZ
  - SME Board: 002xxx.SZ
  - ChiNext (创业板): 300xxx.SZ
  - Ranges: 000001-003999, 300001-301999

Only scans known ranges — NOT brute force!
Uses yfinance to validate tickers and get Chinese company names.

Usage:
    PGHOST=localhost PGUSER=postgres PGPASSWORD=postgres python3 scripts/seed_china_tickers.py [--featured-only]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2
import psycopg2.extras

try:
    import yfinance as yf
except ImportError:
    print("yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

# ── Featured blue chips — always seeded, no scanning needed ──────────────────

# Top 20 SSE blue chips (Shanghai)
FEATURED_SSE = {
    "600519": "贵州茅台",        # Kweichow Moutai
    "601318": "中国平安",        # Ping An Insurance
    "600036": "招商银行",        # China Merchants Bank
    "600276": "恒瑞医药",        # Hengrui Medicine
    "601166": "兴业银行",        # Industrial Bank
    "600900": "长江电力",        # Yangtze Power
    "600887": "伊利股份",        # Yili Group
    "601888": "中国中免",        # China Tourism Group Duty Free
    "600809": "山西汾酒",        # Shanxi Fen Wine
    "600030": "中信证券",        # CITIC Securities
    "601398": "工商银行",        # ICBC
    "601288": "农业银行",        # Agricultural Bank of China
    "601857": "中国石油",        # PetroChina
    "600028": "中国石化",        # Sinopec
    "600585": "海螺水泥",        # Conch Cement
    "601668": "中国建筑",        # China State Construction
    "600031": "三一重工",        # SANY Heavy Industry
    "601012": "隆基绿能",        # LONGi Green Energy
    "688981": "中芯国际",        # SMIC (STAR Market)
    "600050": "中国联通",        # China Unicom
}

# Top 20 SZSE blue chips (Shenzhen)
FEATURED_SZSE = {
    "000858": "五粮液",          # Wuliangye Yibin
    "000333": "美的集团",        # Midea Group
    "002714": "牧原股份",        # Muyuan Foods
    "000001": "平安银行",        # Ping An Bank
    "002594": "比亚迪",          # BYD
    "000651": "格力电器",        # Gree Electric
    "000568": "泸州老窖",        # Luzhou Laojiao
    "002415": "海康威视",        # Hikvision
    "300750": "宁德时代",        # CATL
    "300059": "东方财富",        # East Money Information
    "002304": "洋河股份",        # Yanghe Brewery
    "000002": "万科A",           # China Vanke
    "002352": "顺丰控股",        # SF Holding
    "300760": "迈瑞医疗",        # Mindray Bio-Medical
    "002475": "立讯精密",        # Luxshare Precision
    "000725": "京东方A",         # BOE Technology
    "002230": "科大讯飞",        # iFlytek
    "300124": "汇川技术",        # Inovance Technology
    "002049": "紫光国微",        # Unigroup Guoxin
    "300015": "爱尔眼科",        # Aier Eye Hospital
}

# ── Ticker ranges to scan ───────────────────────────────────────────────────

SSE_RANGES = [
    (600000, 605000),   # Main Board
    (688000, 689999),   # STAR Market
]

SZSE_RANGES = [
    (1, 3999),          # Main Board (000001-003999)
    (300001, 301999),   # ChiNext
]

# English names for featured stocks (fallback if yfinance doesn't return)
FEATURED_EN = {
    "600519": "Kweichow Moutai", "601318": "Ping An Insurance", "600036": "China Merchants Bank",
    "600276": "Hengrui Medicine", "601166": "Industrial Bank", "600900": "Yangtze Power",
    "600887": "Yili Group", "601888": "China Tourism Group Duty Free", "600809": "Shanxi Fen Wine",
    "600030": "CITIC Securities", "601398": "ICBC", "601288": "Agricultural Bank of China",
    "601857": "PetroChina", "600028": "Sinopec", "600585": "Conch Cement",
    "601668": "China State Construction", "600031": "SANY Heavy Industry", "601012": "LONGi Green Energy",
    "688981": "SMIC", "600050": "China Unicom",
    "000858": "Wuliangye Yibin", "000333": "Midea Group", "002714": "Muyuan Foods",
    "000001": "Ping An Bank", "002594": "BYD", "000651": "Gree Electric",
    "000568": "Luzhou Laojiao", "002415": "Hikvision", "300750": "CATL",
    "300059": "East Money Information", "002304": "Yanghe Brewery", "000002": "China Vanke",
    "002352": "SF Holding", "300760": "Mindray Bio-Medical", "002475": "Luxshare Precision",
    "000725": "BOE Technology", "002230": "iFlytek", "300124": "Inovance Technology",
    "002049": "Unigroup Guoxin", "300015": "Aier Eye Hospital",
}


def get_conn():
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", "postgres"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", "postgres"),
    )


def validate_ticker(code: str, suffix: str) -> dict | None:
    """Validate a single ticker via yfinance. Returns info dict or None."""
    yf_symbol = f"{code}{suffix}"
    try:
        tk = yf.Ticker(yf_symbol)
        info = tk.info
        if not info or info.get("regularMarketPrice") is None:
            return None
        name = info.get("shortName") or info.get("longName") or ""
        if not name:
            return None
        return {"code": code, "yf_symbol": yf_symbol, "name": name}
    except Exception:
        return None


def scan_range(start: int, end: int, suffix: str, exchange: str, batch_size: int = 50) -> list[dict]:
    """Scan a range of ticker codes using thread pool."""
    results = []
    codes = []
    for i in range(start, end + 1):
        if suffix == ".SS":
            code = str(i)
        else:  # .SZ — zero-pad to 6 digits
            code = str(i).zfill(6)
        codes.append(code)

    print(f"  Scanning {exchange} range {start}-{end}: {len(codes)} codes...")
    for batch_start in range(0, len(codes), batch_size):
        batch = codes[batch_start:batch_start + batch_size]
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(validate_ticker, c, suffix): c for c in batch}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    results.append(result)
        # Rate limit
        if batch_start + batch_size < len(codes):
            time.sleep(1)
        print(f"    ...scanned {min(batch_start + batch_size, len(codes))}/{len(codes)}, found {len(results)} valid")

    return results


def seed_featured(conn):
    """Seed only the featured blue chips (fast, no scanning)."""
    with conn.cursor() as cur:
        # SSE featured
        sse_rows = []
        sse_dir_rows = []
        for code, cn_name in FEATURED_SSE.items():
            yf_sym = f"{code}.SS"
            en_name = FEATURED_EN.get(code, cn_name)
            sse_rows.append((code, "SSE", yf_sym, en_name, True, "featured"))
            sse_dir_rows.append((code, en_name, "SSE", "en"))
            sse_dir_rows.append((code, cn_name, "SSE", "zh"))
            sse_dir_rows.append((code, cn_name, "SSE", "zh-TW"))

        psycopg2.extras.execute_values(cur, """
            INSERT INTO datapai.ticker_universe (ticker, exchange, yf_symbol, company_name, is_active, source)
            VALUES %s
            ON CONFLICT (ticker, exchange) DO UPDATE SET
                yf_symbol = EXCLUDED.yf_symbol, company_name = EXCLUDED.company_name,
                is_active = EXCLUDED.is_active, updated_at = NOW()
        """, sse_rows, page_size=100)

        psycopg2.extras.execute_values(cur, """
            INSERT INTO datapai.stock_directory (symbol, name, exchange, lang) VALUES %s
            ON CONFLICT (symbol, exchange, lang) DO UPDATE SET name = EXCLUDED.name
        """, sse_dir_rows, page_size=200)

        # Set featured
        for i, code in enumerate(FEATURED_SSE.keys(), 1):
            cur.execute(
                "UPDATE datapai.ticker_universe SET is_featured = TRUE, featured_order = %s WHERE ticker = %s AND exchange = 'SSE'",
                (i, code),
            )
        print(f"Seeded {len(sse_rows)} SSE featured tickers")

        # SZSE featured
        szse_rows = []
        szse_dir_rows = []
        for code, cn_name in FEATURED_SZSE.items():
            yf_sym = f"{code}.SZ"
            en_name = FEATURED_EN.get(code, cn_name)
            szse_rows.append((code, "SZSE", yf_sym, en_name, True, "featured"))
            szse_dir_rows.append((code, en_name, "SZSE", "en"))
            szse_dir_rows.append((code, cn_name, "SZSE", "zh"))
            szse_dir_rows.append((code, cn_name, "SZSE", "zh-TW"))

        psycopg2.extras.execute_values(cur, """
            INSERT INTO datapai.ticker_universe (ticker, exchange, yf_symbol, company_name, is_active, source)
            VALUES %s
            ON CONFLICT (ticker, exchange) DO UPDATE SET
                yf_symbol = EXCLUDED.yf_symbol, company_name = EXCLUDED.company_name,
                is_active = EXCLUDED.is_active, updated_at = NOW()
        """, szse_rows, page_size=100)

        psycopg2.extras.execute_values(cur, """
            INSERT INTO datapai.stock_directory (symbol, name, exchange, lang) VALUES %s
            ON CONFLICT (symbol, exchange, lang) DO UPDATE SET name = EXCLUDED.name
        """, szse_dir_rows, page_size=200)

        for i, code in enumerate(FEATURED_SZSE.keys(), 1):
            cur.execute(
                "UPDATE datapai.ticker_universe SET is_featured = TRUE, featured_order = %s WHERE ticker = %s AND exchange = 'SZSE'",
                (i, code),
            )
        print(f"Seeded {len(szse_rows)} SZSE featured tickers")

        conn.commit()


def seed_full_scan(conn):
    """Full scan of known ticker ranges (takes time)."""
    # SSE
    for start, end in SSE_RANGES:
        tickers = scan_range(start, end, ".SS", "SSE")
        if tickers:
            with conn.cursor() as cur:
                rows = [(t["code"], "SSE", t["yf_symbol"], t["name"], True, "scan") for t in tickers]
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO datapai.ticker_universe (ticker, exchange, yf_symbol, company_name, is_active, source)
                    VALUES %s
                    ON CONFLICT (ticker, exchange) DO UPDATE SET
                        yf_symbol = EXCLUDED.yf_symbol, company_name = EXCLUDED.company_name,
                        is_active = EXCLUDED.is_active, updated_at = NOW()
                """, rows, page_size=200)

                dir_rows = [(t["code"], t["name"], "SSE", "en") for t in tickers]
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO datapai.stock_directory (symbol, name, exchange, lang) VALUES %s
                    ON CONFLICT (symbol, exchange, lang) DO NOTHING
                """, dir_rows, page_size=200)

                conn.commit()
            print(f"  SSE range {start}-{end}: {len(tickers)} valid tickers")

    # SZSE
    for start, end in SZSE_RANGES:
        tickers = scan_range(start, end, ".SZ", "SZSE")
        if tickers:
            with conn.cursor() as cur:
                rows = [(t["code"], "SZSE", t["yf_symbol"], t["name"], True, "scan") for t in tickers]
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO datapai.ticker_universe (ticker, exchange, yf_symbol, company_name, is_active, source)
                    VALUES %s
                    ON CONFLICT (ticker, exchange) DO UPDATE SET
                        yf_symbol = EXCLUDED.yf_symbol, company_name = EXCLUDED.company_name,
                        is_active = EXCLUDED.is_active, updated_at = NOW()
                """, rows, page_size=200)

                dir_rows = [(t["code"], t["name"], "SZSE", "en") for t in tickers]
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO datapai.stock_directory (symbol, name, exchange, lang) VALUES %s
                    ON CONFLICT (symbol, exchange, lang) DO NOTHING
                """, dir_rows, page_size=200)

                conn.commit()
            print(f"  SZSE range {start}-{end}: {len(tickers)} valid tickers")


def main():
    parser = argparse.ArgumentParser(description="Seed China A-shares tickers")
    parser.add_argument("--featured-only", action="store_true", help="Only seed featured blue chips (fast)")
    args = parser.parse_args()

    conn = get_conn()
    try:
        print("=== Seeding featured China A-shares blue chips ===")
        seed_featured(conn)

        if not args.featured_only:
            print("\n=== Full scan of known ticker ranges (this takes a while) ===")
            seed_full_scan(conn)

        # Print summary
        with conn.cursor() as cur:
            cur.execute("SELECT exchange, COUNT(*) FROM datapai.ticker_universe WHERE exchange IN ('SSE', 'SZSE') GROUP BY exchange")
            for row in cur.fetchall():
                print(f"  {row[0]}: {row[1]} tickers")
    finally:
        conn.close()
    print("Done!")


if __name__ == "__main__":
    main()
