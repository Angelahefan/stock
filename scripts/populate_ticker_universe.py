#!/usr/bin/env python3
"""
populate_ticker_universe.py — Populate datapai.ticker_universe table.

Loads tickers from:
  1. A file (one ticker per line) — for ASX from official ASX CSV
  2. NASDAQ screener API — for US tickers
  3. Existing prices table — any ticker already in DB

Usage:
    # Populate ASX from file
    python3 scripts/populate_ticker_universe.py --exchange ASX --file ~/asx_full_tickers.txt

    # Populate US from NASDAQ API
    python3 scripts/populate_ticker_universe.py --exchange US --from-api

    # Populate from existing prices table (both exchanges)
    python3 scripts/populate_ticker_universe.py --from-db

    # All three sources
    python3 scripts/populate_ticker_universe.py --exchange ASX --file ~/asx_full_tickers.txt --from-db
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import List

import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_conn():
    return psycopg2.connect(
        host=os.getenv("PGHOST", os.getenv("DATAPAI_PG_HOST", "localhost")),
        port=int(os.getenv("PGPORT", os.getenv("DATAPAI_PG_PORT", "5432"))),
        dbname=os.getenv("PGDATABASE", os.getenv("DATAPAI_PG_DB", "postgres")),
        user=os.getenv("PGUSER", os.getenv("DATAPAI_PG_USER", "postgres")),
        password=os.getenv("PGPASSWORD", os.getenv("DATAPAI_PG_PASSWORD", "")),
    )


def load_tickers_from_file(path: str) -> list[str]:
    """Read tickers from a text file (one per line or comma-separated)."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")

    tickers = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Handle comma-separated or single ticker per line
        for part in line.split(","):
            t = part.strip().upper()
            # Remove .AX suffix if present — we store bare ticker
            if t.endswith(".AX"):
                t = t[:-3]
            if t and len(t) <= 10 and t.isascii():
                tickers.append(t)

    return sorted(set(tickers))


def upsert_tickers(conn, tickers: list[str], exchange: str, source: str):
    """Upsert tickers into datapai.ticker_universe."""
    rows = []
    for t in tickers:
        yf_sym = f"{t}.AX" if exchange == "ASX" else t
        rows.append((t, exchange, yf_sym, source))

    sql = """
        INSERT INTO datapai.ticker_universe (ticker, exchange, yf_symbol, source, is_active)
        VALUES (%s, %s, %s, %s, TRUE)
        ON CONFLICT (ticker, exchange)
        DO UPDATE SET
            yf_symbol = EXCLUDED.yf_symbol,
            is_active = TRUE,
            updated_at = NOW()
    """

    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows, page_size=500)
    conn.commit()
    logger.info("Upserted %d %s tickers (source=%s)", len(rows), exchange, source)


def populate_from_db(conn):
    """Add any ticker already in prices table but not in universe."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO datapai.ticker_universe (ticker, exchange, yf_symbol, source, is_active)
            SELECT DISTINCT
                CASE WHEN p.exchange = 'ASX' AND p.ticker LIKE '%%.AX'
                     THEN REPLACE(p.ticker, '.AX', '')
                     ELSE p.ticker
                END AS ticker,
                p.exchange,
                p.ticker AS yf_symbol,
                'from_prices' AS source,
                TRUE
            FROM datapai.prices p
            WHERE NOT EXISTS (
                SELECT 1 FROM datapai.ticker_universe u
                WHERE u.ticker = (
                    CASE WHEN p.exchange = 'ASX' AND p.ticker LIKE '%%.AX'
                         THEN REPLACE(p.ticker, '.AX', '')
                         ELSE p.ticker
                    END
                )
                AND u.exchange = p.exchange
            )
            GROUP BY p.ticker, p.exchange
            ON CONFLICT (ticker, exchange) DO NOTHING
        """)
        count = cur.rowcount
    conn.commit()
    logger.info("Added %d tickers from existing prices table", count)


def populate_us_from_api(conn):
    """Fetch US tickers from NASDAQ screener API and add to universe."""
    try:
        from scripts.lib.ticker_loader import load_us_tickers
        tickers = load_us_tickers(use_cache=True)
        # Strip .AX suffix (shouldn't have any for US, but just in case)
        clean = [t.replace(".AX", "") for t in tickers]
        upsert_tickers(conn, clean, "US", "nasdaq_api")
    except Exception as e:
        logger.error("Failed to load US tickers from API: %s", e)


def main():
    parser = argparse.ArgumentParser(description="Populate datapai.ticker_universe")
    parser.add_argument("--exchange", help="US or ASX")
    parser.add_argument("--file", help="Ticker file (one per line)")
    parser.add_argument("--from-api", action="store_true", help="Load US tickers from NASDAQ API")
    parser.add_argument("--from-db", action="store_true", help="Add tickers from existing prices table")
    args = parser.parse_args()

    conn = get_conn()
    try:
        if args.file and args.exchange:
            tickers = load_tickers_from_file(args.file)
            logger.info("Loaded %d tickers from %s", len(tickers), args.file)
            upsert_tickers(conn, tickers, args.exchange.upper(), "asx_csv" if args.exchange.upper() == "ASX" else "file")

        if args.from_api:
            populate_us_from_api(conn)

        if args.from_db:
            populate_from_db(conn)

        # Print summary
        with conn.cursor() as cur:
            cur.execute("""
                SELECT exchange, COUNT(*) as total, COUNT(*) FILTER (WHERE is_active) as active
                FROM datapai.ticker_universe
                GROUP BY exchange ORDER BY exchange
            """)
            for row in cur.fetchall():
                logger.info("  Universe: %s — %d total, %d active", row[0], row[1], row[2])
    finally:
        conn.close()


if __name__ == "__main__":
    main()
