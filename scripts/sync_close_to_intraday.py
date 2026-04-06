#!/usr/bin/env python3
"""
sync_close_to_intraday.py — Insert correct EOD close into intraday table.

After the EOD refresh_workers fetch correct daily close from Yahoo,
this script copies today's close into ohlcv_intraday as a 16:00 bar.
The frontend reads the latest intraday bar, so it automatically
picks up the correct close — no frontend changes needed.

Usage:
    python3 scripts/sync_close_to_intraday.py --exchange US
    python3 scripts/sync_close_to_intraday.py --exchange ASX
"""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
import pytz

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.lib.db_helpers import get_conn, upsert_intraday_rows
from scripts.lib.log_setup import setup_logging

logger = setup_logging("sync_close_to_intraday")

# Per-market intraday tables
_INTRADAY_TABLES = {
    "US": "ohlcv_intraday_us", "ASX": "ohlcv_intraday_asx",
    "HKEX": "ohlcv_intraday_hkex", "HOSE": "ohlcv_intraday_hose",
    "SET": "ohlcv_intraday_set", "KLSE": "ohlcv_intraday_klse",
    "IDX": "ohlcv_intraday_idx", "SSE": "ohlcv_intraday_sse",
    "SZSE": "ohlcv_intraday_szse", "LSE": "ohlcv_intraday_lse",
    "TWSE": "ohlcv_intraday_twse",
    "SGX": "ohlcv_intraday_sgx",
    "TSE": "ohlcv_intraday_tse",
}

def _intraday_table(exchange: str) -> str:
    tbl = _INTRADAY_TABLES.get(exchange.upper())
    if not tbl:
        raise ValueError(f"Unknown exchange: {exchange}")
    return f"datapai.{tbl}"

def _load_market_close() -> dict:
    """Load market close times from DB (datapai.market_trading_hours)."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT exchange, timezone, close_hour, close_minute
                    FROM datapai.market_trading_hours WHERE is_active = TRUE
                """)
                result = {}
                for ex, tz, ch, cm in cur.fetchall():
                    result[ex] = {"tz": tz, "hour": ch, "minute": cm}
                logger.info("Loaded market close times from DB: %d markets", len(result))
                return result
    except Exception as e:
        logger.warning("Failed to load from DB, using fallback: %s", e)
        return {"US": {"tz": "America/New_York", "hour": 16, "minute": 0}}

MARKET_CLOSE = _load_market_close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange", required=True)
    args = parser.parse_args()
    exchange = args.exchange.upper()

    mkt = MARKET_CLOSE.get(exchange)
    if not mkt:
        logger.error("Unknown exchange: %s", exchange)
        sys.exit(1)

    with get_conn() as conn:
        _run(conn, exchange, mkt)


def _run(conn, exchange, mkt):
    cur = conn.cursor()

    # Find the latest trade date for this exchange (not hardcoded to "today")
    # Handles timezone differences — e.g. ASX March 30 data when it's already March 31 in Sydney
    tz = pytz.timezone(mkt["tz"])
    cur.execute("""
        SELECT MAX(trade_date) FROM datapai.prices WHERE exchange = %s
    """, [exchange])
    row = cur.fetchone()
    latest_trade_date = row[0] if row else None

    if not latest_trade_date:
        logger.info("No EOD data for %s — skipping", exchange)
        return

    today_local = str(latest_trade_date)

    # Read latest day's EOD close from datapai.prices
    cur.execute("""
        SELECT ticker, open, high, low, close, volume
        FROM datapai.prices
        WHERE exchange = %s AND trade_date = %s
    """, [exchange, today_local])
    eod_rows = cur.fetchall()

    if not eod_rows:
        logger.info("No EOD data for %s on %s — skipping", exchange, today_local)
        return

    # Get the last intraday bar's close per ticker (= opening price of the closing bar)
    # and sum of intraday volume (to compute residual volume for closing bar)
    tickers = [r[0] for r in eod_rows]
    placeholders = ",".join(["%s"] * len(tickers))
    tbl = _intraday_table(exchange)
    cur.execute(f"""
        SELECT ticker,
               (ARRAY_AGG(close ORDER BY ts DESC))[1] AS last_bar_close,
               COALESCE(SUM(volume), 0) AS total_intraday_vol
        FROM {tbl}
        WHERE ticker IN ({placeholders})
          AND ts::date = %s
        GROUP BY ticker
    """, tickers + [today_local])
    last_bar_map = {}
    for row in cur.fetchall():
        last_bar_map[row[0]] = {"last_close": float(row[1]) if row[1] else None, "vol_sum": int(row[2])}

    # Build closing bar timestamp: trade_date at market close time
    # Uses the actual trade date from prices table, NOT today's date
    close_ts = f"{today_local} {mkt['hour']:02d}:{mkt['minute']:02d}:00"

    # Build intraday rows: (ticker, ts, open, high, low, close, volume, exchange, source)
    # Transform logic for the synthetic closing bar:
    #   open  = last intraday bar's close (where price was at 15:55)
    #   close = EOD daily close (official closing auction price)
    #   high  = max(open, close)
    #   low   = min(open, close)
    #   volume = daily volume - sum of intraday volumes (residual closing auction volume)
    intraday_rows = []
    for ticker, _o, _h, _l, c, v in eod_rows:
        close_f = float(c)
        info = last_bar_map.get(ticker, {})
        bar_open = info.get("last_close") or close_f
        bar_high = max(bar_open, close_f)
        bar_low = min(bar_open, close_f)
        daily_vol = int(v or 0)
        intraday_vol = info.get("vol_sum", 0)
        bar_vol = max(daily_vol - intraday_vol, 0)

        intraday_rows.append((
            ticker, close_ts,
            bar_open, bar_high, bar_low, close_f,
            bar_vol, exchange, "eod_sync",
        ))

    # Upsert into intraday table — ON CONFLICT updates the close price
    n = upsert_intraday_rows(intraday_rows, batch_label="eod_close", exchange=exchange)

    logger.info("Synced %d EOD closing bars into intraday for %s @ %s", n, exchange, close_ts)


if __name__ == "__main__":
    main()
