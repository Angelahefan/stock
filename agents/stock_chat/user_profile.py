# ═══════════════════════════════════════════════════════════════════════════════
# stock_chat/user_profile.py  —  Persistent user context
# Table: datapai.user_profiles
# This is the "memory" that travels across all sessions so users never
# have to repeat: portfolio, risk tolerance, investment style, language.
# ═══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import logging
from typing import Optional

from .db import execute, execute_returning, query

logger = logging.getLogger(__name__)


def get_profile(user_id: int) -> dict:
    """Return user profile, creating a default one if it doesn't exist."""
    rows = query(
        "SELECT * FROM datapai.user_profiles WHERE user_id = %s",
        (user_id,),
    )
    if rows:
        return rows[0]

    # Auto-create default profile on first chat
    execute(
        """
        INSERT INTO datapai.user_profiles (user_id)
        VALUES (%s)
        ON CONFLICT (user_id) DO NOTHING
        """,
        (user_id,),
    )
    return {
        "user_id": user_id,
        "portfolio_tickers": [],
        "risk_tolerance": "moderate",
        "investment_style": "general",
        "preferred_lang": "en",
        "custom_context": {},
    }


def update_profile(
    user_id: int,
    portfolio_tickers: Optional[list] = None,
    risk_tolerance: Optional[str] = None,
    investment_style: Optional[str] = None,
    preferred_lang: Optional[str] = None,
    custom_context: Optional[dict] = None,
) -> dict:
    """Partial update — only supplied fields are changed."""
    current = get_profile(user_id)

    new_portfolio = portfolio_tickers if portfolio_tickers is not None else current["portfolio_tickers"]
    new_risk      = risk_tolerance    if risk_tolerance    is not None else current["risk_tolerance"]
    new_style     = investment_style  if investment_style  is not None else current["investment_style"]
    new_lang      = preferred_lang    if preferred_lang    is not None else current["preferred_lang"]
    new_ctx       = custom_context    if custom_context    is not None else current["custom_context"]

    execute(
        """
        INSERT INTO datapai.user_profiles
            (user_id, portfolio_tickers, risk_tolerance, investment_style, preferred_lang, custom_context)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            portfolio_tickers = EXCLUDED.portfolio_tickers,
            risk_tolerance    = EXCLUDED.risk_tolerance,
            investment_style  = EXCLUDED.investment_style,
            preferred_lang    = EXCLUDED.preferred_lang,
            custom_context    = EXCLUDED.custom_context,
            updated_at        = now()
        """,
        (user_id, new_portfolio, new_risk, new_style, new_lang, json.dumps(new_ctx)),
    )
    return get_profile(user_id)


def build_profile_context(profile: dict) -> str:
    """
    Convert a user profile dict into a system-prompt context block.
    This is injected at the start of every chat so the LLM knows who it's
    talking to without the user having to repeat themselves.
    """
    lines = ["[User Investment Profile]"]

    tickers = profile.get("portfolio_tickers") or []
    if tickers:
        lines.append(f"Portfolio: {', '.join(tickers)}")

    risk = profile.get("risk_tolerance", "moderate")
    style = profile.get("investment_style", "general")
    lines.append(f"Risk tolerance: {risk} | Investment style: {style}")

    ctx = profile.get("custom_context") or {}
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except Exception:
            ctx = {}
    if ctx.get("notes"):
        lines.append(f"Notes: {ctx['notes']}")

    lang = profile.get("preferred_lang", "en")
    if lang == "zh":
        lines.append("Preferred output language: Simplified Chinese (简体中文)")

    return "\n".join(lines)
