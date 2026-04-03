"""
agents/fundamental/contracts.py
================================
Pydantic request/response models for the Fundamental Analysis agent.
All API endpoints use the shared ApiResponse envelope:
    {"ok": bool, "data": {...} | None, "error": {"message": str} | None}
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared envelope (mirrors tinyfish_api.py pattern)
# ---------------------------------------------------------------------------

class ApiError(BaseModel):
    message: str
    code: Optional[str] = None


class ApiResponse(BaseModel):
    ok: bool
    data: Optional[Any] = None
    error: Optional[ApiError] = None

    @classmethod
    def success(cls, data: Any) -> "ApiResponse":
        return cls(ok=True, data=data)

    @classmethod
    def failure(cls, message: str, code: Optional[str] = None) -> "ApiResponse":
        return cls(ok=False, error=ApiError(message=message, code=code))


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class FundamentalPipelineRequest(BaseModel):
    ticker: str = Field(..., description="Stock ticker symbol, e.g. AAPL")
    exchange: str = Field(..., description="Exchange: US or ASX")
    dry_run: bool = Field(False, description="If true, skip DB writes")


class FundamentalCompareRequest(BaseModel):
    tickers: List[str] = Field(..., min_items=2, max_items=5,
                               description="2-5 ticker symbols to compare")
    exchange: str = Field(..., description="Exchange: US or ASX")


# ---------------------------------------------------------------------------
# Score sub-models
# ---------------------------------------------------------------------------

class ValuationDetail(BaseModel):
    pe_score: Optional[float] = None
    ev_ebitda_score: Optional[float] = None
    pb_score: Optional[float] = None
    peg_score: Optional[float] = None
    fcf_yield_score: Optional[float] = None
    sector_pe_median: Optional[float] = None


class QualityDetail(BaseModel):
    roe_score: Optional[float] = None
    net_margin_score: Optional[float] = None
    gross_margin_score: Optional[float] = None
    debt_score: Optional[float] = None
    current_ratio_score: Optional[float] = None
    interest_coverage_score: Optional[float] = None


class GrowthDetail(BaseModel):
    revenue_yoy_score: Optional[float] = None
    eps_yoy_score: Optional[float] = None
    fcf_trend_score: Optional[float] = None
    cagr_score: Optional[float] = None


class MacroDetail(BaseModel):
    macro_score: float = 0.0
    macro_summary: Optional[str] = None
    macro_factors: List[str] = Field(default_factory=list)
    geopolitical_flags: List[str] = Field(default_factory=list)
    tech_disruption_risk: str = "UNKNOWN"
    cached: bool = False


class AnalystDetail(BaseModel):
    consensus: Optional[str] = None          # STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL
    target_price: Optional[float] = None
    upside_pct: Optional[float] = None
    num_analysts: Optional[int] = None
    sources: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Main result model
# ---------------------------------------------------------------------------

class FundamentalResult(BaseModel):
    # identity
    ticker: str
    exchange: str
    company_name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    currency: Optional[str] = None

    # size
    market_cap: Optional[int] = None
    enterprise_value: Optional[int] = None

    # valuation
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    ps_ratio: Optional[float] = None
    ev_ebitda: Optional[float] = None
    ev_revenue: Optional[float] = None

    # profitability
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    roic: Optional[float] = None

    # growth
    revenue_yoy: Optional[float] = None
    earnings_yoy: Optional[float] = None
    revenue_growth_5yr: Optional[float] = None
    eps_growth_5yr: Optional[float] = None

    # financial health
    current_ratio: Optional[float] = None
    quick_ratio: Optional[float] = None
    debt_to_equity: Optional[float] = None
    interest_coverage: Optional[float] = None
    total_cash: Optional[int] = None
    total_debt: Optional[int] = None
    net_cash: Optional[int] = None

    # cash flow
    free_cash_flow: Optional[int] = None
    fcf_per_share: Optional[float] = None
    fcf_yield: Optional[float] = None
    operating_cf_margin: Optional[float] = None

    # dividend
    dividend_yield: Optional[float] = None
    payout_ratio: Optional[float] = None

    # market / risk
    beta: Optional[float] = None
    short_ratio: Optional[float] = None
    next_earnings_date: Optional[date] = None

    # scores
    valuation_score: Optional[float] = None
    quality_score: Optional[float] = None
    growth_score: Optional[float] = None
    macro_score: Optional[float] = None
    fundamental_score: Optional[float] = None
    fundamental_signal: Optional[str] = None   # STRONG_BUY / BUY / NEUTRAL / SELL / STRONG_SELL

    # score detail breakdowns
    valuation_detail: Optional[ValuationDetail] = None
    quality_detail: Optional[QualityDetail] = None
    growth_detail: Optional[GrowthDetail] = None
    macro_detail: Optional[MacroDetail] = None
    analyst_detail: Optional[AnalystDetail] = None

    # analyst consensus
    analyst_consensus: Optional[str] = None
    analyst_target_price: Optional[float] = None
    analyst_upside_pct: Optional[float] = None

    # macro context
    macro_summary: Optional[str] = None
    macro_factors: List[str] = Field(default_factory=list)
    geopolitical_flags: List[str] = Field(default_factory=list)
    tech_disruption_risk: Optional[str] = None

    # LLM narrative
    fundamental_summary: Optional[str] = None
    key_strengths: List[str] = Field(default_factory=list)
    key_risks: List[str] = Field(default_factory=list)

    # metadata
    source: str = "yfinance"
    computed_at: Optional[datetime] = None
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Screener response item
# ---------------------------------------------------------------------------

class ScreenerItem(BaseModel):
    ticker: str
    exchange: str
    company_name: Optional[str] = None
    sector: Optional[str] = None
    fundamental_signal: Optional[str] = None
    fundamental_score: Optional[float] = None
    valuation_score: Optional[float] = None
    quality_score: Optional[float] = None
    growth_score: Optional[float] = None
    macro_score: Optional[float] = None
    analyst_consensus: Optional[str] = None
    analyst_upside_pct: Optional[float] = None
    tech_disruption_risk: Optional[str] = None
    computed_at: Optional[datetime] = None
