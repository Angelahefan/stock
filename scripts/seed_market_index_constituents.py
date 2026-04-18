#!/usr/bin/env python3
"""
seed_market_index_constituents.py — Initial seed of market index constituent lists.

Fetches from public sources where available (Wikipedia for S&P 500, Nikkei 225).
For other markets, seeds from our existing demo/featured stocks as starting point.

This is a ONE-TIME seed. After this, the table is manually maintained.
The weekly DAG only refreshes prices/fundamentals, not the constituent list.

Usage:
    python3 scripts/seed_market_index_constituents.py
"""
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.lib.db_helpers import get_conn
from scripts.lib.log_setup import setup_logging
from psycopg2.extras import execute_values

logger = setup_logging("seed_market_index_constituents")


def fetch_sp500() -> list:
    """S&P 500 from Wikipedia."""
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
        tickers = re.findall(r'<td[^>]*><a[^>]*class="external text"[^>]*>([A-Z.]{1,5})</a>', html)
        if not tickers:
            tickers = re.findall(r'<td[^>]*><a[^>]*>([A-Z]{1,5})</a>', html)
        unique = list(dict.fromkeys(tickers))
        logger.info("  S&P 500: %d tickers", len(unique))
        return unique[:503]
    except Exception as e:
        logger.warning("  S&P 500 failed: %s", e)
        return []


def fetch_nikkei225() -> list:
    """Nikkei 225 from Wikipedia."""
    try:
        url = "https://en.wikipedia.org/wiki/Nikkei_225"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
        tickers = re.findall(r'>(\d{4})<', html)
        unique = list(dict.fromkeys(t for t in tickers if len(t) == 4))
        logger.info("  Nikkei 225: %d tickers", len(unique))
        return unique[:225]
    except Exception as e:
        logger.warning("  Nikkei 225 failed: %s", e)
        return []


def _fetch_tradingview_tickers(exchange_code: str, limit: int = 300) -> list:
    """Fetch top tickers by market cap from TradingView scanner."""
    import json
    try:
        all_tickers = []
        for page in range(0, limit, 100):
            data = json.dumps({
                "columns": ["name", "market_cap_basic"],
                "filter": [{"left": "exchange", "operation": "equal", "right": exchange_code}],
                "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
                "range": [page, page + 100]
            }).encode()
            req = urllib.request.Request(
                f"https://scanner.tradingview.com/{'singapore' if exchange_code == 'SGX' else 'japan' if exchange_code == 'TSE' else 'global'}/scan",
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
            )
            resp = urllib.request.urlopen(req, timeout=15)
            result = json.loads(resp.read().decode("utf-8"))
            items = result.get("data", [])
            if not items:
                break
            for item in items:
                sym = item["s"].replace(f"{exchange_code}:", "")
                all_tickers.append(sym)
        logger.info("  TradingView %s: %d tickers (top by market cap)", exchange_code, len(all_tickers))
        return all_tickers[:limit]
    except Exception as e:
        logger.warning("  TradingView %s failed: %s", exchange_code, e)
        return []


# TradingView exchange codes mapping
_TV_EXCHANGE = {
    "ASX": "ASX", "HKEX": "HKEX", "TWSE": "TWSE", "SGX": "SGX",
    "SSE": "SSE", "SZSE": "SZSE", "HOSE": "HOSE", "SET": "SET",
    "KLSE": "MYX", "IDX": "IDX", "LSE": "LSE",
}


def seed_from_db(conn, exchange: str, index_name: str, category: str = "blue_chip", target: int = 200):
    """Seed from TradingView (top by market cap) + demo/featured stocks."""
    # First try TradingView for broader coverage
    tv_code = _TV_EXCHANGE.get(exchange)
    tv_tickers = []
    if tv_code:
        tv_tickers = _fetch_tradingview_tickers(tv_code, limit=target)

    with conn.cursor() as cur:
        # Also get our demo/featured stocks
        cur.execute("""
            SELECT DISTINCT ticker FROM datapai.ticker_universe
            WHERE exchange = %s AND is_active AND is_featured
            UNION
            SELECT DISTINCT ticker FROM datapai.market_demo_stocks
            WHERE exchange = %s
        """, [exchange, exchange])
        db_tickers = [r[0] for r in cur.fetchall()]

        # Combine: TradingView + DB, deduplicate
        all_tickers = list(dict.fromkeys(tv_tickers + db_tickers))

        if all_tickers:
            rows = [(t, exchange, index_name, category) for t in all_tickers]
            execute_values(cur, """
                INSERT INTO datapai.market_index_constituents (ticker, exchange, index_name, index_category)
                VALUES %s ON CONFLICT (ticker, exchange, index_name) DO NOTHING
            """, rows)
            logger.info("  %s (%s): %d tickers (TV=%d + DB=%d)", exchange, index_name, len(all_tickers), len(tv_tickers), len(db_tickers))


def main():
    with get_conn() as conn:
        with conn.cursor() as cur:
            # S&P 500
            sp500 = fetch_sp500()
            if sp500:
                rows = [(t, "US", "S&P 500", "large_cap") for t in sp500]
                execute_values(cur, """
                    INSERT INTO datapai.market_index_constituents (ticker, exchange, index_name, index_category)
                    VALUES %s ON CONFLICT (ticker, exchange, index_name) DO NOTHING
                """, rows)
                logger.info("  S&P 500: %d inserted", len(rows))

            # Nikkei 225
            nikkei = fetch_nikkei225()
            if nikkei:
                rows = [(t, "TSE", "Nikkei 225", "large_cap") for t in nikkei]
                execute_values(cur, """
                    INSERT INTO datapai.market_index_constituents (ticker, exchange, index_name, index_category)
                    VALUES %s ON CONFLICT (ticker, exchange, index_name) DO NOTHING
                """, rows)
                logger.info("  Nikkei 225: %d inserted", len(rows))

            # Other markets — seed from demo/featured stocks
            seed_from_db(conn, "ASX", "ASX 300", "blue_chip")
            seed_from_db(conn, "HKEX", "HSI Composite", "blue_chip")
            seed_from_db(conn, "TWSE", "TWSE 50", "blue_chip")
            seed_from_db(conn, "SGX", "STI", "blue_chip")
            seed_from_db(conn, "SSE", "SSE 300", "large_cap")
            seed_from_db(conn, "SZSE", "SZSE 100", "large_cap")
            seed_from_db(conn, "HOSE", "VN30", "blue_chip")
            seed_from_db(conn, "SET", "SET 100", "blue_chip")
            seed_from_db(conn, "KLSE", "KLCI", "blue_chip")
            seed_from_db(conn, "IDX", "IDX 80", "blue_chip")
            seed_from_db(conn, "LSE", "FTSE 350", "blue_chip")

            # Summary
            cur.execute("""
                SELECT exchange, index_name, COUNT(*)
                FROM datapai.market_index_constituents WHERE is_active
                GROUP BY exchange, index_name ORDER BY exchange
            """)
            for row in cur.fetchall():
                logger.info("  Final: %s / %s = %d stocks", row[0], row[1], row[2])

    logger.info("=== Seed complete ===")


if __name__ == "__main__":
    main()
