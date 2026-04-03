"""
agents/stock_synthesis/memory.py
─────────────────────────────────────────────────────────────────────────────
DB-driven Agent Memory with BM25 runtime index.

Ported from TradingAgents (TauricResearch) FinancialSituationMemory pattern,
extended with Postgres persistence and curated best-results layer.

Architecture:
  Postgres (sys_agent_memory)  →  BM25 index (runtime cache)
  Postgres (sys_agent_results) →  Curated wisdom (always-inject layer)

Usage:
    store = AgentMemoryStore.from_env()
    store.load()

    # Retrieve memories for a debate agent
    memories = store.get_memories("bull", situation_text, n=2)
    best = store.get_best_results("bull", regime="BULL_MOMENTUM", quality="A")

    # After reflection, add a new memory
    store.add_memory("bull", ticker="BHP", exchange="ASX",
                     situation="...", recommendation="...",
                     outcome="WRONG", source="reflection",
                     tags=["regime:BULL", "quality:A"])
"""
from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# BM25 is optional at import time — graceful degradation if not installed
try:
    from rank_bm25 import BM25Okapi
    _HAS_BM25 = True
except ImportError:
    _HAS_BM25 = False
    logger.warning("rank_bm25 not installed — agent memory retrieval disabled. pip install rank-bm25")


def _tokenize(text: str) -> List[str]:
    """Tokenize text for BM25 indexing. Simple whitespace + punctuation split."""
    return re.findall(r'\b\w+\b', text.lower())


