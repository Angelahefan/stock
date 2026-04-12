# ═══════════════════════════════════════════════════════════════════════════════
# stock_chat/user_context.py  —  Continuous User Context Learning
#
# Accumulates what we learn about each user from chat, onboarding, watchlist.
# LLM-extracted, confidence-scored, always injected into prompts.
#
# Table: datapai.sys_user_context
# ═══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Optional

from .db import execute, execute_returning, query
from .fw_db import fw_execute as _fw_execute

logger = logging.getLogger(__name__)

# ── Context key taxonomy ──────────────────────────────────────────────────────
# pref/*       — user preferences (risk, horizon, style)
# behavior/*   — observed patterns (frequent tickers, session patterns)
# knowledge/*  — user's knowledge level and domains
# style/*      — communication preferences
# portfolio/*  — holdings, budget, tax
# goal/*       — investment goals and benchmarks

CONTEXT_TYPE_MAP = {
    "pref": "preference",
    "behavior": "behavior",
    "knowledge": "knowledge",
    "style": "style",
    "portfolio": "portfolio",
    "goal": "goal",
}

# ── Extraction prompt ─────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """Analyze this user message and extract any facts about the user's investment profile, preferences, or goals.

User message: "{user_message}"

Existing user context (do NOT re-extract these unless the value CHANGED):
{existing_context}

Extract ONLY new or updated facts. For each fact, provide:
- key: one of these standard keys:
  pref/risk_tolerance, pref/investment_horizon, pref/trading_style, pref/response_style, pref/analysis_preference, pref/language, pref/currency
  behavior/frequent_sectors, behavior/preferred_timeframe
  knowledge/level, knowledge/domains
  style/communication, style/detail_level
  portfolio/holdings, portfolio/budget_range, portfolio/tax_jurisdiction
  goal/current, goal/timeline, goal/benchmark
- value: the fact (concise, max 1 sentence)
- confidence: 0.0-1.0 (0.9 for explicit statements like "I'm aggressive", 0.5 for inferences)

Rules:
- ONLY extract facts the user EXPLICITLY stated or STRONGLY implied about THEMSELVES
- Do NOT infer preferences from the stock being discussed
- Do NOT re-extract facts already in existing context unless the value changed
- If nothing new to extract, return empty array
- IMPORTANT: The user may write in ANY language (Vietnamese, Chinese, Thai, Malay, Japanese, Korean, English).
  You MUST understand the message in its original language but ALWAYS write the extracted value in ENGLISH.
  Example: user says "Tôi thích cổ phiếu công nghệ" → {{"key": "behavior/frequent_sectors", "value": "Technology", "confidence": 0.8}}
  Example: user says "我是激进型投资者" → {{"key": "pref/risk_tolerance", "value": "aggressive", "confidence": 0.9}}

