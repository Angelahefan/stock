"""
agents/data_providers/postgres_provider.py
─────────────────────────────────────────────────────────────────────────────
OHLCV provider backed by datapai PostgreSQL tables.

Priority chain in tinyfish_signal_pipeline.py:
    PostgresProvider → PolygonProvider → YahooProvider

Reads:
  "1d"  → datapai.prices      (daily OHLCV, 9K stocks, 5yr history)
  "30m" → datapai.ohlcv_intraday (30m bars, monitored ~200 tickers)
  "5m"  → returns None (no 5m data stored — falls back to live providers)
  "1h"  → returns None (no 1h data stored — falls back to live providers)

Freshness checks:
  "1d"  : latest row must be within 2 trading days of today
  "30m" : latest bar must be within 35 minutes

Returns None when data is absent, stale, or the table doesn't have the
requested timeframe — downstream callers fall back to live providers.

Connection config: inherits from agents/stock_chat/db.py (same env vars).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from agents.data_providers.base import OHLCVProvider

logger = logging.getLogger(__name__)

# ── Freshness thresholds ──────────────────────────────────────────────────────
_DAILY_MAX_AGE_DAYS     = 2      # allow for weekend / public holiday gaps
_INTRADAY_MAX_AGE_MINS  = 35     # 30m bar + 5m grace

# ── Supported timeframes ──────────────────────────────────────────────────────
_DAILY_TF    = {"1d"}
_INTRADAY_TF = {"30m"}
_UNSUPPORTED = {"5m", "1h"}       # return None → fallback to live providers


class PostgresProvider(OHLCVProvider):
    """
    OHLCV provider reading from datapai.prices and datapai.ohlcv_intraday.

    Falls back gracefully (returns None) when:
      - Data is absent or stale
      - Timeframe not stored in DB (5m, 1h)
      - Any DB error
    """

    @property
    def source_name(self) -> str:
        return "datapai PostgreSQL"

    def fetch(
        self,
        ticker: str,
        timeframe: str,
        suffix: str,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV from Postgres.

        Parameters
        ----------
        ticker    : bare ticker (e.g. "BHP", "AAPL")
        timeframe : "1d" | "30m" | "5m" | "1h"
        suffix    : ".AX" for ASX, "" for US
        """
        if timeframe in _UNSUPPORTED:
            # 5m / 1h not stored — caller falls back to live API immediately
            return None

        exchange = "ASX" if suffix == ".AX" else "US"
        # Full symbol with suffix (e.g. "BHP.AX" for ASX tickers in ohlcv tables)
        full_sym = f"{ticker.upper()}{suffix}" if suffix else ticker.upper()

        if timeframe in _DAILY_TF:
            return self._fetch_daily(full_sym, ticker.upper(), exchange)
        if timeframe in _INTRADAY_TF:
            return self._fetch_intraday(full_sym, exchange)

        return None

    # ── Daily ─────────────────────────────────────────────────────────────────

    def _fetch_daily(
        self,
        full_sym: str,
        bare_ticker: str,
        exchange: str,
    ) -> Optional[pd.DataFrame]:
        """
        Read daily OHLCV from datapai.prices.

        datapai.prices stores:
          - ASX tickers as bare code (e.g. 'BHP') with exchange='ASX'
          - US tickers as bare code (e.g. 'AAPL') with exchange='US'
        Try both bare + full symbol to handle either convention.
        """
        try:
            from agents.stock_chat.db import query as db_query
        except ImportError:
            logger.debug("PostgresProvider: db module not available")
            return None

        sql = """
            SELECT date, open, high, low, close, adj_close, volume
            FROM   datapai.prices
            WHERE  ticker   = %s
              AND  exchange = %s
            ORDER  BY date DESC
            LIMIT  500
        """

        rows = []
        # Try bare ticker first (most common storage format)
        for sym_try in [bare_ticker, full_sym]:
            try:
                rows = db_query(sql, (sym_try, exchange))
                if rows:
                    break
            except Exception as exc:
                logger.warning("PostgresProvider daily query failed for %s: %s", sym_try, exc)
                return None

        if not rows:
            logger.debug("PostgresProvider: no daily data for %s [%s]", full_sym, exchange)
            return None

        # Freshness check
        latest_date = rows[0]["date"]  # already a date object from psycopg2
        if isinstance(latest_date, str):
            latest_date = date.fromisoformat(latest_date)
        today = date.today()
        age_days = (today - latest_date).days

        if age_days > _DAILY_MAX_AGE_DAYS:
            logger.info(
                "PostgresProvider: stale daily data for %s — latest=%s, age=%d days > %d",
                full_sym, latest_date, age_days, _DAILY_MAX_AGE_DAYS,
            )
            return None

        # Build DataFrame
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()

        # Rename to match OHLCVProvider contract: Open, High, Low, Close, Volume
        df = df.rename(columns={
            "open":      "Open",
            "high":      "High",
            "low":       "Low",
            "close":     "Close",
            "adj_close": "Adj Close",
            "volume":    "Volume",
        })

        # Ensure required columns exist (older rows may have NULLs before v1.6 migration)
        required = ["Open", "High", "Low", "Close", "Volume"]
        missing  = [c for c in required if c not in df.columns]
        if missing:
            logger.debug("PostgresProvider: daily data for %s missing columns %s", full_sym, missing)
            return None

        # Drop rows where Close is null (pre-migration rows)
        df = df.dropna(subset=["Close"])
        if df.empty:
            return None

        logger.debug(
            "PostgresProvider: daily %s [%s] — %d rows, latest=%s",
            full_sym, exchange, len(df), latest_date,
        )
        return df[required + ["Adj Close"]].copy() if "Adj Close" in df.columns else df[required].copy()

    # ── Intraday 30m ──────────────────────────────────────────────────────────

    def _fetch_intraday(self, full_sym: str, exchange: str) -> Optional[pd.DataFrame]:
        """
        Read 30m bars from datapai.ohlcv_intraday.
        """
        try:
            from agents.stock_chat.db import query as db_query
        except ImportError:
            return None

        sql = """
            SELECT ts, open, high, low, close, volume
            FROM   datapai.ohlcv_intraday
            WHERE  ticker   = %s
              AND  exchange = %s
              AND  ts       > NOW() - INTERVAL '5 days'
            ORDER  BY ts DESC
            LIMIT  500
        """

        try:
            rows = db_query(sql, (full_sym, exchange))
        except Exception as exc:
            logger.warning("PostgresProvider intraday query failed for %s: %s", full_sym, exc)
            return None

        if not rows:
            logger.debug("PostgresProvider: no intraday data for %s [%s]", full_sym, exchange)
            return None

        # Freshness check
        latest_ts = rows[0]["ts"]
        if not hasattr(latest_ts, "tzinfo") or latest_ts.tzinfo is None:
            from datetime import timezone as _tz
            latest_ts = latest_ts.replace(tzinfo=_tz.utc)

        now_utc = datetime.now(timezone.utc)
        age_mins = (now_utc - latest_ts).total_seconds() / 60

        if age_mins > _INTRADAY_MAX_AGE_MINS:
            logger.info(
                "PostgresProvider: stale intraday for %s — latest=%s, age=%.0f min > %d",
                full_sym, latest_ts, age_mins, _INTRADAY_MAX_AGE_MINS,
            )
            return None

        df = pd.DataFrame(rows)
        df = df.set_index("ts").sort_index()
        df = df.rename(columns={
            "open":   "Open",
            "high":   "High",
            "low":    "Low",
            "close":  "Close",
            "volume": "Volume",
        })

        df = df.dropna(subset=["Close"])
        if df.empty:
            return None

        logger.debug(
            "PostgresProvider: intraday %s [%s] — %d bars, latest=%s",
            full_sym, exchange, len(df), latest_ts,
        )
        return df[["Open", "High", "Low", "Close", "Volume"]].copy()

    # ── Convenience: check if DB has data for a ticker ───────────────────────

    def has_daily_data(self, ticker: str, exchange: str) -> bool:
        """Quick check — useful for monitoring / health endpoints."""
        df = self._fetch_daily(ticker, ticker, exchange)
        return df is not None and not df.empty

    def row_count(self, table: str = "prices", exchange: str | None = None) -> int:
        """Return approximate row count for monitoring."""
        try:
            from agents.stock_chat.db import query as db_query
            if exchange:
                rows = db_query(
                    f"SELECT COUNT(*) AS n FROM datapai.{table} WHERE exchange = %s",
                    (exchange,),
                )
            else:
                rows = db_query(f"SELECT COUNT(*) AS n FROM datapai.{table}")
            return rows[0]["n"] if rows else 0
        except Exception:
            return -1
