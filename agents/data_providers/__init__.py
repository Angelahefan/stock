# agents/data_providers/__init__.py
"""
OHLCV provider registry.

Usage
-----
    from agents.data_providers import get_provider
    provider = get_provider("postgres")   # DB-backed (fastest, offline)
    df = provider.fetch("BHP", "1d", ".AX")

Priority chain (recommended):
    postgres → polygon → yahoo

Graceful degradation
--------------------
If the requested provider requires an API key that is not set in the
environment, get_provider() logs a warning and returns YahooProvider
instead.  Callers never need to handle "provider unavailable" — they
always get a working provider back.

Available providers
-------------------
  "postgres" — datapai PostgreSQL (v1.6+).  No API key.
               datapai.prices (daily) + datapai.ohlcv_intraday (30m).
               Falls back automatically when data is absent or stale.

  "yahoo"   — Yahoo Finance via yfinance.  Free, no key.
              Best for ASX, US, LSE, TSX, HK.  Intraday capped 60 days.

  "polygon" — Polygon.io (Massive) REST API v2.  Needs POLYGON_KEY.
              US stocks only (NYSE/NASDAQ/OTC).  Starter plan = real-time.

  "eodhd"   — EOD Historical Data (eodhd.com).  Needs EODHD_API_KEY.
              Recommended for ASX — better intraday depth than Yahoo.
              Covers 70+ exchanges.
"""
from __future__ import annotations

import importlib
import logging
import os

from agents.data_providers.base import OHLCVProvider

logger = logging.getLogger(__name__)

# name → "module.ClassName"
_REGISTRY: dict[str, str] = {
    "postgres": "agents.data_providers.postgres_provider.PostgresProvider",
    "yahoo":    "agents.data_providers.yahoo.YahooProvider",
    "polygon":  "agents.data_providers.polygon.PolygonProvider",
    "eodhd":    "agents.data_providers.eodhd.EODHDProvider",
}

# Which env var is required for each provider ("" = no key needed)
_REQUIRED_KEY: dict[str, str] = {
    "postgres": "",
    "yahoo":    "",
    "polygon":  "POLYGON_KEY",
    "eodhd":    "EODHD_API_KEY",
}


def get_provider(name: str = "yahoo") -> OHLCVProvider:
    """
    Return an OHLCVProvider by name, with automatic Yahoo fallback.

    Parameters
    ----------
    name : "postgres" | "yahoo" | "polygon" | "eodhd"
           Case-insensitive. Unknown names fall back to Yahoo.

    Returns
    -------
    OHLCVProvider instance — always returns something usable.
    """
    name = (name or "yahoo").lower().strip()

    # Graceful degradation: missing API key → Yahoo
    required_key = _REQUIRED_KEY.get(name, "")
    if required_key and not os.environ.get(required_key):
        logger.warning(
            "Data provider '%s' requires %s which is not set in the environment. "
            "Falling back to Yahoo Finance.",
            name, required_key,
        )
        name = "yahoo"

    if name not in _REGISTRY:
        logger.warning(
            "Unknown data provider '%s'. Available: %s. Falling back to Yahoo.",
            name, list(_REGISTRY),
        )
        name = "yahoo"

    module_path, class_name = _REGISTRY[name].rsplit(".", 1)
    try:
        module = importlib.import_module(module_path)
        cls    = getattr(module, class_name)
        return cls()
    except Exception as exc:
        logger.error(
            "Failed to load provider '%s' (%s): %s — falling back to Yahoo.",
            name, module_path, exc,
        )
        from agents.data_providers.yahoo import YahooProvider
        return YahooProvider()


# ---------------------------------------------------------------------------
# Exchange-specific fallback chains
# ---------------------------------------------------------------------------

EXCHANGE_CHAINS: dict[str, list[str]] = {
    "ASX":  ["postgres", "yahoo", "eodhd"],
    "US":   ["postgres", "polygon", "yahoo"],
    "NYSE": ["postgres", "polygon", "yahoo"],
    "NASDAQ": ["postgres", "polygon", "yahoo"],
    "VN":   ["yahoo", "eodhd"],
    "HOSE": ["yahoo", "eodhd"],
    "HNX":  ["yahoo", "eodhd"],
    "ID":   ["yahoo", "eodhd"],
    "IDX":  ["yahoo", "eodhd"],
    "TH":   ["yahoo", "eodhd"],
    "SET":  ["yahoo", "eodhd"],
    "MY":   ["yahoo", "eodhd"],
    "KLSE": ["yahoo", "eodhd"],
    "LSE":  ["yahoo"],
    "TSX":  ["yahoo"],
    "HKEX": ["yahoo"],
}


def fetch_with_fallback(
    ticker: str,
    timeframe: str = "1d",
    suffix: str = "",
    exchange: str = "US",
) -> tuple:
    """
    Fetch OHLCV data with automatic vendor fallback per exchange.

    Tries each provider in the exchange's fallback chain until one succeeds.

    Parameters
    ----------
    ticker    : bare symbol (e.g. "BHP", "AAPL")
    timeframe : "5m" | "30m" | "1h" | "1d"
    suffix    : exchange suffix (".AX", "", ".L", etc.)
    exchange  : exchange code for chain selection ("ASX", "US", "VN", etc.)

    Returns
    -------
    (pd.DataFrame | None, str | None) — data and provider name that succeeded
    """
    chain = EXCHANGE_CHAINS.get(exchange.upper(), ["yahoo"])

    for provider_name in chain:
        provider = get_provider(provider_name)
        try:
            result = provider.fetch(ticker, timeframe, suffix)
            if result is not None and not result.empty:
                logger.info(
                    "[data] %s%s (%s) fetched from %s (%d bars)",
                    ticker, suffix, timeframe, provider_name, len(result),
                )
                return result, provider_name
        except Exception as exc:
            logger.warning(
                "[data] %s%s (%s) failed on %s: %s",
                ticker, suffix, timeframe, provider_name, str(exc)[:100],
            )
            continue

    logger.error(
        "[data] %s%s (%s) exhausted all providers in chain %s",
        ticker, suffix, timeframe, chain,
    )
    return None, None


__all__ = ["OHLCVProvider", "get_provider", "fetch_with_fallback", "EXCHANGE_CHAINS"]
