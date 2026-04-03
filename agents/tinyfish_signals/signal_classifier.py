"""
Signal Classifier
==================
Combines all three signal agents and applies priority ordering per spec:
  1. GUIDANCE_WITHDRAWAL
  2. RISK_DISCLOSURE_EXPANSION
  3. TONE_SOFTENING

v1.5 additions (claude-build-spec-v1.5-financial-agents.md):
  - Noise classification via change_type_classifier (CONTENT/ARCHIVE/LAYOUT)
  - Financial confidence score now considers: signal strength, signal type,
    text quality, cross-validation result, AND noise classification.
  - Only CONTENT_CHANGE propagates with full confidence.

Optionally boosts confidence if cross-validation confirms the signal.

Returns the unified SignalClassification output.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .forward_guidance_agent   import run_forward_guidance_agent
from .risk_disclosure_agent    import run_risk_disclosure_agent
from .tone_shift_agent         import run_tone_shift_agent
from .change_type_classifier   import classify_change_type, get_confidence_multiplier

logger = logging.getLogger(__name__)

# Priority order — lower index = higher priority
_PRIORITY = [
    "GUIDANCE_WITHDRAWAL",
    "RISK_DISCLOSURE_EXPANSION",
    "TONE_SOFTENING",
]

# Minimum confidence threshold to surface a signal
_MIN_CONFIDENCE = 0.15

# Cross-validation confidence boost
_VALIDATION_BOOST = {
    "CONFIRMED":           0.20,
    "PARTIALLY_CONFIRMED": 0.10,
    "NOT_CONFIRMED_YET":   0.00,
    "SOURCE_UNAVAILABLE":  -0.05,
}

# Financial relevance boosts by severity
_SEVERITY_WEIGHTS = {"HIGH": 0.9, "MEDIUM": 0.6, "LOW": 0.3, "NONE": 0.0}


def classify_signals(
    old_text: str,
    new_text: str,
    changed_snippet: str = "",
    llm_client=None,
    validation_result: Optional[dict] = None,
    change_type: str = "CONTENT_CHANGE",
    change_quality_score: float = 1.0,
) -> dict:
    """
    Run all three signal agents, apply priority ordering, and return the
    top-priority signal above the confidence threshold.

    v1.5: Accepts change_type and change_quality_score from the
    change_type_classifier to apply noise-aware confidence scaling.

    Args:
        old_text              : previous text snapshot
        new_text              : current text snapshot
        changed_snippet       : diff snippet from TinyFish
        llm_client            : optional RouterChatClient
        validation_result     : output of cross_validation_agent (optional)
        change_type           : CONTENT_CHANGE | ARCHIVE_CHANGE | LAYOUT_CHANGE
        change_quality_score  : quality score from change_type_classifier (0.0–1.0)

    Returns a dict with all SignalClassification fields.
    """
    # ── Run all three agents ──────────────────────────────────────────────────
    results: Dict[str, dict] = {
        "GUIDANCE_WITHDRAWAL":    run_forward_guidance_agent(
                                      old_text, new_text, changed_snippet, llm_client),
        "RISK_DISCLOSURE_EXPANSION": run_risk_disclosure_agent(
                                      old_text, new_text, changed_snippet, llm_client),
        "TONE_SOFTENING":         run_tone_shift_agent(
                                      old_text, new_text, changed_snippet, llm_client),
    }

    # ── v1.5: Apply noise classification multiplier ───────────────────────────
    # Per spec: ARCHIVE/LAYOUT changes should not generate high-confidence signals.
    noise_multiplier = get_confidence_multiplier(change_type, change_quality_score)
    if noise_multiplier < 1.0:
        for r in results.values():
            if r.get("signal_type") != "NO_SIGNAL":
                r["confidence"] = round(r["confidence"] * noise_multiplier, 3)
                r.setdefault("quality_flags", []).append(
                    f"confidence_reduced_{change_type.lower()}"
                )

    # ── Apply validation confidence boost ────────────────────────────────────
    if validation_result:
        vstatus = validation_result.get("validation_status", "NOT_CONFIRMED_YET")
        boost   = _VALIDATION_BOOST.get(vstatus, 0.0)
        cadj    = validation_result.get("confidence_adjustment", 0.0)
        for r in results.values():
            if r.get("signal_type") != "NO_SIGNAL":
                r["confidence"] = min(
                    1.0,
                    r["confidence"] + boost + cadj
                )

    # ── Select top-priority signal above threshold ────────────────────────────
    winner = None
    for signal_type in _PRIORITY:
        r = results[signal_type]
        if r.get("signal_type") == signal_type and r.get("confidence", 0) >= _MIN_CONFIDENCE:
            winner = r
            break

    if winner is None:
        # No signal above threshold — return NO_SIGNAL with best confidence
        best_conf = max(r.get("confidence", 0.0) for r in results.values())
        winner = {
            "signal_type":        "NO_SIGNAL",
            "severity":           "NONE",
            "confidence":         round(best_conf, 3),
            "financial_relevance": "No meaningful financial signal detected in the text changes.",
            "evidence_quotes":    [],
            "quality_flags":      [],
        }

    # ── Merge validation fields ───────────────────────────────────────────────
    validation_status  = "NOT_CONFIRMED_YET"
    validation_summary = ""
    validation_evidence: List[dict] = []

    if validation_result:
        validation_status   = validation_result.get("validation_status",  validation_status)
        validation_summary  = validation_result.get("validation_summary",  validation_summary)
        validation_evidence = validation_result.get("validation_evidence", validation_evidence)

    # ── v1.5: Financial confidence score considers all factors ────────────────
    # signal strength × signal type weight × text quality × validation boost
    severity_weight = _SEVERITY_WEIGHTS.get(winner.get("severity", "NONE"), 0.0)
    validation_boost_score = {
        "CONFIRMED":           0.15,
        "PARTIALLY_CONFIRMED": 0.08,
        "NOT_CONFIRMED_YET":   0.0,
        "SOURCE_UNAVAILABLE":  -0.03,
    }.get(validation_status, 0.0)

    financial_relevance_score = round(
        min(1.0, max(0.0,
            winner.get("confidence", 0.0) * 0.5
            + severity_weight * 0.3
            + change_quality_score * 0.1
            + validation_boost_score * 0.1
        )),
        3,
    )

    # Add change type to quality flags for transparency
    winner_flags = list(winner.get("quality_flags", []))
    if change_type != "CONTENT_CHANGE":
        winner_flags.append(f"change_type_{change_type.lower()}")
    elif change_quality_score < 0.6:
        winner_flags.append("low_content_quality")

    return {
        "signal_type":          winner.get("signal_type"),
        "severity":             winner.get("severity"),
        "confidence":           winner.get("confidence"),
        "financial_relevance":  winner.get("financial_relevance"),
        "financial_relevance_score": financial_relevance_score,
        "evidence_quotes":      winner.get("evidence_quotes", []),
        "quality_flags":        winner_flags,
        "change_type":          change_type,
        "change_quality_score": change_quality_score,
        "validation_status":    validation_status,
        "validation_summary":   validation_summary,
        "validation_evidence":  validation_evidence,
        # Include all sub-agent results for transparency / debugging
        "_all_signals": {k: v for k, v in results.items()},
    }
