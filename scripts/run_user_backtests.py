#!/usr/bin/env python3
"""
scripts/run_user_backtests.py
─────────────────────────────────────────────────────────────────────────────
Nightly backtest runner for Personalized Agent Studio.

Picks up strategies with backtest_status='pending' (or updated_at > last_backtest_at),
runs a vectorised backtest using TA indicator data from datapai.ta_indicators,
and stores results in datapai.usr_backtest_results.

Usage:
    python3 scripts/run_user_backtests.py
    python3 scripts/run_user_backtests.py --strategy-id 42   # single strategy
    python3 scripts/run_user_backtests.py --max 50           # limit batch size
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib.db_helpers import get_conn
from scripts.lib.log_setup import setup_logging

logger = setup_logging("user_backtests")

# ── Constants ────────────────────────────────────────────────────────────────

MAX_STRATEGIES_PER_RUN = 50
STRATEGY_TIMEOUT_SECONDS = 300  # 5 min per strategy
DEFAULT_COMMISSION_PCT = 0.1
DEFAULT_INITIAL_CAPITAL = 100000
BENCHMARK_TICKER = "^GSPC"  # S&P 500


# ── Condition evaluators ─────────────────────────────────────────────────────

def _eval_condition(row: pd.Series, prev_row: pd.Series | None, rule: dict) -> bool:
    """Evaluate a single entry/exit rule condition against a TA indicator row."""
    indicator = rule.get("indicator", "")
    condition = rule.get("condition", "")
    value = rule.get("value")

    # Map indicator names to column names
    col_map = {
        "rsi_14": "rsi",
        "rsi": "rsi",
        "macd_signal": "macd_hist",
        "macd_hist": "macd_hist",
        "macd_line": "macd_line",
        "sma_50": "ema_50",    # we use EMA as proxy (available in DB)
        "sma_200": "ema_200",
        "ema_9": "ema_9",
        "ema_20": "ema_20",
        "ema_50": "ema_50",
        "ema_200": "ema_200",
        "bb_upper": "bb_upper",
        "bb_lower": "bb_lower",
        "bb_middle": "bb_middle",
        "bb_pct": "bb_pct",
        "stoch_k": "stoch_k",
        "stoch_d": "stoch_d",
        "atr": "atr",
        "adx": "adx",
        "volume": "volume",
        "vol_ratio_5": "vol_ratio_5",
        "vol_ratio_10": "vol_ratio_10",
        "close": "close",
        "price": "close",
    }

    col = col_map.get(indicator, indicator)
    val = row.get(col)
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return False

    # Special conditions
    if condition == "crossover_up":
        if prev_row is None:
            return False
        if indicator in ("macd_signal", "macd_hist"):
            prev_val = prev_row.get("macd_hist")
            return prev_val is not None and not np.isnan(prev_val) and prev_val <= 0 and val > 0
        return False

    if condition == "crossover_down":
        if prev_row is None:
            return False
        if indicator in ("macd_signal", "macd_hist"):
            prev_val = prev_row.get("macd_hist")
            return prev_val is not None and not np.isnan(prev_val) and prev_val >= 0 and val < 0
        return False

    if condition == "golden_cross":
        ema50 = row.get("ema_50")
        ema200 = row.get("ema_200")
        if ema50 is None or ema200 is None:
            return False
        if prev_row is None:
            return False
        prev50 = prev_row.get("ema_50")
        prev200 = prev_row.get("ema_200")
        if prev50 is None or prev200 is None:
            return False
        return prev50 <= prev200 and ema50 > ema200

    if condition == "death_cross":
        ema50 = row.get("ema_50")
        ema200 = row.get("ema_200")
        if ema50 is None or ema200 is None:
            return False
        if prev_row is None:
            return False
        prev50 = prev_row.get("ema_50")
        prev200 = prev_row.get("ema_200")
        if prev50 is None or prev200 is None:
            return False
        return prev50 >= prev200 and ema50 < ema200

    # Simple comparisons
    if value is None:
        return False

    try:
        value = float(value)
    except (TypeError, ValueError):
        return False

    if condition == "above":
        return val > value
    elif condition == "below":
        return val < value
    elif condition == "equals":
        return abs(val - value) < 0.001
    elif condition == "crosses_above":
        if prev_row is None:
            return False
        prev_val = prev_row.get(col)
        if prev_val is None or np.isnan(prev_val):
            return False
        return prev_val <= value and val > value
    elif condition == "crosses_below":
        if prev_row is None:
            return False
        prev_val = prev_row.get(col)
        if prev_val is None or np.isnan(prev_val):
            return False
        return prev_val >= value and val < value

    return False


def check_entry(row: pd.Series, prev_row: pd.Series | None, entry_rules: list[dict]) -> bool:
    """All entry rules must be satisfied (AND logic)."""
    if not entry_rules:
        return False
    return all(_eval_condition(row, prev_row, r) for r in entry_rules)


def check_exit(row: pd.Series, prev_row: pd.Series | None, exit_rules: list[dict],
               entry_price: float) -> tuple[bool, str]:
    """Check exit conditions. Returns (should_exit, reason)."""
    close = row.get("close", 0)

    for rule in exit_rules:
        indicator = rule.get("indicator", "")

        # Stop loss
        if indicator == "stop_loss_pct":
            pct = float(rule.get("value", 5))
            if entry_price > 0 and ((close - entry_price) / entry_price) * 100 <= -pct:
                return True, f"Stop loss ({pct}%)"

        # Trailing stop (simplified: uses high watermark from entry)
        elif indicator == "trailing_stop_pct":
            # Simplified trailing stop — checked via running max
            pass  # handled in the simulation loop

        # Indicator-based exits
        else:
            if _eval_condition(row, prev_row, rule):
                return True, f"{indicator} {rule.get('condition', '')} {rule.get('value', '')}"

    return False, ""


# ── Data loading ─────────────────────────────────────────────────────────────

def load_ta_data(ticker: str, exchange: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Load TA indicator data from DB for a given ticker and date range."""
    with get_conn() as conn:
        df = pd.read_sql(
            """
            SELECT trade_date, open, high, low, close, volume, change_pct,
                   rsi, macd_line, macd_signal, macd_hist,
                   bb_upper, bb_middle, bb_lower, bb_pct,
                   ema_9, ema_20, ema_50, ema_200,
                   stoch_k, stoch_d, atr, atr_pct, adx,
                   vol_ratio_5, vol_ratio_10, vol_ratio_30,
                   overall_signal, signal_score
            FROM datapai.ta_indicators
            WHERE ticker = %s AND exchange = %s
              AND trade_date >= %s AND trade_date <= %s
              AND timeframe = '1d'
            ORDER BY trade_date
            """,
            conn,
            params=[ticker, exchange, start_date, end_date],
        )
    if not df.empty:
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date")
    return df


