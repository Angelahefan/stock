#!/usr/bin/env python3
"""
scripts/backtest_trade_lifecycle.py
══════════════════════════════════════════════════════════════════════════════
Trade-Level Backtest: Entry + Exit Simulation

Simulates full trade lifecycles to compare profitability across strategies:
  1. BASELINE:       Enter on BUY signal, exit after fixed N days
  2. RISK_GATED:     Only enter when Risk Agent risk_score < 0.7
  3. EXIT_MANAGED:   Enter on BUY, exit via Exit Agent rules (TP/SL/trail)
  4. FULL_COMMITTEE: Risk-gated entry + Exit-managed exit + regime weighting

This proves that the Investment Committee pattern (regime awareness +
quantitative risk gating + disciplined exit management) improves
profitability beyond simple forward-return win rate.

Usage:
    python scripts/backtest_trade_lifecycle.py --exchange US --sample 200
    python scripts/backtest_trade_lifecycle.py --exchange ASX --sample 100
    python scripts/backtest_trade_lifecycle.py --exchange US --full --start 2023-01-01

Metrics per strategy:
  - Win Rate          (% of trades with positive return)
  - Average Return    (mean % return per trade)
  - Median Return     (median % return per trade)
  - Profit Factor     (total gains / total losses)
  - Avg Trade Duration (days held)
  - Max Drawdown      (worst peak-to-trough per trade)
  - Sharpe-like Ratio (avg return / std dev)
  - Exit Breakdown    (% by take-profit / stop-loss / trail / time)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.backtest_signals import (
    compute_all_indicators,
    compute_signal_days,
    compute_signal_weeks,
    compute_signal_months,
    compute_signal_quarter,
    load_price_history,
    load_tickers,
)

# Import v2 agents
from agents.fundamental.macro_agent import (
    MarketRegime,
    classify_regime_from_ta,
    get_regime_weights,
)
from agents.stock_synthesis.risk_agent import assess_risk_from_row, RiskAssessment
from agents.stock_synthesis.exit_agent import (
    ExitAction,
    ExitSignal,
    check_exit,
    get_thresholds,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("backtest_lifecycle")


# ═══════════════════════════════════════════════════════════════════════════════
# Trade result data classes
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TradeResult:
    """Result of a single completed trade."""
    ticker: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    return_pct: float
    days_held: int
    max_drawdown_pct: float    # worst intra-trade drawdown
    exit_reason: str           # TAKE_PROFIT, CUT_LOSS, TRAIL_STOP, TIME_STOP, FIXED_EXIT
    timeframe: str
    regime: str
    risk_score: float


@dataclass
class StrategyStats:
    """Aggregated statistics for a strategy."""
    strategy: str
    trade_count: int = 0
    win_count: int = 0
    win_rate: float = 0.0
    avg_return: float = 0.0
    median_return: float = 0.0
    profit_factor: float = 0.0
    avg_duration: float = 0.0
    avg_max_drawdown: float = 0.0
    sharpe_like: float = 0.0
    exit_breakdown: Dict[str, int] = field(default_factory=dict)
    regime_breakdown: Dict[str, Dict[str, float]] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# Signal functions map
# ═══════════════════════════════════════════════════════════════════════════════

SIGNAL_FUNCS = {
    "days": compute_signal_days,
    "weeks": compute_signal_weeks,
    "months": compute_signal_months,
    "quarter": compute_signal_quarter,
}

# Fixed hold period per timeframe (for BASELINE strategy)
FIXED_HOLD_DAYS = {
    "days": 5,
    "weeks": 15,
    "months": 40,
    "quarter": 120,
}

# Max hold period (safety cap for EXIT_MANAGED)
MAX_HOLD_DAYS = {
    "days": 20,
    "weeks": 40,
    "months": 80,
    "quarter": 200,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Trade simulation
# ═══════════════════════════════════════════════════════════════════════════════

def simulate_baseline_trade(
    df: pd.DataFrame,
    entry_idx: int,
    timeframe: str,
    ticker: str,
) -> Optional[TradeResult]:
    """BASELINE: enter at signal, exit after fixed N days."""
    hold_days = FIXED_HOLD_DAYS[timeframe]
    exit_idx = entry_idx + hold_days

    if exit_idx >= len(df):
        return None

    entry_price = df.iloc[entry_idx]["Close"]
    exit_price = df.iloc[exit_idx]["Close"]
    if entry_price <= 0:
        return None

    # Compute max drawdown during hold
    prices = df.iloc[entry_idx:exit_idx + 1]["Close"].values
    peak = prices[0]
    max_dd = 0.0
    for p in prices:
        peak = max(peak, p)
        dd = ((peak - p) / peak) * 100
        max_dd = max(max_dd, dd)

    return_pct = ((exit_price - entry_price) / entry_price) * 100

    return TradeResult(
        ticker=ticker,
        entry_date=str(df.index[entry_idx].date()),
        exit_date=str(df.index[exit_idx].date()),
        entry_price=round(entry_price, 2),
        exit_price=round(exit_price, 2),
        return_pct=round(return_pct, 4),
        days_held=hold_days,
        max_drawdown_pct=round(max_dd, 2),
        exit_reason="FIXED_EXIT",
        timeframe=timeframe,
        regime="N/A",
        risk_score=0.0,
    )


def simulate_exit_managed_trade(
    df: pd.DataFrame,
    entry_idx: int,
    timeframe: str,
    ticker: str,
    risk_score: float = 0.0,
    regime: str = "NEUTRAL_TRANSITION",
) -> Optional[TradeResult]:
    """EXIT_MANAGED: enter at signal, exit via Exit Agent rules."""
    entry_price = df.iloc[entry_idx]["Close"]
    if entry_price <= 0:
        return None

    max_days = MAX_HOLD_DAYS[timeframe]
    highest = entry_price

    for day in range(1, max_days + 1):
        idx = entry_idx + day
        if idx >= len(df):
            break

        row = df.iloc[idx]
        current_price = row["Close"]
        highest = max(highest, current_price)

        ta_data = {
            "rsi_14": row.get("rsi_14"),
            "macd_trend": row.get("macd_trend"),
        }

        exit_signal = check_exit(
            entry_price=entry_price,
            current_price=current_price,
            highest_since_entry=highest,
            days_held=day,
            timeframe=timeframe,
            ta_data=ta_data,
        )

        if exit_signal.action != ExitAction.HOLD:
            # Compute max drawdown
            prices = df.iloc[entry_idx:idx + 1]["Close"].values
            peak = prices[0]
            max_dd = 0.0
            for p in prices:
                peak = max(peak, p)
                dd = ((peak - p) / peak) * 100
                max_dd = max(max_dd, dd)

            return_pct = ((current_price - entry_price) / entry_price) * 100

            return TradeResult(
                ticker=ticker,
                entry_date=str(df.index[entry_idx].date()),
                exit_date=str(df.index[idx].date()),
                entry_price=round(entry_price, 2),
                exit_price=round(current_price, 2),
                return_pct=round(return_pct, 4),
                days_held=day,
                max_drawdown_pct=round(max_dd, 2),
                exit_reason=exit_signal.action.value,
                timeframe=timeframe,
                regime=regime,
                risk_score=risk_score,
            )

    # Reached max hold — force exit
    exit_idx = min(entry_idx + max_days, len(df) - 1)
    exit_price = df.iloc[exit_idx]["Close"]
    return_pct = ((exit_price - entry_price) / entry_price) * 100

    prices = df.iloc[entry_idx:exit_idx + 1]["Close"].values
    peak = prices[0]
    max_dd = 0.0
    for p in prices:
        peak = max(peak, p)
        dd = ((peak - p) / peak) * 100
        max_dd = max(max_dd, dd)

    return TradeResult(
        ticker=ticker,
        entry_date=str(df.index[entry_idx].date()),
        exit_date=str(df.index[exit_idx].date()),
        entry_price=round(entry_price, 2),
        exit_price=round(exit_price, 2),
        return_pct=round(return_pct, 4),
        days_held=max_days,
        max_drawdown_pct=round(max_dd, 2),
        exit_reason="TIME_STOP",
        timeframe=timeframe,
        regime=regime,
        risk_score=risk_score,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Main backtest loop
# ═══════════════════════════════════════════════════════════════════════════════

def backtest_ticker_lifecycle(
    ticker: str,
    exchange: str,
    df: pd.DataFrame,
    start_date: Optional[str] = None,
    timeframes: Optional[List[str]] = None,
) -> Dict[str, List[TradeResult]]:
    """
    Run all 4 strategies on a single ticker.

    Returns dict: {"BASELINE": [...], "RISK_GATED": [...], "EXIT_MANAGED": [...], "FULL_COMMITTEE": [...]}
    """
    if len(df) < 300:
        return {}

    df = compute_all_indicators(df.copy())
    tfs = timeframes or ["days", "weeks", "months"]

    required = ["sma_200", "rsi_14", "macd_trend"]
    mask = df[required].notna().all(axis=1)
    valid_idx = df.index[mask]
    if len(valid_idx) == 0:
        return {}

    start_idx = valid_idx[0]
    if start_date:
        start_ts = pd.Timestamp(start_date)
        start_idx = max(start_idx, start_ts)

    results: Dict[str, List[TradeResult]] = {
        "BASELINE": [],
        "RISK_GATED": [],
        "EXIT_MANAGED": [],
        "FULL_COMMITTEE": [],
    }

    max_hold = max(MAX_HOLD_DAYS.values())

    for i, (dt, row) in enumerate(df.iterrows()):
        if dt < start_idx:
            continue
        if len(df) - i - 1 < max_hold:
            break

        for tf in tfs:
            signal_func = SIGNAL_FUNCS[tf]
            signal = signal_func(row)
            if signal != "BUY":
                continue

            # Compute regime from TA proxy
            regime = classify_regime_from_ta(
                sma_50=row.get("sma_50"),
                sma_200=row.get("sma_200"),
                rsi_14=row.get("rsi_14"),
                volatility_20d=row.get("volatility_20d"),
            )

            # Compute risk score
            row_dict = row.to_dict() if hasattr(row, 'to_dict') else dict(row)
            risk = assess_risk_from_row(row_dict, regime=regime.value)

            # Strategy 1: BASELINE
            trade = simulate_baseline_trade(df, i, tf, ticker)
            if trade:
                results["BASELINE"].append(trade)

            # Strategy 2: RISK_GATED
            if risk.risk_score < 0.7:
                trade = simulate_baseline_trade(df, i, tf, ticker)
                if trade:
                    trade.risk_score = risk.risk_score
                    trade.regime = regime.value
                    results["RISK_GATED"].append(trade)

            # Strategy 3: EXIT_MANAGED
            trade = simulate_exit_managed_trade(df, i, tf, ticker, risk.risk_score, regime.value)
            if trade:
                results["EXIT_MANAGED"].append(trade)

            # Strategy 4: FULL_COMMITTEE (risk-gated + exit-managed + regime filter)
            if risk.risk_score < 0.7:
                # In BEAR regime, only take BUY if fundamental-driven
                if regime == MarketRegime.BEAR_RECESSION:
                    # Skip pure momentum trades in bear market
                    if tf in ("days", "weeks"):
                        continue

                trade = simulate_exit_managed_trade(df, i, tf, ticker, risk.risk_score, regime.value)
                if trade:
                    results["FULL_COMMITTEE"].append(trade)

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Statistics computation
# ═══════════════════════════════════════════════════════════════════════════════

def compute_strategy_stats(strategy: str, trades: List[TradeResult]) -> StrategyStats:
    """Compute aggregated statistics for a strategy."""
    if not trades:
        return StrategyStats(strategy=strategy)

    returns = np.array([t.return_pct for t in trades])
    durations = np.array([t.days_held for t in trades])
    drawdowns = np.array([t.max_drawdown_pct for t in trades])

    wins = np.sum(returns > 0)
    win_rate = wins / len(returns) * 100

    # Profit factor
    gains = np.sum(returns[returns > 0]) if np.any(returns > 0) else 0
    losses = np.abs(np.sum(returns[returns < 0])) if np.any(returns < 0) else 0.001
    profit_factor = gains / losses if losses > 0 else 99.99

    # Sharpe-like ratio
    std_dev = np.std(returns)
    sharpe_like = np.mean(returns) / std_dev if std_dev > 0 else 0

    # Exit breakdown
    exit_counts: Dict[str, int] = defaultdict(int)
    for t in trades:
        exit_counts[t.exit_reason] += 1

    # Regime breakdown
    regime_data: Dict[str, List[float]] = defaultdict(list)
    for t in trades:
        regime_data[t.regime].append(t.return_pct)
    regime_breakdown = {
        r: {"count": len(rets), "avg_return": round(np.mean(rets), 2), "win_rate": round(np.mean(np.array(rets) > 0) * 100, 1)}
        for r, rets in regime_data.items()
    }

    return StrategyStats(
        strategy=strategy,
        trade_count=len(trades),
        win_count=int(wins),
        win_rate=round(win_rate, 1),
        avg_return=round(float(np.mean(returns)), 2),
        median_return=round(float(np.median(returns)), 2),
        profit_factor=round(profit_factor, 2),
        avg_duration=round(float(np.mean(durations)), 1),
        avg_max_drawdown=round(float(np.mean(drawdowns)), 2),
        sharpe_like=round(sharpe_like, 3),
        exit_breakdown=dict(exit_counts),
        regime_breakdown=regime_breakdown,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Report
# ═══════════════════════════════════════════════════════════════════════════════

def print_report(
    all_stats: Dict[str, StrategyStats],
    exchange: str,
    ticker_count: int,
    elapsed: float,
):
    """Print comparison report."""
    print("\n" + "=" * 95)
    print(f"  TRADE LIFECYCLE BACKTEST — {exchange} ({ticker_count} tickers, {elapsed:.1f}s)")
    print("=" * 95)

    # Header
    strategies = ["BASELINE", "RISK_GATED", "EXIT_MANAGED", "FULL_COMMITTEE"]
    print(f"\n  {'Metric':<22}", end="")
    for s in strategies:
        print(f"  │ {s:>14}", end="")
    print()
    print(f"  {'─' * 22}", end="")
    for _ in strategies:
        print(f"  │ {'─' * 14}", end="")
    print()

    # Metrics
    metrics = [
        ("Trades", lambda s: f"{s.trade_count:>14,}"),
        ("Win Rate", lambda s: f"{s.win_rate:>13.1f}%"),
        ("Avg Return", lambda s: f"{s.avg_return:>+13.2f}%"),
        ("Median Return", lambda s: f"{s.median_return:>+13.2f}%"),
        ("Profit Factor", lambda s: f"{s.profit_factor:>14.2f}"),
        ("Avg Duration (d)", lambda s: f"{s.avg_duration:>14.1f}"),
        ("Avg Max Drawdown", lambda s: f"{s.avg_max_drawdown:>13.2f}%"),
        ("Sharpe-like", lambda s: f"{s.sharpe_like:>14.3f}"),
    ]

    for metric_name, fmt in metrics:
        print(f"  {metric_name:<22}", end="")
        for s_name in strategies:
            stats = all_stats.get(s_name, StrategyStats(strategy=s_name))
            print(f"  │ {fmt(stats)}", end="")
        print()

    # Exit breakdown for EXIT_MANAGED and FULL_COMMITTEE
    print(f"\n── Exit Breakdown ──")
    for s_name in ["EXIT_MANAGED", "FULL_COMMITTEE"]:
        stats = all_stats.get(s_name)
        if stats and stats.exit_breakdown:
            total = sum(stats.exit_breakdown.values())
            print(f"  {s_name}:")
            for reason, count in sorted(stats.exit_breakdown.items(), key=lambda x: -x[1]):
                pct = count / total * 100
                print(f"    {reason:<15}: {count:>6,} ({pct:>5.1f}%)")

    # Regime breakdown for FULL_COMMITTEE
    fc = all_stats.get("FULL_COMMITTEE")
    if fc and fc.regime_breakdown:
        print(f"\n── Regime Breakdown (FULL_COMMITTEE) ──")
        for regime, data in sorted(fc.regime_breakdown.items()):
            print(f"  {regime:<25}: {data['count']:>5,} trades, "
                  f"win rate {data['win_rate']:.1f}%, avg return {data['avg_return']:+.2f}%")

    # Improvement summary
    baseline = all_stats.get("BASELINE", StrategyStats(strategy="BASELINE"))
    fc_stats = all_stats.get("FULL_COMMITTEE", StrategyStats(strategy="FULL_COMMITTEE"))
    if baseline.trade_count > 0 and fc_stats.trade_count > 0:
        wr_delta = fc_stats.win_rate - baseline.win_rate
        ret_delta = fc_stats.avg_return - baseline.avg_return
        pf_delta = fc_stats.profit_factor - baseline.profit_factor
        dd_delta = baseline.avg_max_drawdown - fc_stats.avg_max_drawdown

        print(f"\n── FULL_COMMITTEE vs BASELINE ──")
        print(f"  Win Rate:       {wr_delta:+.1f}% {'✓' if wr_delta > 0 else '✗'}")
        print(f"  Avg Return:     {ret_delta:+.2f}% {'✓' if ret_delta > 0 else '✗'}")
        print(f"  Profit Factor:  {pf_delta:+.2f} {'✓' if pf_delta > 0 else '✗'}")
        print(f"  Drawdown Reduction: {dd_delta:+.2f}% {'✓' if dd_delta > 0 else '✗'}")

        improvements = sum(1 for x in [wr_delta, ret_delta, pf_delta, dd_delta] if x > 0)
        if improvements >= 3:
            print(f"\n  ✅ FULL_COMMITTEE wins on {improvements}/4 metrics — Investment Committee improves profitability")
        elif improvements >= 2:
            print(f"\n  ⚠️  FULL_COMMITTEE wins on {improvements}/4 metrics — mixed results")
        else:
            print(f"\n  ❌ FULL_COMMITTEE wins on only {improvements}/4 metrics — needs tuning")

    print("\n" + "=" * 95)
    print("  Note: Past performance does not guarantee future results.")
    print("=" * 95 + "\n")


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Trade lifecycle backtest")
    parser.add_argument("--exchange", default="US")
    parser.add_argument("--sample", type=int, default=200)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--start", type=str, default="2023-01-01")
    parser.add_argument("--timeframes", type=str, default="days,weeks,months",
                        help="Comma-separated timeframes to test")
    args = parser.parse_args()

    if args.full:
        args.sample = None

    timeframes = [t.strip() for t in args.timeframes.split(",")]

    log.info("═══ TRADE LIFECYCLE BACKTEST: %s, sample=%s, start=%s, tf=%s ═══",
             args.exchange, args.sample or "ALL", args.start, timeframes)

    start_time = time.time()
    tickers = load_tickers(args.exchange, args.sample)
    if not tickers:
        log.error("No tickers found for %s", args.exchange)
        return

    # Aggregate all trades per strategy
    all_trades: Dict[str, List[TradeResult]] = {
        "BASELINE": [],
        "RISK_GATED": [],
        "EXIT_MANAGED": [],
        "FULL_COMMITTEE": [],
    }

    processed = 0
    for i, ticker in enumerate(tickers):
        if i % 50 == 0 and i > 0:
            total_trades = sum(len(t) for t in all_trades.values())
            log.info("Progress: %d/%d tickers (%.0f%%), %d total trades",
                     i, len(tickers), i / len(tickers) * 100, total_trades)

        df = load_price_history(ticker, args.exchange)
        if df is None:
            continue

        ticker_results = backtest_ticker_lifecycle(
            ticker, args.exchange, df,
            start_date=args.start,
            timeframes=timeframes,
        )

        for strategy, trades in ticker_results.items():
            all_trades[strategy].extend(trades)
        processed += 1

    elapsed = time.time() - start_time

    # Compute stats
    all_stats = {}
    for strategy, trades in all_trades.items():
        all_stats[strategy] = compute_strategy_stats(strategy, trades)

    # Print report
    print_report(all_stats, args.exchange, processed, elapsed)


if __name__ == "__main__":
    main()
