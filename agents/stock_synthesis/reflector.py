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

    # ── Horizon-specific thresholds (2026-05-28) ─────────────────────────
    # 7d  is noisier — wider HOLD band, smaller "significant" cutoff
    # 30d is medium-term — standard equity-research thresholds
    # 90d is long-term — fundamentals dominate, larger HOLD band acceptable
    _HORIZON_THRESHOLDS = {
        7:  {"significant": 3.0,  "hold_band": 5.0},
        30: {"significant": 5.0,  "hold_band": 10.0},
        90: {"significant": 8.0,  "hold_band": 15.0},
    }

    def _evaluate_correctness_for_horizon(
        self, direction: str, return_pct: Optional[float], horizon_days: int
    ) -> str:
        """Correctness for ONE horizon. Returns prose for the LLM prompt.

        7 directions supported (2026-05-28: WATCH + AVOID added):
          STRONG_BUY / BUY     → correct if stock rose
          HOLD                 → correct if stock stayed within band
          WATCH                → correct if NOT a big move (similar to HOLD;
                                 we said "no conviction either way" — being
                                 right means the deferral was warranted)
          AVOID                → correct if stock flat or DROPPED
                                 (we said "don't engage" — being right
                                  means avoiding the position paid off)
          SELL / STRONG_SELL   → correct if stock dropped
        """
        if return_pct is None:
            return f"N/A — {horizon_days}d return not yet available"
        thr = self._HORIZON_THRESHOLDS.get(horizon_days, self._HORIZON_THRESHOLDS[30])
        sig = thr["significant"]
        band = thr["hold_band"]

        buy = {"STRONG_BUY", "BUY"}
        sell = {"STRONG_SELL", "SELL"}

        if direction in buy:
            if return_pct > sig:    return f"CORRECT — gained {return_pct:+.1f}% over {horizon_days}d"
            if return_pct > 0:      return f"PARTIALLY CORRECT — modest gain {return_pct:+.1f}% over {horizon_days}d"
            return f"WRONG — dropped {return_pct:+.1f}% over {horizon_days}d"
        if direction in sell:
            if return_pct < -sig:   return f"CORRECT — dropped {return_pct:+.1f}% over {horizon_days}d"
            if return_pct < 0:      return f"PARTIALLY CORRECT — modest drop {return_pct:+.1f}% over {horizon_days}d"
            return f"WRONG — gained {return_pct:+.1f}% over {horizon_days}d"
        if direction == "AVOID":
            # AVOID is "don't engage" — correct if you'd have saved yourself
            # from a flat or down stock. Wrong if a big rally happened.
            if return_pct <= sig:   return f"CORRECT — AVOID held: stock returned {return_pct:+.1f}% over {horizon_days}d"
            return f"WRONG — AVOID missed: stock rallied {return_pct:+.1f}% over {horizon_days}d"
        if direction == "WATCH":
            # WATCH = "no conviction; monitor." Correct when nothing dramatic
            # happens (stock stays range-bound). Wrong if the market provided
            # a clear setup we should have caught.
            if abs(return_pct) < band:
                return f"CORRECT — WATCH held: stock range-bound {return_pct:+.1f}% over {horizon_days}d"
            direction_word = "rallied" if return_pct > 0 else "dropped"
            return f"WRONG — WATCH missed: stock {direction_word} {return_pct:+.1f}% (should have called {'BUY' if return_pct > 0 else 'SELL'})"
        # HOLD (default branch)
        if abs(return_pct) < band:  return f"CORRECT — range-bound {return_pct:+.1f}% over {horizon_days}d"
        return f"WRONG — moved {return_pct:+.1f}% over {horizon_days}d (should not have held)"

    def _was_correct_bool_for_horizon(
        self, direction: str, return_pct: Optional[float], horizon_days: int
    ) -> Optional[bool]:
        """Boolean for `was_correct_Nd` column. None if return not available."""
        if return_pct is None:
            return None
        thr  = self._HORIZON_THRESHOLDS.get(horizon_days, self._HORIZON_THRESHOLDS[30])
        sig  = thr["significant"]
        band = thr["hold_band"]
        if direction in ("STRONG_BUY", "BUY"):
            return return_pct > 0
        if direction in ("STRONG_SELL", "SELL"):
            return return_pct < 0
        if direction == "AVOID":
            return return_pct <= sig            # flat or down = AVOID was right
        if direction == "WATCH":
            return abs(return_pct) < band       # range-bound = deferral was warranted
        # HOLD
        return abs(return_pct) < band

    # ── Backward-compat wrappers (kept for callers using the old API) ────
    def _evaluate_correctness(self, direction: str, actual_returns: Dict[str, float]) -> str:
        """Legacy single-string correctness. Prefers 90d → 30d → 7d."""
        for h in (90, 30, 7):
            r = actual_returns.get(f"{h}d")
            if r is not None:
                return self._evaluate_correctness_for_horizon(direction, r, h)
        return "N/A — no realised returns yet"

    def _was_correct_bool(self, direction: str, actual_returns: Dict[str, float]) -> bool:
        """Legacy single-bool. Uses 30d if available, else 7d."""
        for h in (30, 7):
            r = actual_returns.get(f"{h}d")
            if r is not None:
                return bool(self._was_correct_bool_for_horizon(direction, r, h))
        return False

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
        horizon_days: Optional[int] = None,
    ) -> List[int]:
        """
        Reflect on a single debate and write lessons into memory.

        Parameters
        ----------
        debate_id : int
            ID from sys_agent_debate_log
        actual_returns : dict
            {"7d": float, "30d": float, "90d": float}
        horizon_days : Optional[int]
            7, 30, or 90 — which horizon to grade against and tag lessons
            with. If None, falls back to legacy single-horizon behaviour
            (prefers 90d → 30d → 7d).

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

        # Per-horizon evaluation — drives lesson content + correctness flag
        if horizon_days in (7, 30, 90):
            ret_for_horizon = actual_returns.get(f"{horizon_days}d")
            correctness = self._evaluate_correctness_for_horizon(direction, ret_for_horizon, horizon_days)
            was_correct = bool(self._was_correct_bool_for_horizon(direction, ret_for_horizon, horizon_days))
        else:
            # Legacy single-horizon — prefer 90d → 30d → 7d
            correctness = self._evaluate_correctness(direction, actual_returns)
            was_correct = self._was_correct_bool(direction, actual_returns)
        situation = self._build_situation_text(debate)
        tags = self._extract_tags(debate)
        if horizon_days in (7, 30, 90):
            tags.append(f"horizon:{horizon_days}d")

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

        # Update debate log with actuals.
        # When called per-horizon (the new Airflow path), write only the
        # was_correct_{horizon}d column. The aggregated was_correct boolean
        # is also updated for backward-compat with anything reading it.
        update_kwargs = dict(
            debate_id=debate_id,
            actual_return_7d=actual_returns.get("7d"),
            actual_return_30d=actual_returns.get("30d"),
            actual_return_90d=actual_returns.get("90d"),
            lessons_extracted=lessons,
        )
        if horizon_days == 7:
            update_kwargs["was_correct_7d"] = was_correct
        elif horizon_days == 30:
            update_kwargs["was_correct_30d"] = was_correct
            update_kwargs["was_correct"] = was_correct  # 30d is the canonical legacy view
        elif horizon_days == 90:
            update_kwargs["was_correct_90d"] = was_correct
        else:
            update_kwargs["was_correct"] = was_correct  # legacy single-shot path
        self.memory.update_debate_actuals(**update_kwargs)

        logger.info(
            "Reflected on debate #%d (%s/%s): %s, %d memories created",
            debate_id, debate["ticker"], debate["exchange"], correctness, len(memory_ids),
        )
        return memory_ids

    async def reflect_pending(
        self,
        horizon_days: int = 30,
        min_age_days: Optional[int] = None,
    ) -> int:
        """
        Batch-process debates that have reached the given horizon but haven't
        been graded yet at that horizon.

        Parameters
        ----------
        horizon_days : int (7 | 30 | 90)
            Which horizon to grade against. Reflector should be called once
            per horizon per day (separate DAG tasks).
        min_age_days : Optional[int]
            Defaults to horizon_days. Debates younger than this are skipped
            because the realised return at that horizon doesn't exist yet.

        Skips debates where was_correct_{horizon_days}d IS already set (so
        running this daily is idempotent — only fresh-due rows are processed).

        Returns total memories created in this run.
        """
        if not self.memory._conn:
            logger.warning("No DB connection — skipping batch reflection")
            return 0

        if horizon_days not in (7, 30, 90):
            raise ValueError(f"horizon_days must be 7, 30, or 90 (got {horizon_days})")

        if min_age_days is None:
            min_age_days = horizon_days

        cutoff = date.today() - timedelta(days=min_age_days)
        column_filter = {7: "was_correct_7d", 30: "was_correct_30d", 90: "was_correct_90d"}[horizon_days]

        cur = self.memory._conn.cursor()
        cur.execute(
            f"SELECT id, ticker, exchange, debate_date, direction "
            f"FROM datapai.sys_agent_debate_log_full "
            f"WHERE {column_filter} IS NULL AND debate_date <= %s "
            f"ORDER BY debate_date",
            (cutoff,),
        )
        pending = cur.fetchall()
        cols = [d[0] for d in cur.description]
        cur.close()

        if not pending:
            logger.info("No pending debates at horizon=%dd (min_age=%dd)", horizon_days, min_age_days)
            return 0

        logger.info("Reflector horizon=%dd: %d debates pending", horizon_days, len(pending))
        total_memories = 0

        for row in pending:
            debate = dict(zip(cols, row))
            actual = await self._fetch_actual_returns(
                debate["ticker"], debate["exchange"], debate["debate_date"]
            )
            if actual is None:
                continue
            ret = actual.get(f"{horizon_days}d")
            if ret is None:
                logger.debug("[%s/%s] %dd return still missing — skip",
                             debate["ticker"], debate["exchange"], horizon_days)
                continue

            mem_ids = await self.reflect_on_debate(
                debate["id"], actual, horizon_days=horizon_days
            )
            total_memories += len(mem_ids)

        logger.info("Reflector horizon=%dd done: %d memories from %d debates",
                    horizon_days, total_memories, len(pending))
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
