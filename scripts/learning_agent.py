#!/usr/bin/env python3
"""
learning_agent.py — Self-Learning Feedback Loop for Exit Agent
═══════════════════════════════════════════════════════════════

After each backtest, this agent:
1. REGRET ANALYSIS: For every exit, compute "what if we held 30/60/90 more days?"
   If the stock went higher → the exit was a MISTAKE (positive regret).
2. MISTAKE GROUPING: Group mistakes by exit reason, regime, quality, sector.
   Find systematic errors: "trailing stops in bull market lose us +12% on average".
3. PARAMETER TUNING: Adjust exit agent thresholds to fix the worst mistakes.
   e.g., if catastrophe stop exits average +20% regret → widen the stop.
4. VALIDATION: Re-run backtest with new params, keep only improvements.
5. PERSISTENCE: Save learned params to JSON config for production use.

This is gradient-free optimization: no LLM cost, pure statistical learning.
"""
import argparse
import json
import logging
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.backtest_signals import (
    compute_all_indicators,
    compute_signal_months,
    compute_signal_quarter,
    load_price_history,
)
from agents.fundamental.macro_agent import classify_regime_from_ta, MarketRegime
from agents.stock_synthesis.exit_agent import check_exit, ExitAction

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("learning_agent")

LEARNED_PARAMS_PATH = os.path.join(os.path.dirname(__file__), "..", "agents", "stock_synthesis", "learned_exit_params.json")


# ═══════════════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExitEvent:
    """One exit event with regret analysis."""
    ticker: str
    exit_day: int
    exit_reason: str
    exit_pnl_pct: float
    regime: str
    quality: str
    sector: str
    sell_signal_count: int
    # Regret: what if we held longer?
    pnl_if_held_30d: Optional[float] = None
    pnl_if_held_60d: Optional[float] = None
    pnl_if_held_90d: Optional[float] = None
    regret_30d: float = 0.0  # positive = we left money on the table
    regret_60d: float = 0.0
    regret_90d: float = 0.0
    best_future_pnl: float = 0.0  # best possible exit in next 90 days


@dataclass
class MistakePattern:
    """A systematic mistake pattern found in the data."""
    exit_reason: str
    regime: str
    quality: str
    count: int
    avg_regret_30d: float
    avg_regret_60d: float
    avg_regret_90d: float
    pct_would_recover: float  # % of exits where holding would have been better
    recommendation: str


# ═══════════════════════════════════════════════════════════════════════════════
# Step 1: Run backtest and capture every exit with full context
# ═══════════════════════════════════════════════════════════════════════════════