Return ONLY a JSON array (no markdown, no explanation):
[{{"key": "pref/risk_tolerance", "value": "aggressive", "confidence": 0.9}}]
Return [] if nothing to extract."""


# ── CRUD operations ───────────────────────────────────────────────────────────

def upsert_user_context(
    user_id: str,
    context_key: str,
    context_value: str,
    confidence: float = 0.7,
    source: str = "chat_extraction",
    source_detail: str = "",
) -> None:
    """Insert or update a user context entry. Bumps mention_count on conflict."""
    prefix = context_key.split("/")[0] if "/" in context_key else "pref"
    context_type = CONTEXT_TYPE_MAP.get(prefix, "preference")

    # Phase 1.13 fix: sys_user_context is an FDW alias on stock_db; writes
    # through the FDW bypass the remote-side DEFAULT nextval(id) clause.
    # Route through direct framework_db connection via fw_db.
    _fw_execute(
        """INSERT INTO datapai.sys_user_context
           (user_id, context_key, context_value, context_type, confidence, source, source_detail, mention_count)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
           ON CONFLICT (user_id, context_key)
           DO UPDATE SET
             context_value = EXCLUDED.context_value,
             confidence = GREATEST(datapai.sys_user_context.confidence, EXCLUDED.confidence),
             source = EXCLUDED.source,
             source_detail = EXCLUDED.source_detail,
             mention_count = datapai.sys_user_context.mention_count + 1,
             last_seen = NOW(),
             is_active = TRUE
        """,
        (user_id, context_key, context_value, context_type, confidence,
         source, (source_detail or "")[:500]),
    )


def get_user_context(user_id: str, min_confidence: float = 0.3, limit: int = 20) -> list[dict]:
    """Get all active context for a user, sorted by confidence then recency."""
    return query(
        """SELECT context_key, context_value, context_type, confidence, mention_count, last_seen
           FROM datapai.sys_user_context
           WHERE user_id = %s AND is_active = TRUE AND confidence >= %s
           ORDER BY confidence DESC, last_seen DESC
           LIMIT %s""",
        (user_id, min_confidence, limit),
    )


def get_user_context_dict(user_id: str) -> dict[str, str]:
    """Get user context as {key: value} dict (for injection into extraction prompt)."""
    rows = get_user_context(user_id, min_confidence=0.3, limit=30)
    return {r["context_key"]: r["context_value"] for r in rows}


# ── LLM-based extraction ─────────────────────────────────────────────────────

def extract_user_context(user_id: str, user_message: str) -> int:
    """
    Extract user context from a chat message using LLM.

    Runs after every user message. Uses cheapest model available.
    Returns number of context items extracted.
    """
    msg = user_message.strip()
    if len(msg) < 15:
        return 0  # too short to contain self-disclosure

    # Skip pure questions with no self-disclosure
    if msg.endswith("?") and len(msg) < 60 and not any(
        w in msg.lower() for w in ["i ", "my ", "i'm", "i am", "i like", "i prefer", "i want", "i have"]
    ):
        return 0

    # Get existing context to avoid re-extraction
    existing = get_user_context_dict(user_id)
    existing_text = "\n".join(f"  {k}: {v}" for k, v in existing.items()) if existing else "  (none yet)"

    prompt = EXTRACTION_PROMPT.format(
        user_message=msg[:500],
        existing_context=existing_text,
    )

    try:
        from agents.llm_client import RouterChatClient
        client = RouterChatClient()
        response = client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )

        # Parse response — handle both dict and string returns
        text = response.get("content", "") if isinstance(response, dict) else str(response)
        text = text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        if not text or text == "[]":
            return 0

        items = json.loads(text)
        if not isinstance(items, list):
            return 0

        extracted = 0
        for item in items:
            key = item.get("key", "").strip()
            value = item.get("value", "").strip()
            confidence = float(item.get("confidence", 0.5))

            if not key or not value or "/" not in key:
                continue
            if confidence < 0.3:
                continue

            upsert_user_context(
                user_id=user_id,
                context_key=key,
                context_value=value,
                confidence=min(confidence, 0.95),
                source="chat_extraction",
                source_detail=msg[:200],
            )
            extracted += 1

        if extracted:
            logger.info("Extracted %d context items for user %s", extracted, user_id[:8])
        return extracted

    except json.JSONDecodeError:
        logger.debug("User context extraction returned non-JSON (normal for no-match)")
        return 0
    except Exception as exc:
        logger.warning("User context extraction failed (non-fatal): %s", str(exc)[:100])
        return 0


# ── Batch extraction (concat all daily messages into 1 LLM call) ──────────────

BATCH_EXTRACTION_PROMPT = """Analyze ALL of this user's messages from today and extract any facts about their investment profile, preferences, goals, knowledge level, or communication style.

User messages (chronological order):
{messages_block}

Existing user context (do NOT re-extract these unless the value CHANGED):
{existing_context}

Extract ONLY new or updated facts. For each fact, provide:
- key: one of these standard keys:
  pref/risk_tolerance, pref/investment_horizon, pref/trading_style, pref/response_style, pref/analysis_preference, pref/language, pref/currency
  behavior/frequent_sectors, behavior/preferred_timeframe
  knowledge/level, knowledge/domains
  style/communication, style/detail_level
  portfolio/holdings, portfolio/budget_range, portfolio/tax_jurisdiction
  goal/current, goal/timeline, goal/benchmark
