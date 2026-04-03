"""
Forward Guidance Agent
=======================
Signal Agent 1 — Detects removal or weakening of forward-looking statements.

Examples:
  "We expect revenue growth of 25% in FY2026" → removed
  "will achieve"  → "aim to pursue"
  "targeting"     → removed
  explicit timeline removed

Reuses: RouterChatClient from agents/llm_client.py
"""

from __future__ import annotations

import re
import logging
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Keyword sets ───────────────────────────────────────────────────────────────

# Strong forward-guidance words — presence in OLD text but not NEW signals withdrawal
_GUIDANCE_STRONG = {
    "expect", "expects", "expected", "expecting",
    "project", "projects", "projected", "projection",
    "forecast", "forecasts", "forecasted",
    "target", "targets", "targeting", "targeted",
    "will achieve", "will deliver", "will grow", "will reach",
    "guidance", "on track", "committed to",
    "confident", "confidence",
    "anticipate", "anticipates", "anticipated",
}

# Weakening words — replacement of strong words with these signals softening
_GUIDANCE_WEAK = {
    "aim", "aims", "aiming",
    "pursue", "pursues", "pursuing",
    "seek", "seeks", "seeking",
    "explore", "exploring",
    "evaluate", "evaluating",
    "hope", "hopes",
    "may", "might", "could",
    "aspire", "aspires",
    "continue to evaluate",
}

# Temporal markers that are often removed when guidance is withdrawn
_TEMPORAL_PATTERNS = [
    r"\b(fy|financial year)\s*20\d\d\b",
    r"\bq[1-4]\s+20\d\d\b",
    r"\b20\d\d\b",                        # standalone year
    r"\bby (end of|end|mid|late|early)\b",
    r"\bwithin \d+ (months?|years?|quarters?)\b",
]


def _tokenize(text: str) -> set:
    """Return lowercase word set from text."""
    return set(re.findall(r"\b\w+\b", text.lower()))


def _find_guidance_sentences(text: str) -> List[str]:
    """Return sentences that contain forward-guidance language."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    hits = []
    for s in sentences:
        s_lower = s.lower()
        if any(kw in s_lower for kw in _GUIDANCE_STRONG):
            hits.append(s.strip())
    return hits


def _temporal_markers_present(text: str) -> bool:
    for pat in _TEMPORAL_PATTERNS:
        if re.search(pat, text.lower()):
            return True
    return False


def _count_strong_guidance(text: str) -> int:
    words = _tokenize(text)
    return sum(1 for kw in _GUIDANCE_STRONG if kw in words or kw in text.lower())


def detect_guidance_withdrawal(
    old_text: str,
    new_text: str,
    changed_snippet: str = "",
) -> Tuple[bool, float, str, List[str]]:
    """
    Core heuristic detection for guidance withdrawal.

    Returns:
        detected      : bool   — whether a signal is detected
        confidence    : float  — 0.0–1.0
        severity_hint : str    — "HIGH" | "MEDIUM" | "LOW"
        evidence      : List[str]
    """
    evidence: List[str] = []

    old_strong  = _count_strong_guidance(old_text)
    new_strong  = _count_strong_guidance(new_text)
    drop        = old_strong - new_strong

    old_sents   = _find_guidance_sentences(old_text)
    new_sents   = _find_guidance_sentences(new_text)

    old_temporal = _temporal_markers_present(old_text)
    new_temporal = _temporal_markers_present(new_text)
    temporal_removed = old_temporal and not new_temporal

    # Sentences that exist in old but are substantially absent from new
    removed_sents: List[str] = []
    for s in old_sents:
        # Use SequenceMatcher to check if this sentence still exists in new_text
        ratio = SequenceMatcher(None, s.lower(), new_text.lower()).ratio()
        if ratio < 0.5:
            removed_sents.append(s)
            evidence.append(f"Removed: \"{s}\"")

    # Weakening substitutions
    old_words = _tokenize(old_text)
    new_words = _tokenize(new_text)
    strong_removed = old_words & _GUIDANCE_STRONG - new_words
    weak_added     = (new_words & _GUIDANCE_WEAK) - old_words
    if strong_removed and weak_added:
        evidence.append(
            f"Strong words removed: {sorted(strong_removed)} | "
            f"Weak words added: {sorted(weak_added)}"
        )

    if temporal_removed:
        evidence.append("Explicit timeline / year reference removed.")

    # Score
    score = 0.0
    if removed_sents:
        score += 0.4
    if drop >= 2:
        score += 0.2
    elif drop >= 1:
        score += 0.1
    if strong_removed and weak_added:
        score += 0.2
    if temporal_removed:
        score += 0.2

    # Clamp
    score = min(score, 1.0)

    detected = score >= 0.2

    if score >= 0.7:
        severity = "HIGH"
    elif score >= 0.4:
        severity = "MEDIUM"
    else:
        severity = "LOW"

    return detected, round(score, 3), severity, evidence


def run_forward_guidance_agent(
    old_text: str,
    new_text: str,
    changed_snippet: str = "",
    llm_client=None,
) -> dict:
    """
    Run the forward guidance detection agent.

    Args:
        old_text         : previous website / document snapshot
        new_text         : current website / document snapshot
        changed_snippet  : optional diff snippet (from TinyFish)
        llm_client       : optional RouterChatClient for LLM enrichment

    Returns a dict compatible with DetectSignalData (minus signal_type wrapper).
    """
    detected, confidence, severity, evidence = detect_guidance_withdrawal(
        old_text, new_text, changed_snippet
    )

    flags = _quality_flags(old_text, new_text)

    if not detected:
        return {
            "signal_type": "NO_SIGNAL",
            "severity":    "NONE",
            "confidence":  confidence,
            "financial_relevance": "No meaningful change in forward guidance language detected.",
            "evidence_quotes": [],
            "quality_flags": flags,
        }

    # Optional LLM enrichment for a concise financial_relevance explanation
    financial_relevance = _llm_explain_guidance(evidence, llm_client)

    return {
        "signal_type":        "GUIDANCE_WITHDRAWAL",
        "severity":           severity,
        "confidence":         confidence,
        "financial_relevance": financial_relevance,
        "evidence_quotes":    evidence[:5],   # cap for response size
        "quality_flags":      flags,
    }


def _llm_explain_guidance(evidence: List[str], llm_client) -> str:
    """Use LLM (if available) to write a concise financial relevance explanation."""
    if llm_client is None or not evidence:
        return (
            "The company appears to have removed or weakened explicit forward-looking "
            "guidance language. This may indicate reduced management confidence in "
            "previously communicated targets."
        )

    prompt_lines = [
        "You are a financial analyst. The following changes were detected in a company's "
        "investor-facing text. Write 1-2 sentences explaining the potential financial "
        "significance. Be factual and professional. Do not give investment advice.",
        "",
        "Evidence of guidance withdrawal:",
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
        logger.warning("[ForwardGuidanceAgent] LLM call failed: %s", exc)
        return (
            "Forward guidance language removed or weakened. "
            "Management confidence in stated targets may have decreased."
        )


def _quality_flags(old_text: str, new_text: str) -> List[str]:
    flags = []
    if len(old_text) < 100:
        flags.append("old_text_very_short")
    if len(new_text) < 100:
        flags.append("new_text_very_short")
    if old_text.strip() == new_text.strip():
        flags.append("texts_identical")
    return flags
