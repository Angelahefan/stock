#!/usr/bin/env python3
"""
compute_fundamental_lite.py — Fast bulk fundamental fetcher for ALL tickers.

Uses yfinance only (no LLM calls). Fetches key valuation, profitability,
growth, and health metrics. Computes simple quality tiers.

Usage:
    python scripts/compute_fundamental_lite.py --exchange US
    python scripts/compute_fundamental_lite.py --exchange ASX
    python scripts/compute_fundamental_lite.py --exchange ALL
    python scripts/compute_fundamental_lite.py --exchange US --full-refresh

Runs weekly via cron. ~90 min for 8,500 tickers (yfinance rate limited).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import psycopg2
import psycopg2.extras

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def get_conn():
    return psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "postgres"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", ""),
    )


def get_yf_symbol(ticker: str, exchange: str) -> str:
    """Convert ticker to yfinance symbol (add .AX for ASX, .VN for HOSE, .HK for HKEX)."""
    from core.config.exchange_registry import registry
    return registry.get_yf_symbol(ticker, exchange)


def fetch_yf_info(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch key info from yfinance. Returns None on failure."""
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        info = t.info
        if not info or info.get("regularMarketPrice") is None:
            return None
        return info
    except Exception:
        return None


def safe_float(info: dict, key: str) -> Optional[float]:
    v = info.get(key)
    if v is None or v == "Infinity" or v == "-Infinity":
        return None
    try:
        f = float(v)
        if f != f:  # NaN check
            return None
        return f
    except (ValueError, TypeError):
        return None


def safe_int(info: dict, key: str) -> Optional[int]:
    v = info.get(key)
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def compute_quality_tier(row: Dict[str, Any]) -> str:
    """
    Simple rule-based quality tier:
      A = Profitable + Growing + Healthy financials
      B = Profitable + (Growing OR Healthy)
      C = At least one positive signal
      D = None of the above
    """
    score = 0
    # Profitability
    nm = row.get("net_margin")
    if nm is not None and nm > 0:
        score += 1
    if nm is not None and nm > 0.10:  # >10% margin = strong
        score += 1

    # Growth
    rev = row.get("revenue_yoy")
    if rev is not None and rev > 0:
        score += 1
    if rev is not None and rev > 0.15:  # >15% growth = strong
        score += 1

    # Financial health
    cr = row.get("current_ratio")
    de = row.get("debt_to_equity")
    if cr is not None and cr > 1.0:
        score += 1
    if de is not None and de < 2.0:
        score += 1

    # Cash flow
    fcf = row.get("free_cash_flow")
    if fcf is not None and fcf > 0:
        score += 1

    # ROE
    roe = row.get("roe")
    if roe is not None and roe > 0.10:
        score += 1

    if score >= 6:
        return "A"
    elif score >= 4:
        return "B"
    elif score >= 2:
        return "C"
    return "D"


