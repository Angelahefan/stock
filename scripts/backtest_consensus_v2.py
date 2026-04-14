#!/usr/bin/env python3
"""
backtest_consensus_v2.py — TRUE Multi-Agent Consensus Backtest
══════════════════════════════════════════════════════════════════

The right way: FA SELECTS the stock, TA TIMES the entry, Macro FILTERS the regime.

Investment process:
  Step 1 (FA): Screen universe for quality — profitable, growing, healthy
  Step 2 (Macro): Only trade in favorable regime (golden cross = bull market)
  Step 3 (TA): Wait for technical entry signal (momentum confirmation)
  Step 4 (Risk): Reject if drawdown/volatility too high
  Step 5 (Exit): Manage trade with stop-loss, take-profit, trailing stop

This is how real institutional investors work:
  "Buy GOOD companies at GOOD prices at the RIGHT time"

NOT: "Buy anything when RSI bounces"
"""
import argparse
import logging
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.backtest_signals import (
    compute_all_indicators,
    compute_signal_months,
    compute_signal_quarter,
    compute_signal_weeks,
    load_price_history,
)
from agents.fundamental.macro_agent import classify_regime_from_ta, MarketRegime
from agents.stock_synthesis.exit_agent import check_exit, ExitAction

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("consensus_v2")


@dataclass
class Trade:
    ticker: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    return_pct: float
    days_held: int
    max_drawdown_pct: float
    exit_reason: str
    regime: str
    quality_tier: str
    sector: str


def get_conn():
    from scripts.lib.db_helpers import get_conn as _get_conn
    return _get_conn()


