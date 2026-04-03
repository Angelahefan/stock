#!/usr/bin/env python3
"""
refresh_ohlcv_daily_indexes.py — Daily delta refresh for 16 global market indexes.
Fetches last 5 days from Yahoo Finance and upserts into datapai.prices.
"""
import sys, os, time, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yfinance as yf
from scripts.lib.db_helpers import get_conn, upsert_daily_rows, df_to_daily_rows

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)


def load_index_tickers():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT yf_symbol FROM datapai.ticker_universe
                WHERE exchange = 'INDEX' AND is_active = TRUE ORDER BY ticker
            """)
            return [r[0] for r in cur.fetchall()]


def refresh():
    tickers = load_index_tickers()
    log.info("Refreshing %d global indexes (last 5 days)", len(tickers))

    total_rows = 0
    failed = []

    for sym in tickers:
        try:
            df = yf.download(sym, period="5d", interval="1d",
                             auto_adjust=True, threads=False, progress=False)
            if df is None or df.empty:
                log.warning("  %s — no data", sym)
                failed.append(sym)
                continue

            if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
                df.columns = df.columns.droplevel(1)

            rows = df_to_daily_rows(df, sym, "INDEX", "yahoo")
            if rows:
                upsert_daily_rows(rows, f"daily-index-{sym}")
                total_rows += len(rows)

            time.sleep(0.5)
        except Exception as e:
            log.error("  FAILED %s: %s", sym, e)
            failed.append(sym)

    log.info("═══ Index refresh done: %d rows upserted, %d failed ═══", total_rows, len(failed))
    if failed:
        log.warning("Failed: %s", ", ".join(failed))


if __name__ == "__main__":
    refresh()
