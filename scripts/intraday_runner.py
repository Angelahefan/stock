#!/usr/bin/env python3
"""
scripts/intraday_runner.py
─────────────────────────────────────────────────────────────────────────────
Self-throttling intraday data collector.

Runs continuously during market hours for a given exchange.
Dynamically adjusts refresh interval based on ticker count:
  < 500 tickers  → 5 min
  500-1000       → 5 min
  1000-2000      → 10 min
  2000-3000      → 15 min
  3000-5000      → 20 min
  5000+          → 30 min

Formula: interval = max(5, ceil(tickers / 200)) minutes

Loads featured + watchlist + priority tickers from DB.
Uses yfinance batch download (20 per request) with 5m interval.
Exits automatically when market closes.

Usage:
    python3 scripts/intraday_runner.py --exchange US
    python3 scripts/intraday_runner.py --exchange HKEX
    python3 scripts/intraday_runner.py --exchange all
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg2
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.lib.log_setup import setup_logging
from scripts.lib.db_helpers import (
    upsert_intraday_rows as _db_upsert_intraday,
    archive_and_truncate_intraday,
)

logger = setup_logging("intraday_runner")

# ── Market hours (local time) ─────────────────────────────────────────────

def _load_market_hours() -> dict:
    """Load market hours via ExchangeRegistry (DB-backed, cached, with fallback)."""
    from core.config.exchange_registry import registry
    return registry.get_all_market_hours()

MARKET_HOURS = _load_market_hours()

BATCH_SIZE = 20
YF_INTERVAL = "5m"  # 5-minute bars


def get_conn():
    return psycopg2.connect(
        host=os.environ.get("DATAPAI_PG_HOST", os.environ.get("PGHOST", "localhost")),
        port=int(os.environ.get("DATAPAI_PG_PORT", os.environ.get("PGPORT", "5434"))),
        dbname="postgres",
        user=os.environ.get("PGUSER", os.environ.get("DATAPAI_PG_USER", "postgres")),
        password=os.environ.get("PGPASSWORD", os.environ.get("DATAPAI_PG_PASSWORD", "postgres")),
    )


# Grace period after official close.
# yfinance 5m bars never include the closing auction (last bar = 15:55 for 16:00 close).
# Keep 10 min grace to capture the 15:55 bar, then exit to free resources
# for quick_close_price DAG which fetches correct daily close.
CLOSE_GRACE_MINUTES = 10


def is_market_open(exchange: str) -> bool:
    """Check if the market is currently in trading hours (weekday + within open→close+grace).
    Includes a 15-min grace period after official close to capture the closing auction bar.
    Handles lunch breaks (e.g. China A-shares 11:30-13:00)."""
    mkt = MARKET_HOURS.get(exchange)
    if not mkt:
        return False
    tz = ZoneInfo(mkt["tz"])
    now = datetime.now(tz)
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    open_time = now.replace(hour=mkt["open"][0], minute=mkt["open"][1], second=0)
    close_time = now.replace(hour=mkt["close"][0], minute=mkt["close"][1], second=0)
    # Add grace period to capture closing auction
    close_with_grace = close_time + timedelta(minutes=CLOSE_GRACE_MINUTES)
    if not (open_time <= now <= close_with_grace):
        return False
    # Check lunch break (China A-shares: 11:30-13:00)
    if "lunch_start" in mkt and "lunch_end" in mkt:
        lunch_start = now.replace(hour=mkt["lunch_start"][0], minute=mkt["lunch_start"][1], second=0)
        lunch_end = now.replace(hour=mkt["lunch_end"][0], minute=mkt["lunch_end"][1], second=0)
        if lunch_start <= now <= lunch_end:
            return False
    return True


def get_open_exchanges(exchanges: list[str]) -> list[str]:
    """Filter to only currently open exchanges."""
    return [ex for ex in exchanges if is_market_open(ex)]


def load_tickers(conn, exchange: str) -> list[tuple[str, str, str]]:
    """Load (ticker, yf_symbol, exchange) for featured + watchlist + priority stocks."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT tu.ticker, tu.yf_symbol, tu.exchange
            FROM datapai.ticker_universe tu
            WHERE tu.is_active = TRUE AND tu.exchange = %s
              AND (
                tu.is_featured = TRUE
                OR EXISTS (SELECT 1 FROM datapai.watchlist w
                           WHERE w.symbol = tu.ticker AND w.exchange = tu.exchange)
                OR EXISTS (SELECT 1 FROM datapai.priority_tickers pt
                           WHERE pt.ticker = tu.ticker AND pt.exchange = tu.exchange)
              )
            ORDER BY tu.ticker
        """, (exchange,))
        return cur.fetchall()


def compute_interval(ticker_count: int) -> int:
    """Compute refresh interval in minutes based on ticker count."""
    return max(5, math.ceil(ticker_count / 200))


def download_batch(yf_symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Download latest 5m bars for a batch."""
    try:
        raw = yf.download(
            tickers=" ".join(yf_symbols),
            period="1d",
            interval=YF_INTERVAL,
            group_by="ticker",
            auto_adjust=True,
            prepost=False,
            progress=False,
            threads=False,
        )
        if raw is None or raw.empty:
            return {}
        if len(yf_symbols) == 1:
            return {yf_symbols[0].upper(): raw}
        result = {}
        available = set(raw.columns.get_level_values(0))
        for sym in yf_symbols:
            sym_up = sym.upper()
            if sym_up in available:
                df = raw[sym_up]
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(-1)
                if not df.empty:
                    result[sym_up] = df
        return result
    except Exception as e:
        logger.warning("Batch download error: %s", e)
        return {}


