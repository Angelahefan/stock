"""
Tone Shift Agent
=================
Signal Agent 3 — Detects softer management language.

Uses a confidence-word vs uncertainty-word scoring approach.

Examples:
  expect → aim
  strong → stable
  will   → may
  confident → cautious
  commit → evaluate

Reuses: RouterChatClient from agents/llm_client.py
"""

from __future__ import annotations

import re
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


# ── Vocabulary ─────────────────────────────────────────────────────────────────
# Higher positive score = more confident language
# Words that move from old→new in a downward direction = tone softening

_CONFIDENCE_VOCAB: Dict[str, int] = {
    # Very confident (+3)
    "commit":      3, "committed":    3, "will":        3,
    "certainty":   3, "certain":      3, "guarantee":   3,
    "deliver":     3, "delivering":   3,

    # Confident (+2)
    "expect":      2, "expects":      2, "expected":    2,
    "confident":   2, "confidence":   2,
    "strong":      2, "strongly":     2, "robust":      2,
    "achieve":     2, "achieves":     2,
    "target":      2, "targeting":    2,
    "forecast":    2, "project":      2,
    "grow":        2, "growing":      2, "growth":      2,
    "accelerate":  2, "accelerating": 2,

    # Moderately confident (+1)
    "plan":        1, "plans":        1, "planned":     1,
    "anticipate":  1, "expect":       1, "execute":     1,
    "on track":    1, "positive":     1,
}

_UNCERTAINTY_VOCAB: Dict[str, int] = {
    # Very uncertain (-3)
    "uncertain":   3, "uncertainty":  3,
    "risk":        3, "risks":        3,
    "challenging": 3, "headwinds":    3,
    "volatile":    3, "volatility":   3,

    # Uncertain (-2)
    "may":         2, "might":        2, "could":       2,
    "cautious":    2, "caution":      2, "careful":     2,
    "evaluate":    2, "evaluating":   2, "exploring":   2,
    "prudent":     2, "prudently":    2,
    "aim":         2, "aims":         2,
    "seek":        2, "seeking":      2,
    "stable":      2,   # "stable" replaces "strong" = softening

    # Mildly uncertain (-1)
    "hope":        1, "hopes":        1,
    "subject to":  1, "depending on": 1,
    "aspire":      1,
    "possible":    1, "potentially":  1,
    "limited":     1,
}

# Specific substitution pairs that are canonical tone-softening signals
_SUBSTITUTION_PAIRS = [
    ("will",       "may"),
    ("will",       "might"),
    ("will",       "could"),
    ("confident",  "cautious"),
    ("committed",  "evaluating"),
    ("committed",  "exploring"),
    ("strong",     "stable"),
    ("expect",     "aim"),
    ("expect",     "hope"),
    ("target",     "pursue"),
    ("deliver",    "seek"),
    ("guarantee",  "aim"),
    ("certain",    "uncertain"),
    ("growth",     "stability"),
    ("accelerate", "maintain"),
]


def _score_text(text: str) -> Tuple[int, int]:
    """
    Return (confidence_score, uncertainty_score) for a block of text.
    Scores are weighted by frequency × weight.
    """
    text_lower = text.lower()
    conf  = sum(w * text_lower.count(kw) for kw, w in _CONFIDENCE_VOCAB.items())
    uncert = sum(w * text_lower.count(kw) for kw, w in _UNCERTAINTY_VOCAB.items())
    return conf, uncert


def _net_tone_score(text: str) -> float:
    """Return normalised net tone score: positive = confident, negative = uncertain."""
    conf, uncert = _score_text(text)
    total = conf + uncert
    if total == 0:
        return 0.0
    return (conf - uncert) / total


def _detect_substitutions(old_text: str, new_text: str) -> List[str]:
    """Find canonical confidence→uncertainty substitution pairs."""
    old_lower = old_text.lower()
    new_lower = new_text.lower()
    found = []
    for (conf_word, uncert_word) in _SUBSTITUTION_PAIRS:
        if conf_word in old_lower and uncert_word in new_lower:
            found.append(f'"{conf_word}" → "{uncert_word}"')
    return found


def detect_tone_softening(
    old_text: str,
    new_text: str,
    changed_snippet: str = "",
) -> Tuple[bool, float, str, List[str]]:
    """
    Core heuristic detection for tone softening.

    Returns:
        detected      : bool
        confidence    : float  0.0–1.0
        severity_hint : str    "HIGH" | "MEDIUM" | "LOW"
        evidence      : List[str]
    """
    evidence: List[str] = []

    old_tone = _net_tone_score(old_text)
    new_tone = _net_tone_score(new_text)
    tone_delta = old_tone - new_tone   # positive = tone has dropped

    substitutions = _detect_substitutions(old_text, new_text)
    for sub in substitutions:
        evidence.append(f"Tone substitution detected: {sub}")

    if tone_delta > 0.05:
        evidence.append(
            f"Net tone score dropped: {old_tone:+.2f} → {new_tone:+.2f} "
            f"(Δ = {tone_delta:.2f})"
        )

    # Score
    score = 0.0
    score += min(tone_delta * 1.5, 0.5)          # up to 0.5 from tone delta
    score += min(len(substitutions) * 0.15, 0.4)  # up to 0.4 from substitutions
    score = max(score, 0.0)
    score = min(score, 1.0)

    detected = score >= 0.15 or len(substitutions) >= 2

    if score >= 0.6:
        severity = "HIGH"
    elif score >= 0.3:
        severity = "MEDIUM"
    else:
        severity = "LOW"

    return detected, round(score, 3), severity, evidence


def run_tone_shift_agent(
    old_text: str,
    new_text: str,
    changed_snippet: str = "",
    llm_client=None,
) -> dict:
    """
    Run the tone shift detection agent.
    Returns a dict compatible with DetectSignalData.
    """
    detected, confidence, severity, evidence = detect_tone_softening(
        old_text, new_text, changed_snippet
    )

    if not detected:
        return {
            "signal_type": "NO_SIGNAL",
            "severity":    "NONE",
            "confidence":  confidence,
            "financial_relevance": "No meaningful softening in management tone detected.",
            "evidence_quotes": [],
            "quality_flags": [],
        }

    financial_relevance = _llm_explain_tone(evidence, llm_client)

    return {
        "signal_type":        "TONE_SOFTENING",
        "severity":           severity,
        "confidence":         confidence,
        "financial_relevance": financial_relevance,
        "evidence_quotes":    evidence[:5],
        "quality_flags":      _quality_flags(old_text, new_text),
    }


def _llm_explain_tone(evidence: List[str], llm_client) -> str:
    if llm_client is None or not evidence:
        return (
            "Management language has shifted toward less confident, more hedged phrasing. "
            "Repeated substitution of assertive words with cautious alternatives "
            "may signal reduced conviction in the company's near-term outlook."
        )

    prompt_lines = [
        "You are a financial analyst. These tone changes were detected in a company's "
        "investor-facing text. Write 1-2 sentences on the potential financial significance. "
        "Professional, factual, no investment advice.",
        "",
        "Tone shift evidence:",
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
        logger.warning("[ToneShiftAgent] LLM call failed: %s", exc)
        return (
            "Management tone has shifted to more cautious language. "
            "This pattern may indicate reduced confidence in the company's near-term trajectory."
        )


def _quality_flags(old_text: str, new_text: str) -> List[str]:
    flags = []
    if len(old_text) < 100:
        flags.append("old_text_very_short")
    if len(new_text) < 100:
        flags.append("new_text_very_short")
    return flags
