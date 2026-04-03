"""
scripts/lib/ta_compute.py
─────────────────────────────────────────────────────────────────────────────
Shared logic for pre-computing TA indicators and writing them to
datapai.ta_indicators.

Used by:
  compute_ta_intraday.py  — 30m bars  (runs every 30min during market hours)
  compute_ta_daily.py     — 1d bars   (runs nightly after EOD rollup)
  compute_ta_weekly.py    — 1w bars   (runs Sunday UTC)
  compute_ta_monthly.py   — 1mo bars  (runs 1st of month)

Core flow per ticker
────────────────────
  1. Fetch OHLCV bars from datapai.prices / datapai.ohlcv_intraday
     (or from the live Polygon / yfinance provider for intraday).
  2. For weekly/monthly: resample daily bars with pandas.
  3. Call agents.technical_analysis.calc_indicators(df).
  4. Build a upsert tuple and write to datapai.ta_indicators.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ── timeframe label used in ta_indicators.timeframe column ────────────────────
TF_30M  = "30m"
TF_1D   = "1d"
TF_1W   = "1w"
TF_1MO  = "1mo"


# ── Fetch helpers ─────────────────────────────────────────────────────────────

def fetch_daily_bars(
    ticker: str,
    exchange: str,
    lookback_days: int = 300,
) -> Optional[pd.DataFrame]:
    """
    Fetch daily OHLCV bars for a ticker from datapai.prices.

    Returns a DataFrame with columns [Open, High, Low, Close, Volume]
    indexed by trade_date (DATE), or None if no data found.
    We fetch `lookback_days` days of history so that slow indicators
    (EMA200, ADX) have enough warm-up bars.
    """
    from scripts.lib.db_helpers import get_conn

    sql = """
        SELECT trade_date, open, high, low, close, volume
        FROM   datapai.prices
        WHERE  ticker   = %(ticker)s
          AND  exchange = %(exchange)s
          AND  trade_date::date >= CURRENT_DATE - %(days)s
        ORDER  BY trade_date ASC
    """
    try:
        with get_conn() as conn:
            df = pd.read_sql(
                sql,
                conn,
                params={"ticker": ticker, "exchange": exchange, "days": lookback_days},
            )
    except Exception as exc:
        logger.warning("fetch_daily_bars failed for %s/%s: %s", ticker, exchange, exc)
        return None

    if df.empty:
        return None

    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.set_index("trade_date")
    df.columns = [c.capitalize() for c in df.columns]
    return df


def fetch_intraday_bars(
    ticker: str,
    exchange: str,
    lookback_days: int = 10,
) -> Optional[pd.DataFrame]:
    """
    Fetch 30-minute intraday bars from datapai.ohlcv_intraday.

    Returns a DataFrame[Open, High, Low, Close, Volume] indexed by ts
    (TIMESTAMPTZ), or None if no data found.
    """
    from scripts.lib.db_helpers import get_conn

    sql = """
        SELECT ts, open, high, low, close, volume
        FROM   datapai.ohlcv_intraday
        WHERE  ticker   = %(ticker)s
          AND  exchange = %(exchange)s
          AND  ts >= NOW() - INTERVAL '%(days)s days'
        ORDER  BY ts ASC
    """
    # psycopg2 can't interpolate INTERVAL %(days)s safely with %s, build it manually
    sql = f"""
        SELECT ts, open, high, low, close, volume
        FROM   datapai.ohlcv_intraday
        WHERE  ticker   = %(ticker)s
          AND  exchange = %(exchange)s
          AND  ts >= NOW() - INTERVAL '{lookback_days} days'
        ORDER  BY ts ASC
    """
    try:
        with get_conn() as conn:
            df = pd.read_sql(
                sql,
                conn,
                params={"ticker": ticker, "exchange": exchange},
            )
    except Exception as exc:
        logger.warning("fetch_intraday_bars failed for %s/%s: %s", ticker, exchange, exc)
        return None

    if df.empty:
        return None

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")
    df.columns = [c.capitalize() for c in df.columns]
    return df


def resample_daily_to_weekly(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    Resample daily OHLCV bars to weekly (week ending Friday).
    Requires a DatetimeIndex.
    """
    if df is None or df.empty:
        return None
    weekly = df.resample("W-FRI").agg({
        "Open":   "first",
        "High":   "max",
        "Low":    "min",
        "Close":  "last",
        "Volume": "sum",
    }).dropna(subset=["Close"])
    return weekly if not weekly.empty else None


