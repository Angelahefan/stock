#!/usr/bin/env python3
"""
backtest_signal_driven.py — Signal-Driven Multi-Agent Backtest
══════════════════════════════════════════════════════════════════

The RIGHT approach:
  - BUY when multiple agents agree
  - HOLD as long as agents still say BUY/HOLD
  - ADD (buy more) when we're profitable AND agents still say BUY
  - SELL only when agents FLIP (TA turns bearish, or regime turns BEAR)
  - NEVER sell just because you hit a profit target

This models how real investors think:
  "I sell when the reason I bought changes, not when a number triggers."
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
    load_price_history,
)
from agents.fundamental.macro_agent import classify_regime_from_ta, MarketRegime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("signal_driven")


@dataclass
class Trade:
    ticker: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    return_pct: float
    days_held: int
    max_gain_pct: float
    max_drawdown_pct: float
    exit_reason: str
    quality_tier: str
    sector: str
    add_count: int = 0  # how many times we added to position


def get_conn():
    from scripts.lib.db_helpers import get_conn as _get_conn
    return _get_conn()


def load_fa_universe(exchange: str) -> Dict[str, dict]:
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT ticker, quality_tier, sector, industry,
                   is_profitable, is_growing, is_healthy
            FROM datapai.fundamental_lite
            WHERE exchange = %s
        """, (exchange,))
        data = {r["ticker"]: dict(r) for r in cur.fetchall()}
    conn.close()
    return data


def simulate_signal_driven_trade(
    df, entry_idx, ticker, quality, sector,
    max_days=250, catastrophe_stop=-25.0,
):
    """
    v3 Signal-driven trade using the regime-aware Exit Agent.

    Exit Agent decides based on:
    - Regime (bull=patient, bear=sensitive)
    - Quality (A/B=tolerant, C/D=tight)
    - TA signal consensus (need multiple signals agreeing, not just one)
    - Trailing stop only after significant gain
    - Catastrophe stop as circuit breaker

    We NEVER sell just because price hit a target.
    We sell when the BUY THESIS BREAKS (agents flip to sell).
    """
    from agents.stock_synthesis.exit_agent import check_exit, ExitAction

    entry_p = df.iloc[entry_idx]["Close"]
    if entry_p <= 0:
        return None

    highest = entry_p
    add_count = 0

    for day in range(1, max_days + 1):
        idx = entry_idx + day
        if idx >= len(df):
            break

        row = df.iloc[idx]
        cur_p = row["Close"]
        highest = max(highest, cur_p)

        # Current regime
        regime = classify_regime_from_ta(
            sma_50=row.get("sma_50"), sma_200=row.get("sma_200"),
            rsi_14=row.get("rsi_14"), volatility_20d=row.get("volatility_20d"),
        )

        # Build full TA data for exit agent
        ta_data = {
            "rsi_14": row.get("rsi_14"),
            "macd_trend": row.get("macd_trend"),
            "kdj_signal": row.get("kdj_signal"),
            "sma_50": row.get("sma_50"),
            "sma_200": row.get("sma_200"),
            "bb_pct_b": row.get("bb_pct_b"),
            "obv_trend": row.get("obv_trend"),
            "volume_ratio": row.get("volume_ratio"),
            "change_1d_pct": row.get("change_1d_pct"),
        }

        # Ask the Exit Agent
        signal = check_exit(
            entry_price=entry_p,
            current_price=cur_p,
            highest_since_entry=highest,
            days_held=day,
            timeframe="months",
            ta_data=ta_data,
            regime=regime.value,
            quality=quality,
        )

        if signal.action == ExitAction.ADD:
            add_count += 1
            continue  # keep holding, would add in real trading

        if signal.action not in (ExitAction.HOLD, ExitAction.ADD):
            return _build_trade(
                df, entry_idx, idx, ticker, quality, sector,
                day, highest, signal.action.value, add_count,
            )

    # Max hold reached
    return _build_trade(
        df, entry_idx, min(entry_idx + max_days, len(df) - 1),
        ticker, quality, sector, max_days, highest, "MAX_HOLD", add_count,
    )


