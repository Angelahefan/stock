#!/usr/bin/env python3
"""
compute_multi_factor_signals.py — Multi-factor signal scoring engine.

Combines:
  1. Technical Analysis (from screener_metrics)
  2. Fundamental Quality (from fundamental_lite)
  3. Value + Momentum cross-check

Produces Buy/Hold/Sell signals per timeframe (Days/Weeks/Months/Quarter)
that are superior to pure-TA signals because they filter out junk stocks
and boost conviction for quality companies at good prices.

Usage:
    python scripts/compute_multi_factor_signals.py --exchange US
    python scripts/compute_multi_factor_signals.py --exchange ASX
    python scripts/compute_multi_factor_signals.py --exchange ALL

Output: datapai.multi_factor_signals table
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import sys
import time
from typing import Optional, Dict, Any, List, Tuple

import psycopg2
import psycopg2.extras

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


# ─── Signal computation helpers ──────────────────────────────────────────────

def _vote(condition: Optional[bool]) -> int:
    """Returns +1 for True, -1 for False, 0 for None/unknown."""
    if condition is None:
        return 0
    return 1 if condition else -1


def compute_ta_votes(r: Dict[str, Any], timeframe: str) -> Tuple[List[int], List[str]]:
    """
    Compute TA indicator votes for a given timeframe.
    Returns (votes_list, indicator_names) for transparency.
    """
    votes = []
    names = []

    rsi = r.get("rsi_14")
    macd = r.get("macd_trend")
    kdj = r.get("kdj_signal")
    sma5 = r.get("sma_5")
    sma10 = r.get("sma_10")
    sma20 = r.get("sma_20")
    sma50 = r.get("sma_50")
    sma200 = r.get("sma_200")
    bb_pct_b = r.get("bb_pct_b")
    obv = r.get("obv_trend")
    chg_1d = r.get("change_1d_pct")
    chg_5d = r.get("change_5d_pct")
    chg_1m = r.get("change_1m_pct")
    chg_3m = r.get("change_3m_pct")
    chg_6m = r.get("change_6m_pct")
    chg_1y = r.get("change_1y_pct")
    pct_52w = r.get("pct_from_52w_high")
    close = r.get("latest_close")
    vol_ratio = r.get("volume_ratio")

    if timeframe == "days":
        # RSI recovery zone (30-45 = buy zone, not <30 falling knife)
        if rsi is not None:
            if 30 <= rsi <= 45:
                votes.append(1); names.append("RSI recovery")
            elif rsi >= 65:
                votes.append(-1); names.append("RSI hot")
            else:
                votes.append(0); names.append("RSI neutral")

        # MACD
        if macd:
            votes.append(1 if macd == "BULLISH" else -1)
            names.append("MACD")

        # KDJ
        if kdj:
            votes.append(1 if kdj == "OVERSOLD" else (-1 if kdj == "OVERBOUGHT" else 0))
            names.append("KDJ")

        # Price extension: overextended = sell (take profit)
        if close and sma5 and sma5 > 0:
            ext = ((close - sma5) / sma5) * 100
            votes.append(-1 if ext > 3 else (1 if ext < -3 else 0))
            names.append("SMA5 ext")

        # 1D change guard
        if chg_1d is not None:
            votes.append(-1 if chg_1d > 3 else (1 if chg_1d < -3 else 0))
            names.append("1D guard")

    elif timeframe == "weeks":
        # SMA10 vs SMA20
        if sma10 and sma20:
            votes.append(1 if sma10 > sma20 else -1)
            names.append("SMA10/20")

        # Bollinger %B
        if bb_pct_b is not None:
            votes.append(1 if bb_pct_b < 0.2 else (-1 if bb_pct_b > 0.8 else 0))
            names.append("BB %B")

        # MACD
        if macd:
            votes.append(1 if macd == "BULLISH" else -1)
            names.append("MACD")

        # Volume confirmation
        if vol_ratio is not None and obv:
            if vol_ratio > 1.5 and obv == "UP":
                votes.append(1)
            elif vol_ratio > 1.5 and obv == "DOWN":
                votes.append(-1)
            else:
                votes.append(0)
            names.append("Vol confirm")

        # 5D extension guard
        if chg_5d is not None:
            votes.append(-1 if chg_5d > 8 else (1 if chg_5d < -8 else 0))
            names.append("5D guard")

    elif timeframe == "months":
        # SMA20 vs SMA50
        if sma20 and sma50:
            votes.append(1 if sma20 > sma50 else -1)
            names.append("SMA20/50")

        # RSI (wider bands for medium term)
        if rsi is not None:
            votes.append(1 if rsi <= 35 else (-1 if rsi >= 65 else 0))
            names.append("RSI")

        # 1M change: trend regime filter
        if chg_1m is not None:
            if chg_1m > 5:
                votes.append(1)  # uptrend
            elif chg_1m < -10:
                votes.append(-1)  # downtrend
            else:
                votes.append(0)
            names.append("1M trend")

        # OBV
        if obv:
            votes.append(1 if obv == "UP" else (-1 if obv == "DOWN" else 0))
            names.append("OBV")

        # 1M extension guard
        if chg_1m is not None:
            votes.append(-1 if chg_1m > 20 else (1 if chg_1m < -15 else 0))
            names.append("1M guard")

    elif timeframe == "quarter":
        # SMA50 vs SMA200
        if sma50 and sma200:
            votes.append(1 if sma50 > sma200 else -1)
            names.append("SMA50/200")

        # 52-week position
        if pct_52w is not None:
            votes.append(1 if pct_52w > -10 else (-1 if pct_52w < -40 else 0))
            names.append("52w position")

        # 3M trend
        if chg_3m is not None:
            votes.append(1 if chg_3m > 10 else (-1 if chg_3m < -15 else 0))
            names.append("3M trend")

        # 6M trend
        if chg_6m is not None:
            votes.append(1 if chg_6m > 15 else (-1 if chg_6m < -20 else 0))
            names.append("6M trend")

        # 1Y trend
        if chg_1y is not None:
            votes.append(1 if chg_1y > 20 else (-1 if chg_1y < -30 else 0))
            names.append("1Y trend")

    return votes, names


def compute_fundamental_modifier(f: Optional[Dict[str, Any]], timeframe: str) -> Tuple[float, str]:
    """
    Compute a fundamental quality modifier that adjusts the TA signal.

    Returns (modifier, reason):
      modifier > 0: boost BUY confidence (quality company)
      modifier < 0: suppress BUY / boost SELL (junk company)
      modifier = 0: no fundamental data (pure TA)
    """
    if f is None:
        return 0.0, "no_fundamental_data"

    tier = f.get("quality_tier", "D")
    is_profitable = f.get("is_profitable", False)
    is_growing = f.get("is_growing", False)
    is_healthy = f.get("is_healthy", False)
    net_margin = f.get("net_margin")
    roe = f.get("roe")
    revenue_yoy = f.get("revenue_yoy")
    pe = f.get("pe_ratio")
    forward_pe = f.get("forward_pe")
    analyst_target = f.get("analyst_target")
    close = f.get("latest_close")  # will be joined from screener_metrics

    modifier = 0.0
    reasons = []

    # Quality tier bonus/penalty
    if tier == "A":
        modifier += 1.5
        reasons.append("tier_A")
    elif tier == "B":
        modifier += 0.75
        reasons.append("tier_B")
    elif tier == "C":
        modifier += 0.0
        reasons.append("tier_C")
    else:  # D
        modifier -= 1.0
        reasons.append("tier_D")

    # Profitability bonus
    if is_profitable:
        modifier += 0.5
        if net_margin and net_margin > 0.15:
            modifier += 0.5
            reasons.append("high_margin")
    else:
        modifier -= 0.5
        reasons.append("unprofitable")

    # Growth bonus (more important for shorter timeframes)
    if is_growing:
        growth_weight = {"days": 0.25, "weeks": 0.5, "months": 0.75, "quarter": 1.0}.get(timeframe, 0.5)
        modifier += growth_weight
        if revenue_yoy and revenue_yoy > 0.20:
            modifier += growth_weight * 0.5
            reasons.append("strong_growth")

    # Value check: reasonable PE = boost
    if pe is not None:
        if 5 < pe < 25:
            modifier += 0.5
            reasons.append("reasonable_PE")
        elif pe > 100 or pe < 0:
            modifier -= 0.5
            reasons.append("extreme_PE")

    # Analyst upside (more relevant for longer timeframes)
    if analyst_target and close and close > 0:
        upside = ((analyst_target - close) / close) * 100
        if timeframe in ("months", "quarter"):
            if upside > 20:
                modifier += 1.0
                reasons.append(f"analyst_upside_{upside:.0f}%")
            elif upside < -10:
                modifier -= 0.5
                reasons.append(f"analyst_downside_{upside:.0f}%")

    return modifier, "+".join(reasons) if reasons else "neutral"


def compute_signal(ta_votes: List[int], fund_modifier: float, timeframe: str) -> Dict[str, Any]:
    """
    Combine TA votes + fundamental modifier into final signal.

    Signal logic:
      ta_sum = sum of TA indicator votes
      adjusted = ta_sum + fund_modifier
      BUY: adjusted >= threshold
      SELL: adjusted <= -threshold (asymmetric for short-term)
      HOLD: everything else

    Confidence = |adjusted| / max_possible * 100
    """
    ta_sum = sum(ta_votes)
    adjusted = ta_sum + fund_modifier
    n_indicators = len(ta_votes)

    # Thresholds: short-term easier to sell (take profit), long-term symmetric
    if timeframe in ("days", "weeks"):
        buy_threshold = 3.0
        sell_threshold = -2.0
    else:
        buy_threshold = 3.0
        sell_threshold = -3.0

    if adjusted >= buy_threshold:
        signal = "BUY"
    elif adjusted <= sell_threshold:
        signal = "SELL"
    else:
        signal = "HOLD"

    # Confidence: how far past threshold
    max_possible = n_indicators + abs(fund_modifier) + 2  # rough max
    if max_possible == 0:
        max_possible = 1
    confidence = min(abs(adjusted) / max_possible * 100, 100)

    return {
        "signal": signal,
        "ta_score": ta_sum,
        "fund_modifier": round(fund_modifier, 2),
        "adjusted_score": round(adjusted, 2),
        "confidence": round(confidence, 1),
        "n_indicators": n_indicators,
    }


# ─── Main pipeline ───────────────────────────────────────────────────────────

def ensure_table(conn):
    """Create output table if not exists."""
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS datapai.multi_factor_signals (
            ticker          TEXT NOT NULL,
            exchange        TEXT NOT NULL,
            -- Timeframe signals
            signal_days     TEXT,
            score_days      DOUBLE PRECISION,
            conf_days       DOUBLE PRECISION,
            detail_days     TEXT,

            signal_weeks    TEXT,
            score_weeks     DOUBLE PRECISION,
            conf_weeks      DOUBLE PRECISION,
            detail_weeks    TEXT,

            signal_months   TEXT,
            score_months    DOUBLE PRECISION,
            conf_months     DOUBLE PRECISION,
            detail_months   TEXT,

            signal_quarter  TEXT,
            score_quarter   DOUBLE PRECISION,
            conf_quarter    DOUBLE PRECISION,
            detail_quarter  TEXT,

            -- Fundamental quality context
            quality_tier    TEXT,
            fund_modifier_avg DOUBLE PRECISION,

            -- Meta
            computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (ticker, exchange)
        );
        CREATE INDEX IF NOT EXISTS idx_mf_signals_exchange ON datapai.multi_factor_signals (exchange);
        """)
    conn.commit()