def upsert_bars(conn, rows: list[tuple]) -> int:
    """Bulk upsert intraday bars into per-market table via db_helpers."""
    if not rows:
        return 0
    # rows format: (ticker, ts, open, high, low, close, volume, exchange)
    # db_helpers expects: (ticker, ts, open, high, low, close, volume, exchange, source)
    db_rows = [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], "yfinance") for r in rows]
    exchange = rows[0][7]
    n = _db_upsert_intraday(db_rows, exchange=exchange)
    conn.commit()
    return n


def refresh_exchange(conn, exchange: str) -> tuple[int, int]:
    """Run one refresh cycle for an exchange. Returns (tickers, rows)."""
    tickers = load_tickers(conn, exchange)
    if not tickers:
        return (0, 0)

    # China A-shares: use Sina Finance (free, no API key, works from AWS)
    if exchange in ("SSE", "SZSE"):
        return _refresh_exchange_sina(conn, exchange, tickers)

    return _refresh_exchange_yfinance(conn, exchange, tickers)


def _refresh_exchange_sina(conn, exchange: str, tickers: list) -> tuple[int, int]:
    """Refresh SSE/SZSE using Sina Finance API (China A-share specialist)."""
    from scripts.lib.sina_helpers import fetch_batch_sina

    all_rows = fetch_batch_sina(tickers, period="5", bars=50, sleep_between=0.2)
    if all_rows:
        _db_upsert_intraday(all_rows, exchange=exchange)
        conn.commit()

    return (len(tickers), len(all_rows))


def _refresh_exchange_akshare(conn, exchange: str, tickers: list) -> tuple[int, int]:
    """Refresh SSE/SZSE using AKShare (China A-share specialist)."""
    from scripts.lib.akshare_helpers import fetch_batch_akshare

    all_rows = fetch_batch_akshare(tickers, period="5", sleep_between=0.3)
    if all_rows:
        # Add source field for upsert_bars format
        db_rows = [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]) for r in all_rows]
        _upsert_akshare_rows(conn, db_rows, exchange)

    return (len(tickers), len(all_rows))


def _upsert_akshare_rows(conn, rows: list[tuple], exchange: str):
    """Upsert AKShare rows into per-market intraday table."""
    if not rows:
        return
    # rows: (ticker, ts, open, high, low, close, volume, exchange, source)
    _db_upsert_intraday(rows, exchange=exchange)
    conn.commit()


