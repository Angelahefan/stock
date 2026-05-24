"""
agents/stock_synthesis/reflector.py
─────────────────────────────────────────────────────────────────────────────
Post-trade reflection agent — evaluates debate outcomes and writes lessons
into agent memory for continuous improvement.

Inspired by TradingAgents (TauricResearch) reflection system, adapted for
DataPAI's architecture (RouterChatClient, Postgres-backed memory, regime-aware).

Two entry points:
  1. reflect_on_debate()  — single debate reflection (called per debate)
  2. reflect_pending()    — batch process all un-evaluated debates (Airflow daily)

Usage:
    from agents.stock_synthesis.reflector import Reflector
    from agents.stock_synthesis.memory import AgentMemoryStore

    store = AgentMemoryStore.from_env()
    store.load()
    reflector = Reflector(store)

    # Single debate
    await reflector.reflect_on_debate(debate_id=42, actual_returns={"7d": -2.1, "30d": 5.3, "90d": 12.0})

    # Batch (Airflow)
    await reflector.reflect_pending()
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from agents.stock_synthesis.memory import AgentMemoryStore

logger = logging.getLogger(__name__)

# Agent roles we reflect on (must match agent_role values in sys_agent_memory)
DEBATE_ROLES = ["bull", "bear", "risk_manager", "portfolio_manager"]

REFLECTION_PROMPT = """You are reflecting on a past trading debate as the {role} agent.

## Context
- Ticker: {ticker} ({exchange})
- Debate date: {debate_date}
- Regime at time: {regime}
- Your debate direction: {direction}
- Your arguments: {agent_arguments}
- Input signals: {input_signals}

## Actual Outcome
- 7-day return: {return_7d}
- 30-day return: {return_30d}
- 90-day return: {return_90d}
- The debate call was: {correctness}

## Your Task
Write a concise lesson (2-3 sentences) that your future self should remember when encountering a similar situation. Focus on:
1. What signals you over/under-weighted
2. What you would do differently
3. What pattern to watch for next time

