"""
agents/fundamental/macro_agent.py
===================================
Scores macro-economic and geopolitical context for a given exchange + sector
using Gemini grounding (real-time Google Search).

Data sourced from: Reuters, Bloomberg, FT, WSJ, IMF, World Bank,
Federal Reserve, RBA, ECB, OECD, and major financial news outlets.

Performance: results are cached in-memory per (exchange, sector) pair for
_CACHE_TTL seconds (24 h by default) so the expensive Gemini grounding call
is made at most once per sector per batch run.

Public API
----------
fetch_macro_context(exchange, sector, llm) -> MacroResult
    Returns MacroResult dataclass. Never raises — returns neutral defaults
    on any failure.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_CACHE_TTL: float = 86_400.0   # 24 hours

# In-process cache: keyed by (exchange, sector)
_MACRO_CACHE: dict[tuple, "MacroResult"] = {}
_MACRO_CACHE_TS: dict[tuple, float] = {}


# ---------------------------------------------------------------------------
# Market Regime
# ---------------------------------------------------------------------------

class MarketRegime(str, Enum):
    """Market regime classification for regime-aware agent weighting."""
    BULL_MOMENTUM = "BULL_MOMENTUM"
    BEAR_RECESSION = "BEAR_RECESSION"
    NEUTRAL_TRANSITION = "NEUTRAL_TRANSITION"


# Agent weight keys — map to existing signal sources
_REGIME_WEIGHTS: Dict[MarketRegime, Dict[str, float]] = {
    MarketRegime.BULL_MOMENTUM: {
        "TECHNICAL": 0.35,
        "SENTIMENT": 0.35,   # maps to NEWS agent
        "FUNDAMENTAL": 0.20,
        "MACRO": 0.10,
    },
    MarketRegime.BEAR_RECESSION: {
        "FUNDAMENTAL": 0.35,
        "MACRO": 0.35,
        "TECHNICAL": 0.20,
        "SENTIMENT": 0.10,
    },
    MarketRegime.NEUTRAL_TRANSITION: {
        "TECHNICAL": 0.25,
        "FUNDAMENTAL": 0.25,
        "MACRO": 0.25,
        "SENTIMENT": 0.25,
    },
}


@dataclass
class MacroResult:
    macro_score: float = 0.0            # -1.0 (very negative) to +1.0 (very positive)
    macro_summary: str = ""
    macro_factors: List[str] = field(default_factory=list)
    geopolitical_flags: List[str] = field(default_factory=list)
    tech_disruption_risk: str = "UNKNOWN"   # LOW / MEDIUM / HIGH
    cached: bool = False
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a macro-economic analyst. Assess the current macro environment and \
geopolitical context for the specified exchange and sector. \
Use ONLY authoritative sources: Reuters, Bloomberg, Financial Times, Wall Street Journal, \
IMF World Economic Outlook, World Bank, Federal Reserve, RBA, ECB, OECD economic reports. \
Be factual and current. No investment advice."""

