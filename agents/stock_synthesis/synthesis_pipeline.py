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
from typing import List, Optional

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
MAX_DEBATE_ROUNDS = 2  # Bull → Bear → Risk → PM (2 rounds = 8 messages)


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

        # Create agents with memory-injected prompts
        # Build llm_config in AG2 v0.5+ config_list format so we can route to
        # the same Gemini provider the chat endpoint + RouterChatClient already
        # use, instead of AG2 silently falling back to OpenAI's default client
        # (which needs OPENAI_API_KEY and would explain 2 months of "AG2 debate
        # failed: ... — falling back" log lines).
        #
        # LLM_PRIMARY_PROVIDER drives the choice: google (default), openai,
        # bedrock. The fallback path (RouterChatClient) follows the same env.
        _llm_provider = os.environ.get("LLM_PRIMARY_PROVIDER", "google").lower()
        if _llm_provider == "google":
            llm_config = {
                "config_list": [{
                    "model": use_model,
                    "api_key": os.environ.get("GOOGLE_API_KEY", ""),
                    "api_type": "google",
                }],
                "temperature": 0.3,
            }
        elif _llm_provider == "bedrock":
            llm_config = {
                "config_list": [{
                    "model": use_model,
                    "aws_region": os.environ.get("BEDROCK_REGION", "ap-southeast-2"),
                    "api_type": "bedrock",
                }],
                "temperature": 0.3,
            }
        else:
            # OpenAI default — original behaviour
            llm_config = {
                "config_list": [{
                    "model": use_model,
                    "api_key": os.environ.get("OPENAI_API_KEY", ""),
                }],
                "temperature": 0.3,
            }

        bull = ConversableAgent(
            name="Bull_Analyst",
            system_message=BULL_ANALYST_PROMPT.format(past_lessons=bull_lessons),
            llm_config=llm_config,
            human_input_mode="NEVER",
        )
        bear = ConversableAgent(
            name="Bear_Analyst",
            system_message=BEAR_ANALYST_PROMPT.format(past_lessons=bear_lessons),
            llm_config=llm_config,
            human_input_mode="NEVER",
        )
        risk_mgr = ConversableAgent(
            name="Risk_Manager",
            system_message=RISK_MANAGER_PROMPT.format(past_lessons=risk_lessons),
            llm_config=llm_config,
            human_input_mode="NEVER",
        )
        portfolio_mgr = ConversableAgent(
            name="Portfolio_Manager",
            system_message=PORTFOLIO_MANAGER_PROMPT.format(past_lessons=pm_lessons),
            llm_config=llm_config,
            human_input_mode="NEVER",
        )

        # Group chat with structured turn order
        groupchat = GroupChat(
            agents=[bull, bear, risk_mgr, portfolio_mgr],
            messages=[],
            max_round=MAX_DEBATE_ROUNDS * 4 + 1,  # 4 agents × rounds + initial
            speaker_selection_method="round_robin",
        )
        manager = GroupChatManager(
            groupchat=groupchat,
            llm_config=llm_config,
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

        # Extract debate points from chat history
        for msg in groupchat.messages:
            if msg.get("role") == "assistant" and msg.get("name"):
                debate_points.append(DebatePoint(
                    agent=msg["name"],
                    argument=msg["content"][:500],
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

    except ImportError:
        logger.warning("AG2/autogen not installed — falling back to single-LLM synthesis")
        recommendation, debate_points = await _fallback_synthesis(
            ticker, exchange, context, signals_aligned, use_model
        )
    except Exception as exc:
        logger.error("AG2 debate failed: %s — falling back", str(exc)[:200])
        recommendation, debate_points = await _fallback_synthesis(
            ticker, exchange, context, signals_aligned, use_model
        )

    # Build final result
    if recommendation:
        direction = SignalDirection(recommendation.get("direction", "HOLD"))
        confidence = float(recommendation.get("confidence", 0.5))
        conviction = recommendation.get("conviction", "MEDIUM")
        thesis = recommendation.get("thesis", "")
        what_bulls_say = recommendation.get("what_bulls_say", "")
        what_bears_say = recommendation.get("what_bears_say", "")
        key_risk = recommendation.get("key_risk", "")
    else:
        # Default to HOLD if debate produced no result
        direction = SignalDirection.HOLD
        confidence = 0.3
        conviction = "LOW"
        thesis = "Insufficient signal clarity for a directional call."
        what_bulls_say = ""
        what_bears_say = ""
        key_risk = "Conflicting signals with no clear resolution"

    # CRITICAL news event override: boost confidence and bias toward event direction
    if has_critical_news and news_signal:
        news_sentiment = news_signal.data.get("overall_sentiment", "NEUTRAL")
        if "NEGATIVE" in news_sentiment.upper():
            # Force SELL direction with high confidence
            if direction not in (SignalDirection.SELL, SignalDirection.STRONG_SELL):
                direction = SignalDirection.SELL
                thesis = (
                    f"CRITICAL material event override: {news_signal.data.get('top_event_headline', 'Unknown')}. "
                    + thesis
                )
            confidence = max(confidence, 0.85)
            conviction = "HIGH"
        elif "POSITIVE" in news_sentiment.upper():
            # Boost buy confidence
            if direction in (SignalDirection.HOLD, SignalDirection.BUY):
                direction = SignalDirection.BUY
            confidence = max(confidence, 0.80)
        key_risk = f"CRITICAL NEWS: {news_signal.data.get('top_event_headline', key_risk)}"

    # Disagreement summary
    disagreement = None
    if not signals_aligned:
        source_dirs = [f"{s.source.value}={s.direction.value}" for s in signals]
        disagreement = f"Signals diverge: {', '.join(source_dirs)}"

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
        prompt = (
            f"You are a senior portfolio manager. Analyze these signals for {ticker} ({exchange}) "
            f"and produce a unified recommendation.\n\n"
            f"{context}\n\n"
            f"Signals are {'ALIGNED' if signals_aligned else 'CONFLICTING'}.\n\n"
            f"Respond with ONLY valid JSON:\n"
            f'{{"direction": "BUY|SELL|HOLD|STRONG_BUY|STRONG_SELL", '
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