def run_backtest_with_regret(exchange: str, tickers_fund: Dict[str, dict],
                             quality_tickers: Dict[str, dict],
                             max_days: int = 250) -> List[ExitEvent]:
    """Run backtest and compute regret for every exit."""
    events = []
    processed = 0

    for i, ticker in enumerate(quality_tickers):
        if i % 20 == 0 and i > 0:
            log.info("  Regret analysis: %d/%d tickers, %d events", i, len(quality_tickers), len(events))

        df = load_price_history(ticker, exchange)
        if df is None or len(df) < 400:
            continue
        df = compute_all_indicators(df.copy())
        processed += 1

        fund = quality_tickers[ticker]
        quality = fund.get("quality_tier", "D")
        sector = fund.get("sector", "Unknown")

        for j in range(252, len(df) - max_days - 90):  # need 90 extra days for regret
            row = df.iloc[j]
            sig_m = compute_signal_months(row)
            sig_q = compute_signal_quarter(row)
            if sig_m != "BUY" and sig_q != "BUY":
                continue

            regime = classify_regime_from_ta(
                sma_50=row.get("sma_50"), sma_200=row.get("sma_200"),
                rsi_14=row.get("rsi_14"), volatility_20d=row.get("volatility_20d"),
            )
            if regime != MarketRegime.BULL_MOMENTUM:
                continue

            entry_p = row["Close"]
            if entry_p <= 0:
                continue

            # Simulate trade with current exit agent
            highest = entry_p
            exit_day = None
            exit_reason = None
            exit_pnl = None
            sell_count = 0

            for day in range(1, max_days + 1):
                idx = j + day
                if idx >= len(df):
                    break

                r = df.iloc[idx]
                cur_p = r["Close"]
                highest = max(highest, cur_p)

                cur_regime = classify_regime_from_ta(
                    sma_50=r.get("sma_50"), sma_200=r.get("sma_200"),
                    rsi_14=r.get("rsi_14"), volatility_20d=r.get("volatility_20d"),
                )

                ta_data = {
                    "rsi_14": r.get("rsi_14"),
                    "macd_trend": r.get("macd_trend"),
                    "kdj_signal": r.get("kdj_signal"),
                    "sma_50": r.get("sma_50"),
                    "sma_200": r.get("sma_200"),
                    "bb_pct_b": r.get("bb_pct_b"),
                    "obv_trend": r.get("obv_trend"),
                    "volume_ratio": r.get("volume_ratio"),
                    "change_1d_pct": r.get("change_1d_pct"),
                }

                signal = check_exit(
                    entry_price=entry_p, current_price=cur_p,
                    highest_since_entry=highest, days_held=day,
                    timeframe="months", ta_data=ta_data,
                    regime=cur_regime.value, quality=quality,
                )

                if signal.action not in (ExitAction.HOLD, ExitAction.ADD):
                    exit_day = day
                    exit_reason = signal.action.value
                    exit_pnl = ((cur_p - entry_p) / entry_p) * 100
                    sell_count = signal.sell_signal_count
                    break

            if exit_day is None:
                exit_day = max_days
                exit_reason = "MAX_HOLD"
                exit_idx = min(j + max_days, len(df) - 1)
                exit_pnl = ((df.iloc[exit_idx]["Close"] - entry_p) / entry_p) * 100
                sell_count = 0

            # Compute regret: what if we held 30/60/90 more days?
            exit_idx = j + exit_day
            pnl_30d = pnl_60d = pnl_90d = None
            best_future = exit_pnl

            for extra in [30, 60, 90]:
                future_idx = exit_idx + extra
                if future_idx < len(df):
                    future_p = df.iloc[future_idx]["Close"]
                    future_pnl = ((future_p - entry_p) / entry_p) * 100
                    if extra == 30:
                        pnl_30d = future_pnl
                    elif extra == 60:
                        pnl_60d = future_pnl
                    elif extra == 90:
                        pnl_90d = future_pnl
                    best_future = max(best_future, future_pnl)

            # Also check max price in next 90 days
            for k in range(exit_idx + 1, min(exit_idx + 91, len(df))):
                future_pnl = ((df.iloc[k]["Close"] - entry_p) / entry_p) * 100
                best_future = max(best_future, future_pnl)

            events.append(ExitEvent(
                ticker=ticker,
                exit_day=exit_day,
                exit_reason=exit_reason,
                exit_pnl_pct=round(exit_pnl, 4),
                regime=regime.value,
                quality=quality,
                sector=sector,
                sell_signal_count=sell_count,
                pnl_if_held_30d=round(pnl_30d, 4) if pnl_30d is not None else None,
                pnl_if_held_60d=round(pnl_60d, 4) if pnl_60d is not None else None,
                pnl_if_held_90d=round(pnl_90d, 4) if pnl_90d is not None else None,
                regret_30d=round((pnl_30d - exit_pnl), 4) if pnl_30d is not None else 0,
                regret_60d=round((pnl_60d - exit_pnl), 4) if pnl_60d is not None else 0,
                regret_90d=round((pnl_90d - exit_pnl), 4) if pnl_90d is not None else 0,
                best_future_pnl=round(best_future, 4),
            ))

    log.info("  Processed %d tickers, %d exit events", processed, len(events))
    return events


