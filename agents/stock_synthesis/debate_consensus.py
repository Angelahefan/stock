"""
agents/stock_synthesis/debate_consensus.py
─────────────────────────────────────────────────────────────────────────────
Structured Debate Engine for the Investment Committee (v2).

Implements a three-phase debate pattern:
  1. DRAFTING:   Each specialist agent scores the stock (-1 to +1)
  2. CHALLENGE:  Red-team prompts when agents disagree by > 0.5
  3. FINAL VOTE: Revised scores + regime weights → consensus

Integrates Risk Agent (entry gate) and Exit Agent (stop/target levels).
Wraps existing signal_gatherer + macro_agent infrastructure.

Usage:
    from agents.stock_synthesis.debate_consensus import run_debate_consensus

    result = await run_debate_consensus("BHP", "ASX")
    print(result.synthesis.direction, result.consensus.consensus_score)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from agents.stock_synthesis.conflict_meter import (
    ConflictConsensus,
    compute_conflict_consensus,
    direction_to_score,
    score_to_direction,
)
from agents.stock_synthesis.contracts import (
    AgentSignalInput,
    DebatePoint,
    SignalDirection,
    StockSynthesis,
)
from agents.stock_synthesis.exit_agent import (
    ExitAction,
    ExitSignal,
    ExitThresholds,
    get_thresholds,
)
from agents.stock_synthesis.risk_agent import (
    PositionSize,
    RiskAssessment,
    assess_risk,
)

logger = logging.getLogger(__name__)

MODEL = os.getenv("SYNTHESIS_MODEL", "gpt-4o-mini")

# Lazy-loaded singleton memory store (shared with synthesis_pipeline)
_memory_store = None


def _get_memory_store():
    """Lazy-load agent memory store (singleton)."""
    global _memory_store
    if _memory_store is None:
        try:
            from agents.stock_synthesis.memory import AgentMemoryStore
            _memory_store = AgentMemoryStore.from_env()
            _memory_store.load()
        except Exception as exc:
            logger.warning("Agent memory unavailable in debate_consensus: %s", exc)
            from agents.stock_synthesis.memory import AgentMemoryStore
            _memory_store = AgentMemoryStore()
    return _memory_store


# ---------------------------------------------------------------------------
# Debate result container
# ---------------------------------------------------------------------------

@dataclass
class DebateResult:
    """Full debate output: synthesis + consensus + risk + exit."""
    synthesis: StockSynthesis
    consensus: ConflictConsensus
    risk: RiskAssessment
    exit_strategy: Dict[str, Any]
    debate_phases: Dict[str, Any]  # draft/challenge/vote details


# ---------------------------------------------------------------------------
# Phase 1: DRAFTING — each agent scores the stock
# ---------------------------------------------------------------------------

def _draft_agent_scores(
    signals: List[AgentSignalInput],
) -> Dict[str, float]:
    """
    Convert input signals into raw agent scores (-1 to +1).

    Maps signal sources to committee agent roles:
      TECHNICAL      → TECHNICAL
      FUNDAMENTAL    → FUNDAMENTAL
      NEWS           → SENTIMENT
      MARKET_ACTIVITY → MACRO (IR page changes = macro-adjacent information)
    """
    source_to_agent = {
        "TECHNICAL": "TECHNICAL",
        "FUNDAMENTAL": "FUNDAMENTAL",
        "NEWS": "SENTIMENT",
        "MARKET_ACTIVITY": "MACRO",
    }

    scores = {}
    for signal in signals:
        agent_key = source_to_agent.get(signal.source.value, signal.source.value)
        scores[agent_key] = direction_to_score(signal.direction)

    # Ensure all 4 agents have scores (default 0 = HOLD if no signal)
    for key in ("TECHNICAL", "FUNDAMENTAL", "SENTIMENT", "MACRO"):
        scores.setdefault(key, 0.0)

    return scores


def _draft_agent_reasoning(
    signals: List[AgentSignalInput],
) -> Dict[str, str]:
    """Extract reasoning summaries from input signals."""
    source_to_agent = {
        "TECHNICAL": "TECHNICAL",
        "FUNDAMENTAL": "FUNDAMENTAL",
        "NEWS": "SENTIMENT",
        "MARKET_ACTIVITY": "MACRO",
    }
    reasoning = {}
    for signal in signals:
        agent_key = source_to_agent.get(signal.source.value, signal.source.value)
        factors = ", ".join(signal.key_factors) if signal.key_factors else ""
        reasoning[agent_key] = f"{signal.summary} [{factors}]" if factors else signal.summary

    for key in ("TECHNICAL", "FUNDAMENTAL", "SENTIMENT", "MACRO"):
        reasoning.setdefault(key, "No signal available")

    return reasoning


# ---------------------------------------------------------------------------
# Phase 2: CHALLENGE — red-team when agents disagree
# ---------------------------------------------------------------------------

def _identify_challenges(
    scores: Dict[str, float],
    threshold: float = 0.5,
) -> List[Tuple[str, str, float]]:
    """
    Find pairs of agents that disagree by more than threshold.

    Returns list of (agent_a, agent_b, disagreement_magnitude).
    """
    agents = list(scores.keys())
    challenges = []

    for i in range(len(agents)):
        for j in range(i + 1, len(agents)):
            a, b = agents[i], agents[j]
            diff = abs(scores[a] - scores[b])
            if diff > threshold:
                # The more extreme agent challenges the other
                challenges.append((a, b, diff))

    return sorted(challenges, key=lambda x: -x[2])  # most conflict first


async def _run_challenge_phase(
    ticker: str,
    exchange: str,
    draft_scores: Dict[str, float],
    draft_reasoning: Dict[str, str],
    challenges: List[Tuple[str, str, float]],
) -> Tuple[Dict[str, float], List[DebatePoint]]:
    """
    Run the challenge phase using LLM red-team prompts.

    For each disagreeing pair, asks the bearish agent to refute the bullish one.
    Returns revised scores and debate points.
    """
    revised_scores = dict(draft_scores)
    debate_points: List[DebatePoint] = []

    if not challenges:
        # No disagreement — skip challenge phase
        for agent, reasoning in draft_reasoning.items():
            debate_points.append(DebatePoint(
                agent=agent,
                argument=f"[DRAFT] Score: {draft_scores.get(agent, 0):.2f} — {reasoning}",
            ))
        return revised_scores, debate_points

    # Record draft phase debate points
    for agent, reasoning in draft_reasoning.items():
        debate_points.append(DebatePoint(
            agent=agent,
            argument=f"[DRAFT] Score: {draft_scores.get(agent, 0):.2f} — {reasoning}",
        ))

    try:
        from agents.llm_client import RouterChatClient
        client = RouterChatClient()

        # Load memory for challenge phase
        memory = _get_memory_store()
        situation = f"{ticker} on {exchange}, " + ", ".join(
            f"{k}={v:+.2f}" for k, v in draft_scores.items()
        )

        for agent_a, agent_b, disagreement in challenges[:3]:  # max 3 challenges
            # Determine which is bullish and which is bearish
            if draft_scores[agent_a] > draft_scores[agent_b]:
                bull_agent, bear_agent = agent_a, agent_b
            else:
                bull_agent, bear_agent = agent_b, agent_a

            # Get past lessons for the challenging (bear) agent
            bear_role = bear_agent.lower()
            if bear_role not in ("bull", "bear", "risk_manager", "portfolio_manager"):
                bear_role = "bear"  # default
            lessons = memory.format_lessons_for_prompt(bear_role, situation, n_memories=1, n_best=1)
            lessons_block = f"\n\n{lessons}\n" if lessons else ""

            # Red-team prompt
            prompt = (
                f"Stock: {ticker} ({exchange})\n\n"
                f"The {bull_agent} agent scored this stock {draft_scores[bull_agent]:+.2f} "
                f"(bullish) with reasoning: \"{draft_reasoning.get(bull_agent, 'N/A')}\"\n\n"
                f"The {bear_agent} agent scored this stock {draft_scores[bear_agent]:+.2f} "
                f"(bearish) with reasoning: \"{draft_reasoning.get(bear_agent, 'N/A')}\"\n"
                f"{lessons_block}\n"
                f"As the {bear_agent} analyst, refute the {bull_agent} agent's bullish thesis. "
                f"If past lessons are provided, factor them into your rebuttal. "
                f"Then provide your revised score (-1.0 to +1.0) as a single number on the last line.\n"
                f"Format: your argument, then on the last line just the number."
            )

            response = client.chat(
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract revised score from response
            if response:
                lines = response.strip().split("\n")
                # Try to get score from last line
                try:
                    revised = float(lines[-1].strip())
                    revised = max(-1.0, min(1.0, revised))
                    revised_scores[bear_agent] = revised
                except (ValueError, IndexError):
                    pass  # keep original score

                debate_points.append(DebatePoint(
                    agent=bear_agent,
                    argument=f"[CHALLENGE] vs {bull_agent}: {response[:400]}",
                    rebuttal_to=bull_agent,
                ))

    except Exception as exc:
        logger.warning("Challenge phase LLM call failed: %s — using draft scores", str(exc)[:200])

    return revised_scores, debate_points


# ---------------------------------------------------------------------------
# Phase 3: FINAL VOTE — regime-weighted consensus
# ---------------------------------------------------------------------------

def _compute_final_vote(
    revised_scores: Dict[str, float],
    regime_weights: Dict[str, float],
    macro_view: str,
    risk: RiskAssessment,
) -> Tuple[ConflictConsensus, SignalDirection, float, str]:
    """
    Compute final consensus with regime weighting and risk gating.

    Returns (consensus, direction, confidence, conviction).
    """
    consensus = compute_conflict_consensus(revised_scores, regime_weights, macro_view)

    direction = consensus.consensus_direction
    # Confidence: higher when agents agree, lower when they conflict
    base_confidence = (1.0 - consensus.conflict_level) * abs(consensus.consensus_score)
    confidence = max(0.1, min(0.95, base_confidence))

    # Risk gate: suppress BUY if risk is too high
    if risk.risk_score > 0.7 and direction in (SignalDirection.STRONG_BUY, SignalDirection.BUY):
        direction = SignalDirection.HOLD
        confidence *= 0.5
        logger.info("Risk gate activated: risk_score=%.2f, suppressing BUY → HOLD", risk.risk_score)

    # Reduce position for moderate risk
    if risk.risk_score > 0.5:
        confidence *= 0.8

    confidence = round(confidence, 4)

    # Conviction
    if confidence >= 0.7 and consensus.conflict_level < 0.3:
        conviction = "HIGH"
    elif confidence >= 0.4 or consensus.conflict_level < 0.5:
        conviction = "MEDIUM"
    else:
        conviction = "LOW"

    return consensus, direction, confidence, conviction


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_debate_consensus(
    ticker: str,
    exchange: str,
    signals: List[AgentSignalInput],
    regime_weights: Dict[str, float],
    macro_view: str,
    ta_data: Optional[Dict[str, Any]] = None,
    fa_data: Optional[Dict[str, Any]] = None,
    news_data: Optional[Dict[str, Any]] = None,
    sector: Optional[str] = None,
    current_price: Optional[float] = None,
) -> DebateResult:
    """
    Run the full Investment Committee debate.

    Parameters
    ----------
    ticker, exchange : str
        Stock identifier
    signals : list[AgentSignalInput]
        Input signals from TA, FA, MA, NEWS agents
    regime_weights : dict
        Agent weights from get_regime_weights()
    macro_view : str
        Regime label from classify_regime()
    ta_data : dict, optional
        Raw TA data for risk assessment
    fa_data : dict, optional
        Raw FA data for risk assessment
    news_data : dict, optional
        News data for risk and exit checks
    sector : str, optional
        Stock sector for risk cyclicality
    current_price : float, optional
        Current price for exit strategy levels

    Returns
    -------
    DebateResult
    """
    debate_phases: Dict[str, Any] = {}

    # ── Phase 1: DRAFTING ──
    draft_scores = _draft_agent_scores(signals)
    draft_reasoning = _draft_agent_reasoning(signals)
    debate_phases["draft"] = {"scores": dict(draft_scores), "reasoning": dict(draft_reasoning)}

    # ── Phase 2: CHALLENGE ──
    challenges = _identify_challenges(draft_scores)
    debate_phases["challenges_identified"] = len(challenges)

    revised_scores, debate_points = await _run_challenge_phase(
        ticker, exchange, draft_scores, draft_reasoning, challenges,
    )
    debate_phases["challenge"] = {
        "pairs": [(a, b, round(d, 2)) for a, b, d in challenges],
        "revised_scores": dict(revised_scores),
    }

    # ── Risk Agent ──
    risk = assess_risk(
        ta_data=ta_data or {},
        fa_data=fa_data,
        regime=macro_view,
        news_data=news_data,
        sector=sector,
    )

    # ── Phase 3: FINAL VOTE ──
    consensus, direction, confidence, conviction = _compute_final_vote(
        revised_scores, regime_weights, macro_view, risk,
    )
    debate_phases["vote"] = {
        "consensus_score": consensus.consensus_score,
        "conflict_level": consensus.conflict_level,
        "direction": direction.value,
        "confidence": confidence,
    }

    # ── Exit Strategy ──
    thresholds = get_thresholds("weeks")  # default timeframe
    exit_strategy = {
        "take_profit_pct": thresholds.take_profit_pct,
        "hard_stop_pct": thresholds.hard_stop_pct,
        "trailing_stop_pct": thresholds.trailing_stop_pct,
        "time_stop_days": thresholds.time_stop_days,
        "entry_price": current_price,
    }

    # ── Build thesis ──
    bull_agents = [k for k, v in revised_scores.items() if v > 0.1]
    bear_agents = [k for k, v in revised_scores.items() if v < -0.1]
    bull_reasoning = "; ".join(draft_reasoning[a] for a in bull_agents if a in draft_reasoning)
    bear_reasoning = "; ".join(draft_reasoning[a] for a in bear_agents if a in draft_reasoning)

    thesis_parts = []
    if direction in (SignalDirection.STRONG_BUY, SignalDirection.BUY):
        thesis_parts.append(f"Bullish consensus ({consensus.consensus_score:+.2f})")
    elif direction in (SignalDirection.STRONG_SELL, SignalDirection.SELL):
        thesis_parts.append(f"Bearish consensus ({consensus.consensus_score:+.2f})")
    else:
        thesis_parts.append(f"No clear direction ({consensus.consensus_score:+.2f})")

    if consensus.conflict_level > 0.5:
        thesis_parts.append(f"high conflict ({consensus.conflict_level:.2f})")
    thesis_parts.append(f"regime: {macro_view}")
    if risk.risk_score > 0.5:
        thesis_parts.append(f"elevated risk ({risk.risk_score:.2f})")

    thesis = ". ".join(thesis_parts) + "."

    # Per-source directions
    ta_dir = next((s.direction for s in signals if s.source.value == "TECHNICAL"), SignalDirection.HOLD)
    fa_dir = next((s.direction for s in signals if s.source.value == "FUNDAMENTAL"), SignalDirection.HOLD)
    ma_dir = next((s.direction for s in signals if s.source.value == "MARKET_ACTIVITY"), None)
    news_dir = next((s.direction for s in signals if s.source.value == "NEWS"), None)

    signals_aligned = consensus.conflict_level < 0.3

    # Key risk from risk agent
    key_risk = risk.risk_flags[0] if risk.risk_flags else "No significant risk flags"

    synthesis = StockSynthesis(
        ticker=ticker,
        exchange=exchange,
        direction=direction,
        confidence=confidence,
        conviction=conviction,
        thesis=thesis,
        what_bulls_say=bull_reasoning[:500] if bull_reasoning else "No bullish signals",
        what_bears_say=bear_reasoning[:500] if bear_reasoning else "No bearish signals",
        key_risk=key_risk,
        ta_direction=ta_dir,
        fa_direction=fa_dir,
        ma_direction=ma_dir,
        news_direction=news_dir,
        signals_aligned=signals_aligned,
        disagreement_summary=(
            f"Conflict level: {consensus.conflict_level:.2f}. "
            f"Agents: {', '.join(f'{k}={v:+.2f}' for k, v in revised_scores.items())}"
            if not signals_aligned else None
        ),
        debate_points=debate_points,
        debate_rounds=len(challenges) + 1,  # 1 draft round + N challenge rounds
        model_used=MODEL,
        total_tokens=0,
    )

    # ── Log debate to DB for future reflection ──
    try:
        memory = _get_memory_store()
        input_signals_dict = {}
        for s in signals:
            src = s.source.value if hasattr(s.source, 'value') else str(s.source)
            input_signals_dict[src] = {
                "direction": s.direction.value if hasattr(s.direction, 'value') else str(s.direction),
                "confidence": s.confidence,
                "summary": s.summary[:200],
            }

        bull_args = [dp.argument for dp in debate_points if "TECHNICAL" in dp.agent or "Bull" in dp.agent]
        bear_args = [dp.argument for dp in debate_points if "SENTIMENT" in dp.agent or "Bear" in dp.agent]
        risk_args = [dp.argument for dp in debate_points if "risk" in dp.agent.lower()]
        pm_args = [dp.argument for dp in debate_points if "MACRO" in dp.agent]

        from datetime import datetime as _dt
        memory.log_debate(
            ticker=ticker,
            exchange=exchange,
            debate_date=_dt.utcnow().date(),
            input_signals=input_signals_dict,
            direction=direction.value,
            confidence=confidence,
            thesis=thesis,
            recommendation=f"{direction.value} (conf={confidence:.2f}, {conviction})",
            bull_arguments=bull_args,
            bear_arguments=bear_args,
            risk_arguments=risk_args,
            pm_arguments=pm_args,
            regime=macro_view,
            quality_tier=None,
            conflict_level=consensus.conflict_level,
            agent_scores=revised_scores,
            debate_type="consensus_v2",
        )
    except Exception as exc:
        logger.warning("Failed to log consensus debate: %s", exc)

    return DebateResult(
        synthesis=synthesis,
        consensus=consensus,
        risk=risk,
        exit_strategy=exit_strategy,
        debate_phases=debate_phases,
    )