_USER_PROMPT_TEMPLATE = """\
Analyse the current macro-economic and geopolitical environment for \
{sector} sector stocks on the {exchange} exchange ({region}).

Cover ALL of the following:
1. Central bank policy — interest rate trajectory (Fed/RBA/ECB), monetary tightening/easing cycle
2. Inflation & GDP — current inflation trend, GDP growth outlook (IMF/World Bank forecasts)
3. Trade & tariffs — US-China trade policy, tariffs affecting this sector, WTO developments
4. Geopolitical risks — Middle East conflicts (energy/shipping impact), Russia-Ukraine (commodities), \
   Taiwan strait (semiconductors), geographic risks relevant to this sector
5. AI & technology revolution — AI adoption tailwinds/headwinds for this sector, \
   automation disruption risk, technology capex cycle
6. Sector-specific policy — regulation (antitrust, capital requirements, carbon pricing, data privacy laws)
7. Currency & global trade — USD strength, EM risks, global supply chain status

Return a JSON object ONLY (no markdown, no extra text):
{{
  "macro_score": <float from -1.0 to +1.0, where +1 = very positive macro for this sector>,
  "macro_summary": "<2-3 sentence summary of the key macro backdrop>",
  "macro_factors": [
    "<tailwind or headwind 1>",
    "<tailwind or headwind 2>",
    "<tailwind or headwind 3>",
    "<tailwind or headwind 4 (optional)>",
    "<tailwind or headwind 5 (optional)>"
  ],
  "geopolitical_flags": [
    "<specific geopolitical risk 1>",
    "<specific geopolitical risk 2>"
  ],
  "tech_disruption_risk": "<LOW|MEDIUM|HIGH>"
}}

Scoring guidance for macro_score:
  +0.8 to +1.0 : Very positive — strong tailwinds (rate cuts, fiscal stimulus, sector boom)
  +0.3 to +0.7 : Moderately positive — net tailwinds outweigh risks
   0.0          : Neutral — roughly balanced
  -0.3 to -0.1 : Moderately negative — headwinds outweigh tailwinds
  -0.8 to -0.4 : Very negative — significant structural or cyclical risks
"""

_EXCHANGE_REGION: dict[str, str] = {
    "US":  "United States / North America",
    "ASX": "Australia / Asia-Pacific",
}


def _build_prompt(exchange: str, sector: str) -> str:
    region = _EXCHANGE_REGION.get(exchange.upper(), exchange)
    return _USER_PROMPT_TEMPLATE.format(
        sector=sector or "General",
        exchange=exchange.upper(),
        region=region,
    )


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Extract the first JSON object from Gemini's response."""
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip markdown fences
    text_clean = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
    try:
        return json.loads(text_clean)
    except json.JSONDecodeError:
        pass
    # Find first {...} block
    m = re.search(r"\{[\s\S]+\}", text_clean)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


# ---------------------------------------------------------------------------
# Main grounding call
# ---------------------------------------------------------------------------

def _call_gemini_grounding(exchange: str, sector: str, llm) -> MacroResult:
    """Make a single Gemini grounding call and parse the result."""
    from agents.llm_client import GoogleChatClient

    prompt = _build_prompt(exchange, sector)

    # Prefer a GoogleChatClient directly for grounding
    try:
        if not isinstance(llm, GoogleChatClient):
            google_llm = GoogleChatClient()
        else:
            google_llm = llm
    except Exception as exc:
        log.warning("macro_agent: cannot build GoogleChatClient: %s", exc)
        return MacroResult(error=str(exc))

    try:
        resp = google_llm.chat(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.1,
            grounding=True,
        )
    except Exception as exc:
        log.warning("macro_agent: Gemini grounding call failed (%s): %s",
                    f"{exchange}/{sector}", exc)
        return MacroResult(error=str(exc))

    raw = resp.get("content", "") if isinstance(resp, dict) else str(resp)
    if not raw:
        return MacroResult(error="empty response from Gemini")

    parsed = _extract_json(raw)
    if not parsed:
        log.warning("macro_agent: could not parse JSON from response for %s/%s", exchange, sector)
        return MacroResult(error="JSON parse failed", macro_summary=raw[:300])

    # Build result
    macro_score = float(parsed.get("macro_score", 0.0))
    macro_score = max(-1.0, min(1.0, macro_score))   # clamp

    return MacroResult(
        macro_score=macro_score,
        macro_summary=parsed.get("macro_summary", ""),
        macro_factors=parsed.get("macro_factors", []),
        geopolitical_flags=parsed.get("geopolitical_flags", []),
        tech_disruption_risk=parsed.get("tech_disruption_risk", "UNKNOWN").upper(),
    )


# ---------------------------------------------------------------------------
# Public entry point (with caching)
# ---------------------------------------------------------------------------

