"""
scripts/lib/akshare_helpers.py — AKShare adapter for China A-share intraday data.

AKShare provides free, real-time A-share data with no API key.
Returns 5-min bars including the actual 15:00 close bar (which yfinance misses).

Column mapping (Chinese → English):
  时间=time, 开盘=open, 收盘=close, 最高=high, 最低=low, 成交量=volume
"""
import logging
import time
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

# Lazy import — akshare is heavy, only load when needed
_ak = None


def _get_ak():
    global _ak
    if _ak is None:
        import akshare
        _ak = akshare
    return _ak


def fetch_intraday_akshare(
    ticker: str,
    exchange: str,
    period: str = "5",
) -> List[Tuple[str, float, float, float, float, int]]:
    """
    Fetch intraday bars for a single A-share ticker via AKShare.

    Args:
        ticker: Plain code e.g. "600519"
        exchange: "SSE" or "SZSE"
        period: "1", "5", "15", "30", "60" (minutes)

    Returns:
        List of (ts_str, open, high, low, close, volume) tuples.
        ts_str is local Shanghai time: "YYYY-MM-DD HH:MM:SS"
    """
    ak = _get_ak()
    try:
        df = ak.stock_zh_a_hist_min_em(symbol=ticker, period=period, adjust="qfq")
        if df is None or df.empty:
            return []

        rows = []
        for _, r in df.iterrows():
            ts_str = str(r["时间"])  # Already local Shanghai time
            o = float(r["开盘"])
            h = float(r["最高"])
            l = float(r["最低"])
            c = float(r["收盘"])
            v = int(r["成交量"])
            rows.append((ts_str, o, h, l, c, v))

        return rows
    except Exception as e:
        logger.warning("AKShare fetch failed for %s (%s): %s", ticker, exchange, e)
        return []


def fetch_batch_akshare(
    tickers: List[Tuple[str, str, str]],
    period: str = "5",
    sleep_between: float = 0.3,
) -> List[Tuple]:
    """
    Fetch intraday data for multiple A-share tickers.

    Args:
        tickers: List of (db_ticker, yf_symbol, exchange) — we use db_ticker (plain code)
        period: bar period in minutes
        sleep_between: seconds between API calls (rate-safe)

    Returns:
        List of (ticker, ts, open, high, low, close, volume, exchange, source) tuples
        ready for upsert_intraday_rows().
    """
    all_rows = []
    for i, (db_ticker, _yf_sym, exchange) in enumerate(tickers):
        bars = fetch_intraday_akshare(db_ticker, exchange, period)
        for ts_str, o, h, l, c, v in bars:
            all_rows.append((db_ticker, ts_str, o, h, l, c, v, exchange, "akshare"))

        if i < len(tickers) - 1:
            time.sleep(sleep_between)

    return all_rows
