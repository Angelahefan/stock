"""
agents/stock_synthesis/synthesis_pipeline.py
─────────────────────────────────────────────────────────────────────────────
AG2 multi-agent debate for synthesizing conflicting stock signals.

When TA says BUY, FA says SELL, and TinyFish IR says RISK — this pipeline
runs a structured debate between Bull/Bear/Risk/Portfolio agents to produce
a unified recommendation.

Usage:
    from agents.stock_synthesis import run_synthesis, AgentSignalInput

    signals = [ta_signal, fa_signal, ma_signal]
    result = await run_synthesis("BHP", "ASX", signals)
    print(result.direction, result.thesis)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import List, Optional, Tuple, Any

from agents.stock_synthesis.agent_prompts import (
    BEAR_ANALYST_PROMPT,
    BULL_ANALYST_PROMPT,
    PORTFOLIO_MANAGER_PROMPT,
    RISK_MANAGER_PROMPT,
)
from agents.stock_synthesis.contracts import (
    AgentSignalInput,
    DebatePoint,
    SignalDirection,
    StockSynthesis,
)

logger = logging.getLogger(__name__)

# Lazy-loaded singleton memory store
_memory_store = None


def _get_memory_store():
    """Lazy-load agent memory store (singleton)."""
    global _memory_store
    if _memory_store is None:
        try:
            from agents.stock_synthesis.memory import AgentMemoryStore
            _memory_store = AgentMemoryStore.from_env()
            _memory_store.load()
            logger.info("Agent memory loaded: %s", _memory_store.stats())
        except Exception as exc:
            logger.warning("Agent memory unavailable: %s — debate will run without memory", exc)
            from agents.stock_synthesis.memory import AgentMemoryStore
            _memory_store = AgentMemoryStore()  # in-memory fallback
    return _memory_store


def _build_situation_context(ticker: str, exchange: str, signals: list) -> str:
    """Build a situation description from current signals for memory lookup."""
    parts = [f"{ticker} on {exchange}"]
    for s in signals:
        src = s.source.value if hasattr(s.source, 'value') else str(s.source)
        direction = s.direction.value if hasattr(s.direction, 'value') else str(s.direction)
        parts.append(f"{src}={direction}(conf={s.confidence:.0%})")
    return ", ".join(parts)

# LLM config — uses the same RouterChatClient pattern as other agents
MODEL = os.getenv("SYNTHESIS_MODEL", "gemini-2.5-flash")
MAX_DEBATE_ROUNDS = 1  # Bull → Bear → Risk → PM (1 round = 4 messages, ~2-4 min/ticker)
# 2026-05-24: trimmed from 2 → 1. With Gemini latency a 2-round debate took
# 4-9 min/ticker and the nightly 50-ticker batch ran ~6h, hitting timeouts.
# 1 round = single pass: each role speaks once based on initial signals.
# We lose the PM "refinement after hearing Bull/Bear iterate" round; the
# trade-off is throughput. Reflector compounding gives us iterative
# improvement over time which is more valuable than per-debate iteration.


def _format_signals_context(
    ticker: str,
    exchange: str,
    signals: List[AgentSignalInput],
) -> str:
    """Format all input signals into a context string for the debate."""
    lines = [
        f"Stock: {ticker} ({exchange})",
        f"Date: {datetime.utcnow().strftime('%Y-%m-%d')}",
        "",
        "=== SIGNAL SUMMARY ===",
    ]
    for s in signals:
        lines.append(f"\n--- {s.source.value} ---")
        lines.append(f"Direction: {s.direction.value}")
        lines.append(f"Confidence: {s.confidence:.0%}")
        lines.append(f"Summary: {s.summary}")
        if s.key_factors:
            lines.append(f"Key factors: {', '.join(s.key_factors)}")
        if s.data:
            # Include key metrics
            for k, v in s.data.items():
                if v is not None:
                    lines.append(f"  {k}: {v}")
    return "\n".join(lines)


async def run_synthesis(
    ticker: str,
    exchange: str,
    signals: List[AgentSignalInput],
    model: Optional[str] = None,
) -> StockSynthesis:
    """
    Run AG2 multi-agent debate to synthesize conflicting stock signals.

    Args:
        ticker: Stock symbol (e.g. "BHP")
        exchange: Exchange code ("ASX" or "US")
        signals: List of input signals from TA, FA, and MA agents
        model: LLM model override (default: gpt-4o-mini)

    Returns:
        StockSynthesis with unified recommendation
    """
    use_model = model or MODEL
    context = _format_signals_context(ticker, exchange, signals)
    debate_points: List[DebatePoint] = []
    total_tokens = 0

    # Check signal alignment
    directions = [s.direction for s in signals]
    buy_signals = sum(1 for d in directions if d in (SignalDirection.STRONG_BUY, SignalDirection.BUY))
    sell_signals = sum(1 for d in directions if d in (SignalDirection.STRONG_SELL, SignalDirection.SELL))
    signals_aligned = buy_signals == len(directions) or sell_signals == len(directions)

    # Extract per-source directions
    ta_dir = next((s.direction for s in signals if s.source.value == "TECHNICAL"), SignalDirection.HOLD)
    fa_dir = next((s.direction for s in signals if s.source.value == "FUNDAMENTAL"), SignalDirection.HOLD)
    ma_dir = next((s.direction for s in signals if s.source.value == "MARKET_ACTIVITY"), None)
    news_dir = next((s.direction for s in signals if s.source.value == "NEWS"), None)

    # Check for CRITICAL news events
    news_signal = next((s for s in signals if s.source.value == "NEWS"), None)
    has_critical_news = (
        news_signal is not None
        and news_signal.data.get("has_critical_event") is True
    )

    try:
        from autogen import ConversableAgent, GroupChat, GroupChatManager

        # ── Inject agent memory ──
        memory = _get_memory_store()
        situation = _build_situation_context(ticker, exchange, signals)
        bull_lessons = memory.format_lessons_for_prompt("bull", situation, n_memories=2, n_best=2)
        bear_lessons = memory.format_lessons_for_prompt("bear", situation, n_memories=2, n_best=2)
        risk_lessons = memory.format_lessons_for_prompt("risk_manager", situation, n_memories=2, n_best=2)
        pm_lessons = memory.format_lessons_for_prompt("portfolio_manager", situation, n_memories=2, n_best=2)

        # Build llm_config. Gemini is the default — see gemini_ag2_client.py
        # for why we use a custom ModelClient (AG2 0.5.3's native api_type=google
        # requires google-generativeai>=0.3 which needs Python 3.9+, but EC2 is
        # pinned to 3.8.20 → ancient SDK missing `Content` symbol → silent
        # fallback for 2 months). The custom client wraps GoogleChatClient
        # (pure HTTP — same path the chat bot uses successfully every day).
        # Build llm_config — per-persona max_tokens caps to stop verbose
        # essay-style responses. Empirically (2026-05-24 instrumentation) the
        # uncapped run took 297s for 15 calls with outputs of 7-30K chars.
        # Capping at 400/400/300/600 tokens (~300/300/225/450 words) trims
        # generation latency from 20-35s/call to 5-12s/call.
        _llm_provider = os.environ.get("LLM_PRIMARY_PROVIDER", "google").lower()
        _custom_client_cls = None  # set when we need to register_model_client

        def _cfg(max_tokens: int = 800):
            if _llm_provider == "google":
                from agents.stock_synthesis.gemini_ag2_client import (
                    GeminiHTTPModelClient,
                    build_llm_config,
                )
                # Side-effect: cache the class so we can register_model_client below
                nonlocal _custom_client_cls
                _custom_client_cls = GeminiHTTPModelClient
                return build_llm_config(model=use_model, temperature=0.3, max_tokens=max_tokens)
            if _llm_provider == "bedrock":
                return {
                    "config_list": [{
                        "model": use_model,
                        "aws_region": os.environ.get("BEDROCK_REGION", "ap-southeast-2"),
                        "api_type": "bedrock",
                    }],
                    "temperature": 0.3,
                }
            return {
                "config_list": [{
                    "model": use_model,
                    "api_key": os.environ.get("OPENAI_API_KEY", ""),
                    "max_tokens": max_tokens,
                }],
                "temperature": 0.3,
            }

        # 2026-05-24 v3: tight Bull/Bear/Risk at 200 (≈150 words / 3-4
        # short sentences). PM at 600 — empirically 400 truncated the JSON
        # mid-string (PM output stopped at `"confidence` before completing
        # the schema). 600 fits the 7-field envelope with concise content.
        # Manager at 100 (rarely speaks).
        bull = ConversableAgent(
            name="Bull_Analyst",
            system_message=BULL_ANALYST_PROMPT.format(past_lessons=bull_lessons),
            llm_config=_cfg(max_tokens=200),
            human_input_mode="NEVER",
        )
        bear = ConversableAgent(
            name="Bear_Analyst",
            system_message=BEAR_ANALYST_PROMPT.format(past_lessons=bear_lessons),
            llm_config=_cfg(max_tokens=200),
            human_input_mode="NEVER",
        )
        risk_mgr = ConversableAgent(
            name="Risk_Manager",
            system_message=RISK_MANAGER_PROMPT.format(past_lessons=risk_lessons),
            llm_config=_cfg(max_tokens=200),
            human_input_mode="NEVER",
        )
        portfolio_mgr = ConversableAgent(
            name="Portfolio_Manager",
            system_message=PORTFOLIO_MANAGER_PROMPT.format(past_lessons=pm_lessons),
            llm_config=_cfg(max_tokens=600),
            human_input_mode="NEVER",
        )

        # Group chat with structured turn order.
        # max_round = 4 agents × rounds + 1 (kickoff). With ROUNDS=1 that's 5.
        # Hard-cap regardless of MAX_DEBATE_ROUNDS to prevent the "15 calls
        # for 4 speakers" runaway observed before (AG2 GroupChatManager
        # re-invites agents past the round boundary).
        groupchat = GroupChat(
            agents=[bull, bear, risk_mgr, portfolio_mgr],
            messages=[],
            max_round=MAX_DEBATE_ROUNDS * 4 + 1,
            speaker_selection_method="round_robin",
        )
        manager = GroupChatManager(
            groupchat=groupchat,
            llm_config=_cfg(max_tokens=100),  # manager rarely speaks, keep tiny
        )

        # Register the custom Gemini-over-HTTP client on every agent that has
        # an LLM. AG2 stores a placeholder until register_model_client is
        # called with a class whose __name__ matches model_client_cls.
        if _custom_client_cls is not None:
            for _agent in (bull, bear, risk_mgr, portfolio_mgr, manager):
                try:
                    _agent.register_model_client(model_client_cls=_custom_client_cls)
                except Exception as _reg_exc:
                    logger.warning(
                        "register_model_client failed on %s: %s",
                        getattr(_agent, "name", _agent.__class__.__name__),
                        str(_reg_exc)[:200],
                    )

        # Kick off the debate
        # Build initial message with CRITICAL news alert if applicable
        critical_alert = ""
        if has_critical_news and news_signal:
            critical_alert = (
                f"\n\n*** CRITICAL NEWS ALERT ***\n"
                f"A CRITICAL severity material event has been detected.\n"
                f"Highest severity: {news_signal.data.get('highest_severity', 'UNKNOWN')}\n"
                f"Sentiment: {news_signal.data.get('overall_sentiment', 'UNKNOWN')}\n"
                f"Event: {news_signal.data.get('top_event_headline', 'Unknown event')}\n"
                f"This MUST be the primary factor in your analysis.\n"
                f"*** END CRITICAL ALERT ***\n"
            )

        initial_message = (
            f"We need to debate and reach a consensus on {ticker} ({exchange}).\n\n"
            f"{context}{critical_alert}\n\n"
            f"Signals are {'ALIGNED' if signals_aligned else 'CONFLICTING'}. "
            f"Bull Analyst, please start."
        )

        await bull.a_initiate_chat(
            manager,
            message=initial_message,
            max_turns=MAX_DEBATE_ROUNDS * 4,
        )

        # Extract debate points from chat history.
        # NOTE: AG2's GroupChat tags every message with role='user' (not
        # 'assistant') because each agent's output is consumed by the next
        # as user input. We previously filtered role=='assistant' → ZERO
        # captures → bull_arguments/bear_arguments arrays always empty →
        # Reflector starved. Filter on `name` instead (every speaker has it).
        for msg in groupchat.messages:
            name = msg.get("name")
            content = msg.get("content")
            if name and content and isinstance(content, str) and content.strip():
                debate_points.append(DebatePoint(
                    agent=name,
                    argument=content[:500],
                ))

        # Extract Portfolio Manager's final JSON recommendation
        pm_messages = [
            m for m in groupchat.messages
            if m.get("name") == "Portfolio_Manager"
        ]

        if pm_messages:
            pm_response = pm_messages[-1]["content"]
            # Try to parse JSON from PM response
            recommendation = _extract_json(pm_response)
        else:
            recommendation = None

        # ── Guardrail (2026-05-24) — refuse partial/truncated PM JSON ──
        # `_extract_json` has a "bare pairs" fallback that matches
        # `"direction":"BUY"` and `"confidence":0.5` from truncated text and
        # returns an incomplete dict. We previously silently accepted these
        # — produced rows with thesis="" and bogus BUY/SELL/HOLD signals
        # that looked like real decisions. Now: incomplete = treated as
        # debate failure → fall through to _fallback_synthesis (single LLM)
        # which always produces a complete recommendation.
        if recommendation and not _is_complete_recommendation(recommendation):
            missing = [k for k in ("direction", "thesis", "what_bulls_say",
                                   "what_bears_say", "key_risk")
                       if not (recommendation.get(k) or "").strip()]
            logger.warning(
                "[%s/%s] PM JSON incomplete (missing: %s) — discarding partial "
                "recommendation and falling back to single-LLM synthesis. "
                "PM raw response head: %r",
                ticker, exchange, ", ".join(missing),
                (pm_response if pm_messages else "")[:200],
            )
            recommendation = None  # force fall-through below

    except ImportError as ie:
        # 2026-05-28: promoted INFO→ERROR + include full exception repr.
        # This is the exact log line that would have caught the original
        # 2-month silent ImportError ("cannot import name 'Content' from
        # 'google.ai.generativelanguage'") — the previous wording
        # "AG2/autogen not installed" hid the real failure mode by
        # implying the fallback was expected. It wasn't.
        logger.error(
            "[%s/%s] AG2 import path unavailable: %s — falling back to single-LLM. "
            "If this fires for >20%% of tickers in a batch, INVESTIGATE.",
            ticker, exchange, repr(ie),
        )
        recommendation, debate_points = await _fallback_synthesis(
            ticker, exchange, context, signals_aligned, use_model
        )
    except Exception as exc:
        # Same hardening for non-ImportError failures (e.g. Gemini API down)
        logger.error(
            "[%s/%s] AG2 debate failed: %s — falling back to single-LLM. "
            "If this fires for >20%% of tickers in a batch, INVESTIGATE.",
            ticker, exchange, repr(exc)[:300],
        )
        recommendation, debate_points = await _fallback_synthesis(
            ticker, exchange, context, signals_aligned, use_model
        )

    # If AG2 produced no usable recommendation (e.g. incomplete JSON above
    # set recommendation=None after the try block ran cleanly), try the
    # single-LLM fallback once.
    if recommendation is None and debate_points:
        # debate_points populated → debate ran; only PM JSON was bad. Retry.
        logger.info("[%s/%s] Retrying via single-LLM synthesis after PM JSON failure", ticker, exchange)
        recommendation, _fb_points = await _fallback_synthesis(
            ticker, exchange, context, signals_aligned, use_model
        )
        # Keep debate_points from the AG2 run for Reflector; append fallback
        debate_points.extend(_fb_points or [])

    # ── Post-debate Quality + Regime gates (backtest-proven, +~8% win rate) ──
    # Applied to BUY/STRONG_BUY signals only. Demote to HOLD if:
    #   1. quality_tier in {C, D}
    #   2. NOT (is_profitable AND is_growing AND is_healthy)
    #   3. Regime proxy: TA + FA both bearish
    # Fail-open: missing quality row → gate is a no-op.
    #
    # 2026-05-28: also build structured `gate_decisions` dict for the
    # "Behind the call" UI panel (migration 045 added the JSONB column).
    gate_notes: List[str] = []
    gate_decisions: dict = {
        "quality_gate":    {"fired": False},
        "regime_gate":     {"fired": False},
        "sanity_override": {"fired": False},  # populated lower down in sanity-check block
        "critical_news":   {"fired": False},  # populated in CRITICAL news override block
    }
    if recommendation and recommendation.get("direction") in ("BUY", "STRONG_BUY"):
        original_direction = recommendation.get("direction")
        quality = await _get_quality_for_gate(ticker, exchange)
        if quality:
            qt = (quality.get("quality_tier") or "").upper()
            if qt in ("C", "D"):
                gate_notes.append(f"[Quality gate] Demoted BUY → HOLD (quality tier {qt})")
                gate_decisions["quality_gate"] = {
                    "fired": True,
                    "reason": f"quality_tier={qt}",
                    "quality_tier": qt,
                    "demoted_from": original_direction,
                    "demoted_to": "HOLD",
                }
                recommendation["direction"]  = "HOLD"
                recommendation["confidence"] = max(0.3, float(recommendation.get("confidence", 0.5)) - 0.3)
                recommendation["conviction"] = "LOW"
            elif not (quality.get("is_profitable") and quality.get("is_growing") and quality.get("is_healthy")):
                failing = [k for k in ("is_profitable", "is_growing", "is_healthy") if not quality.get(k)]
                gate_notes.append(f"[Quality gate] Demoted BUY → HOLD (failed: {', '.join(failing)})")
                gate_decisions["quality_gate"] = {
                    "fired": True,
                    "reason": f"failed_checks={','.join(failing)}",
                    "failed_checks": failing,
                    "demoted_from": original_direction,
                    "demoted_to": "HOLD",
                }
                recommendation["direction"]  = "HOLD"
                recommendation["confidence"] = max(0.3, float(recommendation.get("confidence", 0.5)) - 0.2)
                recommendation["conviction"] = "LOW"
        if recommendation.get("direction") in ("BUY", "STRONG_BUY"):
            if ta_dir == SignalDirection.SELL and fa_dir == SignalDirection.SELL:
                gate_notes.append("[Regime gate] Demoted BUY → HOLD (TA + FA both SELL — bearish regime)")
                gate_decisions["regime_gate"] = {
                    "fired": True,
                    "reason": "TA+FA both SELL (bearish regime)",
                    "ta_direction": ta_dir.value,
                    "fa_direction": fa_dir.value,
                    "demoted_from": original_direction,
                    "demoted_to": "HOLD",
                }
                recommendation["direction"]  = "HOLD"
                recommendation["confidence"] = max(0.3, float(recommendation.get("confidence", 0.5)) - 0.2)
                recommendation["conviction"] = "LOW"
        if gate_notes:
            logger.info("[%s/%s] post-debate gates fired: %s", ticker, exchange, " | ".join(gate_notes))

    # Build final result
    if recommendation:
        direction = SignalDirection(recommendation.get("direction", "HOLD"))
        confidence = float(recommendation.get("confidence", 0.5))
        conviction = recommendation.get("conviction", "MEDIUM")
        thesis = recommendation.get("thesis", "")
        what_bulls_say = recommendation.get("what_bulls_say", "")
        what_bears_say = recommendation.get("what_bears_say", "")
        key_risk = recommendation.get("key_risk", "")
        # Surface gate-firing reason so the UI shows WHY the BUY was demoted.
        if gate_notes:
            gate_text = " ".join(gate_notes)
            key_risk = (key_risk + " · " + gate_text) if key_risk else gate_text
    else:
        # Default to HOLD if debate produced no result
        direction = SignalDirection.HOLD
        confidence = 0.3
        conviction = "LOW"
        thesis = "Insufficient signal clarity for a directional call."
        what_bulls_say = ""
        what_bears_say = ""
        key_risk = "Conflicting signals with no clear resolution"

    # CRITICAL news event override (2026-05-28: emits AVOID for non-position
    # holders instead of SELL — semantically cleaner).
    if has_critical_news and news_signal:
        news_sentiment = news_signal.data.get("overall_sentiment", "NEUTRAL")
        headline = news_signal.data.get("top_event_headline", "Unknown")
        _pre_dir = direction
        if "NEGATIVE" in news_sentiment.upper():
            # For non-holders, AVOID is the right call (you can't sell what
            # you don't own). For users who likely DO hold (HIGH conviction
            # BUY recently), STRONG_SELL is still appropriate — but until we
            # have per-user position context, default to AVOID.
            if direction not in (SignalDirection.SELL, SignalDirection.STRONG_SELL):
                direction = SignalDirection.AVOID
                thesis = (
                    f"CRITICAL material event override: {headline}. "
                    + thesis
                )
            confidence = max(confidence, 0.85)
            conviction = "HIGH"
        elif "POSITIVE" in news_sentiment.upper():
            # Boost buy confidence
            if direction in (SignalDirection.HOLD, SignalDirection.WATCH, SignalDirection.BUY):
                direction = SignalDirection.BUY
            confidence = max(confidence, 0.80)
        key_risk = f"CRITICAL NEWS: {headline}"
        # Structured record for FE
        gate_decisions["critical_news"] = {
            "fired": True,
            "sentiment": news_sentiment,
            "headline": headline[:300],
            "severity": news_signal.data.get("highest_severity", "UNKNOWN"),
            "demoted_from": _pre_dir.value,
            "demoted_to": direction.value,
        }

    # ── AVOID always conviction=HIGH (2026-05-28) ──────────────────────
    # AVOID is a protective call — material risk like fraud/bankruptcy/
    # sanctions. There's no such thing as "low-conviction AVOID" semantically:
    # if you can't tell whether to engage, that's WATCH. AVOID requires
    # certainty that the risk is material. Force HIGH conviction so the UI
    # doesn't show "AVOID with LOW conviction" — confusing to users.
    if direction == SignalDirection.AVOID and conviction != "HIGH":
        logger.info("[%s/%s] AVOID forced to HIGH conviction (was %s)",
                    ticker, exchange, conviction)
        conviction = "HIGH"
        confidence = max(confidence, 0.85)

    # ── Low-confidence HOLD → WATCH demotion (2026-05-28) ──────────────
    # HOLD has a specific meaning: "the signal IS to keep the current state."
    # When PM emits HOLD with confidence < 0.5 AND signals not aligned, it's
    # not actually a HOLD recommendation — it's "we don't have conviction
    # either way." That's WATCH, not HOLD. The semantic distinction matters
    # for the user: WATCH = "we'll tell you when conviction firms up";
    # HOLD = "stay where you are, this is the action."
    if direction == SignalDirection.HOLD and confidence < 0.50 and not signals_aligned:
        logger.info("[%s/%s] low-conviction HOLD (conf=%.2f, signals not aligned) → WATCH",
                    ticker, exchange, confidence)
        gate_decisions["hold_to_watch"] = {
            "fired": True,
            "reason": f"confidence={confidence:.2f} < 0.50 AND signals not aligned",
            "demoted_from": "HOLD",
            "demoted_to": "WATCH",
        }
        direction = SignalDirection.WATCH
        conviction = "LOW"
        key_risk = key_risk or "Signals not yet clear — monitoring for a better setup."

    # Disagreement summary
    disagreement = None
    if not signals_aligned:
        source_dirs = [f"{s.source.value}={s.direction.value}" for s in signals]
        disagreement = f"Signals diverge: {', '.join(source_dirs)}"

    # ── Sanity check (2026-05-24) — flag impossible direction flips ──
    # If TA, FA, and News all agree bearish (SELL/STRONG_SELL) but the LLM
    # said BUY/STRONG_BUY (or vice versa), that's a near-certain reasoning
    # error or JSON-parse artefact. Don't silently emit garbage; demote to
    # HOLD and stamp key_risk so downstream sees the override.
    #
    # 2026-05-28: WATCH + AVOID exempt from this check — both are *defensive*
    # outcomes, so AVOID on all-bearish signals is the RIGHT call, not an
    # impossible flip. WATCH likewise just defers; no contradiction.
    _input_dirs = [s.direction for s in signals]
    _all_bearish = all(d in (SignalDirection.SELL, SignalDirection.STRONG_SELL) for d in _input_dirs) and _input_dirs
    _all_bullish = all(d in (SignalDirection.BUY, SignalDirection.STRONG_BUY) for d in _input_dirs) and _input_dirs
    if direction in (SignalDirection.WATCH, SignalDirection.AVOID):
        pass  # both states are inherently consistent with any signal mix
    elif _all_bearish and direction in (SignalDirection.BUY, SignalDirection.STRONG_BUY):
        logger.warning("[%s/%s] SANITY OVERRIDE: all signals bearish but LLM said %s → demoting to HOLD",
                       ticker, exchange, direction.value)
        gate_decisions["sanity_override"] = {
            "fired": True,
            "reason": "all_input_signals_bearish_but_pm_said_buy",
            "input_directions": [d.value for d in _input_dirs],
            "demoted_from": direction.value,
            "demoted_to": "HOLD",
        }
        direction = SignalDirection.HOLD
        confidence = min(confidence, 0.4)
        conviction = "LOW"
        key_risk = f"[Sanity override] All input signals bearish but PM emitted BUY — flagged as inconsistent. {key_risk}"
    elif _all_bullish and direction in (SignalDirection.SELL, SignalDirection.STRONG_SELL):
        logger.warning("[%s/%s] SANITY OVERRIDE: all signals bullish but LLM said %s → demoting to HOLD",
                       ticker, exchange, direction.value)
        gate_decisions["sanity_override"] = {
            "fired": True,
            "reason": "all_input_signals_bullish_but_pm_said_sell",
            "input_directions": [d.value for d in _input_dirs],
            "demoted_from": direction.value,
            "demoted_to": "HOLD",
        }
        direction = SignalDirection.HOLD
        confidence = min(confidence, 0.4)
        conviction = "LOW"
        key_risk = f"[Sanity override] All input signals bullish but PM emitted SELL — flagged as inconsistent. {key_risk}"

    # ── Log debate to DB for future reflection ──
    try:
        memory = _get_memory_store()
        bull_args = [dp.argument for dp in debate_points if "Bull" in dp.agent]
        bear_args = [dp.argument for dp in debate_points if "Bear" in dp.agent]
        risk_args = [dp.argument for dp in debate_points if "Risk" in dp.agent]
        pm_args = [dp.argument for dp in debate_points if "Portfolio" in dp.agent or "pm" in dp.agent.lower()]

        input_signals_dict = {}
        for s in signals:
            src = s.source.value if hasattr(s.source, 'value') else str(s.source)
            input_signals_dict[src] = {
                "direction": s.direction.value if hasattr(s.direction, 'value') else str(s.direction),
                "confidence": s.confidence,
                "summary": s.summary[:200],
            }

        memory.log_debate(
            ticker=ticker,
            exchange=exchange,
            debate_date=datetime.utcnow().date(),
            input_signals=input_signals_dict,
            direction=direction.value if hasattr(direction, 'value') else str(direction),
            confidence=confidence,
            thesis=thesis,
            recommendation=f"{direction.value if hasattr(direction, 'value') else direction} (conf={confidence:.2f}, {conviction})",
            bull_arguments=bull_args,
            bear_arguments=bear_args,
            risk_arguments=risk_args,
            pm_arguments=pm_args,
        )
    except Exception as exc:
        logger.warning("Failed to log debate: %s", exc)

    # ── Snapshot the price the AI saw (migration 046) ──────────────────────
    # Frozen here so the /debate page can never display a "wrong" price even
    # if datapai.prices gets reloaded with corrections later. Single source
    # of truth = the row we're about to write.
    snap_price, snap_currency, snap_date = await _get_price_snapshot(ticker, exchange)
    if snap_price is not None:
        logger.info("[%s/%s] price snapshot: %s%.2f as of %s",
                    ticker, exchange, snap_currency or "", snap_price, snap_date)

    # ── Build structured agent_signals for the FE transparency panel ────────
    # Each input agent (TA / FA / Macro / Market Activity / News) contributes
    # a record: direction + confidence + summary + key data points.
    agent_signals: dict = {}
    for s in signals:
        src = (s.source.value if hasattr(s.source, "value") else str(s.source)).lower()
        agent_signals[src] = {
            "direction": s.direction.value if hasattr(s.direction, "value") else str(s.direction),
            "confidence": round(float(s.confidence), 3),
            "summary": (s.summary or "")[:300],
            "data": s.data if isinstance(s.data, dict) else {},
        }

    # Reflector lessons that fed into this debate (best-effort — depends on
    # AgentMemoryStore.format_lessons_for_prompt having been called above).
    reflector_lessons: dict = {}
    try:
        if "memory" in locals() and "situation" in locals():
            # Pull a flat list of lessons across personas for display
            all_lessons: list[str] = []
            for role in ("bull", "bear", "risk_manager", "portfolio_manager"):
                try:
                    txt = memory.format_lessons_for_prompt(role, situation, n_memories=2, n_best=1)
                    # format_lessons_for_prompt returns prose; pluck non-empty lines
                    for line in (txt or "").splitlines():
                        line = line.strip("- •*\t ")
                        if line and len(line) > 25 and not line.startswith(("Past", "Lessons", "No prior")):
                            all_lessons.append(f"[{role}] {line[:300]}")
                except Exception:
                    pass
            # Dedup
            seen = set(); uniq = []
            for l in all_lessons:
                if l not in seen:
                    seen.add(l); uniq.append(l)
            if uniq:
                reflector_lessons = {"lessons_count": len(uniq), "lessons": uniq[:8]}
    except Exception as exc:
        logger.debug("reflector_lessons assembly failed: %s", exc)

    return StockSynthesis(
        ticker=ticker,
        exchange=exchange,
        direction=direction,
        confidence=confidence,
        conviction=conviction,
        thesis=thesis,
        what_bulls_say=what_bulls_say,
        what_bears_say=what_bears_say,
        key_risk=key_risk,
        ta_direction=ta_dir,
        fa_direction=fa_dir,
        ma_direction=ma_dir,
        news_direction=news_dir,
        signals_aligned=signals_aligned,
        disagreement_summary=disagreement,
        debate_points=debate_points,
        debate_rounds=MAX_DEBATE_ROUNDS,
        # ── new structured transparency fields (migration 045) ──
        gate_decisions=gate_decisions,
        agent_signals=agent_signals,
        reflector_lessons=reflector_lessons,
        # ── price snapshot (migration 046) ──
        price_at_debate=snap_price,
        price_currency=snap_currency,
        price_as_of_date=snap_date,
        model_used=use_model,
        total_tokens=total_tokens,
    )


def _extract_json(text) -> Optional[dict]:
    """Extract a JSON object from an LLM reply.

    Defensive: accepts either a string OR the {role,content,model,usage}
    dict that RouterChatClient.chat() returns (this was the silent killer
    that turned every fallback into HOLD/0.3/LOW for 2 months — the
    fallback re.search() threw TypeError because we passed a dict).

    Tries, in order:
      1. Already-parsed dict → return as-is
      2. Direct json.loads
      3. ```json ... ``` markdown block
      4. ``` ... ``` markdown block (no language tag)
      5. Greedy outermost { ... } match
      6. Last-resort: synthesise an object from `"key": "value"` pairs
         when the LLM forgot the wrapping braces (the literal symptom
         we saw: PM emitted `\n    "direction": "BUY", ...`).
    Returns None if nothing parses.
    """
    import re

    # Coerce to string — accept dict {content:...}, list of blocks, raw str
    if text is None:
        return None
    if isinstance(text, dict):
        if "content" in text and isinstance(text["content"], str):
            text = text["content"]
        else:
            # Already-parsed JSON-looking dict — return only if it looks like
            # a recommendation envelope.
            if "direction" in text:
                return text
            return None
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return None

    raw = text.strip()

    # 1. Direct json.loads
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. ```json ... ``` markdown block
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Greedy outermost { ... }
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            # Try trimming trailing commas then re-parse
            cleaned = re.sub(r",\s*(\}|\])", r"\1", m.group(0))
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

    # 4. Last resort — bare `"key": "value"` pairs without enclosing braces.
    #    Symptom seen in production: PM emitted lines like
    #        \n    "direction": "HOLD",
    #        \n    "confidence": 0.5,
    #    Build a dict from the first set of quoted-key pairs we can find.
    pair_pattern = re.compile(r'"(direction|confidence|conviction|thesis|what_bulls_say|what_bears_say|key_risk)"\s*:\s*("(?:[^"\\]|\\.)*"|[\d.]+|true|false|null)')
    pairs = pair_pattern.findall(raw)
    if pairs:
        out: dict = {}
        for key, val in pairs:
            try:
                out[key] = json.loads(val)
            except json.JSONDecodeError:
                continue
        if out.get("direction"):
            return out

    return None


def _is_complete_recommendation(rec: dict) -> bool:
    """
    A PM recommendation is "complete" only if direction is a recognized
    enum value AND the three narrative fields (thesis, what_bulls_say,
    what_bears_say, key_risk) have non-trivial content (>=20 chars each).

    Why this matters: Gemini 2.5's thinking budget can truncate the JSON
    mid-string. Our `_extract_json` has a bare-pairs fallback that picks up
    `"direction":"BUY"` from `{"direction":"BUY","confidence":0.5,` even
    though the rest of the JSON never came. Returning such a partial dict
    produces convincing-looking BUY/SELL signals with empty thesis — exactly
    the kind of silent garbage that pollutes win-rate metrics.
    """
    if not isinstance(rec, dict):
        return False
    direction = (rec.get("direction") or "").upper().strip()
    # 2026-05-28: WATCH + AVOID added to the valid set. Without them in this
    # whitelist, any PM JSON emitting the new states gets rejected here and
    # falls through to single-LLM fallback synthesis. Quiet but lethal bug.
    if direction not in ("STRONG_BUY", "BUY", "HOLD", "WATCH", "AVOID", "SELL", "STRONG_SELL"):
        return False
    for narrative_field in ("thesis", "what_bulls_say", "what_bears_say", "key_risk"):
        val = (rec.get(narrative_field) or "").strip()
        if len(val) < 20:
            return False
    return True


async def _get_price_snapshot(ticker: str, exchange: str) -> Tuple[Optional[float], Optional[str], Optional[Any]]:
    """
    Return (close_price, currency, as_of_date) for the latest available
    close in datapai.prices. Frozen at synthesis time so the /debate page
    can always show "the price the AI agents saw" without re-querying.

    Fails soft → (None, None, None) on any error.
    """
    # Currency hint by exchange (best-effort, no FX implied)
    currency_map = {
        "US": "USD", "ASX": "AUD", "HKEX": "HKD", "HOSE": "VND",
        "SET": "THB", "KLSE": "MYR", "IDX": "IDR", "SGX": "SGD",
        "TSE": "JPY", "TWSE": "TWD", "LSE": "GBP", "SSE": "CNY", "SZSE": "CNY",
    }
    currency = currency_map.get(exchange.upper())

    # FE uses datapai.prices (the unified table) — match its lookup so the
    # snapshot agrees with anything else that reads from the same source.
    # Ticker may have an exchange suffix in some pipelines (BHP.AX, VIC.VN);
    # we try the bare ticker first, then the suffixed form.
    suffix_map = {"ASX": ".AX", "HOSE": ".VN", "HKEX": ".HK", "SET": ".BK",
                  "KLSE": ".KL", "IDX": ".JK", "SSE": ".SS", "SZSE": ".SZ", "LSE": ".L"}
    suffix = suffix_map.get(exchange.upper(), "")
    candidates = [ticker]
    if suffix and not ticker.endswith(suffix):
        candidates.append(f"{ticker}{suffix}")

    try:
        from scripts.lib.db_helpers import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                for cand in candidates:
                    cur.execute(
                        "SELECT close, trade_date FROM datapai.prices "
                        "WHERE ticker = %s ORDER BY trade_date DESC LIMIT 1",
                        (cand,),
                    )
                    row = cur.fetchone()
                    if row and row[0] is not None:
                        return float(row[0]), currency, row[1]
    except Exception as exc:
        logger.debug("price snapshot lookup failed for %s/%s: %s", ticker, exchange, str(exc)[:120])
    return None, currency, None


async def _get_quality_for_gate(ticker: str, exchange: str) -> Optional[dict]:
    """Single-shot read of quality fields from fundamental_lite used by the
    post-debate Quality Gate. Returns None on failure so the gate becomes a
    no-op (fail-open — never refuse to emit a signal because the quality
    table is unreachable)."""
    try:
        from scripts.lib.db_helpers import get_conn
        import psycopg2.extras
        conn = get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT quality_tier, is_profitable, is_growing, is_healthy "
                    "FROM datapai.fundamental_lite "
                    "WHERE ticker = %s AND exchange = %s LIMIT 1",
                    (ticker, exchange),
                )
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as exc:
        logger.debug("quality gate lookup failed for %s/%s: %s", ticker, exchange, str(exc)[:120])
        return None


async def _fallback_synthesis(
    ticker: str,
    exchange: str,
    context: str,
    signals_aligned: bool,
    model: str,
) -> tuple[Optional[dict], List[DebatePoint]]:
    """
    Fallback: single LLM call to synthesize signals when AG2 isn't available.
    Still produces a structured recommendation, just without the multi-agent debate.
    """
    try:
        from agents.llm_client import RouterChatClient

        client = RouterChatClient()
        # 2026-05-28: 7-state vocabulary — WATCH for honest deferral (no
        # conviction), AVOID for material risk (don't engage). Earlier
        # 5-state prompt forced this fallback path to emit HOLD when the
        # right call was actually WATCH or AVOID.
        prompt = (
            f"You are a senior portfolio manager. Analyze these signals for {ticker} ({exchange}) "
            f"and produce a unified recommendation.\n\n"
            f"{context}\n\n"
            f"Signals are {'ALIGNED' if signals_aligned else 'CONFLICTING'}.\n\n"
            f"Pick direction from this 7-state set:\n"
            f"  STRONG_BUY / BUY  — enter the position\n"
            f"  HOLD              — keep current position (signal IS to stay put, with conviction)\n"
            f"  WATCH             — no conviction yet; monitor + revisit (use when signals are mixed and confidence < 0.5)\n"
            f"  AVOID             — material risk; don't engage (fraud/bankruptcy/sanctions/major-lawsuit)\n"
            f"  SELL / STRONG_SELL — exit the position\n\n"
            f"Respond with ONLY valid JSON:\n"
            f'{{"direction": "STRONG_BUY|BUY|HOLD|WATCH|AVOID|SELL|STRONG_SELL", '
            f'"confidence": 0.0-1.0, "conviction": "HIGH|MEDIUM|LOW", '
            f'"thesis": "...", "what_bulls_say": "...", '
            f'"what_bears_say": "...", "key_risk": "..."}}'
        )

        response = client.chat(
            messages=[{"role": "user", "content": prompt}],
        )
        # RouterChatClient.chat() returns {role, content, model, usage, ...}
        # — NOT a bare string. Extract content for both JSON parsing and the
        # debate-point preview. Previously we passed the dict to _extract_json
        # and to str-slicing, throwing TypeError and silently producing the
        # HOLD/0.3/LOW default for every ticker.
        content = ""
        if isinstance(response, dict):
            content = str(response.get("content") or "")
        elif isinstance(response, str):
            content = response
        recommendation = _extract_json(content)
        debate_points = [DebatePoint(
            agent="portfolio_manager_fallback",
            argument=content[:500] if content else "No response",
        )]
        return recommendation, debate_points
    except Exception as exc:
        logger.error("Fallback synthesis failed: %s", str(exc)[:200])
        return None, []
