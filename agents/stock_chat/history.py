# ═══════════════════════════════════════════════════════════════════════════════
# stock_chat/history.py  —  Chat session & message persistence
# Tables: datapai.chat_sessions, datapai.chat_messages, datapai.user_preferences
#
# ── AI GOVERNANCE RULE (Phase 1.13, 2026-04-12) ───────────────────────────────
# Every AI chat interaction must be persisted for audit, back-tracking, and
# accountability. No black-box AI at DATAP.AI. A failed persist is NOT
# non-fatal — it's a loud error + an audit log entry. See the standing rule
# in ~/.claude/.../memory/feedback_ai_governance_audit.md.
#
# ── WRITE PATH ARCHITECTURAL RULE (Phase 1.13, 2026-04-12) ────────────────────
# For any user-facing table on framework_db (chat_sessions, chat_messages,
# notification_log, user_devices, sys_user_context, user_preferences, etc.),
# write paths go through a DIRECT framework_db connection, NOT the stock_db
# FDW alias. The FDW alias works fine for reads but breaks INSERT DEFAULTs
# (postgres_fdw sends NULL for columns not in the VALUES list, bypassing
# remote-side DEFAULT gen_random_uuid() / nextval() / NOW() clauses).
#
# READS continue to use the .db pool (stock_db via FDW) because reads via
# FDW are transparent and fast.
#
# Reference fix: send_alerts.py::_get_framework_conn (Phase 4A, 2026-04-11).
# ═══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import logging
from typing import Optional
from uuid import UUID

from .db import query  # kept for reads via stock_db FDW (fast + transparent)
from .fw_db import (
    fw_execute as _fw_execute,
    fw_execute_returning as _fw_execute_returning,
    fw_query as _fw_query,
)

logger = logging.getLogger(__name__)


# ── Sessions ──────────────────────────────────────────────────────────────────
#
# All session INSERTs go through _fw_* helpers which hit framework_db directly,
# bypassing the stock_db FDW alias. This fixes the pre-existing DEFAULT-bypass
# bug that had broken chat history persistence since the FDW aliases were added.
#
# The SELECT in get_or_create_session also uses _fw_query for consistency
# within a single request (avoids read-your-own-write races across the FDW).

def get_or_create_session(user_id: int, ticker: str, exchange: str = "US") -> str:
    """
    Return the most recent active session UUID for (user_id, ticker),
    or create a new one if none exists.
    """
    rows = _fw_query(
        """
        SELECT id::text AS id FROM datapai.chat_sessions
        WHERE user_id = %s AND ticker = %s
        ORDER BY updated_at DESC LIMIT 1
        """,
        (user_id, ticker.upper()),
    )
    if rows:
        return rows[0]["id"]

    row = _fw_execute_returning(
        """
        INSERT INTO datapai.chat_sessions (user_id, ticker, exchange, title)
        VALUES (%s, %s, %s, %s)
        RETURNING id::text AS id
        """,
        (user_id, ticker.upper(), exchange.upper(), f"{ticker.upper()} AI Analysis Chat"),
    )
    session_id = row["id"]
    logger.info("Created chat session %s for user=%s ticker=%s", session_id, user_id, ticker)
    return session_id


def create_new_session(user_id: int, ticker: str, exchange: str = "US") -> str:
    """Force-create a fresh session (user clicked 'New chat')."""
    row = _fw_execute_returning(
        """
        INSERT INTO datapai.chat_sessions (user_id, ticker, exchange, title)
        VALUES (%s, %s, %s, %s)
        RETURNING id::text AS id
        """,
        (user_id, ticker.upper(), exchange.upper(), f"{ticker.upper()} AI Analysis Chat"),
    )
    return row["id"]


# ── Messages ──────────────────────────────────────────────────────────────────

