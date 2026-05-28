"""
agents/stock_synthesis/db.py — Postgres persistence for stock synthesis results.

Table: datapai.stock_synthesis
"""
from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS datapai.stock_synthesis (
    ticker              VARCHAR(20)  NOT NULL,
    exchange            VARCHAR(10)  NOT NULL,
    direction           VARCHAR(20)  NOT NULL,
    confidence          DOUBLE PRECISION NOT NULL,
    conviction          VARCHAR(10)  NOT NULL,
    thesis              TEXT,
    what_bulls_say      TEXT,
    what_bears_say      TEXT,
    key_risk            TEXT,
    ta_direction        VARCHAR(20),
    fa_direction        VARCHAR(20),
    ma_direction        VARCHAR(20),
    signals_aligned     BOOLEAN,
    disagreement_summary TEXT,
    debate_points_json  TEXT,
    debate_rounds       INT DEFAULT 0,
    model_used          VARCHAR(50),
    total_tokens        INT DEFAULT 0,
    computed_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, exchange, computed_at)
);

CREATE INDEX IF NOT EXISTS idx_stock_synthesis_latest
    ON datapai.stock_synthesis (ticker, exchange, computed_at DESC);
"""


async def ensure_table():
    """Create the stock_synthesis table if it doesn't exist."""
    try:
        from agents.stock_chat.db import query as db_query
        from scripts.lib.db_helpers import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(CREATE_TABLE_SQL)
            conn.commit()
        logger.info("datapai.stock_synthesis table ready")
    except Exception as exc:
        logger.warning("Could not create stock_synthesis table: %s", exc)


async def save_synthesis(synthesis) -> bool:
    """Save a StockSynthesis result to Postgres."""
    try:
        from scripts.lib.db_helpers import get_conn

        debate_json = json.dumps(
            [dp.model_dump() for dp in synthesis.debate_points]
        ) if synthesis.debate_points else "[]"

        with get_conn() as conn:
            with conn.cursor() as cur:
                # 2026-05-28: write transparency JSONB columns (migration 045)
                # + price snapshot columns (migration 046). Fail-soft via
                # getattr() so older StockSynthesis instances still write.
                gate_decisions    = getattr(synthesis, "gate_decisions", None) or {}
                agent_signals     = getattr(synthesis, "agent_signals", None) or {}
                reflector_lessons = getattr(synthesis, "reflector_lessons", None) or {}
                price_at_debate   = getattr(synthesis, "price_at_debate", None)
                price_currency    = getattr(synthesis, "price_currency", None)
                price_as_of_date  = getattr(synthesis, "price_as_of_date", None)
                cur.execute(
                    """INSERT INTO datapai.stock_synthesis
                       (ticker, exchange, direction, confidence, conviction,
                        thesis, what_bulls_say, what_bears_say, key_risk,
                        ta_direction, fa_direction, ma_direction,
                        signals_aligned, disagreement_summary,
                        debate_points_json, debate_rounds,
                        model_used, total_tokens, computed_at,
                        gate_decisions, agent_signals, reflector_lessons,
                        price_at_debate, price_currency, price_as_of_date)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                               %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s)
                       ON CONFLICT (ticker, exchange, computed_at) DO UPDATE SET
                        direction = EXCLUDED.direction,
                        confidence = EXCLUDED.confidence,
                        conviction = EXCLUDED.conviction,
                        thesis = EXCLUDED.thesis,
                        gate_decisions = EXCLUDED.gate_decisions,
                        agent_signals = EXCLUDED.agent_signals,
                        reflector_lessons = EXCLUDED.reflector_lessons,
                        price_at_debate = EXCLUDED.price_at_debate,
                        price_currency = EXCLUDED.price_currency,
                        price_as_of_date = EXCLUDED.price_as_of_date""",
                    (
                        synthesis.ticker, synthesis.exchange,
                        synthesis.direction.value, synthesis.confidence, synthesis.conviction,
                        synthesis.thesis, synthesis.what_bulls_say, synthesis.what_bears_say,
                        synthesis.key_risk,
                        synthesis.ta_direction.value, synthesis.fa_direction.value,
                        synthesis.ma_direction.value if synthesis.ma_direction else None,
                        synthesis.signals_aligned, synthesis.disagreement_summary,
                        debate_json, synthesis.debate_rounds,
                        synthesis.model_used, synthesis.total_tokens,
                        synthesis.computed_at,
                        json.dumps(gate_decisions),
                        json.dumps(agent_signals),
                        json.dumps(reflector_lessons),
                        price_at_debate,
                        price_currency,
                        price_as_of_date,
                    ),
                )
            conn.commit()
        logger.info("Saved synthesis for %s/%s: %s (%.0f%%)",
                    synthesis.ticker, synthesis.exchange,
                    synthesis.direction.value, synthesis.confidence * 100)
        return True
    except Exception as exc:
        logger.error("Failed to save synthesis for %s: %s", synthesis.ticker, exc)
        return False


