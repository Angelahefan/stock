# ═══════════════════════════════════════════════════════════════════════════════
# stock_chat/endpoint.py  —  POST /agent/stock-chat
#                             GET  /agent/stock-chat/sessions
#                             POST /agent/stock-chat/profile
#
# Uses RouterChatClient from llm_client.py — IMPORT ONLY, never modified.
# ═══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.llm_client import RouterChatClient, OpenAIChatClient
from .history import get_or_create_session, create_new_session, save_message, get_history, list_sessions, extract_and_save_preferences
from .user_profile import get_profile, update_profile
from .context_builder import build_system_prompt
from .user_context import extract_user_context_fast, sync_watchlist_to_context
from .twenty_context import log_chat_to_twenty
from .db import query, execute

logger = logging.getLogger(__name__)

# ── Token usage limits (env-var configurable) ────────────────────────────────
# Cost estimates: Gemini 2.5 Flash Lite ≈ $0.075/1M input + $0.30/1M output
# At ~2K tokens per request → ~$0.0007/request → ~7,000 requests per $5
import time as _time

_config_cache: dict = {}
_config_cache_ts: float = 0
_CONFIG_CACHE_TTL = 300  # 5 minutes


def _load_all_config() -> dict:
    """Load all config from sys_common_config into memory. Cached for 5 min."""
    global _config_cache, _config_cache_ts
    now = _time.time()
    if _config_cache and (now - _config_cache_ts) < _CONFIG_CACHE_TTL:
        return _config_cache
    try:
        from .db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT config_type, config_key, config_value
                    FROM datapai.sys_common_config
                    WHERE (effective_to IS NULL OR effective_to >= CURRENT_DATE)
                """)
                result = {}
                for ct, ck, cv in cur.fetchall():
                    result[f"{ct}.{ck}"] = cv
                _config_cache = result
                _config_cache_ts = now
                return result
    except Exception:
        return _config_cache or {}


def _load_config(config_type: str, config_key: str, default: str) -> str:
    """Get a config value. Reads from 5-min cache, not DB per call."""
    return _load_all_config().get(f"{config_type}.{config_key}", default)

def _get_user_plan(user_id: int) -> str:
    """Get user's plan from datapai.users table. Returns 'watch' if unknown."""
    if user_id == 0:
        return "watch"
    try:
        from .db import query
        rows = query("SELECT plan FROM datapai.users WHERE id = %s", (str(user_id),))
        if rows and rows[0].get("plan"):
            return rows[0]["plan"]
    except Exception:
        pass
    return "watch"


def _get_limit(key: str, default: str) -> int:
    return int(_load_config("chat_limits", key, default))

def _get_float_limit(key: str, default: str) -> float:
    return float(_load_config("chat_limits", key, default))


