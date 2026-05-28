"""
agents/stock_synthesis/contracts.py — Pydantic models for AG2 synthesis.
"""
from __future__ import annotations

from datetime import datetime, date
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class SignalDirection(str, Enum):
    """
    7-state direction enum (2026-05-28: added WATCH + AVOID).

    Why the extra two states:
      - HOLD historically meant "if you own it, keep it" — but for users
        WITHOUT a position, HOLD reads as "don't buy", which is muddy.
      - WATCH separates "we don't have conviction yet, monitor" from
        "we're confident this should stay flat".
      - AVOID separates "we see material risk — don't engage" from SELL
        (which presupposes a position to exit).

    Decision tree:
      conf < 0.50 AND signals not aligned          → WATCH
      CRITICAL negative news AND confidence < HIGH → AVOID
      everything else                              → existing 5 states
    """
    STRONG_BUY  = "STRONG_BUY"
    BUY         = "BUY"
    WATCH       = "WATCH"        # NEW: active deferral — monitor, no action yet
    HOLD        = "HOLD"         # if owned, keep it
    AVOID       = "AVOID"        # NEW: material risk — don't engage regardless of position
    SELL        = "SELL"
    STRONG_SELL = "STRONG_SELL"


class SignalSource(str, Enum):
    TECHNICAL = "TECHNICAL"      # TA agent (RSI, MACD, etc.)
    FUNDAMENTAL = "FUNDAMENTAL"  # FA agent (valuation, quality, growth)
    MARKET_ACTIVITY = "MARKET_ACTIVITY"  # TinyFish IR scan (guidance, risk, tone)
    NEWS = "NEWS"                # Breaking news / material events agent


class AgentSignalInput(BaseModel):
    """Input signal from one of the upstream agents (TA, FA, or MA)."""
    source: SignalSource
    direction: SignalDirection
    confidence: float = Field(ge=0.0, le=1.0, description="0-1 confidence")
    summary: str = Field(description="1-2 sentence signal summary")
    key_factors: List[str] = Field(default_factory=list, description="Key factors driving this signal")
    data: dict = Field(default_factory=dict, description="Raw data (scores, indicators, etc.)")


class DebatePoint(BaseModel):
    """A single point made during the AG2 multi-agent debate."""
    agent: str  # bull_analyst, bear_analyst, risk_manager
    argument: str
    supporting_evidence: List[str] = Field(default_factory=list)
    rebuttal_to: Optional[str] = None


class StockSynthesis(BaseModel):
    """Final synthesized recommendation from the AG2 debate."""
    ticker: str
    exchange: str

    # Unified recommendation
    direction: SignalDirection
    confidence: float = Field(ge=0.0, le=1.0)
    conviction: str = Field(description="HIGH / MEDIUM / LOW")

    # Thesis
    thesis: str = Field(description="2-3 sentence investment thesis explaining the recommendation")
    what_bulls_say: str = Field(description="Key bull argument")
    what_bears_say: str = Field(description="Key bear argument")
    key_risk: str = Field(description="Primary risk factor")

    # Signal breakdown
    ta_direction: SignalDirection
    fa_direction: SignalDirection
    ma_direction: Optional[SignalDirection] = None  # Market activity (TinyFish) — may not always have signal
    news_direction: Optional[SignalDirection] = None  # Breaking news / material events
    signals_aligned: bool = Field(description="True if all signals point same direction")
    disagreement_summary: Optional[str] = Field(
        default=None,
        description="Explains why signals disagree (only if signals_aligned=False)"
    )

    # Debate transcript (for transparency)
    debate_points: List[DebatePoint] = Field(default_factory=list)
    debate_rounds: int = Field(default=0, description="How many rounds of debate occurred")

    # ── Structured transparency (2026-05-28, migration 045) ──────────────
    # Drives the /ticker/[X]/intel "Behind the call" panel + /methodology page.
    # All three are stored as JSONB; default {} so older callers don't break.
    gate_decisions: dict = Field(
        default_factory=dict,
        description="Per-gate outcome: {quality_gate, regime_gate, sanity_override, critical_news} "
                    "each with {fired:bool, reason, demoted_from, demoted_to}",
    )
    agent_signals: dict = Field(
        default_factory=dict,
        description="Per-input-agent contribution: technical/fundamental/macro/market_activity/news "
                    "each with {direction, confidence, summary} + FA sub-agents",
    )
    reflector_lessons: dict = Field(
        default_factory=dict,
        description="Past lessons injected into agent prompts: {lessons_count, lessons:[...]}",
    )

    # ── Price snapshot (2026-05-28, migration 046) ───────────────────────
    # Frozen at write time so the /debate page always shows the EXACT price
    # the AI agents saw when they made the call. Independent of any future
    # price-table reloads, split adjustments, or source changes.
    price_at_debate: Optional[float] = Field(
        default=None,
        description="Close price the AI saw at synthesis time. NULL = lookup unavailable.",
    )
    price_currency: Optional[str] = Field(
        default=None,
        description="Best-effort currency code (USD/AUD/HKD/VND/…). Inferred from exchange.",
    )
    price_as_of_date: Optional[date] = Field(
        default=None,
        description="Trade date of the price_at_debate close. Usually = computed_at.date().",
    )

    # Metadata
    computed_at: datetime = Field(default_factory=datetime.utcnow)
    model_used: str = Field(default="gpt-4o-mini")
    total_tokens: int = Field(default=0)


# ---------------------------------------------------------------------------
# v2: ConsensusReport — persisted debate output
# ---------------------------------------------------------------------------

class ConsensusReport(BaseModel):
    """
    Persisted consensus report from the Investment Committee debate (v2).

    Stores regime-weighted consensus, conflict metrics, risk assessment,
    exit strategy, and full debate transcript for transparency.
    """
    ticker: str
    exchange: str
    macro_view: str = Field(description="Market regime: BULL_MOMENTUM / BEAR_RECESSION / NEUTRAL_TRANSITION")
    consensus_score: float = Field(ge=-1.0, le=1.0, description="Regime-weighted consensus (-1 to +1)")
    conflict_level: float = Field(ge=0.0, le=1.0, description="Agent disagreement (0=unanimous, 1=max)")
    consensus_direction: str = Field(description="Final direction: STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL")
    agent_scores: dict = Field(description="{TECHNICAL: 0.6, FUNDAMENTAL: -0.3, SENTIMENT: 0.2, MACRO: -0.1}")
    regime_weights: dict = Field(description="Weights applied per regime")
    risk_score: float = Field(ge=0.0, le=1.0, description="Quantitative risk (0=safe, 1=extreme)")
    risk_flags: List[str] = Field(default_factory=list, description="Active risk flags")
    position_size: str = Field(default="FULL", description="FULL/HALF/QUARTER/NONE")
    exit_strategy: dict = Field(default_factory=dict, description="Take profit / stop loss levels")
    debate_transcript: str = Field(default="", description="Full debate text for transparency")
    debate_phases: dict = Field(default_factory=dict, description="Draft/challenge/vote details")
    computed_at: datetime = Field(default_factory=datetime.utcnow)
