"""
scripts/lib/db_helpers.py
─────────────────────────────────────────────────────────────────────────────
Shared PostgreSQL helpers for OHLCV ETL scripts.

Uses the same connection config as agents/stock_chat/db.py so a single
.env / environment-variable block controls both application queries and
ETL ingestion.

Connection env vars (all optional):
  DATAPAI_PG_HOST      default: localhost
  DATAPAI_PG_PORT      default: 5434
  DATAPAI_PG_DB        default: postgres
  DATAPAI_PG_USER      default: postgres
  DATAPAI_PG_PASSWORD  default: postgres
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)

# ── Connection config ────────────────────────────────────────────────────────

_PG_HOST     = os.getenv("DATAPAI_PG_HOST", "localhost")
_PG_PORT     = int(os.getenv("DATAPAI_PG_PORT", "5434"))
_PG_DB       = os.getenv("DATAPAI_PG_DB", "postgres")
_PG_USER     = os.getenv("DATAPAI_PG_USER", "postgres")
_PG_PASSWORD = os.getenv("DATAPAI_PG_PASSWORD", "postgres")


def get_conn() -> psycopg2.extensions.connection:
    """Return a new psycopg2 connection to the datapai database."""
    # Airflow sets PGPORT=5432/PGHOST for its own DB. psycopg2 libpq picks
    # these up and ignores our explicit port= kwarg. Unset them temporarily.
    saved = {}
    for key in ("PGPORT", "PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD"):
        if key in os.environ:
            saved[key] = os.environ.pop(key)
    try:
        conn = psycopg2.connect(
            host=_PG_HOST,
            port=_PG_PORT,
            dbname=_PG_DB,
            user=_PG_USER,
            password=_PG_PASSWORD,
            options="-c search_path=datapai,public",
            connect_timeout=10,
        )
    finally:
        os.environ.update(saved)
    return conn


# ── Per-market intraday table mapping ────────────────────────────────────────

_INTRADAY_TABLES: dict[str, str] = {
    "US":   "ohlcv_intraday_us",
    "ASX":  "ohlcv_intraday_asx",
    "HKEX": "ohlcv_intraday_hkex",
    "HOSE": "ohlcv_intraday_hose",
    "SET":  "ohlcv_intraday_set",
    "KLSE": "ohlcv_intraday_klse",
    "IDX":  "ohlcv_intraday_idx",
    "SSE":  "ohlcv_intraday_sse",
    "SZSE": "ohlcv_intraday_szse",
    "LSE":  "ohlcv_intraday_lse",
    "TWSE": "ohlcv_intraday_twse",
    "SGX":  "ohlcv_intraday_sgx",
    "TSE":  "ohlcv_intraday_tse",
}


def _intraday_table(exchange: str) -> str:
    """Return the fully qualified per-market intraday table name."""
    tbl = _INTRADAY_TABLES.get(exchange.upper())
    if not tbl:
        raise ValueError(f"No intraday table mapping for exchange: {exchange}")
    return f"datapai.{tbl}"


# ═════════════════════════════════════════════════════════════════════════════
# Daily OHLCV helpers (datapai.prices)
# ═════════════════════════════════════════════════════════════════════════════

def df_to_daily_rows(
    df: pd.DataFrame,
    yf_symbol: str,
    exchange: str,
    source: str,
) -> list[tuple]:
    """
    Convert a yfinance daily DataFrame into a list of tuples for upsert.

    Parameters
    ----------
    df        : DataFrame with columns Open, High, Low, Close, Volume
                (DatetimeIndex = trade dates).
    yf_symbol : yfinance symbol (e.g. "AAPL", "BHP.AX").
    exchange  : exchange code (e.g. "US", "ASX").
    source    : data source label (e.g. "yahoo", "polygon").

    Returns
    -------
    list of (ticker, trade_date, open, high, low, close, adj_close, volume,
             exchange, source) tuples.
    """
    rows: list[tuple] = []
    # Strip exchange suffix to get base ticker for storage
    ticker = yf_symbol.upper()

    for idx, row in df.iterrows():
        close = row.get("Close")
        if pd.isna(close) or close == 0:
            continue

        # Handle pandas Timestamp → date string
        if isinstance(idx, pd.Timestamp):
            trade_date = idx.strftime("%Y-%m-%d")
        elif isinstance(idx, (date, datetime)):
            trade_date = idx.strftime("%Y-%m-%d")
        else:
            trade_date = str(idx)

        open_  = float(row.get("Open") or 0)
        high   = float(row.get("High") or 0)
        low    = float(row.get("Low") or 0)
        close_f = float(close)
        adj    = float(row.get("Adj Close", close_f))
        volume = int(row.get("Volume") or 0)

        rows.append((
            ticker, trade_date, open_, high, low, close_f, adj,
            volume, exchange, source,
        ))

    return rows


def upsert_daily_rows(
    rows: list[tuple],
    batch_label: str = "",
) -> int:
    """
    Bulk-upsert daily OHLCV rows into datapai.prices.

    Each row: (ticker, trade_date, open, high, low, close, adj_close,
               volume, exchange, source).

    Returns number of rows upserted.
    """
    if not rows:
        return 0

    sql = """
        INSERT INTO datapai.prices
            (ticker, trade_date, open, high, low, close, adj_close,
             volume, exchange, source)
        VALUES %s
        ON CONFLICT (ticker, trade_date, exchange)
        DO UPDATE SET
            open      = EXCLUDED.open,
            high      = EXCLUDED.high,
            low       = EXCLUDED.low,
            close     = EXCLUDED.close,
            adj_close = EXCLUDED.adj_close,
            volume    = EXCLUDED.volume,
            source    = EXCLUDED.source
    """

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                execute_values(cur, sql, rows, page_size=500)
            conn.commit()
        logger.info("Upserted %d daily rows [%s]", len(rows), batch_label)
        return len(rows)
    except Exception as exc:
        logger.error("upsert_daily_rows failed [%s]: %s", batch_label, exc)
        raise


def get_latest_dates(
    conn: psycopg2.extensions.connection,
    exchange: str,
) -> dict[str, str]:
    """
    Return {ticker: latest_trade_date} for all tickers in a given exchange.

    Parameters
    ----------
    conn     : psycopg2 connection.
    exchange : exchange code.

    Returns
    -------
    dict mapping ticker to its most recent trade_date string.
    """
    sql = """
        SELECT ticker, MAX(trade_date) AS latest
        FROM   datapai.prices
        WHERE  exchange = %s
        GROUP  BY ticker
    """
    with conn.cursor() as cur:
        cur.execute(sql, (exchange,))
        return {row[0]: row[1] for row in cur.fetchall()}


# ═════════════════════════════════════════════════════════════════════════════
# Intraday OHLCV helpers (datapai.ohlcv_intraday_{exchange})
# ═════════════════════════════════════════════════════════════════════════════

def df_to_intraday_rows(
    df: pd.DataFrame,
    ticker: str,
    exchange: str,
    source: str,
) -> list[tuple]:
    """
    Convert a 30m / 5m intraday DataFrame into upsert tuples.

    Parameters
    ----------
    df       : DataFrame with columns open/Open, high/High, low/Low,
               close/Close, volume/Volume. DatetimeIndex = bar timestamps.
    ticker   : base ticker (e.g. "AAPL", "BHP.AX").
    exchange : exchange code.
    source   : "polygon" | "yahoo" | "sina" etc.

    Returns
    -------
    list of (ticker, ts, open, high, low, close, volume, exchange, source).
    """
    rows: list[tuple] = []
    ticker_up = ticker.upper()

    for ts_idx, row in df.iterrows():
        # Handle both capitalised and lowercase column names
        close = row.get("Close", row.get("close"))
        if pd.isna(close) or close == 0:
            continue

        open_  = float(row.get("Open",   row.get("open", 0)) or 0)
        high   = float(row.get("High",   row.get("high", 0)) or 0)
        low    = float(row.get("Low",    row.get("low", 0)) or 0)
        close_f = float(close)
        volume = int(row.get("Volume", row.get("volume", 0)) or 0)

        # Convert timestamp to string if needed
        if isinstance(ts_idx, pd.Timestamp):
            ts_str = ts_idx.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(ts_idx, datetime):
            ts_str = ts_idx.strftime("%Y-%m-%d %H:%M:%S")
        else:
            ts_str = str(ts_idx)

        rows.append((ticker_up, ts_str, open_, high, low, close_f, volume, exchange, source))

    return rows


def upsert_intraday_rows(
    rows: list[tuple],
    batch_label: str = "",
    exchange: str | None = None,
) -> int:
    """
    Bulk-upsert intraday bars into per-market table (ohlcv_intraday_{exchange}).

    Each row: (ticker, ts, open, high, low, close, volume, exchange, source).

    Parameters
    ----------
    rows        : list of 9-element tuples.
    batch_label : human-readable label for logging.
    exchange    : exchange code. If None, derived from the first row's
                  exchange field (index 7).

    Returns number of rows upserted.
    """
    if not rows:
        return 0

    # Determine exchange from rows if not explicitly passed
    if exchange is None:
        exchange = rows[0][7]

    table = _intraday_table(exchange)

    sql = f"""
        INSERT INTO {table}
            (ticker, ts, open, high, low, close, volume, exchange, source)
        VALUES %s
        ON CONFLICT (ticker, ts)
        DO UPDATE SET
            open   = EXCLUDED.open,
            high   = EXCLUDED.high,
            low    = EXCLUDED.low,
            close  = EXCLUDED.close,
            volume = EXCLUDED.volume,
            source = EXCLUDED.source
    """

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                execute_values(cur, sql, rows, page_size=500)
            conn.commit()
        logger.info("Upserted %d intraday rows into %s [%s]", len(rows), table, batch_label)
        return len(rows)
    except Exception as exc:
        logger.error("upsert_intraday_rows failed [%s]: %s", batch_label, exc)
        raise


def purge_old_intraday(days: int = 60) -> int:
    """
    Delete intraday bars older than `days` across all per-market tables.
    Returns total rows deleted.
    """
    total = 0
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for exchange, tbl in _INTRADAY_TABLES.items():
                    cur.execute(
                        f"DELETE FROM datapai.{tbl} WHERE ts < NOW() - INTERVAL '%s days'",
                        (days,),
                    )
                    n = cur.rowcount
                    if n:
                        logger.info("Purged %d old rows from datapai.%s", n, tbl)
                    total += n
            conn.commit()
    except Exception as exc:
        logger.error("purge_old_intraday failed: %s", exc)
    return total


def archive_and_truncate_intraday(exchange: str) -> tuple[int, int]:
    """
    Archive yesterday's (and older) intraday bars, then truncate the live table.

    Flow:
      1. INSERT INTO {table}_archive SELECT * FROM {table} WHERE ts::date < today
      2. DELETE FROM {table} WHERE ts::date < today

    Parameters
    ----------
    exchange : exchange code (e.g. "US", "ASX").

    Returns
    -------
    (archived_count, deleted_count) tuple.
    """
    table = _intraday_table(exchange)
    archive_table = f"{table}_archive"

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Archive rows from before today
                cur.execute(f"""
                    INSERT INTO {archive_table}
                    SELECT * FROM {table}
                    WHERE ts::date < CURRENT_DATE
                    ON CONFLICT DO NOTHING
                """)
                archived = cur.rowcount

                # Remove archived rows from live table
                cur.execute(f"""
                    DELETE FROM {table}
                    WHERE ts::date < CURRENT_DATE
                """)
                deleted = cur.rowcount

            conn.commit()

        if archived:
            logger.info("Archived %d rows from %s → %s", archived, table, archive_table)
        return (archived, deleted)

    except Exception as exc:
        logger.error("archive_and_truncate_intraday failed for %s: %s", exchange, exc)
        raise


# ═════════════════════════════════════════════════════════════════════════════
# TA indicators helpers (datapai.ta_indicators)
# ═════════════════════════════════════════════════════════════════════════════

def upsert_ta_indicators(
    rows: list[tuple],
    batch_label: str = "",
) -> int:
    """
    Bulk-upsert TA indicator rows into datapai.ta_indicators.

    Each row is a tuple matching the column order produced by
    ta_compute.indicators_to_row():
      (ticker, exchange, timeframe, ts, trade_date,
       open, high, low, close, volume, change_pct,
       rsi, rsi_label,
       macd_line, macd_signal, macd_hist, macd_label,
       bb_upper, bb_middle, bb_lower, bb_pct, bb_label,
       ema_5, ema_9, ema_10, ema_20, ema_21, ema_30, ema_50, ema_200,
       stoch_k, stoch_d, stoch_label,
       atr, atr_pct,
       adx, plus_di, minus_di, adx_label,
       obv, obv_trend,
       vol_ma_5, vol_ma_10, vol_ma_30,
       vol_ratio_5, vol_ratio_10, vol_ratio_30,
       overall_signal, signal_score,
       quality_ok, low_volume, suspicious_move,
       source)

    Returns number of rows upserted.
    """
    if not rows:
        return 0

    sql = """
        INSERT INTO datapai.ta_indicators (
            ticker, exchange, timeframe, ts, trade_date,
            open, high, low, close, volume, change_pct,
            rsi, rsi_label,
            macd_line, macd_signal, macd_hist, macd_label,
            bb_upper, bb_middle, bb_lower, bb_pct, bb_label,
            ema_5, ema_9, ema_10, ema_20, ema_21, ema_30, ema_50, ema_200,
            stoch_k, stoch_d, stoch_label,
            atr, atr_pct,
            adx, plus_di, minus_di, adx_label,
            obv, obv_trend,
            vol_ma_5, vol_ma_10, vol_ma_30,
            vol_ratio_5, vol_ratio_10, vol_ratio_30,
            overall_signal, signal_score,
            quality_ok, low_volume, suspicious_move,
            source
        )
        VALUES %s
        ON CONFLICT (ticker, exchange, timeframe, ts)
        DO UPDATE SET
            trade_date      = EXCLUDED.trade_date,
            open            = EXCLUDED.open,
            high            = EXCLUDED.high,
            low             = EXCLUDED.low,
            close           = EXCLUDED.close,
            volume          = EXCLUDED.volume,
            change_pct      = EXCLUDED.change_pct,
            rsi             = EXCLUDED.rsi,
            rsi_label       = EXCLUDED.rsi_label,
            macd_line       = EXCLUDED.macd_line,
            macd_signal     = EXCLUDED.macd_signal,
            macd_hist       = EXCLUDED.macd_hist,
            macd_label      = EXCLUDED.macd_label,
            bb_upper        = EXCLUDED.bb_upper,
            bb_middle       = EXCLUDED.bb_middle,
            bb_lower        = EXCLUDED.bb_lower,
            bb_pct          = EXCLUDED.bb_pct,
            bb_label        = EXCLUDED.bb_label,
            ema_5           = EXCLUDED.ema_5,
            ema_9           = EXCLUDED.ema_9,
            ema_10          = EXCLUDED.ema_10,
            ema_20          = EXCLUDED.ema_20,
            ema_21          = EXCLUDED.ema_21,
            ema_30          = EXCLUDED.ema_30,
            ema_50          = EXCLUDED.ema_50,
            ema_200         = EXCLUDED.ema_200,
            stoch_k         = EXCLUDED.stoch_k,
            stoch_d         = EXCLUDED.stoch_d,
            stoch_label     = EXCLUDED.stoch_label,
            atr             = EXCLUDED.atr,
            atr_pct         = EXCLUDED.atr_pct,
            adx             = EXCLUDED.adx,
            plus_di         = EXCLUDED.plus_di,
            minus_di        = EXCLUDED.minus_di,
            adx_label       = EXCLUDED.adx_label,
            obv             = EXCLUDED.obv,
            obv_trend       = EXCLUDED.obv_trend,
            vol_ma_5        = EXCLUDED.vol_ma_5,
            vol_ma_10       = EXCLUDED.vol_ma_10,
            vol_ma_30       = EXCLUDED.vol_ma_30,
            vol_ratio_5     = EXCLUDED.vol_ratio_5,
            vol_ratio_10    = EXCLUDED.vol_ratio_10,
            vol_ratio_30    = EXCLUDED.vol_ratio_30,
            overall_signal  = EXCLUDED.overall_signal,
            signal_score    = EXCLUDED.signal_score,
            quality_ok      = EXCLUDED.quality_ok,
            low_volume      = EXCLUDED.low_volume,
            suspicious_move = EXCLUDED.suspicious_move,
            source          = EXCLUDED.source,
            computed_at     = NOW()
    """

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                execute_values(cur, sql, rows, page_size=200)
            conn.commit()
        logger.info("Upserted %d TA rows [%s]", len(rows), batch_label)
        return len(rows)
    except Exception as exc:
        logger.error("upsert_ta_indicators failed [%s]: %s", batch_label, exc)
        raise
