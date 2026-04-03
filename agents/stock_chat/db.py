# ═══════════════════════════════════════════════════════════════════════════════
# stock_chat/db.py  —  PostgreSQL connection pool for datapai schema
# Uses psycopg2 (sync) with a simple connection pool. All queries are
# scoped to the datapai schema — never touches public/graphile_worker.
# ═══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import os
import logging
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# ── Connection config ─────────────────────────────────────────────────────────
# lightdash_db_1 postgres is exposed on host at 127.0.0.1:5432 via docker port binding
# Override via env vars for local dev or future migration
_PG_HOST     = os.getenv("DATAPAI_PG_HOST",     "localhost")
_PG_PORT     = int(os.getenv("DATAPAI_PG_PORT", "5432"))
_PG_DB       = os.getenv("DATAPAI_PG_DB",       "postgres")
_PG_USER     = os.getenv("DATAPAI_PG_USER",     "postgres")
_PG_PASSWORD = os.getenv("DATAPAI_PG_PASSWORD", "postgres")

_pool: pool.ThreadedConnectionPool | None = None


def _get_pool() -> pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            host=_PG_HOST,
            port=_PG_PORT,
            dbname=_PG_DB,
            user=_PG_USER,
            password=_PG_PASSWORD,
            options="-c search_path=datapai,public",
            connect_timeout=5,
        )
        logger.info("datapai postgres pool initialised → %s:%s/%s", _PG_HOST, _PG_PORT, _PG_DB)
    return _pool


@contextmanager
def get_conn() -> Generator:
    """Context manager — borrows a connection from the pool, returns it on exit."""
    p = _get_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


def query(sql: str, params=None) -> list[dict]:
    """Execute a SELECT and return list of dicts."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def execute(sql: str, params=None) -> None:
    """Execute an INSERT/UPDATE/DELETE."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def execute_returning(sql: str, params=None) -> dict | None:
    """Execute INSERT ... RETURNING and return the first row."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None
