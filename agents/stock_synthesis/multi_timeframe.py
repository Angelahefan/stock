"""
agents/stock_synthesis/multi_timeframe.py
─────────────────────────────────────────────────────────────────────────────
Multi-Timeframe TA Analysis.

Higher timeframe always takes priority:
  - Daily sell + Weekly hold + Monthly buy → HOLD (it's just a pullback)
  - Daily sell + Weekly sell + Monthly hold → CAUTION (trend weakening)
  - Daily sell + Weekly sell + Monthly sell → SELL (genuine reversal)

This prevents selling quality stocks on daily noise when the weekly
and monthly trends are still intact.

Usage:
    from agents.stock_synthesis.multi_timeframe import (
        compute_weekly_monthly_indicators,
        count_multi_tf_sell_signals,
    )

    weekly, monthly = compute_weekly_monthly_indicators(daily_df)
    result = count_multi_tf_sell_signals(daily_ta, weekly_ta, monthly_ta)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def _resample_ohlcv(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Resample daily OHLCV to weekly ('W') or monthly ('ME')."""
    resampled = df.resample(freq).agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }).dropna(subset=["Close"])
    return resampled


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _compute_macd(close: pd.Series) -> Tuple[pd.Series, pd.Series]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return macd_line, signal_line


def compute_tf_indicators(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compute key TA indicators for a single timeframe.
    Returns dict with latest values.
    """
    if df.empty or len(df) < 26:
        return {}

    close = df["Close"]

    rsi = _compute_rsi(close)
    macd_line, macd_signal = _compute_macd(close)

    sma_10 = close.rolling(10).mean()
    sma_20 = close.rolling(20).mean()
    sma_50 = close.rolling(min(50, len(close))).mean()

    latest = {
        "rsi_14": rsi.iloc[-1] if not rsi.empty else None,
        "macd_trend": "BULLISH" if (macd_line.iloc[-1] > macd_signal.iloc[-1]) else "BEARISH",
        "sma_trend": "UP" if (sma_10.iloc[-1] > sma_20.iloc[-1]) else "DOWN",
        "price_vs_sma50": "ABOVE" if (close.iloc[-1] > sma_50.iloc[-1]) else "BELOW",
        "close": close.iloc[-1],
    }

    # Check for NaN
    for k, v in latest.items():
        if isinstance(v, float) and np.isnan(v):
            latest[k] = None

    return latest


def compute_weekly_monthly_indicators(daily_df: pd.DataFrame) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    From a daily OHLCV DataFrame, compute weekly and monthly indicators.

    Returns (weekly_indicators, monthly_indicators).
    """
    weekly_df = _resample_ohlcv(daily_df, "W")
    monthly_df = _resample_ohlcv(daily_df, "M")

    weekly = compute_tf_indicators(weekly_df)
    monthly = compute_tf_indicators(monthly_df)

    return weekly, monthly


def compute_weekly_monthly_at_index(daily_df: pd.DataFrame, idx: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Compute weekly/monthly indicators using data UP TO a specific index.
    For backtesting — no look-ahead bias.
    """
    # Use all data up to and including idx
    subset = daily_df.iloc[:idx + 1]
    if len(subset) < 60:
        return {}, {}
    return compute_weekly_monthly_indicators(subset)


# ---------------------------------------------------------------------------
# Multi-timeframe sell signal analysis
# ---------------------------------------------------------------------------

@dataclass
class MultiTFSignal:
    """Multi-timeframe signal analysis result."""
    daily_sell_count: int = 0
    weekly_bearish: bool = False
    monthly_bearish: bool = False
    tf_agreement: str = "NONE"  # NONE, DAILY_ONLY, DAILY_WEEKLY, ALL_TIMEFRAMES
    should_exit: bool = False
    reason: str = ""


def analyze_multi_tf(
    daily_ta: Dict[str, Any],
    weekly_ta: Dict[str, Any],
    monthly_ta: Dict[str, Any],
    pnl_pct: float = 0.0,
) -> MultiTFSignal:
    """
    Analyze sell signals across timeframes.

    Rules:
    - Daily sell signals alone → NOISE (don't exit quality stocks)
    - Daily + Weekly bearish → CAUTION (consider reducing, not exiting)
    - Daily + Weekly + Monthly bearish → GENUINE REVERSAL (exit)
    - Weekly bearish alone (without daily) → something structural changing

    Higher timeframe ALWAYS takes priority.
    """
    result = MultiTFSignal()

    # Count daily sell signals
    from agents.stock_synthesis.exit_agent import _count_ta_sell_signals
    daily_sell, _ = _count_ta_sell_signals(daily_ta, pnl_pct)
    result.daily_sell_count = daily_sell

    # Weekly assessment
    w_macd = weekly_ta.get("macd_trend")
    w_rsi = weekly_ta.get("rsi_14")
    w_sma = weekly_ta.get("sma_trend")
    w_price = weekly_ta.get("price_vs_sma50")

    weekly_bearish_signals = 0
    if w_macd == "BEARISH":
        weekly_bearish_signals += 1
    if w_rsi is not None and w_rsi > 70:
        weekly_bearish_signals += 1
    if w_sma == "DOWN":
        weekly_bearish_signals += 1
    if w_price == "BELOW":
        weekly_bearish_signals += 1

    result.weekly_bearish = weekly_bearish_signals >= 2

    # Monthly assessment
    m_macd = monthly_ta.get("macd_trend")
    m_rsi = monthly_ta.get("rsi_14")
    m_price = monthly_ta.get("price_vs_sma50")

    monthly_bearish_signals = 0
    if m_macd == "BEARISH":
        monthly_bearish_signals += 1
    if m_rsi is not None and m_rsi > 75:
        monthly_bearish_signals += 1
    if m_price == "BELOW":
        monthly_bearish_signals += 1

    result.monthly_bearish = monthly_bearish_signals >= 2

    # Determine agreement level
    if daily_sell >= 2 and result.weekly_bearish and result.monthly_bearish:
        result.tf_agreement = "ALL_TIMEFRAMES"
        result.should_exit = True
        result.reason = (
            f"All timeframes bearish: daily ({daily_sell} sell), "
            f"weekly ({weekly_bearish_signals} bearish), "
            f"monthly ({monthly_bearish_signals} bearish). Genuine reversal."
        )
    elif daily_sell >= 2 and result.weekly_bearish:
        result.tf_agreement = "DAILY_WEEKLY"
        result.should_exit = True
        result.reason = (
            f"Daily + weekly bearish: daily ({daily_sell} sell), "
            f"weekly ({weekly_bearish_signals} bearish). Trend weakening."
        )
    elif daily_sell >= 3:
        result.tf_agreement = "DAILY_ONLY"
        result.should_exit = False  # daily alone = noise for quality stocks
        result.reason = (
            f"Daily bearish ({daily_sell} sell) but weekly/monthly still OK. "
            f"Likely a pullback, not a reversal."
        )
    else:
        result.tf_agreement = "NONE"
        result.should_exit = False
        result.reason = "No multi-timeframe sell confirmation."

    return result
