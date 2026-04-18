#!/usr/bin/env python3
"""
backfill_sgx_slow.py — SGX 5yr price backfill, 1 ticker at a time.
30s sleep between tickers. ~5 hours for 600 tickers. Won't get rate limited.
Skips tickers that already have data.
"""
import sys
import time
import random
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.lib.db_helpers import get_conn, upsert_daily_rows
from scripts.lib.log_setup import setup_logging

logger = setup_logging("backfill_sgx_slow")


def main():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ticker, yf_symbol FROM datapai.ticker_universe WHERE exchange = %s AND is_active", ["SGX"])
            tickers = cur.fetchall()
            cur.execute("SELECT DISTINCT ticker FROM datapai.prices WHERE exchange = %s", ["SGX"])
            done = set(r[0] for r in cur.fetchall())

    todo = [(t, y) for t, y in tickers if t not in done]
    logger.info("SGX: %d total, %d done, %d remaining", len(tickers), len(done), len(todo))

    total = 0
    for i, (db_t, yf_sym) in enumerate(todo):
        try:
            df = yf.download(yf_sym, period="5y", interval="1d", auto_adjust=True, progress=False)
            if df is not None and not df.empty:
                rows = []
                for ts, row in df.iterrows():
                    c = row.get("Close")
                    if c is None:
                        continue
                    cv = float(c.iloc[0]) if hasattr(c, "iloc") else float(c)
                    if cv == 0:
                        continue
                    td = ts.strftime("%Y-%m-%d")
                    o = float(row.get("Open", cv).iloc[0]) if hasattr(row.get("Open", cv), "iloc") else float(row.get("Open", cv))
                    h = float(row.get("High", cv).iloc[0]) if hasattr(row.get("High", cv), "iloc") else float(row.get("High", cv))
                    l = float(row.get("Low", cv).iloc[0]) if hasattr(row.get("Low", cv), "iloc") else float(row.get("Low", cv))
                    v = int(row.get("Volume", 0).iloc[0]) if hasattr(row.get("Volume", 0), "iloc") else int(row.get("Volume", 0))
                    rows.append((db_t, td, o, h, l, cv, cv, v, "SGX", "yfinance"))
                if rows:
                    upsert_daily_rows(rows, batch_label=f"SGX {db_t}")
                    total += len(rows)
                    logger.info("  %d/%d %s: %d rows (total: %d)", i + 1, len(todo), db_t, len(rows), total)
                else:
                    logger.info("  %d/%d %s: no data", i + 1, len(todo), db_t)
            else:
                logger.info("  %d/%d %s: empty", i + 1, len(todo), db_t)
        except Exception as e:
            err = str(e)
            if "RateLimit" in err or "429" in err:
                logger.warning("  %d/%d %s: rate limited, sleeping 300s", i + 1, len(todo), db_t)
                time.sleep(300)
            else:
                logger.warning("  %d/%d %s: error %s", i + 1, len(todo), db_t, err)
        time.sleep(random.uniform(25, 35))

    logger.info("DONE: %d rows for %d tickers", total, len(todo))


if __name__ == "__main__":
    main()