Be specific and actionable. Reference the actual signal values and regime context.
Do NOT include preamble or headers — just the lesson text."""


class Reflector:
    """Post-trade reflection agent that writes lessons into agent memory."""

    def __init__(self, memory_store: AgentMemoryStore, llm_client=None):
        """
        Parameters
        ----------
        memory_store : AgentMemoryStore
            Must be loaded and connected to Postgres.
        llm_client : RouterChatClient or None
            If None, will create one on demand.
        """
        self.memory = memory_store
        self._llm = llm_client

    def _get_llm(self):
        """Lazy-load LLM client."""
        if self._llm is None:
            from agents.llm_client import RouterChatClient
            self._llm = RouterChatClient()
        return self._llm

    def _evaluate_correctness(self, direction: str, actual_returns: Dict[str, float]) -> str:
        """Determine if the debate call was correct based on actual returns."""
        ret_30d = actual_returns.get("30d", 0)
        ret_90d = actual_returns.get("90d")

        # Use 90d if available, else 30d
        primary_return = ret_90d if ret_90d is not None else ret_30d

        buy_directions = {"STRONG_BUY", "BUY"}
        sell_directions = {"STRONG_SELL", "SELL"}

        if direction in buy_directions:
            if primary_return > 5:
                return "CORRECT — stock gained significantly"
            elif primary_return > 0:
                return "PARTIALLY CORRECT — stock gained modestly"
            else:
                return f"WRONG — stock dropped {primary_return:+.1f}%"
        elif direction in sell_directions:
            if primary_return < -5:
                return "CORRECT — stock dropped significantly"
            elif primary_return < 0:
                return "PARTIALLY CORRECT — stock dropped modestly"
            else:
                return f"WRONG — stock gained {primary_return:+.1f}%"
        else:  # HOLD
            if abs(primary_return) < 10:
                return "CORRECT — stock stayed range-bound"
            else:
                return f"WRONG — stock moved {primary_return:+.1f}% (should not have held)"

    def _was_correct_bool(self, direction: str, actual_returns: Dict[str, float]) -> bool:
        """Simple boolean: did the direction align with the 30d return?"""
        ret = actual_returns.get("30d", 0)
        if direction in ("STRONG_BUY", "BUY"):
            return ret > 0
        elif direction in ("STRONG_SELL", "SELL"):
            return ret < 0
        else:
            return abs(ret) < 10

    def _build_situation_text(self, debate: dict) -> str:
        """Build a situation description from a debate log row."""
        parts = [f"{debate['ticker']} on {debate['exchange']}"]
        if debate.get("regime"):
            parts.append(f"regime={debate['regime']}")
        if debate.get("quality_tier"):
            parts.append(f"quality={debate['quality_tier']}")

        signals = debate.get("input_signals") or {}
        if isinstance(signals, str):
            try:
                signals = json.loads(signals)
            except (json.JSONDecodeError, TypeError):
                signals = {}

        for src in ["fa", "FUNDAMENTAL", "ta", "TECHNICAL", "tinyfish", "MARKET_ACTIVITY", "news", "NEWS"]:
            s = signals.get(src)
            if s and isinstance(s, dict):
                sig = s.get("signal") or s.get("direction", "?")
                score = s.get("score") or s.get("confidence", "?")
                parts.append(f"{src}={sig}(score={score})")

        return ", ".join(parts)

    def _extract_tags(self, debate: dict) -> List[str]:
        """Extract tags from a debate for memory tagging."""
        tags = []
        if debate.get("regime"):
            tags.append(f"regime:{debate['regime']}")
        if debate.get("quality_tier"):
            tags.append(f"quality:{debate['quality_tier']}")
        if debate.get("direction"):
            tags.append(f"direction:{debate['direction']}")
        return tags

    async def reflect_on_debate(
        self,
        debate_id: int,
        actual_returns: Dict[str, float],
    ) -> List[int]:
        """
        Reflect on a single debate and write lessons into memory.

        Parameters
        ----------
        debate_id : int
            ID from sys_agent_debate_log
        actual_returns : dict
            {"7d": float, "30d": float, "90d": float}

        Returns
        -------
        List of memory IDs created.
        """
        if not self.memory._conn:
            logger.warning("No DB connection — skipping reflection")
            return []

        # Load debate
        cur = self.memory._conn.cursor()
        cur.execute(
            "SELECT ticker, exchange, debate_date, direction, confidence, thesis, "
            "bull_arguments, bear_arguments, risk_arguments, pm_arguments, "
            "input_signals, regime, quality_tier "
            "FROM datapai.sys_agent_debate_log_full WHERE id = %s",
            (debate_id,),
        )
        row = cur.fetchone()
        if not row:
            logger.warning("Debate #%d not found", debate_id)
            cur.close()
            return []

        cols = [d[0] for d in cur.description]
        debate = dict(zip(cols, row))
        cur.close()

        direction = debate["direction"]
        correctness = self._evaluate_correctness(direction, actual_returns)
        was_correct = self._was_correct_bool(direction, actual_returns)
        situation = self._build_situation_text(debate)
        tags = self._extract_tags(debate)

        # Map roles to their argument columns
        role_args = {
            "bull": debate.get("bull_arguments") or [],
            "bear": debate.get("bear_arguments") or [],
            "risk_manager": debate.get("risk_arguments") or [],
            "portfolio_manager": debate.get("pm_arguments") or [],
        }

        llm = self._get_llm()
        memory_ids = []
        lessons = []

        for role in DEBATE_ROLES:
            args = role_args.get(role, [])
            args_text = "\n".join(args) if isinstance(args, list) else str(args)

            if not args_text.strip():
                continue

            # Format input signals for prompt
            signals_text = json.dumps(debate.get("input_signals") or {}, indent=2, default=str)

            prompt = REFLECTION_PROMPT.format(
                role=role,
                ticker=debate["ticker"],
                exchange=debate["exchange"],
                debate_date=debate.get("debate_date", "unknown"),
                regime=debate.get("regime", "unknown"),
                direction=direction,
                agent_arguments=args_text[:1000],
                input_signals=signals_text[:1000],
                return_7d=f"{actual_returns.get('7d', 0):+.1f}%",
                return_30d=f"{actual_returns.get('30d', 0):+.1f}%",
                return_90d=f"{actual_returns.get('90d', 0):+.1f}%" if actual_returns.get("90d") is not None else "N/A",
                correctness=correctness,
            )

            try:
                lesson = llm.chat(messages=[{"role": "user", "content": prompt}])
                if not lesson or not lesson.strip():
                    continue
            except Exception as exc:
                logger.warning("LLM reflection failed for %s: %s", role, exc)
                continue

            # Determine outcome
            outcome = "CORRECT" if was_correct else "WRONG"
            if "PARTIALLY" in correctness:
                outcome = "PARTIAL"

            outcome_detail = (
                f"7d:{actual_returns.get('7d', 0):+.1f}%, "
                f"30d:{actual_returns.get('30d', 0):+.1f}%, "
                f"90d:{actual_returns.get('90d', 0):+.1f}%"
                if actual_returns.get("90d") is not None
                else f"7d:{actual_returns.get('7d', 0):+.1f}%, 30d:{actual_returns.get('30d', 0):+.1f}%"
            )

            mem_id = self.memory.add_memory(
                agent_role=role,
                ticker=debate["ticker"],
                exchange=debate["exchange"],
                situation=situation,
                recommendation=lesson.strip(),
                outcome=outcome,
                outcome_detail=outcome_detail,
                confidence=0.7 if was_correct else 0.5,
                source="reflection",
                tags=tags,
            )
            if mem_id:
                memory_ids.append(mem_id)
            lessons.append(lesson.strip()[:200])

        # Update debate log with actuals
        self.memory.update_debate_actuals(
            debate_id=debate_id,
            actual_return_7d=actual_returns.get("7d"),
            actual_return_30d=actual_returns.get("30d"),
            actual_return_90d=actual_returns.get("90d"),
            was_correct=was_correct,
            lessons_extracted=lessons,
        )

        logger.info(
            "Reflected on debate #%d (%s/%s): %s, %d memories created",
            debate_id, debate["ticker"], debate["exchange"], correctness, len(memory_ids),
        )
        return memory_ids

    async def reflect_pending(self, min_age_days: int = 7) -> int:
        """
        Batch-process all un-evaluated debates older than min_age_days.

        Called by Airflow daily EOD task.
        Returns total memories created.
        """
        if not self.memory._conn:
            logger.warning("No DB connection — skipping batch reflection")
            return 0

        cutoff = date.today() - timedelta(days=min_age_days)

        cur = self.memory._conn.cursor()
        cur.execute(
            "SELECT id, ticker, exchange, debate_date, direction "
            "FROM datapai.sys_agent_debate_log_full "
            "WHERE was_correct IS NULL AND debate_date <= %s "
            "ORDER BY debate_date",
            (cutoff,),
        )
        pending = cur.fetchall()
        cols = [d[0] for d in cur.description]
        cur.close()

        if not pending:
            logger.info("No pending debates to reflect on")
            return 0

        logger.info("Found %d pending debates for reflection", len(pending))
        total_memories = 0

        for row in pending:
            debate = dict(zip(cols, row))
            # Fetch actual returns from price data
            actual = await self._fetch_actual_returns(
                debate["ticker"], debate["exchange"], debate["debate_date"]
            )
            if actual is None:
                continue

            mem_ids = await self.reflect_on_debate(debate["id"], actual)
            total_memories += len(mem_ids)

        logger.info("Batch reflection complete: %d memories from %d debates", total_memories, len(pending))
        return total_memories

    async def _fetch_actual_returns(
        self, ticker: str, exchange: str, debate_date
    ) -> Optional[Dict[str, float]]:
        """Fetch actual forward returns from price data."""
        try:
            from agents.data_providers import get_provider
            import pandas as pd

            suffix = ".AX" if exchange == "ASX" else ""
            provider = get_provider("yahoo")
            df = provider.fetch(ticker, "1d", suffix)

            if df is None or df.empty:
                return None

            # Find the debate date row
            if isinstance(debate_date, str):
                debate_date = datetime.strptime(debate_date, "%Y-%m-%d").date()

            df.index = pd.to_datetime(df.index).date
            if debate_date not in df.index:
                # Find nearest date
                dates = sorted(df.index)
                closest = min(dates, key=lambda d: abs((d - debate_date).days))
                if abs((closest - debate_date).days) > 5:
                    return None
                debate_date = closest

            debate_idx = list(df.index).index(debate_date)
            base_price = df.iloc[debate_idx]["Close"]
            if base_price <= 0:
                return None

            returns = {}
            for label, offset in [("7d", 5), ("30d", 22), ("90d", 63)]:
                idx = debate_idx + offset
                if idx < len(df):
                    returns[label] = round(((df.iloc[idx]["Close"] - base_price) / base_price) * 100, 2)

            return returns if returns else None
        except Exception as exc:
            logger.warning("Failed to fetch actual returns for %s/%s: %s", ticker, exchange, exc)
            return None

    async def promote_to_best_results(self, min_evidence: int = 10, min_success_rate: float = 0.65):
        """
        Scan sys_agent_memory for patterns with high evidence and promote
        to sys_agent_results. This is the "wisdom distillation" step.
        """
        if not self.memory._conn:
            return

        cur = self.memory._conn.cursor()
        # Group by agent_role + tag patterns, count outcomes
        cur.execute("""
            SELECT agent_role,
                   unnest(tags) as tag,
                   COUNT(*) as total,
                   COUNT(*) FILTER (WHERE outcome = 'CORRECT') as correct,
                   COUNT(*) FILTER (WHERE outcome = 'WRONG') as wrong
            FROM datapai.sys_agent_memory
            WHERE is_active = TRUE AND outcome != 'PENDING'
            GROUP BY agent_role, tag
            HAVING COUNT(*) >= %s
            ORDER BY COUNT(*) DESC
        """, (min_evidence,))

        patterns = cur.fetchall()
        cur.close()

        promoted = 0
        for role, tag, total, correct, wrong in patterns:
            success_rate = correct / total if total > 0 else 0
            if success_rate < min_success_rate:
                continue

            # Generate a best-result summary using LLM
            key_prefix, key_val = tag.split(":", 1) if ":" in tag else ("tag", tag)
            result_key = f"{role}/{tag}"

            # Fetch sample memories for this pattern
            sample_cur = self.memory._conn.cursor()
            sample_cur.execute(
                "SELECT recommendation FROM datapai.sys_agent_memory "
                "WHERE agent_role = %s AND %s = ANY(tags) AND outcome = 'CORRECT' "
                "ORDER BY confidence DESC NULLS LAST LIMIT 5",
                (role, tag),
            )
            samples = [r[0] for r in sample_cur.fetchall()]
            sample_cur.close()

            if not samples:
                continue

            # Synthesize a best result
            title = f"Pattern: {role} + {tag} ({correct}/{total} correct, {success_rate:.0%})"
            lesson = "\n---\n".join(samples[:3])

            self.memory.upsert_best_result(
                result_key=result_key,
                agent_role=role,
                category="auto_promoted",
                title=title,
                lesson_text=lesson[:2000],
                evidence_count=total,
                success_rate=round(success_rate, 3),
                applicable_when={key_prefix: [key_val]},
                priority=min(95, 50 + total),
            )
            promoted += 1

        logger.info("Promoted %d patterns to best results", promoted)