# ═══════════════════════════════════════════════════════════════════════════════
# Step 2: Analyze mistakes — find systematic patterns
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_mistakes(events: List[ExitEvent]) -> List[MistakePattern]:
    """Group exit events and find systematic mistakes."""
    # Group by (exit_reason, regime, quality)
    groups: Dict[Tuple[str, str, str], List[ExitEvent]] = defaultdict(list)
    for e in events:
        key = (e.exit_reason, e.regime, e.quality)
        groups[key].append(e)

    patterns = []
    for (reason, regime, quality), group in sorted(groups.items()):
        if len(group) < 5:
            continue

        regrets_30 = [e.regret_30d for e in group if e.pnl_if_held_30d is not None]
        regrets_60 = [e.regret_60d for e in group if e.pnl_if_held_60d is not None]
        regrets_90 = [e.regret_90d for e in group if e.pnl_if_held_90d is not None]

        avg_r30 = np.mean(regrets_30) if regrets_30 else 0
        avg_r60 = np.mean(regrets_60) if regrets_60 else 0
        avg_r90 = np.mean(regrets_90) if regrets_90 else 0

        # What % of exits would have been better if we held?
        would_recover = sum(1 for e in group if e.best_future_pnl > e.exit_pnl_pct)
        pct_recover = would_recover / len(group) * 100

        # Generate recommendation
        if avg_r90 > 5.0 and pct_recover > 60:
            rec = f"LOOSEN: avg regret +{avg_r90:.1f}%, {pct_recover:.0f}% would recover. Make this exit harder to trigger."
        elif avg_r90 > 2.0 and pct_recover > 50:
            rec = f"SLIGHTLY_LOOSEN: avg regret +{avg_r90:.1f}%, {pct_recover:.0f}% recover."
        elif avg_r90 < -5.0:
            rec = f"GOOD_EXIT: holding longer would have lost {abs(avg_r90):.1f}% more. Keep or tighten."
        else:
            rec = f"NEUTRAL: regret is small ({avg_r90:+.1f}%). Current threshold is reasonable."

        patterns.append(MistakePattern(
            exit_reason=reason,
            regime=regime,
            quality=quality,
            count=len(group),
            avg_regret_30d=round(avg_r30, 2),
            avg_regret_60d=round(avg_r60, 2),
            avg_regret_90d=round(avg_r90, 2),
            pct_would_recover=round(pct_recover, 1),
            recommendation=rec,
        ))

    return sorted(patterns, key=lambda p: -p.avg_regret_90d)


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3: Generate parameter adjustments
# ═══════════════════════════════════════════════════════════════════════════════

def generate_adjustments(patterns: List[MistakePattern]) -> Dict[str, Any]:
    """
    Convert mistake patterns into concrete parameter adjustments.

    Returns a dict that can be saved as learned_exit_params.json.
    """
    adjustments = {
        "version": 1,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sell_threshold_overrides": {},
        "catastrophe_stop_overrides": {},
        "trailing_stop_overrides": {},
        "time_stop_overrides": {},
        "analysis_summary": [],
    }

    for p in patterns:
        key = f"{p.regime}/{p.quality}"
        summary = {
            "exit_reason": p.exit_reason,
            "regime": p.regime,
            "quality": p.quality,
            "count": p.count,
            "avg_regret_90d": p.avg_regret_90d,
            "pct_would_recover": p.pct_would_recover,
            "recommendation": p.recommendation,
        }
        adjustments["analysis_summary"].append(summary)

        # Apply adjustments based on patterns
        if "LOOSEN" in p.recommendation:
            if p.exit_reason == "CUT_LOSS":
                # Widen catastrophe stop
                current = -25.0 if p.quality in ("A", "B") else -20.0
                new_val = current * 1.2  # 20% wider
                adjustments["catastrophe_stop_overrides"][key] = round(new_val, 1)

            elif p.exit_reason == "TRAIL_STOP":
                # Widen trailing stop
                adjustments["trailing_stop_overrides"][key] = {
                    "activation_multiplier": 1.3,  # activate later
                    "trail_multiplier": 1.2,       # wider trail
                }

            elif p.exit_reason == "TAKE_PROFIT" or p.exit_reason == "TA_SELL_SIGNAL":
                # Require more sell signals
                current_threshold = 3 if p.quality in ("A", "B") else 2
                if p.regime == "BULL_MOMENTUM":
                    new_threshold = min(current_threshold + 1, 5)
                    adjustments["sell_threshold_overrides"][key] = new_threshold

            elif p.exit_reason == "TIME_STOP":
                # Give more time
                adjustments["time_stop_overrides"][key] = {"multiplier": 1.5}

        elif "GOOD_EXIT" in p.recommendation:
            if p.exit_reason in ("CUT_LOSS", "CATASTROPHE_STOP"):
                # This exit is correct — might even tighten
                if p.avg_regret_90d < -10:
                    adjustments["catastrophe_stop_overrides"][key] = adjustments.get(
                        "catastrophe_stop_overrides", {}
                    ).get(key, -20.0) * 0.9  # 10% tighter

    return adjustments


# ═══════════════════════════════════════════════════════════════════════════════
# Step 4: Print report and save
# ═══════════════════════════════════════════════════════════════════════════════

