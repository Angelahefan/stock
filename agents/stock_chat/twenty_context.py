# ═══════════════════════════════════════════════════════════════════════════════
# stock_chat/twenty_context.py  —  Phase 1.12 — Twenty CRM ↔ chatbot integration
#
# This module bridges the DATAP.AI Twenty CRM (at crm-stock.datap.ai) with the
# stock chatbot so that:
#
#   1. READ path — build_twenty_context_block(email) returns a system-prompt
#      block describing the user's stockClient record (plan, markets, devices,
#      signup source, last login). Injected alongside the existing
#      build_user_context_block() output in context_builder.py.
#
#   2. WRITE path — log_chat_to_twenty(email, user_message, assistant_reply, ...)
#      creates a Note record on the user's stockClient in Twenty, so every
#      chatbot conversation leaves an audit trail visible in the Twenty UI.
#      Called AFTER the streaming response completes so it never blocks the
#      user. Failures are logged but non-fatal.
#
# Design doc: docs/phase-journals/2026-04-12-phase-1.12-chatbot-crm-design.md
# Implementation: 2026-04-12 (autonomous mode)
#
# Architecture principles (from Phase 1.10-4B):
#   - Twenty is DB-driven — enum values read from Twenty at runtime, not hardcoded
#   - All writes are fire-and-forget with graceful degradation
#   - Never crash the chatbot if Twenty is down — empty block / failed log is OK
# ═══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from agents.lib.twenty_client import TwentyClient, TwentyError, TwentyAuthError

from .db import query

logger = logging.getLogger(__name__)


# ── Module-level client cache ────────────────────────────────────────────────
# A single TwentyClient is reused across chat requests. The client itself
# maintains an httpx session so connection pooling is free. We lazily
# initialize on first use and swallow init errors (chat still works without
# Twenty, just without the CRM block).

_twenty_client: Optional[TwentyClient] = None
_twenty_client_init_failed: bool = False