def simulate_multi_tf_trade(
    df, entry_idx, ticker, quality, sector,
    max_days=250,
):
    """
    Multi-timeframe driven trade: only exit when WEEKLY confirms daily sell.

    For quality stocks in bull market:
    - Daily sell alone = noise, HOLD
    - Daily + Weekly bearish = trend weakening, EXIT
    - Only catastrophe stop (-30%) and critical news bypass this

    This is how professional investors think: daily chart for entry timing,
    weekly/monthly chart for trend direction. Never fight the higher timeframe.
    """
    from agents.stock_synthesis.multi_timeframe import (
        compute_weekly_monthly_at_index,
        analyze_multi_tf,
    )
    from agents.stock_synthesis.exit_agent import _count_ta_sell_signals

    entry_p = df.iloc[entry_idx]["Close"]
    if entry_p <= 0:
        return None

    highest = entry_p
    add_count = 0
    # Only compute weekly/monthly every 5 days (expensive)
    weekly_ta = {}
    monthly_ta = {}
    last_tf_compute = -5

    for day in range(1, max_days + 1):
        idx = entry_idx + day
        if idx >= len(df):
            break

        row = df.iloc[idx]
        cur_p = row["Close"]
        highest = max(highest, cur_p)
        pnl_pct = ((cur_p - entry_p) / entry_p) * 100

        # 1. Catastrophe stop — always active
        if pnl_pct <= -30.0:
            return _build_trade(
                df, entry_idx, idx, ticker, quality, sector,
                day, highest, "CATASTROPHE_STOP", add_count,
            )

        # 2. Regime flip to BEAR — exit
        regime = classify_regime_from_ta(
            sma_50=row.get("sma_50"), sma_200=row.get("sma_200"),
            rsi_14=row.get("rsi_14"), volatility_20d=row.get("volatility_20d"),
        )
        if regime == MarketRegime.BEAR_RECESSION and day >= 20:
            # Regime flipped — but check weekly first
            if day - last_tf_compute >= 5:
                weekly_ta, monthly_ta = compute_weekly_monthly_at_index(df, idx)
                last_tf_compute = day

            if weekly_ta.get("macd_trend") == "BEARISH":
                return _build_trade(
                    df, entry_idx, idx, ticker, quality, sector,
                    day, highest, "REGIME_FLIP_CONFIRMED", add_count,
                )
            # Weekly still bullish → death cross may be temporary, hold

        # 3. Multi-timeframe sell check (every 5 days)
        if day >= 20 and day - last_tf_compute >= 5:
            weekly_ta, monthly_ta = compute_weekly_monthly_at_index(df, idx)
            last_tf_compute = day

            daily_ta = {
                "rsi_14": row.get("rsi_14"),
                "macd_trend": row.get("macd_trend"),
                "kdj_signal": row.get("kdj_signal"),
                "sma_50": row.get("sma_50"),
                "sma_200": row.get("sma_200"),
                "bb_pct_b": row.get("bb_pct_b"),
                "obv_trend": row.get("obv_trend"),
                "volume_ratio": row.get("volume_ratio"),
                "change_1d_pct": row.get("change_1d_pct"),
            }

            mtf = analyze_multi_tf(daily_ta, weekly_ta, monthly_ta, pnl_pct)

            if mtf.should_exit:
                exit_reason = f"MTF_{mtf.tf_agreement}"
                return _build_trade(
                    df, entry_idx, idx, ticker, quality, sector,
                    day, highest, exit_reason, add_count,
                )

        # 4. Track add opportunities
        if pnl_pct > 5.0:
            sell_count, _ = _count_ta_sell_signals(
                {"rsi_14": row.get("rsi_14"), "macd_trend": row.get("macd_trend"),
                 "obv_trend": row.get("obv_trend")}, pnl_pct)
            if sell_count == 0:
                add_count += 1

    # Max hold
    return _build_trade(
        df, entry_idx, min(entry_idx + max_days, len(df) - 1),
        ticker, quality, sector, max_days, highest, "MAX_HOLD", add_count,
    )


def simulate_fixed_hold(df, entry_idx, hold_days, ticker, quality, sector):
    """Baseline: fixed hold period."""
    exit_idx = entry_idx + hold_days
    if exit_idx >= len(df):
        return None
    return _build_trade(df, entry_idx, exit_idx, ticker, quality, sector,
                        hold_days, 0, "FIXED_HOLD", 0)


def _build_trade(df, entry_idx, exit_idx, ticker, quality, sector,
                 days, highest_override, reason, add_count):
    entry_p = df.iloc[entry_idx]["Close"]
    exit_p = df.iloc[exit_idx]["Close"]
    if entry_p <= 0:
        return None
    ret = ((exit_p - entry_p) / entry_p) * 100

    prices = df.iloc[entry_idx:exit_idx + 1]["Close"].values
    peak = prices[0]
    max_dd = 0.0
    max_gain = 0.0
    for p in prices:
        peak = max(peak, p)
        max_dd = max(max_dd, ((peak - p) / peak) * 100)
        gain = ((p - prices[0]) / prices[0]) * 100
        max_gain = max(max_gain, gain)

    return Trade(
        ticker=ticker, entry_date=str(df.index[entry_idx].date()),
        exit_date=str(df.index[exit_idx].date()),
        entry_price=round(entry_p, 2), exit_price=round(exit_p, 2),
        return_pct=round(ret, 4), days_held=days,
        max_gain_pct=round(max_gain, 2),
        max_drawdown_pct=round(max_dd, 2), exit_reason=reason,
        quality_tier=quality, sector=sector, add_count=add_count,
    )


