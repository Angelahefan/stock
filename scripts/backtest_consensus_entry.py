#!/usr/bin/env python3
"""
backtest_consensus_entry.py — Multi-Agent Consensus Entry Backtest
═══════════════════════════════════════════════════════════════════

The REAL test: only buy when MULTIPLE agents agree.

Strategies compared:
  1. TA_ONLY:       BUY when TA signal fires (current baseline)
  2. TA+QUALITY:    BUY when TA fires AND fundamental quality_tier = A or B
  3. TA+GROWTH:     BUY when TA fires AND is_growing=True AND is_profitable=True
  4. CONSENSUS:     BUY when TA fires AND quality A/B AND growing AND regime=BULL
  5. CONSENSUS+EXIT: Same as CONSENSUS but with Exit Agent managing the trade

This tests whether multi-agent consensus entry produces better returns.
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
    load_tickers,
)
from agents.fundamental.macro_agent import classify_regime_from_ta, MarketRegime
from agents.stock_synthesis.risk_agent import assess_risk_from_row
from agents.stock_synthesis.exit_agent import check_exit, ExitAction

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("consensus_backtest")


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


def get_db_conn():
    return psycopg2.connect(
        host=os.getenv("DATAPAI_PG_HOST", "localhost"),
        port=int(os.getenv("DATAPAI_PG_PORT", "5432")),
        dbname=os.getenv("DATAPAI_PG_DB", "postgres"),
        user=os.getenv("DATAPAI_PG_USER", "postgres"),
        password=os.getenv("DATAPAI_PG_PASSWORD", "postgres"),
    )


def load_fundamentals(exchange: str) -> Dict[str, dict]:
    """Load fundamental data keyed by ticker."""
    conn = get_db_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT ticker, quality_tier, sector, industry,
                   pe_ratio, forward_pe, roe, revenue_yoy, earnings_yoy,
                   is_profitable, is_growing, is_healthy,
                   market_cap, debt_to_equity, gross_margin, operating_margin
            FROM datapai.fundamental_lite
            WHERE exchange = %s
        """, (exchange,))
        data = {r["ticker"]: dict(r) for r in cur.fetchall()}
    conn.close()
    return data


def simulate_hold_trade(df, entry_idx, hold_days, ticker, regime, quality_tier, sector):
    """Fixed hold period trade."""
    exit_idx = entry_idx + hold_days
    if exit_idx >= len(df):
        return None
    entry_p = df.iloc[entry_idx]["Close"]
    exit_p = df.iloc[exit_idx]["Close"]
    if entry_p <= 0:
        return None

    prices = df.iloc[entry_idx:exit_idx + 1]["Close"].values
    peak = prices[0]
    max_dd = 0.0
    for p in prices:
        peak = max(peak, p)
        dd = ((peak - p) / peak) * 100
        max_dd = max(max_dd, dd)

    ret = ((exit_p - entry_p) / entry_p) * 100
    return Trade(
        ticker=ticker,
        entry_date=str(df.index[entry_idx].date()),
        exit_date=str(df.index[exit_idx].date()),
        entry_price=round(entry_p, 2),
        exit_price=round(exit_p, 2),
        return_pct=round(ret, 4),
        days_held=hold_days,
        max_drawdown_pct=round(max_dd, 2),
        exit_reason="FIXED_HOLD",
        regime=regime,
        quality_tier=quality_tier,
        sector=sector,
    )


def simulate_managed_trade(df, entry_idx, ticker, regime, quality_tier, sector, max_days=120):
    """Exit Agent managed trade."""
    entry_p = df.iloc[entry_idx]["Close"]
    if entry_p <= 0:
        return None

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
            entry_price=entry_p,
            current_price=cur_p,
            highest_since_entry=highest,
            days_held=day,
            timeframe="months",
            ta_data=ta_data,
        )

        if sig.action != ExitAction.HOLD:
            prices = df.iloc[entry_idx:idx + 1]["Close"].values
            peak = prices[0]
            max_dd = 0.0
            for p in prices:
                peak = max(peak, p)
                dd = ((peak - p) / peak) * 100
                max_dd = max(max_dd, dd)

            ret = ((cur_p - entry_p) / entry_p) * 100
            return Trade(
                ticker=ticker, entry_date=str(df.index[entry_idx].date()),
                exit_date=str(df.index[idx].date()),
                entry_price=round(entry_p, 2), exit_price=round(cur_p, 2),
                return_pct=round(ret, 4), days_held=day,
                max_drawdown_pct=round(max_dd, 2),
                exit_reason=sig.action.value,
                regime=regime, quality_tier=quality_tier, sector=sector,
            )

    # Max hold reached
    exit_idx = min(entry_idx + max_days, len(df) - 1)
    exit_p = df.iloc[exit_idx]["Close"]
    ret = ((exit_p - entry_p) / entry_p) * 100
    prices = df.iloc[entry_idx:exit_idx + 1]["Close"].values
    peak = prices[0]
    max_dd = 0.0
    for p in prices:
        peak = max(peak, p)
        dd = ((peak - p) / peak) * 100
        max_dd = max(max_dd, dd)
    return Trade(
        ticker=ticker, entry_date=str(df.index[entry_idx].date()),
        exit_date=str(df.index[exit_idx].date()),
        entry_price=round(entry_p, 2), exit_price=round(exit_p, 2),
        return_pct=round(ret, 4), days_held=max_days,
        max_drawdown_pct=round(max_dd, 2), exit_reason="MAX_HOLD",
        regime=regime, quality_tier=quality_tier, sector=sector,
    )


