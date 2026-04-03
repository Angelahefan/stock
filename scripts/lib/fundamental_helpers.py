"""
scripts/lib/fundamental_helpers.py
====================================
Database helpers for the Fundamental Analysis pipeline.

Public API
----------
upsert_fundamental_snapshot(result: FundamentalResult) -> None
upsert_fundamental_history(ticker, exchange, history) -> None
get_fundamental_snapshot(ticker, exchange) -> dict | None
screener_query(exchange, signal, sector, min_score, limit) -> list[dict]
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from psycopg2.extras import execute_values

log = logging.getLogger(__name__)

_BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# Upsert fundamental_snapshot
# ---------------------------------------------------------------------------

_UPSERT_SNAPSHOT = """
INSERT INTO datapai.fundamental_snapshot (
    ticker, exchange, company_name, sector, industry, currency,
    market_cap, enterprise_value,
    pe_ratio, forward_pe, peg_ratio, pb_ratio, ps_ratio, ev_ebitda, ev_revenue,
    gross_margin, operating_margin, net_margin, roe, roa, roic,
    revenue_yoy, earnings_yoy, revenue_growth_5yr, eps_growth_5yr,
    current_ratio, quick_ratio, debt_to_equity, interest_coverage,
    total_cash, total_debt, net_cash,
    free_cash_flow, fcf_per_share, fcf_yield, operating_cf_margin,
    dividend_yield, payout_ratio,
    beta, short_ratio, next_earnings_date,
    valuation_score, quality_score, growth_score, macro_score,
    fundamental_score, fundamental_signal,
    analyst_consensus, analyst_target_price, analyst_upside_pct,
    macro_summary, macro_factors, geopolitical_flags, tech_disruption_risk,
    fundamental_summary, key_strengths, key_risks,
    source, computed_at
) VALUES %s
ON CONFLICT (ticker, exchange) DO UPDATE SET
    company_name        = EXCLUDED.company_name,
    sector              = EXCLUDED.sector,
    industry            = EXCLUDED.industry,
    currency            = EXCLUDED.currency,
    market_cap          = EXCLUDED.market_cap,
    enterprise_value    = EXCLUDED.enterprise_value,
    pe_ratio            = EXCLUDED.pe_ratio,
    forward_pe          = EXCLUDED.forward_pe,
    peg_ratio           = EXCLUDED.peg_ratio,
    pb_ratio            = EXCLUDED.pb_ratio,
    ps_ratio            = EXCLUDED.ps_ratio,
    ev_ebitda           = EXCLUDED.ev_ebitda,
    ev_revenue          = EXCLUDED.ev_revenue,
    gross_margin        = EXCLUDED.gross_margin,
    operating_margin    = EXCLUDED.operating_margin,
    net_margin          = EXCLUDED.net_margin,
    roe                 = EXCLUDED.roe,
    roa                 = EXCLUDED.roa,
    roic                = EXCLUDED.roic,
    revenue_yoy         = EXCLUDED.revenue_yoy,
    earnings_yoy        = EXCLUDED.earnings_yoy,
    revenue_growth_5yr  = EXCLUDED.revenue_growth_5yr,
    eps_growth_5yr      = EXCLUDED.eps_growth_5yr,
    current_ratio       = EXCLUDED.current_ratio,
    quick_ratio         = EXCLUDED.quick_ratio,
    debt_to_equity      = EXCLUDED.debt_to_equity,
    interest_coverage   = EXCLUDED.interest_coverage,
    total_cash          = EXCLUDED.total_cash,
    total_debt          = EXCLUDED.total_debt,
    net_cash            = EXCLUDED.net_cash,
    free_cash_flow      = EXCLUDED.free_cash_flow,
    fcf_per_share       = EXCLUDED.fcf_per_share,
    fcf_yield           = EXCLUDED.fcf_yield,
    operating_cf_margin = EXCLUDED.operating_cf_margin,
    dividend_yield      = EXCLUDED.dividend_yield,
    payout_ratio        = EXCLUDED.payout_ratio,
    beta                = EXCLUDED.beta,
    short_ratio         = EXCLUDED.short_ratio,
    next_earnings_date  = EXCLUDED.next_earnings_date,
    valuation_score     = EXCLUDED.valuation_score,
    quality_score       = EXCLUDED.quality_score,
    growth_score        = EXCLUDED.growth_score,
    macro_score         = EXCLUDED.macro_score,
    fundamental_score   = EXCLUDED.fundamental_score,
    fundamental_signal  = EXCLUDED.fundamental_signal,
    analyst_consensus   = EXCLUDED.analyst_consensus,
    analyst_target_price= EXCLUDED.analyst_target_price,
    analyst_upside_pct  = EXCLUDED.analyst_upside_pct,
    macro_summary       = EXCLUDED.macro_summary,
    macro_factors       = EXCLUDED.macro_factors,
    geopolitical_flags  = EXCLUDED.geopolitical_flags,
    tech_disruption_risk= EXCLUDED.tech_disruption_risk,
    fundamental_summary = EXCLUDED.fundamental_summary,
    key_strengths       = EXCLUDED.key_strengths,
    key_risks           = EXCLUDED.key_risks,
    source              = EXCLUDED.source,
    computed_at         = EXCLUDED.computed_at
