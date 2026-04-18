#!/usr/bin/env python3
"""
bootstrap_ohlcv_indexes.py — Load 5 years of daily OHLCV for global market indexes.
Only 16 indexes, so no batching needed. Runs in ~2 minutes.
"""
import sys, os, time, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yfinance as yf
from scripts.lib.db_helpers import get_conn, upsert_daily_rows, df_to_daily_rows

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)


def load_index_tickers():
    """Load active index tickers from ticker_universe."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT yf_symbol, company_name, region
                FROM datapai.ticker_universe
                WHERE exchange = 'INDEX' AND is_active = TRUE
                ORDER BY region, ticker
            """)
            return cur.fetchall()


def bootstrap():
    indexes = load_index_tickers()
    log.info("Bootstrapping %d global market indexes (5-year history)", len(indexes))

    total_rows = 0
    failed = []

    for yf_sym, name, region in indexes:
        try:
            log.info("  %s (%s) [%s] ...", yf_sym, name, region)
            df = yf.download(yf_sym, period="5y", interval="1d",
                             auto_adjust=True, threads=False, progress=False)
            if df is None or df.empty:
                log.warning("    No data for %s — skipping", yf_sym)
                failed.append(yf_sym)
                continue

            # Flatten multi-level columns if present
            if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
                df.columns = df.columns.droplevel(1)

            rows = df_to_daily_rows(df, yf_sym, "INDEX", "yahoo")
            if rows:
                upsert_daily_rows(rows, f"bootstrap-index-{yf_sym}")
                log.info("    → %d rows upserted", len(rows))
                total_rows += len(rows)
            else:
                log.warning("    → 0 rows for %s", yf_sym)
                failed.append(yf_sym)

            time.sleep(1.5)  # rate-limit courtesy

        except Exception as e:
            log.error("    FAILED %s: %s", yf_sym, e)
            failed.append(yf_sym)

    log.info("═══ Bootstrap complete: %d total rows, %d failed ═══", total_rows, len(failed))
    if failed:
        log.warning("Failed indexes: %s", ", ".join(failed))


if __name__ == "__main__":
    bootstrap()