class AgentMemoryStore:
    """
    DB-driven agent memory with BM25 runtime index.

    Postgres is truth. BM25 is a cache rebuilt on load/add.
    """

    def __init__(self, pg_conn=None):
        """
        Parameters
        ----------
        pg_conn : psycopg2 connection or None
            If None, memory operates in-memory only (no persistence).
        """
        self._conn = pg_conn
        self._indices: Dict[str, Any] = {}       # role -> BM25 index
        self._memories: Dict[str, List[dict]] = defaultdict(list)  # role -> [row dicts]
        self._loaded = False

    @classmethod
    def from_env(cls) -> "AgentMemoryStore":
        """Create store from standard DataPAI Postgres env vars."""
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=os.getenv("DATAPAI_PG_HOST", os.getenv("PGHOST", "localhost")),
                port=int(os.getenv("DATAPAI_PG_PORT", os.getenv("PGPORT", "5432"))),
                user=os.getenv("DATAPAI_PG_USER", os.getenv("PGUSER", "postgres")),
                password=os.getenv("DATAPAI_PG_PASSWORD", os.getenv("PGPASSWORD", "postgres")),
                dbname=os.getenv("DATAPAI_PG_DB", os.getenv("PGDATABASE", "postgres")),
            )
            conn.autocommit = True
            return cls(pg_conn=conn)
        except Exception as exc:
            logger.warning("Could not connect to Postgres for agent memory: %s — running in-memory only", exc)
            return cls(pg_conn=None)

    # ──────────────────────────────────────────────────────────────────────
    # Load from DB
    # ──────────────────────────────────────────────────────────────────────

    def load(self) -> int:
        """
        Load all active memories from Postgres into BM25 indices.

        Returns number of memories loaded.
        """
        if not self._conn:
            self._loaded = True
            return 0

        try:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT id, agent_role, ticker, exchange, situation_text, recommendation, "
                "outcome, confidence, tags "
                "FROM datapai.sys_agent_memory WHERE is_active = TRUE "
                "ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            cur.close()
        except Exception as exc:
            logger.error("Failed to load agent memories from DB: %s", exc)
            self._loaded = True
            return 0

        self._memories.clear()
        self._indices.clear()

        for row in rows:
            d = dict(zip(cols, row))
            self._memories[d["agent_role"]].append(d)

        # Build BM25 index per role
        if _HAS_BM25:
            for role, mems in self._memories.items():
                corpus = [_tokenize(m["situation_text"]) for m in mems]
                if corpus:
                    self._indices[role] = BM25Okapi(corpus)

        total = sum(len(v) for v in self._memories.values())
        logger.info("Loaded %d agent memories across %d roles", total, len(self._memories))
        self._loaded = True
        return total

    # ──────────────────────────────────────────────────────────────────────
    # BM25 retrieval
    # ──────────────────────────────────────────────────────────────────────

    def get_memories(
        self, agent_role: str, situation: str, n: int = 2
    ) -> List[dict]:
        """
        Retrieve top-N most similar past situations for an agent role.

        Returns list of dicts: {situation, recommendation, relevance, ticker, outcome}
        """
        if not self._loaded:
            self.load()

        if not _HAS_BM25 or agent_role not in self._indices:
            return []

        bm25 = self._indices[agent_role]
        mems = self._memories[agent_role]
        tokens = _tokenize(situation)
        scores = bm25.get_scores(tokens)

        if len(scores) == 0:
            return []

        max_score = max(scores) if max(scores) > 0 else 1.0
        top_n = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:n]

        results = []
        for i in top_n:
            if scores[i] <= 0.0:
                continue
            m = mems[i]
            results.append({
                "situation": m["situation_text"],
                "recommendation": m["recommendation"],
                "relevance": round(float(scores[i] / max_score), 3),
                "ticker": m.get("ticker"),
                "outcome": m.get("outcome"),
            })
        return results

    # ──────────────────────────────────────────────────────────────────────
    # Curated best results (sys_agent_results)
    # ──────────────────────────────────────────────────────────────────────

    def get_best_results(
        self,
        agent_role: str,
        regime: Optional[str] = None,
        quality: Optional[str] = None,
        signal_type: Optional[str] = None,
        limit: int = 3,
    ) -> List[dict]:
        """
        Retrieve curated best lessons from sys_agent_results.

        Filters by applicable_when JSONB conditions. Returns highest-priority first.
        """
        if not self._conn:
            return []

        try:
            cur = self._conn.cursor()
            # Base query — filter by role, active, priority desc
            sql = (
                "SELECT result_key, title, lesson_text, success_rate, priority, "
                "applicable_when, evidence_count "
                "FROM datapai.sys_agent_results "
                "WHERE agent_role = %s AND is_active = TRUE "
                "ORDER BY priority DESC LIMIT %s"
            )
            cur.execute(sql, (agent_role, limit * 3))  # fetch more, filter in Python
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            cur.close()
        except Exception as exc:
            logger.warning("Failed to load best results: %s", exc)
            return []

        results = []
        for row in rows:
            d = dict(zip(cols, row))
            aw = d.get("applicable_when") or {}
            # Check conditions
            if regime and aw.get("regime") and regime not in aw["regime"]:
                continue
            if quality and aw.get("quality") and quality not in aw["quality"]:
                continue
            if signal_type and aw.get("signal_type") and signal_type not in aw["signal_type"]:
                continue
            results.append(d)
            if len(results) >= limit:
                break

        return results

    # ──────────────────────────────────────────────────────────────────────
    # Add memory
    # ──────────────────────────────────────────────────────────────────────

    def add_memory(
        self,
        agent_role: str,
        situation: str,
        recommendation: str,
        ticker: Optional[str] = None,
        exchange: Optional[str] = None,
        outcome: str = "PENDING",
        outcome_detail: Optional[str] = None,
        confidence: Optional[float] = None,
        source: str = "reflection",
        tags: Optional[List[str]] = None,
    ) -> Optional[int]:
        """
        Write a new memory to DB and update BM25 index.

        Returns the memory ID if persisted, None if in-memory only.
        """
        mem_id = None
        tags = tags or []

        if self._conn:
            try:
                cur = self._conn.cursor()
                cur.execute(
                    "INSERT INTO datapai.sys_agent_memory "
                    "(agent_role, ticker, exchange, situation_text, recommendation, "
                    "outcome, outcome_detail, confidence, source, tags) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (agent_role, ticker, exchange, situation, recommendation,
                     outcome, outcome_detail, confidence, source, tags),
                )
                mem_id = cur.fetchone()[0]
                cur.close()
            except Exception as exc:
                logger.error("Failed to persist memory: %s", exc)

        # Update in-memory index
        new_mem = {
            "id": mem_id,
            "agent_role": agent_role,
            "ticker": ticker,
            "exchange": exchange,
            "situation_text": situation,
            "recommendation": recommendation,
            "outcome": outcome,
            "confidence": confidence,
            "tags": tags,
        }
        self._memories[agent_role].append(new_mem)
        self._rebuild_index(agent_role)

        return mem_id

    def _rebuild_index(self, agent_role: str):
        """Rebuild BM25 index for a single role."""
        if not _HAS_BM25:
            return
        mems = self._memories.get(agent_role, [])
        if mems:
            corpus = [_tokenize(m["situation_text"]) for m in mems]
            self._indices[agent_role] = BM25Okapi(corpus)
        else:
            self._indices.pop(agent_role, None)

    # ──────────────────────────────────────────────────────────────────────
    # Debate logging (sys_agent_debate_log)
    # ──────────────────────────────────────────────────────────────────────

    def log_debate(
        self,
        ticker: str,
        exchange: str,
        debate_date,
        input_signals: dict,
        direction: str,
        confidence: float,
        thesis: str = "",
        recommendation: str = "",
        bull_arguments: Optional[List[str]] = None,
        bear_arguments: Optional[List[str]] = None,
        risk_arguments: Optional[List[str]] = None,
        pm_arguments: Optional[List[str]] = None,
        regime: Optional[str] = None,
        quality_tier: Optional[str] = None,
        conflict_level: Optional[float] = None,
        agent_scores: Optional[dict] = None,
        debate_type: str = "synthesis",
    ) -> Optional[int]:
        """Log a full debate transcript to sys_agent_debate_log. Returns debate ID."""
        if not self._conn:
            return None

        try:
            import json
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO datapai.sys_agent_debate_log "
                "(ticker, exchange, debate_date, debate_type, input_signals, "
                "bull_arguments, bear_arguments, risk_arguments, pm_arguments, "
                "direction, confidence, thesis, recommendation, "
                "regime, quality_tier, conflict_level, agent_scores) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (ticker, exchange, debate_date, debate_type,
                 json.dumps(input_signals),
                 bull_arguments or [], bear_arguments or [],
                 risk_arguments or [], pm_arguments or [],
                 direction, confidence, thesis, recommendation,
                 regime, quality_tier, conflict_level,
                 json.dumps(agent_scores or {})),
            )
            debate_id = cur.fetchone()[0]
            cur.close()
            logger.info("Logged debate #%d for %s/%s", debate_id, ticker, exchange)
            return debate_id
        except Exception as exc:
            logger.error("Failed to log debate: %s", exc)
            return None

    def update_debate_actuals(
        self,
        debate_id: int,
        actual_return_7d: Optional[float] = None,
        actual_return_30d: Optional[float] = None,
        actual_return_90d: Optional[float] = None,
        was_correct: Optional[bool] = None,
        lessons_extracted: Optional[List[str]] = None,
    ):
        """Update a debate log with actual returns (called by reflection)."""
        if not self._conn:
            return

        try:
            cur = self._conn.cursor()
            cur.execute(
                "UPDATE datapai.sys_agent_debate_log SET "
                "actual_return_7d = COALESCE(%s, actual_return_7d), "
                "actual_return_30d = COALESCE(%s, actual_return_30d), "
                "actual_return_90d = COALESCE(%s, actual_return_90d), "
                "was_correct = COALESCE(%s, was_correct), "
                "lessons_extracted = COALESCE(%s, lessons_extracted) "
                "WHERE id = %s",
                (actual_return_7d, actual_return_30d, actual_return_90d,
                 was_correct, lessons_extracted, debate_id),
            )
            cur.close()
        except Exception as exc:
            logger.error("Failed to update debate actuals: %s", exc)

    # ──────────────────────────────────────────────────────────────────────
    # Upsert best result (sys_agent_results)
    # ──────────────────────────────────────────────────────────────────────

    def upsert_best_result(
        self,
        result_key: str,
        agent_role: str,
        category: str,
        title: str,
        lesson_text: str,
        evidence_count: int = 1,
        success_rate: Optional[float] = None,
        applicable_when: Optional[dict] = None,
        priority: int = 50,
    ) -> Optional[int]:
        """Insert or update a curated best result."""
        if not self._conn:
            return None

        try:
            import json
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO datapai.sys_agent_results "
                "(result_key, agent_role, category, title, lesson_text, "
                "evidence_count, success_rate, applicable_when, priority, last_validated) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW()) "
                "ON CONFLICT (result_key) DO UPDATE SET "
                "title = EXCLUDED.title, lesson_text = EXCLUDED.lesson_text, "
                "evidence_count = EXCLUDED.evidence_count, success_rate = EXCLUDED.success_rate, "
                "applicable_when = EXCLUDED.applicable_when, priority = EXCLUDED.priority, "
                "last_validated = NOW(), updated_at = NOW() "
                "RETURNING id",
                (result_key, agent_role, category, title, lesson_text,
                 evidence_count, success_rate,
                 json.dumps(applicable_when or {}), priority),
            )
            result_id = cur.fetchone()[0]
            cur.close()
            return result_id
        except Exception as exc:
            logger.error("Failed to upsert best result: %s", exc)
            return None

    # ──────────────────────────────────────────────────────────────────────
    # Formatting for prompt injection
    # ──────────────────────────────────────────────────────────────────────

    def format_lessons_for_prompt(
        self,
        agent_role: str,
        situation: str,
        regime: Optional[str] = None,
        quality: Optional[str] = None,
        n_memories: int = 2,
        n_best: int = 2,
    ) -> str:
        """
        Build a formatted lessons block ready to inject into an agent prompt.

        Combines curated best results (high priority) + BM25 similar memories.
        Returns empty string if no memories found.
        """
        parts = []

        # Layer 1: Curated best results
        best = self.get_best_results(agent_role, regime=regime, quality=quality, limit=n_best)
        if best:
            parts.append("=== LEARNED LESSONS (validated) ===")
            for b in best:
                sr = f" (success rate: {b['success_rate']:.0%})" if b.get("success_rate") else ""
                parts.append(f"- {b['title']}{sr}")
                parts.append(f"  {b['lesson_text'][:300]}")

        # Layer 2: Similar past situations
        memories = self.get_memories(agent_role, situation, n=n_memories)
        if memories:
            parts.append("\n=== PAST SIMILAR SITUATIONS ===")
            for m in memories:
                outcome_tag = f" [outcome: {m['outcome']}]" if m.get("outcome") and m["outcome"] != "PENDING" else ""
                parts.append(f"- Situation: {m['situation'][:200]}")
                parts.append(f"  Lesson: {m['recommendation'][:300]}{outcome_tag}")

        return "\n".join(parts) if parts else ""

    # ──────────────────────────────────────────────────────────────────────
    # Stats
    # ──────────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return memory stats per role."""
        return {
            role: len(mems) for role, mems in self._memories.items()
        }