def save_message(
    session_id: str,
    role: str,
    content: str,
    model_used: str | None = None,
    tokens_used: int | None = None,
    context_sources: list | None = None,
) -> None:
    """Persist a chat message to framework_db.

    Governance rule: a failed save here is NOT non-fatal. Callers should NOT
    swallow exceptions with `except: logger.warning(...)` — let them bubble up
    so monitoring + alerts can fire. Silent failure = lost AI audit record.
    """
    _fw_execute(
        """
        INSERT INTO datapai.chat_messages
            (session_id, role, content, model_used, tokens_used, context_sources)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            session_id,
            role,
            content,
            model_used,
            tokens_used,
            json.dumps(context_sources or []),
        ),
    )
    # Touch session updated_at (same direct connection — keeps the two writes
    # temporally close; no explicit transaction because psycopg2 autocommit is on)
    _fw_execute(
        "UPDATE datapai.chat_sessions SET updated_at = now() WHERE id = %s",
        (session_id,),
    )


def get_history(session_id: str, limit: int = 20) -> list[dict]:
    """
    Return the last `limit` messages for a session, oldest first.
    Returns list of {role, content} dicts (OpenAI message format).
    """
    rows = query(
        """
        SELECT role, content FROM (
            SELECT role, content, created_at
            FROM datapai.chat_messages
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        ) sub
        ORDER BY created_at ASC
        """,
        (session_id, limit),
    )
    return [{"role": r["role"], "content": r["content"]} for r in rows]


# ── User Preferences (extracted from chat) ───────────────────────────────────

def save_user_preference(user_id: str, pref_key: str, pref_value: str, source_message: str = "") -> None:
    """Upsert a user preference extracted from chat. Routes through direct
    framework_db connection (user_preferences is an FDW alias on stock_db)."""
    _fw_execute(
        """
        INSERT INTO datapai.user_preferences (user_id, pref_key, pref_value, source_message, updated_at)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT (user_id, pref_key)
        DO UPDATE SET pref_value = EXCLUDED.pref_value,
                      source_message = EXCLUDED.source_message,
                      updated_at = now()
        """,
        (str(user_id), pref_key, pref_value, source_message[:500] if source_message else ""),
    )


def get_user_preferences(user_id: str) -> dict[str, str]:
    """Get all stored preferences for a user as {key: value} dict."""
    rows = query(
        "SELECT pref_key, pref_value FROM datapai.user_preferences WHERE user_id = %s",
        (str(user_id),),
    )
    return {r["pref_key"]: r["pref_value"] for r in rows}


def extract_and_save_preferences(user_id: str, user_message: str) -> None:
    """
    Extract user preferences from a chat message using simple keyword matching.
    Fast, no LLM call needed — runs after every user message.
    """
    msg = user_message.lower().strip()
    if len(msg) < 10:
        return  # too short to contain preferences

    # Risk tolerance
    if any(w in msg for w in ["aggressive", "high risk", "speculative"]):
        save_user_preference(user_id, "risk_tolerance", "aggressive", user_message)
    elif any(w in msg for w in ["conservative", "low risk", "safe", "cautious"]):
        save_user_preference(user_id, "risk_tolerance", "conservative", user_message)
    elif "moderate" in msg and "risk" in msg:
        save_user_preference(user_id, "risk_tolerance", "moderate", user_message)

    # Investment horizon
    if any(w in msg for w in ["long term", "long-term", "2+ year", "5 year", "10 year", "buy and hold"]):
        save_user_preference(user_id, "investment_horizon", "long_term", user_message)
    elif any(w in msg for w in ["short term", "short-term", "day trad", "scalp", "intraday"]):
        save_user_preference(user_id, "investment_horizon", "short_term", user_message)
    elif any(w in msg for w in ["swing", "week", "medium term", "medium-term"]):
        save_user_preference(user_id, "investment_horizon", "medium_term", user_message)

    # Trading style
    if any(w in msg for w in ["day trad", "scalp", "intraday"]):
        save_user_preference(user_id, "trading_style", "day_trader", user_message)
    elif any(w in msg for w in ["swing trad"]):
        save_user_preference(user_id, "trading_style", "swing_trader", user_message)
    elif any(w in msg for w in ["buy and hold", "buy & hold", "hold for"]):
        save_user_preference(user_id, "trading_style", "buy_and_hold", user_message)

    # Portfolio focus
    if any(w in msg for w in ["value invest", "undervalued", "bargain"]):
        save_user_preference(user_id, "portfolio_focus", "value", user_message)
    elif any(w in msg for w in ["growth", "high growth", "momentum"]):
        save_user_preference(user_id, "portfolio_focus", "growth", user_message)
    elif any(w in msg for w in ["dividend", "income", "yield"]):
        save_user_preference(user_id, "portfolio_focus", "income", user_message)

    # Sector interests (extract from mentions)
    sectors = {
        "tech": "Technology", "technology": "Technology", "ai": "Technology",
        "health": "Healthcare", "biotech": "Healthcare", "pharma": "Healthcare",
        "energy": "Energy", "oil": "Energy", "mining": "Energy",
        "finance": "Financials", "bank": "Financials",
        "real estate": "Real Estate", "reit": "Real Estate",
    }
    for keyword, sector in sectors.items():
        if keyword in msg and any(w in msg for w in ["interested", "focus", "like", "prefer", "into"]):
            save_user_preference(user_id, "sector_interest", sector, user_message)
            break

    # Country/exchange preference
    if any(w in msg for w in ["asx", "australian", "aussie"]):
        save_user_preference(user_id, "preferred_exchange", "ASX", user_message)
    elif any(w in msg for w in ["us stock", "nasdaq", "nyse", "s&p"]):
        save_user_preference(user_id, "preferred_exchange", "US", user_message)


def build_preferences_context(user_id: str) -> str:
    """Build a system prompt section from stored user preferences."""
    prefs = get_user_preferences(user_id)
    if not prefs:
        return ""
    lines = ["[User Preferences — remembered from previous conversations]"]
    label_map = {
        "risk_tolerance": "Risk tolerance",
        "investment_horizon": "Investment horizon",
        "trading_style": "Trading style",
        "portfolio_focus": "Portfolio focus",
        "sector_interest": "Sector interest",
        "preferred_exchange": "Preferred exchange",
        "favourite_stocks": "Favourite stocks",
    }
    for k, v in prefs.items():
        label = label_map.get(k, k.replace("_", " ").title())
        lines.append(f"  • {label}: {v}")
    lines.append("Use these to personalise responses. Do NOT ask the user to repeat this info.")
    return "\n".join(lines)


def list_sessions(user_id: int, ticker: Optional[str] = None, limit: int = 10) -> list[dict]:
    """List recent sessions for a user, optionally filtered by ticker."""
    if ticker:
        rows = query(
            """
            SELECT id::text, ticker, exchange, title, created_at, updated_at
            FROM datapai.chat_sessions
            WHERE user_id = %s AND ticker = %s
            ORDER BY updated_at DESC LIMIT %s
            """,
            (user_id, ticker.upper(), limit),
        )
    else:
        rows = query(
            """
            SELECT id::text, ticker, exchange, title, created_at, updated_at
            FROM datapai.chat_sessions
            WHERE user_id = %s
            ORDER BY updated_at DESC LIMIT %s
            """,
            (user_id, limit),
        )
    return rows
