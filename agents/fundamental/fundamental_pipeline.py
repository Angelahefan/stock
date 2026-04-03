"""
agents/fundamental/fundamental_pipeline.py
===========================================
10-step orchestration pipeline for the Fundamental Analysis agent.

Steps
-----
 1. fetch_fundamentals()        — yfinance data fetch
 2. score_valuation()           — valuation score
 3. score_quality()             — quality/moat score
 4. score_growth()              — growth score
 5. fetch_macro_context()       — macro + geopolitical score (cached per sector)
 6. fetch_analyst_consensus()   — analyst consensus (Gemini grounding)
 7. classify_fundamental()      — composite score + signal label
 8. _generate_llm_summary()     — natural-language narrative (RouterChatClient)
 9. upsert_fundamental_snapshot() — persist to DB
10. upsert_fundamental_history()  — persist historical financials to DB

Each step is no-raise; exceptions are captured in result.errors so the
pipeline always returns a (potentially partial) FundamentalResult.

Public API
----------
run_fundamental_pipeline(ticker, exchange, dry_run, llm, google_llm) -> FundamentalResult
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from agents.fundamental.contracts import (
    AnalystDetail,
    FundamentalResult,
    GrowthDetail,
    MacroDetail,
    QualityDetail,
    ValuationDetail,
)
from agents.fundamental.fetcher import fetch_fundamentals
from agents.fundamental.valuation_agent import score_valuation
from agents.fundamental.quality_agent import score_quality
from agents.fundamental.growth_agent import score_growth
from agents.fundamental.macro_agent import fetch_macro_context
from agents.fundamental.analyst_agent import fetch_analyst_consensus
from agents.fundamental.fundamental_classifier import classify_fundamental

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM summary generation
# ---------------------------------------------------------------------------

_SUMMARY_SYSTEM = """\
You are a professional equity analyst writing a concise fundamental assessment.
Be factual, data-driven, and neutral. No investment advice.
Keep the summary to 3-4 sentences maximum."""

_SUMMARY_PROMPT_TEMPLATE = """\
Write a brief fundamental assessment for {company} ({ticker}, {exchange}).

Key data:
- Sector: {sector}
- Fundamental signal: {signal} (score: {score:.2f})
- Valuation score: {val_score:.2f} (P/E: {pe}, EV/EBITDA: {ev_ebitda})
- Quality score: {qual_score:.2f} (ROE: {roe_pct}, Net margin: {nm_pct})
- Growth score: {growth_score:.2f} (Revenue YoY: {rev_yoy_pct}, EPS YoY: {eps_yoy_pct})
- Macro score: {macro_score:.2f} — {macro_summary}
- Analyst consensus: {analyst_consensus} (target: {target_price}, upside: {upside_pct})

Provide:
1. A 2-3 sentence summary of the fundamental thesis
2. key_strengths: list of 2-3 specific strengths (short bullet strings)
3. key_risks: list of 2-3 specific risks (short bullet strings)