def load_benchmark(start_date: str, end_date: str) -> pd.DataFrame:
    """Load S&P 500 benchmark data from prices table."""
    with get_conn() as conn:
        df = pd.read_sql(
            """
            SELECT trade_date, close
            FROM datapai.prices
            WHERE ticker = %s AND trade_date >= %s AND trade_date <= %s
            ORDER BY trade_date
            """,
            conn,
            params=[BENCHMARK_TICKER, start_date, end_date],
        )
    if not df.empty:
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("trade_date")
    return df


def resolve_tickers(strategy: dict) -> list[str]:
    """Resolve the ticker list from strategy config."""
    tickers = strategy.get("tickers")
    exchange = strategy["exchange"]

    if tickers == "all_featured" or tickers is None:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT ticker FROM datapai.ticker_universe
                       WHERE exchange = %s AND is_active = TRUE AND is_featured = TRUE
                       ORDER BY featured_order LIMIT 50""",
                    (exchange,),
                )
                return [r[0] for r in cur.fetchall()]

    if isinstance(tickers, list):
        return tickers[:50]  # max 50

    if isinstance(tickers, str):
        try:
            parsed = json.loads(tickers)
            if isinstance(parsed, list):
                return parsed[:50]
        except (json.JSONDecodeError, TypeError):
            return [tickers]

    return []


# ── Simulation engine ────────────────────────────────────────────────────────

def run_backtest_for_ticker(
    ticker: str,
    exchange: str,
    config: dict,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """Run backtest for a single ticker. Returns list of trade dicts."""
    entry_rules = config.get("entry_rules", [])
    exit_rules = config.get("exit_rules", [])

    df = load_ta_data(ticker, exchange, start_date, end_date)
    if df.empty or len(df) < 5:
        return []

    trades = []
    in_position = False
    entry_price = 0.0
    entry_date = None
    entry_signal = ""
    peak_price = 0.0
    trailing_stop_pct = None

    # Extract trailing stop from exit rules
    for r in exit_rules:
        if r.get("indicator") == "trailing_stop_pct":
            trailing_stop_pct = float(r.get("value", 3))

    prev_row = None
    for idx, row in df.iterrows():
        if in_position:
            # Update trailing stop peak
            if row["close"] > peak_price:
                peak_price = row["close"]

            # Check trailing stop
            if trailing_stop_pct and peak_price > 0:
                trail_price = peak_price * (1 - trailing_stop_pct / 100)
                if row["close"] <= trail_price:
                    ret_pct = ((row["close"] - entry_price) / entry_price) * 100
                    trades.append({
                        "ticker": ticker,
                        "entry_date": str(entry_date),
                        "entry_price": round(entry_price, 4),
                        "exit_date": str(idx.date()),
                        "exit_price": round(row["close"], 4),
                        "return_pct": round(ret_pct, 2),
                        "entry_signal": entry_signal,
                        "exit_signal": f"Trailing stop ({trailing_stop_pct}%)",
                    })
                    in_position = False
                    prev_row = row
                    continue

            # Check other exit conditions
            should_exit, reason = check_exit(row, prev_row, exit_rules, entry_price)
            if should_exit:
                ret_pct = ((row["close"] - entry_price) / entry_price) * 100
                trades.append({
                    "ticker": ticker,
                    "entry_date": str(entry_date),
                    "entry_price": round(entry_price, 4),
                    "exit_date": str(idx.date()),
                    "exit_price": round(row["close"], 4),
                    "return_pct": round(ret_pct, 2),
                    "entry_signal": entry_signal,
                    "exit_signal": reason,
                })
                in_position = False
        else:
            # Check entry conditions
            if check_entry(row, prev_row, entry_rules):
                in_position = True
                entry_price = row["close"]
                entry_date = idx.date()
                peak_price = entry_price
                entry_signal = ", ".join(
                    f"{r.get('indicator','')} {r.get('condition','')} {r.get('value','')}"
                    for r in entry_rules
                ).strip()

        prev_row = row

    # Close open position at last price
    if in_position and len(df) > 0:
        last = df.iloc[-1]
        ret_pct = ((last["close"] - entry_price) / entry_price) * 100
        trades.append({
            "ticker": ticker,
            "entry_date": str(entry_date),
            "entry_price": round(entry_price, 4),
            "exit_date": str(df.index[-1].date()),
            "exit_price": round(last["close"], 4),
            "return_pct": round(ret_pct, 2),
            "entry_signal": entry_signal,
            "exit_signal": "End of period",
        })

    return trades


def compute_backtest_results(
    config: dict,
    exchange: str,
    tickers: list[str],
) -> dict:
    """Run full backtest across all tickers and compute aggregate results."""
    bp = config.get("backtest_params", {})
    start_date = bp.get("start_date", (date.today() - timedelta(days=365)).isoformat())
    end_date = bp.get("end_date", date.today().isoformat())
    initial_capital = float(bp.get("initial_capital", DEFAULT_INITIAL_CAPITAL))
    commission_pct = float(bp.get("commission_pct", DEFAULT_COMMISSION_PCT))

    position_sizing = config.get("position_sizing", {})
    max_positions = int(position_sizing.get("max_positions", 10))
    max_per_position_pct = float(position_sizing.get("max_per_position_pct", 15))

    # Run backtest for each ticker
    all_trades = []
    for ticker in tickers:
        try:
            trades = run_backtest_for_ticker(ticker, exchange, config, start_date, end_date)
            all_trades.extend(trades)
        except Exception as e:
            logger.warning("Backtest failed for %s: %s", ticker, e)
            continue

    if not all_trades:
        return _empty_results(initial_capital, start_date, end_date)

    # Sort trades by entry date
    all_trades.sort(key=lambda t: t["entry_date"])

    # Simulate portfolio equity curve
    capital = initial_capital
    equity_curve = [{"date": start_date, "value": round(capital, 2)}]
    monthly_returns: dict[str, float] = {}

    # Simple simulation: equal-weight positions, sequential
    position_size = capital / max(max_positions, 1)

    for trade in all_trades:
        # Commission cost
        commission = position_size * (commission_pct / 100) * 2  # entry + exit
        trade_pnl = position_size * (trade["return_pct"] / 100) - commission
        capital += trade_pnl

        equity_curve.append({
            "date": trade["exit_date"],
            "value": round(capital, 2),
        })

        # Monthly return tracking
        month = trade["exit_date"][:7]
        monthly_returns[month] = monthly_returns.get(month, 0) + trade["return_pct"]

    # Calculate summary metrics
    total_return_pct = ((capital - initial_capital) / initial_capital) * 100

    # Annualized return
    days = max((date.fromisoformat(end_date) - date.fromisoformat(start_date)).days, 1)
    years = days / 365.25
    annualized_return = ((capital / initial_capital) ** (1 / max(years, 0.01)) - 1) * 100

    # Win rate
    winning = sum(1 for t in all_trades if t["return_pct"] > 0)
    win_rate = (winning / len(all_trades)) * 100 if all_trades else 0

    # Average trade return
    avg_trade_return = sum(t["return_pct"] for t in all_trades) / len(all_trades)

    # Max drawdown from equity curve
    equity_values = [e["value"] for e in equity_curve]
    max_dd = _max_drawdown(equity_values)

    # Sharpe ratio (simplified: using trade returns as proxy)
    returns = [t["return_pct"] for t in all_trades]
    sharpe = _sharpe_ratio(returns)

    # Benchmark comparison
    benchmark_return = _benchmark_return(start_date, end_date)
    alpha = total_return_pct - benchmark_return

    # Monthly returns list
    monthly_list = [{"month": m, "return_pct": round(r, 2)} for m, r in sorted(monthly_returns.items())]

    return {
        "summary": {
            "total_return_pct": round(total_return_pct, 2),
            "annualized_return_pct": round(annualized_return, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "win_rate_pct": round(win_rate, 1),
            "total_trades": len(all_trades),
            "avg_trade_return_pct": round(avg_trade_return, 2),
            "benchmark_return_pct": round(benchmark_return, 2),
            "alpha_pct": round(alpha, 2),
            "initial_capital": initial_capital,
            "final_capital": round(capital, 2),
        },
        "trades": all_trades[:200],  # cap at 200 for storage
        "equity_curve": equity_curve,
        "monthly_returns": monthly_list,
    }


def _empty_results(capital: float, start: str, end: str) -> dict:
    return {
        "summary": {
            "total_return_pct": 0, "annualized_return_pct": 0, "sharpe_ratio": 0,
            "max_drawdown_pct": 0, "win_rate_pct": 0, "total_trades": 0,
            "avg_trade_return_pct": 0, "benchmark_return_pct": 0, "alpha_pct": 0,
            "initial_capital": capital, "final_capital": capital,
        },
        "trades": [],
        "equity_curve": [{"date": start, "value": capital}, {"date": end, "value": capital}],
        "monthly_returns": [],
    }


def _max_drawdown(equity: list[float]) -> float:
    """Calculate max drawdown percentage from equity series."""
    if len(equity) < 2:
        return 0
    peak = equity[0]
    max_dd = 0
    for v in equity:
        if v > peak:
            peak = v
        dd = ((v - peak) / peak) * 100 if peak > 0 else 0
        if dd < max_dd:
            max_dd = dd
    return max_dd


def _sharpe_ratio(returns: list[float], risk_free_annual: float = 4.0) -> float:
    """Simplified Sharpe ratio from trade returns."""
    if len(returns) < 2:
        return 0
    arr = np.array(returns)
    mean = np.mean(arr)
    std = np.std(arr, ddof=1)
    if std == 0:
        return 0
    # Assume ~252 trades per year as annualization factor (rough)
    trades_per_year = min(len(returns), 252)
    annual_return = mean * trades_per_year
    annual_std = std * np.sqrt(trades_per_year)
    return (annual_return - risk_free_annual) / annual_std if annual_std > 0 else 0


def _benchmark_return(start_date: str, end_date: str) -> float:
    """Get S&P 500 return over the period."""
    try:
        bm = load_benchmark(start_date, end_date)
        if bm.empty or len(bm) < 2:
            return 0
        return ((bm["close"].iloc[-1] - bm["close"].iloc[0]) / bm["close"].iloc[0]) * 100
    except Exception:
        return 0


# ── Main runner ──────────────────────────────────────────────────────────────

def fetch_pending_strategies(strategy_id: int | None = None, max_count: int = MAX_STRATEGIES_PER_RUN) -> list[dict]:
    """Load strategies that need backtesting."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            if strategy_id:
                cur.execute(
                    """SELECT id, user_id, name, exchange, tickers, strategy_type, config,
                              backtest_status, last_backtest_at
                       FROM datapai.usr_strategies
                       WHERE id = %s AND is_active = TRUE""",
                    (strategy_id,),
                )
            else:
                cur.execute(
                    """SELECT id, user_id, name, exchange, tickers, strategy_type, config,
                              backtest_status, last_backtest_at
                       FROM datapai.usr_strategies
                       WHERE is_active = TRUE
                         AND (backtest_status = 'pending'
                              OR (updated_at > last_backtest_at AND backtest_status != 'running'))
                       ORDER BY created_at
                       LIMIT %s""",
                    (max_count,),
                )
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            return [dict(zip(cols, r)) for r in rows]