"""


def _result_to_row(result) -> tuple:
    """Convert FundamentalResult to a DB row tuple matching _UPSERT_SNAPSHOT columns."""
    return (
        result.ticker,
        result.exchange,
        result.company_name,
        result.sector,
        result.industry,
        result.currency,
        result.market_cap,
        result.enterprise_value,
        result.pe_ratio,
        result.forward_pe,
        result.peg_ratio,
        result.pb_ratio,
        result.ps_ratio,
        result.ev_ebitda,
        result.ev_revenue,
        result.gross_margin,
        result.operating_margin,
        result.net_margin,
        result.roe,
        result.roa,
        result.roic,
        result.revenue_yoy,
        result.earnings_yoy,
        result.revenue_growth_5yr,
        result.eps_growth_5yr,
        result.current_ratio,
        result.quick_ratio,
        result.debt_to_equity,
        result.interest_coverage,
        result.total_cash,
        result.total_debt,
        result.net_cash,
        result.free_cash_flow,
        result.fcf_per_share,
        result.fcf_yield,
        result.operating_cf_margin,
        result.dividend_yield,
        result.payout_ratio,
        result.beta,
        result.short_ratio,
        result.next_earnings_date,
        result.valuation_score,
        result.quality_score,
        result.growth_score,
        result.macro_score,
        result.fundamental_score,
        result.fundamental_signal,
        result.analyst_consensus,
        result.analyst_target_price,
        result.analyst_upside_pct,
        result.macro_summary,
        result.macro_factors or [],
        result.geopolitical_flags or [],
        result.tech_disruption_risk,
        result.fundamental_summary,
        result.key_strengths or [],
        result.key_risks or [],
        result.source or "yfinance",
        result.computed_at or datetime.utcnow(),
    )


def upsert_fundamental_snapshot(result) -> None:
    """
    Upsert a single FundamentalResult into datapai.fundamental_snapshot.

    Parameters
    ----------
    result : FundamentalResult
    """
    from scripts.lib.db_helpers import get_conn

    row = _result_to_row(result)
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, _UPSERT_SNAPSHOT, [row])
    log.debug("upserted fundamental_snapshot for %s/%s", result.ticker, result.exchange)


# ---------------------------------------------------------------------------
# Upsert fundamental_history
# ---------------------------------------------------------------------------

_UPSERT_HISTORY = """
INSERT INTO datapai.fundamental_history (
    ticker, exchange, period_end, period_type,
    revenue, gross_profit, operating_income, net_income, ebitda, eps,
    free_cash_flow, operating_cash_flow, capex,
    total_assets, total_debt, shareholders_equity, cash_and_equivalents,
    revenue_yoy, earnings_yoy, fcf_yoy,
    source, computed_at
) VALUES %s
ON CONFLICT (ticker, exchange, period_end, period_type) DO UPDATE SET
    revenue             = EXCLUDED.revenue,
    gross_profit        = EXCLUDED.gross_profit,
    operating_income    = EXCLUDED.operating_income,
    net_income          = EXCLUDED.net_income,
    ebitda              = EXCLUDED.ebitda,
    eps                 = EXCLUDED.eps,
    free_cash_flow      = EXCLUDED.free_cash_flow,
    operating_cash_flow = EXCLUDED.operating_cash_flow,
    capex               = EXCLUDED.capex,
    total_assets        = EXCLUDED.total_assets,
    total_debt          = EXCLUDED.total_debt,
    shareholders_equity = EXCLUDED.shareholders_equity,
    cash_and_equivalents= EXCLUDED.cash_and_equivalents,
    revenue_yoy         = EXCLUDED.revenue_yoy,
    earnings_yoy        = EXCLUDED.earnings_yoy,
    fcf_yoy             = EXCLUDED.fcf_yoy,
    source              = EXCLUDED.source,
    computed_at         = EXCLUDED.computed_at