def _check_anon_budget(ip: str) -> dict | None:
    """Check anonymous visitor limit by IP. Returns error dict or None if OK."""
    try:
        from .db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO datapai.anonymous_usage (ip, message_count, first_seen)
                    VALUES (%s, 1, NOW())
                    ON CONFLICT (ip) DO UPDATE SET message_count = datapai.anonymous_usage.message_count + 1
                    RETURNING message_count
                """, [ip])
                count = cur.fetchone()[0]
        anon_limit = _get_limit("anon_msg_limit", "20")
        if count > anon_limit:
            return {
                "error": "anonymous_limit",
                "message": f"Daily limit reached ({anon_limit} requests) as you haven't registered yet. Please register or login for 200+/day.",
                "limit": anon_limit,
                "used": count,
                "action": "REGISTER",
            }
    except Exception as e:
        logger.warning("Anon budget check failed (allowing): %s", e)
    return None


def _check_token_budget(user_id: int, plan: str = "watch") -> dict | None:
    """Check if user has exceeded their token budget. Returns error dict or None if OK."""
    if user_id == 0:
        return None  # anonymous handled by _check_anon_budget
    uid = str(user_id)
    is_paid = plan not in ("watch", "", None)
    # Per-plan limits from DB
    plan_daily_key = f"{plan}_daily_limit" if plan in ("individual", "pro", "business") else "daily_limit_free"
    plan_monthly_key = f"{plan}_monthly_limit" if plan in ("individual", "pro", "business") else "free_monthly_limit"
    daily_limit = _get_limit(plan_daily_key, "200")
    monthly_limit = _get_limit(plan_monthly_key, "500")

    try:
        # Check daily
        rows = query(
            "SELECT COALESCE(request_count, 0) as cnt, COALESCE(cost_usd, 0) as cost "
            "FROM datapai.user_token_usage WHERE user_id = %s AND usage_date = CURRENT_DATE",
            (uid,),
        )
        daily_count = rows[0]["cnt"] if rows else 0
        if daily_count >= daily_limit:
            msg = (f"You've reached your daily limit ({daily_limit} requests). Try again tomorrow!"
                   if is_paid else
                   f"You've used all {daily_limit} free messages today. Upgrade to Individual plan for unlimited daily access and premium AI features.")
            return {
                "error": msg,
                "message": msg,
                "limit_type": "daily",
                "action": "UPGRADE" if not is_paid else None,
                "upgradeUrl": "/pricing",
            }

        # Check monthly
        rows = query(
            "SELECT COALESCE(SUM(request_count), 0) as cnt, COALESCE(SUM(cost_usd), 0) as cost "
            "FROM datapai.user_token_usage WHERE user_id = %s "
            "AND usage_date >= date_trunc('month', CURRENT_DATE)",
            (uid,),
        )
        monthly_count = rows[0]["cnt"] if rows else 0
        monthly_cost = rows[0]["cost"] if rows else 0
        if monthly_count >= monthly_limit:
            msg = (f"You've reached your monthly limit ({monthly_limit} requests). Resets next month."
                   if is_paid else
                   f"You've used all {monthly_limit} free messages this month. Upgrade to Individual plan for unlimited monthly access.")
            return {
                "error": msg,
                "message": msg,
                "limit_type": "monthly",
                "action": "UPGRADE" if not is_paid else None,
                "upgradeUrl": "/pricing",
            }
        cost_cap = _get_float_limit("cost_limit_monthly_usd", "5.0")
        if monthly_cost >= cost_cap:
            return {
                "error": f"Monthly cost cap (${cost_cap:.0f}) reached. Resets next month.",
                "limit_type": "cost",
                "upgradeUrl": "/pricing",
            }
    except Exception as e:
        logger.warning("Token budget check failed (allowing): %s", e)
    return None


def _get_local_company_name(ticker: str, exchange: str, lang: str) -> str | None:
    """Fast DB lookup for localized company name from stock_directory."""
    try:
        # Try exact exchange match first, then any exchange
        rows = query(
            "SELECT name FROM datapai.stock_directory "
            "WHERE symbol = %s AND lang = %s AND exchange = %s LIMIT 1",
            (ticker.upper(), lang, exchange.upper()),
        )
        if not rows:
            rows = query(
                "SELECT name FROM datapai.stock_directory "
                "WHERE symbol = %s AND lang = %s LIMIT 1",
                (ticker.upper(), lang),
            )
        return rows[0]["name"] if rows else None
    except Exception:
        return None


async def _yahoo_quick_price(ticker: str, exchange: str) -> dict:
    """
    Fast async Yahoo Finance price fetch for Gemini function calling.
    Uses the v8 chart API (single HTTP call, ~300ms).
    Returns dict with price, prev_close, change%, currency, market_state.
    """
    import httpx

    _SUFFIX = {
        "ASX": ".AX", "XASX": ".AX",
        "HKEX": ".HK", "SEHK": ".HK",
        "TSE": ".T", "JPX": ".T", "TYO": ".T",
        "TWSE": ".TW", "TPE": ".TW",
        "SGX": ".SI",
        "SSE": ".SS", "SZSE": ".SZ",
        "KRX": ".KS", "KOSPI": ".KS",
        "BSE": ".BO", "NSE": ".NS",
        "SET": ".BK",
        "IDX": ".JK", "JKSE": ".JK",
        "BURSA": ".KL",
    }

    ex = exchange.upper()
    suffix = _SUFFIX.get(ex, "")
    symbol = f"{ticker}{suffix}" if suffix else ticker

    try:
        import time as _time

        async with httpx.AsyncClient(timeout=5) as client:
            # First call with 1d to get meta + trading period
            resp = await client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            data = resp.json()
            result = data["chart"]["result"][0]
            meta = result["meta"]

            company_name = meta.get("longName") or meta.get("shortName", "")
            price = meta.get("regularMarketPrice", 0)
            prev_close = meta.get("chartPreviousClose") or meta.get("previousClose", 0)
            currency = meta.get("currency", "USD")
            reg_time = meta.get("regularMarketTime", 0)
            tz_name = meta.get("exchangeTimezoneName", "")

            change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0

            # Determine if market is currently in live trading session
            now_ts = int(_time.time())
            trading_period = meta.get("currentTradingPeriod", {}).get("regular", {})
            tp_start = trading_period.get("start", 0)
            tp_end = trading_period.get("end", 0)
            is_live = tp_start <= now_ts <= tp_end if tp_start and tp_end else False

            # OHLCV: use 1d bar from initial response (works for both live and closed)
            # During live: 1d bar has running OHLCV; after close: official EOD
            # meta.regularMarketPrice is always accurate regardless
            day_open = day_high = day_low = volume = None
            indicators = result.get("indicators", {})
            quotes = indicators.get("quote", [{}])[0] if indicators.get("quote") else {}
            if quotes:
                o = (quotes.get("open") or [None])[0]
                h = (quotes.get("high") or [None])[0]
                l = (quotes.get("low") or [None])[0]
                v = (quotes.get("volume") or [None])[0]
                if o is not None: day_open = round(o, 2)
                if h is not None: day_high = round(h, 2)
                if l is not None: day_low  = round(l, 2)
                if v is not None: volume   = v

            # Format the trade timestamp in the exchange's local timezone
            trade_time_str = ""
            trade_date_str = ""
            if reg_time and tz_name:
                try:
                    from datetime import datetime
                    import pytz
                    tz = pytz.timezone(tz_name)
                    dt = datetime.utcfromtimestamp(reg_time).replace(tzinfo=pytz.utc).astimezone(tz)
                    trade_date_str = dt.strftime("%b %d")       # e.g. "Apr 01"
                    _TZ_LABEL = {
                        "Australia/Sydney": "Sydney time", "Australia/Melbourne": "Sydney time",
                        "America/New_York": "New York time", "US/Eastern": "New York time",
                        "Asia/Hong_Kong": "Hong Kong time", "Asia/Tokyo": "Tokyo time",
                        "Asia/Taipei": "Taipei time", "Asia/Singapore": "Singapore time",
                        "Asia/Shanghai": "Shanghai time", "Asia/Seoul": "Seoul time",
                        "Asia/Kolkata": "Mumbai time", "Asia/Bangkok": "Bangkok time",
                        "Asia/Jakarta": "Jakarta time", "Asia/Kuala_Lumpur": "KL time",
                    }
                    tz_label = _TZ_LABEL.get(tz_name, tz_name.split("/")[-1] + " time")
                    trade_time_str = f"{dt.strftime('%I:%M %p')} {tz_label}"  # "04:00 PM New York time"
                except Exception:
                    pass

            if is_live:
                price_label = f"Live {trade_date_str} {trade_time_str}".strip()   # "Live Apr 01 03:41 PM"
            else:
                price_label = f"Close {trade_date_str} {trade_time_str}".strip()  # "Close Apr 01 04:10 PM"

            out = {
                "ticker": ticker,
                "company_name": company_name,
                "exchange": ex,
                "price": round(price, 4),
                "previous_close": round(prev_close, 4),
                "change_percent": change_pct,
                "currency": currency,
                "is_live": is_live,
                "trade_date": trade_date_str,
                "trade_time": trade_time_str,
                "price_label": price_label,
                "source": "Yahoo Finance",
            }
            if day_open is not None: out["open"] = day_open
            if day_high is not None: out["day_high"] = day_high
            if day_low  is not None: out["day_low"] = day_low
            if volume   is not None: out["volume"] = volume
            return out
    except Exception as e:
        logger.warning("Yahoo quick price failed for %s.%s: %s", ticker, exchange, e)
        return {"ticker": ticker, "exchange": exchange, "error": str(e)}


def _record_token_usage(user_id: int, tokens: int = 0, cost_usd: float = 0) -> None:
    """Upsert daily token usage for a user."""
    if user_id == 0:
        return
    try:
        execute(
            """INSERT INTO datapai.user_token_usage (user_id, usage_date, tokens_used, cost_usd, request_count)
               VALUES (%s, CURRENT_DATE, %s, %s, 1)
               ON CONFLICT (user_id, usage_date)
               DO UPDATE SET tokens_used = datapai.user_token_usage.tokens_used + EXCLUDED.tokens_used,
                             cost_usd = datapai.user_token_usage.cost_usd + EXCLUDED.cost_usd,
                             request_count = datapai.user_token_usage.request_count + 1""",
            (str(user_id), tokens, cost_usd),
        )
    except Exception as e:
        logger.warning("Token usage record failed (non-fatal): %s", e)

router = APIRouter()


# ── Request / Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    ticker:          str
    exchange:        str       = "US"
    message:         str
    user_id:         int       = 0          # 0 = anonymous fallback. Legacy int (from
                                             # Next.js parseInt(UUID) = 4-digit prefix).
    # Phase 1.14 (#4, 2026-04-12): the real full UUID, passed from the frontend
    # so downstream lookups (plan, Twenty CRM, email resolution) can match on
    # the actual user identity rather than a 4-digit prefix. Optional for
    # backward compat with older frontend builds.
    user_uuid:       Optional[str] = None
    session_id:      Optional[str] = None   # None = auto-resolve latest session
    new_session:     bool      = False      # True = force fresh session
    lang:            str       = "en"
    # Optional grounding context passed from Next.js (already fetched by frontend)
    ta_signal_md:    Optional[str] = None
    snapshot_text:   Optional[str] = None
    # Rich 7-dimension investor profile from Next.js investor_profile table.
    # When present, supersedes legacy Python user_profiles lookup.
    profile_context: Optional[str] = None


class ProfileUpdateRequest(BaseModel):
    user_id:          int
    portfolio_tickers: Optional[list[str]] = None
    risk_tolerance:   Optional[str]        = None
    investment_style: Optional[str]        = None
    preferred_lang:   Optional[str]        = None
    custom_context:   Optional[dict]       = None


# ── Chat endpoint ─────────────────────────────────────────────────────────────

@router.post("/stock-chat")
async def stock_chat(req: ChatRequest):
    """
    Conversational AI co-pilot for a specific stock ticker.
    """
    ticker   = req.ticker.upper()
    exchange = req.exchange.upper()

    # ── 0. Token budget check ────────────────────────────────────────────────
    plan = _get_user_plan(req.user_id)
    budget_err = _check_token_budget(req.user_id, plan)
    if budget_err:
        raise HTTPException(status_code=429, detail=budget_err)

    # ── 1. Session ────────────────────────────────────────────────────────────
    try:
        if req.new_session:
            session_id = create_new_session(req.user_id, ticker, exchange)
        elif req.session_id:
            session_id = req.session_id
        else:
            session_id = get_or_create_session(req.user_id, ticker, exchange)
    except Exception as e:
        # GOVERNANCE rule: session setup failures are loud ERRORs, not warnings.
        # The ephemeral fallback below still lets the user get an answer, but
        # without a session_id the chat will NOT be persisted → audit gap.
        logger.error(
            "GOVERNANCE: session setup FAILED (chat will be ephemeral, NOT persisted) user_id=%s ticker=%s: %s",
            req.user_id, ticker, e,
        )
        session_id = None  # Graceful degradation — still answer, just don't persist

    # ── 2. History ────────────────────────────────────────────────────────────
    history: list[dict] = []
    if session_id:
        try:
            history = get_history(session_id, limit=10)
        except Exception as e:
            logger.warning("History load failed: %s", e)

    # ── 3. User profile ───────────────────────────────────────────────────────
    try:
        profile = get_profile(req.user_id)
        lang    = req.lang or profile.get("preferred_lang", "en")
    except Exception as e:
        logger.warning("Profile load failed: %s", e)
        profile = {}
        lang    = req.lang

    # ── 4. System prompt ──────────────────────────────────────────────────────
    # Phase 1.14 (#4): prefer the full user_uuid (passed by new frontend
    # builds) over the legacy parseInt-prefix int. Fall back to the int for
    # backward compatibility with older Next.js builds.
    user_id_for_context: str | None = None
    if req.user_uuid:
        user_id_for_context = str(req.user_uuid).strip() or None
    if not user_id_for_context and req.user_id:
        user_id_for_context = str(req.user_id)
    user_id_str = user_id_for_context  # preserved name for downstream code

    system_prompt = build_system_prompt(
        ticker          = ticker,
        exchange        = exchange,
        user_profile    = profile,
        ta_signal_md    = req.ta_signal_md,
        snapshot_text   = req.snapshot_text,
        user_message    = req.message,
        lang            = lang,
        profile_context = req.profile_context,
        user_id         = user_id_str,
    )

    # ── 5. Build messages for LLM ─────────────────────────────────────────────
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": req.message})

    # ── 6. LLM call ───────────────────────────────────────────────────────────
    try:
        client   = RouterChatClient()
        response = client.chat(messages, temperature=0.3)
        reply    = response.get("content", "").strip()
        model    = response.get("model", "unknown")
        tokens   = response.get("usage", {}).get("total_tokens")
    except Exception as e:
        logger.error("LLM call failed for %s: %s", ticker, e)
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")

    # ── 7. Persist (AI governance rule — Phase 1.13, 2026-04-12) ───────────
    # A failed persist is NOT non-fatal. A user message + AI reply that is
    # not stored is a lost audit record, and AI governance says we can't
    # leave black boxes. We still return the reply to the user (they got
    # their answer), but we log at ERROR level and rely on ops monitoring.
    #
    # context_sources is currently an empty list but should be populated
    # in a future phase with the names of each system-prompt block that
    # was injected (user_profile, twenty_crm, rag_tinyfish, etc.) so
    # audits can reproduce what the LLM saw.
    if session_id:
        try:
            save_message(session_id, "user",      req.message, context_sources=[])
            save_message(session_id, "assistant", reply, model_used=model, tokens_used=tokens)
            # Extract user context: fast keywords inline, LLM extraction in nightly batch
            if user_id_str:
                extract_user_context_fast(user_id_str, req.message)
                extract_and_save_preferences(user_id_str, req.message)
        except Exception as e:
            # ERROR not WARNING — this is a governance violation (lost audit record).
            # Loud enough to show up in monitoring / journalctl.
            logger.error(
                "GOVERNANCE: chat persist FAILED for session=%s user_id=%s ticker=%s: %s",
                session_id, user_id_str, ticker, e,
            )

    # ── 7b. Log chat to Twenty CRM as a Note on stockClient (Phase 1.12.2) ──
    # Fire-and-forget audit trail. Failures are logged but do NOT affect the
    # chat response. Never raises. Note: Twenty write is a secondary audit
    # surface — the primary is chat_messages above. Twenty note gives human
    # reviewers a timeline view on the customer record; chat_messages gives
    # the full history for LLM context recall + training data + compliance.
    if user_id_str:
        try:
            log_chat_to_twenty(
                user_id=user_id_str,
                user_message=req.message,
                assistant_reply=reply,
                ticker=ticker,
                exchange=exchange,
                model=model,
                tokens_used=tokens,
            )
        except Exception as e:
            logger.warning("Twenty chat log failed (non-fatal secondary audit): %s", e)

    return {
        "ok":         True,
        "reply":      reply,
        "session_id": session_id,
        "model":      model,
        "ticker":     ticker,
    }


# ── Streaming chat endpoint ───────────────────────────────────────────────────

@router.post("/stock-chat/stream")
async def stock_chat_stream(req: ChatRequest, request: Request):
    """
    Streaming version of stock_chat — returns SSE chunks as words arrive.
    Skips the dual-review pass so first token appears in ~1-2 seconds.

    SSE event types:
      {"type": "session",  "session_id": "...", "ticker": "..."}
      {"type": "chunk",    "text": "..."}
      {"type": "done",     "model": "..."}
      {"type": "error",    "message": "..."}
    """
    ticker   = req.ticker.upper()
    exchange = req.exchange.upper()

    # ── Anonymous visitor limit (5 messages total, then must register) ─────
    if req.user_id == 0:
        client_ip = request.client.host if request.client else "unknown"
        anon_err = _check_anon_budget(client_ip)
        if anon_err:
            async def _anon_limit_stream():
                yield f"data: {json.dumps({'type': 'error', 'message': anon_err['message'], 'action': 'REGISTER'})}\n\n"
            return StreamingResponse(_anon_limit_stream(), media_type="text/event-stream")

    # ── Token budget check ──────────────────────────────────────────────────
    _plan = _get_user_plan(req.user_id)
    budget_err = _check_token_budget(req.user_id, _plan)
    if budget_err:
        async def _limit_stream():
            yield f"data: {json.dumps({'type': 'error', 'message': budget_err.get('message', budget_err.get('error', 'Limit reached')), 'action': 'UPGRADE'})}\n\n"
        return StreamingResponse(_limit_stream(), media_type="text/event-stream")

    # ── Session ───────────────────────────────────────────────────────────────
    try:
        if req.new_session:
            session_id = create_new_session(req.user_id, ticker, exchange)
        elif req.session_id:
            session_id = req.session_id
        else:
            session_id = get_or_create_session(req.user_id, ticker, exchange)
    except Exception as e:
        # GOVERNANCE: loud ERROR, not warning. Ephemeral chat = audit gap.
        logger.error(
            "GOVERNANCE: stream session setup FAILED (chat ephemeral, NOT persisted) user_id=%s ticker=%s: %s",
            req.user_id, ticker, e,
        )
        session_id = None

    # ── History + profile + system prompt (same as non-streaming) ─────────────
    history: list[dict] = []
    if session_id:
        try:
            history = get_history(session_id, limit=10)
        except Exception as e:
            logger.warning("History load failed: %s", e)

    try:
        profile = get_profile(req.user_id)
        lang    = req.lang or profile.get("preferred_lang", "en")
    except Exception as e:
        logger.warning("Profile load failed: %s", e)
        profile = {}
        lang    = req.lang

    from .context_builder import build_system_prompt
    # Phase 1.14 (#4): prefer full user_uuid over legacy int prefix
    user_id_for_context: str | None = None
    if req.user_uuid:
        user_id_for_context = str(req.user_uuid).strip() or None
    if not user_id_for_context and req.user_id:
        user_id_for_context = str(req.user_id)
    user_id_str = user_id_for_context
    system_prompt = build_system_prompt(
        ticker          = ticker,
        exchange        = exchange,
        user_profile    = profile,
        ta_signal_md    = req.ta_signal_md,
        snapshot_text   = req.snapshot_text,
        user_message    = req.message,
        lang            = lang,
        profile_context = req.profile_context,
        user_id         = user_id_str,
    )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": req.message})

    # ── SSE generator (Gemini streaming + function calling for prices) ──────────
    _GOOGLE_API_KEY = __import__("os").environ.get("GOOGLE_API_KEY", "")
    _GOOGLE_MODEL   = __import__("os").environ.get("GOOGLE_MODEL", "gemini-2.0-flash")

    async def event_stream():
        import httpx as _httpx

        # Send session_id immediately so frontend can store it
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id, 'ticker': ticker})}\n\n"

        # ── AI governance guardrail (pre-call gate) ─────────────────────────
        # Runs policy-as-data check against datapai.dim_ai_control (213 rules
        # / 16 frameworks). On BLOCK/ESCALATE, streams a cited refusal and a
        # structured governance event so the UI can show APRA/ASIC/OWASP
        # citations live. Fail-open if module unavailable (availability > demo).
        from .guardrail_bridge import run_gate_sync, governance_sse_event, footer_markdown, persist_decision
        _gate_meta = {"domain": "stock", "ticker": ticker, "exchange": exchange, "user_id": req.user_id}
        _gate = run_gate_sync(message=req.message, metadata=_gate_meta)
        # Write-once audit evidence — never blocks the turn; ERROR-level log on failure.
        persist_decision(
            _gate,
            user_prompt=req.message,
            metadata=_gate_meta,
            session_id=session_id,
            user_id=user_id_str,
        )
        # Track whether this turn was blocked by governance. When blocked we
        # still call the LLM but with a factual-only constraint, and we render
        # the governance UI at the end. When allowed we stay completely silent
        # about governance — buyers don't want a citation footer on every
        # routine "what's the price of X" question.
        _blocked = bool(_gate and _gate["verdict"] in ("block", "escalate"))
        _block_constraint = ""
        if _blocked:
            refusal_lead = _gate["refusal"] or "I can't give buy/sell or personalised investment advice under our governance policy. Here is factual information instead:"
            yield f"data: {json.dumps({'type': 'chunk', 'text': refusal_lead + chr(10) + chr(10)})}\n\n"
            # Inject a factual-only constraint into the system prompt so the
            # LLM still answers about the ticker (price, news, key facts) but
            # refuses to recommend buy/sell/hold.
            _block_constraint = (
                "\n\nGOVERNANCE CONSTRAINT (this turn only): The user's request "
                "was flagged as personalised investment advice. You MUST NOT "
                "recommend buy/sell/hold actions, target prices, position "
                "sizing, or any personal financial advice. You MAY still "
                "answer factual questions about the ticker (current price, "
                "recent news, fundamentals, sector context) by calling tools "
                "as normal. Keep the answer factual and neutral."
            )

        full_reply = ""
        model_used = _GOOGLE_MODEL

        # Convert OpenAI-style messages → Gemini format
        system_text  = ""
        gem_contents = []
        for m in messages:
            if m["role"] == "system":
                system_text = m["content"]
            elif m["role"] == "user":
                gem_contents.append({"role": "user",  "parts": [{"text": m["content"]}]})
            elif m["role"] == "assistant":
                gem_contents.append({"role": "model", "parts": [{"text": m["content"]}]})

        # Function declaration — Gemini calls this when user asks about any stock price
        price_fn_decl = {
            "name": "get_stock_price",
            "description": "Get the current or latest stock price from Yahoo Finance. ALWAYS call this when the user asks about a stock price, instead of using Google Search for prices.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "ticker": {
                        "type": "STRING",
                        "description": "Stock ticker symbol. Examples: AAPL, BHP, 2330, 9984, D05"
                    },
                    "exchange": {
                        "type": "STRING",
                        "description": "Exchange code: US, ASX, HKEX, TSE, TWSE, SGX, SSE, SZSE, KRX, BSE, NSE, SET, IDX, BURSA"
                    }
                },
                "required": ["ticker", "exchange"]
            }
        }

        # NOTE: Google Search and Function Calling CANNOT be combined in Gemini API.
        # We choose function calling for accurate prices (top priority).
        # Gemini's training data covers general market info (news, fundamentals, etc).
        payload: dict = {
            "contents":         gem_contents,
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1024},
            "tools": [
                {"functionDeclarations": [price_fn_decl]},
            ],
        }
        # Append governance block constraint (if any) to the system prompt
        if _block_constraint:
            system_text = (system_text + _block_constraint) if system_text else _block_constraint
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models"
            f"/{_GOOGLE_MODEL}:streamGenerateContent"
            f"?key={_GOOGLE_API_KEY}&alt=sse"
        )

        MAX_FN_ROUNDS = 3  # Safety: max function-call round-trips

        try:
            async with _httpx.AsyncClient(timeout=55) as hc:
                for _round in range(MAX_FN_ROUNDS + 1):
                    fn_call = None
                    model_parts = []  # Collect all parts from model response

                    async with hc.stream("POST", url, json=payload) as resp:
                        if resp.status_code != 200:
                            err_body = await resp.aread()
                            logger.error("Gemini API %s: %s", resp.status_code, err_body[:500])
                            # If function calling not supported by model, retry without tools
                            if _round == 0 and (b"unction" in err_body or b"tool" in err_body):
                                logger.warning("Function calling not supported, falling back to no tools")
                                payload.pop("tools", None)
                                continue
                            yield f"data: {json.dumps({'type': 'error', 'message': f'Gemini API error {resp.status_code}'})}\n\n"
                            return

                        _events_seen = 0
                        _last_finish_reason = None
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            raw = line[6:].strip()
                            if not raw or raw == "[DONE]":
                                continue
                            _events_seen += 1
                            try:
                                chunk = json.loads(raw)
                            except Exception as e:
                                logger.warning("Gemini SSE JSON parse failed: %s — raw=%s", e, raw[:200])
                                continue
                            try:
                                cand = (chunk.get("candidates") or [{}])[0]
                                _last_finish_reason = cand.get("finishReason") or _last_finish_reason
                                parts = (cand.get("content") or {}).get("parts") or []
                                for part in parts:
                                    # Skip "thought" parts from gemini-2.5 thinking mode —
                                    # these are reasoning traces, not user-visible output.
                                    if part.get("thought"):
                                        continue
                                    if part.get("text"):
                                        full_reply += part["text"]
                                        yield f"data: {json.dumps({'type': 'chunk', 'text': part['text']})}\n\n"
                                        model_parts.append(part)
                                    elif "functionCall" in part:
                                        fn_call = part["functionCall"]
                                        model_parts.append(part)
                            except Exception as e:
                                logger.warning("Gemini chunk handling failed: %s — chunk=%s", e, str(chunk)[:200])
                        # Empty-parts response from gemini-2.5 with finishReason=STOP
                        # usually means the system prompt contained a value the model
                        # refused on (e.g. malformed numeric data). Log loudly so we
                        # catch future data-quality issues before users do.
                        if not full_reply and not fn_call and _last_finish_reason == "STOP":
                            logger.error(
                                "Gemini returned empty response (likely sanity-refusal on bad system-prompt data) "
                                "ticker=%s round=%d events=%d", ticker, _round, _events_seen,
                            )

                    # No function call → done streaming
                    if not fn_call:
                        break

                    # Execute the function call
                    fn_name = fn_call["name"]
                    fn_args = fn_call.get("args", {})
                    logger.info("Gemini function call: %s(%s)", fn_name, json.dumps(fn_args))

                    if fn_name == "get_stock_price":
                        fn_result = await _yahoo_quick_price(
                            fn_args.get("ticker", ""),
                            fn_args.get("exchange", "US"),
                        )
                        # Enrich with localized company name from stock_directory
                        if lang and lang != "en" and fn_result.get("ticker"):
                            local_name = _get_local_company_name(
                                fn_result["ticker"], fn_result.get("exchange", ""), lang
                            )
                            if local_name:
                                fn_result["company_name_local"] = local_name
                    else:
                        fn_result = {"error": f"Unknown function: {fn_name}"}

                    logger.info("Function result: %s", json.dumps(fn_result))

                    # Append model's function call + our response to conversation
                    gem_contents.append({
                        "role": "model",
                        "parts": model_parts if model_parts else [{"functionCall": fn_call}]
                    })
                    gem_contents.append({
                        "role": "user",
                        "parts": [{"functionResponse": {
                            "name": fn_name,
                            "response": {"name": fn_name, "content": fn_result}
                        }}]
                    })
                    payload["contents"] = gem_contents
                    # Loop continues → next streaming call with function result

        except Exception as e:
            logger.error("Gemini streaming failed for %s: %s", ticker, e)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        # Governance footer — ONLY show when the turn was actually blocked /
        # escalated. On allow/allow_with_conditions the UI stays clean: users
        # don't want a citation footer on routine factual questions like
        # "what's the price of BHP". The full audit trail is still persisted
        # to datapai.fct_ai_guardrail_decision regardless (write-once).
        if _blocked:
            gov_evt = governance_sse_event(_gate)
            if gov_evt:
                yield gov_evt
            md = footer_markdown(_gate)
            if md:
                yield f"data: {json.dumps({'type': 'chunk', 'text': md})}\n\n"

        yield f"data: {json.dumps({'type': 'done', 'blocked': _blocked})}\n\n"

        # Persist after streaming completes (AI governance rule — Phase 1.13)
        # Loud ERROR on failure, not "non-fatal warning". See the non-streaming
        # endpoint above for the full rationale.
        if session_id and full_reply:
            try:
                save_message(session_id, "user",      req.message,  context_sources=[])
                save_message(session_id, "assistant", full_reply,   model_used=model_used)
                if user_id_str:
                    extract_user_context_fast(user_id_str, req.message)
                    extract_and_save_preferences(user_id_str, req.message)
            except Exception as e:
                logger.error(
                    "GOVERNANCE: chat stream persist FAILED for session=%s user_id=%s ticker=%s: %s",
                    session_id, user_id_str, ticker, e,
                )

        # Log chat to Twenty CRM as a Note on stockClient (Phase 1.12.2)
        # Fire-and-forget secondary audit trail. Non-fatal on any failure
        # because the primary audit record (chat_messages) landed above.
        if user_id_str and full_reply:
            try:
                est_tokens_for_note = (len(req.message) + len(full_reply)) // 4
                log_chat_to_twenty(
                    user_id=user_id_str,
                    user_message=req.message,
                    assistant_reply=full_reply,
                    ticker=ticker,
                    exchange=exchange,
                    model=model_used,
                    tokens_used=est_tokens_for_note,
                )
            except Exception as e:
                logger.warning("Twenty chat log failed (non-fatal secondary audit): %s", e)

        # Record token usage (estimate: ~4 chars per token)
        est_tokens = (len(req.message) + len(full_reply)) // 4
        est_cost = est_tokens * 0.0003 / 1000  # ~$0.30/1M output tokens
        _record_token_usage(req.user_id, est_tokens, est_cost)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",   # Disable nginx buffering
            "Cache-Control":     "no-cache",
            "Connection":        "keep-alive",
        },
    )


# ── Session history endpoint ──────────────────────────────────────────────────

@router.get("/stock-chat/sessions")
async def get_sessions(user_id: int, ticker: Optional[str] = None):
    try:
        sessions = list_sessions(user_id, ticker=ticker, limit=10)
        return {"ok": True, "sessions": sessions}
    except Exception as e:
        logger.error("list_sessions failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock-chat/history")
async def get_chat_history(session_id: str, limit: int = 50):
    try:
        msgs = get_history(session_id, limit=limit)
        return {"ok": True, "messages": msgs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── User profile endpoints ────────────────────────────────────────────────────

@router.get("/stock-chat/profile")
async def get_user_profile(user_id: int):
    try:
        profile = get_profile(user_id)
        return {"ok": True, "profile": profile}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stock-chat/profile")
async def update_user_profile(req: ProfileUpdateRequest):
    try:
        profile = update_profile(
            user_id          = req.user_id,
            portfolio_tickers= req.portfolio_tickers,
            risk_tolerance   = req.risk_tolerance,
            investment_style = req.investment_style,
            preferred_lang   = req.preferred_lang,
            custom_context   = req.custom_context,
        )
        return {"ok": True, "profile": profile}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Token usage endpoint ────────────────────────────────────────────────────

@router.get("/stock-chat/token-usage")
async def get_token_usage(user_id: str):
    """Get current token usage for a user (daily + monthly)."""
    try:
        daily = query(
            "SELECT COALESCE(request_count, 0) as cnt, COALESCE(cost_usd, 0) as cost "
            "FROM datapai.user_token_usage WHERE user_id = %s AND usage_date = CURRENT_DATE",
            (user_id,),
        )
        monthly = query(
            "SELECT COALESCE(SUM(request_count), 0) as cnt, COALESCE(SUM(cost_usd), 0) as cost "
            "FROM datapai.user_token_usage WHERE user_id = %s "
            "AND usage_date >= date_trunc('month', CURRENT_DATE)",
            (user_id,),
        )
        return {
            "ok": True,
            "daily": {"requests": daily[0]["cnt"] if daily else 0, "cost_usd": round(daily[0]["cost"] if daily else 0, 4)},
            "monthly": {"requests": monthly[0]["cnt"] if monthly else 0, "cost_usd": round(monthly[0]["cost"] if monthly else 0, 4)},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Signal recommendation tracking (P&L) ────────────────────────────────────

class RecordSignalRequest(BaseModel):
    user_id:      str
    ticker:       str
    exchange:     str = "US"
    signal_type:  str        # BUY, SELL, STRONG_BUY, STRONG_SELL
    signal_source: str = "screener"  # screener, copilot, ag2_synthesis
    entry_price:  Optional[float] = None
    metadata:     Optional[dict] = None


class CloseSignalRequest(BaseModel):
    recommendation_id: int
    exit_price:        float


@router.post("/stock-chat/record-signal")
async def record_signal(req: RecordSignalRequest):
    """Record a buy/sell recommendation for P&L tracking."""
    try:
        entry_price = req.entry_price
        if not entry_price:
            rows = query(
                "SELECT latest_close FROM datapai.screener_metrics WHERE ticker = %s LIMIT 1",
                (req.ticker.upper(),),
            )
            entry_price = rows[0]["latest_close"] if rows else None

        row = execute_returning(
            """INSERT INTO datapai.signal_recommendations
               (user_id, ticker, exchange, signal_type, signal_source, entry_price, entry_date, signal_metadata)
               VALUES (%s, %s, %s, %s, %s, %s, CURRENT_DATE, %s)
               RETURNING id, entry_price, entry_date::text""",
            (req.user_id, req.ticker.upper(), req.exchange.upper(),
             req.signal_type.upper(), req.signal_source,
             entry_price, json.dumps(req.metadata or {})),
        )
        return {"ok": True, "recommendation": row}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stock-chat/close-signal")
async def close_signal(req: CloseSignalRequest):
    """Close a recommendation and calculate P&L."""
    try:
        rows = query(
            "SELECT id, entry_price, signal_type FROM datapai.signal_recommendations WHERE id = %s",
            (req.recommendation_id,),
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Not found")
        rec = rows[0]
        entry = rec["entry_price"]
        pnl_pct = ((req.exit_price - entry) / entry) * 100 if entry else None
        if rec["signal_type"] in ("SELL", "STRONG_SELL") and pnl_pct is not None:
            pnl_pct = -pnl_pct  # SELL profits when price drops
        execute(
            """UPDATE datapai.signal_recommendations
               SET exit_price = %s, exit_date = CURRENT_DATE, pnl_pct = %s,
                   status = 'closed', updated_at = NOW()
               WHERE id = %s""",
            (req.exit_price, pnl_pct, req.recommendation_id),
        )
        return {"ok": True, "pnl_pct": pnl_pct}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock-chat/signal-performance")
async def signal_performance(user_id: str):
    """Get P&L summary for a user's signal recommendations."""
    try:
        open_recs = query(
            """SELECT r.id, r.ticker, r.signal_type, r.entry_price, r.entry_date::text,
                      r.signal_source, sm.latest_close as current_price,
                      CASE WHEN r.entry_price > 0 THEN
                        ROUND(((sm.latest_close - r.entry_price) / r.entry_price * 100)::numeric, 2)
                      END as unrealized_pnl_pct
               FROM datapai.signal_recommendations r
               LEFT JOIN datapai.screener_metrics sm ON sm.ticker = r.ticker
               WHERE r.user_id = %s AND r.status = 'open'
               ORDER BY r.entry_date DESC""",
            (user_id,),
        )
        closed_recs = query(
            """SELECT ticker, signal_type, entry_price, exit_price,
                      entry_date::text, exit_date::text, pnl_pct
               FROM datapai.signal_recommendations
               WHERE user_id = %s AND status = 'closed'
               ORDER BY exit_date DESC LIMIT 20""",
            (user_id,),
        )
        closed_pnls = [r["pnl_pct"] for r in closed_recs if r["pnl_pct"] is not None]
        win_count = sum(1 for p in closed_pnls if p > 0)
        total_closed = len(closed_pnls)
        return {
            "ok": True,
            "open_positions": open_recs,
            "closed_positions": closed_recs,
            "summary": {
                "total_open": len(open_recs),
                "total_closed": total_closed,
                "win_rate": round(win_count / total_closed * 100, 1) if total_closed else None,
                "avg_pnl_pct": round(sum(closed_pnls) / total_closed, 2) if total_closed else None,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
