"""
scripts/lib/sina_helpers.py — Sina Finance adapter for China A-share intraday data.

Free, no API key, no rate limit, works from anywhere (including AWS).
Returns 5-min bars in local Shanghai time with OHLCV.

API: https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData
"""
import json
import logging
import time
import urllib.request
from typing import List, Tuple

logger = logging.getLogger(__name__)


def _sina_symbol(ticker: str, exchange: str) -> str:
    """Convert DB ticker + exchange to Sina symbol format."""
    # SSE tickers start with 6, SZSE with 0/3
    if exchange == "SSE" or ticker.startswith("6"):
        return f"sh{ticker}"
    else:
        return f"sz{ticker}"


def fetch_intraday_sina(
    ticker: str,
    exchange: str,
    period: str = "5",
    bars: int = 100,
) -> List[Tuple[str, float, float, float, float, int]]:
    """
    Fetch intraday bars for a single A-share ticker via Sina Finance.

    Returns:
        List of (ts_str, open, high, low, close, volume) tuples.
        ts_str is local Shanghai time: "YYYY-MM-DD HH:MM:SS"
    """
    symbol = _sina_symbol(ticker, exchange)
    url = (
        f"https://quotes.sina.cn/cn/api/jsonp_v2.php/=/"
        f"CN_MarketDataService.getKLineData?"
        f"symbol={symbol}&scale={period}&ma=no&datalen={bars}"
    )
    try:
        req = urllib.request.Request(url, headers={
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0",
        })
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode("utf-8")

        # Parse JSONP: =([{...}, ...])
        json_str = data[data.index("(") + 1 : data.rindex(")")]
        result = json.loads(json_str)

        rows = []
        for b in result:
            ts = b.get("day", "")
            o = float(b.get("open", 0))
            h = float(b.get("high", 0))
            l = float(b.get("low", 0))
            c = float(b.get("close", 0))
            v = int(b.get("volume", 0))
            if c > 0:
                rows.append((ts, o, h, l, c, v))
        return rows
    except Exception as e:
        logger.warning("Sina fetch failed for %s (%s): %s", ticker, exchange, e)
        return []


def fetch_batch_sina(
    tickers: List[Tuple[str, str, str]],
    period: str = "5",
    bars: int = 50,
    sleep_between: float = 0.2,
) -> List[Tuple]:
    """
    Fetch intraday data for multiple A-share tickers via Sina.

    Args:
        tickers: List of (db_ticker, yf_symbol, exchange)
        period: bar period in minutes
        bars: number of bars to fetch per ticker
        sleep_between: seconds between API calls

    Returns:
        List of (ticker, ts, open, high, low, close, volume, exchange, source) tuples
    """
    all_rows = []
    for i, (db_ticker, _yf_sym, exchange) in enumerate(tickers):
        result = fetch_intraday_sina(db_ticker, exchange, period, bars)
        for ts, o, h, l, c, v in result:
            all_rows.append((db_ticker, ts, o, h, l, c, v, exchange, "sina"))

        if i < len(tickers) - 1:
            time.sleep(sleep_between)

    return all_rows