def mark_strategy_status(strategy_id: int, status: str):
    """Update strategy backtest_status."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            if status == "completed":
                cur.execute(
                    """UPDATE datapai.usr_strategies
                       SET backtest_status = %s, last_backtest_at = NOW(), updated_at = NOW()
                       WHERE id = %s""",
                    (status, strategy_id),
                )
            else:
                cur.execute(
                    """UPDATE datapai.usr_strategies
                       SET backtest_status = %s, updated_at = NOW()
                       WHERE id = %s""",
                    (status, strategy_id),
                )


def store_results(strategy_id: int, user_id: str, config: dict, results: dict, status: str = "completed", error: str | None = None):
    """Store backtest results in DB."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO datapai.usr_backtest_results
                   (strategy_id, user_id, run_date, config_snapshot, results, status, error_message)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    strategy_id,
                    user_id,
                    date.today(),
                    json.dumps(config),
                    json.dumps(results),
                    status,
                    error,
                ),
            )


def run_backtest(strategy: dict) -> bool:
    """Run backtest for a single strategy. Returns True on success."""
    sid = strategy["id"]
    name = strategy["name"]
    user_id = strategy["user_id"]
    exchange = strategy["exchange"]

    config = strategy["config"]
    if isinstance(config, str):
        config = json.loads(config)

    logger.info("Running backtest for strategy #%d '%s' (user=%s, exchange=%s)", sid, name, user_id, exchange)

    mark_strategy_status(sid, "running")

    try:
        tickers = resolve_tickers(strategy)
        if not tickers:
            raise ValueError("No tickers resolved for strategy")

        logger.info("  Tickers: %d (%s...)", len(tickers), ", ".join(tickers[:5]))

        results = compute_backtest_results(config, exchange, tickers)

        store_results(sid, user_id, config, results)
        mark_strategy_status(sid, "completed")

        summary = results.get("summary", {})
        logger.info(
            "  Completed: return=%.1f%%, sharpe=%.2f, trades=%d, alpha=%.1f%%",
            summary.get("total_return_pct", 0),
            summary.get("sharpe_ratio", 0),
            summary.get("total_trades", 0),
            summary.get("alpha_pct", 0),
        )
        return True

    except Exception as e:
        logger.error("  FAILED: %s", e, exc_info=True)
        store_results(sid, user_id, config, {}, status="failed", error=str(e))
        mark_strategy_status(sid, "failed")
        return False


def main():
    parser = argparse.ArgumentParser(description="Run user backtests")
    parser.add_argument("--strategy-id", type=int, help="Run single strategy")
    parser.add_argument("--max", type=int, default=MAX_STRATEGIES_PER_RUN, help="Max strategies per run")
    args = parser.parse_args()

    strategies = fetch_pending_strategies(args.strategy_id, args.max)
    if not strategies:
        logger.info("No pending strategies to backtest.")
        return

    logger.info("Found %d strategies to backtest", len(strategies))

    ok = 0
    fail = 0
    for s in strategies:
        if run_backtest(s):
            ok += 1
        else:
            fail += 1

    logger.info("Backtest run complete: %d succeeded, %d failed", ok, fail)


if __name__ == "__main__":
    main()
