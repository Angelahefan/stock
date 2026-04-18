"""
core/config/exchange_registry.py
─────────────────────────────────────────────────────────────────────────────
DB-driven exchange/market configuration — single source of truth.

Replaces all hardcoded SUFFIX_MAP, ALL_EXCHANGES, ASIA_EXCHANGES,
US_EXCHANGES, _FALLBACK_MARKET_HOURS, and CONTEXT_MAP scattered across
scripts and agents.

Tables used:
    datapai.exchange_config          — yf_suffix, region, data_provider, batch_size
    datapai.market_trading_hours     — timezone, open/close hours, is_active
    datapai.exchange_ref             — currency, symbol, country
    datapai.ticker_context_config    — sector ETF, commodity, FX per ticker

Thread-safe, singleton, 5-minute cache with graceful DB-unavailable fallback.

Usage:
    from core.config.exchange_registry import registry

    suffix = registry.get_suffix("ASX")         # ".AX"
    all_ex = registry.get_all_exchanges()        # ["US", "ASX", "HKEX", ...]
    asia   = registry.get_exchanges_by_region("asia")  # ["ASX", "HKEX", ...]
    hours  = registry.get_market_hours("US")     # {"tz": "America/New_York", ...}
    ctx    = registry.get_context_config("BHP")  # {"sector_etf": "XMM.AX", ...}
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Fallback data (used when DB is unreachable) ─────────────────────────────

_FALLBACK_EXCHANGE_CONFIG = {
    "US":   {"yf_suffix": "",    "region": "us",     "data_provider": "yahoo", "batch_size": 500},
    "ASX":  {"yf_suffix": ".AX", "region": "asia",   "data_provider": "yahoo", "batch_size": 200},
    "HKEX": {"yf_suffix": ".HK", "region": "asia",   "data_provider": "yahoo", "batch_size": 300},
    "HOSE": {"yf_suffix": ".VN", "region": "asia",   "data_provider": "yahoo", "batch_size": 200},
    "HNX":  {"yf_suffix": ".VN", "region": "asia",   "data_provider": "yahoo", "batch_size": 200},
    "SET":  {"yf_suffix": ".BK", "region": "asia",   "data_provider": "yahoo", "batch_size": 300},
    "KLSE": {"yf_suffix": ".KL", "region": "asia",   "data_provider": "yahoo", "batch_size": 300},
    "IDX":  {"yf_suffix": ".JK", "region": "asia",   "data_provider": "yahoo", "batch_size": 300},
    "SSE":  {"yf_suffix": ".SS", "region": "asia",   "data_provider": "yahoo", "batch_size": 300},
    "SZSE": {"yf_suffix": ".SZ", "region": "asia",   "data_provider": "yahoo", "batch_size": 300},
    "LSE":  {"yf_suffix": ".L",  "region": "europe", "data_provider": "yahoo", "batch_size": 300},
    "TSE":  {"yf_suffix": ".T",  "region": "asia",   "data_provider": "yahoo", "batch_size": 300},
    "TWSE": {"yf_suffix": ".TW", "region": "asia",   "data_provider": "yahoo", "batch_size": 300},
    "SGX":  {"yf_suffix": ".SI", "region": "asia",   "data_provider": "yahoo", "batch_size": 300},
}

_FALLBACK_MARKET_HOURS = {
    "US":   {"tz": "America/New_York",    "open": (9, 30), "close": (16, 0)},
    "ASX":  {"tz": "Australia/Sydney",     "open": (10, 0), "close": (16, 0)},
    "HKEX": {"tz": "Asia/Hong_Kong",       "open": (9, 30), "close": (16, 0)},
    "HOSE": {"tz": "Asia/Ho_Chi_Minh",     "open": (9, 0),  "close": (14, 30)},
    "SET":  {"tz": "Asia/Bangkok",          "open": (10, 0), "close": (16, 30)},
    "KLSE": {"tz": "Asia/Kuala_Lumpur",     "open": (9, 0),  "close": (17, 0)},
    "IDX":  {"tz": "Asia/Jakarta",          "open": (9, 0),  "close": (16, 0)},
    "TSE":  {"tz": "Asia/Tokyo",            "open": (9, 0),  "close": (15, 0),
             "lunch_start": (11, 30), "lunch_end": (12, 30)},
    "SSE":  {"tz": "Asia/Shanghai",         "open": (9, 30), "close": (15, 0),
             "lunch_start": (11, 30), "lunch_end": (13, 0)},
    "SZSE": {"tz": "Asia/Shanghai",         "open": (9, 30), "close": (15, 0),
             "lunch_start": (11, 30), "lunch_end": (13, 0)},
    "LSE":  {"tz": "Europe/London",         "open": (8, 0),  "close": (16, 30)},
    "TWSE": {"tz": "Asia/Taipei",           "open": (9, 0),  "close": (13, 30)},
    "SGX":  {"tz": "Asia/Singapore",        "open": (9, 0),  "close": (17, 0)},
}

CACHE_TTL_SECONDS = 300  # 5 minutes


def _get_db_connection():
    """Get a PostgreSQL connection using standard datapai env vars."""
    import psycopg2
    return psycopg2.connect(
        host=os.environ.get("DATAPAI_PG_HOST", os.environ.get("PGHOST", "localhost")),
        port=int(os.environ.get("DATAPAI_PG_PORT", os.environ.get("PGPORT", "5432"))),
        dbname=os.environ.get("DATAPAI_PG_DB", os.environ.get("PGDATABASE", "postgres")),
        user=os.environ.get("DATAPAI_PG_USER", os.environ.get("PGUSER", "postgres")),
        password=os.environ.get("DATAPAI_PG_PASSWORD", os.environ.get("PGPASSWORD", "postgres")),
    )


class ExchangeRegistry:
    """Thread-safe, cached exchange configuration loaded from DB."""

    def __init__(self, cache_ttl: int = CACHE_TTL_SECONDS):
        self._lock = threading.Lock()
        self._cache_ttl = cache_ttl
        # Exchange config cache
        self._exchange_config: Dict[str, Dict[str, Any]] = {}
        self._exchange_config_ts: float = 0
        # Market hours cache
        self._market_hours: Dict[str, Dict[str, Any]] = {}
        self._market_hours_ts: float = 0
        # Ticker context cache
        self._ticker_context: Dict[str, Dict[str, Any]] = {}
        self._ticker_context_ts: float = 0

    # ── Exchange Config ──────────────────────────────────────────────────────

    def _load_exchange_config(self) -> Dict[str, Dict[str, Any]]:
        """Load from datapai.exchange_config table."""
        try:
            conn = _get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT exchange, yf_suffix, region, data_provider, batch_size
                FROM datapai.exchange_config
                WHERE is_active = TRUE
                ORDER BY exchange
            """)
            result = {}
            for row in cur.fetchall():
                ex, suffix, region, provider, batch = row
                result[ex] = {
                    "yf_suffix": suffix,
                    "region": region,
                    "data_provider": provider,
                    "batch_size": batch,
                }
            cur.close()
            conn.close()
            if result:
                logger.debug("Loaded exchange config from DB: %d exchanges", len(result))
                return result
        except Exception as e:
            logger.warning("Failed to load exchange_config from DB: %s — using fallback", e)
        return dict(_FALLBACK_EXCHANGE_CONFIG)

    def _ensure_exchange_config(self) -> Dict[str, Dict[str, Any]]:
        now = time.time()
        if now - self._exchange_config_ts < self._cache_ttl and self._exchange_config:
            return self._exchange_config
        with self._lock:
            # Double-check after acquiring lock
            if now - self._exchange_config_ts < self._cache_ttl and self._exchange_config:
                return self._exchange_config
            self._exchange_config = self._load_exchange_config()
            self._exchange_config_ts = time.time()
            return self._exchange_config

    def get_suffix(self, exchange: str) -> str:
        """yfinance symbol suffix for an exchange. e.g. 'ASX' -> '.AX', 'US' -> ''"""
        cfg = self._ensure_exchange_config()
        entry = cfg.get(exchange.upper())
        if entry:
            return entry["yf_suffix"]
        # Check fallback directly
        fb = _FALLBACK_EXCHANGE_CONFIG.get(exchange.upper())
        return fb["yf_suffix"] if fb else ""

    def get_all_exchanges(self, active_only: bool = True) -> List[str]:
        """All exchange codes. Replaces ALL_EXCHANGES lists."""
        cfg = self._ensure_exchange_config()
        return sorted(cfg.keys())

    def get_exchanges_by_region(self, region: str) -> List[str]:
        """Exchanges in a region ('asia', 'us', 'europe'). Replaces ASIA_EXCHANGES etc."""
        cfg = self._ensure_exchange_config()
        region_lower = region.lower()
        return sorted(ex for ex, c in cfg.items() if c["region"] == region_lower)

    def get_batch_size(self, exchange: str) -> int:
        """yfinance download batch size for an exchange."""
        cfg = self._ensure_exchange_config()
        entry = cfg.get(exchange.upper())
        return entry["batch_size"] if entry else 500

    def get_data_provider(self, exchange: str) -> str:
        """Data provider name for an exchange."""
        cfg = self._ensure_exchange_config()
        entry = cfg.get(exchange.upper())
        return entry["data_provider"] if entry else "yahoo"

    # ── Market Hours ─────────────────────────────────────────────────────────

    def _load_market_hours(self) -> Dict[str, Dict[str, Any]]:
        """Load from datapai.market_trading_hours table."""
        try:
            conn = _get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT exchange, timezone, open_hour, open_minute,
                       close_hour, close_minute,
                       lunch_start_hour, lunch_start_minute,
                       lunch_end_hour, lunch_end_minute
                FROM datapai.market_trading_hours
                WHERE is_active = TRUE
            """)
            result = {}
            for row in cur.fetchall():
                ex, tz, oh, om, ch, cm, lsh, lsm, leh, lem = row
                entry: Dict[str, Any] = {"tz": tz, "open": (oh, om), "close": (ch, cm)}
                if lsh is not None and leh is not None:
                    entry["lunch_start"] = (lsh, lsm)
                    entry["lunch_end"] = (leh, lem)
                result[ex] = entry
            cur.close()
            conn.close()
            if result:
                logger.debug("Loaded market hours from DB: %d markets", len(result))
                return result
        except Exception as e:
            logger.warning("Failed to load market_trading_hours from DB: %s — using fallback", e)
        return dict(_FALLBACK_MARKET_HOURS)

    def _ensure_market_hours(self) -> Dict[str, Dict[str, Any]]:
        now = time.time()
        if now - self._market_hours_ts < self._cache_ttl and self._market_hours:
            return self._market_hours
        with self._lock:
            if now - self._market_hours_ts < self._cache_ttl and self._market_hours:
                return self._market_hours
            self._market_hours = self._load_market_hours()
            self._market_hours_ts = time.time()
            return self._market_hours

    def get_market_hours(self, exchange: str) -> Optional[Dict[str, Any]]:
        """Open/close times + timezone + lunch break for an exchange."""
        hours = self._ensure_market_hours()
        return hours.get(exchange.upper())

    def get_timezone(self, exchange: str) -> Optional[str]:
        """Timezone string for an exchange."""
        entry = self.get_market_hours(exchange)
        return entry["tz"] if entry else None

    def get_all_market_hours(self) -> Dict[str, Dict[str, Any]]:
        """All market hours — replaces _load_market_hours() + _FALLBACK_MARKET_HOURS pattern."""
        return dict(self._ensure_market_hours())

    # ── Ticker Context (Sector/Commodity/FX) ─────────────────────────────────

    def _load_ticker_context(self) -> Dict[str, Dict[str, Any]]:
        """Load from datapai.ticker_context_config table."""
        try:
            conn = _get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT ticker, exchange, sector_etf, sector_label,
                       commodity, commodity_label, fx_pair, fx_label
                FROM datapai.ticker_context_config
                WHERE is_active = TRUE
            """)
            result = {}
            for row in cur.fetchall():
                ticker, exchange, etf, etf_lbl, com, com_lbl, fx, fx_lbl = row
                result[ticker.upper()] = {
                    "exchange": exchange,
                    "sector_etf": etf,
                    "sector_label": etf_lbl,
                    "commodity": com,
                    "commodity_label": com_lbl,
                    "fx": fx,
                    "fx_label": fx_lbl,
                }
            cur.close()
            conn.close()
            if result:
                logger.debug("Loaded ticker context from DB: %d tickers", len(result))
                return result
        except Exception as e:
            logger.warning("Failed to load ticker_context_config from DB: %s — using empty map", e)
        return {}

    def _ensure_ticker_context(self) -> Dict[str, Dict[str, Any]]:
        now = time.time()
        if now - self._ticker_context_ts < self._cache_ttl and self._ticker_context:
            return self._ticker_context
        with self._lock:
            if now - self._ticker_context_ts < self._cache_ttl and self._ticker_context:
                return self._ticker_context
            self._ticker_context = self._load_ticker_context()
            self._ticker_context_ts = time.time()
            return self._ticker_context

    def get_context_config(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Sector ETF, commodity, FX config for a ticker. Replaces CONTEXT_MAP."""
        ctx = self._ensure_ticker_context()
        return ctx.get(ticker.upper().strip())

    # ── Utility ──────────────────────────────────────────────────────────────

    def invalidate_cache(self):
        """Force reload on next access."""
        with self._lock:
            self._exchange_config_ts = 0
            self._market_hours_ts = 0
            self._ticker_context_ts = 0

    def get_yf_symbol(self, ticker: str, exchange: str) -> str:
        """Convert bare ticker + exchange to yfinance symbol. e.g. ('BHP', 'ASX') -> 'BHP.AX'"""
        suffix = self.get_suffix(exchange)
        if suffix and not ticker.endswith(suffix):
            return f"{ticker}{suffix}"
        return ticker


# ── Module-level singleton ───────────────────────────────────────────────────

registry = ExchangeRegistry()

# Convenience aliases for common operations
get_suffix = registry.get_suffix
get_all_exchanges = registry.get_all_exchanges
get_exchanges_by_region = registry.get_exchanges_by_region
get_market_hours = registry.get_market_hours
get_timezone = registry.get_timezone
get_context_config = registry.get_context_config
get_yf_symbol = registry.get_yf_symbol
