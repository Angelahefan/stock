#!/usr/bin/env python3
"""
Seed LSE (London Stock Exchange) tickers into datapai.ticker_universe and stock_directory.

Uses curated FTSE 100 + FTSE 250 constituents (no brute-force scanning).
LSE tickers use .L suffix in yfinance (e.g., HSBA.L, BP.L).
Prices are in GBX (pence) — yfinance returns this correctly, stored as-is.

Usage:
    PGHOST=localhost PGUSER=postgres PGPASSWORD=postgres python3 scripts/seed_lse_tickers.py [--featured-only]
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

# ── Featured blue chips (Top 20) — always seeded ─────────────────────────────

FEATURED_LSE = {
    "HSBA": "HSBC Holdings",
    "BP":   "BP",
    "AZN":  "AstraZeneca",
    "SHEL": "Shell",
    "GSK":  "GSK",
    "ULVR": "Unilever",
    "RIO":  "Rio Tinto",
    "DGE":  "Diageo",
    "LSEG": "London Stock Exchange Group",
    "REL":  "RELX",
    "AAL":  "Anglo American",
    "BATS": "British American Tobacco",
    "PRU":  "Prudential",
    "LLOY": "Lloyds Banking Group",
    "BARC": "Barclays",
    "GLEN": "Glencore",
    "VOD":  "Vodafone Group",
    "NG":   "National Grid",
    "AHT":  "Ashtead Group",
    "CRH":  "CRH",
}

# ── FTSE 100 + FTSE 250 curated list ─────────────────────────────────────────
# These are well-known constituents. yfinance validation filters out delisted ones.

FTSE_100 = [
    "III", "ABF", "ADM", "AAF", "AAL", "ANTO", "AHT", "ABN", "AZN",
    "AUTO", "AVV", "AVST", "BA", "BARC", "BDEV", "BKG", "BHP", "BP",
    "BRBY", "BT.A", "BNZL", "CCH", "CPG", "CRH", "CRDA", "DCC",
    "DGE", "DPLM", "EDV", "ENT", "EXPN", "FERG", "FLTR", "FRES",
    "GLEN", "GSK", "HLN", "HLMA", "HIK", "HSBA", "IHG", "IMB",
    "INF", "ITRK", "IAG", "JD", "KGF", "LAND", "LGEN", "LLOY",
    "LSEG", "MNG", "MKS", "MNDI", "NG", "NWG", "NXT", "OCDO",
    "PSON", "PSH", "PSN", "PRU", "RKT", "REL", "RIO", "RR",
    "RMV", "RS1", "SGE", "SBRY", "SDR", "SMT", "SGRO", "SVT",
    "SHEL", "SN", "SMDS", "SMIN", "SKG", "SPX", "SSE", "STAN",
    "TW", "TSCO", "ULVR", "UTG", "UU", "VOD", "WEIR", "WTB",
    "WPP", "BATS",
]

FTSE_250 = [
    "AGK", "AGR", "AIIT", "AJB", "ASHM", "ATT", "BBY", "BGEO",
    "BHMG", "BIG", "BNKR", "BOY", "BREE", "BRSC", "BYIT", "CBG",
    "CCC", "CEY", "CHG", "CHRT", "CKN", "CMCX", "CNA", "CNE",
    "COB", "CURY", "DARK", "DCTA", "DFS", "DHG", "DIG", "DJAN",
    "DOCS", "DOM", "DPLM", "ECM", "ELM", "EMG", "ENOG", "EQLS",
    "FCIT", "FDM", "FDEV", "FGP", "FOUR", "FUTR", "GAW", "GCP",
    "GNS", "GPOR", "GRI", "HAS", "HCFT", "HDIV", "HICL", "HRI",
    "HTWS", "HWDN", "ICP", "IGG", "IMI", "INCH", "IPO", "ITV",
    "JET2", "JHD", "JLG", "JMAT", "JMG", "JWNG", "JLEN", "KEI",
    "KIE", "KWS", "LGEN", "LIO", "LOG", "LUND", "LWB", "MART",
    "MCB", "MCRO", "MGGT", "MGNS", "MJH", "MONY", "MTRO", "MTO",
    "NCYF", "NRR", "NWF", "OSB", "OXIG", "PAGE", "PAG", "PCGH",
    "PFG", "PHE", "PINE", "PRTC", "QQ", "REDD", "RHM", "RNWH",
    "ROR", "RSW", "RTO", "S32", "SAFE", "SAVE", "SDP", "SEPL",
    "SGC", "SHED", "SHI", "SHTG", "SMWH", "SRC", "SRP", "SXS",
    "SYNT", "TATE", "TEM", "THRG", "TLW", "TPK", "TRN", "TRY",
    "TRIG", "UDG", "UJO", "UKW", "UKCM", "VCT", "VEIL", "VIDA",
    "VMUK", "VTY", "WAG", "WIZZ", "WJG", "WKP", "WOSG", "WPHO",
    "WWH", "XAR", "YOU", "ZTF",
]

# Deduplicate
ALL_TICKERS = list(dict.fromkeys(list(FEATURED_LSE.keys()) + FTSE_100 + FTSE_250))


def get_conn():
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", "postgres"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", "postgres"),
    )


def validate_ticker(code: str) -> dict | None:
    """Validate a single LSE ticker via yfinance. Returns info dict or None."""
    yf_symbol = f"{code}.L"
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


def seed_featured(conn):
    """Seed the top 20 featured blue chips (fast, no yfinance validation)."""
    with conn.cursor() as cur:
        rows = []
        dir_rows = []
        for code, name in FEATURED_LSE.items():
            yf_sym = f"{code}.L"
            rows.append((code, "LSE", yf_sym, name, True, "featured"))
            dir_rows.append((code, name, "LSE", "en"))

        psycopg2.extras.execute_values(cur, """
            INSERT INTO datapai.ticker_universe (ticker, exchange, yf_symbol, company_name, is_active, source)
            VALUES %s
            ON CONFLICT (ticker, exchange) DO UPDATE SET
                yf_symbol = EXCLUDED.yf_symbol, company_name = EXCLUDED.company_name,
                is_active = EXCLUDED.is_active, updated_at = NOW()
        """, rows, page_size=100)

        psycopg2.extras.execute_values(cur, """
            INSERT INTO datapai.stock_directory (symbol, name, exchange, lang) VALUES %s
            ON CONFLICT (symbol, exchange, lang) DO UPDATE SET name = EXCLUDED.name
        """, dir_rows, page_size=200)

        for i, code in enumerate(FEATURED_LSE.keys(), 1):
            cur.execute(
                "UPDATE datapai.ticker_universe SET is_featured = TRUE, featured_order = %s WHERE ticker = %s AND exchange = 'LSE'",
                (i, code),
            )
        conn.commit()
        print(f"Seeded {len(rows)} LSE featured tickers")


def seed_full(conn, batch_size: int = 40):
    """Validate and seed all FTSE 100 + FTSE 250 tickers via yfinance."""
    valid = []
    for batch_start in range(0, len(ALL_TICKERS), batch_size):
        batch = ALL_TICKERS[batch_start:batch_start + batch_size]
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(validate_ticker, c): c for c in batch}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    valid.append(result)
        scanned = min(batch_start + batch_size, len(ALL_TICKERS))
        print(f"  Validated {scanned}/{len(ALL_TICKERS)}, found {len(valid)} valid so far")
        if batch_start + batch_size < len(ALL_TICKERS):
            time.sleep(1)

    if valid:
        with conn.cursor() as cur:
            rows = [(t["code"], "LSE", t["yf_symbol"], t["name"], True, "scan") for t in valid]
            psycopg2.extras.execute_values(cur, """
                INSERT INTO datapai.ticker_universe (ticker, exchange, yf_symbol, company_name, is_active, source)
                VALUES %s
                ON CONFLICT (ticker, exchange) DO UPDATE SET
                    yf_symbol = EXCLUDED.yf_symbol, company_name = EXCLUDED.company_name,
                    is_active = EXCLUDED.is_active, updated_at = NOW()
            """, rows, page_size=200)

            dir_rows = [(t["code"], t["name"], "LSE", "en") for t in valid]
            psycopg2.extras.execute_values(cur, """
                INSERT INTO datapai.stock_directory (symbol, name, exchange, lang) VALUES %s
                ON CONFLICT (symbol, exchange, lang) DO NOTHING
            """, dir_rows, page_size=200)

            conn.commit()
        print(f"  Seeded {len(valid)} valid LSE tickers total")
    else:
        print("  WARNING: No valid tickers found!")


def main():
    parser = argparse.ArgumentParser(description="Seed LSE tickers (FTSE 100 + FTSE 250)")
    parser.add_argument("--featured-only", action="store_true", help="Only seed featured blue chips (fast)")
    args = parser.parse_args()

    conn = get_conn()
    try:
        print("=== Seeding LSE featured blue chips ===")
        seed_featured(conn)

        if not args.featured_only:
            print("\n=== Validating FTSE 100 + FTSE 250 tickers via yfinance ===")
            seed_full(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM datapai.ticker_universe WHERE exchange = 'LSE'")
            count = cur.fetchone()[0]
            print(f"\nLSE total: {count} tickers in ticker_universe")
    finally:
        conn.close()
    print("Done!")


if __name__ == "__main__":
    main()
