# ═══════════════════════════════════════════════════════════════════════════════
# stock_chat/fw_db.py  —  Direct framework_db writer (Phase 1.13, 2026-04-12)
#
# Why this module exists:
#   Many user-facing tables in datapai_framework_db are accessed from stock-be
#   via postgres_fdw foreign-table aliases on stock_db. READS through the FDW
#   are transparent and fast, but WRITES are broken by a postgres_fdw quirk:
#   INSERT via the FDW always sends the full column list with NULL for any
#   column not in the VALUES list, bypassing the remote-side DEFAULT clauses
#   (gen_random_uuid(), nextval(), NOW(), etc.).
#
#   This caused chat history to silently fail to persist from ~2026-04-02
#   onwards. See docs/architecture/fdw-gotchas.md for the full story.
#
# What this module provides:
#   A shared direct-connection writer for framework_db that ANY stock_chat
#   module can import and use for INSERT/UPDATE/DELETE. Reads continue to
#   use .db (the FDW-backed pool).
#
#   - _get_fw_conn() — lazy psycopg2 connection, auto-reconnects on drop
#   - fw_execute(sql, params) — INSERT/UPDATE/DELETE
#   - fw_execute_returning(sql, params) — INSERT ... RETURNING
#   - fw_query(sql, params) — SELECT (for writes that need read-your-own-write)
#
# Architectural rule (AI governance): any table on framework_db with DEFAULT
# clauses on id/created_at/etc. MUST be written through this module. Adding
# a new table? Import these helpers rather than using the .db FDW pool.
#
# Reference: send_alerts.py::_get_framework_conn (same pattern, earlier fix)
# ═══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


_fw_conn: psycopg2.extensions.connection | None = None


def _get_fw_conn() -> psycopg2.extensions.connection:
    """Lazily open + return a direct framework_db connection.
    Auto-reconnects if the connection has been closed or is broken."""
    global _fw_conn
    if _fw_conn is None or _fw_conn.closed:
        _fw_conn = psycopg2.connect(
            host=os.getenv("AUTH_DB_HOST", "localhost"),
            port=int(os.getenv("AUTH_DB_PORT", "5433")),
            dbname=os.getenv("AUTH_DB_NAME", "datapai_auth_db"),
            user=os.getenv("AUTH_DB_USER", "auth_service"),
            password=os.getenv("AUTH_DB_PASSWORD", ""),
            connect_timeout=5,
        )
        _fw_conn.autocommit = True
        logger.info(
            "[fw_db] framework_db writer connection opened → %s:%s/%s",
            os.getenv("AUTH_DB_HOST", "localhost"),
            os.getenv("AUTH_DB_PORT", "5433"),
            os.getenv("AUTH_DB_NAME", "datapai_auth_db"),
        )
    return _fw_conn


@contextmanager
def _fw_cursor(dict_cursor: bool = False) -> Generator:
    """Context manager yielding a psycopg2 cursor. Handles connection-dropped
    recovery: if the operation fails with OperationalError/InterfaceError, we
    drop the cached connection so the next call reopens it."""
    global _fw_conn
    try:
        conn = _get_fw_conn()
        cursor_kw = {"cursor_factory": RealDictCursor} if dict_cursor else {}
        with conn.cursor(**cursor_kw) as cur:
            yield cur
    except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
        logger.error("[fw_db] framework_db connection broken: %s", e)
        try:
            if _fw_conn is not None and not _fw_conn.closed:
                _fw_conn.close()
        except Exception:
            pass
        _fw_conn = None
        raise


def fw_execute(sql: str, params=None) -> None:
    """Execute an INSERT/UPDATE/DELETE on framework_db directly."""
    with _fw_cursor() as cur:
        cur.execute(sql, params)


def fw_execute_returning(sql: str, params=None) -> dict | None:
    """Execute INSERT ... RETURNING on framework_db directly. Returns the first row."""
    with _fw_cursor(dict_cursor=True) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def fw_query(sql: str, params=None) -> list[dict]:
    """Execute a SELECT on framework_db directly. Use this when you need
    read-your-own-write consistency within a single request (e.g.
    get_or_create_session)."""
    with _fw_cursor(dict_cursor=True) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