UPSERT_SIGNAL_SQL = """
INSERT INTO datapai.multi_factor_signals (
    ticker, exchange,
    signal_days, score_days, conf_days, detail_days,
    signal_weeks, score_weeks, conf_weeks, detail_weeks,
    signal_months, score_months, conf_months, detail_months,
    signal_quarter, score_quarter, conf_quarter, detail_quarter,
    quality_tier, fund_modifier_avg, computed_at
) VALUES (
    %(ticker)s, %(exchange)s,
    %(signal_days)s, %(score_days)s, %(conf_days)s, %(detail_days)s,
    %(signal_weeks)s, %(score_weeks)s, %(conf_weeks)s, %(detail_weeks)s,
    %(signal_months)s, %(score_months)s, %(conf_months)s, %(detail_months)s,
    %(signal_quarter)s, %(score_quarter)s, %(conf_quarter)s, %(detail_quarter)s,
    %(quality_tier)s, %(fund_modifier_avg)s, NOW()
)
ON CONFLICT (ticker, exchange) DO UPDATE SET
    signal_days = EXCLUDED.signal_days, score_days = EXCLUDED.score_days,
    conf_days = EXCLUDED.conf_days, detail_days = EXCLUDED.detail_days,
    signal_weeks = EXCLUDED.signal_weeks, score_weeks = EXCLUDED.score_weeks,
    conf_weeks = EXCLUDED.conf_weeks, detail_weeks = EXCLUDED.detail_weeks,
    signal_months = EXCLUDED.signal_months, score_months = EXCLUDED.score_months,
    conf_months = EXCLUDED.conf_months, detail_months = EXCLUDED.detail_months,
    signal_quarter = EXCLUDED.signal_quarter, score_quarter = EXCLUDED.score_quarter,
    conf_quarter = EXCLUDED.conf_quarter, detail_quarter = EXCLUDED.detail_quarter,
    quality_tier = EXCLUDED.quality_tier, fund_modifier_avg = EXCLUDED.fund_modifier_avg,
    computed_at = NOW()
"""


