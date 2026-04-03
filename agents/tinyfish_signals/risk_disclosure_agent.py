"""
Risk Disclosure Agent
======================
Signal Agent 2 — Detects increasing risk language.

Examples:
  new mention of supply chain risk
  new mention of regulatory uncertainty
  new mention of liquidity / financing pressure
  new cautionary language in operations or outlook

Reuses: RouterChatClient from agents/llm_client.py
"""

from __future__ import annotations

import re
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


# ── Risk keyword taxonomy ──────────────────────────────────────────────────────

_RISK_KEYWORDS = {
    # Liquidity / financial stress
    "liquidity", "financing", "covenant", "credit facility", "going concern",
    "capital requirements", "cash runway",

    # Regulatory / legal
    "regulatory", "regulation", "compliance", "litigation", "investigation",
    "enforcement", "sanction", "penalty", "lawsuit", "legal proceedings",

    # Macro / geopolitical
    "geopolitical", "macroeconomic", "interest rate", "inflation",
    "tariff", "trade war", "sanctions", "currency risk",

    # Operational
    "supply chain", "supply disruption", "disruption", "shortage",
    "capacity constraints", "operational risk", "execution risk",

    # Margin / performance
    "margin pressure", "cost pressure", "headwinds", "volume decline",
    "pricing pressure", "competitive pressure",

    # Uncertainty / volatility
    "uncertainty", "volatile", "volatility", "unpredictable",
    "material adverse", "adverse conditions", "downside risk",

    # Catastrophic / structural
    "impairment", "write-down", "write-off", "restructuring",
    "workforce reduction", "redundanc",   # prefix match
}

# Weight multiplier for high-severity risk terms
_HIGH_SEVERITY_TERMS = {
    "going concern", "material adverse", "liquidity", "impairment",
    "write-down", "write-off", "enforcement", "sanction",
}


def _find_risk_sentences(text: str) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    hits = []
    for s in sentences:
        s_lower = s.lower()
        if any(kw in s_lower for kw in _RISK_KEYWORDS):
            hits.append(s.strip())
    return hits


def _count_risk_mentions(text: str) -> dict:
    """Return {keyword: count} for all risk keywords found."""
    text_lower = text.lower()
    return {kw: text_lower.count(kw) for kw in _RISK_KEYWORDS if kw in text_lower}


def detect_risk_disclosure_expansion(
    old_text: str,
    new_text: str,
    changed_snippet: str = "",
) -> Tuple[bool, float, str, List[str]]:
    """
    Core heuristic detection for risk disclosure expansion.

    Returns:
        detected      : bool
        confidence    : float  0.0–1.0
        severity_hint : str    "HIGH" | "MEDIUM" | "LOW"
        evidence      : List[str]
    """
    evidence: List[str] = []

    old_mentions = _count_risk_mentions(old_text)
    new_mentions = _count_risk_mentions(new_text)

    # New keywords not previously present
    newly_added = {k for k, v in new_mentions.items() if k not in old_mentions}
    # Keywords with increased mention count (≥2x or +2)
    expanded = {
        k for k, v in new_mentions.items()
        if k in old_mentions and (v >= old_mentions[k] * 2 or v - old_mentions[k] >= 2)
    }
    # Keywords removed (sometimes risk rollback is also significant — but not our signal)
    # removed = {k for k in old_mentions if k not in new_mentions}

    for kw in sorted(newly_added):
        # Find the sentence context
        sents = [s for s in _find_risk_sentences(new_text) if kw in s.lower()]
        snippet = sents[0] if sents else f'(keyword: "{kw}")'
        evidence.append(f"New risk language — \"{kw}\": {snippet}")

    for kw in sorted(expanded):
        evidence.append(
            f"Expanded mention of \"{kw}\": "
            f"{old_mentions[kw]} → {new_mentions[kw]} occurrences."
        )

    # Score
    high_severity_new = newly_added & _HIGH_SEVERITY_TERMS

    score = 0.0
    score += min(len(newly_added) * 0.12, 0.48)   # up to 0.48 for new keywords
    score += min(len(expanded) * 0.08, 0.24)       # up to 0.24 for expanded
    score += min(len(high_severity_new) * 0.15, 0.30)  # bonus for serious terms

    score = min(score, 1.0)
    detected = score >= 0.12 or bool(high_severity_new)

    if score >= 0.6 or high_severity_new:
        severity = "HIGH"
    elif score >= 0.3:
        severity = "MEDIUM"
    else:
        severity = "LOW"

    return detected, round(score, 3), severity, evidence


def run_risk_disclosure_agent(
    old_text: str,
    new_text: str,
    changed_snippet: str = "",
    llm_client=None,
) -> dict:
    """
    Run the risk disclosure expansion detection agent.
    Returns a dict compatible with DetectSignalData.
    """
    detected, confidence, severity, evidence = detect_risk_disclosure_expansion(
        old_text, new_text, changed_snippet
    )

    if not detected:
        return {
            "signal_type": "NO_SIGNAL",
            "severity":    "NONE",
            "confidence":  confidence,
            "financial_relevance": "No significant increase in risk disclosure language detected.",
            "evidence_quotes": [],
            "quality_flags": [],
        }

    financial_relevance = _llm_explain_risk(evidence, llm_client)

    return {
        "signal_type":        "RISK_DISCLOSURE_EXPANSION",
        "severity":           severity,
        "confidence":         confidence,
        "financial_relevance": financial_relevance,
        "evidence_quotes":    evidence[:5],
        "quality_flags":      _quality_flags(old_text, new_text),
    }


def _llm_explain_risk(evidence: List[str], llm_client) -> str:
    if llm_client is None or not evidence:
        return (
            "The company has expanded its risk disclosure language. "
            "New or increased risk terminology may signal emerging operational, "
            "regulatory, or financial challenges."
        )

    prompt_lines = [
        "You are a financial analyst. These risk language changes were detected "
        "in a company's investor-facing text. In 1-2 sentences, explain the "
        "potential financial significance. Professional tone, no investment advice.",
        "",
        "Evidence:",
    ] + [f"  - {e}" for e in evidence[:3]]

    try:
        resp = llm_client.chat(
            messages=[
                {"role": "system", "content": "You are a concise financial analyst."},
                {"role": "user",   "content": "\n".join(prompt_lines)},
            ],
            temperature=0.1,
        )
        return resp.get("content", "").strip()
    except Exception as exc:
        logger.warning("[RiskDisclosureAgent] LLM call failed: %s", exc)
        return (
            "New or expanded risk disclosure language detected. "
            "This may indicate emerging operational, regulatory, or financial risks."
        )


def _quality_flags(old_text: str, new_text: str) -> List[str]:
    flags = []
    if len(old_text) < 100:
        flags.append("old_text_very_short")
    if len(new_text) < 100:
        flags.append("new_text_very_short")
    return flags
