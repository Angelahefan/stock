"""
TinyFish Financial Signal Pipeline
====================================
Full orchestration pipeline per claude-build-spec-v1.5-financial-agents.md:

  1. Receive TinyFish-extracted website result
  2. Normalize and clean text
  3. Classify change type (CONTENT / ARCHIVE / LAYOUT) — v1.5 Signal Quality Filter
  4. Run financial signal agents (with noise-aware confidence weighting)
  5. If signal is meaningful, run Investigation Agent — v1.5 NEW AGENT
  6. Run Cross-Validation Agent
  7. Re-classify signal with investigation + validation evidence
  8. Generate financial interpretation (LLM-backed)
  9. Generate user-facing summary

v1.5 Additions:
  - change_type_classifier  — Signal Quality Filter (CONTENT/ARCHIVE/LAYOUT)
  - investigation_agent     — NEW: probes press releases, exchange filings, IR pages
  - Enhanced financial confidence score incorporating noise classification

Reuses:
  agents/llm_client.py         — RouterChatClient for LLM calls
  signal_classifier            — combines all 3 agents + noise weighting
  cross_validation_agent       — multi-source confirmation
  change_type_classifier       — CONTENT/ARCHIVE/LAYOUT classification
  investigation_agent          — press release + exchange source investigation
"""

from __future__ import annotations

import html
import logging
import os
import re
from typing import Optional

from .signal_classifier        import classify_signals
from .cross_validation_agent   import run_cross_validation_agent
from .change_type_classifier   import classify_change_type
from .investigation_agent      import run_investigation_agent

logger = logging.getLogger(__name__)

# Minimum confidence to trigger investigation + cross-validation
_CROSS_VALIDATE_THRESHOLD = 0.25
# For ARCHIVE/LAYOUT changes, apply a higher threshold before wasting API calls
_NOISE_SIGNAL_THRESHOLD   = 0.40


# ══════════════════════════════════════════════════════════════════════════════
# Step 2 — Text normalisation
# ══════════════════════════════════════════════════════════════════════════════

def normalize_text(text: str) -> str:
    """
    Normalize raw scraped text for consistent comparison.
    Removes HTML entities, excess whitespace, and control chars.
    """
    if not text:
        return ""
    # Decode HTML entities (e.g. &amp; → &)
    text = html.unescape(text)
    # Strip HTML tags if any remain
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ══════════════════════════════════════════════════════════════════════════════
# Step 7 — Financial interpretation (LLM-backed)
# ══════════════════════════════════════════════════════════════════════════════

