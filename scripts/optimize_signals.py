#!/usr/bin/env python3
"""
scripts/optimize_signals.py
══════════════════════════════════════════════════════════════════════════════
Auto-optimizer for Buy/Hold/Sell signal thresholds.

Instead of manual v1 → v2 tuning, this script systematically searches
for the best parameter combinations using walk-forward validation:

  1. TRAIN period: compute signals with candidate parameters
  2. VALIDATE period: measure forward returns on unseen data
  3. Score: win_rate × profit_factor (balances accuracy + profitability)
  4. Output: best parameters as JSON config

Walk-forward prevents overfitting:
  ┌──────── TRAIN (70%) ────────┐┌── VALIDATE (30%) ──┐
  2021 ──────────────────── 2025  2025 ──────────── 2026

The output config can be:
  a) Read by the screener at runtime (dynamic thresholds)
  b) Used to update the TypeScript code (static deploy)
  c) Compared against current params to decide if update is worth it

Schedule: Run weekly via Airflow after new price data arrives.

Usage:
    python3 scripts/optimize_signals.py --exchange US --sample 300
    python3 scripts/optimize_signals.py --exchange US --full
    python3 scripts/optimize_signals.py --exchange ASX --sample 200
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.backtest_signals import (
    compute_all_indicators,
    load_price_history,
    load_tickers,
    signal_long_term,
    signal_short_term,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("optimize")


# ═══════════════════════════════════════════════════════════════════════════════
# Part 1: Parameterized Signal Functions
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DaysParams:
    rsi_buy_lo: float = 30      # RSI buy zone lower bound
    rsi_buy_hi: float = 45      # RSI buy zone upper bound
    rsi_sell: float = 65        # RSI sell threshold
    sma_ext_buy_lo: float = -3  # SMA5 extension buy zone (lower)
    sma_ext_buy_hi: float = -0.5  # SMA5 extension buy zone (upper)
    sma_ext_sell: float = 3     # SMA5 extension sell threshold
    chg1d_buy_lo: float = -4    # 1D% buy zone (lower)
    chg1d_buy_hi: float = -1    # 1D% buy zone (upper)
    chg1d_sell: float = 3       # 1D% sell threshold
    buy_threshold: int = 3
    sell_threshold: int = -2

    def to_dict(self):
        return self.__dict__


@dataclass
class WeeksParams:
    bb_buy: float = 0.2         # BB %B buy threshold
    bb_sell: float = 0.8        # BB %B sell threshold
    rsi_buy: float = 35         # RSI buy threshold
    rsi_sell: float = 65        # RSI sell threshold
    chg5d_buy: float = -5       # 5D% buy threshold
    chg5d_sell: float = 5       # 5D% sell threshold
    vol_spike: float = 2.0      # Volume spike multiplier
    buy_threshold: int = 3
    sell_threshold: int = -2

    def to_dict(self):
        return self.__dict__


@dataclass
class MonthsParams:
    chg1m_buy: float = 5        # 1M% buy threshold
    chg1m_sell: float = -5      # 1M% sell threshold
    rsi_buy: float = 35
    rsi_sell: float = 65
    chg3m_guard_buy: float = -30  # 3M% capitulation buy
    chg3m_guard_sell: float = 30  # 3M% overextended sell
    use_trend_regime: bool = True  # SMA50/200 filter
    buy_threshold: int = 3
    sell_threshold: int = -4     # stricter sell

    def to_dict(self):
        return self.__dict__


@dataclass
class QuarterParams:
    pct_52w_buy: float = -10    # 52w high proximity for buy
    pct_52w_sell: float = -30   # 52w high distance for sell
    chg6m_buy: float = 15
    chg6m_sell: float = -15
    chg1y_buy: float = 20
    chg1y_sell: float = -20
    buy_threshold: int = 3
    sell_threshold: int = -3

    def to_dict(self):
        return self.__dict__


def signal_days_param(row: pd.Series, p: DaysParams) -> str:
    votes = []
    rsi = row.get("rsi_14")
    if pd.notna(rsi):
        votes.append(1 if p.rsi_buy_lo <= rsi <= p.rsi_buy_hi else (-1 if rsi >= p.rsi_sell else 0))
    macd = row.get("macd_trend")
    if pd.notna(macd):
        votes.append(1 if macd == "BULLISH" else (-1 if macd == "BEARISH" else 0))
    kdj = row.get("kdj_signal")
    if pd.notna(kdj):
        votes.append(1 if kdj == "OVERSOLD" else (-1 if kdj == "OVERBOUGHT" else 0))
    close = row.get("Close")
    sma5 = row.get("sma_5")
    if pd.notna(close) and pd.notna(sma5) and sma5 > 0:
        ext = ((close - sma5) / sma5) * 100
        votes.append(-1 if ext > p.sma_ext_sell else (1 if p.sma_ext_buy_lo <= ext <= p.sma_ext_buy_hi else 0))
    chg1d = row.get("change_1d_pct")
    if pd.notna(chg1d):
        votes.append(-1 if chg1d > p.chg1d_sell else (1 if p.chg1d_buy_lo <= chg1d <= p.chg1d_buy_hi else 0))
    s = sum(votes)
    if s >= p.buy_threshold:
        return "BUY"
    if s <= p.sell_threshold:
        return "SELL"
    return "HOLD"


def signal_weeks_param(row: pd.Series, p: WeeksParams) -> str:
    votes = []
    sma10 = row.get("sma_10")
    sma20 = row.get("sma_20")
    if pd.notna(sma10) and pd.notna(sma20):
        votes.append(1 if sma10 > sma20 else -1)
    bb = row.get("bb_pct_b")
    if pd.notna(bb):
        votes.append(1 if bb < p.bb_buy else (-1 if bb > p.bb_sell else 0))
    vol_ratio = row.get("volume_ratio")
    chg1d = row.get("change_1d_pct")
    if pd.notna(vol_ratio) and pd.notna(chg1d):
        votes.append((1 if chg1d >= 0 else -1) if vol_ratio >= p.vol_spike else 0)
    rsi = row.get("rsi_14")
    if pd.notna(rsi):
        votes.append(1 if rsi <= p.rsi_buy else (-1 if rsi >= p.rsi_sell else 0))
    chg5d = row.get("change_5d_pct")
    if pd.notna(chg5d):
        votes.append(-1 if chg5d > p.chg5d_sell else (1 if chg5d < p.chg5d_buy else 0))
    s = sum(votes)
    if s >= p.buy_threshold:
        return "BUY"
    if s <= p.sell_threshold:
        return "SELL"
    return "HOLD"


def signal_months_param(row: pd.Series, p: MonthsParams) -> str:
    votes = []
    sma20 = row.get("sma_20")
    sma50 = row.get("sma_50")
    if pd.notna(sma20) and pd.notna(sma50):
        votes.append(1 if sma20 > sma50 else -1)
    chg1m = row.get("change_1m_pct")
    if pd.notna(chg1m):
        votes.append(1 if chg1m > p.chg1m_buy else (-1 if chg1m < p.chg1m_sell else 0))
    obv = row.get("obv_trend")
    if pd.notna(obv):
        votes.append(1 if obv == "UP" else (-1 if obv == "DOWN" else 0))
    rsi = row.get("rsi_14")
    if pd.notna(rsi):
        votes.append(1 if rsi <= p.rsi_buy else (-1 if rsi >= p.rsi_sell else 0))
    chg3m = row.get("change_3m_pct")
    if pd.notna(chg3m):
        votes.append(-1 if chg3m > p.chg3m_guard_sell else (1 if chg3m < p.chg3m_guard_buy else 0))
    if p.use_trend_regime:
        sma200 = row.get("sma_200")
        if pd.notna(sma50) and pd.notna(sma200):
            votes.append(1 if sma50 > sma200 else -1)
    s = sum(votes)
    if s >= p.buy_threshold:
        return "BUY"
    if s <= p.sell_threshold:
        return "SELL"
    return "HOLD"


def signal_quarter_param(row: pd.Series, p: QuarterParams) -> str:
    votes = []
    sma50 = row.get("sma_50")
    sma200 = row.get("sma_200")
    if pd.notna(sma50) and pd.notna(sma200):
        votes.append(1 if sma50 > sma200 else -1)
    pct_52w = row.get("pct_from_52w_high")
    if pd.notna(pct_52w):
        votes.append(1 if pct_52w > p.pct_52w_buy else (-1 if pct_52w < p.pct_52w_sell else 0))
    chg6m = row.get("change_6m_pct")
    if pd.notna(chg6m):
        votes.append(1 if chg6m > p.chg6m_buy else (-1 if chg6m < p.chg6m_sell else 0))
    chg1y = row.get("change_1y_pct")
    if pd.notna(chg1y):
        votes.append(1 if chg1y > p.chg1y_buy else (-1 if chg1y < p.chg1y_sell else 0))
    obv = row.get("obv_trend")
    if pd.notna(obv):
        votes.append(1 if obv == "UP" else (-1 if obv == "DOWN" else 0))
    s = sum(votes)
    if s >= p.buy_threshold:
        return "BUY"
    if s <= p.sell_threshold:
        return "SELL"
    return "HOLD"


# ═══════════════════════════════════════════════════════════════════════════════
# Part 2: Walk-Forward Evaluation Engine
# ═══════════════════════════════════════════════════════════════════════════════

FORWARD_WINDOWS = {
    "days":    [1, 3, 5],
    "weeks":   [5, 10, 15],
    "months":  [20, 40, 60],
    "quarter": [60, 120, 180],
}


def evaluate_params(
    all_dfs: dict[str, pd.DataFrame],
    timeframe: str,
    signal_func,
    params,
    train_end: str,
    validate_start: str,
) -> dict:
    """
    Evaluate a parameter set using walk-forward validation.

    Train: signals before train_end (for calibration/counting)
    Validate: signals from validate_start onward (actual scoring)

    Returns dict with win_rates, avg_returns, profit_factors, score.
    """
    windows = FORWARD_WINDOWS[timeframe]
    max_fwd = max(windows)

    all_returns = {w: [] for w in windows}
    signal_counts = {"BUY": 0, "SELL": 0}

    validate_ts = pd.Timestamp(validate_start)

    for ticker, df in all_dfs.items():
        if len(df) < 300:
            continue

        close = df["Close"]

        for i, (dt, row) in enumerate(df.iterrows()):
            if dt < validate_ts:
                continue
            remaining = len(df) - i - 1
            if remaining < max_fwd:
                break

            signal = signal_func(row, params)
            if signal == "HOLD":
                continue

            signal_counts[signal] = signal_counts.get(signal, 0) + 1

            for fwd in windows:
                if i + fwd < len(df):
                    fwd_ret = ((close.iloc[i + fwd] - row["Close"]) / row["Close"]) * 100
                    all_returns[fwd].append((signal, fwd_ret))

    # Compute metrics
    result = {
        "signal_counts": signal_counts,
        "win_rates": {},
        "avg_returns": {},
        "profit_factors": {},
    }

    scores = []
    for fwd in windows:
        entries = all_returns[fwd]
        if len(entries) < 20:  # Need minimum sample size
            continue

        buy_entries = [(s, r) for s, r in entries if s == "BUY"]
        sell_entries = [(s, r) for s, r in entries if s == "SELL"]

        for sig, sig_entries in [("BUY", buy_entries), ("SELL", sell_entries)]:
            if len(sig_entries) < 10:
                continue
            returns = np.array([r for _, r in sig_entries])

            if sig == "BUY":
                wins = np.sum(returns > 0)
            else:
                wins = np.sum(returns < 0)

            wr = wins / len(returns) * 100
            avg_ret = float(np.mean(returns))

            if sig == "BUY":
                gain = float(np.sum(returns[returns > 0])) if np.any(returns > 0) else 0
                loss = float(np.abs(np.sum(returns[returns < 0]))) if np.any(returns < 0) else 0.001
            else:
                gain = float(np.abs(np.sum(returns[returns < 0]))) if np.any(returns < 0) else 0
                loss = float(np.sum(returns[returns > 0])) if np.any(returns > 0) else 0.001
            pf = gain / loss if loss > 0 else 99.99

            key = f"{sig}_{fwd}D"
            result["win_rates"][key] = round(wr, 1)
            result["avg_returns"][key] = round(avg_ret, 2)
            result["profit_factors"][key] = round(pf, 2)

            # Score: win_rate * profit_factor (rewards both accuracy and profitability)
            # Only score BUY signals for optimization (SELL is harder to validate)
            if sig == "BUY" and wr > 45:
                scores.append(wr * pf / 100)

    result["composite_score"] = round(sum(scores) / max(len(scores), 1), 4) if scores else 0
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Part 3: Grid Search
# ═══════════════════════════════════════════════════════════════════════════════

def generate_days_candidates() -> list[DaysParams]:
    """Generate candidate parameter combinations for Days signal."""
    candidates = []
    for rsi_lo, rsi_hi in [(25, 40), (30, 45), (30, 50), (35, 50)]:
        for rsi_sell in [60, 65, 70]:
            for ext_sell in [2, 3, 4]:
                for chg_lo, chg_hi in [(-5, -2), (-4, -1), (-3, -0.5)]:
                    for buy_t in [2, 3]:
                        for sell_t in [-2, -3]:
                            candidates.append(DaysParams(
                                rsi_buy_lo=rsi_lo, rsi_buy_hi=rsi_hi,
                                rsi_sell=rsi_sell,
                                sma_ext_buy_lo=-ext_sell, sma_ext_buy_hi=-0.5,
                                sma_ext_sell=ext_sell,
                                chg1d_buy_lo=chg_lo, chg1d_buy_hi=chg_hi,
                                chg1d_sell=ext_sell,
                                buy_threshold=buy_t, sell_threshold=sell_t,
                            ))
    return candidates


def generate_weeks_candidates() -> list[WeeksParams]:
    candidates = []
    for rsi_buy in [30, 35, 40]:
        for rsi_sell in [60, 65, 70]:
            for chg5d in [(-8, 8), (-5, 5), (-3, 3)]:
                for buy_t in [2, 3]:
                    for sell_t in [-2, -3]:
                        candidates.append(WeeksParams(
                            rsi_buy=rsi_buy, rsi_sell=rsi_sell,
                            chg5d_buy=chg5d[0], chg5d_sell=chg5d[1],
                            buy_threshold=buy_t, sell_threshold=sell_t,
                        ))
    return candidates


def generate_months_candidates() -> list[MonthsParams]:
    candidates = []
    for rsi_buy in [30, 35, 40]:
        for rsi_sell in [60, 65, 70]:
            for chg1m in [(3, -3), (5, -5), (8, -8)]:
                for regime in [True, False]:
                    for sell_t in [-3, -4, -5]:
                        candidates.append(MonthsParams(
                            rsi_buy=rsi_buy, rsi_sell=rsi_sell,
                            chg1m_buy=chg1m[0], chg1m_sell=chg1m[1],
                            use_trend_regime=regime,
                            sell_threshold=sell_t,
                        ))
    return candidates


def generate_quarter_candidates() -> list[QuarterParams]:
    candidates = []
    for pct_52w in [(-5, -25), (-10, -30), (-15, -40)]:
        for chg6m in [(10, -10), (15, -15), (20, -20)]:
            for chg1y in [(15, -15), (20, -20), (30, -30)]:
                for sell_t in [-3, -4]:
                    candidates.append(QuarterParams(
                        pct_52w_buy=pct_52w[0], pct_52w_sell=pct_52w[1],
                        chg6m_buy=chg6m[0], chg6m_sell=chg6m[1],
                        chg1y_buy=chg1y[0], chg1y_sell=chg1y[1],
                        sell_threshold=sell_t,
                    ))
    return candidates


TIMEFRAME_CONFIG = {
    "days": {
        "candidates_fn": generate_days_candidates,
        "signal_fn": signal_days_param,
    },
    "weeks": {
        "candidates_fn": generate_weeks_candidates,
        "signal_fn": signal_weeks_param,
    },
    "months": {
        "candidates_fn": generate_months_candidates,
        "signal_fn": signal_months_param,
    },
    "quarter": {
        "candidates_fn": generate_quarter_candidates,
        "signal_fn": signal_quarter_param,
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# Part 4: Main Optimizer
# ═══════════════════════════════════════════════════════════════════════════════

def optimize_timeframe(
    all_dfs: dict[str, pd.DataFrame],
    timeframe: str,
    train_end: str,
    validate_start: str,
) -> tuple[dict, dict]:
    """
    Find the best parameters for a timeframe via grid search.

    Returns (best_params_dict, best_result).
    """
    config = TIMEFRAME_CONFIG[timeframe]
    candidates = config["candidates_fn"]()
    signal_fn = config["signal_fn"]

    logger.info("  %s: testing %d parameter combinations...", timeframe, len(candidates))

    best_score = -1
    best_params = None
    best_result = None

    for i, params in enumerate(candidates):
        if i > 0 and i % 100 == 0:
            logger.info("    %s: %d/%d (best score so far: %.4f)",
                        timeframe, i, len(candidates), best_score)

        result = evaluate_params(
            all_dfs, timeframe, signal_fn, params,
            train_end, validate_start,
        )

        if result["composite_score"] > best_score:
            best_score = result["composite_score"]
            best_params = params
            best_result = result

    return best_params.to_dict() if best_params else {}, best_result or {}


def main():
    parser = argparse.ArgumentParser(description="Optimize signal parameters")
    parser.add_argument("--exchange", default="US")
    parser.add_argument("--sample", type=int, default=200)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--train-end", default="2025-06-01",
                        help="End of training period (YYYY-MM-DD)")
    parser.add_argument("--validate-start", default="2025-06-01",
                        help="Start of validation period (YYYY-MM-DD)")
    parser.add_argument("--output", default=None,
                        help="Output JSON config path")
    args = parser.parse_args()

    if args.full:
        args.sample = None

    logger.info("═══ SIGNAL OPTIMIZER: %s exchange, sample=%s ═══",
                args.exchange, args.sample or "ALL")
    logger.info("    Train: ... → %s  |  Validate: %s → latest",
                args.train_end, args.validate_start)

    start_time = time.time()

    # Load all ticker data
    tickers = load_tickers(args.exchange, args.sample)
    logger.info("Loading price history for %d tickers...", len(tickers))

    all_dfs: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        df = load_price_history(ticker, args.exchange)
        if df is not None and len(df) >= 300:
            df = compute_all_indicators(df.copy())
            required = ["sma_200", "rsi_14", "macd_trend"]
            if df[required].notna().any().all():
                all_dfs[ticker] = df

    logger.info("Loaded %d tickers with sufficient data", len(all_dfs))

    # Optimize each timeframe
    optimized = {}
    for tf in ["days", "weeks", "months", "quarter"]:
        logger.info("\nOptimizing %s...", tf.upper())
        best_params, best_result = optimize_timeframe(
            all_dfs, tf, args.train_end, args.validate_start,
        )
        optimized[tf] = {
            "params": best_params,
            "validation_result": {
                "win_rates": best_result.get("win_rates", {}),
                "avg_returns": best_result.get("avg_returns", {}),
                "profit_factors": best_result.get("profit_factors", {}),
                "composite_score": best_result.get("composite_score", 0),
                "signal_counts": best_result.get("signal_counts", {}),
            },
        }
        logger.info("  Best %s score: %.4f", tf, best_result.get("composite_score", 0))
        for k, v in best_result.get("win_rates", {}).items():
            pf = best_result.get("profit_factors", {}).get(k, 0)
            logger.info("    %s: win=%.1f%% PF=%.2f", k, v, pf)

    elapsed = time.time() - start_time

    # Build output
    output = {
        "version": "auto-v3",
        "exchange": args.exchange,
        "optimized_at": datetime.now().isoformat(),
        "train_end": args.train_end,
        "validate_start": args.validate_start,
        "tickers_tested": len(all_dfs),
        "runtime_sec": round(elapsed, 1),
        "timeframes": optimized,
    }

    # Save
    output_path = args.output or f"/tmp/signal_config_{args.exchange.lower()}.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    logger.info("\n═══ OPTIMIZATION COMPLETE ═══")
    logger.info("  Runtime: %.1fs", elapsed)
    logger.info("  Config saved to: %s", output_path)
    logger.info("  Next: review config, then update screener thresholds")

    # Print summary comparison vs current (v2) params
    print("\n" + "=" * 70)
    print("  OPTIMIZED vs CURRENT (v2) PARAMETERS")
    print("=" * 70)
    for tf, data in optimized.items():
        print(f"\n  {tf.upper()}:")
        print(f"    Score: {data['validation_result']['composite_score']:.4f}")
        for k, v in data["params"].items():
            print(f"    {k}: {v}")
        print(f"    Win rates: {data['validation_result']['win_rates']}")
    print("=" * 70)


if __name__ == "__main__":
    main()