def run_backtest(exchange: str, sample: int, start_date: str, hold_days: int):
    log.info("Loading fundamentals...")
    fundamentals = load_fundamentals(exchange)
    log.info("Loaded fundamentals for %d tickers", len(fundamentals))

    tickers = load_tickers(exchange, sample)
    # Filter to only tickers with fundamental data
    tickers_with_fund = [t for t in tickers if t in fundamentals]
    log.info("Tickers with fundamentals: %d / %d", len(tickers_with_fund), len(tickers))

    strategies = {
        "TA_ONLY": [],
        "TA+QUALITY": [],
        "TA+GROWTH": [],
        "CONSENSUS": [],
        "CONSENSUS+EXIT": [],
    }

    processed = 0
    for i, ticker in enumerate(tickers_with_fund):
        if i % 50 == 0 and i > 0:
            total = sum(len(v) for v in strategies.values())
            log.info("Progress: %d/%d tickers, %d total trades", i, len(tickers_with_fund), total)

        df = load_price_history(ticker, exchange)
        if df is None or len(df) < 400:
            continue
        df = compute_all_indicators(df.copy())
        processed += 1

        fund = fundamentals[ticker]
        quality = fund.get("quality_tier", "D")
        sector = fund.get("sector", "Unknown")
        is_growing = fund.get("is_growing", False)
        is_profitable = fund.get("is_profitable", False)
        is_healthy = fund.get("is_healthy", False)

        for j in range(252, len(df) - hold_days - 60):
            row = df.iloc[j]

            # Check TA signal (months + quarter)
            sig_m = compute_signal_months(row)
            sig_q = compute_signal_quarter(row)
            ta_buy = sig_m == "BUY" or sig_q == "BUY"
            if not ta_buy:
                continue

            # Compute regime
            regime = classify_regime_from_ta(
                sma_50=row.get("sma_50"),
                sma_200=row.get("sma_200"),
                rsi_14=row.get("rsi_14"),
                volatility_20d=row.get("volatility_20d"),
            )

            # Strategy 1: TA_ONLY — any TA buy signal
            trade = simulate_hold_trade(df, j, hold_days, ticker, regime.value, quality, sector)
            if trade:
                strategies["TA_ONLY"].append(trade)

            # Strategy 2: TA + Quality tier A or B
            if quality in ("A", "B"):
                trade = simulate_hold_trade(df, j, hold_days, ticker, regime.value, quality, sector)
                if trade:
                    strategies["TA+QUALITY"].append(trade)

            # Strategy 3: TA + Growing + Profitable
            if is_growing and is_profitable:
                trade = simulate_hold_trade(df, j, hold_days, ticker, regime.value, quality, sector)
                if trade:
                    strategies["TA+GROWTH"].append(trade)

            # Strategy 4: CONSENSUS — TA + Quality + Growing + Bull regime
            if quality in ("A", "B") and is_growing and is_profitable and regime == MarketRegime.BULL_MOMENTUM:
                trade = simulate_hold_trade(df, j, hold_days, ticker, regime.value, quality, sector)
                if trade:
                    strategies["CONSENSUS"].append(trade)

            # Strategy 5: CONSENSUS + Exit Agent
            if quality in ("A", "B") and is_growing and is_profitable and regime == MarketRegime.BULL_MOMENTUM:
                trade = simulate_managed_trade(df, j, ticker, regime.value, quality, sector, max_days=hold_days)
                if trade:
                    strategies["CONSENSUS+EXIT"].append(trade)

    # Print results
    print()
    print("=" * 110)
    print(f"  MULTI-AGENT CONSENSUS ENTRY BACKTEST — {exchange} ({processed} tickers, hold={hold_days}d)")
    print("=" * 110)

    print(f"\n  {'Strategy':<18} {'Trades':>7} {'Win':>6} {'AvgRet':>8} {'MedRet':>8} "
          f"{'P25':>8} {'P75':>8} {'PF':>6} {'AvgDD':>7} {'AnnAvg':>8} {'AnnMed':>8}")
    print("  " + "-" * 105)

    for name in ["TA_ONLY", "TA+QUALITY", "TA+GROWTH", "CONSENSUS", "CONSENSUS+EXIT"]:
        trades = strategies[name]
        if not trades:
            print(f"  {name:<18} {'0':>7}")
            continue

        rets = np.array([t.return_pct for t in trades])
        dds = np.array([t.max_drawdown_pct for t in trades])
        durations = np.array([t.days_held for t in trades])
        win = np.mean(rets > 0) * 100
        gains = np.sum(rets[rets > 0]) if np.any(rets > 0) else 0
        losses = np.abs(np.sum(rets[rets < 0])) if np.any(rets < 0) else 0.001
        pf = gains / losses if losses > 0 else 99.99
        avg_dur = np.mean(durations)
        ann_avg = np.mean(rets) * (252 / avg_dur) if avg_dur > 0 else 0
        ann_med = np.median(rets) * (252 / avg_dur) if avg_dur > 0 else 0

        mark = ""
        if name == "CONSENSUS+EXIT":
            baseline_med = np.median([t.return_pct for t in strategies["TA_ONLY"]]) if strategies["TA_ONLY"] else 0
            if np.median(rets) > baseline_med * 2:
                mark = " ★★"
            elif np.median(rets) > baseline_med * 1.3:
                mark = " ★"

        print(f"  {name:<18} {len(trades):>7,} {win:>5.1f}% {np.mean(rets):>+7.2f}% {np.median(rets):>+7.2f}% "
              f"{np.percentile(rets, 25):>+7.1f}% {np.percentile(rets, 75):>+7.1f}% "
              f"{pf:>5.2f} {np.mean(dds):>6.1f}% "
              f"{ann_avg:>+7.1f}% {ann_med:>+7.1f}%{mark}")

    # Quality tier breakdown for CONSENSUS
    consensus_trades = strategies["CONSENSUS"]
    if consensus_trades:
        print(f"\n── Quality Tier Breakdown (CONSENSUS) ──")
        tier_groups = defaultdict(list)
        for t in consensus_trades:
            tier_groups[t.quality_tier].append(t.return_pct)
        for tier in sorted(tier_groups.keys()):
            arr = np.array(tier_groups[tier])
            wr = np.mean(arr > 0) * 100
            print(f"  Tier {tier}: {len(arr):>5,} trades, win {wr:>5.1f}%, "
                  f"avg {np.mean(arr):>+6.2f}%, med {np.median(arr):>+6.2f}%")

    # Sector breakdown for CONSENSUS
    if consensus_trades:
        print(f"\n── Top Sectors (CONSENSUS, by median return) ──")
        sector_groups = defaultdict(list)
        for t in consensus_trades:
            sector_groups[t.sector].append(t.return_pct)
        sorted_sectors = sorted(sector_groups.items(), key=lambda x: np.median(x[1]), reverse=True)
        for sector, rets in sorted_sectors[:10]:
            arr = np.array(rets)
            if len(arr) < 5:
                continue
            wr = np.mean(arr > 0) * 100
            print(f"  {sector:<30}: {len(arr):>4,} trades, win {wr:>5.1f}%, "
                  f"avg {np.mean(arr):>+7.2f}%, med {np.median(arr):>+7.2f}%")

    # Exit breakdown for CONSENSUS+EXIT
    exit_trades = strategies["CONSENSUS+EXIT"]
    if exit_trades:
        print(f"\n── Exit Breakdown (CONSENSUS+EXIT) ──")
        exit_counts = defaultdict(list)
        for t in exit_trades:
            exit_counts[t.exit_reason].append(t.return_pct)
        for reason, rets in sorted(exit_counts.items(), key=lambda x: -len(x[1])):
            arr = np.array(rets)
            wr = np.mean(arr > 0) * 100
            print(f"  {reason:<15}: {len(arr):>5,} ({len(arr)/len(exit_trades)*100:>5.1f}%), "
                  f"win {wr:>5.1f}%, avg {np.mean(arr):>+6.2f}%, med {np.median(arr):>+6.2f}%")

    print()
    print("=" * 110)
    print("  AnnAvg/AnnMed = annualized returns based on avg trade duration")
    print("  PF = Profit Factor (total gains / total losses). >1.5 = good, >2.0 = excellent")
    print("  ★ = median return >1.3x baseline, ★★ = >2x baseline")
    print("=" * 110)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange", default="US")
    parser.add_argument("--sample", type=int, default=300)
    parser.add_argument("--start", type=str, default="2023-06-01")
    parser.add_argument("--hold", type=int, default=90, help="Hold period in trading days")
    args = parser.parse_args()

    start = time.time()
    run_backtest(args.exchange, args.sample, args.start, args.hold)
    log.info("Completed in %.1fs", time.time() - start)


if __name__ == "__main__":
    main()