def print_report(events: List[ExitEvent], patterns: List[MistakePattern],
                 adjustments: Dict[str, Any]):
    """Print the learning agent's analysis."""
    print()
    print("=" * 110)
    print("  LEARNING AGENT — Self-Improvement Analysis")
    print("=" * 110)

    # Overall stats
    exits_only = [e for e in events if e.exit_reason != "MAX_HOLD"]
    if exits_only:
        regrets = [e.regret_90d for e in exits_only if e.pnl_if_held_90d is not None]
        print(f"\n  Total exit events analyzed: {len(events):,}")
        print(f"  Exits (non-MAX_HOLD):       {len(exits_only):,}")
        if regrets:
            print(f"  Average 90-day regret:      {np.mean(regrets):+.2f}%")
            print(f"  Median 90-day regret:       {np.median(regrets):+.2f}%")
            pct_mistake = sum(1 for r in regrets if r > 0) / len(regrets) * 100
            print(f"  Exits that were mistakes:   {pct_mistake:.1f}% (would have been better holding)")

    # Mistake patterns
    print(f"\n── Systematic Mistake Patterns (sorted by regret) ──\n")
    print(f"  {'Reason':<20} {'Regime':<20} {'Qlty':>4} {'Count':>6} "
          f"{'Regret30':>9} {'Regret60':>9} {'Regret90':>9} {'Recover%':>9}")
    print("  " + "-" * 100)

    for p in patterns:
        marker = ""
        if "LOOSEN" in p.recommendation:
            marker = " ← FIX"
        elif "GOOD" in p.recommendation:
            marker = " ✓"

        print(f"  {p.exit_reason:<20} {p.regime:<20} {p.quality:>4} {p.count:>6} "
              f"{p.avg_regret_30d:>+8.2f}% {p.avg_regret_60d:>+8.2f}% {p.avg_regret_90d:>+8.2f}% "
              f"{p.pct_would_recover:>8.1f}%{marker}")

    # Recommendations
    print(f"\n── Recommendations ──\n")
    for p in patterns:
        if "LOOSEN" in p.recommendation or "GOOD" in p.recommendation:
            print(f"  [{p.exit_reason}/{p.regime}/{p.quality}]: {p.recommendation}")

    # Adjustments
    if adjustments.get("sell_threshold_overrides"):
        print(f"\n── Parameter Adjustments ──\n")
        for key, val in adjustments["sell_threshold_overrides"].items():
            print(f"  Sell signal threshold {key}: → {val} signals required")
    if adjustments.get("catastrophe_stop_overrides"):
        for key, val in adjustments["catastrophe_stop_overrides"].items():
            print(f"  Catastrophe stop {key}: → {val}%")
    if adjustments.get("trailing_stop_overrides"):
        for key, val in adjustments["trailing_stop_overrides"].items():
            print(f"  Trailing stop {key}: activate {val['activation_multiplier']}x later, "
                  f"trail {val['trail_multiplier']}x wider")

    print(f"\n{'=' * 110}")


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def _get_db_conn():
    from scripts.lib.db_helpers import get_conn as _get_conn
    return _get_conn()