def load_fa_universe(exchange: str) -> Dict[str, dict]:
    """
    Step 1: FA screens the universe.
    Returns tickers that meet fundamental quality criteria.
    """
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT ticker, quality_tier, sector, industry,
                   pe_ratio, forward_pe, roe, revenue_yoy, earnings_yoy,
                   is_profitable, is_growing, is_healthy,
                   market_cap, debt_to_equity, gross_margin, operating_margin,
                   peg_ratio, ev_ebitda
            FROM datapai.fundamental_lite
            WHERE exchange = %s
        """, (exchange,))
        all_tickers = {r["ticker"]: dict(r) for r in cur.fetchall()}
    conn.close()
    return all_tickers


def fa_screen(fund: dict, level: str = "quality") -> bool:
    """
    Fundamental screening levels:
      - 'any':     just has fundamental data
      - 'quality': quality_tier A or B
      - 'growth':  profitable + growing
      - 'strict':  quality A/B + profitable + growing + healthy
    """
    if level == "any":
        return True
    if level == "quality":
        return fund.get("quality_tier") in ("A", "B")
    if level == "growth":
        return bool(fund.get("is_profitable")) and bool(fund.get("is_growing"))
    if level == "strict":
        return (
            fund.get("quality_tier") in ("A", "B")
            and bool(fund.get("is_profitable"))
            and bool(fund.get("is_growing"))
            and bool(fund.get("is_healthy"))
        )
    return True


def simulate_managed_trade(df, entry_idx, ticker, regime, quality, sector, timeframe="months", max_days=120):
    """Exit Agent managed trade with quality-aware stop/target levels."""
    entry_p = df.iloc[entry_idx]["Close"]
    if entry_p <= 0:
        return None

    # Quality stocks get wider stops
    from agents.stock_synthesis.exit_agent import get_thresholds as _get_thresholds
    custom_thresholds = _get_thresholds(timeframe, quality=quality)

    highest = entry_p
    for day in range(1, max_days + 1):
        idx = entry_idx + day
        if idx >= len(df):
            break

        row = df.iloc[idx]
        cur_p = row["Close"]
        highest = max(highest, cur_p)

        ta_data = {"rsi_14": row.get("rsi_14"), "macd_trend": row.get("macd_trend")}

        sig = check_exit(
            entry_price=entry_p, current_price=cur_p,
            highest_since_entry=highest, days_held=day,
            timeframe=timeframe, ta_data=ta_data,
            custom_thresholds=custom_thresholds,
        )

        if sig.action != ExitAction.HOLD:
            prices = df.iloc[entry_idx:idx + 1]["Close"].values
            peak, max_dd = prices[0], 0.0
            for p in prices:
                peak = max(peak, p)
                max_dd = max(max_dd, ((peak - p) / peak) * 100)

            ret = ((cur_p - entry_p) / entry_p) * 100
            return Trade(
                ticker=ticker, entry_date=str(df.index[entry_idx].date()),
                exit_date=str(df.index[idx].date()),
                entry_price=round(entry_p, 2), exit_price=round(cur_p, 2),
                return_pct=round(ret, 4), days_held=day,
                max_drawdown_pct=round(max_dd, 2), exit_reason=sig.action.value,
                regime=regime, quality_tier=quality, sector=sector,
            )

    # Max hold reached
    exit_idx = min(entry_idx + max_days, len(df) - 1)
    exit_p = df.iloc[exit_idx]["Close"]
    ret = ((exit_p - entry_p) / entry_p) * 100
    prices = df.iloc[entry_idx:exit_idx + 1]["Close"].values
    peak, max_dd = prices[0], 0.0
    for p in prices:
        peak = max(peak, p)
        max_dd = max(max_dd, ((peak - p) / peak) * 100)
    return Trade(
        ticker=ticker, entry_date=str(df.index[entry_idx].date()),
        exit_date=str(df.index[exit_idx].date()),
        entry_price=round(entry_p, 2), exit_price=round(exit_p, 2),
        return_pct=round(ret, 4), days_held=max_days,
        max_drawdown_pct=round(max_dd, 2), exit_reason="MAX_HOLD",
        regime=regime, quality_tier=quality, sector=sector,
    )


def simulate_hold_trade(df, entry_idx, hold_days, ticker, regime, quality, sector):
    """Fixed hold period trade."""
    exit_idx = entry_idx + hold_days
    if exit_idx >= len(df):
        return None
    entry_p = df.iloc[entry_idx]["Close"]
    exit_p = df.iloc[exit_idx]["Close"]
    if entry_p <= 0:
        return None
    prices = df.iloc[entry_idx:exit_idx + 1]["Close"].values
    peak, max_dd = prices[0], 0.0
    for p in prices:
        peak = max(peak, p)
        max_dd = max(max_dd, ((peak - p) / peak) * 100)
    ret = ((exit_p - entry_p) / entry_p) * 100
    return Trade(
        ticker=ticker, entry_date=str(df.index[entry_idx].date()),
        exit_date=str(df.index[exit_idx].date()),
        entry_price=round(entry_p, 2), exit_price=round(exit_p, 2),
        return_pct=round(ret, 4), days_held=hold_days,
        max_drawdown_pct=round(max_dd, 2), exit_reason="FIXED_HOLD",
        regime=regime, quality_tier=quality, sector=sector,
    )


def run_backtest(exchange: str, start_date: str, hold_days: int):
    """
    Run the TRUE multi-agent consensus backtest.

    Universe = FA-screened tickers (not random sample).
    Entry = TA signal + macro regime.
    """
    log.info("Step 1: FA screens the universe...")
    all_fund = load_fa_universe(exchange)
    log.info("Total tickers with fundamentals: %d", len(all_fund))

    def simulate_trail_only_trade(df, entry_idx, ticker, regime, quality, sector, max_days=180):
        """Trail-only: no hard stop-loss, only trailing stop to protect gains. Let winners run."""
        entry_p = df.iloc[entry_idx]["Close"]
        if entry_p <= 0:
            return None

        highest = entry_p
        # Only activate trailing stop after stock is up at least 10%
        trail_pct = 12.0 if quality in ("A", "B") else 10.0
        activation_pct = 10.0

        for day in range(1, max_days + 1):
            idx = entry_idx + day
            if idx >= len(df):
                break

            cur_p = df.iloc[idx]["Close"]
            highest = max(highest, cur_p)

            pnl_pct = ((cur_p - entry_p) / entry_p) * 100
            drawdown_from_peak = ((highest - cur_p) / highest) * 100

            # Only trail if we've been up enough to activate
            peak_gain = ((highest - entry_p) / entry_p) * 100
            if peak_gain >= activation_pct and drawdown_from_peak >= trail_pct:
                prices = df.iloc[entry_idx:idx + 1]["Close"].values
                pk, max_dd = prices[0], 0.0
                for p in prices:
                    pk = max(pk, p)
                    max_dd = max(max_dd, ((pk - p) / pk) * 100)

                return Trade(
                    ticker=ticker, entry_date=str(df.index[entry_idx].date()),
                    exit_date=str(df.index[idx].date()),
                    entry_price=round(entry_p, 2), exit_price=round(cur_p, 2),
                    return_pct=round(pnl_pct, 4), days_held=day,
                    max_drawdown_pct=round(max_dd, 2), exit_reason="TRAIL_STOP",
                    regime=regime, quality_tier=quality, sector=sector,
                )

        # Max hold — exit at end
        exit_idx = min(entry_idx + max_days, len(df) - 1)
        exit_p = df.iloc[exit_idx]["Close"]
        ret = ((exit_p - entry_p) / entry_p) * 100
        prices = df.iloc[entry_idx:exit_idx + 1]["Close"].values
        pk, max_dd = prices[0], 0.0
        for p in prices:
            pk = max(pk, p)
            max_dd = max(max_dd, ((pk - p) / pk) * 100)
        return Trade(
            ticker=ticker, entry_date=str(df.index[entry_idx].date()),
            exit_date=str(df.index[exit_idx].date()),
            entry_price=round(entry_p, 2), exit_price=round(exit_p, 2),
            return_pct=round(ret, 4), days_held=max_days,
            max_drawdown_pct=round(max_dd, 2), exit_reason="MAX_HOLD",
            regime=regime, quality_tier=quality, sector=sector,
        )

    # Define strategies with different FA screening levels
    strategies = {
        "TA_ONLY (all fund)":  {"fa_level": "any",     "regime_filter": False, "exit_managed": False},
        "FA Quality (A/B)":    {"fa_level": "quality", "regime_filter": False, "exit_managed": False},
        "FA+Regime (Bull)":    {"fa_level": "quality", "regime_filter": True,  "exit_managed": False},
        "FA+Regime+Exit":      {"fa_level": "quality", "regime_filter": True,  "exit_managed": True},
        "Strict+Regime":       {"fa_level": "strict",  "regime_filter": True,  "exit_managed": False},
        "Strict+Regime+Exit":  {"fa_level": "strict",  "regime_filter": True,  "exit_managed": True},
        "Strict+TrailOnly":    {"fa_level": "strict",  "regime_filter": True,  "exit_managed": "trail_only"},
    }

    results = {name: [] for name in strategies}
    processed = 0

    # Process ALL tickers with fundamental data (not a random sample)
    tickers = list(all_fund.keys())
    log.info("Processing all %d tickers with fundamentals...", len(tickers))

    for i, ticker in enumerate(tickers):
        if i % 50 == 0 and i > 0:
            total = sum(len(v) for v in results.values())
            log.info("Progress: %d/%d tickers, %d total trades", i, len(tickers), total)

        from scripts.backtest_signals import load_price_history
        df = load_price_history(ticker, exchange)
        if df is None or len(df) < 400:
            continue
        df = compute_all_indicators(df.copy())
        processed += 1

        fund = all_fund[ticker]
        quality = fund.get("quality_tier", "D")
        sector = fund.get("sector", "Unknown")

        for j in range(252, len(df) - hold_days - 30):
            row = df.iloc[j]

            # TA signal check (months + quarter — medium/long term only)
            sig_m = compute_signal_months(row)
            sig_q = compute_signal_quarter(row)
            ta_buy = sig_m == "BUY" or sig_q == "BUY"
            if not ta_buy:
                continue

            # Regime check
            regime = classify_regime_from_ta(
                sma_50=row.get("sma_50"), sma_200=row.get("sma_200"),
                rsi_14=row.get("rsi_14"), volatility_20d=row.get("volatility_20d"),
            )

            # Run each strategy
            for name, config in strategies.items():
                # FA screen
                if not fa_screen(fund, config["fa_level"]):
                    continue
                # Regime filter
                if config["regime_filter"] and regime != MarketRegime.BULL_MOMENTUM:
                    continue

                # Execute trade
                if config["exit_managed"] == "trail_only":
                    trade = simulate_trail_only_trade(
                        df, j, ticker, regime.value, quality, sector,
                        max_days=hold_days,
                    )
                elif config["exit_managed"]:
                    trade = simulate_managed_trade(
                        df, j, ticker, regime.value, quality, sector,
                        timeframe="months", max_days=hold_days,
                    )
                else:
                    trade = simulate_hold_trade(df, j, hold_days, ticker, regime.value, quality, sector)

                if trade:
                    results[name].append(trade)

    # ═══════════════════════════════════════════════════════════════════════
    # Report
    # ═══════════════════════════════════════════════════════════════════════
    print()
    print("=" * 120)
    print(f"  TRUE MULTI-AGENT CONSENSUS BACKTEST — {exchange}")
    print(f"  Universe: {processed} tickers with FA data | Hold: {hold_days}d | Since: {start_date}")
    print(f"  Process: FA selects stock → Macro filters regime → TA times entry → Exit manages trade")
    print("=" * 120)

    print(f"\n  {'Strategy':<22} {'Tickers':>7} {'Trades':>7} {'Win':>6} "
          f"{'AvgRet':>8} {'MedRet':>8} {'P25':>8} {'P75':>8} {'PF':>6} "
          f"{'AvgDD':>7} {'AnnRet':>8}")
    print("  " + "-" * 115)

    baseline_med = 0
    for name in strategies:
        trades = results[name]
        if not trades:
            print(f"  {name:<22} {'0':>7} {'0':>7}")
            continue

        rets = np.array([t.return_pct for t in trades])
        dds = np.array([t.max_drawdown_pct for t in trades])
        durations = np.array([t.days_held for t in trades])
        unique_tickers = len(set(t.ticker for t in trades))

        win = np.mean(rets > 0) * 100
        gains = np.sum(rets[rets > 0]) if np.any(rets > 0) else 0
        losses = np.abs(np.sum(rets[rets < 0])) if np.any(rets < 0) else 0.001
        pf = gains / losses
        avg_dur = np.mean(durations)
        ann_ret = np.median(rets) * (252 / avg_dur) if avg_dur > 0 else 0

        if name == "TA_ONLY (all fund)":
            baseline_med = np.median(rets)

        # Improvement marker
        mark = ""
        cur_med = np.median(rets)
        if baseline_med != 0 and name != "TA_ONLY (all fund)":
            improvement = ((cur_med - baseline_med) / abs(baseline_med)) * 100 if baseline_med != 0 else 0
            if improvement > 100:
                mark = " ★★★"
            elif improvement > 50:
                mark = " ★★"
            elif improvement > 20:
                mark = " ★"

        print(f"  {name:<22} {unique_tickers:>7} {len(trades):>7,} {win:>5.1f}% "
              f"{np.mean(rets):>+7.2f}% {np.median(rets):>+7.2f}% "
              f"{np.percentile(rets, 25):>+7.1f}% {np.percentile(rets, 75):>+7.1f}% "
              f"{pf:>5.2f} {np.mean(dds):>6.1f}% "
              f"{ann_ret:>+7.1f}%{mark}")

    # Sector analysis for best strategy
    best_name = "Strict+Regime+Exit" if results["Strict+Regime+Exit"] else "FA+Regime+Exit"
    best_trades = results[best_name]
    if best_trades:
        print(f"\n── Sector Breakdown ({best_name}) ──")
        sector_groups = defaultdict(list)
        for t in best_trades:
            sector_groups[t.sector].append(t.return_pct)
        for sector, rets in sorted(sector_groups.items(), key=lambda x: np.median(x[1]), reverse=True):
            arr = np.array(rets)
            if len(arr) < 3:
                continue
            print(f"  {sector:<30}: {len(arr):>4} trades, win {np.mean(arr > 0)*100:>5.1f}%, "
                  f"avg {np.mean(arr):>+7.2f}%, med {np.median(arr):>+7.2f}%")

    # Exit breakdown
    if best_trades and any(t.exit_reason != "FIXED_HOLD" for t in best_trades):
        print(f"\n── Exit Breakdown ({best_name}) ──")
        exit_groups = defaultdict(list)
        for t in best_trades:
            exit_groups[t.exit_reason].append(t.return_pct)
        for reason, rets in sorted(exit_groups.items(), key=lambda x: -len(x[1])):
            arr = np.array(rets)
            print(f"  {reason:<15}: {len(arr):>5} ({len(arr)/len(best_trades)*100:>5.1f}%), "
                  f"win {np.mean(arr > 0)*100:>5.1f}%, avg {np.mean(arr):>+7.2f}%, med {np.median(arr):>+7.2f}%")

    # Summary comparison
    ta_only = results["TA_ONLY (all fund)"]
    best = results[best_name]
    if ta_only and best:
        ta_med = np.median([t.return_pct for t in ta_only])
        best_med = np.median([t.return_pct for t in best])
        ta_wr = np.mean([t.return_pct > 0 for t in ta_only]) * 100
        best_wr = np.mean([t.return_pct > 0 for t in best]) * 100
        ta_dd = np.mean([t.max_drawdown_pct for t in ta_only])
        best_dd = np.mean([t.max_drawdown_pct for t in best])

        print(f"\n{'═' * 60}")
        print(f"  VERDICT: {best_name} vs TA_ONLY")
        print(f"{'═' * 60}")
        print(f"  Win Rate:      {ta_wr:.1f}% → {best_wr:.1f}%  ({best_wr - ta_wr:>+.1f}%)")
        print(f"  Median Return: {ta_med:+.2f}% → {best_med:+.2f}%  ({best_med - ta_med:>+.2f}%)")
        print(f"  Avg Drawdown:  {ta_dd:.1f}% → {best_dd:.1f}%  ({best_dd - ta_dd:>+.1f}%)")
        if best_med > ta_med and best_wr > ta_wr:
            print(f"\n  ✅ Multi-agent consensus WORKS — better returns with less risk")
        elif best_med > ta_med:
            print(f"\n  ⚠️  Better returns but mixed win rate — needs tuning")
        else:
            print(f"\n  ❌ Not enough improvement — need more FA data or better screening")

    print(f"\n{'═' * 120}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange", default="US")
    parser.add_argument("--start", default="2023-06-01")
    parser.add_argument("--hold", type=int, default=90)
    args = parser.parse_args()

    start = time.time()
    run_backtest(args.exchange, args.start, args.hold)
    log.info("Completed in %.1fs", time.time() - start)


if __name__ == "__main__":
    main()
