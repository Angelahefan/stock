"""
agents/stock_synthesis — AG2 multi-agent stock signal synthesis.

v1: 4-agent round-robin debate (Bull/Bear/Risk/PM)
v2: Investment Committee pattern with regime-aware consensus,
    quantitative risk gating, and exit strategy management.

Agents (v2):
    - Technical Agent: TA indicators (RSI, MACD, etc.)
    - Fundamental Agent: valuation, quality, growth
    - Sentiment Agent: news/material events
    - Macro Agent: regime classification + geopolitical context
    - Risk Agent: quantitative risk scoring + entry gate
    - Exit Agent: take-profit / stop-loss / trailing stop

Output: StockSynthesis + ConsensusReport
"""

from agents.stock_synthesis.synthesis_pipeline import run_synthesis
from agents.stock_synthesis.contracts import (
    StockSynthesis,
    AgentSignalInput,
    ConsensusReport,
)
from agents.stock_synthesis.debate_consensus import run_debate_consensus, DebateResult
from agents.stock_synthesis.conflict_meter import (
    compute_conflict_consensus,
    compute_conflict_from_signals,
    ConflictConsensus,
)
from agents.stock_synthesis.risk_agent import assess_risk, RiskAssessment
from agents.stock_synthesis.exit_agent import check_exit, ExitSignal
from agents.stock_synthesis.memory import AgentMemoryStore
from agents.stock_synthesis.reflector import Reflector

__all__ = [
    # v1 (backward compatible)
    "run_synthesis",
    "StockSynthesis",
    "AgentSignalInput",
    # v2
    "run_debate_consensus",
    "DebateResult",
    "ConsensusReport",
    "compute_conflict_consensus",
    "compute_conflict_from_signals",
    "ConflictConsensus",
    "assess_risk",
    "RiskAssessment",
    "check_exit",
    "ExitSignal",
    # v3 — Agent Memory & Reflection
    "AgentMemoryStore",
    "Reflector",
]