- value: the fact (concise, max 1 sentence)
- confidence: 0.0-1.0 (0.9 for explicit statements, 0.5 for inferences)

Rules:
- ONLY extract facts the user EXPLICITLY stated or STRONGLY implied about THEMSELVES
- Do NOT infer preferences from stocks being discussed (asking about BHP ≠ prefers mining)
- Do NOT re-extract facts already in existing context unless the value changed
- The user may write in ANY language — ALWAYS write values in ENGLISH
- If nothing new to extract, return empty array

Return ONLY a JSON array (no markdown):
[{{"key": "pref/risk_tolerance", "value": "aggressive", "confidence": 0.9}}]
Return [] if nothing to extract."""


def extract_user_context_batch(user_id: str, messages: list[str]) -> int:
    """
    Extract user context from ALL of a user's daily messages in a single LLM call.

    This is 4x cheaper than per-message extraction:
    - 4 messages × 1 call each = 4 calls
    - 4 messages concatenated × 1 call = 1 call

    Called by the nightly batch job, not inline.
    Returns number of context items extracted.
    """
    # Filter out short/question-only messages
    substantive = [m for m in messages if len(m.strip()) >= 15]
    if not substantive:
        return 0

    # Check if any message has self-disclosure signals
    has_self_ref = any(
        any(w in m.lower() for w in ["i ", "my ", "i'm", "i am", "i like", "i prefer",
                                      "i want", "i have", "tôi", "我", "ฉัน", "saya"])
        for m in substantive
    )
    if not has_self_ref:
        return 0  # pure questions, skip LLM call entirely

    # Concat messages with numbering
    messages_block = "\n".join(f"  [{i+1}] {m[:300]}" for i, m in enumerate(substantive[:10]))

    existing = get_user_context_dict(user_id)
    existing_text = "\n".join(f"  {k}: {v}" for k, v in existing.items()) if existing else "  (none yet)"

    prompt = BATCH_EXTRACTION_PROMPT.format(
        messages_block=messages_block,
        existing_context=existing_text,
    )

    try:
        from agents.llm_client import RouterChatClient
        client = RouterChatClient()
        response = client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )

        text = response.get("content", "") if isinstance(response, dict) else str(response)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        if not text or text == "[]":
            return 0

        items = json.loads(text)
        if not isinstance(items, list):
            return 0

        extracted = 0
        for item in items:
            key = item.get("key", "").strip()
            value = item.get("value", "").strip()
            confidence = float(item.get("confidence", 0.5))

            if not key or not value or "/" not in key:
                continue
            if confidence < 0.3:
                continue

            upsert_user_context(
                user_id=user_id,
                context_key=key,
                context_value=value,
                confidence=min(confidence, 0.95),
                source="chat_extraction",
                source_detail=f"batch: {len(substantive)} messages",
            )
            extracted += 1

        return extracted

    except json.JSONDecodeError:
        return 0
    except Exception as exc:
        logger.warning("Batch extraction failed for user %s: %s", user_id[:8], str(exc)[:100])
        return 0


# ── Fast keyword extraction (fallback when LLM unavailable) ──────────────────

def extract_user_context_fast(user_id: str, user_message: str) -> int:
    """
    Fast keyword-based extraction (no LLM call). Fallback for when LLM is
    unavailable or for low-priority messages. Mirrors the old
    extract_and_save_preferences() logic but writes to sys_user_context.
    """
    msg = user_message.lower().strip()
    if len(msg) < 10:
        return 0

    extracted = 0

    # Risk tolerance (EN + VI + ZH + TH)
    if any(w in msg for w in ["aggressive", "high risk", "speculative", "mạo hiểm", "激进", "เสี่ยงสูง"]):
        upsert_user_context(user_id, "pref/risk_tolerance", "aggressive", 0.8, "chat_extraction", msg[:200])
        extracted += 1
    elif any(w in msg for w in ["conservative", "low risk", "safe", "cautious", "an toàn", "bảo thủ", "保守", "ปลอดภัย"]):
        upsert_user_context(user_id, "pref/risk_tolerance", "conservative", 0.8, "chat_extraction", msg[:200])
        extracted += 1
    elif any(w in msg for w in ["moderate", "vừa phải", "温和", "ปานกลาง"]) and any(w in msg for w in ["risk", "rủi ro", "风险", "ความเสี่ยง"]):
        upsert_user_context(user_id, "pref/risk_tolerance", "moderate", 0.7, "chat_extraction", msg[:200])
        extracted += 1

    # Investment horizon (EN + VI + ZH + TH)
    if any(w in msg for w in ["long term", "long-term", "2+ year", "5 year", "10 year", "buy and hold", "dài hạn", "长期", "ระยะยาว"]):
        upsert_user_context(user_id, "pref/investment_horizon", "long_term", 0.8, "chat_extraction", msg[:200])
        extracted += 1
    elif any(w in msg for w in ["short term", "short-term", "day trad", "scalp", "intraday", "ngắn hạn", "短期", "ระยะสั้น"]):
        upsert_user_context(user_id, "pref/investment_horizon", "short_term", 0.8, "chat_extraction", msg[:200])
        extracted += 1
    elif any(w in msg for w in ["swing", "medium term", "medium-term", "trung hạn", "中期", "ระยะกลาง"]):
        upsert_user_context(user_id, "pref/investment_horizon", "medium_term", 0.7, "chat_extraction", msg[:200])
        extracted += 1

    # Trading style
    if any(w in msg for w in ["day trad", "scalp", "intraday"]):
        upsert_user_context(user_id, "pref/trading_style", "day_trader", 0.8, "chat_extraction", msg[:200])
        extracted += 1
    elif "swing trad" in msg:
        upsert_user_context(user_id, "pref/trading_style", "swing_trader", 0.8, "chat_extraction", msg[:200])
        extracted += 1
    elif any(w in msg for w in ["buy and hold", "buy & hold"]):
        upsert_user_context(user_id, "pref/trading_style", "buy_and_hold", 0.8, "chat_extraction", msg[:200])
        extracted += 1

    # Portfolio focus
    if any(w in msg for w in ["value invest", "undervalued", "bargain"]):
        upsert_user_context(user_id, "pref/trading_style", "value investing", 0.7, "chat_extraction", msg[:200])
        extracted += 1
    elif any(w in msg for w in ["dividend", "income", "yield"]):
        upsert_user_context(user_id, "pref/trading_style", "income/dividend", 0.7, "chat_extraction", msg[:200])
        extracted += 1

    # Sector interests
    sectors = {
        "tech": "Technology", "technology": "Technology", "ai": "Technology",
        "health": "Healthcare", "biotech": "Healthcare", "pharma": "Healthcare",
        "energy": "Energy", "oil": "Energy", "mining": "Mining",
        "finance": "Financials", "bank": "Financials",
        "real estate": "Real Estate", "reit": "Real Estate",
    }
    for keyword, sector in sectors.items():
        if keyword in msg and any(w in msg for w in ["interested", "focus", "like", "prefer", "into", "i "]):
            upsert_user_context(user_id, "behavior/frequent_sectors", sector, 0.6, "chat_extraction", msg[:200])
            extracted += 1
            break

    # Exchange preference
    if any(w in msg for w in ["asx", "australian", "aussie"]):
        upsert_user_context(user_id, "behavior/frequent_exchanges", "ASX", 0.7, "chat_extraction", msg[:200])
        extracted += 1
    elif any(w in msg for w in ["vietnam", "hose", "vnindex", "vietnamese"]):
        upsert_user_context(user_id, "behavior/frequent_exchanges", "HOSE", 0.7, "chat_extraction", msg[:200])
        extracted += 1
    elif any(w in msg for w in ["us stock", "nasdaq", "nyse", "s&p"]):
        upsert_user_context(user_id, "behavior/frequent_exchanges", "US", 0.7, "chat_extraction", msg[:200])
        extracted += 1

    return extracted


# ── Build prompt block ────────────────────────────────────────────────────────

def build_user_context_block(user_id: str, limit: int = 15) -> str:
    """
    Build a concise user context block for system prompt injection.
    Selects top-N context items by confidence x recency.
    Returns empty string if no context found.
    """
    if not user_id or user_id == "0":
        return ""

    rows = get_user_context(user_id, min_confidence=0.4, limit=limit)
    if not rows:
        return ""

    # Group by type
    by_type: dict[str, list] = defaultdict(list)
    for r in rows:
        by_type[r["context_type"]].append(r)

    type_labels = {
        "preference": "Preferences",
        "behavior": "Behavior Patterns",
        "knowledge": "Knowledge Level",
        "style": "Communication Style",
        "portfolio": "Portfolio",
        "goal": "Investment Goals",
    }

    lines = [
        "[User Context — learned from previous conversations]",
        "Use this to personalise responses. Do NOT ask about things listed here.",
    ]

    for ctype, label in type_labels.items():
        items = by_type.get(ctype, [])
        if not items:
            continue
        lines.append(f"  [{label}]")
        for item in items:
            key_short = item["context_key"].split("/", 1)[-1].replace("_", " ").title()
            conf_note = f" (inferred)" if item["confidence"] < 0.7 else ""
            lines.append(f"    - {key_short}: {item['context_value']}{conf_note}")

    return "\n".join(lines)


# ── Profile sync (investor_profile → sys_user_context) ────────────────────────

PROFILE_FIELD_MAP = {
    "risk_tolerance": "pref/risk_tolerance",
    "investment_horizon": "pref/investment_horizon",
    "strategies": "pref/trading_style",
    "preferred_exchanges": "behavior/frequent_exchanges",
    "preferred_sectors": "behavior/frequent_sectors",
    "portfolio_tickers": "portfolio/holdings",
    "portfolio_size": "portfolio/budget_range",
    "analysis_preference": "pref/analysis_preference",
    "response_style": "style/detail_level",
    "tax_context": "portfolio/tax_jurisdiction",
    "preferred_lang": "pref/language",
}


def sync_profile_to_context(user_id: str, profile: dict) -> int:
    """
    Sync investor_profile fields to sys_user_context with confidence=1.0.
    Called when user saves their profile in the settings page.
    Returns number of context items synced.
    """
    synced = 0
    for profile_field, context_key in PROFILE_FIELD_MAP.items():
        value = profile.get(profile_field)
        if not value:
            continue
        # Convert lists to comma-separated strings
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        upsert_user_context(
            user_id=user_id,
            context_key=context_key,
            context_value=str(value),
            confidence=1.0,
            source="onboarding",
            source_detail="investor_profile sync",
        )
        synced += 1
    if synced:
        logger.info("Synced %d profile fields to user context for %s", synced, user_id[:8])
    return synced


# ── Watchlist sync ────────────────────────────────────────────────────────────

def sync_watchlist_to_context(user_id: str) -> int:
    """
    Sync watchlist patterns to sys_user_context.
    Called when user adds/removes from watchlist.
    """
    rows = query(
        "SELECT symbol, exchange FROM datapai.watchlist WHERE user_id = %s ORDER BY added_at DESC",
        (user_id,),
    )
    if not rows:
        return 0

    tickers = [f"{r['symbol']} ({r['exchange']})" for r in rows[:10]]
    exchanges = list(set(r["exchange"] for r in rows))

    upsert_user_context(
        user_id=user_id,
        context_key="behavior/watchlist_tickers",
        context_value=", ".join(tickers),
        confidence=0.9,
        source="watchlist_pattern",
    )
    upsert_user_context(
        user_id=user_id,
        context_key="behavior/frequent_exchanges",
        context_value=", ".join(exchanges),
        confidence=0.8,
        source="watchlist_pattern",
    )
    return 2