def run(exchange: str):
    conn = get_conn()
    ensure_table(conn)
    t0 = time.time()

    # Load TA metrics (daily from screener_metrics)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT * FROM datapai.screener_metrics
            WHERE exchange = %s AND latest_close IS NOT NULL
        """, (exchange,))
        ta_rows = {r["ticker"]: dict(r) for r in cur.fetchall()}

    log.info("Loaded %d daily TA rows for %s", len(ta_rows), exchange)

    # Load weekly TA indicators (for weeks/months signals — proper timeframe data)
    ta_weekly: dict = {}
    ta_monthly: dict = {}
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Weekly: latest row per ticker (map ta_indicators columns to screener_metrics names)
        cur.execute("""
            SELECT DISTINCT ON (ticker) ticker, exchange,
                   rsi as rsi_14,
                   macd_label as macd_trend,
                   stoch_label as kdj_signal,
                   overall_signal, signal_score,
                   ema_5 as sma_5, ema_10 as sma_10, ema_20 as sma_20,
                   ema_50 as sma_50, ema_200 as sma_200,
                   bb_pct as bb_pct_b,
                   obv_trend,
                   close as latest_close,
                   change_pct as change_1w_pct
            FROM datapai.ta_indicators
            WHERE exchange = %s AND timeframe = '1w'
            ORDER BY ticker, trade_date DESC
        """, (exchange,))
        ta_weekly = {r["ticker"]: dict(r) for r in cur.fetchall()}

        # Monthly: latest row per ticker
        cur.execute("""
            SELECT DISTINCT ON (ticker) ticker, exchange,
                   rsi as rsi_14,
                   macd_label as macd_trend,
                   stoch_label as kdj_signal,
                   overall_signal, signal_score,
                   ema_5 as sma_5, ema_10 as sma_10, ema_20 as sma_20,
                   ema_50 as sma_50, ema_200 as sma_200,
                   bb_pct as bb_pct_b,
                   obv_trend,
                   close as latest_close,
                   change_pct as change_1m_pct
            FROM datapai.ta_indicators
            WHERE exchange = %s AND timeframe = '1mo'
            ORDER BY ticker, trade_date DESC
        """, (exchange,))
        ta_monthly = {r["ticker"]: dict(r) for r in cur.fetchall()}

    log.info("Loaded %d weekly, %d monthly TA rows for %s",
             len(ta_weekly), len(ta_monthly), exchange)

    # Load fundamental data
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT * FROM datapai.fundamental_lite
            WHERE exchange = %s
        """, (exchange,))
        fund_rows = {r["ticker"]: dict(r) for r in cur.fetchall()}

    log.info("Loaded %d fundamental rows for %s", len(fund_rows), exchange)

    # Compute signals for each ticker
    results = []
    signal_dist = {"days": {}, "weeks": {}, "months": {}, "quarter": {}}

    for ticker, ta in ta_rows.items():
        fund = fund_rows.get(ticker)  # May be None

        # Inject close price into fund dict for analyst upside calc
        if fund and ta.get("latest_close"):
            fund["latest_close"] = ta["latest_close"]

        row = {"ticker": ticker, "exchange": exchange}
        fund_mods = []

        for tf in ("days", "weeks", "months", "quarter"):
            # Use correct timeframe TA data:
            #   days   → daily (screener_metrics)
            #   weeks  → weekly (ta_indicators 1w) — fallback to daily if no weekly data
            #   months → monthly (ta_indicators 1mo) — fallback to daily
            #   quarter → monthly (same as months — longest available timeframe)
            if tf == "weeks" and ticker in ta_weekly:
                ta_for_tf = ta_weekly[ticker]
            elif tf in ("months", "quarter") and ticker in ta_monthly:
                ta_for_tf = ta_monthly[ticker]
            else:
                ta_for_tf = ta  # fallback to daily

            ta_votes, ta_names = compute_ta_votes(ta_for_tf, tf)
            fund_mod, fund_reason = compute_fundamental_modifier(fund, tf)
            fund_mods.append(fund_mod)

            sig = compute_signal(ta_votes, fund_mod, tf)

            row[f"signal_{tf}"] = sig["signal"]
            row[f"score_{tf}"] = sig["adjusted_score"]
            row[f"conf_{tf}"] = sig["confidence"]

            # Detail: human-readable breakdown
            vote_details = [f"{n}={v:+d}" for v, n in zip(ta_votes, ta_names)]
            detail = f"TA[{sig['ta_score']:+d}]={','.join(vote_details)} Fund[{fund_mod:+.1f}]={fund_reason}"
            row[f"detail_{tf}"] = detail[:500]  # truncate for DB

            # Track distribution
            signal_dist[tf][sig["signal"]] = signal_dist[tf].get(sig["signal"], 0) + 1

        row["quality_tier"] = fund["quality_tier"] if fund else None
        row["fund_modifier_avg"] = round(sum(fund_mods) / len(fund_mods), 2) if fund_mods else None

        results.append(row)

    # Upsert all
    log.info("Upserting %d multi-factor signals...", len(results))
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, UPSERT_SIGNAL_SQL, results, page_size=500)
    conn.commit()

    elapsed = time.time() - t0
    log.info("Done %s in %.1fs", exchange, elapsed)

    # Distribution report
    for tf in ("days", "weeks", "months", "quarter"):
        dist = signal_dist[tf]
        total = sum(dist.values())
        parts = " | ".join(f"{k}={v} ({v/total*100:.0f}%)" for k, v in sorted(dist.items()))
        log.info("  %-8s %s  (total=%d)", tf, parts, total)

    conn.close()
    return len(results)


def main():
    parser = argparse.ArgumentParser(description="Compute multi-factor signals")
    parser.add_argument("--exchange", default="ALL", help="US, ASX, or ALL")
    args = parser.parse_args()

    exchanges = ["US", "ASX"] if args.exchange.upper() == "ALL" else [args.exchange.upper()]
    for ex in exchanges:
        run(ex)


if __name__ == "__main__":
    main()
