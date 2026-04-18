#!/usr/bin/env python3
"""Backfill last 5 days of 30m intraday bars for demo stocks into per-market tables."""
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

import yfinance as yf
import pandas as pd
from scripts.lib.db_helpers import get_conn, upsert_intraday_rows
from scripts.lib.log_setup import setup_logging

# Market timezone mapping
MARKET_TZ = {
    "US": "America/New_York", "ASX": "Australia/Sydney",
    "HKEX": "Asia/Hong_Kong", "HOSE": "Asia/Ho_Chi_Minh",
    "SET": "Asia/Bangkok", "KLSE": "Asia/Kuala_Lumpur",
    "IDX": "Asia/Jakarta", "SSE": "Asia/Shanghai",
    "SZSE": "Asia/Shanghai", "LSE": "Europe/London",
}

logger = setup_logging("backfill_intraday_demo")

BATCH_SIZE = 20


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT d.ticker, d.exchange, COALESCE(tu.yf_symbol, d.ticker) as yf_symbol "
                "FROM datapai.market_demo_stocks d "
                "LEFT JOIN datapai.ticker_universe tu ON tu.ticker = d.ticker AND tu.exchange = d.exchange "
                "WHERE d.exchange != 'INDEX' "
                "ORDER BY d.exchange, d.display_order"
            )
            stocks = cur.fetchall()

    logger.info("Total demo stocks to backfill: %d", len(stocks))

    by_exchange = {}
    for ticker, exchange, yf_sym in stocks:
        by_exchange.setdefault(exchange, []).append((ticker, yf_sym))

    for exchange in sorted(by_exchange):
        tickers = by_exchange[exchange]
        yf_syms = [t[1] for t in tickers]
        sym_to_ticker = {t[1].upper(): t[0] for t in tickers}

        logger.info("[%s] Downloading 30m bars for %d tickers...", exchange, len(yf_syms))
        local_tz = ZoneInfo(MARKET_TZ.get(exchange, "UTC"))

        all_rows = []
        for i in range(0, len(yf_syms), BATCH_SIZE):
            batch = yf_syms[i:i + BATCH_SIZE]
            try:
                raw = yf.download(
                    " ".join(batch), period="5d", interval="30m",
                    auto_adjust=True, prepost=False, progress=False, threads=False,
                )
                if raw is None or raw.empty:
                    continue

                # yfinance returns MultiIndex: (Price, Ticker)
                if isinstance(raw.columns, pd.MultiIndex):
                    ticker_syms = raw.columns.get_level_values("Ticker").unique().tolist()
                    for sym in ticker_syms:
                        sym_up = sym.upper()
                        ticker = sym_to_ticker.get(sym_up, sym_up)
                        df = raw.xs(sym, level="Ticker", axis=1)
                        for ts, row in df.iterrows():
                            c = row.get("Close")
                            if pd.isna(c) or c == 0:
                                continue
                            local_ts = ts.astimezone(local_tz).strftime("%Y-%m-%d %H:%M:%S")
                            all_rows.append((
                                ticker, local_ts,
                                float(row["Open"]), float(row["High"]),
                                float(row["Low"]), float(c),
                                int(row.get("Volume", 0) or 0),
                                exchange, "yfinance",
                            ))
                else:
                    # Flat columns (single ticker edge case)
                    ticker = sym_to_ticker.get(batch[0].upper(), batch[0])
                    for ts, row in raw.iterrows():
                        c = row.get("Close")
                        if pd.isna(c) or c == 0:
                            continue
                        all_rows.append((
                            ticker, ts.to_pydatetime(),
                            float(row["Open"]), float(row["High"]),
                            float(row["Low"]), float(c),
                            int(row.get("Volume", 0) or 0),
                            exchange, "yfinance",
                        ))
            except Exception as e:
                logger.warning("  Batch error: %s", e)
            time.sleep(0.5)

        if all_rows:
            n = upsert_intraday_rows(all_rows, batch_label=f"{exchange} backfill", exchange=exchange)
            unique = len(set(r[0] for r in all_rows))
            logger.info("[%s] Inserted %d bars for %d tickers", exchange, n, unique)
        else:
            logger.warning("[%s] No data returned", exchange)

    logger.info("Backfill complete!")


if __name__ == "__main__":
    main()
