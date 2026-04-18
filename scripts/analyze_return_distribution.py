#!/usr/bin/env python3
"""Quick analysis: what returns are actually achievable from BUY signals?"""
import sys, os
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.backtest_signals import (
    compute_all_indicators, load_tickers, load_price_history,
    compute_signal_weeks, compute_signal_months, compute_signal_quarter,
)

tickers = load_tickers("US", 200)
hold_periods = [20, 40, 60, 90, 120, 180]
results = {p: [] for p in hold_periods}
max_drawdowns = {p: [] for p in hold_periods}

loaded = 0
for ticker in tickers:
    df = load_price_history(ticker, "US")
    if df is None or len(df) < 400:
        continue
    df = compute_all_indicators(df.copy())
    loaded += 1

    for i in range(252, len(df) - 180):
        row = df.iloc[i]
        # Test months and quarter signals
        sig_m = compute_signal_months(row)
        sig_q = compute_signal_quarter(row)
        if sig_m != "BUY" and sig_q != "BUY":
            continue
        entry = row["Close"]
        if entry <= 0:
            continue

        for p in hold_periods:
            if i + p >= len(df):
                continue
            exit_price = df.iloc[i + p]["Close"]
            ret = ((exit_price - entry) / entry) * 100
            results[p].append(ret)

            # Track max drawdown during hold
            prices = df.iloc[i:i + p + 1]["Close"].values
            peak = prices[0]
            worst_dd = 0.0
            for px in prices:
                peak = max(peak, px)
                dd = ((peak - px) / peak) * 100
                worst_dd = max(worst_dd, dd)
            max_drawdowns[p].append(worst_dd)

print(f"\nTickers: {loaded}, BUY signals analyzed")
print(f"\n{'Period':>8} {'Trades':>7} {'Win':>6} {'AvgRet':>8} {'MedRet':>8} {'P10':>8} {'P25':>8} {'P75':>8} {'P90':>8} {'AvgDD':>8}")
print("-" * 85)
for p in hold_periods:
    arr = np.array(results[p])
    dd_arr = np.array(max_drawdowns[p])
    if len(arr) == 0:
        continue
    wr = np.mean(arr > 0) * 100
    print(
        f"{p:>6}d {len(arr):>7,} {wr:>5.1f}% "
        f"{np.mean(arr):>+7.2f}% {np.median(arr):>+7.2f}% "
        f"{np.percentile(arr, 10):>+7.1f}% {np.percentile(arr, 25):>+7.1f}% "
        f"{np.percentile(arr, 75):>+7.1f}% {np.percentile(arr, 90):>+7.1f}% "
        f"{np.mean(dd_arr):>7.1f}%"
    )

# Annualized returns
print(f"\n{'Period':>8} {'AnnRet(avg)':>12} {'AnnRet(med)':>12}")
print("-" * 35)
for p in hold_periods:
    arr = np.array(results[p])
    if len(arr) == 0:
        continue
    ann_avg = np.mean(arr) * (252 / p)
    ann_med = np.median(arr) * (252 / p)
    print(f"{p:>6}d {ann_avg:>+11.1f}% {ann_med:>+11.1f}%")

# What if we only take signals with favorable regime (golden cross)?
print("\n\n=== REGIME-FILTERED (Golden Cross only) ===")
regime_results = {p: [] for p in hold_periods}
regime_dd = {p: [] for p in hold_periods}

for ticker in tickers:
    df = load_price_history(ticker, "US")
    if df is None or len(df) < 400:
        continue
    df = compute_all_indicators(df.copy())

    for i in range(252, len(df) - 180):
        row = df.iloc[i]
        sma50 = row.get("sma_50")
        sma200 = row.get("sma_200")
        if sma50 is None or sma200 is None or sma50 <= sma200:
            continue  # Only golden cross

        sig_m = compute_signal_months(row)
        sig_q = compute_signal_quarter(row)
        if sig_m != "BUY" and sig_q != "BUY":
            continue
        entry = row["Close"]
        if entry <= 0:
            continue

        for p in hold_periods:
            if i + p >= len(df):
                continue
            exit_price = df.iloc[i + p]["Close"]
            ret = ((exit_price - entry) / entry) * 100
            regime_results[p].append(ret)

            prices = df.iloc[i:i + p + 1]["Close"].values
            peak = prices[0]
            worst_dd = 0.0
            for px in prices:
                peak = max(peak, px)
                dd = ((peak - px) / peak) * 100
                worst_dd = max(worst_dd, dd)
            regime_dd[p].append(worst_dd)

print(f"\n{'Period':>8} {'Trades':>7} {'Win':>6} {'AvgRet':>8} {'MedRet':>8} {'P25':>8} {'P75':>8} {'AnnAvg':>8} {'AnnMed':>8} {'AvgDD':>8}")
print("-" * 90)
for p in hold_periods:
    arr = np.array(regime_results[p])
    dd_arr = np.array(regime_dd[p])
    if len(arr) == 0:
        continue
    wr = np.mean(arr > 0) * 100
    ann_avg = np.mean(arr) * (252 / p)
    ann_med = np.median(arr) * (252 / p)
    print(
        f"{p:>6}d {len(arr):>7,} {wr:>5.1f}% "
        f"{np.mean(arr):>+7.2f}% {np.median(arr):>+7.2f}% "
        f"{np.percentile(arr, 25):>+7.1f}% {np.percentile(arr, 75):>+7.1f}% "
        f"{ann_avg:>+7.1f}% {ann_med:>+7.1f}% "
        f"{np.mean(dd_arr):>7.1f}%"
    )
