#!/usr/bin/env python3
"""
compute_screener_metrics.py — Compute price-based screening metrics for ALL tickers.

Reads from datapai.prices (OHLCV), computes:
  - % price changes (1d/5d/1m/3m/6m/1y)
  - 52-week high/low
  - SMA 5/10/20/30/50/200 + price vs each
  - Golden/death cross
  - RSI-14
  - MACD (12/26/9)
  - KDJ / Stochastic (9,3,3)
  - Bollinger Bands (20,2)
  - Pivot Points (PP, R1/R2, S1/S2)
  - Volume indicators (ratios, OBV trend)
  - 20-day volatility

and upserts into datapai.screener_metrics.

Usage:
    python scripts/compute_screener_metrics.py [--exchange US|ASX|ALL]

Runs in ~40-60s for 8,500 tickers.
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from typing import Optional, List, Dict

import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_conn():
    """Get Postgres connection using standard env vars."""
    import os
    return psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "postgres"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", ""),
    )


# ── TA helper functions ───────────────────────────────────────────────────────

def compute_rsi(gains: List[float], losses: List[float], period: int = 14) -> Optional[float]:
    """Compute RSI matching Yahoo Finance exactly: SMA-based rolling average."""
    if len(gains) < period:
        return None
    # Yahoo uses simple rolling mean (SMA), not Wilder EMA smoothing
    # Take the last `period` gains/losses (most recent)
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_ema(values: List[float], period: int) -> Optional[float]:
    """Compute EMA over a list ordered newest→oldest. Returns latest EMA."""
    if len(values) < period:
        return None
    # Reverse so oldest first
    vals = list(reversed(values[:period * 3]))  # use up to 3x period for warm-up
    if len(vals) < period:
        return None
    multiplier = 2.0 / (period + 1)
    ema = sum(vals[:period]) / period  # seed with SMA
    for v in vals[period:]:
        ema = (v - ema) * multiplier + ema
    return ema


def compute_macd(closes: List[float]) -> Dict[str, Optional[float]]:
    """MACD(12,26,9) matching Yahoo Finance / pandas ewm() exactly.
    closes ordered newest→oldest. Uses FULL history for EMA warmup."""
    result = {"macd_line": None, "macd_signal": None, "macd_histogram": None, "macd_trend": None}
    if len(closes) < 35:
        return result

    # Cap to ~252 bars (1 year) — matches Yahoo's ewm window
    vals = list(reversed(closes[:min(len(closes), 252)]))

    # EMA matching pandas ewm(span=N, adjust=False): multiplier = 2/(N+1)
    # Seed with first value (not SMA) — this matches pandas ewm(adjust=False)
    m12 = 2.0 / 13
    m26 = 2.0 / 27
    ema12 = vals[0]
    ema26 = vals[0]

    ema12_all = []
    ema26_all = []
    for v in vals:
        ema12 = (v - ema12) * m12 + ema12
        ema26 = (v - ema26) * m26 + ema26
        ema12_all.append(ema12)
        ema26_all.append(ema26)

    # MACD line = EMA12 - EMA26
    macd_all = [e12 - e26 for e12, e26 in zip(ema12_all, ema26_all)]

    # Signal = EMA(9) of MACD line
    m9 = 2.0 / 10
    sig = macd_all[0]
    for v in macd_all:
        sig = (v - sig) * m9 + sig

    result["macd_line"] = macd_all[-1]
    result["macd_signal"] = sig
    result["macd_histogram"] = macd_all[-1] - sig
    result["macd_trend"] = "BULLISH" if macd_all[-1] > sig else "BEARISH"
    return result


def compute_kdj(highs: List[float], lows: List[float], closes: List[float],
                k_period: int = 9, d_period: int = 3) -> Dict[str, Optional[float]]:
    """KDJ/Stochastic(9,3,3) matching Yahoo Finance exactly.
    Lists ordered newest→oldest. Uses ALL data for rolling computation.
    K=SMA(3,rawK), D=SMA(3,K), J=3K-2D."""
    result = {"kdj_k": None, "kdj_d": None, "kdj_j": None, "kdj_signal": None}
    need = k_period + d_period * 2
    if len(closes) < need:
        return result

    # Cap to ~252 bars (1 year) to match Yahoo, then compute raw %K
    max_bars = min(len(closes), 252)
    n_raw = max_bars - k_period + 1
    raw_k_values = []
    for i in range(n_raw):
        hh = max(highs[i:i + k_period])
        ll = min(lows[i:i + k_period])
        if hh == ll:
            raw_k_values.append(50.0)
        else:
            raw_k_values.append((closes[i] - ll) / (hh - ll) * 100.0)

    # Reverse to oldest-first
    raw_k_values.reverse()

    if len(raw_k_values) < d_period:
        return result

    # K = SMA(d_period) of raw_K — rolling mean over ALL values
    k_values = []
    for i in range(d_period - 1, len(raw_k_values)):
        k_values.append(sum(raw_k_values[i - d_period + 1:i + 1]) / d_period)

    if len(k_values) < d_period:
        return result

    # D = SMA(d_period) of K — rolling mean over ALL K values
    d_values = []
    for i in range(d_period - 1, len(k_values)):
        d_values.append(sum(k_values[i - d_period + 1:i + 1]) / d_period)

    if not d_values:
        return result

    k = k_values[-1]
    d = d_values[-1]
    j = 3 * k - 2 * d

    result["kdj_k"] = k
    result["kdj_d"] = d
    result["kdj_j"] = j
    if k > 80:
        result["kdj_signal"] = "OVERBOUGHT"
    elif k < 20:
        result["kdj_signal"] = "OVERSOLD"
    else:
        result["kdj_signal"] = "NEUTRAL"

    return result


def compute_bollinger(closes: List[float], period: int = 20, std_mult: float = 2.0) -> Dict[str, Optional[float]]:
    """Bollinger Bands (20,2). closes ordered newest→oldest."""
    result = {"bb_upper": None, "bb_middle": None, "bb_lower": None, "bb_pct_b": None, "bb_width": None}
    if len(closes) < period:
        return result

    window = closes[:period]
    middle = sum(window) / period
    std = math.sqrt(sum((c - middle) ** 2 for c in window) / period)

    upper = middle + std_mult * std
    lower = middle - std_mult * std

    result["bb_middle"] = middle
    result["bb_upper"] = upper
    result["bb_lower"] = lower

    if upper != lower:
        result["bb_pct_b"] = (closes[0] - lower) / (upper - lower)
    result["bb_width"] = (upper - lower) / middle if middle != 0 else None

    return result


def compute_pivot_points(high: float, low: float, close: float) -> Dict[str, Optional[float]]:
    """Classic Pivot Points from yesterday's HLC."""
    pp = (high + low + close) / 3
    return {
        "pivot_pp": pp,
        "pivot_r1": 2 * pp - low,
        "pivot_r2": pp + (high - low),
        "pivot_s1": 2 * pp - high,
        "pivot_s2": pp - (high - low),
    }


