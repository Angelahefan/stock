"""
agents/news_agent/db.py — Store and retrieve material events in Postgres.

Table: datapai.material_events
Uses psycopg2 with %s parameter style (NOT $1 node-postgres style).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from agents.news_agent.contracts import (
    EventType,
    MaterialEvent,
    Sentiment,
    Severity,
)

logger = logging.getLogger(__name__)


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS datapai.material_events (
    id              SERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    exchange        TEXT NOT NULL DEFAULT 'US',
    event_type      TEXT NOT NULL,
    severity        TEXT NOT NULL,
    sentiment       TEXT NOT NULL DEFAULT 'NEUTRAL',
    headline        TEXT NOT NULL,
    summary         TEXT NOT NULL DEFAULT '',
    source_url      TEXT NOT NULL DEFAULT '',
    source_name     TEXT NOT NULL DEFAULT '',
    published_at    TIMESTAMPTZ,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_material_events_ticker
    ON datapai.material_events (ticker, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_material_events_severity
    ON datapai.material_events (severity, detected_at DESC);
"""


def ensure_table() -> None:
    """Create the material_events table if it does not exist."""
    from scripts.lib.db_helpers import get_conn

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_CREATE_TABLE_SQL)
        logger.info("datapai.material_events table ensured")
    except Exception as exc:
        logger.error("Failed to ensure material_events table: %s", exc)
        raise


def save_material_event(
    ticker: str,
    exchange: str,
    event: MaterialEvent,
) -> Optional[int]:
    """
    Insert a single material event into the DB.
    Returns the new row id, or None on failure.
    """
    from scripts.lib.db_helpers import get_conn

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO datapai.material_events
                       (ticker, exchange, event_type, severity, sentiment,
                        headline, summary, source_url, source_name, published_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       RETURNING id""",
                    (
                        ticker,
                        exchange,
                        event.event_type.value,
                        event.severity.value,
                        event.sentiment.value,
                        event.title,
                        event.summary,
                        event.url,
                        event.source,
                        event.published_at,
                    ),
                )
                row = cur.fetchone()
                return row[0] if row else None
    except Exception as exc:
        logger.error("Failed to save material event for %s: %s", ticker, exc)
        return None


def save_material_events(
    ticker: str,
    exchange: str,
    events: List[MaterialEvent],
) -> int:
    """Batch-save material events. Returns count of rows inserted."""
    saved = 0
    for event in events:
        if event.event_type == EventType.NONE and event.severity == Severity.NONE:
            continue
        row_id = save_material_event(ticker, exchange, event)
        if row_id is not None:
            saved += 1
    logger.info("Saved %d/%d material events for %s", saved, len(events), ticker)
    return saved


def get_latest_events(
    ticker: str,
    exchange: Optional[str] = None,
    hours: int = 72,
    limit: int = 20,
) -> List[dict]:
    """
    Retrieve recent material events for a ticker from the DB.
    Returns list of dicts (not Pydantic models) for API serialisation.
    """
    from scripts.lib.db_helpers import get_conn

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if exchange:
                    cur.execute(
                        """SELECT id, ticker, exchange, event_type, severity, sentiment,
                                  headline, summary, source_url, source_name,
                                  published_at, detected_at
                           FROM datapai.material_events
                           WHERE ticker = %s AND exchange = %s
                             AND detected_at > NOW() - INTERVAL '%s hours'
                           ORDER BY detected_at DESC
                           LIMIT %s""",
                        (ticker, exchange, hours, limit),
                    )
                else:
                    cur.execute(
                        """SELECT id, ticker, exchange, event_type, severity, sentiment,
                                  headline, summary, source_url, source_name,
                                  published_at, detected_at
                           FROM datapai.material_events
                           WHERE ticker = %s
                             AND detected_at > NOW() - INTERVAL '%s hours'
                           ORDER BY detected_at DESC
                           LIMIT %s""",
                        (ticker, hours, limit),
                    )
                if cur.description:
                    cols = [d[0] for d in cur.description]
                    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
                    # Convert datetimes to ISO strings for JSON
                    for row in rows:
                        for k, v in row.items():
                            if hasattr(v, "isoformat"):
                                row[k] = v.isoformat()
                    return rows
        return []
    except Exception as exc:
        logger.error("Failed to get material events for %s: %s", ticker, exc)
        return []