def extract_fundamentals(info: Dict[str, Any], ticker: str, exchange: str) -> Dict[str, Any]:
    """Extract all fields from yfinance info dict."""
    row = {
        "ticker": ticker,
        "exchange": exchange,
        "company_name": info.get("shortName") or info.get("longName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": safe_int(info, "marketCap"),
        "pe_ratio": safe_float(info, "trailingPE"),
        "forward_pe": safe_float(info, "forwardPE"),
        "pb_ratio": safe_float(info, "priceToBook"),
        "ps_ratio": safe_float(info, "priceToSalesTrailing12Months"),
        "peg_ratio": safe_float(info, "pegRatio") or safe_float(info, "trailingPegRatio"),
        "ev_ebitda": safe_float(info, "enterpriseToEbitda"),
        "gross_margin": safe_float(info, "grossMargins"),
        "operating_margin": safe_float(info, "operatingMargins"),
        "net_margin": safe_float(info, "profitMargins"),
        "roe": safe_float(info, "returnOnEquity"),
        "roa": safe_float(info, "returnOnAssets"),
        "revenue_yoy": safe_float(info, "revenueGrowth"),
        "earnings_yoy": safe_float(info, "earningsGrowth"),
        "current_ratio": safe_float(info, "currentRatio"),
        "quick_ratio": safe_float(info, "quickRatio"),
        "debt_to_equity": safe_float(info, "debtToEquity"),
        "free_cash_flow": safe_int(info, "freeCashflow"),
        "operating_cash_flow": safe_int(info, "operatingCashflow"),
        "dividend_yield": safe_float(info, "dividendYield") or safe_float(info, "trailingAnnualDividendYield"),
        "payout_ratio": safe_float(info, "payoutRatio"),
        "beta": safe_float(info, "beta"),
        "short_ratio": safe_float(info, "shortRatio"),
        "analyst_target": safe_float(info, "targetMeanPrice"),
        "analyst_rating": info.get("recommendationKey"),
        "num_analysts": safe_int(info, "numberOfAnalystOpinions"),
    }

    # Computed flags
    row["is_profitable"] = row["net_margin"] is not None and row["net_margin"] > 0
    row["is_growing"] = row["revenue_yoy"] is not None and row["revenue_yoy"] > 0
    row["is_healthy"] = (
        (row["current_ratio"] is not None and row["current_ratio"] > 1.0)
        and (row["debt_to_equity"] is None or row["debt_to_equity"] < 300)  # yfinance reports D/E as percentage
    )
    row["quality_tier"] = compute_quality_tier(row)

    return row


UPSERT_SQL = """
INSERT INTO datapai.fundamental_lite (
    ticker, exchange, company_name, sector, industry,
    market_cap, pe_ratio, forward_pe, pb_ratio, ps_ratio, peg_ratio, ev_ebitda,
    gross_margin, operating_margin, net_margin, roe, roa,
    revenue_yoy, earnings_yoy,
    current_ratio, quick_ratio, debt_to_equity,
    free_cash_flow, operating_cash_flow,
    dividend_yield, payout_ratio,
    beta, short_ratio,
    analyst_target, analyst_rating, num_analysts,
    is_profitable, is_growing, is_healthy, quality_tier,
    fetched_at
) VALUES (
    %(ticker)s, %(exchange)s, %(company_name)s, %(sector)s, %(industry)s,
    %(market_cap)s, %(pe_ratio)s, %(forward_pe)s, %(pb_ratio)s, %(ps_ratio)s, %(peg_ratio)s, %(ev_ebitda)s,
    %(gross_margin)s, %(operating_margin)s, %(net_margin)s, %(roe)s, %(roa)s,
    %(revenue_yoy)s, %(earnings_yoy)s,
    %(current_ratio)s, %(quick_ratio)s, %(debt_to_equity)s,
    %(free_cash_flow)s, %(operating_cash_flow)s,
    %(dividend_yield)s, %(payout_ratio)s,
    %(beta)s, %(short_ratio)s,
    %(analyst_target)s, %(analyst_rating)s, %(num_analysts)s,
    %(is_profitable)s, %(is_growing)s, %(is_healthy)s, %(quality_tier)s,
    NOW()
)
ON CONFLICT (ticker, exchange)
DO UPDATE SET
    company_name = EXCLUDED.company_name,
    sector = EXCLUDED.sector,
    industry = EXCLUDED.industry,
    market_cap = EXCLUDED.market_cap,
    pe_ratio = EXCLUDED.pe_ratio,
    forward_pe = EXCLUDED.forward_pe,
    pb_ratio = EXCLUDED.pb_ratio,
    ps_ratio = EXCLUDED.ps_ratio,
    peg_ratio = EXCLUDED.peg_ratio,
    ev_ebitda = EXCLUDED.ev_ebitda,
    gross_margin = EXCLUDED.gross_margin,
    operating_margin = EXCLUDED.operating_margin,
    net_margin = EXCLUDED.net_margin,
    roe = EXCLUDED.roe,
    roa = EXCLUDED.roa,
    revenue_yoy = EXCLUDED.revenue_yoy,
    earnings_yoy = EXCLUDED.earnings_yoy,
    current_ratio = EXCLUDED.current_ratio,
    quick_ratio = EXCLUDED.quick_ratio,
    debt_to_equity = EXCLUDED.debt_to_equity,
    free_cash_flow = EXCLUDED.free_cash_flow,
    operating_cash_flow = EXCLUDED.operating_cash_flow,
    dividend_yield = EXCLUDED.dividend_yield,
    payout_ratio = EXCLUDED.payout_ratio,
    beta = EXCLUDED.beta,
    short_ratio = EXCLUDED.short_ratio,
    analyst_target = EXCLUDED.analyst_target,
    analyst_rating = EXCLUDED.analyst_rating,
    num_analysts = EXCLUDED.num_analysts,
    is_profitable = EXCLUDED.is_profitable,
    is_growing = EXCLUDED.is_growing,
    is_healthy = EXCLUDED.is_healthy,
    quality_tier = EXCLUDED.quality_tier,
    fetched_at = NOW()
"""


def run(exchange: str, full_refresh: bool = False, batch_size: int = 20):
    """Fetch fundamentals for PRIORITY tickers only (not all 8,500+)."""
    conn = get_conn()
    recency_hours = 168 if not full_refresh else 0  # 7 days cache

    # Get tickers from priority_tickers table (built by compute_priority_tickers.py)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (ticker) ticker, priority
            FROM datapai.priority_tickers
            WHERE exchange = %s
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY ticker, priority ASC
        """, (exchange,))
        rows = cur.fetchall()
        tickers = [r[0] for r in rows]
        priorities = {r[0]: r[1] for r in rows}

    if not tickers:
        log.warning("No priority tickers for %s — run compute_priority_tickers.py first!", exchange)
        log.info("Falling back to watchlist only...")
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT symbol FROM datapai.watchlist WHERE exchange = %s
            """, (exchange,))
            tickers = [r[0] for r in cur.fetchall()]
            priorities = {t: 1 for t in tickers}

    # Sort by priority (P1 first, so watchlist stocks always get fetched)
    tickers.sort(key=lambda t: priorities.get(t, 99))
    log.info("Found %d priority tickers for %s (P1=%d, P2=%d, P3=%d, P4=%d, P5=%d)",
             len(tickers), exchange,
             sum(1 for t in tickers if priorities.get(t) == 1),
             sum(1 for t in tickers if priorities.get(t) == 2),
             sum(1 for t in tickers if priorities.get(t) == 3),
             sum(1 for t in tickers if priorities.get(t) == 4),
             sum(1 for t in tickers if priorities.get(t) == 5))

    # Filter out recently fetched (unless full refresh)
    if recency_hours > 0:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ticker FROM datapai.fundamental_lite
                WHERE exchange = %s AND fetched_at > NOW() - INTERVAL '%s hours'
            """, (exchange, recency_hours))
            recent = {r[0] for r in cur.fetchall()}
        before = len(tickers)
        tickers = [t for t in tickers if t not in recent]
        log.info("Skipping %d recently fetched tickers, %d remaining", before - len(tickers), len(tickers))

    processed = 0
    errors = 0
    t0 = time.time()

    for i, ticker in enumerate(tickers, 1):
        symbol = get_yf_symbol(ticker, exchange)
        info = fetch_yf_info(symbol)

        if info is None:
            errors += 1
            if i % 100 == 0:
                log.info("[%d/%d] %s — no data (errors=%d)", i, len(tickers), ticker, errors)
            continue

        row = extract_fundamentals(info, ticker, exchange)

        try:
            with conn.cursor() as cur:
                cur.execute(UPSERT_SQL, row)
            conn.commit()
            processed += 1
        except Exception as e:
            conn.rollback()
            log.warning("[%d/%d] %s — DB error: %s", i, len(tickers), ticker, e)
            errors += 1
            continue

        if i % 50 == 0:
            elapsed = time.time() - t0
            rate = processed / elapsed * 60 if elapsed > 0 else 0
            eta = (len(tickers) - i) / (rate / 60) / 60 if rate > 0 else 0
            log.info(
                "[%d/%d] %s=%s  processed=%d errors=%d  (%.0f/min, ETA %.0fmin)",
                i, len(tickers), ticker, row["quality_tier"],
                processed, errors, rate, eta,
            )

        # Rate limit: ~0.3s between calls to avoid yfinance blocking
        time.sleep(0.3)

    elapsed = time.time() - t0
    log.info(
        "=== DONE %s: %d processed, %d errors, %d total in %.0fs ===",
        exchange, processed, errors, len(tickers), elapsed,
    )

    # Summary
    with conn.cursor() as cur:
        cur.execute("""
            SELECT quality_tier, COUNT(*)
            FROM datapai.fundamental_lite
            WHERE exchange = %s
            GROUP BY quality_tier ORDER BY quality_tier
        """, (exchange,))
        for tier, cnt in cur.fetchall():
            log.info("  Tier %s: %d tickers", tier, cnt)

    conn.close()
    return {"processed": processed, "errors": errors, "elapsed": elapsed}


def main():
    parser = argparse.ArgumentParser(description="Fetch lightweight fundamentals from yfinance")
    parser.add_argument("--exchange", default="ALL", help="US, ASX, or ALL")
    parser.add_argument("--full-refresh", action="store_true", help="Ignore 7-day cache")
    args = parser.parse_args()

    exchanges = ["US", "ASX", "HOSE"] if args.exchange.upper() == "ALL" else [args.exchange.upper()]
    for ex in exchanges:
        run(ex, full_refresh=args.full_refresh)


if __name__ == "__main__":
    main()