def fetch_macro_context(exchange: str, sector: str, llm=None) -> MacroResult:
    """
    Fetch macro + geopolitical context for the given exchange/sector.

    Results are cached in-process for _CACHE_TTL seconds so that a batch
    run over 500 tickers in 10 sectors triggers ~10 Gemini calls, not 500.

    Parameters
    ----------
    exchange : str  ("US" or "ASX")
    sector   : str  yfinance sector label, e.g. "Technology"
    llm      : optional LLM client; if None, a GoogleChatClient is created

    Returns
    -------
    MacroResult — never raises
    """
    key = (exchange.upper(), sector or "Unknown")
    now = time.time()

    # Cache hit
    if key in _MACRO_CACHE and (now - _MACRO_CACHE_TS.get(key, 0)) < _CACHE_TTL:
        cached = _MACRO_CACHE[key]
        return MacroResult(
            macro_score=cached.macro_score,
            macro_summary=cached.macro_summary,
            macro_factors=cached.macro_factors,
            geopolitical_flags=cached.geopolitical_flags,
            tech_disruption_risk=cached.tech_disruption_risk,
            cached=True,
        )

    log.info("macro_agent: fetching live macro context for %s / %s", exchange, sector)
    result = _call_gemini_grounding(exchange, sector, llm)

    if result.error is None:
        _MACRO_CACHE[key] = result
        _MACRO_CACHE_TS[key] = now
    else:
        # Still cache the error result briefly (5 min) to avoid hammering API on failures
        _MACRO_CACHE[key] = result
        _MACRO_CACHE_TS[key] = now - _CACHE_TTL + 300

    return result


def clear_cache() -> None:
    """Clear the in-process macro cache (useful for testing)."""
    _MACRO_CACHE.clear()
    _MACRO_CACHE_TS.clear()


# ---------------------------------------------------------------------------
# Regime Classification (v2 — Investment Committee pattern)
# ---------------------------------------------------------------------------

def classify_regime(macro: MacroResult) -> MarketRegime:
    """
    Classify the market regime from a MacroResult.

    Rules:
      BULL_MOMENTUM  — macro_score > 0.3, fewer than 2 geopolitical flags
      BEAR_RECESSION — macro_score < -0.3 OR 3+ geopolitical flags
      NEUTRAL        — everything else
    """
    critical_geo = len(macro.geopolitical_flags) >= 3

    if macro.macro_score < -0.3 or critical_geo:
        return MarketRegime.BEAR_RECESSION
    if macro.macro_score > 0.3 and len(macro.geopolitical_flags) < 2:
        return MarketRegime.BULL_MOMENTUM
    return MarketRegime.NEUTRAL_TRANSITION


def get_regime_weights(regime: MarketRegime) -> Dict[str, float]:
    """
    Get agent weights for the given market regime.

    Returns dict with keys: TECHNICAL, SENTIMENT, FUNDAMENTAL, MACRO
    summing to 1.0.
    """
    return dict(_REGIME_WEIGHTS[regime])


def classify_regime_from_ta(
    sma_50: Optional[float],
    sma_200: Optional[float],
    rsi_14: Optional[float] = None,
    volatility_20d: Optional[float] = None,
) -> MarketRegime:
    """
    Historical regime proxy using TA indicators (for backtesting).

    Since we can't call Gemini for historical macro context, this uses
    SMA50/200 golden/death cross as a regime proxy:
      - Golden cross (SMA50 > SMA200) + RSI < 70 → BULL_MOMENTUM
      - Death cross (SMA50 < SMA200) + high vol   → BEAR_RECESSION
      - Otherwise                                  → NEUTRAL_TRANSITION
    """
    if sma_50 is None or sma_200 is None:
        return MarketRegime.NEUTRAL_TRANSITION

    golden_cross = sma_50 > sma_200
    death_cross = sma_50 < sma_200
    high_vol = volatility_20d is not None and volatility_20d > 0.30

    if death_cross and high_vol:
        return MarketRegime.BEAR_RECESSION
    if golden_cross:
        if rsi_14 is not None and rsi_14 > 75:
            # Overheated bull — treat as neutral
            return MarketRegime.NEUTRAL_TRANSITION
        return MarketRegime.BULL_MOMENTUM
    return MarketRegime.NEUTRAL_TRANSITION