def run_backtest(exchange: str, start_date: str, hold_days: int):
    log.info("Loading FA universe...")
    all_fund = load_fa_universe(exchange)
    log.info("Total tickers: %d", len(all_fund))

    # Only process quality stocks (A/B, profitable, growing, healthy)
    quality_tickers = {
        t: f for t, f in all_fund.items()
        if f.get("quality_tier") in ("A", "B")
        and f.get("is_profitable")
        and f.get("is_growing")
        and f.get("is_healthy")
    }
    log.info("Strict quality stocks: %d", len(quality_tickers))

    strategies = {
        "TA_ONLY (no FA)": [],        # baseline: any ticker, fixed hold
        "Quality+FixedHold": [],       # quality stocks, fixed hold
        "Quality+Regime+FixedHold": [],# quality + bull regime, fixed hold
        "Signal-Driven": [],           # hold until exit agent says sell
        "MultiTF-Driven": [],          # only exit when weekly confirms daily sell
    }

    processed = 0
    from scripts.backtest_signals import load_price_history

    for i, ticker in enumerate(all_fund.keys()):
        if i % 50 == 0 and i > 0:
            total = sum(len(v) for v in strategies.values())
            log.info("Progress: %d/%d tickers, %d trades", i, len(all_fund), total)

        df = load_price_history(ticker, exchange)
        if df is None or len(df) < 400:
            continue
        df = compute_all_indicators(df.copy())
        processed += 1

        fund = all_fund[ticker]
        quality = fund.get("quality_tier", "D")
        sector = fund.get("sector", "Unknown")
        is_quality = ticker in quality_tickers

        for j in range(252, len(df) - hold_days - 30):
            row = df.iloc[j]
            sig_m = compute_signal_months(row)
            sig_q = compute_signal_quarter(row)
            ta_buy = sig_m == "BUY" or sig_q == "BUY"
            if not ta_buy:
                continue

            regime = classify_regime_from_ta(
                sma_50=row.get("sma_50"), sma_200=row.get("sma_200"),
                rsi_14=row.get("rsi_14"), volatility_20d=row.get("volatility_20d"),
            )

            # Strategy 1: TA_ONLY baseline
            trade = simulate_fixed_hold(df, j, hold_days, ticker, quality, sector)
            if trade:
                strategies["TA_ONLY (no FA)"].append(trade)

            if not is_quality:
                continue

            # Strategy 2: Quality + fixed hold
            trade = simulate_fixed_hold(df, j, hold_days, ticker, quality, sector)
            if trade:
                strategies["Quality+FixedHold"].append(trade)

            # Strategy 3: Quality + bull regime + fixed hold
            if regime == MarketRegime.BULL_MOMENTUM:
                trade = simulate_fixed_hold(df, j, hold_days, ticker, quality, sector)
                if trade:
                    strategies["Quality+Regime+FixedHold"].append(trade)

            # Strategy 4: Signal-driven (exit agent)
            if regime == MarketRegime.BULL_MOMENTUM:
                trade = simulate_signal_driven_trade(
                    df, j, ticker, quality, sector,
                    max_days=hold_days, catastrophe_stop=-25.0,
                )
                if trade:
                    strategies["Signal-Driven"].append(trade)

            # Strategy 5: Multi-timeframe driven (weekly must confirm daily)
            if regime == MarketRegime.BULL_MOMENTUM:
                trade = simulate_multi_tf_trade(
                    df, j, ticker, quality, sector,
                    max_days=hold_days,
                )
                if trade:
                    strategies["MultiTF-Driven"].append(trade)

    # ═══════════════════════════════════════════════════════════════════════
    # Report
    # ═══════════════════════════════════════════════════════════════════════
    print()
    print("=" * 130)
    print(f"  SIGNAL-DRIVEN MULTI-AGENT BACKTEST — {exchange}")
    print(f"  Universe: {processed} tickers | Quality stocks: {len(quality_tickers)}")
    print(f"  Max hold: {hold_days}d | Since: {start_date}")
    print(f"  Rule: HOLD as long as agents say BUY/HOLD. SELL only when agents flip.")
    print("=" * 130)

    print(f"\n  {'Strategy':<28} {'Stks':>5} {'Trades':>7} {'Win':>6} "
          f"{'AvgRet':>8} {'MedRet':>8} {'P25':>8} {'P75':>8} {'PF':>6} "
          f"{'AvgDD':>7} {'AvgDays':>7} {'AnnRet':>8}")
    print("  " + "-" * 125)

    for name in strategies:
        trades = strategies[name]
        if not trades:
            print(f"  {name:<28} {'0':>5}")
            continue

        rets = np.array([t.return_pct for t in trades])
        dds = np.array([t.max_drawdown_pct for t in trades])
        durs = np.array([t.days_held for t in trades])
        unique_tickers = len(set(t.ticker for t in trades))

        win = np.mean(rets > 0) * 100
        gains = np.sum(rets[rets > 0]) if np.any(rets > 0) else 0
        losses = np.abs(np.sum(rets[rets < 0])) if np.any(rets < 0) else 0.001
        pf = gains / losses
        avg_dur = np.mean(durs)
        ann_ret = np.median(rets) * (252 / avg_dur) if avg_dur > 0 else 0

        print(f"  {name:<28} {unique_tickers:>5} {len(trades):>7,} {win:>5.1f}% "
              f"{np.mean(rets):>+7.2f}% {np.median(rets):>+7.2f}% "
              f"{np.percentile(rets, 25):>+7.1f}% {np.percentile(rets, 75):>+7.1f}% "
              f"{pf:>5.2f} {np.mean(dds):>6.1f}% "
              f"{avg_dur:>6.1f}d {ann_ret:>+7.1f}%")

    # Signal-Driven detail
    sd = strategies["Signal-Driven"]
    if sd:
        print(f"\n── Signal-Driven Exit Breakdown ──")
        exit_groups = defaultdict(list)
        for t in sd:
            exit_groups[t.exit_reason].append(t)
        for reason in ["TA_DOUBLE_SELL", "TA_SELL_SIGNAL", "REGIME_FLIP_BEAR",
                        "CATASTROPHE_STOP", "MAX_HOLD"]:
            trades = exit_groups.get(reason, [])
            if not trades:
                continue
            rets = np.array([t.return_pct for t in trades])
            durs = np.array([t.days_held for t in trades])
            wr = np.mean(rets > 0) * 100
            print(f"  {reason:<20}: {len(trades):>5} ({len(trades)/len(sd)*100:>5.1f}%), "
                  f"win {wr:>5.1f}%, avg {np.mean(rets):>+7.2f}%, med {np.median(rets):>+7.2f}%, "
                  f"avgDays {np.mean(durs):>5.0f}")

        # Add opportunities
        adds = [t for t in sd if t.add_count > 0]
        if adds:
            add_rets = np.array([t.return_pct for t in adds])
            print(f"\n  Trades with ADD opportunities: {len(adds)} ({len(adds)/len(sd)*100:.1f}%)")
            print(f"  These winners avg return: {np.mean(add_rets):+.2f}%, med: {np.median(add_rets):+.2f}%")

        # Top sector performance
        print(f"\n── Top Sectors (Signal-Driven) ──")
        sec_groups = defaultdict(list)
        for t in sd:
            sec_groups[t.sector].append(t.return_pct)
        for sector, rets in sorted(sec_groups.items(), key=lambda x: np.median(x[1]), reverse=True):
            arr = np.array(rets)
            if len(arr) < 5:
                continue
            print(f"  {sector:<30}: {len(arr):>4} trades, win {np.mean(arr>0)*100:>5.1f}%, "
                  f"avg {np.mean(arr):>+7.2f}%, med {np.median(arr):>+7.2f}%")

    # Final comparison
    ta = strategies["TA_ONLY (no FA)"]
    sd = strategies["Signal-Driven"]
    if ta and sd:
        ta_r = np.array([t.return_pct for t in ta])
        sd_r = np.array([t.return_pct for t in sd])
        print(f"\n{'═' * 70}")
        print(f"  $100K COMPARISON (annualized, since {start_date})")
        print(f"{'═' * 70}")
        ta_ann = np.median(ta_r) * (252 / np.mean([t.days_held for t in ta]))
        sd_ann = np.median(sd_r) * (252 / np.mean([t.days_held for t in sd]))
        print(f"  TA Only:       ${100000 * (1 + ta_ann/100):>10,.0f}  ({ta_ann:>+.1f}% annualized)")
        print(f"  Signal-Driven: ${100000 * (1 + sd_ann/100):>10,.0f}  ({sd_ann:>+.1f}% annualized)")
        print(f"  S&P 500 (est): ${145000:>10,}  (+45% since Jan 2023)")
        print(f"{'═' * 70}")

    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange", default="US")
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--hold", type=int, default=250, help="Max hold days (safety cap)")
    args = parser.parse_args()

    start = time.time()
    run_backtest(args.exchange, args.start, args.hold)
    log.info("Completed in %.1fs", time.time() - start)


if __name__ == "__main__":
    main()