def resample_daily_to_monthly(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    Resample daily OHLCV bars to monthly (month-start anchor).
    Requires a DatetimeIndex.
    """
    if df is None or df.empty:
        return None
    monthly = df.resample("MS").agg({
        "Open":   "first",
        "High":   "max",
        "Low":    "min",
        "Close":  "last",
        "Volume": "sum",
    }).dropna(subset=["Close"])
    return monthly if not monthly.empty else None


# ── Row builder ───────────────────────────────────────────────────────────────

def indicators_to_row(
    ind: dict,
    ticker: str,
    exchange: str,
    timeframe: str,
    ts: datetime,
    trade_date: date,
    source: str,
) -> tuple:
    """
    Convert a calc_indicators() dict + metadata into a upsert tuple matching
    the column order expected by upsert_ta_indicators().
    """
    def _g(key, default=None):
        return ind.get(key, default)

    return (
        ticker, exchange, timeframe, ts, trade_date,
        # price snapshot
        _g("open"),  _g("high"),  _g("low"),  _g("close"),
        _g("volume"), _g("change_pct"),
        # RSI
        _g("rsi"),        _g("rsi_label"),
        # MACD
        _g("macd_line"),  _g("macd_signal"), _g("macd_hist"), _g("macd_label"),
        # Bollinger
        _g("bb_upper"),   _g("bb_middle"),   _g("bb_lower"),
        _g("bb_pct"),     _g("bb_label"),
        # EMAs
        _g("ema_5"),  _g("ema_9"),  _g("ema_10"), _g("ema_20"),
        _g("ema_21"), _g("ema_30"), _g("ema_50"), _g("ema_200"),
        # Stochastic
        _g("stoch_k"),    _g("stoch_d"),     _g("stoch_label"),
        # ATR
        _g("atr"),        _g("atr_pct"),
        # ADX + DI
        _g("adx"),        _g("plus_di"),     _g("minus_di"),  _g("adx_label"),
        # OBV
        _g("obv"),        _g("obv_trend"),
        # Volume MAs
        _g("vol_ma_5"),   _g("vol_ma_10"),   _g("vol_ma_30"),
        _g("vol_ratio_5"), _g("vol_ratio_10"), _g("vol_ratio_30"),
        # Overall signal
        _g("overall_signal"), _g("signal_score"),
        # Quality flags
        _g("quality_ok", True), _g("low_volume", False), _g("suspicious_move", False),
        # Source
        source,
    )


# ── Batch compute + store ─────────────────────────────────────────────────────

def compute_and_store(
    df: pd.DataFrame,
    ticker: str,
    exchange: str,
    timeframe: str,
    source: str,
    dry_run: bool = False,
) -> int:
    """
    Run calc_indicators on the last bar of `df`, then upsert to ta_indicators.

    For intraday (30m): called once per ticker per run — stores the latest bar.
    For daily/weekly/monthly: called once per ticker — stores ALL bars in df
    so historical data is backfilled on first run.

    Returns number of rows written (0 on skip/dry-run/error).
    """
    from agents.technical_analysis import calc_indicators
    from scripts.lib.db_helpers import upsert_ta_indicators

    if df is None or len(df) < 2:
        return 0

    rows = []

    # For daily/weekly/monthly we backfill all bars; for intraday only latest.
    # We identify "intraday" by timeframe code.
    if timeframe == TF_30M:
        # Intraday: compute indicators on the full history,
        # but only store the very last bar (most recent 30m candle).
        try:
            ind = calc_indicators(df)
        except Exception as exc:
            logger.warning("calc_indicators failed for %s [%s]: %s", ticker, timeframe, exc)
            return 0
        last_ts    = df.index[-1]
        ts_dt      = _to_utc_datetime(last_ts)
        trade_date = ts_dt.date()
        rows.append(indicators_to_row(ind, ticker, exchange, timeframe, ts_dt, trade_date, source))

    else:
        # Daily / Weekly / Monthly: backfill all bars.
        # We use a sliding window so each bar gets its own full indicator set.
        for i in range(len(df)):
            # Need at least 2 bars for change_pct
            if i < 1:
                continue
            sub_df = df.iloc[: i + 1]
            try:
                ind = calc_indicators(sub_df)
            except Exception as exc:
                logger.debug("calc_indicators bar %d for %s: %s", i, ticker, exc)
                continue
            bar_idx    = df.index[i]
            ts_dt      = _to_utc_datetime(bar_idx)
            trade_date = ts_dt.date()
            rows.append(indicators_to_row(
                ind, ticker, exchange, timeframe, ts_dt, trade_date, source
            ))

    if not rows:
        return 0

    if dry_run:
        logger.info("[DRY RUN] Would upsert %d TA rows for %s [%s]", len(rows), ticker, timeframe)
        return len(rows)

    upsert_ta_indicators(rows, batch_label=f"{ticker} {timeframe}")
    return len(rows)


def _to_utc_datetime(idx_val) -> datetime:
    """Convert a pandas Timestamp / date to a tz-aware UTC datetime."""
    if isinstance(idx_val, datetime):
        if idx_val.tzinfo is None:
            return idx_val.replace(tzinfo=timezone.utc)
        return idx_val.astimezone(timezone.utc)
    if isinstance(idx_val, pd.Timestamp):
        ts = idx_val.to_pydatetime()
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    # date object → midnight UTC
    d = idx_val
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


# ── Incremental (latest-only) helper ─────────────────────────────────────────

def get_latest_ts(ticker: str, exchange: str, timeframe: str) -> Optional[datetime]:
    """
    Return the most recent ts already in ta_indicators for this
    ticker/exchange/timeframe, so incremental runs can skip already-stored bars.
    Returns None if no rows exist yet.
    """
    from scripts.lib.db_helpers import get_conn

    sql = """
        SELECT MAX(ts) AS latest
        FROM   datapai.ta_indicators
        WHERE  ticker    = %(ticker)s
          AND  exchange  = %(exchange)s
          AND  timeframe = %(timeframe)s
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, {"ticker": ticker, "exchange": exchange, "timeframe": timeframe})
                row = cur.fetchone()
                return row[0] if row and row[0] is not None else None
    except Exception as exc:
        logger.warning("get_latest_ts failed: %s", exc)
        return None