async def upsert_consensus_report(report) -> bool:
    """Save a ConsensusReport to Postgres."""
    try:
        from scripts.lib.db_helpers import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO datapai.consensus_reports
                       (ticker, exchange, macro_view, consensus_score, conflict_level,
                        consensus_direction, agent_scores_json, regime_weights_json,
                        risk_score, risk_flags_json, position_size,
                        exit_strategy_json, debate_transcript, debate_phases_json, computed_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (ticker, exchange, computed_at) DO UPDATE SET
                        consensus_score = EXCLUDED.consensus_score,
                        conflict_level = EXCLUDED.conflict_level,
                        consensus_direction = EXCLUDED.consensus_direction,
                        risk_score = EXCLUDED.risk_score""",
                    (
                        report.ticker, report.exchange,
                        report.macro_view, report.consensus_score, report.conflict_level,
                        report.consensus_direction,
                        json.dumps(report.agent_scores),
                        json.dumps(report.regime_weights),
                        report.risk_score,
                        json.dumps(report.risk_flags),
                        report.position_size,
                        json.dumps(report.exit_strategy),
                        report.debate_transcript,
                        json.dumps(report.debate_phases),
                        report.computed_at,
                    ),
                )
            conn.commit()
        logger.info("Saved consensus report for %s/%s: score=%.2f, conflict=%.2f",
                    report.ticker, report.exchange,
                    report.consensus_score, report.conflict_level)
        return True
    except Exception as exc:
        logger.error("Failed to save consensus report for %s: %s", report.ticker, exc)
        return False


async def get_latest_consensus_report(ticker: str, exchange: str) -> Optional[dict]:
    """Get the most recent consensus report for a ticker."""
    try:
        from scripts.lib.db_helpers import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT * FROM datapai.consensus_reports
                       WHERE ticker = %s AND exchange = %s
                       ORDER BY computed_at DESC LIMIT 1""",
                    (ticker, exchange),
                )
                if cur.description:
                    cols = [d[0] for d in cur.description]
                    row = cur.fetchone()
                    return dict(zip(cols, row)) if row else None
        return None
    except Exception as exc:
        logger.warning("Failed to get consensus report for %s: %s", ticker, exc)
        return None


async def get_latest_synthesis(ticker: str, exchange: str) -> Optional[dict]:
    """Get the most recent synthesis for a ticker."""
    try:
        from scripts.lib.db_helpers import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT * FROM datapai.stock_synthesis
                       WHERE ticker = %s AND exchange = %s
                       ORDER BY computed_at DESC LIMIT 1""",
                    (ticker, exchange),
                )
                if cur.description:
                    cols = [d[0] for d in cur.description]
                    row = cur.fetchone()
                    return dict(zip(cols, row)) if row else None
        return None
    except Exception as exc:
        logger.warning("Failed to get synthesis for %s: %s", ticker, exc)
        return None