Return as JSON:
{{
  "summary": "...",
  "key_strengths": ["...", "..."],
  "key_risks": ["...", "..."]
}}"""


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"{v * 100:.1f}%"


def _fmt_val(v, fmt: str = ".1f") -> str:
    if v is None:
        return "N/A"
    try:
        return format(float(v), fmt)
    except (TypeError, ValueError):
        return str(v)


def _generate_llm_summary(result: FundamentalResult, llm) -> tuple[str, list, list]:
    """Call RouterChatClient for a narrative summary. Returns (summary, strengths, risks)."""
    import json, re

    prompt = _SUMMARY_PROMPT_TEMPLATE.format(
        company=result.company_name or result.ticker,
        ticker=result.ticker,
        exchange=result.exchange,
        sector=result.sector or "Unknown",
        signal=result.fundamental_signal or "NEUTRAL",
        score=result.fundamental_score or 0.0,
        val_score=result.valuation_score or 0.0,
        qual_score=result.quality_score or 0.0,
        growth_score=result.growth_score or 0.0,
        macro_score=result.macro_score or 0.0,
        macro_summary=(result.macro_summary or "")[:200],
        pe=_fmt_val(result.pe_ratio),
        ev_ebitda=_fmt_val(result.ev_ebitda),
        roe_pct=_fmt_pct(result.roe),
        nm_pct=_fmt_pct(result.net_margin),
        rev_yoy_pct=_fmt_pct(result.revenue_yoy),
        eps_yoy_pct=_fmt_pct(result.earnings_yoy),
        analyst_consensus=result.analyst_consensus or "N/A",
        target_price=_fmt_val(result.analyst_target_price, ".2f"),
        upside_pct=_fmt_pct(result.analyst_upside_pct),
    )

    resp = llm.chat(
        messages=[
            {"role": "system", "content": _SUMMARY_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.3,
    )
    raw = resp.get("content", "") if isinstance(resp, dict) else str(resp)

    # Parse JSON
    raw = raw.strip()
    raw_clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    m = re.search(r"\{[\s\S]+\}", raw_clean)
    if m:
        try:
            parsed = json.loads(m.group())
            return (
                parsed.get("summary", ""),
                parsed.get("key_strengths", []),
                parsed.get("key_risks", []),
            )
        except json.JSONDecodeError:
            pass
    return raw[:500], [], []


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_fundamental_pipeline(
    ticker: str,
    exchange: str,
    dry_run: bool = False,
    llm=None,
    google_llm=None,
) -> FundamentalResult:
    """
    Run the full 10-step fundamental analysis pipeline.

    Parameters
    ----------
    ticker    : str  e.g. "AAPL"
    exchange  : str  "US" or "ASX"
    dry_run   : bool  if True, skip DB writes
    llm       : RouterChatClient (for summary generation)
    google_llm: GoogleChatClient (for grounding calls)

    Returns
    -------
    FundamentalResult — always returned, even on partial failure.
    Check result.errors for any issues encountered.
    """
    result = FundamentalResult(
        ticker=ticker.upper(),
        exchange=exchange.upper(),
        computed_at=datetime.utcnow(),
    )

    # ── Step 1: Fetch fundamentals ────────────────────────────────────────────
    try:
        data = fetch_fundamentals(ticker, exchange)
        result.errors.extend(data.pop("errors", []))
        result.warnings.extend(data.pop("warnings", []))
        history = data.pop("history", [])

        # Map flat dict fields to result
        for field_name in FundamentalResult.model_fields:
            if field_name in data:
                setattr(result, field_name, data[field_name])

    except Exception as exc:
        result.errors.append(f"Step 1 (fetch): {exc}")
        log.error("pipeline step 1 failed for %s: %s", ticker, exc)
        return result  # Cannot proceed without data

    # ── Step 2: Valuation score ───────────────────────────────────────────────
    try:
        val_score, val_detail = score_valuation(data)
        result.valuation_score = val_score
        result.valuation_detail = ValuationDetail(**val_detail) if val_detail else None
    except Exception as exc:
        result.errors.append(f"Step 2 (valuation): {exc}")
        log.warning("pipeline step 2 failed for %s: %s", ticker, exc)

    # ── Step 3: Quality score ─────────────────────────────────────────────────
    try:
        qual_score, qual_detail = score_quality(data)
        result.quality_score = qual_score
        result.quality_detail = QualityDetail(**qual_detail) if qual_detail else None
    except Exception as exc:
        result.errors.append(f"Step 3 (quality): {exc}")
        log.warning("pipeline step 3 failed for %s: %s", ticker, exc)

    # ── Step 4: Growth score ──────────────────────────────────────────────────
    try:
        growth_score, growth_detail = score_growth(data)
        result.growth_score = growth_score
        result.growth_detail = GrowthDetail(**growth_detail) if growth_detail else None
    except Exception as exc:
        result.errors.append(f"Step 4 (growth): {exc}")
        log.warning("pipeline step 4 failed for %s: %s", ticker, exc)

    # ── Step 5: Macro context (sector-cached) ─────────────────────────────────
    try:
        macro = fetch_macro_context(
            exchange=result.exchange,
            sector=result.sector or "Unknown",
            llm=google_llm,
        )
        result.macro_score = macro.macro_score
        result.macro_summary = macro.macro_summary
        result.macro_factors = macro.macro_factors
        result.geopolitical_flags = macro.geopolitical_flags
        result.tech_disruption_risk = macro.tech_disruption_risk
        result.macro_detail = MacroDetail(
            macro_score=macro.macro_score,
            macro_summary=macro.macro_summary,
            macro_factors=macro.macro_factors,
            geopolitical_flags=macro.geopolitical_flags,
            tech_disruption_risk=macro.tech_disruption_risk,
            cached=macro.cached,
        )
        if macro.error:
            result.warnings.append(f"Macro context partial: {macro.error}")
    except Exception as exc:
        result.errors.append(f"Step 5 (macro): {exc}")
        log.warning("pipeline step 5 failed for %s: %s", ticker, exc)

    # ── Step 6: Analyst consensus ─────────────────────────────────────────────
    try:
        analyst = fetch_analyst_consensus(
            ticker=result.ticker,
            exchange=result.exchange,
            company_name=result.company_name,
            llm=google_llm,
        )
        result.analyst_consensus = analyst.consensus
        result.analyst_target_price = analyst.target_price
        result.analyst_upside_pct = analyst.upside_pct
        result.analyst_detail = AnalystDetail(
            consensus=analyst.consensus,
            target_price=analyst.target_price,
            upside_pct=analyst.upside_pct,
            num_analysts=analyst.num_analysts,
            sources=analyst.sources,
        )
        if analyst.error:
            result.warnings.append(f"Analyst consensus partial: {analyst.error}")
    except Exception as exc:
        result.errors.append(f"Step 6 (analyst): {exc}")
        log.warning("pipeline step 6 failed for %s: %s", ticker, exc)

    # ── Step 7: Classify ──────────────────────────────────────────────────────
    try:
        fund_score, fund_signal = classify_fundamental(
            valuation_score=result.valuation_score,
            quality_score=result.quality_score,
            growth_score=result.growth_score,
            macro_score=result.macro_score,
        )
        result.fundamental_score = fund_score
        result.fundamental_signal = fund_signal
    except Exception as exc:
        result.errors.append(f"Step 7 (classify): {exc}")
        log.warning("pipeline step 7 failed for %s: %s", ticker, exc)

    # ── Step 8: LLM summary ───────────────────────────────────────────────────
    if llm is not None:
        try:
            summary, strengths, risks = _generate_llm_summary(result, llm)
            result.fundamental_summary = summary
            result.key_strengths = strengths
            result.key_risks = risks
        except Exception as exc:
            result.warnings.append(f"Step 8 (summary): {exc}")
            log.warning("pipeline step 8 failed for %s: %s", ticker, exc)

    # ── Steps 9 & 10: DB persistence ─────────────────────────────────────────
    if not dry_run:
        try:
            from scripts.lib.fundamental_helpers import (
                upsert_fundamental_snapshot,
                upsert_fundamental_history,
            )
            upsert_fundamental_snapshot(result)
        except Exception as exc:
            result.errors.append(f"Step 9 (upsert_snapshot): {exc}")
            log.error("pipeline step 9 failed for %s: %s", ticker, exc)

        try:
            from scripts.lib.fundamental_helpers import upsert_fundamental_history
            if history:
                upsert_fundamental_history(result.ticker, result.exchange, history)
        except Exception as exc:
            result.errors.append(f"Step 10 (upsert_history): {exc}")
            log.error("pipeline step 10 failed for %s: %s", ticker, exc)
    else:
        log.info("[DRY RUN] skipping DB writes for %s", ticker)

    return result