def _refresh_exchange_yfinance(conn, exchange: str, tickers: list) -> tuple[int, int]:
    """Refresh non-China exchanges using yfinance."""
    yf_symbols = [t[1] for t in tickers]
    sym_to_info = {t[1].upper(): (t[0], t[2]) for t in tickers}

    # Convert timestamps to market local timezone
    market_tz = ZoneInfo(MARKET_HOURS[exchange]["tz"])

    total_rows = 0
    total_tickers = 0

    for i in range(0, len(yf_symbols), BATCH_SIZE):
        batch = yf_symbols[i:i + BATCH_SIZE]
        data = download_batch(batch)

        rows = []
        for sym, df in data.items():
            sym_up = sym.upper()
            if sym_up not in sym_to_info:
                continue
            ticker, exch = sym_to_info[sym_up]
            for ts, row in df.iterrows():
                c = row.get("Close")
                if pd.isna(c) or c == 0:
                    continue
                # Convert UTC → market local time (e.g. AEDT for ASX)
                local_ts = ts.astimezone(market_tz).strftime("%Y-%m-%d %H:%M:%S")
                rows.append((
                    ticker,
                    local_ts,
                    float(row.get("Open") or 0),
                    float(row.get("High") or 0),
                    float(row.get("Low") or 0),
                    float(c),
                    int(row.get("Volume") or 0),
                    exch,
                ))
            total_tickers += 1

        if rows:
            upsert_bars(conn, rows)
            total_rows += len(rows)

        if i + BATCH_SIZE < len(yf_symbols):
            time.sleep(random.uniform(0.5, 1.0))

    return (total_tickers, total_rows)


def run(exchanges: list[str]):
    """Main loop: continuously refresh open markets with dynamic intervals."""
    conn = get_conn()
    logger.info("── Intraday Runner started  exchanges=%s ──", ",".join(exchanges))

    # Archive yesterday's bars and start fresh for today
    open_now = get_open_exchanges(exchanges)
    for ex in (open_now or exchanges):
        try:
            archived, truncated = archive_and_truncate_intraday(ex)
            if archived:
                logger.info("[%s] Archived %d bars, truncated live table", ex, archived)
        except Exception as e:
            logger.warning("[%s] Archive+truncate failed: %s", ex, e)

    # Count all tickers to determine interval
    all_tickers = []
    for ex in exchanges:
        all_tickers.extend(load_tickers(conn, ex))
    total_count = len(all_tickers)
    interval_min = compute_interval(total_count)
    logger.info("Total tickers: %d → refresh interval: %d min", total_count, interval_min)

    cycle = 0
    while True:
        cycle += 1
        open_markets = get_open_exchanges(exchanges)

        if not open_markets:
            idle_checks = getattr(run, '_idle_checks', 0) + 1
            run._idle_checks = idle_checks

            # Single-exchange mode: exit after 2 idle checks (10 min grace)
            # Multi-exchange mode: exit after 24 idle checks (2 hours)
            max_idle = 2 if len(exchanges) == 1 else 24

            if idle_checks >= max_idle:
                logger.info("Market closed. %d idle checks reached (max %d). Exiting.", idle_checks, max_idle)
                break

            logger.info("Cycle %d: no markets open. Idle check %d/%d. Sleeping 5 min...", cycle, idle_checks, max_idle)
            time.sleep(300)
            continue
        else:
            run._idle_checks = 0  # Reset idle counter when markets are open

        logger.info("Cycle %d: refreshing %s (interval=%dm)", cycle, ",".join(open_markets), interval_min)

        for ex in open_markets:
            try:
                tickers, rows = refresh_exchange(conn, ex)
                logger.info("  %s: %d tickers, %d rows", ex, tickers, rows)
            except Exception as e:
                logger.error("  %s failed: %s", ex, e)
                # Reconnect on DB errors
                try:
                    conn.close()
                except Exception:
                    pass
                conn = get_conn()

        # Recount tickers periodically (every 10 cycles) in case watchlists changed
        if cycle % 10 == 0:
            all_tickers = []
            for ex in exchanges:
                all_tickers.extend(load_tickers(conn, ex))
            new_count = len(all_tickers)
            new_interval = compute_interval(new_count)
            if new_interval != interval_min:
                logger.info("Ticker count changed: %d → %d. Interval: %dm → %dm",
                           total_count, new_count, interval_min, new_interval)
                total_count = new_count
                interval_min = new_interval

        logger.info("Sleeping %d min until next cycle...", interval_min)
        time.sleep(interval_min * 60)

    conn.close()
    logger.info("── Intraday Runner stopped ──")


def main():
    ap = argparse.ArgumentParser(description="Self-throttling intraday data collector")
    ap.add_argument("--exchange", required=True,
                    help="Exchange code or 'all' for all markets")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    except ImportError:
        pass

    if args.exchange.upper() == "ALL":
        exchanges = list(MARKET_HOURS.keys())
    else:
        exchanges = [e.strip().upper() for e in args.exchange.split(",")]

    run(exchanges)


if __name__ == "__main__":
    main()