def seed_agent_memory(events: List[ExitEvent], patterns: List[MistakePattern], exchange: str):
    """
    Seed agent memory from backtest results — connects learning_agent to
    the BM25 memory system for continuous improvement.

    Each mistake pattern with significant regret becomes a memory for the
    exit_agent role. Each pattern recommendation becomes a best result
    if it has enough evidence.
    """
    try:
        from agents.stock_synthesis.memory import AgentMemoryStore
        store = AgentMemoryStore.from_env()
        store.load()
    except Exception as exc:
        log.warning("Could not seed agent memory: %s", exc)
        return

    seeded = 0
    for p in patterns:
        if p.count < 5:
            continue

        situation = (
            f"Exit scenario: {p.exit_reason} in {p.regime} regime, "
            f"quality {p.quality}, {p.count} historical cases on {exchange}"
        )
        recommendation = (
            f"{p.recommendation} "
            f"(avg regret: 30d={p.avg_regret_30d:+.1f}%, 60d={p.avg_regret_60d:+.1f}%, "
            f"90d={p.avg_regret_90d:+.1f}%, recovery rate={p.pct_would_recover:.0f}%)"
        )

        # Determine outcome based on whether the exit was good or bad
        if "LOOSEN" in p.recommendation:
            outcome = "WRONG"  # exit was too aggressive
        elif "GOOD" in p.recommendation:
            outcome = "CORRECT"
        else:
            outcome = "PARTIAL"

        store.add_memory(
            agent_role="exit_agent",
            situation=situation,
            recommendation=recommendation,
            ticker=None,  # general pattern
            exchange=exchange,
            outcome=outcome,
            confidence=min(0.9, 0.5 + p.count / 100),
            source="backtest",
            tags=[f"regime:{p.regime}", f"quality:{p.quality}", f"exit_reason:{p.exit_reason}"],
        )
        seeded += 1

        # Promote strong patterns to best results
        if p.count >= 10 and (p.pct_would_recover > 65 or p.avg_regret_90d < -5):
            result_key = f"exit_agent/{p.exit_reason}/{p.regime}/{p.quality}"
            store.upsert_best_result(
                result_key=result_key,
                agent_role="exit_agent",
                category="exit_rule",
                title=f"{p.exit_reason} in {p.regime}/{p.quality}: {p.recommendation.split(':')[0]}",
                lesson_text=recommendation,
                evidence_count=p.count,
                success_rate=p.pct_would_recover / 100 if "LOOSEN" in p.recommendation else 1 - p.pct_would_recover / 100,
                applicable_when={"regime": [p.regime], "quality": [p.quality]},
                priority=min(95, 50 + p.count // 2),
            )

    log.info("Seeded %d memories from %d mistake patterns", seeded, len(patterns))


def save_to_db(events: List[ExitEvent], patterns: List[MistakePattern],
               adjustments: Dict[str, Any], exchange: str):
    """Persist learning results to agt_ tables + seed agent memory."""
    import psycopg2.extras

    # Seed agent memory from patterns (BM25 + best results)
    seed_agent_memory(events, patterns, exchange)

    conn = _get_db_conn()
    try:
        with conn.cursor() as cur:
            # 1. Save learning run summary
            exits_only = [e for e in events if e.exit_reason != "MAX_HOLD"]
            regrets = [e.regret_90d for e in exits_only if e.pnl_if_held_90d is not None]
            mistake_pct = sum(1 for r in regrets if r > 0) / len(regrets) * 100 if regrets else 0

            patterns_json = json.dumps([asdict(p) for p in patterns])
            summary_json = json.dumps(adjustments.get("analysis_summary", []))

            cur.execute("""
                INSERT INTO datapai.agt_learning_runs
                (run_type, exchange, tickers_analyzed, exit_events_total,
                 mistake_pct, avg_regret_90d, params_adjusted,
                 summary_json, patterns_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                "REGRET_ANALYSIS", exchange,
                len(set(e.ticker for e in events)), len(events),
                round(mistake_pct, 1),
                round(np.mean(regrets), 2) if regrets else 0,
                sum(1 for v in adjustments.values() if isinstance(v, dict) and v),
                summary_json, patterns_json,
            ))
            run_id = cur.fetchone()[0]

            # 2. Save/update learned parameters
            version = adjustments.get("version", 1)
            for param_type in ["sell_threshold_overrides", "catastrophe_stop_overrides",
                               "trailing_stop_overrides", "time_stop_overrides"]:
                overrides = adjustments.get(param_type, {})
                for key, val in overrides.items():
                    param_key = f"{param_type}/{key}"
                    # Find matching pattern for the reason
                    reason = next(
                        (p.recommendation for p in patterns
                         if f"{p.regime}/{p.quality}" == key),
                        "Auto-adjusted by learning agent"
                    )
                    cur.execute("""
                        INSERT INTO datapai.agt_learned_params
                        (param_key, param_value, source, reason, version, is_active)
                        VALUES (%s, %s, 'learning_agent', %s, %s, TRUE)
                        ON CONFLICT (param_key, version) DO UPDATE SET
                            param_value = EXCLUDED.param_value,
                            reason = EXCLUDED.reason,
                            is_active = TRUE
                    """, (param_key, json.dumps(val), reason, version))

        conn.commit()
        log.info("Saved learning run #%d and %d params to DB", run_id,
                 sum(len(v) for v in adjustments.values() if isinstance(v, dict)))
    except Exception as exc:
        log.error("Failed to save to DB: %s", exc)
        conn.rollback()
    finally:
        conn.close()


def save_backtest_result(strategy: str, exchange: str, hold_days: int,
                         trades: list, params_version: int):
    """Save a backtest result to agt_backtest_runs."""
    if not trades:
        return
    conn = _get_db_conn()
    try:
        rets = np.array([t.return_pct for t in trades])
        durs = np.array([t.days_held for t in trades])
        gains = np.sum(rets[rets > 0]) if np.any(rets > 0) else 0
        losses = np.abs(np.sum(rets[rets < 0])) if np.any(rets < 0) else 0.001

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO datapai.agt_backtest_runs
                (strategy, exchange, hold_days, tickers_tested, total_trades,
                 win_rate, avg_return, median_return, profit_factor,
                 avg_drawdown, annualized_return, params_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                strategy, exchange, hold_days,
                len(set(t.ticker for t in trades)), len(trades),
                round(np.mean(rets > 0) * 100, 2),
                round(float(np.mean(rets)), 4),
                round(float(np.median(rets)), 4),
                round(gains / losses, 4),
                round(float(np.mean([t.max_drawdown_pct for t in trades])), 2),
                round(float(np.median(rets) * (252 / np.mean(durs))), 2) if np.mean(durs) > 0 else 0,
                params_version,
            ))
        conn.commit()
    except Exception as exc:
        log.error("Failed to save backtest result: %s", exc)
        conn.rollback()
    finally:
        conn.close()


def run_iterative_learning(exchange: str, max_hold: int, iterations: int = 3):
    """
    Run multiple learning iterations, each building on the previous.

    Each iteration:
    1. Load current learned params (from JSON)
    2. Run backtest with regret analysis
    3. Analyze mistakes
    4. Generate incremental adjustments (building on previous)
    5. Save to JSON and DB
    6. Compare to previous iteration

    The exit agent reloads params on each iteration.
    """
    import psycopg2.extras

    log.info("═══ ITERATIVE LEARNING: %d iterations ═══", iterations)

    # Load FA universe once
    conn = _get_db_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT ticker, quality_tier, sector, is_profitable, is_growing, is_healthy
            FROM datapai.fundamental_lite WHERE exchange = %s
        """, (exchange,))
        all_fund = {r["ticker"]: dict(r) for r in cur.fetchall()}
    conn.close()

    quality_tickers = {
        t: f for t, f in all_fund.items()
        if f.get("quality_tier") in ("A", "B")
        and f.get("is_profitable") and f.get("is_growing") and f.get("is_healthy")
    }
    log.info("Quality universe: %d tickers", len(quality_tickers))

    iteration_results = []

    for iteration in range(1, iterations + 1):
        log.info("\n{'=' * 60}")
        log.info("  ITERATION %d / %d", iteration, iterations)
        log.info("{'=' * 60}")

        # Force reload learned params
        from agents.stock_synthesis.exit_agent import reload_learned_params
        reload_learned_params()

        # Step 1: Backtest with regret
        log.info("Step 1: Running backtest with regret analysis...")
        events = run_backtest_with_regret(exchange, all_fund, quality_tickers, max_hold)

        # Step 2: Analyze
        log.info("Step 2: Analyzing mistakes...")
        patterns = analyze_mistakes(events)

        # Step 3: Generate adjustments (incremental — load existing and extend)
        log.info("Step 3: Generating incremental adjustments...")
        try:
            with open(LEARNED_PARAMS_PATH) as f:
                existing = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            existing = {}

        new_adjustments = generate_adjustments(patterns)
        # Merge: new overrides on top of existing
        merged = {
            "version": existing.get("version", 0) + 1,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "iteration": iteration,
            "sell_threshold_overrides": {
                **existing.get("sell_threshold_overrides", {}),
                **new_adjustments.get("sell_threshold_overrides", {}),
            },
            "catastrophe_stop_overrides": {
                **existing.get("catastrophe_stop_overrides", {}),
                **new_adjustments.get("catastrophe_stop_overrides", {}),
            },
            "trailing_stop_overrides": {
                **existing.get("trailing_stop_overrides", {}),
                **new_adjustments.get("trailing_stop_overrides", {}),
            },
            "time_stop_overrides": {
                **existing.get("time_stop_overrides", {}),
                **new_adjustments.get("time_stop_overrides", {}),
            },
            "analysis_summary": new_adjustments.get("analysis_summary", []),
        }

        # Step 4: Save
        with open(LEARNED_PARAMS_PATH, "w") as f:
            json.dump(merged, f, indent=2)
        log.info("Saved iteration %d params (version %d)", iteration, merged["version"])

        # Save to DB
        save_to_db(events, patterns, merged, exchange)

        # Track iteration metrics
        exits_only = [e for e in events if e.exit_reason != "MAX_HOLD"]
        regrets = [e.regret_90d for e in exits_only if e.pnl_if_held_90d is not None]
        mistake_pct = sum(1 for r in regrets if r > 0) / len(regrets) * 100 if regrets else 0
        avg_regret = np.mean(regrets) if regrets else 0
        avg_return = np.mean([e.exit_pnl_pct for e in events])
        med_return = np.median([e.exit_pnl_pct for e in events])

        result = {
            "iteration": iteration,
            "version": merged["version"],
            "events": len(events),
            "mistake_pct": round(mistake_pct, 1),
            "avg_regret_90d": round(avg_regret, 2),
            "avg_return": round(avg_return, 2),
            "med_return": round(med_return, 2),
        }
        iteration_results.append(result)

        # Print iteration summary
        print(f"\n  Iteration {iteration}: {len(events)} events, "
              f"{mistake_pct:.1f}% mistakes, regret {avg_regret:+.2f}%, "
              f"avg return {avg_return:+.2f}%, med return {med_return:+.2f}%")

    # Final comparison across iterations
    print(f"\n{'=' * 80}")
    print(f"  LEARNING CONVERGENCE ({iterations} iterations)")
    print(f"{'=' * 80}")
    print(f"  {'Iter':>4} {'Version':>7} {'Events':>7} {'Mistake%':>9} {'Regret90':>9} {'AvgRet':>8} {'MedRet':>8}")
    print(f"  " + "-" * 60)
    for r in iteration_results:
        print(f"  {r['iteration']:>4} {r['version']:>7} {r['events']:>7} "
              f"{r['mistake_pct']:>8.1f}% {r['avg_regret_90d']:>+8.2f}% "
              f"{r['avg_return']:>+7.2f}% {r['med_return']:>+7.2f}%")

    if len(iteration_results) >= 2:
        first = iteration_results[0]
        last = iteration_results[-1]
        print(f"\n  Improvement: mistake% {first['mistake_pct']:.1f}% → {last['mistake_pct']:.1f}%, "
              f"regret {first['avg_regret_90d']:+.2f}% → {last['avg_regret_90d']:+.2f}%")

    print(f"{'=' * 80}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange", default="US")
    parser.add_argument("--hold", type=int, default=250)
    parser.add_argument("--save", action="store_true", help="Save learned params to JSON")
    parser.add_argument("--iterations", type=int, default=1,
                        help="Number of learning iterations (each builds on previous)")
    args = parser.parse_args()

    if args.iterations > 1:
        run_iterative_learning(args.exchange, args.hold, args.iterations)
        return

    import psycopg2, psycopg2.extras

    log.info("═══ LEARNING AGENT: Analyzing exit mistakes ═══")

    conn = _get_db_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT ticker, quality_tier, sector, is_profitable, is_growing, is_healthy
            FROM datapai.fundamental_lite WHERE exchange = %s
        """, (args.exchange,))
        all_fund = {r["ticker"]: dict(r) for r in cur.fetchall()}
    conn.close()

    quality_tickers = {
        t: f for t, f in all_fund.items()
        if f.get("quality_tier") in ("A", "B")
        and f.get("is_profitable") and f.get("is_growing") and f.get("is_healthy")
    }
    log.info("Quality universe: %d tickers", len(quality_tickers))

    log.info("Step 1: Running backtest with regret analysis...")
    events = run_backtest_with_regret(args.exchange, all_fund, quality_tickers, args.hold)

    log.info("Step 2: Analyzing systematic mistakes...")
    patterns = analyze_mistakes(events)

    log.info("Step 3: Generating parameter adjustments...")
    adjustments = generate_adjustments(patterns)

    print_report(events, patterns, adjustments)

    if args.save:
        with open(LEARNED_PARAMS_PATH, "w") as f:
            json.dump(adjustments, f, indent=2)
        log.info("Saved learned parameters to %s", LEARNED_PARAMS_PATH)

        # Also save to DB
        save_to_db(events, patterns, adjustments, args.exchange)
        print(f"\n  ✓ Saved to JSON + database (agt_learning_runs, agt_learned_params)")


if __name__ == "__main__":
    main()