"""


def upsert_fundamental_history(ticker: str, exchange: str, history: list) -> None:
    """
    Upsert historical financial records into datapai.fundamental_history.

    Parameters
    ----------
    ticker   : str
    exchange : str
    history  : list of period dicts from fetcher._parse_history()
    """
    if not history:
        return

    from scripts.lib.db_helpers import get_conn

    now = datetime.utcnow()
    rows = []
    for p in history:
        rows.append((
            ticker.upper(),
            exchange.upper(),
            p.get("period_end"),
            p.get("period_type"),
            p.get("revenue"),
            p.get("gross_profit"),
            p.get("operating_income"),
            p.get("net_income"),
            p.get("ebitda"),
            p.get("eps"),
            p.get("free_cash_flow"),
            p.get("operating_cash_flow"),
            p.get("capex"),
            p.get("total_assets"),
            p.get("total_debt"),
            p.get("shareholders_equity"),
            p.get("cash_and_equivalents"),
            p.get("revenue_yoy"),
            p.get("earnings_yoy"),
            p.get("fcf_yoy"),
            "yfinance",
            now,
        ))

    with get_conn() as conn:
        with conn.cursor() as cur:
            for i in range(0, len(rows), _BATCH_SIZE):
                execute_values(cur, _UPSERT_HISTORY, rows[i:i + _BATCH_SIZE])
    log.debug("upserted %d history rows for %s/%s", len(rows), ticker, exchange)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_fundamental_snapshot(ticker: str, exchange: str) -> Optional[dict]:
    """
    Read the latest fundamental snapshot from DB.
    Returns dict or None if not found.
    """
    from scripts.lib.db_helpers import get_conn

    sql = """
        SELECT * FROM datapai.fundamental_snapshot
        WHERE ticker = %s AND exchange = %s
        LIMIT 1
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), exchange.upper()))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


def screener_query(
    exchange: str,
    signal: Optional[str] = None,
    sector: Optional[str] = None,
    min_score: Optional[float] = None,
    max_tech_risk: Optional[str] = None,
    limit: int = 50,
) -> List[dict]:
    """
    Query the screener index for fundamental_snapshot rows.

    Parameters
    ----------
    exchange      : "US" or "ASX"
    signal        : optional filter e.g. "BUY", "STRONG_BUY"
    sector        : optional sector filter
    min_score     : optional minimum fundamental_score
    max_tech_risk : optional max tech disruption risk ("LOW", "MEDIUM", "HIGH")
    limit         : max rows returned (default 50)

    Returns list of dicts.
    """
    from scripts.lib.db_helpers import get_conn

    conditions = ["exchange = %s"]
    params: list = [exchange.upper()]

    if signal:
        conditions.append("fundamental_signal = %s")
        params.append(signal.upper())
    if sector:
        conditions.append("sector = %s")
        params.append(sector)
    if min_score is not None:
        conditions.append("fundamental_score >= %s")
        params.append(min_score)
    if max_tech_risk:
        risk_order = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
        allowed = [k for k, v in risk_order.items() if v <= risk_order.get(max_tech_risk.upper(), 99)]
        if allowed:
            placeholders = ",".join(["%s"] * len(allowed))
            conditions.append(f"tech_disruption_risk IN ({placeholders})")
            params.extend(allowed)

    where = " AND ".join(conditions)
    params.append(limit)

    sql = f"""
        SELECT ticker, exchange, company_name, sector,
               fundamental_signal, fundamental_score,
               valuation_score, quality_score, growth_score, macro_score,
               analyst_consensus, analyst_upside_pct, tech_disruption_risk,
               computed_at
        FROM datapai.fundamental_snapshot
        WHERE {where}
        ORDER BY fundamental_score DESC
        LIMIT %s
    """

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in rows]
