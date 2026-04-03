#!/usr/bin/env python3
"""
scripts/backtest_signals.py
══════════════════════════════════════════════════════════════════════════════
Backtest the Buy / Hold / Sell composite signals against historical price data.

Validates signal accuracy by computing forward returns after each signal date.
Uses the EXACT same logic as the screener's TypeScript — just in Python.

Methodology (inspired by proven frameworks):
─────────────────────────────────────────────
  Short-term (Days/Weeks):  Mean-reversion model
    - Larry Connors' RSI(2) research: RSI<30 has positive forward returns
    - Mark Minervini: price extension from SMA triggers profit-taking
    - Asymmetric: BUY needs ≥3 conviction, SELL only needs ≤-2 (take profit)

  Long-term (Months/Quarter): Trend-following model
    - William O'Neil CAN SLIM: Golden Cross + relative strength
    - Stan Weinstein Stage Analysis: SMA50/200 + OBV accumulation
    - Symmetric: both BUY and SELL need ≥3 or ≤-3

Data source:  datapai.prices (OHLCV) — 5 years, 8,500+ tickers

Forward return windows:
  - Days signal:    1, 3, 5 trading days forward
  - Weeks signal:   5, 10, 15 trading days forward
  - Months signal:  20, 40, 60 trading days forward
  - Quarter signal: 60, 120, 180 trading days forward

Key metrics per signal:
  - Win Rate: % of signals where forward return > 0 (BUY) or < 0 (SELL)
  - Average Return: Mean forward return following signal
  - Median Return: Median forward return (less skew-sensitive)
  - Profit Factor: Sum(winners) / Sum(losers)
  - Signal Count: Total signals generated (sample size matters)

Usage:
    python3 scripts/backtest_signals.py --exchange US --sample 200
    python3 scripts/backtest_signals.py --exchange US --sample 500 --start 2024-01-01
    python3 scripts/backtest_signals.py --exchange ASX --sample 100
    python3 scripts/backtest_signals.py --exchange US --full
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backtest")


# ═══════════════════════════════════════════════════════════════════════════════
# Part 1: Pure-pandas TA Indicator Computation
# (mirrors agents/technical_analysis.py — all vectorised, no loops)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_kdj(
    high: pd.Series, low: pd.Series, close: pd.Series,
    k_period: int = 9, d_period: int = 3,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    lowest = low.rolling(k_period).min()
    highest = high.rolling(k_period).max()
    denom = (highest - lowest).replace(0, np.nan)
    rsv = 100 * (close - lowest) / denom
    k = rsv.ewm(com=d_period - 1, min_periods=1).mean()
    d = k.ewm(com=d_period - 1, min_periods=1).mean()
    j = 3 * k - 2 * d
    return k, d, j


def compute_bollinger(
    close: pd.Series, period: int = 20, std_dev: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


def compute_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (direction * volume).cumsum()


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all TA indicators from OHLCV DataFrame.

    Input:  df with columns [Open, High, Low, Close, Volume]
    Output: df with added indicator columns, ready for signal computation.
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    # SMAs
    for n in [5, 10, 20, 50, 200]:
        df[f"sma_{n}"] = close.rolling(n).mean()

    # RSI
    df["rsi_14"] = compute_rsi(close, 14)

    # MACD
    macd_line, macd_signal, macd_hist = compute_macd(close)
    df["macd_line"] = macd_line
    df["macd_signal"] = macd_signal
    df["macd_histogram"] = macd_hist
    df["macd_trend"] = np.where(macd_line > macd_signal, "BULLISH", "BEARISH")

    # KDJ
    k, d, j = compute_kdj(high, low, close)
    df["kdj_k"] = k
    df["kdj_d"] = d
    df["kdj_j"] = j
    df["kdj_signal"] = np.where(k > 80, "OVERBOUGHT", np.where(k < 20, "OVERSOLD", "NEUTRAL"))

    # Bollinger Bands
    bb_upper, bb_middle, bb_lower = compute_bollinger(close)
    df["bb_upper"] = bb_upper
    df["bb_lower"] = bb_lower
    bb_range = (bb_upper - bb_lower).replace(0, np.nan)
    df["bb_pct_b"] = (close - bb_lower) / bb_range

    # OBV
    obv = compute_obv(close, volume)
    df["obv"] = obv
    obv_sma20 = obv.rolling(20).mean()
    df["obv_trend"] = np.where(obv > obv_sma20, "UP", np.where(obv < obv_sma20, "DOWN", "FLAT"))

    # Volume ratio
    avg_vol_20 = volume.rolling(20).mean()
    df["volume_ratio"] = volume / avg_vol_20.replace(0, np.nan)

    # Volatility (20-day annualized)
    df["volatility_20d"] = close.pct_change().rolling(20).std() * np.sqrt(252)

    # Percentage changes
    df["change_1d_pct"] = close.pct_change(1) * 100
    df["change_5d_pct"] = close.pct_change(5) * 100
    df["change_1m_pct"] = close.pct_change(21) * 100
    df["change_3m_pct"] = close.pct_change(63) * 100
    df["change_6m_pct"] = close.pct_change(126) * 100
    df["change_1y_pct"] = close.pct_change(252) * 100

    # 52-week high
    df["high_52w"] = high.rolling(252).max()
    df["pct_from_52w_high"] = ((close - df["high_52w"]) / df["high_52w"]) * 100

    return df


# ═══════════════════════════════════════════════════════════════════════════════
# Part 2: Signal Computation
# (EXACT match of screener page.tsx logic)
# ═══════════════════════════════════════════════════════════════════════════════

def signal_short_term(votes: list[int]) -> str:
    """BUY≥3, SELL≤-2 (asymmetric — easier to take profit)."""
    s = sum(votes)
    if s >= 3:
        return "BUY"
    if s <= -2:
        return "SELL"
    return "HOLD"


def signal_long_term(votes: list[int]) -> str:
    """BUY≥3, SELL≤-3 (symmetric)."""
    s = sum(votes)
    if s >= 3:
        return "BUY"
    if s <= -3:
        return "SELL"
    return "HOLD"


def compute_signal_days(row: pd.Series) -> str:
    """
    Short-term (Days) v2 — data-driven after backtest.

    v1 problem: "buy when RSI<30" = catching falling knives (46% win rate).
    v2 fix: buy when RSI is RECOVERING (30-45 range = bouncing up from oversold),
    not when still falling. Require MACD confirmation (momentum turning).

    SELL side was OK (51-52%), keep mostly unchanged.
    """
    votes = []
    rsi = row.get("rsi_14")
    # RSI v2: Buy zone = 30-45 (recovering from oversold, not still falling)
    #         Sell zone = ≥65 (approaching overbought)
    if pd.notna(rsi):
        votes.append(1 if 30 <= rsi <= 45 else (-1 if rsi >= 65 else 0))
    # MACD: must be bullish for BUY to work (momentum confirmation)
    macd = row.get("macd_trend")
    if pd.notna(macd):
        votes.append(1 if macd == "BULLISH" else (-1 if macd == "BEARISH" else 0))
    # KDJ
    kdj = row.get("kdj_signal")
    if pd.notna(kdj):
        votes.append(1 if kdj == "OVERSOLD" else (-1 if kdj == "OVERBOUGHT" else 0))
    # Price vs SMA5: buy when pulled back to SMA5, sell when stretched above
    close = row.get("Close")
    sma5 = row.get("sma_5")
    if pd.notna(close) and pd.notna(sma5) and sma5 > 0:
        ext = ((close - sma5) / sma5) * 100
        votes.append(-1 if ext > 3 else (1 if -3 <= ext <= -0.5 else 0))
    # 1D price action: moderate dip is better buy than crash
    chg1d = row.get("change_1d_pct")
    if pd.notna(chg1d):
        votes.append(-1 if chg1d > 3 else (1 if -4 <= chg1d <= -1 else 0))
    return signal_short_term(votes)


def compute_signal_weeks(row: pd.Series) -> str:
    """Near-term (Weeks): SMA10/20, BB, Volume, RSI, 5D%."""
    votes = []
    sma10 = row.get("sma_10")
    sma20 = row.get("sma_20")
    if pd.notna(sma10) and pd.notna(sma20):
        votes.append(1 if sma10 > sma20 else -1)
    bb = row.get("bb_pct_b")
    if pd.notna(bb):
        votes.append(1 if bb < 0.2 else (-1 if bb > 0.8 else 0))
    vol_ratio = row.get("volume_ratio")
    chg1d = row.get("change_1d_pct")
    if pd.notna(vol_ratio) and pd.notna(chg1d):
        if vol_ratio >= 2:
            votes.append(1 if chg1d >= 0 else -1)
        else:
            votes.append(0)
    rsi = row.get("rsi_14")
    if pd.notna(rsi):
        votes.append(1 if rsi <= 35 else (-1 if rsi >= 65 else 0))
    chg5d = row.get("change_5d_pct")
    if pd.notna(chg5d):
        votes.append(-1 if chg5d > 5 else (1 if chg5d < -5 else 0))
    return signal_short_term(votes)


def compute_signal_months(row: pd.Series) -> str:
    """
    Medium-term (Months) v2 — data-driven after backtest.

    v1 problem: SELL had positive forward returns (48-50% win) — selling in
    bull market doesn't work. SELL needs death cross confirmation.
    v2 fix: Add SMA50/200 as trend filter. If golden cross (bull market),
    SELL needs extreme evidence. Use stricter -4 threshold for SELL.
    """
    votes = []
    sma20 = row.get("sma_20")
    sma50 = row.get("sma_50")
    if pd.notna(sma20) and pd.notna(sma50):
        votes.append(1 if sma20 > sma50 else -1)
    chg1m = row.get("change_1m_pct")
    if pd.notna(chg1m):
        votes.append(1 if chg1m > 5 else (-1 if chg1m < -5 else 0))
    obv = row.get("obv_trend")
    if pd.notna(obv):
        votes.append(1 if obv == "UP" else (-1 if obv == "DOWN" else 0))
    rsi = row.get("rsi_14")
    if pd.notna(rsi):
        votes.append(1 if rsi <= 35 else (-1 if rsi >= 65 else 0))
    chg3m = row.get("change_3m_pct")
    if pd.notna(chg3m):
        votes.append(-1 if chg3m > 30 else (1 if chg3m < -30 else 0))
    # v2: Trend regime filter — don't sell in confirmed uptrends
    sma200 = row.get("sma_200")
    if pd.notna(sma50) and pd.notna(sma200):
        # Golden cross (bull market) adds +1, making SELL harder to reach
        # Death cross (bear market) adds -1, making SELL easier
        votes.append(1 if sma50 > sma200 else -1)
    # v2: Stricter threshold for SELL (need -4 not -3) because long-term
    # trends are hard to reverse
    s = sum(votes)
    if s >= 3:
        return "BUY"
    if s <= -4:  # stricter than -3 for sell
        return "SELL"
    return "HOLD"


def compute_signal_quarter(row: pd.Series) -> str:
    """Long-term (Quarter): SMA50/200, 52w High, 6M%, 1Y%, OBV."""
    votes = []
    sma50 = row.get("sma_50")
    sma200 = row.get("sma_200")
    if pd.notna(sma50) and pd.notna(sma200):
        votes.append(1 if sma50 > sma200 else -1)
    pct_52w = row.get("pct_from_52w_high")
    if pd.notna(pct_52w):
        votes.append(1 if pct_52w > -10 else (-1 if pct_52w < -30 else 0))
    chg6m = row.get("change_6m_pct")
    if pd.notna(chg6m):
        votes.append(1 if chg6m > 15 else (-1 if chg6m < -15 else 0))
    chg1y = row.get("change_1y_pct")
    if pd.notna(chg1y):
        votes.append(1 if chg1y > 20 else (-1 if chg1y < -20 else 0))
    obv = row.get("obv_trend")
    if pd.notna(obv):
        votes.append(1 if obv == "UP" else (-1 if obv == "DOWN" else 0))
    return signal_long_term(votes)


# ═══════════════════════════════════════════════════════════════════════════════
# Part 3: Backtest Engine
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SignalResult:
    """One signal event with its forward returns."""
    ticker: str
    date: str
    signal: str             # BUY / HOLD / SELL
    timeframe: str          # days / weeks / months / quarter
    close_price: float
    forward_returns: dict   # {days_forward: pct_return}


@dataclass
class BacktestStats:
    """Aggregated statistics for a signal type in a timeframe."""
    timeframe: str
    signal: str
    count: int = 0
    win_rates: dict = field(default_factory=dict)        # {fwd_days: win_rate%}
    avg_returns: dict = field(default_factory=dict)       # {fwd_days: avg_return%}
    median_returns: dict = field(default_factory=dict)    # {fwd_days: median_return%}
    profit_factors: dict = field(default_factory=dict)    # {fwd_days: sum_win/sum_loss}


# Forward return windows per timeframe
FORWARD_WINDOWS = {
    "days":    [1, 3, 5],
    "weeks":   [5, 10, 15],
    "months":  [20, 40, 60],
    "quarter": [60, 120, 180],
}

SIGNAL_FUNCS = {
    "days":    compute_signal_days,
    "weeks":   compute_signal_weeks,
    "months":  compute_signal_months,
    "quarter": compute_signal_quarter,
}


def backtest_ticker(
    ticker: str,
    exchange: str,
    df: pd.DataFrame,
    start_date: Optional[str] = None,
) -> list[SignalResult]:
    """
    Run backtest for a single ticker.

    Computes TA indicators over full history, then for each trading day
    (from start_date onwards), computes signals and checks forward returns.
    """
    if len(df) < 252:
        return []  # Need at least 1 year for meaningful indicators

    # Compute all TA indicators
    df = compute_all_indicators(df.copy())

    # Drop rows with NaN in critical columns (warm-up period)
    required = ["sma_200", "rsi_14", "macd_trend", "change_1y_pct"]
    mask = df[required].notna().all(axis=1)
    valid_idx = df.index[mask]
    if len(valid_idx) == 0:
        return []

    start_idx = valid_idx[0]
    if start_date:
        start_ts = pd.Timestamp(start_date)
        start_idx = max(start_idx, start_ts)

    # We need at least max_fwd_window days after each signal date
    max_fwd = max(max(w) for w in FORWARD_WINDOWS.values())

    results = []
    close_series = df["Close"]

    for i, (dt, row) in enumerate(df.iterrows()):
        if dt < start_idx:
            continue
        # Need enough forward data
        remaining = len(df) - i - 1
        if remaining < max_fwd:
            break

        # Compute signals for all 4 timeframes
        for tf_name, signal_func in SIGNAL_FUNCS.items():
            signal = signal_func(row)
            if signal == "HOLD":
                continue  # Only track BUY and SELL signals

            # Compute forward returns
            fwd_returns = {}
            for fwd_days in FORWARD_WINDOWS[tf_name]:
                if i + fwd_days < len(df):
                    future_close = close_series.iloc[i + fwd_days]
                    current_close = row["Close"]
                    if current_close > 0:
                        fwd_return = ((future_close - current_close) / current_close) * 100
                        fwd_returns[fwd_days] = round(fwd_return, 4)

            if fwd_returns:
                results.append(SignalResult(
                    ticker=ticker,
                    date=str(dt.date()) if hasattr(dt, 'date') else str(dt),
                    signal=signal,
                    timeframe=tf_name,
                    close_price=round(row["Close"], 2),
                    forward_returns=fwd_returns,
                ))

    return results


def aggregate_stats(results: list[SignalResult]) -> list[BacktestStats]:
    """Aggregate individual signal results into statistics."""
    # Group by timeframe + signal
    groups: dict[tuple[str, str], list[SignalResult]] = {}
    for r in results:
        key = (r.timeframe, r.signal)
        groups.setdefault(key, []).append(r)

    stats = []
    for (tf, sig), items in sorted(groups.items()):
        bs = BacktestStats(timeframe=tf, signal=sig, count=len(items))

        for fwd_days in FORWARD_WINDOWS.get(tf, []):
            returns = [
                r.forward_returns[fwd_days]
                for r in items
                if fwd_days in r.forward_returns
            ]
            if not returns:
                continue

            arr = np.array(returns)

            # Win rate: for BUY, win = return > 0; for SELL, win = return < 0
            if sig == "BUY":
                wins = np.sum(arr > 0)
            else:  # SELL
                wins = np.sum(arr < 0)
            bs.win_rates[fwd_days] = round(wins / len(arr) * 100, 1)

            bs.avg_returns[fwd_days] = round(float(np.mean(arr)), 2)
            bs.median_returns[fwd_days] = round(float(np.median(arr)), 2)

            # Profit factor (for BUY: sum of positive / abs(sum of negative))
            if sig == "BUY":
                gain = float(np.sum(arr[arr > 0])) if np.any(arr > 0) else 0
                loss = float(np.abs(np.sum(arr[arr < 0]))) if np.any(arr < 0) else 0.001
            else:  # SELL: inverted — profit when price goes down
                gain = float(np.abs(np.sum(arr[arr < 0]))) if np.any(arr < 0) else 0
                loss = float(np.sum(arr[arr > 0])) if np.any(arr > 0) else 0.001
            bs.profit_factors[fwd_days] = round(gain / loss, 2) if loss > 0 else 99.99

        stats.append(bs)

    return stats


# ═══════════════════════════════════════════════════════════════════════════════
# Part 4: Report Generation
# ═══════════════════════════════════════════════════════════════════════════════

def print_report(stats: list[BacktestStats], exchange: str, ticker_count: int,
                 start_date: str, elapsed_sec: float):
    """Print a formatted backtest report."""
    print("\n" + "═" * 80)
    print(f"  BACKTEST REPORT — {exchange} Stocks")
    print("═" * 80)
    print(f"  Tickers tested: {ticker_count}")
    print(f"  Date range:     {start_date} → latest")
    print(f"  Runtime:        {elapsed_sec:.1f}s")
    print(f"  Total signals:  {sum(s.count for s in stats):,}")
    print("═" * 80)

    # Signal distribution
    print("\n── Signal Distribution ──")
    for tf in ["days", "weeks", "months", "quarter"]:
        tf_stats = [s for s in stats if s.timeframe == tf]
        buy_count = sum(s.count for s in tf_stats if s.signal == "BUY")
        sell_count = sum(s.count for s in tf_stats if s.signal == "SELL")
        total = buy_count + sell_count
        print(f"  {tf:10s}: BUY={buy_count:>7,}  SELL={sell_count:>7,}  Total={total:>8,}")

    # Detailed results per timeframe
    for tf in ["days", "weeks", "months", "quarter"]:
        tf_stats = [s for s in stats if s.timeframe == tf]
        if not tf_stats:
            continue

        windows = FORWARD_WINDOWS[tf]

        print(f"\n── {tf.upper()} Signal Performance ──")
        print(f"  {'Signal':>6}  {'Count':>8}", end="")
        for w in windows:
            print(f"  │ {w}D Win%  {w}D Avg%  {w}D Med%  PF", end="")
        print()
        print(f"  {'─' * 6}  {'─' * 8}", end="")
        for _ in windows:
            print(f"  │ {'─' * 7}  {'─' * 7}  {'─' * 7}  {'─' * 5}", end="")
        print()

        for s in sorted(tf_stats, key=lambda x: x.signal):
            print(f"  {s.signal:>6}  {s.count:>8,}", end="")
            for w in windows:
                wr = s.win_rates.get(w, 0)
                ar = s.avg_returns.get(w, 0)
                mr = s.median_returns.get(w, 0)
                pf = s.profit_factors.get(w, 0)
                # Color coding for win rate
                wr_mark = "✓" if wr >= 55 else ("○" if wr >= 50 else "✗")
                print(f"  │ {wr:>5.1f}%{wr_mark} {ar:>+6.2f}% {mr:>+6.2f}%  {pf:>4.1f}", end="")
            print()

    # Summary verdict
    print(f"\n── VERDICT ──")
    passing = 0
    failing = 0
    for s in stats:
        for w, wr in s.win_rates.items():
            if s.signal == "BUY" and wr >= 52:
                passing += 1
            elif s.signal == "SELL" and wr >= 52:
                passing += 1
            else:
                failing += 1

    if passing + failing > 0:
        pass_pct = passing / (passing + failing) * 100
        if pass_pct >= 70:
            print(f"  ✅ {pass_pct:.0f}% of signal/window combos have >52% win rate — STRONG")
        elif pass_pct >= 50:
            print(f"  ⚠️  {pass_pct:.0f}% of signal/window combos have >52% win rate — MODERATE")
        else:
            print(f"  ❌ {pass_pct:.0f}% of signal/window combos have >52% win rate — NEEDS WORK")

    # Best and worst signals
    print("\n  Top 3 signals (by win rate):")
    all_entries = []
    for s in stats:
        for w, wr in s.win_rates.items():
            all_entries.append((s.timeframe, s.signal, w, wr, s.avg_returns.get(w, 0), s.count))
    all_entries.sort(key=lambda x: x[3], reverse=True)
    for tf, sig, w, wr, ar, cnt in all_entries[:3]:
        print(f"    {tf:>8s} {sig:>4s} → {w}D forward: {wr:.1f}% win, {ar:+.2f}% avg (n={cnt:,})")

    if len(all_entries) >= 3:
        print("\n  Bottom 3 signals (by win rate):")
        for tf, sig, w, wr, ar, cnt in all_entries[-3:]:
            print(f"    {tf:>8s} {sig:>4s} → {w}D forward: {wr:.1f}% win, {ar:+.2f}% avg (n={cnt:,})")

    print("\n" + "═" * 80)
    print("  Legend: ✓ = win rate ≥55%  ○ = 50-55%  ✗ = <50%")
    print("  PF = Profit Factor (sum winners / sum losers). >1.0 = profitable")
    print("  Note: Past performance does not guarantee future results.")
    print("═" * 80 + "\n")


def save_report_json(stats: list[BacktestStats], results: list[SignalResult],
                     output_path: str, exchange: str, ticker_count: int):
    """Save detailed results as JSON for further analysis."""
    report = {
        "exchange": exchange,
        "ticker_count": ticker_count,
        "generated_at": datetime.now().isoformat(),
        "summary": [],
        "sample_signals": [],  # First 100 for inspection
    }

    for s in stats:
        report["summary"].append({
            "timeframe": s.timeframe,
            "signal": s.signal,
            "count": s.count,
            "win_rates": s.win_rates,
            "avg_returns": s.avg_returns,
            "median_returns": s.median_returns,
            "profit_factors": s.profit_factors,
        })

    # Include a sample of actual signals for inspection
    for r in results[:200]:
        report["sample_signals"].append({
            "ticker": r.ticker,
            "date": r.date,
            "signal": r.signal,
            "timeframe": r.timeframe,
            "close_price": r.close_price,
            "forward_returns": r.forward_returns,
        })

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    logger.info("Saved JSON report to %s", output_path)


# ═══════════════════════════════════════════════════════════════════════════════
# Part 5: Main — Data Loading & Execution
# ═══════════════════════════════════════════════════════════════════════════════

def load_tickers(exchange: str, sample: Optional[int] = None) -> list[str]:
    """Load ticker list from database."""
    from scripts.lib.db_helpers import get_conn

    sql = """
        SELECT DISTINCT ticker
        FROM datapai.prices
        WHERE exchange = %(exchange)s
          AND trade_date::date >= CURRENT_DATE - INTERVAL '30 days'
        ORDER BY ticker
    """
    with get_conn() as conn:
        df = pd.read_sql(sql, conn, params={"exchange": exchange})

    tickers = df["ticker"].tolist()
    logger.info("Found %d active %s tickers", len(tickers), exchange)

    if sample and sample < len(tickers):
        # Stratified sample: pick evenly across the alphabet
        np.random.seed(42)  # Reproducible
        tickers = list(np.random.choice(tickers, size=sample, replace=False))
        tickers.sort()
        logger.info("Sampled %d tickers for backtest", len(tickers))

    return tickers


def load_price_history(ticker: str, exchange: str) -> Optional[pd.DataFrame]:
    """Load full price history for a ticker."""
    from scripts.lib.db_helpers import get_conn

    sql = """
        SELECT trade_date, open, high, low, close, volume
        FROM datapai.prices
        WHERE ticker = %(ticker)s AND exchange = %(exchange)s
        ORDER BY trade_date ASC
    """
    try:
        with get_conn() as conn:
            df = pd.read_sql(sql, conn, params={"ticker": ticker, "exchange": exchange})
    except Exception:
        return None

    if df.empty or len(df) < 252:
        return None

    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.set_index("trade_date").sort_index()
    df.columns = [c.capitalize() for c in df.columns]

    # Remove any NaN/zero close prices
    df = df[df["Close"] > 0].dropna(subset=["Close"])
    return df


def main():
    parser = argparse.ArgumentParser(description="Backtest Buy/Hold/Sell signals")
    parser.add_argument("--exchange", default="US")
    parser.add_argument("--sample", type=int, default=200,
                        help="Number of tickers to sample (default: 200, use --full for all)")
    parser.add_argument("--full", action="store_true",
                        help="Run on ALL tickers (slow but comprehensive)")
    parser.add_argument("--start", type=str, default="2023-01-01",
                        help="Start date for signal evaluation (default: 2023-01-01)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON file path")
    args = parser.parse_args()

    if args.full:
        args.sample = None

    logger.info("═══ BACKTEST: %s exchange, sample=%s, start=%s ═══",
                args.exchange, args.sample or "ALL", args.start)

    start_time = time.time()

    # Load tickers
    tickers = load_tickers(args.exchange, args.sample)
    if not tickers:
        logger.error("No tickers found for %s", args.exchange)
        return

    # Process each ticker
    all_results: list[SignalResult] = []
    processed = 0
    skipped = 0

    for i, ticker in enumerate(tickers):
        if i % 50 == 0 and i > 0:
            logger.info("Progress: %d/%d tickers (%.0f%%), %d signals so far",
                        i, len(tickers), i / len(tickers) * 100, len(all_results))

        df = load_price_history(ticker, args.exchange)
        if df is None:
            skipped += 1
            continue

        results = backtest_ticker(ticker, args.exchange, df, start_date=args.start)
        all_results.extend(results)
        processed += 1

    elapsed = time.time() - start_time

    if not all_results:
        logger.warning("No signals generated. Check data availability.")
        return

    # Aggregate statistics
    stats = aggregate_stats(all_results)

    # Print report
    print_report(stats, args.exchange, processed, args.start, elapsed)

    # Save JSON report
    output_path = args.output or f"/tmp/backtest_{args.exchange.lower()}_{args.start.replace('-', '')}.json"
    save_report_json(stats, all_results, output_path, args.exchange, processed)


if __name__ == "__main__":
    main()