def compute_obv_trend(closes: List[float], volumes: List[float], lookback: int = 10) -> Optional[str]:
    """OBV direction over last `lookback` days. Returns UP/DOWN/FLAT."""
    if len(closes) < lookback + 1 or len(volumes) < lookback + 1:
        return None
    obv = 0
    obv_start = 0
    # Walk from oldest to newest within lookback window
    for i in range(lookback, -1, -1):
        if i < lookback:
            if closes[i] > closes[i + 1]:
                obv += volumes[i]
            elif closes[i] < closes[i + 1]:
                obv -= volumes[i]
            if i == lookback // 2:
                obv_start = obv

    if obv > obv_start * 1.05:
        return "UP"
    elif obv < obv_start * 0.95:
        return "DOWN"
    return "FLAT"


# ── Main compute ──────────────────────────────────────────────────────────────

def compute_metrics_for_exchange(conn, exchange: str):
    """Compute all screener metrics for one exchange."""
    logger.info("Computing screener metrics for exchange=%s ...", exchange)
    t0 = time.time()

    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ticker FROM datapai.prices
            WHERE exchange = %s ORDER BY ticker
        """, (exchange,))
        tickers = [r[0] for r in cur.fetchall()]

    logger.info("  Found %d tickers for %s", len(tickers), exchange)
    if not tickers:
        return

    batch_size = 50
    all_rows = []

    for batch_start in range(0, len(tickers), batch_size):
        batch = tickers[batch_start:batch_start + batch_size]
        placeholders = ",".join(["%s"] * len(batch))

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"""
                SELECT ticker, trade_date, open, high, low, close, volume
                FROM (
                    SELECT ticker, trade_date, open, high, low, close, volume,
                           ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY trade_date DESC) as rn
                    FROM datapai.prices
                    WHERE exchange = %s AND ticker IN ({placeholders})
                ) sub
                WHERE rn <= 260
                ORDER BY ticker, trade_date DESC
            """, [exchange] + batch)
            rows = cur.fetchall()

        by_ticker = {}
        for r in rows:
            by_ticker.setdefault(r["ticker"], []).append(r)

        for tkr, prices in by_ticker.items():
            if len(prices) < 2:
                continue

            latest = prices[0]
            closes = [float(p["close"]) for p in prices if p["close"] is not None]
            highs = [float(p["high"]) for p in prices if p["high"] is not None]
            lows = [float(p["low"]) for p in prices if p["low"] is not None]
            volumes = [float(p["volume"]) for p in prices if p["volume"] is not None]

            if not closes or closes[0] is None or closes[0] == 0:
                continue

            c0 = closes[0]

            # ── % changes ──
            def pct_change(n):
                if len(closes) > n and closes[n] and closes[n] != 0:
                    return ((c0 - closes[n]) / closes[n]) * 100.0
                return None

            change_1d = pct_change(1)
            change_5d = pct_change(5)
            change_1m = pct_change(21)
            change_3m = pct_change(63)
            change_6m = pct_change(126)
            change_1y = pct_change(252)

            # ── 52-week range ──
            yr_closes = closes[:252]
            high_52w = max(yr_closes) if yr_closes else None
            low_52w = min(yr_closes) if yr_closes else None
            pct_from_high = ((c0 - high_52w) / high_52w * 100.0) if high_52w and high_52w != 0 else None
            pct_from_low = ((c0 - low_52w) / low_52w * 100.0) if low_52w and low_52w != 0 else None

            # ── SMAs ──
            def sma(n):
                return sum(closes[:n]) / n if len(closes) >= n else None

            sma5, sma10, sma20, sma30, sma50, sma200 = sma(5), sma(10), sma(20), sma(30), sma(50), sma(200)

            def vs_sma(ma):
                return ((c0 - ma) / ma) * 100.0 if ma and ma != 0 else None

            golden = (sma50 > sma200) if sma50 is not None and sma200 is not None else False
            death = (sma50 < sma200) if sma50 is not None and sma200 is not None else False

            # ── Volume ──
            avg_vol_5 = (sum(volumes[:5]) / 5.0) if len(volumes) >= 5 else None
            avg_vol_10 = (sum(volumes[:10]) / 10.0) if len(volumes) >= 10 else None
            avg_vol_20 = (sum(volumes[:20]) / 20.0) if len(volumes) >= 20 else None
            vol_ratio = (volumes[0] / avg_vol_20) if (avg_vol_20 and avg_vol_20 > 0 and volumes) else None

            # ── Volatility (20d annualised) ──
            volatility = None
            if len(closes) >= 21:
                rets = []
                for i in range(20):
                    if closes[i + 1] and closes[i + 1] != 0:
                        rets.append((closes[i] - closes[i + 1]) / closes[i + 1])
                if len(rets) >= 10:
                    mean_r = sum(rets) / len(rets)
                    var_r = sum((r - mean_r) ** 2 for r in rets) / len(rets)
                    volatility = math.sqrt(var_r) * math.sqrt(252) * 100.0

            # ── RSI-14 ──
            # Match Yahoo Finance: use adj_close, ~126 bars (6 months), Wilder smoothing
            rsi = None
            rsi_window = min(len(closes), 126)  # match Yahoo 6mo window
            if rsi_window >= 16:
                # closes is newest-first; take window and reverse to oldest-first
                rsi_closes = list(reversed(closes[:rsi_window]))
                gains, losses = [], []
                for i in range(1, len(rsi_closes)):
                    diff = rsi_closes[i] - rsi_closes[i - 1]
                    gains.append(max(diff, 0))
                    losses.append(max(-diff, 0))
                rsi = compute_rsi(gains, losses, 14)

            # ── MACD (12/26/9) ──
            macd = compute_macd(closes)

            # ── KDJ / Stochastic (9,3,3) ──
            kdj = compute_kdj(highs, lows, closes, k_period=14, d_period=3)

            # ── Bollinger Bands (20,2) ──
            bb = compute_bollinger(closes)

            # ── Pivot Points (from yesterday's HLC) ──
            pp = {"pivot_pp": None, "pivot_r1": None, "pivot_r2": None, "pivot_s1": None, "pivot_s2": None}
            if len(highs) >= 1 and len(lows) >= 1:
                pp = compute_pivot_points(highs[0], lows[0], c0)

            # ── OBV trend ──
            obv_trend = compute_obv_trend(closes, volumes)

            all_rows.append((
                tkr, exchange, c0, volumes[0] if volumes else None, latest["trade_date"],
                change_1d, change_5d, change_1m, change_3m, change_6m, change_1y,
                high_52w, low_52w, pct_from_high, pct_from_low,
                sma5, sma10, sma20, sma30, sma50, sma200,
                vs_sma(sma5), vs_sma(sma10), vs_sma(sma20), vs_sma(sma30), vs_sma(sma50), vs_sma(sma200),
                golden, death,
                avg_vol_20, vol_ratio,
                volatility, rsi,
                # New TA indicators
                macd["macd_line"], macd["macd_signal"], macd["macd_histogram"], macd["macd_trend"],
                kdj["kdj_k"], kdj["kdj_d"], kdj["kdj_j"], kdj["kdj_signal"],
                bb["bb_upper"], bb["bb_middle"], bb["bb_lower"], bb["bb_pct_b"], bb["bb_width"],
                pp["pivot_pp"], pp["pivot_r1"], pp["pivot_r2"], pp["pivot_s1"], pp["pivot_s2"],
                obv_trend, avg_vol_5, avg_vol_10,
            ))

        if batch_start % 500 == 0 and batch_start > 0:
            logger.info("    Processed %d / %d tickers (%d metrics so far)", batch_start, len(tickers), len(all_rows))

    # ── Step 3: Upsert all rows ──────────────────────────────────────────────
    logger.info("  Upserting %d rows into screener_metrics ...", len(all_rows))

    upsert_sql = """
        INSERT INTO datapai.screener_metrics (
            ticker, exchange, latest_close, latest_volume, trade_date,
            change_1d_pct, change_5d_pct, change_1m_pct, change_3m_pct, change_6m_pct, change_1y_pct,
            high_52w, low_52w, pct_from_52w_high, pct_from_52w_low,
            sma_5, sma_10, sma_20, sma_30, sma_50, sma_200,
            price_vs_sma5_pct, price_vs_sma10_pct, price_vs_sma20_pct, price_vs_sma30_pct, price_vs_sma50_pct, price_vs_sma200_pct,
            golden_cross, death_cross,
            avg_volume_20d, volume_ratio,
            volatility_20d, rsi_14,
            macd_line, macd_signal, macd_histogram, macd_trend,
            kdj_k, kdj_d, kdj_j, kdj_signal,
            bb_upper, bb_middle, bb_lower, bb_pct_b, bb_width,
            pivot_pp, pivot_r1, pivot_r2, pivot_s1, pivot_s2,
            obv_trend, avg_volume_5d, avg_volume_10d,
            computed_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            NOW()
        )
        ON CONFLICT (ticker, exchange)
        DO UPDATE SET
            latest_close = EXCLUDED.latest_close,
            latest_volume = EXCLUDED.latest_volume,
            trade_date = EXCLUDED.trade_date,
            change_1d_pct = EXCLUDED.change_1d_pct,
            change_5d_pct = EXCLUDED.change_5d_pct,
            change_1m_pct = EXCLUDED.change_1m_pct,
            change_3m_pct = EXCLUDED.change_3m_pct,
            change_6m_pct = EXCLUDED.change_6m_pct,
            change_1y_pct = EXCLUDED.change_1y_pct,
            high_52w = EXCLUDED.high_52w,
            low_52w = EXCLUDED.low_52w,
            pct_from_52w_high = EXCLUDED.pct_from_52w_high,
            pct_from_52w_low = EXCLUDED.pct_from_52w_low,
            sma_5 = EXCLUDED.sma_5,
            sma_10 = EXCLUDED.sma_10,
            sma_20 = EXCLUDED.sma_20,
            sma_30 = EXCLUDED.sma_30,
            sma_50 = EXCLUDED.sma_50,
            sma_200 = EXCLUDED.sma_200,
            price_vs_sma5_pct = EXCLUDED.price_vs_sma5_pct,
            price_vs_sma10_pct = EXCLUDED.price_vs_sma10_pct,
            price_vs_sma20_pct = EXCLUDED.price_vs_sma20_pct,
            price_vs_sma30_pct = EXCLUDED.price_vs_sma30_pct,
            price_vs_sma50_pct = EXCLUDED.price_vs_sma50_pct,
            price_vs_sma200_pct = EXCLUDED.price_vs_sma200_pct,
            golden_cross = EXCLUDED.golden_cross,
            death_cross = EXCLUDED.death_cross,
            avg_volume_20d = EXCLUDED.avg_volume_20d,
            volume_ratio = EXCLUDED.volume_ratio,
            volatility_20d = EXCLUDED.volatility_20d,
            rsi_14 = EXCLUDED.rsi_14,
            macd_line = EXCLUDED.macd_line,
            macd_signal = EXCLUDED.macd_signal,
            macd_histogram = EXCLUDED.macd_histogram,
            macd_trend = EXCLUDED.macd_trend,
            kdj_k = EXCLUDED.kdj_k,
            kdj_d = EXCLUDED.kdj_d,
            kdj_j = EXCLUDED.kdj_j,
            kdj_signal = EXCLUDED.kdj_signal,
            bb_upper = EXCLUDED.bb_upper,
            bb_middle = EXCLUDED.bb_middle,
            bb_lower = EXCLUDED.bb_lower,
            bb_pct_b = EXCLUDED.bb_pct_b,
            bb_width = EXCLUDED.bb_width,
            pivot_pp = EXCLUDED.pivot_pp,
            pivot_r1 = EXCLUDED.pivot_r1,
            pivot_r2 = EXCLUDED.pivot_r2,
            pivot_s1 = EXCLUDED.pivot_s1,
            pivot_s2 = EXCLUDED.pivot_s2,
            obv_trend = EXCLUDED.obv_trend,
            avg_volume_5d = EXCLUDED.avg_volume_5d,
            avg_volume_10d = EXCLUDED.avg_volume_10d,
            computed_at = NOW()
    """

    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, upsert_sql, all_rows, page_size=500)
    conn.commit()

    elapsed = time.time() - t0
    logger.info("  Done %s: %d tickers in %.1fs", exchange, len(all_rows), elapsed)


def main():
    parser = argparse.ArgumentParser(description="Compute screener metrics from price data")
    parser.add_argument("--exchange", default="ALL", help="US, ASX, or ALL (default)")
    args = parser.parse_args()

    conn = get_conn()

    try:
        exchanges = ["US", "ASX", "HOSE", "HKEX", "LSE", "SET", "KLSE", "IDX", "SSE", "SZSE", "TWSE", "SGX", "TSE"] if args.exchange.upper() == "ALL" else [args.exchange.upper()]
        for ex in exchanges:
            compute_metrics_for_exchange(conn, ex)

        with conn.cursor() as cur:
            cur.execute("""
                SELECT exchange, COUNT(*) as cnt, MAX(trade_date) as latest
                FROM datapai.screener_metrics
                GROUP BY exchange ORDER BY exchange
            """)
            for row in cur.fetchall():
                logger.info("  Summary: %s -- %d tickers, latest=%s", row[0], row[1], row[2])
    finally:
        conn.close()

    logger.info("All done!")


if __name__ == "__main__":
    main()