def _generate_interpretation(
    ticker: str,
    company_name: str,
    signal_type: str,
    severity: str,
    evidence_quotes: list,
    validation_status: str,
    validation_summary: str,
    llm_client,
) -> dict:
    """
    Generate what_changed / why_it_matters / investment_implication / full summary via LLM.

    Prompt follows Morning Note + Earnings Analysis patterns from institutional research:
      - Lead with the most important finding, not background
      - Focus on what is NEW vs prior disclosure
      - Be opinionated — give a view, not just a description
      - Add an actionable investment implication (thesis intact / under pressure / weakened)

    Falls back to rule-based text if LLM is unavailable.
    """
    _WHAT_CHANGED_DEFAULTS = {
        "GUIDANCE_WITHDRAWAL": (
            f"{company_name} appears to have removed or weakened forward-looking "
            "guidance language from its investor-facing communications."
        ),
        "RISK_DISCLOSURE_EXPANSION": (
            f"{company_name} has expanded its risk disclosure language, "
            "introducing new or more prominent risk factors."
        ),
        "TONE_SOFTENING": (
            f"{company_name}'s investor communications show a shift toward "
            "more cautious and hedged management language."
        ),
        "NO_SIGNAL": "No material change in language was detected.",
    }

    _WHY_MATTERS_DEFAULTS = {
        "GUIDANCE_WITHDRAWAL": (
            "Withdrawal of concrete forward guidance often signals that management "
            "has reduced confidence in previously communicated financial targets. "
            "Analysts typically view this as a potential leading indicator of a guidance revision."
        ),
        "RISK_DISCLOSURE_EXPANSION": (
            "Increasing risk language in corporate communications may indicate management "
            "is becoming more cautious about operational, financial, or macro conditions. "
            "This can precede formal risk updates in filings."
        ),
        "TONE_SOFTENING": (
            "A shift to more hedged management language — replacing confident assertions "
            "with cautious alternatives — may reflect internal concerns not yet disclosed "
            "in formal filings."
        ),
        "NO_SIGNAL": "No meaningful language change was identified in this comparison.",
    }

    _IMPLICATION_DEFAULTS = {
        "GUIDANCE_WITHDRAWAL": "Monitor for formal guidance revision in next filing or earnings call.",
        "RISK_DISCLOSURE_EXPANSION": "Watch for escalation into formal risk factor disclosures.",
        "TONE_SOFTENING": "Track whether tone shift is isolated or part of a broader pattern.",
        "NO_SIGNAL": "",
    }

    what_changed           = _WHAT_CHANGED_DEFAULTS.get(signal_type, _WHAT_CHANGED_DEFAULTS["NO_SIGNAL"])
    why_it_matters         = _WHY_MATTERS_DEFAULTS.get(signal_type, _WHY_MATTERS_DEFAULTS["NO_SIGNAL"])
    investment_implication = _IMPLICATION_DEFAULTS.get(signal_type, "")

    # Try LLM enrichment — Morning Note / Earnings Analysis style
    if llm_client and signal_type != "NO_SIGNAL" and evidence_quotes:
        try:
            # Prompt pattern borrowed from institutional morning note conventions:
            #   - focus on what's NEW (Earnings Analysis: "don't rehash background")
            #   - be opinionated (Morning Note: "summaries without a view are useless")
            #   - add actionable implication (Thesis Tracker: "does this change the thesis?")
            prompt = (
                f"You are a financial analyst writing a tight, opinionated research note "
                f"for a portfolio manager. Be direct and give a view — notes that merely "
                f"describe without a perspective are useless.\n\n"
                f"Company: {company_name} ({ticker})\n"
                f"Signal type: {signal_type.replace('_', ' ').title()} | Severity: {severity}\n"
                f"Evidence (specific language changes detected):\n" +
                "\n".join(f'  — "{q}"' for q in evidence_quotes[:3]) +
                f"\nCross-validation: {validation_status}. {validation_summary}\n\n"
                "Write THREE short sections. Focus only on what is NEW — do not rehash "
                "company background:\n\n"
                "1. WHAT CHANGED: 1-2 sentences on the specific language change observed. "
                "Quote the most significant evidence snippet if possible.\n\n"
                "2. WHY IT MATTERS: 1-2 sentences on the investment significance. "
                "Be opinionated — does this strengthen or weaken the investment thesis? "
                "If guidance was withdrawn, say what was lost. If risk language expanded, "
                "name the new risk dimension.\n\n"
                "3. INVESTMENT IMPLICATION: One sentence on the actionable takeaway — "
                "e.g. 'Thesis intact but monitor earnings call', "
                "'Thesis under pressure — guidance credibility reduced', "
                "'Thesis weakened — risk profile expanded'. "
                "No buy/sell recommendation.\n\n"
                "Rules: plain English, no certainty claims, under 150 words total."
            )
            resp = llm_client.chat(
                messages=[
                    {"role": "system", "content": (
                        "You are a concise, opinionated financial analyst. "
                        "Always give a clear view — never just describe what happened."
                    )},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.15,
            )
            content = resp.get("content", "").strip()
            # Parse the three sections
            parts = [p.strip() for p in re.split(r"\n{2,}", content) if p.strip()]
            if len(parts) >= 3:
                what_changed           = re.sub(r"^(1\.|WHAT CHANGED:?\s*)",           "", parts[0]).strip()
                why_it_matters         = re.sub(r"^(2\.|WHY IT MATTERS:?\s*)",         "", parts[1]).strip()
                investment_implication = re.sub(r"^(3\.|INVESTMENT IMPLICATION:?\s*)", "", parts[2]).strip()
            elif len(parts) >= 2:
                what_changed   = re.sub(r"^(1\.|WHAT CHANGED:?\s*)",   "", parts[0]).strip()
                why_it_matters = re.sub(r"^(2\.|WHY IT MATTERS:?\s*)", "", parts[1]).strip()
            elif len(parts) == 1:
                what_changed = parts[0]
        except Exception as exc:
            logger.warning("[TinyFishPipeline] LLM interpretation failed: %s", exc)

    # Step 8 — User-facing summary
    summary = _build_summary(
        ticker, company_name, signal_type, severity,
        what_changed, why_it_matters, validation_status, validation_summary,
        investment_implication=investment_implication,
    )

    return {
        "what_changed":           what_changed,
        "why_it_matters":         why_it_matters,
        "investment_implication": investment_implication,
        "summary":                summary,
    }


def _build_summary(
    ticker: str,
    company_name: str,
    signal_type: str,
    severity: str,
    what_changed: str,
    why_it_matters: str,
    validation_status: str,
    validation_summary: str,
    investment_implication: str = "",
) -> str:
    """
    Build the full investor-facing narrative summary.

    Format follows Morning Note conventions:
      - Lead with the signal label (the "Top Call" headline)
      - What changed (specific, evidence-based)
      - Why it matters (opinionated view)
      - Investment implication (actionable takeaway — thesis intact/under pressure/weakened)
      - Cross-validation status
    """
    if signal_type == "NO_SIGNAL":
        return f"No material financial signal was detected for {company_name} ({ticker})."

    validation_line = {
        "CONFIRMED":           f"✅ Confirmed — {validation_summary}",
        "PARTIALLY_CONFIRMED": f"⚠️ Partially confirmed — {validation_summary}",
        "NOT_CONFIRMED_YET":   f"🔍 Not yet confirmed in filings — {validation_summary}",
        "SOURCE_UNAVAILABLE":  "ℹ️ Source unavailable for cross-validation.",
    }.get(validation_status, "")

    lines = [
        f"**{signal_type.replace('_', ' ').title()} — {severity} severity**",
        f"{company_name} ({ticker})",
        "",
        f"**What changed:** {what_changed}",
        "",
        f"**Why it matters:** {why_it_matters}",
    ]
    if investment_implication:
        lines += ["", f"**Investment implication:** {investment_implication}"]
    if validation_line:
        lines += ["", f"**Cross-validation:** {validation_line}"]

    lines += [
        "",
        "_This signal is based on language analysis only and does not constitute "
        "investment advice. Always verify with official filings and disclosures._",
    ]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Main pipeline entry point
# ══════════════════════════════════════════════════════════════════════════════

def run_tinyfish_signal_pipeline(
    ticker:          str,
    company_name:    str,
    source_url:      str,
    old_text:        str,
    new_text:        str,
    changed_snippet: str = "",
    llm_client=None,
) -> dict:
    """
    Full TinyFish financial signal pipeline (v1.5).

    Pipeline steps:
      1. Normalize text
      2. Classify change type (CONTENT / ARCHIVE / LAYOUT)    ← v1.5 quality filter
      3. Run signal agents with noise-aware confidence weighting
      4. If signal detected, run Investigation Agent           ← v1.5 new agent
      5. Run Cross-Validation Agent
      6. Re-classify with all evidence
      7. Generate LLM-backed financial interpretation
      8. Build user-facing summary

    Args:
        ticker          : company ticker
        company_name    : full company name
        source_url      : URL of monitored page
        old_text        : previous text snapshot (raw)
        new_text        : current text snapshot (raw)
        changed_snippet : diff snippet from TinyFish scraper
        llm_client      : optional RouterChatClient (uses env if None)

    Returns:
        Full RunPipelineData-compatible dict (extended with v1.5 fields).
    """
    # ── Step 1: Normalize ─────────────────────────────────────────────────────
    old_clean = normalize_text(old_text)
    new_clean = normalize_text(new_text)

    # Resolve LLM client from env if not provided
    if llm_client is None:
        try:
            from agents.llm_client import RouterChatClient
            llm_client = RouterChatClient()
        except Exception as exc:
            logger.info("[TinyFishPipeline] No LLM client, running heuristic-only: %s", exc)

    # ── Step 2: Change type classification (v1.5 Signal Quality Filter) ───────
    change_type, change_quality_score, quality_flags = classify_change_type(
        old_clean, new_clean, changed_snippet
    )
    logger.info(
        "[TinyFishPipeline] Change type: %s (quality=%.2f) for %s (%s)",
        change_type, change_quality_score, company_name, ticker,
    )

    # ── Step 3: Run signal agents + initial classification ────────────────────
    # Pass change_type so noise-aware confidence weighting is applied.
    classification = classify_signals(
        old_clean, new_clean, changed_snippet, llm_client,
        validation_result=None,
        change_type=change_type,
        change_quality_score=change_quality_score,
    )

    signal_type = classification.get("signal_type", "NO_SIGNAL")
    confidence  = classification.get("confidence", 0.0)

    # Determine whether to proceed based on change type + confidence
    # ARCHIVE/LAYOUT changes need higher confidence to warrant further investigation
    min_threshold = (
        _NOISE_SIGNAL_THRESHOLD
        if change_type in ("ARCHIVE_CHANGE", "LAYOUT_CHANGE")
        else _CROSS_VALIDATE_THRESHOLD
    )

    investigation_result = None
    validation_result    = None

    if signal_type != "NO_SIGNAL" and confidence >= min_threshold:
        # ── Step 4: Investigation Agent (v1.5 NEW AGENT) ─────────────────────
        try:
            investigation_result = run_investigation_agent(
                ticker          = ticker,
                company_name    = company_name,
                signal_type     = signal_type,
                source_url      = source_url,
                changed_snippet = changed_snippet,
                llm_client      = llm_client,
            )
            logger.info(
                "[TinyFishPipeline] Investigation: %d corroborating sources found for %s",
                investigation_result.get("corroborating_count", 0), ticker,
            )
        except Exception as exc:
            logger.warning("[TinyFishPipeline] Investigation agent failed: %s", exc)
            investigation_result = {
                "investigation_results": [],
                "sources_checked":       [],
                "investigation_summary": "Investigation could not be completed.",
                "corroborating_count":   0,
                "contradicting_count":   0,
                "found_evidence":        False,
            }

        # ── Step 5: Cross-Validation Agent ───────────────────────────────────
        try:
            validation_result = run_cross_validation_agent(
                ticker          = ticker,
                company_name    = company_name,
                signal_type     = signal_type,
                changed_snippet = changed_snippet,
                source_url      = source_url,
            )
        except Exception as exc:
            logger.warning("[TinyFishPipeline] Cross-validation failed: %s", exc)
            validation_result = {
                "validation_status":     "SOURCE_UNAVAILABLE",
                "validation_summary":    "Cross-validation could not be completed.",
                "validation_evidence":   [],
                "confidence_adjustment": 0.0,
            }

        # ── Step 6: Re-classify with all evidence ─────────────────────────────
        classification = classify_signals(
            old_clean, new_clean, changed_snippet, llm_client,
            validation_result=validation_result,
            change_type=change_type,
            change_quality_score=change_quality_score,
        )

    # ── Steps 7 + 8: Interpretation + summary ────────────────────────────────
    interpretation = _generate_interpretation(
        ticker             = ticker,
        company_name       = company_name,
        signal_type        = classification.get("signal_type", "NO_SIGNAL"),
        severity           = classification.get("severity", "NONE"),
        evidence_quotes    = classification.get("evidence_quotes", []),
        validation_status  = classification.get("validation_status", "NOT_CONFIRMED_YET"),
        validation_summary = classification.get("validation_summary", ""),
        llm_client         = llm_client,
    )

    # Merge all quality flags
    all_quality_flags = list(classification.get("quality_flags", []))
    for f in quality_flags:
        if f not in all_quality_flags:
            all_quality_flags.append(f)

    return {
        # Core signal fields
        "signal_type":        classification.get("signal_type"),
        "severity":           classification.get("severity"),
        "confidence":         classification.get("confidence"),
        "financial_relevance": classification.get("financial_relevance"),
        "evidence_quotes":    classification.get("evidence_quotes", []),
        "quality_flags":      all_quality_flags,
        # v1.5: Change type classification
        "change_type":        change_type,
        "change_quality_score": change_quality_score,
        "financial_relevance_score": classification.get("financial_relevance_score", 0.0),
        # Validation fields
        "validation_status":  classification.get("validation_status", "NOT_CONFIRMED_YET"),
        "validation_summary": classification.get("validation_summary", ""),
        "validation_evidence": (
            validation_result.get("validation_evidence", [])
            if validation_result else []
        ),
        # v1.5: Investigation fields
        "investigation_summary": (
            investigation_result.get("investigation_summary", "")
            if investigation_result else ""
        ),
        "investigation_sources": (
            investigation_result.get("sources_checked", [])
            if investigation_result else []
        ),
        "corroborating_count": (
            investigation_result.get("corroborating_count", 0)
            if investigation_result else 0
        ),
        # Interpretation
        "summary":                interpretation["summary"],
        "what_changed":           interpretation["what_changed"],
        "why_it_matters":         interpretation["why_it_matters"],
        "investment_implication": interpretation.get("investment_implication", ""),
    }
