"""
agents/stock_synthesis/conflict_meter.py
─────────────────────────────────────────────────────────────────────────────
Quantitative conflict and consensus scoring for the Investment Committee.

Converts agent signal directions into numeric scores, measures disagreement,
and computes regime-weighted consensus.

Usage:
    from agents.stock_synthesis.conflict_meter import compute_conflict_consensus

    result = compute_conflict_consensus(
        agent_scores={"TECHNICAL": 0.5, "FUNDAMENTAL": -0.3, "SENTIMENT": 0.2, "MACRO": -0.1},
        regime=MarketRegime.BULL_MOMENTUM,
    )
    print(result.conflict_level, result.consensus_score)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from agents.stock_synthesis.contracts import SignalDirection


# ---------------------------------------------------------------------------
# Direction-to-score mapping
# ---------------------------------------------------------------------------

_DIRECTION_SCORES: Dict[SignalDirection, float] = {
    SignalDirection.STRONG_BUY: 1.0,
    SignalDirection.BUY: 0.5,
    SignalDirection.HOLD: 0.0,
    SignalDirection.SELL: -0.5,
    SignalDirection.STRONG_SELL: -1.0,
}


def direction_to_score(direction: SignalDirection) -> float:
    """Convert a SignalDirection to a numeric score (-1.0 to +1.0)."""
    return _DIRECTION_SCORES.get(direction, 0.0)


def score_to_direction(score: float) -> SignalDirection:
    """Convert a numeric score back to the nearest SignalDirection."""
    if score >= 0.75:
        return SignalDirection.STRONG_BUY
    if score >= 0.25:
        return SignalDirection.BUY
    if score > -0.25:
        return SignalDirection.HOLD
    if score > -0.75:
        return SignalDirection.SELL
    return SignalDirection.STRONG_SELL


# ---------------------------------------------------------------------------
# Conflict & Consensus result
# ---------------------------------------------------------------------------

@dataclass
class ConflictConsensus:
    """Result of conflict and consensus computation."""
    conflict_level: float       # 0.0 (unanimous) to 1.0 (max disagreement)
    consensus_score: float      # -1.0 to +1.0 (regime-weighted average)
    consensus_direction: SignalDirection
    agent_scores: Dict[str, float]
    regime_weights: Dict[str, float]
    macro_view: str             # regime label
    score_spread: float         # max - min agent score
    dominant_side: str          # "BULLISH", "BEARISH", or "MIXED"


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def compute_conflict_consensus(
    agent_scores: Dict[str, float],
    regime_weights: Dict[str, float],
    macro_view: str = "NEUTRAL_TRANSITION",
) -> ConflictConsensus:
    """
    Compute conflict level and consensus score from agent raw scores.

    Parameters
    ----------
    agent_scores : dict
        Raw scores per agent, e.g. {"TECHNICAL": 0.5, "FUNDAMENTAL": -0.3, ...}
        Values should be in [-1.0, +1.0].
    regime_weights : dict
        Weights per agent from get_regime_weights(), e.g. {"TECHNICAL": 0.35, ...}
    macro_view : str
        Regime label (e.g. "BULL_MOMENTUM")

    Returns
    -------
    ConflictConsensus
    """
    scores = list(agent_scores.values())
    n = len(scores)

    if n == 0:
        return ConflictConsensus(
            conflict_level=0.0,
            consensus_score=0.0,
            consensus_direction=SignalDirection.HOLD,
            agent_scores=agent_scores,
            regime_weights=regime_weights,
            macro_view=macro_view,
            score_spread=0.0,
            dominant_side="MIXED",
        )

    # --- Conflict level: normalized std dev ---
    mean = sum(scores) / n
    variance = sum((s - mean) ** 2 for s in scores) / n
    std_dev = math.sqrt(variance)
    # Normalize: max possible std_dev for [-1, +1] range is 1.0 (all at extremes)
    conflict_level = min(std_dev, 1.0)

    # --- Consensus score: regime-weighted average ---
    weighted_sum = 0.0
    weight_total = 0.0
    for agent_key, score in agent_scores.items():
        w = regime_weights.get(agent_key, 0.25)  # default equal weight
        weighted_sum += score * w
        weight_total += w

    consensus_score = weighted_sum / weight_total if weight_total > 0 else mean
    consensus_score = max(-1.0, min(1.0, consensus_score))

    # --- Score spread ---
    score_spread = max(scores) - min(scores)

    # --- Dominant side ---
    bullish = sum(1 for s in scores if s > 0.1)
    bearish = sum(1 for s in scores if s < -0.1)
    if bullish > bearish:
        dominant_side = "BULLISH"
    elif bearish > bullish:
        dominant_side = "BEARISH"
    else:
        dominant_side = "MIXED"

    return ConflictConsensus(
        conflict_level=round(conflict_level, 4),
        consensus_score=round(consensus_score, 4),
        consensus_direction=score_to_direction(consensus_score),
        agent_scores=agent_scores,
        regime_weights=regime_weights,
        macro_view=macro_view,
        score_spread=round(score_spread, 4),
        dominant_side=dominant_side,
    )


def compute_conflict_from_signals(
    directions: Dict[str, SignalDirection],
    regime_weights: Dict[str, float],
    macro_view: str = "NEUTRAL_TRANSITION",
) -> ConflictConsensus:
    """
    Convenience: compute conflict/consensus directly from SignalDirection values.

    Parameters
    ----------
    directions : dict
        e.g. {"TECHNICAL": SignalDirection.BUY, "FUNDAMENTAL": SignalDirection.SELL}
    """
    agent_scores = {k: direction_to_score(v) for k, v in directions.items()}
    return compute_conflict_consensus(agent_scores, regime_weights, macro_view)
