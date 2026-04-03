#!/usr/bin/env python3
"""
compute_market_top_stocks.py — Refresh market_top_stocks from market_index_constituents.

Reads the manually curated market_index_constituents ref table,
enriches with latest market_cap/volume from stock_fundamentals/screener_metrics,
and upserts into market_top_stocks.

Also always includes: demo stocks + watchlisted stocks.

Usage:
    python3 scripts/compute_market_top_stocks.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.lib.db_helpers import get_conn
from scripts.lib.log_setup import setup_logging

logger = setup_logging("compute_market_top_stocks")


def compute():
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Clear and rebuild from ref table
            cur.execute("DELETE FROM datapai.market_top_stocks")

            # Insert from market_index_constituents (curated ref table)
            cur.execute("""
                INSERT INTO datapai.market_top_stocks (ticker, exchange, rank, market_cap, avg_volume, latest_close, sector)
                SELECT
                    mic.ticker, mic.exchange,
                    ROW_NUMBER() OVER (PARTITION BY mic.exchange ORDER BY COALESCE(sf.market_cap, 0) DESC),
                    sf.market_cap,
                    sm.latest_volume,
                    sm.latest_close,
                    COALESCE(sf.sector, sd.sector, mic.sector)
                FROM datapai.market_index_constituents mic
                LEFT JOIN datapai.stock_fundamentals sf ON sf.ticker = mic.ticker AND sf.exchange = mic.exchange
                LEFT JOIN datapai.screener_metrics sm ON sm.ticker = mic.ticker AND sm.exchange = mic.exchange
                LEFT JOIN datapai.stock_directory sd ON sd.symbol = mic.ticker AND sd.exchange = mic.exchange AND sd.lang = 'en'
                WHERE mic.is_active = TRUE
                ON CONFLICT (ticker, exchange) DO UPDATE SET
                    rank = EXCLUDED.rank,
                    market_cap = COALESCE(EXCLUDED.market_cap, datapai.market_top_stocks.market_cap),
                    avg_volume = COALESCE(EXCLUDED.avg_volume, datapai.market_top_stocks.avg_volume),
                    latest_close = COALESCE(EXCLUDED.latest_close, datapai.market_top_stocks.latest_close),
                    sector = COALESCE(EXCLUDED.sector, datapai.market_top_stocks.sector),
                    updated_at = NOW()
            """)
            ref_count = cur.rowcount

            # Always include demo stocks
            cur.execute("""
                INSERT INTO datapai.market_top_stocks (ticker, exchange, rank, sector)
                SELECT d.ticker, d.exchange, 999, d.sector
                FROM datapai.market_demo_stocks d
                ON CONFLICT (ticker, exchange) DO NOTHING
            """)

            # Always include watchlisted stocks
            cur.execute("""
                INSERT INTO datapai.market_top_stocks (ticker, exchange, rank)
                SELECT DISTINCT w.symbol, COALESCE(w.exchange, 'US'), 998
                FROM datapai.watchlist w
                ON CONFLICT (ticker, exchange) DO NOTHING
            """)

            # Summary
            cur.execute("""
                SELECT exchange, COUNT(*) FROM datapai.market_top_stocks
                GROUP BY exchange ORDER BY exchange
            """)
            total = 0
            for row in cur.fetchall():
                logger.info("  %s: %d stocks", row[0], row[1])
                total += row[1]

            logger.info("Done: %d total from ref table (%d from index constituents)", total, ref_count)


if __name__ == "__main__":
    compute()
