"""
agents/fundamental
==================
Fundamental Analysis agent for stock scoring and macro-economic context.

Public API
----------
run_fundamental_pipeline(ticker, exchange, dry_run, llm, google_llm)
    → FundamentalResult

Individual agents
-----------------
fetch_fundamentals(ticker, exchange)      → dict         (fetcher)
score_valuation(data)                      → (score, detail)
score_quality(data)                        → (score, detail)
score_growth(data)                         → (score, detail)
fetch_macro_context(exchange, sector, llm) → MacroResult
fetch_analyst_consensus(ticker, ...)       → AnalystResult
classify_fundamental(val, qual, grow, mac) → (score, signal)
"""

from agents.fundamental.contracts import (
    ApiResponse,
    FundamentalPipelineRequest,
    FundamentalCompareRequest,
    FundamentalResult,
    ScreenerItem,
)
from agents.fundamental.fetcher import fetch_fundamentals
from agents.fundamental.valuation_agent import score_valuation
from agents.fundamental.quality_agent import score_quality
from agents.fundamental.growth_agent import score_growth
from agents.fundamental.macro_agent import fetch_macro_context, MacroResult
from agents.fundamental.analyst_agent import fetch_analyst_consensus, AnalystResult
from agents.fundamental.fundamental_classifier import classify_fundamental
from agents.fundamental.fundamental_pipeline import run_fundamental_pipeline

__all__ = [
    # contracts
    "ApiResponse",
    "FundamentalPipelineRequest",
    "FundamentalCompareRequest",
    "FundamentalResult",
    "ScreenerItem",
    # agents
    "fetch_fundamentals",
    "score_valuation",
    "score_quality",
    "score_growth",
    "fetch_macro_context",
    "MacroResult",
    "fetch_analyst_consensus",
    "AnalystResult",
    "classify_fundamental",
    "run_fundamental_pipeline",
]