def _get_client() -> Optional[TwentyClient]:
    """Lazily construct the Twenty client. Returns None if the client can't
    be initialized (usually missing TWENTY_STOCK_API_KEY env var, or Twenty
    is unreachable). Cached — subsequent calls reuse the same instance."""
    global _twenty_client, _twenty_client_init_failed

    if _twenty_client is not None:
        return _twenty_client
    if _twenty_client_init_failed:
        return None

    try:
        # TwentyClient.from_env() reads TWENTY_STOCK_URL (falls back to
        # https://crm-stock.datap.ai) and TWENTY_STOCK_API_KEY.
        # Also check for the TWENTY_STOCK_SERVER_URL variant, which is what
        # .env.dev actually uses.
        if not os.environ.get("TWENTY_STOCK_URL") and os.environ.get("TWENTY_STOCK_SERVER_URL"):
            os.environ["TWENTY_STOCK_URL"] = os.environ["TWENTY_STOCK_SERVER_URL"]

        _twenty_client = TwentyClient.from_env()
        logger.info("[twenty_context] client initialized (base=%s)", _twenty_client.base_url)
        return _twenty_client
    except TwentyAuthError as e:
        logger.warning("[twenty_context] Twenty API key missing or invalid, disabling CRM integration: %s", e)
        _twenty_client_init_failed = True
        return None
    except Exception as e:
        logger.warning("[twenty_context] failed to init TwentyClient, disabling CRM integration: %s", e)
        _twenty_client_init_failed = True
        return None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_email_from_user_id(user_id: str | int) -> Optional[str]:
    """
    Resolve a user_id (from the chat JWT / request payload) to the user's
    email so we can look them up in Twenty. Returns None for the anonymous
    user (user_id == 0 or empty) or if no matching row exists.

    The chatbot receives user_id in one of these shapes:
      1. Int 0 → anonymous (return None)
      2. Full UUID string (e.g. "9974f810-2256-4f65-82d0-6639c3fd6124") →
         direct match on datapai.users.id
      3. Truncated int prefix (e.g. 9974 from `parseInt("9974f810-...")` in
         the Next.js frontend) → prefix-match LIKE '{user_id}%' on
         datapai.users.id
      4. Integer that could match datapai.users.id starting with digits → same
         as case 3

    Case 3/4 is the quirky one: the Next.js frontend's chat route in
    datapai-stock-fe does `parseInt(user.userId, 10)` which for a UUID
    "9974f810-..." returns 9974 — JavaScript's parseInt reads leading digits
    and stops at the first non-digit (the hyphen). So the stock chat endpoint
    has historically received a 4-digit int that's actually the UUID prefix.

    We resolve this with a LIKE prefix match. If multiple users share the
    same numeric prefix (very rare — 10000:1 collision in a base16 UUID for
    4 digits), we pick the one most recently created.
    """
    if not user_id or str(user_id) == "0":
        return None

    user_id_str = str(user_id).strip()
    if not user_id_str:
        return None

    try:
        # Case 2: full UUID string — direct match
        if len(user_id_str) >= 32:  # UUIDs are 36 chars with hyphens, 32 without
            rows = query("SELECT email FROM datapai.users WHERE id = %s LIMIT 1", (user_id_str,))
            if rows:
                return rows[0]["email"] if isinstance(rows[0], dict) else rows[0][0]

        # Case 3/4: short numeric or non-UUID prefix — try LIKE match
        # We prefer the most recent user with a matching id prefix.
        rows = query(
            """
            SELECT email FROM datapai.users
            WHERE id LIKE %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (f"{user_id_str}%",),
        )
        if rows:
            return rows[0]["email"] if isinstance(rows[0], dict) else rows[0][0]
    except Exception as e:
        logger.debug("[twenty_context] email lookup for user_id=%s failed: %s", user_id, e)
    return None


def _plan_tone_hint(plan: Optional[str]) -> str:
    """Map subscriptionPlan → a short tone instruction for the LLM.
    Kept inline for now; could be promoted to sys_common_config later
    per the DB-driven default principle if it evolves."""
    if not plan:
        return ""
    plan_upper = plan.upper()
    return {
        "WATCH":        "free tier — be helpful but gently mention upgrades where they unlock value",
        "INDIVIDUAL":   "paying user ($49 AUD/mo) — use premium tone, no upgrade nags",
        "PROFESSIONAL": "paying user ($299 AUD/mo) — active trader, expect deeper analysis",
        "BUSINESS":     "paying user ($999 AUD/mo) — team account, expect professional tone",
    }.get(plan_upper, "")


def _platform_hint(signup_source: Optional[str]) -> str:
    """Map signupSource → a formatting hint for the LLM."""
    if not signup_source:
        return ""
    s = signup_source.upper()
    if s in ("MOBILE_IOS", "MOBILE_ANDROID"):
        return "mobile user — prefer short bullets, avoid tables"
    if s == "WEB":
        return "web user — tables and longer content OK"
    return ""


def _format_last_login(iso_str: Optional[str]) -> str:
    """Turn an ISO datetime into a human-readable 'X days ago' string.
    Returns empty string if missing or malformed."""
    if not iso_str:
        return ""
    try:
        # Twenty returns ISO with Z suffix
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - dt
        days = delta.days
        if days < 0:
            return ""  # clock skew, ignore
        if days == 0:
            hours = delta.seconds // 3600
            if hours == 0:
                return "just now"
            return f"{hours}h ago"
        if days == 1:
            return "1 day ago"
        if days < 30:
            return f"{days} days ago"
        if days < 365:
            return f"{days // 30} months ago"
        return f"{days // 365} years ago"
    except Exception:
        return ""


# ── READ path: build the Twenty context block ────────────────────────────────

def build_twenty_context_block(user_id: str | int | None) -> str:
    """
    Phase 1.12.1 — READ side.

    Query Twenty for the user's stockClient record (by email, resolved from
    user_id) and return a formatted system-prompt block. Returns empty string
    for any of:
      - anonymous user (user_id falsy or "0")
      - Twenty unreachable or API key invalid
      - no stockClient record exists for this email
      - any unexpected error (logged + empty fallback)

    Called from context_builder.py::build_system_prompt() alongside
    build_user_context_block(). Both blocks complement each other — the
    user_context block has LLM-learned fine-grained preferences, this
    block has structured CRM identity data.
    """
    email = _get_email_from_user_id(user_id)
    if not email:
        return ""

    client = _get_client()
    if client is None:
        return ""

    try:
        record = client.find_one(
            "stockClients",
            filter={"email": {"eq": email}},
            fields=[
                "id",
                "email",
                "subscriptionPlan",
                "signupSource",
                "preferredMarkets",
                "deviceCount",
                "monthlyQueryCount",
                "lastLoginAt",
            ],
        )
    except (TwentyError, TwentyAuthError) as e:
        logger.warning("[twenty_context] find_one failed for %s: %s", email, e)
        return ""
    except Exception as e:
        logger.warning("[twenty_context] unexpected error fetching stockClient for %s: %s", email, e)
        return ""

    if not record:
        return ""

    plan = record.get("subscriptionPlan")
    signup_source = record.get("signupSource")
    preferred_markets = record.get("preferredMarkets") or []
    device_count = record.get("deviceCount") or 0
    monthly_query_count = record.get("monthlyQueryCount") or 0
    last_login_iso = record.get("lastLoginAt")

    lines = ["[Customer Profile — from CRM]"]

    # Plan with tone hint
    plan_line = f"- Plan: {plan}" if plan else "- Plan: (unknown)"
    tone_hint = _plan_tone_hint(plan)
    if tone_hint:
        plan_line = f"- Plan: {plan} ({tone_hint})"
    lines.append(plan_line)

    # Markets
    if preferred_markets:
        markets_str = ", ".join(sorted(set(preferred_markets)))
        lines.append(f"- Preferred Markets: {markets_str}")

    # Signup source with platform hint
    if signup_source:
        hint = _platform_hint(signup_source)
        if hint:
            lines.append(f"- Signup: {signup_source} ({hint})")
        else:
            lines.append(f"- Signup: {signup_source}")

    # Device count
    if device_count > 0:
        lines.append(f"- Active Devices: {device_count}")

    # Last login
    last_login_str = _format_last_login(last_login_iso)
    if last_login_str:
        lines.append(f"- Last Login: {last_login_str}")

    # Query activity (30-day rolling)
    if monthly_query_count > 0:
        lines.append(f"- Queries This Month: {monthly_query_count}")

    if len(lines) <= 1:
        # Nothing useful to report beyond the header — skip
        return ""

    return "\n".join(lines)


# ── WRITE path: log chat to Twenty as a Note linked to stockClient ───────────

def log_chat_to_twenty(
    *,
    user_id: str | int | None,
    user_message: str,
    assistant_reply: str,
    ticker: Optional[str] = None,
    exchange: Optional[str] = None,
    model: Optional[str] = None,
    tokens_used: Optional[int] = None,
    latency_ms: Optional[int] = None,
) -> bool:
    """
    Phase 1.12.2 — WRITE side.

    Create a Note in Twenty linked to the user's stockClient via noteTarget,
    containing the user's message + assistant reply in markdown format.

    Fire-and-forget semantics: called from endpoint.py AFTER the chat response
    has already been persisted to our local DB and returned to the user.
    Returns True on success, False on any failure. Failures are logged only;
    the chat response is never delayed or broken by a Twenty outage.

    Title format:  Chat: <first 60 chars of user message>
    Body format:   markdown with headers for User and Assistant sections,
                   metadata line with ticker/model/tokens/latency.
    """
    # Skip anonymous users
    if not user_id or str(user_id) == "0":
        return False

    # Resolve email
    email = _get_email_from_user_id(user_id)
    if not email:
        logger.debug("[twenty_context] skipping log: no email for user_id=%s", user_id)
        return False

    client = _get_client()
    if client is None:
        return False

    # Find the stockClient id (required for noteTarget linkage)
    try:
        record = client.find_one(
            "stockClients",
            filter={"email": {"eq": email}},
            fields=["id"],
        )
    except Exception as e:
        logger.warning("[twenty_context] log_chat: find_one failed for %s: %s", email, e)
        return False

    if not record:
        logger.debug("[twenty_context] log_chat: no stockClient for %s — skipping", email)
        return False

    stock_client_id = record["id"]

    # Build title + body
    title = _build_note_title(user_message, ticker)
    body_md = _build_note_body(
        user_message=user_message,
        assistant_reply=assistant_reply,
        ticker=ticker,
        exchange=exchange,
        model=model,
        tokens_used=tokens_used,
        latency_ms=latency_ms,
    )

    # Step 1: createNote
    try:
        note_result = client.graphql(
            """
            mutation CreateNote($data: NoteCreateInput!) {
                createNote(data: $data) { id title }
            }
            """,
            {"data": {"title": title, "bodyV2": {"markdown": body_md}}},
        )
        note = note_result.get("createNote")
        if not note or not note.get("id"):
            logger.warning("[twenty_context] createNote returned no id: %s", note_result)
            return False
        note_id = note["id"]
    except Exception as e:
        logger.warning("[twenty_context] createNote failed for %s: %s", email, e)
        return False

    # Step 2: createNoteTarget linking note → stockClient
    try:
        client.graphql(
            """
            mutation CreateNoteTarget($data: NoteTargetCreateInput!) {
                createNoteTarget(data: $data) { id }
            }
            """,
            {"data": {"noteId": note_id, "targetStockClientId": stock_client_id}},
        )
        logger.info(
            "[twenty_context] logged chat to Twenty: email=%s ticker=%s note_id=%s",
            email, ticker, note_id[:8],
        )
        return True
    except Exception as e:
        logger.warning("[twenty_context] createNoteTarget failed for note %s: %s", note_id, e)
        # Orphan note exists in Twenty but isn't linked to anyone. Not
        # catastrophic — shows up as a "floating" note. Could be cleaned up
        # by a reconciliation job later. Don't attempt to delete here because
        # the deletion could also fail and we'd be chasing our tail.
        return False


def _build_note_title(user_message: str, ticker: Optional[str]) -> str:
    """Build a short scannable title for the Twenty Note."""
    # First 60 chars of the user message, collapsed whitespace
    snippet = " ".join((user_message or "").split())[:60]
    if len(user_message) > 60:
        snippet += "…"
    if ticker:
        return f"Chat [{ticker}]: {snippet}" if snippet else f"Chat [{ticker}]"
    return f"Chat: {snippet}" if snippet else "Chat"


def _build_note_body(
    *,
    user_message: str,
    assistant_reply: str,
    ticker: Optional[str] = None,
    exchange: Optional[str] = None,
    model: Optional[str] = None,
    tokens_used: Optional[int] = None,
    latency_ms: Optional[int] = None,
) -> str:
    """Format the chat exchange as markdown for the Twenty Note body."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Ticker/exchange header line
    ticker_line = ""
    if ticker:
        ticker_line = f" · ticker: {ticker}"
        if exchange:
            ticker_line += f" ({exchange})"

    user_line = f"**User** ({now_str}{ticker_line}):"

    # Assistant metadata line
    meta_bits = []
    if model:
        meta_bits.append(model)
    if tokens_used is not None:
        meta_bits.append(f"{tokens_used} tokens")
    if latency_ms is not None:
        meta_bits.append(f"{latency_ms}ms")
    assistant_meta = f" ({', '.join(meta_bits)})" if meta_bits else ""
    assistant_line = f"**Assistant**{assistant_meta}:"

    # Truncate to prevent huge notes (Twenty's bodyV2 has no strict limit, but
    # ~50k chars would slow down the UI and gzip transport). Keep it reasonable.
    MAX_MSG = 8000
    MAX_REPLY = 12000
    user_clean = (user_message or "").strip()[:MAX_MSG]
    reply_clean = (assistant_reply or "").strip()[:MAX_REPLY]
    user_trunc = "\n*(truncated)*" if len(user_message or "") > MAX_MSG else ""
    reply_trunc = "\n*(truncated)*" if len(assistant_reply or "") > MAX_REPLY else ""

    return (
        f"{user_line}\n"
        f"> {user_clean.replace(chr(10), chr(10) + '> ')}{user_trunc}\n"
        "\n"
        f"{assistant_line}\n"
        f"{reply_clean}{reply_trunc}\n"
    )
