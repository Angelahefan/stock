#!/usr/bin/env python3
"""
scripts/backfill_intraday.py
─────────────────────────────────────────────────────────────────────────────
Backfill intraday OHLCV data from yfinance for featured/popular stocks.
yfinance supports: 1m (7 days), 5m (60 days), 15m (60 days), 30m (60 days).

We use 15m interval — good balance of granularity vs data size.
Backfills last 5 days by default (configurable).

Usage:
    python3 scripts/backfill_intraday.py --exchange US --days 5
    python3 scripts/backfill_intraday.py --exchange all --days 10
    python3 scripts/backfill_intraday.py --exchange HKEX --tickers 0005.HK,0700.HK
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import psycopg2
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.lib.log_setup import setup_logging

logger = setup_logging("backfill_intraday")

from core.config.exchange_registry import registry as _exr
ALL_EXCHANGES = _exr.get_all_exchanges()  # DB-driven, was hardcoded
BATCH_SIZE = 20  # yfinance intraday batch limit is smaller
INTERVAL = "15m"


def get_conn():
    from scripts.lib.db_helpers import get_conn as _get_conn
    return _get_conn()


def load_tickers(conn, exchange: str) -> list[tuple[str, str, str]]:
    """Load (ticker, yf_symbol, exchange) for featured + popular stocks."""
    with conn.cursor() as cur:
        if exchange.upper() == "ALL":
            cur.execute("""
                SELECT tu.ticker, tu.yf_symbol, tu.exchange
                FROM datapai.ticker_universe tu
                WHERE tu.is_active = TRUE AND tu.is_featured = TRUE
                ORDER BY tu.exchange, tu.ticker
            """)
        else:
            cur.execute("""
                SELECT tu.ticker, tu.yf_symbol, tu.exchange
                FROM datapai.ticker_universe tu
                WHERE tu.is_active = TRUE AND tu.exchange = %s
                  AND (tu.is_featured = TRUE
                       OR EXISTS (SELECT 1 FROM datapai.priority_tickers pt
                                  WHERE pt.ticker = tu.ticker AND pt.exchange = tu.exchange))
                ORDER BY tu.ticker
            """, (exchange.upper(),))
        return cur.fetchall()


def download_intraday(yf_symbols: list[str], days: int) -> dict[str, pd.DataFrame]:
    """Download intraday data for a batch of symbols."""
    period = f"{days}d"
    try:
        raw = yf.download(
            tickers=" ".join(yf_symbols),
            period=period,
            interval=INTERVAL,
            group_by="ticker",
            auto_adjust=True,
            prepost=False,
            progress=False,
            threads=False,
        )
        if raw is None or raw.empty:
            return {}

        if len(yf_symbols) == 1:
            return {yf_symbols[0]: raw}

        result = {}
        available = set(raw.columns.get_level_values(0))
        for sym in yf_symbols:
            sym_up = sym.upper()
            try:
                if sym_up in available:
                    df = raw[sym_up]
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(-1)
                    if not df.empty:
                        result[sym_up] = df
            except (KeyError, TypeError):
                pass
        return result

    except Exception as e:
        logger.warning("Download failed: %s", e)
        return {}


def upsert_intraday(conn, rows: list[tuple], exchange: str) -> int:
    """Bulk upsert intraday rows."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        # Use unnest for fast bulk insert
        from psycopg2.extras import execute_values
        execute_values(cur, """
            INSERT INTO datapai.ohlcv_intraday (ticker, ts, open, high, low, close, volume, exchange, source)
            VALUES %s
            ON CONFLICT (ticker, ts, exchange) DO UPDATE
            SET open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                close = EXCLUDED.close, volume = EXCLUDED.volume
        """, rows, template="(%s, %s, %s, %s, %s, %s, %s, %s, 'yfinance')")
    conn.commit()
    return len(rows)


def run(exchange: str, days: int = 5, tickers_override: str = "", dry_run: bool = False):
    conn = get_conn()

    if tickers_override:
        # Manual override: parse comma-separated yf_symbols
        syms = [s.strip().upper() for s in tickers_override.split(",")]
        ticker_list = [(s, s, exchange.upper()) for s in syms]
    else:
        ticker_list = load_tickers(conn, exchange)

    logger.info("── Intraday Backfill  exchange=%s  tickers=%d  days=%d  interval=%s ──",
                exchange, len(ticker_list), days, INTERVAL)

    if not ticker_list:
        logger.info("No tickers to backfill")
        conn.close()
        return

    total_rows = 0
    total_tickers = 0

    # Process in batches
    yf_symbols = [t[1] for t in ticker_list]
    sym_to_info = {t[1].upper(): (t[0], t[2]) for t in ticker_list}

    for i in range(0, len(yf_symbols), BATCH_SIZE):
        batch = yf_symbols[i:i + BATCH_SIZE]
        logger.info("Batch %d/%d  (%d symbols)",
                     i // BATCH_SIZE + 1,
                     (len(yf_symbols) + BATCH_SIZE - 1) // BATCH_SIZE,
                     len(batch))

        data = download_intraday(batch, days)

        rows = []
        for sym, df in data.items():
            sym_up = sym.upper()
            if sym_up not in sym_to_info:
                continue
            ticker, exch = sym_to_info[sym_up]

            for ts, row in df.iterrows():
                o = row.get("Open")
                h = row.get("High")
                l = row.get("Low")
                c = row.get("Close")
                v = row.get("Volume")
                if pd.isna(c) or c == 0:
                    continue
                # ts is a pandas Timestamp
                ts_str = ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)
                rows.append((ticker, ts_str, float(o or 0), float(h or 0), float(l or 0), float(c), int(v or 0), exch))

            total_tickers += 1

        logger.info("  → %d tickers, %d rows", len(data), len(rows))

        if rows and not dry_run:
            upserted = upsert_intraday(conn, rows, exchange)
            total_rows += upserted

        if i + BATCH_SIZE < len(yf_symbols):
            time.sleep(random.uniform(1, 2))

    conn.close()
    logger.info("── Backfill Complete: %d tickers, %d rows ──", total_tickers, total_rows)


def main():
    ap = argparse.ArgumentParser(description="Backfill intraday OHLCV from yfinance")
    ap.add_argument("--exchange", required=True, help="Exchange or 'all'")
    ap.add_argument("--days", type=int, default=5, help="Days to backfill (max 60 for 15m)")
    ap.add_argument("--tickers", default="", help="Override: comma-separated yf_symbols")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    run(exchange=args.exchange, days=args.days, tickers_override=args.tickers, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
