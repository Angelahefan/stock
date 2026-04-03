"""
agents/fundamental/analyst_agent.py
=====================================
Fetches Wall Street / analyst consensus data using Gemini grounding
(real-time Google Search).

Sourced from: Bloomberg, Reuters, Refinitiv, FactSet, Visible Alpha,
Seeking Alpha, MarketBeat, and major brokerage research summaries.

Public API
----------
fetch_analyst_consensus(ticker, exchange, company_name, llm) -> AnalystResult
    Returns AnalystResult dataclass. Never raises.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

log = logging.getLogger(__name__)


@dataclass
class AnalystResult:
    consensus: Optional[str] = None      # STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL
    target_price: Optional[float] = None
    upside_pct: Optional[float] = None
    num_analysts: Optional[int] = None
    sources: List[str] = field(default_factory=list)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a financial research assistant summarising analyst consensus data. \
Use real-time Google Search. Source only from: Bloomberg, Reuters, Refinitiv, \
FactSet, Seeking Alpha, MarketBeat, TipRanks, or official brokerage summaries. \
Return factual data only. No investment advice."""

_USER_PROMPT_TEMPLATE = """\
Find the current Wall Street analyst consensus for {ticker_display}.

Return a JSON object ONLY (no markdown fences, no extra text):
{{
  "consensus": "<STRONG_BUY|BUY|HOLD|SELL|STRONG_SELL>",
  "target_price": <average analyst price target as a number, or null>,
  "upside_pct": <percentage upside to consensus target vs current price, as decimal e.g. 0.15 for 15%, or null>,
  "num_analysts": <number of analysts covering this stock, or null>,
  "sources": ["<source 1>", "<source 2>"]
}}

If no reliable analyst data is available, return:
{{"consensus": null, "target_price": null, "upside_pct": null, "num_analysts": null, "sources": []}}
"""

_EXCHANGE_SUFFIX_DISPLAY: dict[str, str] = {
    "US":  "",
    "ASX": " (ASX-listed)",
}


def _build_prompt(ticker: str, exchange: str, company_name: Optional[str]) -> str:
    suffix = _EXCHANGE_SUFFIX_DISPLAY.get(exchange.upper(), "")
    name_str = f" ({company_name})" if company_name else ""
    ticker_display = f"{ticker.upper()}{suffix}{name_str}"
    return _USER_PROMPT_TEMPLATE.format(ticker_display=ticker_display)


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    text_clean = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
    try:
        return json.loads(text_clean)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]+\}", text_clean)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


_VALID_CONSENSUS = {"STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"}


def _normalise_consensus(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    upper = raw.upper().replace(" ", "_").replace("-", "_")
    # Common aliases
    aliases = {
        "OUTPERFORM": "BUY",
        "OVERWEIGHT":  "BUY",
        "ACCUMULATE":  "BUY",
        "MARKET_OUTPERFORM": "BUY",
        "UNDERPERFORM":  "SELL",
        "UNDERWEIGHT":   "SELL",
        "MARKET_UNDERPERFORM": "SELL",
        "NEUTRAL":       "HOLD",
        "MARKET_PERFORM": "HOLD",
        "EQUAL_WEIGHT":  "HOLD",
        "SECTOR_PERFORM": "HOLD",
    }
    return aliases.get(upper, upper) if upper not in _VALID_CONSENSUS else upper


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fetch_analyst_consensus(
    ticker: str,
    exchange: str,
    company_name: Optional[str] = None,
    llm=None,
) -> AnalystResult:
    """
    Fetch analyst consensus via Gemini grounding.

    Parameters
    ----------
    ticker       : str
    exchange     : str ("US" or "ASX")
    company_name : str, optional
    llm          : optional LLM client (RouterChatClient or GoogleChatClient)

    Returns
    -------
    AnalystResult — never raises
    """
    from agents.llm_client import GoogleChatClient

    try:
        if not isinstance(llm, GoogleChatClient):
            google_llm = GoogleChatClient()
        else:
            google_llm = llm
    except Exception as exc:
        log.warning("analyst_agent: cannot build GoogleChatClient: %s", exc)
        return AnalystResult(error=str(exc))

    prompt = _build_prompt(ticker, exchange, company_name)

    try:
        resp = google_llm.chat(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.0,
            grounding=True,
        )
    except Exception as exc:
        log.warning("analyst_agent: grounding call failed for %s: %s", ticker, exc)
        return AnalystResult(error=str(exc))

    raw = resp.get("content", "") if isinstance(resp, dict) else str(resp)
    if not raw:
        return AnalystResult(error="empty response")

    parsed = _extract_json(raw)
    if not parsed:
        log.warning("analyst_agent: JSON parse failed for %s", ticker)
        return AnalystResult(error="JSON parse failed")

    # Pull grounding sources if available
    sources = [s.get("title", s.get("uri", "")) for s in resp.get("grounding_sources", [])]
    if not sources:
        sources = list(parsed.get("sources", []))

    return AnalystResult(
        consensus=_normalise_consensus(parsed.get("consensus")),
        target_price=_safe_float(parsed.get("target_price")),
        upside_pct=_safe_float(parsed.get("upside_pct")),
        num_analysts=_safe_int(parsed.get("num_analysts")),
        sources=sources[:5],
    )


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None
