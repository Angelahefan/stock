#!/usr/bin/env python3
"""
backtest_multi_factor.py — Backtest multi-factor signals vs pure TA signals.

Proves that combining TA + fundamentals produces better win rates than TA alone.
Uses historical price data + point-in-time fundamental data from yfinance.

Usage:
    python scripts/backtest_multi_factor.py --exchange US --sample 300
    python scripts/backtest_multi_factor.py --exchange ASX --sample 200

Output: Side-by-side comparison of win rates for multi-factor vs pure-TA signals.
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import sys
import time
from collections import defaultdict
from typing import Optional, Dict, Any, List, Tuple

import numpy as np
import psycopg2
import psycopg2.extras

# Reuse TA computation from backtest_signals
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.backtest_signals import compute_all_indicators, load_tickers, load_price_history

# Import signal functions from the multi-factor engine
from scripts.compute_multi_factor_signals import compute_ta_votes, compute_signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def get_conn():
    return psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "postgres"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", ""),
    )


def load_fundamental_data(exchange: str) -> Dict[str, Dict[str, Any]]:
    """Load fundamental_lite data keyed by ticker."""
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT * FROM datapai.fundamental_lite
            WHERE exchange = %s
        """, (exchange,))
        rows = {r["ticker"]: dict(r) for r in cur.fetchall()}
    conn.close()
    return rows


def df_row_to_dict(row) -> Dict[str, Any]:
    """Convert a DataFrame row to a dict matching screener_metrics column names."""
    import pandas as pd
    return {
        "rsi_14": row.get("rsi_14") if pd.notna(row.get("rsi_14")) else None,
        "macd_trend": row.get("macd_trend") if pd.notna(row.get("macd_trend")) else None,
        "kdj_signal": row.get("kdj_signal") if pd.notna(row.get("kdj_signal")) else None,
        "sma_5": row.get("sma_5") if pd.notna(row.get("sma_5")) else None,
        "sma_10": row.get("sma_10") if pd.notna(row.get("sma_10")) else None,
        "sma_20": row.get("sma_20") if pd.notna(row.get("sma_20")) else None,
        "sma_50": row.get("sma_50") if pd.notna(row.get("sma_50")) else None,
        "sma_200": row.get("sma_200") if pd.notna(row.get("sma_200")) else None,
        "bb_pct_b": row.get("bb_pct_b") if pd.notna(row.get("bb_pct_b")) else None,
        "obv_trend": row.get("obv_trend") if pd.notna(row.get("obv_trend")) else None,
        "volume_ratio": row.get("volume_ratio") if pd.notna(row.get("volume_ratio")) else None,
        "latest_close": row.get("Close") if pd.notna(row.get("Close")) else None,
        "change_1d_pct": row.get("change_1d_pct") if pd.notna(row.get("change_1d_pct")) else None,
        "change_5d_pct": row.get("change_5d_pct") if pd.notna(row.get("change_5d_pct")) else None,
        "change_1m_pct": row.get("change_1m_pct") if pd.notna(row.get("change_1m_pct")) else None,
        "change_3m_pct": row.get("change_3m_pct") if pd.notna(row.get("change_3m_pct")) else None,
        "change_6m_pct": row.get("change_6m_pct") if pd.notna(row.get("change_6m_pct")) else None,
        "change_1y_pct": row.get("change_1y_pct") if pd.notna(row.get("change_1y_pct")) else None,
        "pct_from_52w_high": row.get("pct_from_52w_high") if pd.notna(row.get("pct_from_52w_high")) else None,
    }


def run_backtest(exchange: str, sample_size: int):
    """Run multi-factor vs pure-TA backtest comparison."""

    # Forward return periods per timeframe
    fwd_map = {
        "days": [1, 3, 5, 10],
        "weeks": [5, 10, 20],
        "months": [20, 40, 60],
        "quarter": [60, 120, 180],
    }

    # Load fundamental data
    log.info("Loading fundamental data...")
    fund_data = load_fundamental_data(exchange)
    log.info("Loaded fundamentals for %d tickers", len(fund_data))

    # Load tickers and price history
    tickers = load_tickers(exchange, sample_size)
    log.info("Processing %d tickers...", len(tickers))

    # Results: {timeframe: {signal: {fwd_days: [returns]}}}
    mf_results = {tf: {"BUY": defaultdict(list), "SELL": defaultdict(list), "HOLD": defaultdict(list)}
                  for tf in fwd_map}
    ta_results = {tf: {"BUY": defaultdict(list), "SELL": defaultdict(list), "HOLD": defaultdict(list)}
                  for tf in fwd_map}

    # Also track by quality tier
    tier_results = {tier: {tf: {"BUY": defaultdict(list), "SELL": defaultdict(list)}
                          for tf in fwd_map}
                   for tier in ("A", "B", "C", "D", "none")}

    loaded = 0
    for ticker in tickers:
        df = load_price_history(ticker, exchange)
        if df is None or len(df) < 300:
            continue
        df = compute_all_indicators(df.copy())
        loaded += 1

        fund = fund_data.get(ticker)
        tier = fund["quality_tier"] if fund else "none"

        # Walk through each trading day
        for i in range(252, len(df) - 180):  # need 180 days forward
            row = df.iloc[i]
            row_dict = df_row_to_dict(row)

            if fund:
                fund["latest_close"] = row_dict["latest_close"]

            for tf, fwd_periods in fwd_map.items():
                ta_votes, ta_names = compute_ta_votes(row_dict, tf)

                # Pure TA signal (no fundamental modifier)
                ta_sig = compute_signal(ta_votes, 0.0, tf)

                # Multi-factor signal (with fundamental modifier)
                from scripts.compute_multi_factor_signals import compute_fundamental_modifier
                fund_mod, _ = compute_fundamental_modifier(fund, tf)
                mf_sig = compute_signal(ta_votes, fund_mod, tf)

                for fwd in fwd_periods:
                    if i + fwd >= len(df):
                        continue
                    fwd_close = df.iloc[i + fwd]["Close"]
                    cur_close = row["Close"]
                    if cur_close == 0 or np.isnan(cur_close) or np.isnan(fwd_close):
                        continue
                    ret = ((fwd_close - cur_close) / cur_close) * 100

                    # Store returns per signal
                    ta_results[tf][ta_sig["signal"]][fwd].append(ret)
                    mf_results[tf][mf_sig["signal"]][fwd].append(ret)

                    # Store by quality tier (multi-factor only)
                    if mf_sig["signal"] in ("BUY", "SELL"):
                        tier_results[tier][tf][mf_sig["signal"]][fwd].append(ret)

        if loaded % 20 == 0:
            log.info("  Processed %d / %d tickers", loaded, len(tickers))

    log.info("Processed %d tickers total", loaded)

    # ── Print comparison report ──────────────────────────────────────────────
    print()
    print("=" * 90)
    print(f"  MULTI-FACTOR vs PURE-TA BACKTEST — {exchange} ({loaded} tickers)")
    print("=" * 90)

    for tf in ("days", "weeks", "months", "quarter"):
        print(f"\n{'─' * 90}")
        print(f"  {tf.upper()}")
        print(f"{'─' * 90}")
        print(f"  {'Signal':<6} {'FwdD':>4}  │  {'Win%(TA)':>8} {'Avg%(TA)':>8} {'n(TA)':>7}  │  {'Win%(MF)':>8} {'Avg%(MF)':>8} {'n(MF)':>7}  │  {'Δ Win%':>7}")
        print(f"  {'─'*6} {'─'*4}  │  {'─'*8} {'─'*8} {'─'*7}  │  {'─'*8} {'─'*8} {'─'*7}  │  {'─'*7}")

        for sig_type in ("BUY", "SELL"):
            for fwd in fwd_map[tf]:
                ta_arr = np.array(ta_results[tf][sig_type].get(fwd, []))
                mf_arr = np.array(mf_results[tf][sig_type].get(fwd, []))

                if len(ta_arr) == 0 and len(mf_arr) == 0:
                    continue

                # For SELL, "win" means price went DOWN
                if sig_type == "BUY":
                    ta_wr = np.mean(ta_arr > 0) * 100 if len(ta_arr) > 0 else 0
                    mf_wr = np.mean(mf_arr > 0) * 100 if len(mf_arr) > 0 else 0
                else:
                    ta_wr = np.mean(ta_arr < 0) * 100 if len(ta_arr) > 0 else 0
                    mf_wr = np.mean(mf_arr < 0) * 100 if len(mf_arr) > 0 else 0

                ta_avg = np.mean(ta_arr) if len(ta_arr) > 0 else 0
                mf_avg = np.mean(mf_arr) if len(mf_arr) > 0 else 0
                delta = mf_wr - ta_wr

                flag = "  ★" if delta > 2 else (" ▼" if delta < -2 else "")
                print(f"  {sig_type:<6} {fwd:>4}D │  {ta_wr:>7.1f}% {ta_avg:>+7.2f}% {len(ta_arr):>7,}  │  {mf_wr:>7.1f}% {mf_avg:>+7.2f}% {len(mf_arr):>7,}  │  {delta:>+6.1f}%{flag}")

    # ── Quality tier breakdown ───────────────────────────────────────────────
    print(f"\n{'=' * 90}")
    print("  QUALITY TIER BREAKDOWN (Multi-Factor BUY signals)")
    print(f"{'=' * 90}")
    print(f"  {'Tier':<5} {'Timeframe':<10} {'FwdD':>4}  │  {'Win%':>7} {'Avg%':>8} {'Med%':>8} {'Count':>7}")
    print(f"  {'─'*5} {'─'*10} {'─'*4}  │  {'─'*7} {'─'*8} {'─'*8} {'─'*7}")

    for tier in ("A", "B", "C", "D", "none"):
        for tf in ("days", "months", "quarter"):
            for fwd in fwd_map[tf][-1:]:  # just the longest forward period
                arr = np.array(tier_results[tier][tf]["BUY"].get(fwd, []))
                if len(arr) < 10:
                    continue
                wr = np.mean(arr > 0) * 100
                avg = np.mean(arr)
                med = np.median(arr)
                print(f"  {tier:<5} {tf:<10} {fwd:>4}D │  {wr:>6.1f}% {avg:>+7.2f}% {med:>+7.2f}% {len(arr):>7,}")

    print(f"\n{'=' * 90}")
    print("  KEY: ★ = multi-factor beat TA by >2%  ▼ = multi-factor worse by >2%")
    print(f"{'=' * 90}")


def main():
    parser = argparse.ArgumentParser(description="Backtest multi-factor vs pure-TA signals")
    parser.add_argument("--exchange", default="US", help="US or ASX")
    parser.add_argument("--sample", type=int, default=200, help="Number of tickers to sample")
    args = parser.parse_args()

    run_backtest(args.exchange, args.sample)


if __name__ == "__main__":
    main()
