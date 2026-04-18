"""
TinyFish Financial Signal API
==============================
FastAPI service exposing the TinyFish financial signal pipeline.

Called by datapai-tinyfish (Next.js) on port 8005.
All responses follow shared-api-contract.md envelope format.

Run locally:
  uvicorn app:app --host 0.0.0.0 --port 8005 --reload

Environment variables:
  DATAPAI_PLATFORM_DIR    path to datapai-streamlit (platform framework)
  TINYFISH_API_KEY        Bearer token (empty = no auth)
  LLM_MODE                paid | local | hybrid   (drives RouterChatClient)
  LLM_PRIMARY_PROVIDER    openai | bedrock | ollama
"""

from __future__ import annotations

import platform_init  # noqa: F401 — links datapai-streamlit framework via sys.path

import logging
import os
from typing import Optional

from fastapi import Depends, FastAPI, Security, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import JSONResponse

from agents.tinyfish_signals.tinyfish_contracts import (
    ApiResponse,
    CrossValidateRequest,
    DetectSignalRequest,
    GenerateSummaryRequest,
    HealthData,
    RunPipelineRequest,
    SignalType,
    ValidationStatus,
    ChangeType,
)
from agents.tinyfish_signals import (
    run_forward_guidance_agent,
    run_risk_disclosure_agent,
    run_tone_shift_agent,
    run_cross_validation_agent,
    classify_signals,
    run_tinyfish_signal_pipeline,
    classify_change_type,
    run_investigation_agent,
)
from agents.tinyfish_signals.signal_classifier import classify_signals
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

_API_KEY     = os.getenv("TINYFISH_API_KEY", "")
_LLM_MODE    = os.getenv("LLM_MODE", "local")
_LLM_PRIMARY = os.getenv("LLM_PRIMARY_PROVIDER", "openai")

# ── B2B API client auth (for api.datap.ai) ───────────────────────────────────
import hashlib
import time as _time
import psycopg2
import psycopg2.extras

_FRAMEWORK_DB = {
    "host": os.getenv("FRAMEWORK_DB_HOST", "localhost"),
    "port": int(os.getenv("FRAMEWORK_DB_PORT", "5433")),
    "dbname": os.getenv("FRAMEWORK_DB_NAME", "datapai_auth_db"),
    "user": os.getenv("FRAMEWORK_DB_USER", "postgres"),
    "password": os.getenv("FRAMEWORK_DB_PASSWORD", "auth_root_2026"),
}


def _hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _verify_b2b_api_key(api_key: str) -> dict | None:
    """Verify B2B API key against auth.api_clients. Returns client dict or None."""
    try:
        conn = psycopg2.connect(**_FRAMEWORK_DB)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT client_id, client_name, tier, rate_limit_rpm, monthly_quota, is_active "
            "FROM auth.api_clients WHERE api_key_hash = %s",
            [_hash_api_key(api_key)],
        )
        client = cur.fetchone()
        cur.close()
        conn.close()
        if client and client["is_active"]:
            return dict(client)
        return None
    except Exception as e:
        logger.error("B2B API key verification failed: %s", e)
        return None


def _log_api_usage(client_id: str, endpoint: str, method: str, status_code: int,
                   response_ms: int, ip: str):
    """Log B2B API usage for billing."""
    try:
        conn = psycopg2.connect(**_FRAMEWORK_DB)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO auth.api_usage_log (client_id, endpoint, method, status_code, response_ms, ip_address) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [client_id, endpoint, method, status_code, response_ms, ip],
        )
        cur.close()
        conn.close()
    except Exception as e:
        logger.error("API usage logging failed: %s", e)


# ── Webhook firing ───────────────────────────────────────────────────────────
import hmac as _hmac
import json as _json
import concurrent.futures as _futures
import requests as _http

_webhook_pool = _futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="webhook")


def _fire_webhooks(event: str, payload: dict):
    """Fire webhooks for a given event. Runs in background threads."""
    try:
        conn = psycopg2.connect(**_FRAMEWORK_DB)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT id, url, secret FROM auth.api_webhooks "
            "WHERE events @> ARRAY[%s]::text[] AND is_active = TRUE",
            [event],
        )
        webhooks = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error("webhook query failed: %s", e)
        return

    for wh in webhooks:
        _webhook_pool.submit(_deliver_webhook, wh["id"], wh["url"], wh["secret"], event, payload)


def _deliver_webhook(webhook_id: int, url: str, secret: str, event: str, payload: dict):
    """POST payload to webhook URL with HMAC signature. Logs result."""
    body = _json.dumps({"event": event, "data": payload}, default=str)
    sig = _hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-DataPAI-Event": event,
        "X-DataPAI-Signature": sig,
    }

    status_code, success, error_msg, latency_ms = None, False, None, 0
    try:
        start = _time.time()
        resp = _http.post(url, data=body, headers=headers, timeout=10)
        latency_ms = int((_time.time() - start) * 1000)
        status_code = resp.status_code
        success = 200 <= resp.status_code < 300
    except Exception as e:
        latency_ms = int((_time.time() - start) * 1000) if 'start' in dir() else 0
        error_msg = str(e)[:500]

    # Log delivery attempt
    try:
        conn = psycopg2.connect(**_FRAMEWORK_DB)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO auth.api_webhook_log (webhook_id, event, status_code, success, latency_ms, error_msg) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [webhook_id, event, status_code, success, latency_ms, error_msg],
        )
        cur.close()
        conn.close()
    except Exception as e:
        logger.error("webhook log failed: %s", e)


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="DataPAI — TinyFish Financial Signal API",
    description=(
        "Detects and validates financial signals in corporate language changes. "
        "Part of the TinyFish accelerator demo. See shared-api-contract.md."
    ),
    version="1.0.0",
)


@app.on_event("startup")
async def startup_event() -> None:
    """Initialise AI observability via the platform-be governance primitive.

    Configuration (endpoint, environment, enabled flag, instrumentor filter)
    can be driven from datapai.sys_common_config using
    config_type='openlit' and config_key='openlit_datapai-stock_<attr>'.
    Env vars (OPENLIT_OTLP_ENDPOINT, ENVIRONMENT, OPENLIT_ENABLED) are the
    fallback when no DB row is present.
    """
    from agents.observability import init_openlit
    init_openlit(app_name="datapai-stock")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── B2B API Gateway Middleware ────────────────────────────────────────────────
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse as StarletteJSONResponse


class B2BApiMiddleware(BaseHTTPMiddleware):
    """
    When request comes via api.datap.ai (Host header), enforce API key auth + log usage.
    Requests from stock.datap.ai or localhost bypass this (consumer frontend).
    """
    async def dispatch(self, request: StarletteRequest, call_next):
        host = request.headers.get("host", "")

        # Only enforce on api.datap.ai
        if not host.startswith("api.datap.ai"):
            return await call_next(request)

        # Skip health + docs + status endpoints
        path = request.url.path
        if path in ("/agent/health", "/status", "/api/docs", "/docs", "/openapi.json", "/redoc"):
            return await call_next(request)

        # Extract API key from header: Authorization: ApiKey {key}
        auth_header = request.headers.get("authorization", "")
        api_key = ""
        if auth_header.startswith("ApiKey "):
            api_key = auth_header[7:]
        elif auth_header.startswith("Bearer "):
            api_key = auth_header[7:]

        if not api_key:
            return StarletteJSONResponse(
                status_code=401,
                content={"ok": False, "error": {"code": "MISSING_API_KEY", "message": "API key required. Use header: Authorization: ApiKey YOUR_KEY"}},
            )

        client = _verify_b2b_api_key(api_key)
        if not client:
            return StarletteJSONResponse(
                status_code=401,
                content={"ok": False, "error": {"code": "INVALID_API_KEY", "message": "Invalid or inactive API key."}},
            )

        # Attach client info to request state for downstream use
        request.state.b2b_client = client

        # Execute request + measure time
        start = _time.time()
        response = await call_next(request)
        elapsed_ms = int((_time.time() - start) * 1000)

        # Log usage (non-blocking)
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "")
        _log_api_usage(client["client_id"], path, request.method, response.status_code, elapsed_ms, ip)

        return response


app.add_middleware(B2BApiMiddleware)

# ── Stock Chat co-pilot router (sealed module) ────────────────────────────────
try:
    from agents.stock_chat import router as _chat_router
    app.include_router(_chat_router, prefix="/agent")
    import logging as _lg; _lg.getLogger(__name__).info("stock_chat router registered")
except Exception as _e:
    import logging as _lg; _lg.getLogger(__name__).warning("stock_chat router not loaded: %s", _e)

# ── Auth ──────────────────────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)


def _check_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
) -> None:
    if not _API_KEY:
        return   # no auth configured — open
    if not credentials or credentials.credentials != _API_KEY:
        return JSONResponse(
            status_code=401,
            content=ApiResponse.failure(
                code="UNAUTHORIZED",
                message="Invalid or missing API key.",
            ).model_dump(),
        )


# ── LLM client singleton ──────────────────────────────────────────────────────

_llm_client = None


def _get_llm():
    """Return a cached RouterChatClient, or None if unavailable."""
    global _llm_client
    if _llm_client is not None:
        return _llm_client
    try:
        from agents.llm_client import RouterChatClient
        _llm_client = RouterChatClient()
        logger.info("[TinyFishAPI] LLM client initialised: mode=%s", _LLM_MODE)
    except Exception as exc:
        logger.warning("[TinyFishAPI] LLM client unavailable — heuristic-only mode: %s", exc)
        _llm_client = None
    return _llm_client


# ══════════════════════════════════════════════════════════════════════════════
# GET /agent/health
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/agent/health", dependencies=[Depends(_check_api_key)])
def health() -> dict:
    """Service health check. Returns contract version and capability flags."""
    llm = _get_llm()
    data = HealthData(
        service             = "datapai-streamlit",
        ag2_enabled         = True,
        paid_llm_enabled    = _LLM_MODE in ("paid", "hybrid"),
        private_llm_enabled = _LLM_MODE in ("local", "hybrid"),
        rag_enabled         = False,
        version             = "v1",
        contract_version    = "v1",
    )
    return ApiResponse.success(data.model_dump()).model_dump()


# ══════════════════════════════════════════════════════════════════════════════
# GET /status — Infrastructure health check
# ══════════════════════════════════════════════════════════════════════════════

import subprocess as _subprocess
from datetime import datetime as _dt, timezone as _tz

_STATUS_DBS = {
    "framework_db": {"port": 5433, "dbname": "datapai_auth_db"},
    "stock_db":     {"port": 5434, "dbname": "postgres"},
    "health_db":    {"port": 5435, "dbname": "postgres"},
    "trade_db":     {"port": 5436, "dbname": "postgres"},
}


def _check_db(name: str, port: int, dbname: str) -> dict:
    try:
        start = _time.time()
        conn = psycopg2.connect(
            host="localhost", port=port, dbname=dbname,
            user="postgres", password=_FRAMEWORK_DB["password"],
            connect_timeout=3,
        )
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return {"status": "up", "latency_ms": int((_time.time() - start) * 1000)}
    except Exception as e:
        return {"status": "down", "error": str(e)[:200]}


def _check_http(url: str, timeout: int = 5) -> dict:
    try:
        start = _time.time()
        resp = _http.get(url, timeout=timeout)
        latency_ms = int((_time.time() - start) * 1000)
        # 401 = service alive but auth required — that's fine
        if resp.status_code < 500:
            return {"status": "up", "latency_ms": latency_ms}
        return {"status": "degraded", "latency_ms": latency_ms, "http_status": resp.status_code}
    except Exception as e:
        return {"status": "down", "error": str(e)[:200]}


def _check_airflow() -> dict:
    try:
        start = _time.time()
        result = _subprocess.run(
            ["docker", "exec", "dbt_airflow-airflow-scheduler-1", "airflow", "jobs", "check"],
            capture_output=True, text=True, timeout=10,
        )
        latency_ms = int((_time.time() - start) * 1000)
        if result.returncode == 0:
            return {"status": "up", "latency_ms": latency_ms}
        return {"status": "degraded", "latency_ms": latency_ms, "detail": result.stderr[:200]}
    except Exception as e:
        return {"status": "down", "error": str(e)[:200]}


@app.get("/status")
def status_page():
    """Infrastructure health check — no API key required."""
    services = {}

    # Self
    services["stock_be"] = {"status": "up", "latency_ms": 0}

    # Databases
    for name, cfg in _STATUS_DBS.items():
        services[name] = _check_db(name, cfg["port"], cfg["dbname"])

    # auth-be
    services["auth_be"] = _check_http("http://localhost:8008/api/auth/verify")

    # Airflow scheduler
    services["airflow"] = _check_airflow()

    all_up = all(s["status"] == "up" for s in services.values())
    return {
        "ok": all_up,
        "ts": _dt.now(_tz.utc).isoformat(),
        "services": services,
    }


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/docs — Public B2B API documentation (no auth required)
# ══════════════════════════════════════════════════════════════════════════════

from pathlib import Path as _Path
from starlette.responses import HTMLResponse as _HTMLResponse

_DOCS_HTML_PATH = _Path(__file__).parent / "static" / "api_docs.html"


@app.get("/api/docs", response_class=_HTMLResponse, include_in_schema=False)
def api_docs_page():
    """Public B2B API documentation — no API key required."""
    return _HTMLResponse(content=_DOCS_HTML_PATH.read_text(), status_code=200)


# ══════════════════════════════════════════════════════════════════════════════
# POST /agent/detect-financial-signal
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/agent/detect-financial-signal", dependencies=[Depends(_check_api_key)])
def detect_financial_signal(req: DetectSignalRequest) -> dict:
    """
    Detect meaningful financial language changes.

    Runs all three signal agents, returns the highest-priority signal.
    """
    try:
        llm = _get_llm()
        result = classify_signals(
            old_text        = req.old_text,
            new_text        = req.new_text,
            changed_snippet = req.changed_snippet,
            llm_client      = llm,
        )

        data = {
            "signal_type":         result["signal_type"],
            "severity":            result["severity"],
            "confidence":          result["confidence"],
            "financial_relevance": result["financial_relevance"],
            "evidence_quotes":     result.get("evidence_quotes", []),
            "quality_flags":       result.get("quality_flags", []),
        }
        return ApiResponse.success(data).model_dump()

    except Exception as exc:
        logger.exception("[/agent/detect-financial-signal] Unexpected error")
        return ApiResponse.failure(
            code="DETECTION_ERROR",
            message="Financial signal detection failed. Please try again.",
        ).model_dump()


# ══════════════════════════════════════════════════════════════════════════════
# POST /agent/cross-validate-signal
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/agent/cross-validate-signal", dependencies=[Depends(_check_api_key)])
def cross_validate_signal(req: CrossValidateRequest) -> dict:
    """
    Verify a detected signal against exchange filings and public IR sources.
    """
    try:
        result = run_cross_validation_agent(
            ticker          = req.ticker,
            company_name    = req.company_name,
            signal_type     = req.signal_type.value,
            changed_snippet = req.changed_snippet,
            source_url      = req.source_url,
        )

        data = {
            "validation_status":     result["validation_status"],
            "validation_summary":    result["validation_summary"],
            "validation_evidence":   result.get("validation_evidence", []),
            "confidence_adjustment": result.get("confidence_adjustment", 0.0),
        }
        return ApiResponse.success(data).model_dump()

    except Exception as exc:
        logger.exception("[/agent/cross-validate-signal] Unexpected error")
        return ApiResponse.failure(
            code="VALIDATION_ERROR",
            message="Cross-validation could not be completed.",
        ).model_dump()


# ══════════════════════════════════════════════════════════════════════════════
# POST /agent/generate-signal-summary
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/agent/generate-signal-summary", dependencies=[Depends(_check_api_key)])
def generate_signal_summary(req: GenerateSummaryRequest) -> dict:
    """
    Generate an investor-friendly explanation of the detected signal.
    Returns what_changed / why_it_matters / evidence.
    """
    try:
        llm = _get_llm()

        # Build evidence block from request
        evidence = req.evidence_quotes

        # LLM-driven summary (falls back to rule-based if LLM is unavailable)
        from agents.tinyfish_signals.tinyfish_signal_pipeline import _generate_interpretation
        interpretation = _generate_interpretation(
            ticker             = req.ticker,
            company_name       = req.company_name,
            signal_type        = req.signal_type.value,
            severity           = req.severity.value,
            evidence_quotes    = evidence,
            validation_status  = req.validation_status.value,
            validation_summary = req.validation_summary,
            llm_client         = llm,
        )

        data = {
            "what_changed":    interpretation["what_changed"],
            "why_it_matters":  interpretation["why_it_matters"],
            "evidence":        evidence,
            "validation_result": req.validation_summary,
        }
        return ApiResponse.success(data).model_dump()

    except Exception as exc:
        logger.exception("[/agent/generate-signal-summary] Unexpected error")
        return ApiResponse.failure(
            code="SUMMARY_ERROR",
            message="Signal summary generation failed.",
        ).model_dump()


# ══════════════════════════════════════════════════════════════════════════════
# POST /agent/run-financial-signal-pipeline
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/agent/run-financial-signal-pipeline", dependencies=[Depends(_check_api_key)])
def run_financial_signal_pipeline(req: RunPipelineRequest) -> dict:
    """
    Run the complete financial signal pipeline end-to-end (v1.5):
      normalize → change-type classify → detect → investigate → cross-validate
      → classify → interpret → summarise.
    """
    try:
        llm    = _get_llm()
        result = run_tinyfish_signal_pipeline(
            ticker          = req.ticker,
            company_name    = req.company_name,
            source_url      = req.source_url,
            old_text        = req.old_text,
            new_text        = req.new_text,
            changed_snippet = req.changed_snippet,
            llm_client      = llm,
        )

        # Fire webhook if a real signal was detected
        signal_type = result.get("signal_type") or result.get("classification")
        if signal_type and signal_type != "NONE":
            _fire_webhooks("signal.detected", {
                "ticker": req.ticker,
                "company_name": req.company_name,
                "signal_type": signal_type,
                "source_url": req.source_url,
                "summary": result.get("summary", ""),
            })

        return ApiResponse.success(result).model_dump()

    except Exception as exc:
        logger.exception("[/agent/run-financial-signal-pipeline] Unexpected error")
        return ApiResponse.failure(
            code="PIPELINE_ERROR",
            message="Financial signal pipeline failed. Please try again.",
        ).model_dump()


# ══════════════════════════════════════════════════════════════════════════════
# POST /agent/classify-change-type  (v1.5 — Signal Quality Filter)
# ══════════════════════════════════════════════════════════════════════════════

class ClassifyChangeTypeRequest(BaseModel):
    old_text:        str
    new_text:        str
    changed_snippet: str = ""


@app.post("/agent/classify-change-type", dependencies=[Depends(_check_api_key)])
def classify_change_type_endpoint(req: ClassifyChangeTypeRequest) -> dict:
    """
    v1.5: Classify whether the text change is a meaningful content change,
    an archive-page reorder, or a layout-only structural change.

    Returns:
        change_type       : CONTENT_CHANGE | ARCHIVE_CHANGE | LAYOUT_CHANGE
        quality_score     : 0.0–1.0 (1.0 = high-quality content change)
        quality_flags     : explanatory flags
        confidence_multiplier : how much this reduces signal confidence
    """
    try:
        from agents.tinyfish_signals.tinyfish_signal_pipeline import normalize_text
        from agents.tinyfish_signals.change_type_classifier import get_confidence_multiplier

        old_clean = normalize_text(req.old_text)
        new_clean = normalize_text(req.new_text)

        change_type, quality_score, quality_flags = classify_change_type(
            old_clean, new_clean, req.changed_snippet
        )
        multiplier = get_confidence_multiplier(change_type, quality_score)

        data = {
            "change_type":            change_type,
            "quality_score":          quality_score,
            "quality_flags":          quality_flags,
            "confidence_multiplier":  multiplier,
        }
        return ApiResponse.success(data).model_dump()

    except Exception as exc:
        logger.exception("[/agent/classify-change-type] Unexpected error")
        return ApiResponse.failure(
            code="CHANGE_TYPE_ERROR",
            message="Change type classification failed.",
        ).model_dump()


# ══════════════════════════════════════════════════════════════════════════════
# POST /agent/investigate-signal  (v1.5 — Investigation Agent)
# ══════════════════════════════════════════════════════════════════════════════

class InvestigateSignalRequest(BaseModel):
    ticker:          str
    company_name:    str
    signal_type:     SignalType
    source_url:      str = ""
    changed_snippet: str = ""


@app.post("/agent/investigate-signal", dependencies=[Depends(_check_api_key)])
def investigate_signal_endpoint(req: InvestigateSignalRequest) -> dict:
    """
    v1.5 NEW: Investigate additional sources when a financial signal is detected.

    Checks:
      - company press releases page
      - exchange filings (ASX for AU, SEC for US)
      - investor relations page

    Returns corroborating evidence and an investigation summary.
    """
    try:
        llm = _get_llm()
        result = run_investigation_agent(
            ticker          = req.ticker,
            company_name    = req.company_name,
            signal_type     = req.signal_type.value,
            source_url      = req.source_url,
            changed_snippet = req.changed_snippet,
            llm_client      = llm,
        )

        data = {
            "investigation_results":  result.get("investigation_results", []),
            "sources_checked":        result.get("sources_checked", []),
            "investigation_summary":  result.get("investigation_summary", ""),
            "corroborating_count":    result.get("corroborating_count", 0),
            "contradicting_count":    result.get("contradicting_count", 0),
            "found_evidence":         result.get("found_evidence", False),
        }
        return ApiResponse.success(data).model_dump()

    except Exception as exc:
        logger.exception("[/agent/investigate-signal] Unexpected error")
        return ApiResponse.failure(
            code="INVESTIGATION_ERROR",
            message="Signal investigation could not be completed.",
        ).model_dump()


# ══════════════════════════════════════════════════════════════════════════════
# POST /agent/technical-signal  (Option B — Multi-Timeframe TA Signal)
# ══════════════════════════════════════════════════════════════════════════════

class TechnicalSignalRequest(BaseModel):
    ticker:   str
    suffix:   str = ""      # "" for US, ".AX" for ASX, ".L" for LSE
    exchange: str = "US"    # display label used in the prompt


@app.post("/agent/technical-signal", dependencies=[Depends(_check_api_key)])
def technical_signal_endpoint(req: TechnicalSignalRequest) -> dict:
    """
    Generate AI trading signal using LOCAL pre-computed data first (fast),
    falling back to Yahoo Finance only when DB data unavailable.

    Priority: screener_metrics DB (instant) → Yahoo Finance (slow fallback)
    """
    try:
        import time as _time
        from agents.technical_analysis import fetch_all_timeframes, generate_technical_signal

        _t0 = _time.time()
        _data_source = "database"
        indicators_by_tf = None
        db_daily = None

        # ── 1. Try LOCAL pre-computed data from screener_metrics (instant) ────
        try:
            ticker_db = f"{req.ticker}.AX" if req.suffix == ".AX" else req.ticker
            from agents.stock_chat.db import query as db_query
            rows = db_query(
                """SELECT ticker, latest_close, change_1d_pct, change_5d_pct,
                          change_1m_pct, change_3m_pct, rsi_14, macd_trend,
                          kdj_signal, sma_5, sma_10, sma_20, sma_50, sma_200,
                          bb_upper, bb_lower, bb_middle, volume_ratio,
                          avg_volume_20d, latest_volume, trade_date::text,
                          high_52w, pct_from_52w_high, volatility_20d
                   FROM datapai.screener_metrics WHERE ticker = %s LIMIT 1""",
                (ticker_db,),
            )
            if rows:
                r = rows[0]
                rsi = r.get("rsi_14")
                rsi_label = "OVERBOUGHT" if rsi and rsi >= 70 else "OVERSOLD" if rsi and rsi <= 30 else "NEUTRAL"
                macd_label = r.get("macd_trend", "NEUTRAL")
                # Determine trend from SMA alignment
                sma50 = r.get("sma_50")
                sma200 = r.get("sma_200")
                trend = "SIDEWAYS"
                if sma50 and sma200:
                    trend = "UPTREND" if sma50 > sma200 else "DOWNTREND"
                # Bollinger band position
                close = r.get("latest_close")
                bb_upper = r.get("bb_upper")
                bb_lower = r.get("bb_lower")
                bb_label = "MID BAND"
                if close and bb_upper and bb_lower:
                    bb_range = bb_upper - bb_lower
                    if bb_range > 0:
                        pct_b = (close - bb_lower) / bb_range
                        bb_label = "NEAR UPPER BAND" if pct_b > 0.8 else "NEAR LOWER BAND" if pct_b < 0.2 else "MID BAND"

                bb_middle = r.get("bb_middle")
                bb_pct = None
                if close and bb_upper and bb_lower and (bb_upper - bb_lower) > 0:
                    bb_pct = (close - bb_lower) / (bb_upper - bb_lower)

                db_daily = {
                    "current_price": close,
                    "change_pct": r.get("change_1d_pct"),
                    "rsi": rsi,
                    "rsi_label": rsi_label,
                    "trend": trend,
                    # MACD — DB has trend only; line/signal/hist unavailable
                    "macd_line": None, "macd_signal": None, "macd_hist": None,
                    "macd_label": macd_label,
                    # Volume — from screener_metrics
                    "volume": int(r.get("latest_volume") or 0),
                    "vol_ratio": r.get("volume_ratio"),
                    "vol_ratio_30": r.get("volume_ratio"),
                    "vol_ma_30": r.get("avg_volume_20d"),
                    # Optional indicators — set None so .get() works
                    "stoch_k": None, "stoch_d": None, "stoch_label": None,
                    "atr": None, "atr_pct": None,
                    "adx": None, "adx_label": None, "plus_di": None, "minus_di": None,
                    "obv_trend": None, "overall_signal": None, "signal_score": None,
                    "open": None, "high": None, "low": None, "prev_close": None,
                    # Bollinger Bands
                    "bb_upper": bb_upper, "bb_lower": bb_lower,
                    "bb_middle": bb_middle, "bb_pct": bb_pct, "bb_label": bb_label,
                    # SMAs (used as EMAs in display — close enough for daily)
                    "ema_9": r.get("sma_10"), "ema_21": r.get("sma_20"),
                    "ema_50": sma50, "ema_200": sma200,
                    "sma_5": r.get("sma_5"), "sma_10": r.get("sma_10"),
                    "sma_20": r.get("sma_20"), "sma_50": sma50, "sma_200": sma200,
                    "volume_ratio": r.get("volume_ratio"),
                    "kdj_signal": r.get("kdj_signal"),
                    "change_5d_pct": r.get("change_5d_pct"),
                    "change_1m_pct": r.get("change_1m_pct"),
                    "change_3m_pct": r.get("change_3m_pct"),
                    "high_52w": r.get("high_52w"),
                    "pct_from_52w_high": r.get("pct_from_52w_high"),
                    "volatility_20d": r.get("volatility_20d"),
                    "trade_date": r.get("trade_date"),
                }
                indicators_by_tf = {"1d": db_daily}
                logger.info("[technical-signal] Using LOCAL DB data for %s (%.1fms)", req.ticker, (_time.time()-_t0)*1000)
        except Exception as db_err:
            logger.warning("[technical-signal] DB lookup failed for %s: %s", req.ticker, db_err)

        # ── 2. Fall back to Yahoo Finance if DB has no data ───────────────────
        if indicators_by_tf is None or not any(v for v in indicators_by_tf.values()):
            _data_source = "yahoo" if req.suffix else "polygon"
            indicators_by_tf = fetch_all_timeframes(
                ticker=req.ticker, suffix=req.suffix, source=_data_source,
            )
            if _data_source == "polygon" and not any(v for v in indicators_by_tf.values()):
                _data_source = "yahoo"
                indicators_by_tf = fetch_all_timeframes(
                    ticker=req.ticker, suffix=req.suffix, source="yahoo",
                )
            logger.info("[technical-signal] Fell back to %s for %s (%.1fs)", _data_source, req.ticker, _time.time()-_t0)

        signal_md = generate_technical_signal(
            ticker=req.ticker,
            suffix=req.suffix,
            indicators_by_tf=indicators_by_tf,
            use_grounding=True,
        )
        logger.info("[technical-signal] Total time for %s: %.1fs (source=%s)", req.ticker, _time.time()-_t0, _data_source)

        daily = indicators_by_tf.get("1d") or {}
        data = {
            "signal_markdown":  signal_md,
            "current_price":    daily.get("current_price"),
            "change_pct":       daily.get("change_pct"),
            "rsi":              daily.get("rsi"),
            "rsi_label":        daily.get("rsi_label"),
            "trend":            daily.get("trend"),
            "macd_label":       daily.get("macd_label"),
            "bb_label":         daily.get("bb_label"),
            "indicators_by_tf": {
                tf: ind for tf, ind in indicators_by_tf.items() if ind is not None
            },
        }

        # ── Cache TA signal + live price into Postgres for stock chat context ──
        # This means the chat's get_postgres_context() will find fresh price data
        # without making a redundant Yahoo Finance call (user: "we already got data from yahoo")
        try:
            from agents.stock_chat.rag_retriever import upsert_ticker_context
            price_val  = daily.get("current_price")
            chg_val    = daily.get("change_pct")
            rsi_val    = daily.get("rsi")
            trend_val  = daily.get("trend", "")
            cache_text = f"[TA Signal — {req.ticker.upper()} | {req.exchange.upper()}]\n"
            # Today's OHLC — explicitly named so AI can answer "what is today's open/high/low/close"
            if daily.get("open") is not None:
                cache_text += f"Today's Open:  {daily['open']:.4f}\n"
            if daily.get("high") is not None:
                cache_text += f"Today's High:  {daily['high']:.4f}\n"
            if daily.get("low") is not None:
                cache_text += f"Today's Low:   {daily['low']:.4f}\n"
            if price_val is not None:
                cache_text += f"Today's Close: {price_val:.4f}"
                if chg_val is not None:
                    cache_text += f"  ({chg_val:+.2f}% vs prev close)"
                cache_text += "\n"
            if daily.get("prev_close") is not None:
                cache_text += f"Prev Close:    {daily['prev_close']:.4f}\n"
            if rsi_val:
                cache_text += f"RSI(14): {rsi_val:.1f} ({daily.get('rsi_label', '')})\n"
            if trend_val:
                cache_text += f"Trend: {trend_val}\n"
            if daily.get("macd_label"):
                cache_text += f"MACD: {daily.get('macd_label')}\n"
            if daily.get("bb_label"):
                cache_text += f"Bollinger: {daily.get('bb_label')}\n"
            # Append the full signal markdown (first 1500 chars)
            cache_text += "\n" + signal_md[:1500]
            upsert_ticker_context(
                ticker=req.ticker,
                context_type="ta_signal",
                content=cache_text,
                metadata={"source": _data_source, "exchange": req.exchange or req.suffix or "US"},
                ttl_hours=8,
            )
            logger.info("[technical-signal] Cached TA context for %s", req.ticker)
        except Exception as _cache_err:
            logger.warning("[technical-signal] ta_signal cache upsert skipped: %s", _cache_err)

        return ApiResponse.success(data).model_dump()

    except Exception as exc:
        logger.exception("[/agent/technical-signal] Unexpected error")
        return ApiResponse.failure(
            code="TA_SIGNAL_ERROR",
            message=f"Technical signal generation failed: {exc}",
        ).model_dump()


# ══════════════════════════════════════════════════════════════════════════════
# POST /agent/chart-analysis  (Option C — Gemini Vision Chart Analysis)
# ══════════════════════════════════════════════════════════════════════════════

class ChartAnalysisRequest(BaseModel):
    ticker:    str
    suffix:    str = ""      # "" for US, ".AX" for ASX
    timeframe: str = "1d"
    bars:      int = 120


@app.post("/agent/chart-analysis", dependencies=[Depends(_check_api_key)])
def chart_analysis_endpoint(req: ChartAnalysisRequest) -> dict:
    """
    Fetch OHLCV data, render a 3-panel technical chart (Price+BB+EMAs / RSI /
    MACD) as a dark-theme PNG, and run Gemini Vision to produce AI pattern
    recognition.

    Returns
    -------
    chart_b64  : base64-encoded PNG image (data:image/png;base64,...)
    analysis   : markdown pattern analysis from Gemini Vision
    indicators : daily snapshot (price, RSI, MACD, BB, EMAs, trend, volume)
    timeframe  : the timeframe used for the chart
    """
    try:
        import base64
        from agents.technical_analysis import fetch_ohlcv, calc_indicators
        from agents.chart_vision import render_chart, analyse_chart_with_gemini

        df = fetch_ohlcv(req.ticker, "1d", suffix=req.suffix, source="yahoo")
        if df is None:
            return ApiResponse.failure(
                code="NO_PRICE_DATA",
                message=(
                    f"Could not fetch price data for {req.ticker}{req.suffix}. "
                    "Verify the ticker symbol and exchange suffix."
                ),
            ).model_dump()

        indicators = calc_indicators(df)

        chart_bytes = render_chart(
            ticker=req.ticker,
            df=df,
            indicators=indicators,
            suffix=req.suffix,
            timeframe=req.timeframe,
            bars=req.bars,
        )

        if chart_bytes is None:
            return ApiResponse.failure(
                code="CHART_RENDER_ERROR",
                message="Chart rendering failed — insufficient price history (< 10 bars).",
            ).model_dump()

        chart_b64 = base64.b64encode(chart_bytes).decode()

        analysis = analyse_chart_with_gemini(
            ticker=req.ticker,
            chart_bytes=chart_bytes,
            indicators=indicators,
            suffix=req.suffix,
            timeframe=req.timeframe,
        )

        data = {
            "chart_b64":  chart_b64,
            "analysis":   analysis,
            "indicators": indicators,
            "timeframe":  req.timeframe,
        }
        return ApiResponse.success(data).model_dump()

    except Exception as exc:
        logger.exception("[/agent/chart-analysis] Unexpected error")
        return ApiResponse.failure(
            code="CHART_ANALYSIS_ERROR",
            message=f"Chart analysis failed: {exc}",
        ).model_dump()


# ══════════════════════════════════════════════════════════════════════════════
# POST /agent/asx-trading-signal  (ASX Announcement + Price Combined Signal)
# ══════════════════════════════════════════════════════════════════════════════

class AsxTradingSignalRequest(BaseModel):
    ticker:            str
    announcement:      dict   # { ticker, headline, doc_type, market_sensitive, document_date }
    announcement_text: str    # full text from the IR page / announcement body
    use_grounding:     bool = True


@app.post("/agent/asx-trading-signal", dependencies=[Depends(_check_api_key)])
def asx_trading_signal_endpoint(req: AsxTradingSignalRequest) -> dict:
    """
    Generate a full ASX trading signal combining announcement content with
    live multi-timeframe technical indicators fetched for ticker.AX.

    Two-LLM chain:
    1. Gemini (primary, with optional Google Search grounding for real-time news)
    2. GPT-4o compliance reviewer (arithmetic + disclaimer gate)

    Output: STRONG BUY / BUY / HOLD/NEUTRAL / SELL / STRONG SELL / NOT RELATED
    Includes per-timeframe entry/target/stop-loss table in AUD.

    Returns
    -------
    signal_markdown : full structured markdown trading signal
    current_price   : latest daily close in AUD
    trend           : UPTREND | DOWNTREND | SIDEWAYS
    rsi             : daily RSI(14)
    rsi_label       : OVERBOUGHT | NEUTRAL | OVERSOLD
    """
    try:
        from agents.technical_analysis import fetch_all_timeframes
        from agents.asx_trading_signal import generate_trading_signal

        indicators_by_tf = fetch_all_timeframes(
            ticker=req.ticker,
            suffix=".AX",
            source="yahoo",
        )

        signal_md = generate_trading_signal(
            announcement=req.announcement,
            pdf_text=req.announcement_text,
            indicators_by_tf=indicators_by_tf,
            use_grounding=req.use_grounding,
        )

        daily = indicators_by_tf.get("1d") or {}
        data = {
            "signal_markdown": signal_md,
            "current_price":   daily.get("current_price"),
            "trend":           daily.get("trend"),
            "rsi":             daily.get("rsi"),
            "rsi_label":       daily.get("rsi_label"),
        }
        return ApiResponse.success(data).model_dump()

    except Exception as exc:
        logger.exception("[/agent/asx-trading-signal] Unexpected error")
        return ApiResponse.failure(
            code="ASX_SIGNAL_ERROR",
            message=f"ASX trading signal generation failed: {exc}",
        ).model_dump()


# =============================================================================
# Fundamental Analysis endpoints
# =============================================================================

# Lazy-initialised Google LLM client for grounding calls
_google_llm_client = None

def _get_google_llm():
    global _google_llm_client
    if _google_llm_client is not None:
        return _google_llm_client
    try:
        from agents.llm_client import GoogleChatClient
        _google_llm_client = GoogleChatClient()
    except Exception as exc:
        logger.warning("GoogleChatClient unavailable: %s", exc)
    return _google_llm_client


@app.post("/agent/run-fundamental-pipeline")
async def run_fundamental_pipeline_endpoint(req: dict):
    """
    Run the full 10-step fundamental analysis pipeline for a single ticker.

    Request body
    ------------
    {
      "ticker":    "AAPL",
      "exchange":  "US",
      "dry_run":   false       (optional)
    }

    Returns FundamentalResult wrapped in ApiResponse.
    """
    try:
        from agents.fundamental.contracts import FundamentalPipelineRequest
        from agents.fundamental.fundamental_pipeline import run_fundamental_pipeline

        parsed = FundamentalPipelineRequest(**req)
        result = run_fundamental_pipeline(
            ticker=parsed.ticker,
            exchange=parsed.exchange,
            dry_run=parsed.dry_run,
            llm=_get_llm(),
            google_llm=_get_google_llm(),
        )
        return ApiResponse.success(result.model_dump()).model_dump()

    except Exception as exc:
        logger.exception("[/agent/run-fundamental-pipeline] Unexpected error")
        return ApiResponse.failure(
            code="FUNDAMENTAL_PIPELINE_ERROR",
            message=f"Fundamental pipeline failed: {exc}",
        ).model_dump()


@app.get("/agent/fundamental-snapshot")
async def get_fundamental_snapshot(ticker: str, exchange: str):
    """
    Read the latest fundamental snapshot for a ticker from the DB.

    Query params: ?ticker=AAPL&exchange=US
    Returns FundamentalResult fields wrapped in ApiResponse.
    """
    try:
        from scripts.lib.fundamental_helpers import get_fundamental_snapshot

        snap = get_fundamental_snapshot(ticker=ticker, exchange=exchange)
        if snap is None:
            return ApiResponse.failure(
                code="NOT_FOUND",
                message=f"No fundamental snapshot found for {ticker}/{exchange}",
            ).model_dump()
        # Convert non-serialisable types
        for k, v in snap.items():
            if hasattr(v, "isoformat"):
                snap[k] = v.isoformat()
        return ApiResponse.success(snap).model_dump()

    except Exception as exc:
        logger.exception("[/agent/fundamental-snapshot] Unexpected error")
        return ApiResponse.failure(
            code="FUNDAMENTAL_SNAPSHOT_ERROR",
            message=f"Snapshot read failed: {exc}",
        ).model_dump()


@app.get("/agent/fundamental-screener")
async def fundamental_screener(
    exchange: str,
    signal: str = None,
    sector: str = None,
    min_score: float = None,
    max_tech_risk: str = None,
    limit: int = 50,
):
    """
    Screener — return tickers matching fundamental criteria.

    Query params:
      exchange       US or ASX  (required)
      signal         STRONG_BUY | BUY | NEUTRAL | SELL | STRONG_SELL
      sector         e.g. Technology
      min_score      e.g. 0.2
      max_tech_risk  LOW | MEDIUM | HIGH
      limit          max rows (default 50)
    """
    try:
        from scripts.lib.fundamental_helpers import screener_query

        rows = screener_query(
            exchange=exchange,
            signal=signal,
            sector=sector,
            min_score=min_score,
            max_tech_risk=max_tech_risk,
            limit=min(limit, 200),
        )
        # Serialise datetimes
        for row in rows:
            for k, v in row.items():
                if hasattr(v, "isoformat"):
                    row[k] = v.isoformat()
        return ApiResponse.success({"items": rows, "count": len(rows)}).model_dump()

    except Exception as exc:
        logger.exception("[/agent/fundamental-screener] Unexpected error")
        return ApiResponse.failure(
            code="FUNDAMENTAL_SCREENER_ERROR",
            message=f"Screener failed: {exc}",
        ).model_dump()


# ══════════════════════════════════════════════════════════════════════════════
# GET /agent/index-overview  — Compact summary of all global market indexes
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/agent/index-overview")
async def index_overview(region: str = None):
    """Return compact summary of all 16 global market indexes with TA data."""
    try:
        from scripts.lib.db_helpers import get_conn
        sql = """
            SELECT sm.ticker, tu.company_name as name, tu.region,
                   sm.latest_close, sm.change_1d_pct, sm.change_5d_pct,
                   sm.change_1m_pct, sm.change_3m_pct, sm.change_6m_pct, sm.change_1y_pct,
                   sm.rsi_14, sm.macd_trend, sm.sma_50, sm.sma_200,
                   sm.golden_cross, sm.death_cross,
                   sm.high_52w, sm.low_52w, sm.pct_from_52w_high,
                   sm.trade_date
            FROM datapai.screener_metrics sm
            JOIN datapai.ticker_universe tu ON tu.ticker = sm.ticker AND tu.exchange = sm.exchange
            WHERE sm.exchange = 'INDEX'
        """
        params = []
        if region:
            sql += " AND tu.region = %s"
            params.append(region.upper())
        sql += " ORDER BY tu.region, tu.company_name"

        with get_conn() as conn:
            import psycopg2.extras
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]

        return {"ok": True, "data": rows, "total": len(rows)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# GET /agent/technical-screener  — TA-based screener from screener_metrics
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/agent/technical-screener")
async def technical_screener(
    exchange: str = "US",
    sort_by: str = "change_1d_pct",
    sort_dir: str = "desc",
    # Price filters
    min_price: float = None,
    max_price: float = None,
    # Change filters
    min_change_1d: float = None,
    max_change_1d: float = None,
    # RSI filter
    min_rsi: float = None,
    max_rsi: float = None,
    # MACD trend
    macd_trend: str = None,     # BULLISH or BEARISH
    # KDJ signal
    kdj_signal: str = None,     # OVERBOUGHT, OVERSOLD, NEUTRAL
    # MA cross
    golden_cross: bool = None,
    death_cross: bool = None,
    # Volume
    min_volume_ratio: float = None,
    # Volatility
    min_volatility: float = None,
    max_volatility: float = None,
    # 52-week
    near_52w_high: float = None,  # e.g. 5 = within 5% of 52w high
    near_52w_low: float = None,   # e.g. 10 = within 10% of 52w low
    # Pagination
    limit: int = 50,
    offset: int = 0,
):
    """
    Technical screener — query pre-computed screener_metrics table (8,500+ tickers).
    All TA indicators available: SMA, RSI, MACD, KDJ, BB, Pivot Points, OBV, volume.
    """
    try:
        from scripts.lib.db_helpers import get_conn

        conditions = ["exchange = %s"]
        params: list = [exchange.upper()]

        # Default quality filters (skip for INDEX — indexes don't have real volume)
        ex = exchange.upper()
        if ex != "INDEX":
            conditions.append("latest_volume IS NOT NULL")
            conditions.append("avg_volume_20d IS NOT NULL AND avg_volume_20d >= 5000")
            if ex == "ASX":
                if min_price is None:
                    min_price = 0.20
                conditions.append("avg_volume_20d >= 10000")
        conditions.append("trade_date::date >= CURRENT_DATE - INTERVAL '5 days'")

        if min_price is not None:
            conditions.append("latest_close >= %s"); params.append(min_price)
        if max_price is not None:
            conditions.append("latest_close <= %s"); params.append(max_price)
        if min_change_1d is not None:
            conditions.append("change_1d_pct >= %s"); params.append(min_change_1d)
        if max_change_1d is not None:
            conditions.append("change_1d_pct <= %s"); params.append(max_change_1d)
        if min_rsi is not None:
            conditions.append("rsi_14 >= %s"); params.append(min_rsi)
        if max_rsi is not None:
            conditions.append("rsi_14 <= %s"); params.append(max_rsi)
        if macd_trend:
            conditions.append("macd_trend = %s"); params.append(macd_trend.upper())
        if kdj_signal:
            conditions.append("kdj_signal = %s"); params.append(kdj_signal.upper())
        if golden_cross is True:
            conditions.append("golden_cross = TRUE")
        if death_cross is True:
            conditions.append("death_cross = TRUE")
        if min_volume_ratio is not None:
            conditions.append("volume_ratio >= %s"); params.append(min_volume_ratio)
        if min_volatility is not None:
            conditions.append("volatility_20d >= %s"); params.append(min_volatility)
        if max_volatility is not None:
            conditions.append("volatility_20d <= %s"); params.append(max_volatility)
        if near_52w_high is not None:
            conditions.append("pct_from_52w_high >= %s"); params.append(-near_52w_high)
        if near_52w_low is not None:
            conditions.append("pct_from_52w_low <= %s"); params.append(near_52w_low)

        SORTABLE = {
            "ticker", "latest_close", "latest_volume", "trade_date",
            "change_1d_pct", "change_5d_pct", "change_1m_pct", "change_3m_pct",
            "change_6m_pct", "change_1y_pct",
            "rsi_14", "macd_histogram", "kdj_k", "bb_pct_b",
            "volume_ratio", "volatility_20d",
            "pct_from_52w_high", "pct_from_52w_low",
            "sma_50", "sma_200", "price_vs_sma50_pct", "price_vs_sma200_pct",
        }
        sort_col = sort_by if sort_by in SORTABLE else "change_1d_pct"
        direction = "ASC" if sort_dir.lower() == "asc" else "DESC"

        where = " AND ".join(conditions)
        safe_limit = min(int(limit), 500)

        sql = f"""
            SELECT ticker, exchange, latest_close, latest_volume, trade_date,
                   change_1d_pct, change_5d_pct, change_1m_pct, change_3m_pct,
                   change_6m_pct, change_1y_pct,
                   high_52w, low_52w, pct_from_52w_high, pct_from_52w_low,
                   sma_5, sma_10, sma_20, sma_30, sma_50, sma_200,
                   price_vs_sma5_pct, price_vs_sma10_pct, price_vs_sma20_pct,
                   price_vs_sma50_pct, price_vs_sma200_pct,
                   golden_cross, death_cross,
                   rsi_14, macd_line, macd_signal, macd_histogram, macd_trend,
                   kdj_k, kdj_d, kdj_j, kdj_signal,
                   bb_upper, bb_lower, bb_pct_b, bb_width,
                   pivot_pp, pivot_r1, pivot_r2, pivot_s1, pivot_s2,
                   obv_trend, avg_volume_5d, avg_volume_10d, avg_volume_20d,
                   volume_ratio, volatility_20d, computed_at
            FROM datapai.screener_metrics
            WHERE {where}
            ORDER BY {sort_col} {direction} NULLS LAST
            LIMIT %s OFFSET %s
        """
        params.extend([safe_limit, int(offset)])

        # Also get total count for pagination
        count_sql = f"SELECT COUNT(*) FROM datapai.screener_metrics WHERE {where}"
        count_params = params[:-2]  # exclude limit/offset

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(count_sql, count_params)
                total = cur.fetchone()[0]

                cur.execute(sql, params)
                cols = [desc[0] for desc in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]

                # ── Enrich with Change Intelligence + Fundamental data ──
                tickers = [r["ticker"] for r in rows]
                if tickers:
                    # CI: website change alerts
                    ci_sql = """
                        SELECT DISTINCT ON (s.ticker)
                               s.ticker, a.alert_score, a.agent_severity,
                               a.agent_signal_type, a.agent_confidence,
                               a.change_type, a.financial_relevance_score,
                               LEFT(a.agent_what_changed, 120) AS what_changed
                        FROM datapai.analyses a
                        JOIN datapai.snapshots s ON a.snapshot_new_id = s.id
                        WHERE a.change_type = 'CONTENT_CHANGE'
                          AND s.ticker = ANY(%s)
                        ORDER BY s.ticker, a.alert_score DESC NULLS LAST
                    """
                    cur.execute(ci_sql, [tickers])
                    ci_rows = cur.fetchall()
                    logger.info("[screener] CI enrichment: %d tickers → %d matches", len(tickers), len(ci_rows))
                    ci_map = {}
                    for r in ci_rows:
                        ci_map[r[0]] = {
                            "ci_alert_score": r[1], "ci_severity": r[2],
                            "ci_signal_type": r[3], "ci_confidence": r[4],
                            "ci_change_type": r[5], "ci_relevance": r[6],
                            "ci_what_changed": r[7],
                        }

                    # FA: fundamental snapshot
                    # Note: use %%s-safe string — psycopg2 interprets % in '.AX'
                    ax_suffix = ".AX"
                    fa_sql = """
                        SELECT DISTINCT ON (REPLACE(ticker, %s, ''))
                               REPLACE(ticker, %s, '') AS ticker,
                               fundamental_signal, fundamental_score,
                               valuation_score, quality_score, growth_score,
                               analyst_consensus, analyst_upside_pct,
                               sector, next_earnings_date
                        FROM datapai.fundamental_snapshot
                        WHERE REPLACE(ticker, %s, '') = ANY(%s)
                        ORDER BY REPLACE(ticker, %s, ''), computed_at DESC NULLS LAST
                    """
                    cur.execute(fa_sql, [ax_suffix, ax_suffix, ax_suffix, tickers, ax_suffix])
                    fa_rows = cur.fetchall()
                    logger.info("[screener] FA enrichment: %d matches", len(fa_rows))
                    fa_map = {}
                    for r in fa_rows:
                        fa_map[r[0]] = {
                            "fa_signal": r[1], "fa_score": r[2],
                            "fa_valuation": r[3], "fa_quality": r[4],
                            "fa_growth": r[5], "fa_analyst": r[6],
                            "fa_upside_pct": r[7], "fa_sector": r[8],
                            "fa_earnings_date": r[9],
                        }

                    # MFS: multi-factor signals (precomputed TA signals)
                    mfs_sql = """
                        SELECT ticker, signal_days, score_days, conf_days,
                               signal_weeks, score_weeks, conf_weeks,
                               signal_months, score_months, conf_months,
                               signal_quarter, score_quarter, conf_quarter,
                               quality_tier, fund_modifier_avg
                        FROM datapai.multi_factor_signals
                        WHERE ticker = ANY(%s)
                    """
                    cur.execute(mfs_sql, [tickers])
                    mfs_rows = cur.fetchall()
                    mfs_cols = [desc[0] for desc in cur.description]
                    mfs_map = {}
                    for r in mfs_rows:
                        rd = dict(zip(mfs_cols, r))
                        mfs_map[rd["ticker"]] = {
                            "mfs_signal_days": rd["signal_days"],
                            "mfs_score_days": rd["score_days"],
                            "mfs_conf_days": rd["conf_days"],
                            "mfs_signal_weeks": rd["signal_weeks"],
                            "mfs_score_weeks": rd["score_weeks"],
                            "mfs_conf_weeks": rd["conf_weeks"],
                            "mfs_signal_months": rd["signal_months"],
                            "mfs_score_months": rd["score_months"],
                            "mfs_conf_months": rd["conf_months"],
                            "mfs_signal_quarter": rd["signal_quarter"],
                            "mfs_score_quarter": rd["score_quarter"],
                            "mfs_conf_quarter": rd["conf_quarter"],
                            "mfs_quality_tier": rd["quality_tier"],
                            "mfs_fund_modifier": rd["fund_modifier_avg"],
                        }
                    logger.info("[screener] MFS enrichment: %d matches", len(mfs_rows))

                    # FL: fundamental lite (PE, margins, quality for 552 tickers)
                    fl_sql = """
                        SELECT ticker, quality_tier, pe_ratio, forward_pe,
                               pb_ratio, ps_ratio, ev_ebitda,
                               gross_margin, operating_margin, net_margin,
                               roe, roa, revenue_yoy, earnings_yoy,
                               debt_to_equity, current_ratio,
                               analyst_target, analyst_rating, num_analysts,
                               is_profitable, is_growing, is_healthy,
                               market_cap, sector, dividend_yield, beta
                        FROM datapai.fundamental_lite
                        WHERE ticker = ANY(%s)
                    """
                    cur.execute(fl_sql, [tickers])
                    fl_rows = cur.fetchall()
                    fl_cols = [desc[0] for desc in cur.description]
                    fl_map = {}
                    for r in fl_rows:
                        rd = dict(zip(fl_cols, r))
                        fl_map[rd["ticker"]] = {
                            "fl_quality_tier": rd["quality_tier"],
                            "fl_pe": rd["pe_ratio"], "fl_fwd_pe": rd["forward_pe"],
                            "fl_pb": rd["pb_ratio"], "fl_ps": rd["ps_ratio"],
                            "fl_ev_ebitda": rd["ev_ebitda"],
                            "fl_gross_margin": rd["gross_margin"],
                            "fl_op_margin": rd["operating_margin"],
                            "fl_net_margin": rd["net_margin"],
                            "fl_roe": rd["roe"], "fl_roa": rd["roa"],
                            "fl_rev_yoy": rd["revenue_yoy"],
                            "fl_earn_yoy": rd["earnings_yoy"],
                            "fl_de_ratio": rd["debt_to_equity"],
                            "fl_current_ratio": rd["current_ratio"],
                            "fl_analyst_target": rd["analyst_target"],
                            "fl_analyst_rating": rd["analyst_rating"],
                            "fl_num_analysts": rd["num_analysts"],
                            "fl_profitable": rd["is_profitable"],
                            "fl_growing": rd["is_growing"],
                            "fl_healthy": rd["is_healthy"],
                            "fl_market_cap": rd["market_cap"],
                            "fl_sector": rd["sector"],
                            "fl_div_yield": rd["dividend_yield"],
                            "fl_beta": rd["beta"],
                        }
                    logger.info("[screener] FL enrichment: %d matches", len(fl_rows))

                    # ME: material events (news alerts, last 7 days)
                    me_sql = """
                        SELECT DISTINCT ON (ticker)
                               ticker, event_type, severity, sentiment,
                               headline, source_name, published_at
                        FROM datapai.material_events
                        WHERE ticker = ANY(%s)
                          AND published_at > NOW() - INTERVAL '7 days'
                        ORDER BY ticker, published_at DESC
                    """
                    cur.execute(me_sql, [tickers])
                    me_rows = cur.fetchall()
                    me_cols = [desc[0] for desc in cur.description]
                    me_map = {}
                    for r in me_rows:
                        rd = dict(zip(me_cols, r))
                        me_map[rd["ticker"]] = {
                            "me_event_type": rd["event_type"],
                            "me_severity": rd["severity"],
                            "me_sentiment": rd["sentiment"],
                            "me_headline": rd["headline"],
                            "me_source": rd["source_name"],
                            "me_published": rd["published_at"],
                        }
                    logger.info("[screener] ME enrichment: %d matches", len(me_rows))

                    # ── Compute DataPAI composite score ──
                    def _datapai_score(mfs, fl, ci, me):
                        """Combine TA + FA + CI + News into 0-100 score."""
                        score = 50.0  # neutral baseline
                        has_fa = fl.get("fl_quality_tier") is not None
                        has_ci = ci.get("ci_alert_score") is not None
                        has_me = me.get("me_severity") is not None

                        # ── TA component (±25 pts) from multi-factor signals ──
                        ta_pts = 0
                        for tf in ["months", "quarter"]:
                            sig = mfs.get(f"mfs_signal_{tf}")
                            if sig == "BUY": ta_pts += 12.5
                            elif sig == "SELL": ta_pts -= 12.5
                        score += ta_pts

                        # ── FA component (±20 pts) ──
                        if has_fa:
                            tier = fl.get("fl_quality_tier", "")
                            tier_pts = {"A": 15, "B": 8, "C": 0, "D": -10}.get(tier, 0)
                            # Bonus for profitable + growing
                            if fl.get("fl_profitable"): tier_pts += 3
                            if fl.get("fl_growing"): tier_pts += 2
                            score += tier_pts

                        # ── CI component (±15 pts) — website change intelligence ──
                        if has_ci:
                            alert = ci.get("ci_alert_score") or 0
                            severity = (ci.get("ci_severity") or "").upper()
                            sig_type = (ci.get("ci_signal_type") or "").upper()
                            if severity in ("CRITICAL", "HIGH"):
                                ci_pts = 15 if "POSITIVE" in sig_type or "BULLISH" in sig_type else -15
                            elif severity == "MEDIUM":
                                ci_pts = 8 if "POSITIVE" in sig_type or "BULLISH" in sig_type else -8
                            else:
                                ci_pts = 0
                            score += ci_pts

                        # ── News component (±10 pts) ──
                        if has_me:
                            sent = (me.get("me_sentiment") or "").upper()
                            sev = (me.get("me_severity") or "").upper()
                            if sev == "CRITICAL":
                                score += 10 if "POSITIVE" in sent else -10
                            elif sev == "HIGH":
                                score += 6 if "POSITIVE" in sent else -6

                        return max(0, min(100, round(score)))

                    # Merge all enrichments + compute composite score
                    for row in rows:
                        t = row["ticker"]
                        ci = ci_map.get(t, {})
                        fa = fa_map.get(t, {})
                        mfs = mfs_map.get(t, {})
                        fl = fl_map.get(t, {})
                        me = me_map.get(t, {})

                        # CI fields
                        row.update({
                            "ci_alert_score": ci.get("ci_alert_score"),
                            "ci_severity": ci.get("ci_severity"),
                            "ci_signal_type": ci.get("ci_signal_type"),
                            "ci_confidence": ci.get("ci_confidence"),
                            "ci_change_type": ci.get("ci_change_type"),
                            "ci_relevance": ci.get("ci_relevance"),
                            "ci_what_changed": ci.get("ci_what_changed"),
                        })
                        # FA snapshot fields
                        row.update({
                            "fa_signal": fa.get("fa_signal"),
                            "fa_score": fa.get("fa_score"),
                            "fa_valuation": fa.get("fa_valuation"),
                            "fa_quality": fa.get("fa_quality"),
                            "fa_growth": fa.get("fa_growth"),
                            "fa_analyst": fa.get("fa_analyst"),
                            "fa_upside_pct": fa.get("fa_upside_pct"),
                            "fa_sector": fa.get("fa_sector"),
                            "fa_earnings_date": fa.get("fa_earnings_date"),
                        })
                        # Multi-factor signal fields
                        row.update({
                            "mfs_signal_days": mfs.get("mfs_signal_days"),
                            "mfs_score_days": mfs.get("mfs_score_days"),
                            "mfs_signal_weeks": mfs.get("mfs_signal_weeks"),
                            "mfs_score_weeks": mfs.get("mfs_score_weeks"),
                            "mfs_signal_months": mfs.get("mfs_signal_months"),
                            "mfs_score_months": mfs.get("mfs_score_months"),
                            "mfs_signal_quarter": mfs.get("mfs_signal_quarter"),
                            "mfs_score_quarter": mfs.get("mfs_score_quarter"),
                            "mfs_quality_tier": mfs.get("mfs_quality_tier"),
                        })
                        # Fundamental lite fields
                        row.update({
                            "fl_quality_tier": fl.get("fl_quality_tier"),
                            "fl_pe": fl.get("fl_pe"),
                            "fl_fwd_pe": fl.get("fl_fwd_pe"),
                            "fl_gross_margin": fl.get("fl_gross_margin"),
                            "fl_op_margin": fl.get("fl_op_margin"),
                            "fl_roe": fl.get("fl_roe"),
                            "fl_rev_yoy": fl.get("fl_rev_yoy"),
                            "fl_earn_yoy": fl.get("fl_earn_yoy"),
                            "fl_profitable": fl.get("fl_profitable"),
                            "fl_growing": fl.get("fl_growing"),
                            "fl_healthy": fl.get("fl_healthy"),
                            "fl_analyst_rating": fl.get("fl_analyst_rating"),
                            "fl_analyst_target": fl.get("fl_analyst_target"),
                            "fl_market_cap": fl.get("fl_market_cap"),
                            "fl_sector": fl.get("fl_sector"),
                            "fl_div_yield": fl.get("fl_div_yield"),
                            "fl_beta": fl.get("fl_beta"),
                        })
                        # News event fields
                        row.update({
                            "me_event_type": me.get("me_event_type"),
                            "me_severity": me.get("me_severity"),
                            "me_sentiment": me.get("me_sentiment"),
                            "me_headline": me.get("me_headline"),
                            "me_source": me.get("me_source"),
                            "me_published": me.get("me_published"),
                        })
                        # Composite DataPAI Score
                        row["datapai_score"] = _datapai_score(mfs, fl, ci, me)

        # Serialise
        for row in rows:
            for k, v in row.items():
                if hasattr(v, "isoformat"):
                    row[k] = v.isoformat()
                elif isinstance(v, float) and (v != v):  # NaN
                    row[k] = None

        return ApiResponse.success({
            "items": rows,
            "count": len(rows),
            "total": total,
            "offset": int(offset),
            "limit": safe_limit,
        }).model_dump()

    except Exception as exc:
        logger.exception("[/agent/technical-screener] Unexpected error")
        return ApiResponse.failure(
            code="TECHNICAL_SCREENER_ERROR",
            message=f"Technical screener failed: {exc}",
        ).model_dump()


# ══════════════════════════════════════════════════════════════════════════════
# POST /agent/market-intel-synthesis
# ══════════════════════════════════════════════════════════════════════════════

_MARKET_INTEL_SYSTEM_PROMPT = """You are a Senior Equity Research Analyst with 20+ years of experience at a \
top-tier global investment bank (Goldman Sachs Equity Research, Morgan Stanley Research, JP Morgan Cazenove, \
UBS Global Research). You have covered US and international equities across multiple market cycles: the 2000 \
dot-com bust, the 2008 Global Financial Crisis, the 2011 European debt crisis, the 2018 Fed tightening \
tantrum, the 2020 COVID crash, the 2022 rate shock, and the 2023–2025 AI mega-cap bull market.

Portfolio managers at the world's largest hedge funds (Bridgewater, Two Sigma, Renaissance), sovereign wealth \
funds (GIC, ADIA, Norges Bank), and pension funds rely on your insights to allocate capital. Your research \
notes move stocks. Your sector calls are quoted on Bloomberg and CNBC.

Your analytical framework covers FIVE LAYERS simultaneously:

1. MACRO LAYER
   — Federal Reserve / RBA / ECB monetary policy trajectory (rate cuts priced vs delivered)
   — Real interest rates and duration risk (how rising rates reprice equities via DCF)
   — Inflation dynamics (sticky vs transitory), credit spreads (HY vs IG), yield curve shape (inversion = risk-off)
   — US dollar (DXY) strength (crushes EM revenues, benefits US exporters)
   — Commodity shocks: oil (cost-push inflation → margin compression), gold (risk sentiment barometer)
   — Global growth divergence: US vs China vs Europe vs EM
   — Liquidity: Fed balance sheet, repo markets, bank lending standards (SLOOS)

2. GEOPOLITICAL LAYER
   — US-China trade and technology decoupling (tariffs, entity lists, export controls on chips/AI)
   — Taiwan strait risk (semiconductor supply chain existential threat)
   — Middle East energy supply disruption (Strait of Hormuz, Red Sea shipping lanes)
   — Russia-Ukraine: commodity exports (wheat, fertilisers, natural gas, palladium)
   — Sanctions regimes and counter-sanctions risk
   — Deglobalisation: reshoring, friend-shoring, supply chain duplication costs
   — Regulatory nationalism: EU Digital Markets Act, EU AI Act, US antitrust vs Big Tech

3. SECTOR DYNAMICS LAYER
   — Where in the industry cycle (early recovery, mid expansion, late cycle, contraction)?
   — Disruption themes: AI/LLMs replacing SaaS spend, EVs disrupting ICE auto, cloud cannibalising on-prem
   — Competitive intensity: new entrants, pricing power erosion, commoditisation risk
   — Regulatory environment: antitrust (FAANG), capital requirements (banks), carbon pricing (energy/materials)
   — Capital cycle: is the sector overinvesting (capex boom → supply glut → margin compression)?
   — M&A activity: consolidation, roll-up strategies, activist pressure for breakups

4. COMPANY-SPECIFIC LAYER
   — Earnings quality: GAAP vs non-GAAP divergence, one-time items, aggressive revenue recognition
   — Revenue visibility: recurring revenue %, backlog, contract duration, customer concentration
   — Margin trajectory: gross margin expansion/compression drivers, operating leverage
   — FCF conversion and capital allocation: buybacks, dividends, M&A, debt reduction
   — Balance sheet: net debt/EBITDA, refinancing risk, off-balance-sheet obligations
   — Management quality: track record of guidance delivery, capital allocation discipline, insider ownership
   — Product pipeline: TAM expansion, new markets, pricing power sustainability

5. MARKET SENTIMENT LAYER
   — Institutional positioning: crowded longs/shorts (risk of positioning unwind)
   — Short interest: elevated short ratio = potential short squeeze OR ongoing conviction short
   — Options flow: put/call skew, unusual options activity, implied volatility vs realised
   — Momentum factors: trend following vs mean reversion regime
   — Valuation vs sector peers: premium/discount and whether justified by fundamentals

WRITING STYLE: Investment bank research — structured, direct, evidence-based. Use specific numbers. Identify \
conviction levels (HIGH/MEDIUM/LOW). Name the risk explicitly. Do not hedge every sentence. When you see a \
sector-level disruption theme (e.g., "AI is commoditising cloud storage", "Chinese EV brands entering \
Australian market", "DeepSeek destroying NVIDIA's pricing power narrative"), flag it prominently with \
DISRUPTION ALERT. These are the alpha-generating insights.

OUTPUT FORMAT: Return a JSON object with exactly these fields:
{
  "intel_markdown": "<full markdown analyst note — see structure below>",
  "overall_stance": "BULLISH" | "NEUTRAL" | "BEARISH",
  "macro_themes": ["<3-5 bullet strings>"],
  "sector_themes": ["<3-5 bullet strings>"],
  "ticker_catalysts": ["<3-5 bullet strings>"],
  "black_swans": ["<2-4 bullet strings>"]
}

The intel_markdown MUST follow this exact structure:
## 🎯 Investment Stance
[One sentence: BULLISH/NEUTRAL/BEARISH on {ticker} + single strongest reason. This is your headline call.]

## 🌍 Macro Environment — Impact on {ticker}
[How do current Fed policy, rates, geopolitical events, and global growth affect THIS specific stock?
Be specific: "Rising 10yr yields compress P/E multiples for high-growth names like {ticker}"
or "Dollar strength headwind — {ticker} generates X% of revenue outside the US". 2-4 paragraphs.]

## 🏭 Sector Dynamics & Disruption Risks
[Industry tailwinds and headwinds. Call out any structural disruption theme explicitly.
If AI is disrupting this sector, say so and quantify the risk. If there's a regulatory wave coming, name it.
If a new competitor has entered with pricing 50% lower, flag it. 2-4 paragraphs.]

## 📰 Recent Catalysts & News Flow
[Specific, date-tagged news items from the crawled data. Earnings beats/misses, analyst actions with
price targets and firm names, management changes, product launches, regulatory news.
Use bullet points. Be factual — do not fabricate. If no specific data, say "No significant recent catalysts found."]

## ⚠️ Black Swans & Tail Risks
[2-4 specific, named risks that most investors are NOT pricing in. Think creatively.
Example format: "🦢 AI model commoditisation: if GPT-5 / Gemini Ultra 2 / DeepSeek R2 compete on price,
{ticker}'s Azure AI premium could compress 40% within 12 months — not in consensus models."
These should be surprising, specific, and credible.]

## 🐂 Bull Case vs 🐻 Bear Case
**Bull** (price 12m target: implied upside):
• [3 specific, quantifiable catalysts]

**Bear** (downside scenario):
• [3 specific, quantifiable risks]

## 🔍 What to Watch — Next 30–90 Days
[3-5 specific events/data points to monitor with approximate dates if known:
earnings date, Fed meeting dates, regulatory deadlines, product launches, key competitor announcements]

---
*Market Intelligence generated using real-time data from Yahoo Finance via TinyFish browser automation.
Analysis synthesised by AI. Data as of {date}. Educational only — not financial advice.*
"""

def _section(label: str, text: str, max_chars: int = 3000) -> str:
    """Return a labelled source block, or empty string if no content."""
    text = (text or "").strip()
    if not text:
        return ""
    return f"\n---\n## {label}\n{text[:max_chars]}\n"


@app.post("/agent/market-intel-synthesis")
async def market_intel_synthesis(req: dict):
    """
    Synthesise TinyFish-crawled multi-source intelligence into a senior
    investment bank analyst narrative.

    Request body (v2 — 7 sources)
    ------------
    {
      "ticker":                  "AAPL",
      "exchange":                "US",
      "sector":                  "Technology",
      "reuters_text":            "...",   (Reuters Finance — real-time macro + news)
      "ticker_news_text":        "...",   (Yahoo Finance ticker news)
      "sector_news_text":        "...",   (Yahoo Finance sector page)
      "project_syndicate_text":  "...",   (Project Syndicate — top economists' views)
      "cfr_text":                "...",   (CFR — geopolitical risk analysis)
      "imf_text":                "...",   (IMF News — global growth/policy)
      "wef_text":                "...",   (WEF Agenda — mega-trends/disruption)
      "sources_used":            ["Reuters Finance", "Yahoo Finance (AAPL)", ...]
    }

    Returns
    -------
    {
      "intel_markdown":    "<full senior analyst note>",
      "overall_stance":    "BULLISH" | "NEUTRAL" | "BEARISH",
      "macro_themes":      ["..."],
      "sector_themes":     ["..."],
      "ticker_catalysts":  ["..."],
      "black_swans":       ["..."]
    }
    """
    import json as _json
    from datetime import date as _date

    try:
        ticker    = str(req.get("ticker",   "")).upper().strip()
        exchange  = str(req.get("exchange", "US")).upper().strip()
        sector    = str(req.get("sector",   "")).strip()

        if not ticker:
            return ApiResponse.failure(
                code="INVALID_REQUEST",
                message="ticker is required",
            ).model_dump()

        # ── Source section labels (mirrors marketIntelSources.ts sectionLabel) ──
        # These map source id → section heading shown in the LLM prompt.
        # Update here if you add new sources to the TypeScript config.
        SOURCE_LABELS = {
            "reuters":           "📰 REAL-TIME NEWS — Reuters Finance",
            "yahoo_ticker":      f"📊 STOCK NEWS — {ticker} (Yahoo Finance)",
            "yahoo_sector":      f"🏭 SECTOR — {sector if sector else 'Unknown'} (Yahoo Finance)",
            "cnbc_markets":      "📺 REAL-TIME NEWS — CNBC Markets",
            "marketwatch":       "📈 REAL-TIME NEWS — MarketWatch (WSJ)",
            "project_syndicate": "💡 MACRO VIEWS — Project Syndicate (Roubini, El-Erian, Summers et al.)",
            "cfr":               "🌍 GEOPOLITICAL RISK — Council on Foreign Relations (CFR)",
            "imf":               "🏦 GLOBAL POLICY — International Monetary Fund (IMF)",
            "wef":               "🔭 MEGA-TRENDS — World Economic Forum (WEF Agenda)",
            "bis":               "🏛️ SYSTEMIC RISK — Bank for International Settlements (BIS)",
            "fed_reserve":       "🏦 US MONETARY POLICY — Federal Reserve (FOMC)",
            "ft_markets":        "📋 PREMIUM NEWS — Financial Times Markets",
            "economist":         "📘 ANALYSIS — The Economist Finance & Economics",
            "brookings":         "🏛️ POLICY RESEARCH — Brookings Institution",
        }

        sources_used    = list(req.get("sources_used", []) or [])
        sector_display  = sector if sector else "Unknown"
        today_str       = _date.today().isoformat()
        profile_context = str(req.get("profile_context", "") or "").strip()

        # ── Build multi-source prompt blocks dynamically ──────────────────────
        # Accept ANY key in req that matches a known source id; build blocks for
        # non-empty ones. Unknown source ids fall back to a generic label.
        known_source_ids = set(SOURCE_LABELS.keys())
        reserved_keys    = {"ticker", "exchange", "sector", "sources_used", "profile_context"}
        blocks = []
        for key, label in SOURCE_LABELS.items():
            text = str(req.get(key, "") or "").strip()
            if text:
                blocks.append(_section(label, text))
        # Also accept any extra source keys not in the predefined list
        for key, val in req.items():
            if key in reserved_keys or key in known_source_ids:
                continue
            text = str(val or "").strip()
            if text and len(text) > 100:
                blocks.append(_section(f"📄 {key.replace('_', ' ').title()}", text))

        source_blocks = "".join(blocks) or "(No live data available — use your training knowledge as baseline)"

        n_sources     = len(sources_used)
        sources_str   = ", ".join(sources_used) if sources_used else "Multiple financial sources"

        # Append investor profile tailoring instruction if available
        profile_instruction = ""
        if profile_context:
            profile_instruction = f"""
---
## 👤 INVESTOR PROFILE — Frame your analysis for this specific investor:
{profile_context}

CRITICAL: Your analysis, bull/bear case, risk warnings, and recommendations MUST be tailored to this investor's \
profile. Emphasise the dimensions most relevant to their strategy and risk tolerance. Use their preferred response \
style. If their profile says BRIEF, keep sections concise. If DETAILED, expand with full reasoning.
---"""

        user_prompt   = f"""Provide a comprehensive senior equity research analyst note on **{ticker}** \
(Exchange: {exchange}, Sector: {sector_display}).

You have access to REAL-TIME intelligence crawled TODAY ({today_str}) from \
{n_sources} authoritative source{"s" if n_sources != 1 else ""}:
**{sources_str}**

This multi-source mosaic is exactly what differentiates Goldman Sachs equity research from retail analysis:
real-time news + top economists' views + geopolitical risk + IMF/BIS/WEF macro context all synthesised together.

Synthesise ALL available data across ALL layers (macro, geopolitical, sector, company, sentiment).
{source_blocks}{profile_instruction}
---
Write the COMPLETE analyst note now in the exact JSON format from your system prompt.
Today's date: {today_str}.
IMPORTANT: If a source section is missing, note "Data unavailable from [source]" and fill the gap \
using your training knowledge — clearly label it "Prior knowledge (unverified):" so the reader knows.
"""

        # System prompt with ticker substituted in the output format section
        system_prompt = _MARKET_INTEL_SYSTEM_PROMPT.replace("{ticker}", ticker)

        # Call LLM (RouterChatClient respects LLM_MODE env var)
        llm = _get_llm()
        if llm is None:
            return ApiResponse.failure(
                code="LLM_UNAVAILABLE",
                message="LLM client not initialised — check LLM_MODE and API keys.",
            ).model_dump()

        resp = llm.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.3,
        )

        raw = resp.get("content", "") if isinstance(resp, dict) else str(resp)

        # Strip markdown code fences if present, then parse JSON
        clean = raw.strip()
        if clean.startswith("```"):
            # Remove opening fence (```json or ```)
            clean = clean.split("\n", 1)[-1]
        if clean.endswith("```"):
            clean = clean[:-3].rstrip()
        try:
            parsed = _json.loads(clean)
        except (_json.JSONDecodeError, ValueError):
            # Fallback: treat entire output as intel_markdown
            logger.warning("[market-intel-synthesis] LLM did not return valid JSON — using raw output")
            parsed = {
                "intel_markdown":   raw,
                "overall_stance":   None,
                "macro_themes":     [],
                "sector_themes":    [],
                "ticker_catalysts": [],
                "black_swans":      [],
            }

        data = {
            "intel_markdown":   str(parsed.get("intel_markdown",   "")),
            "overall_stance":   parsed.get("overall_stance"),
            "macro_themes":     list(parsed.get("macro_themes",     []) or []),
            "sector_themes":    list(parsed.get("sector_themes",    []) or []),
            "ticker_catalysts": list(parsed.get("ticker_catalysts", []) or []),
            "black_swans":      list(parsed.get("black_swans",      []) or []),
        }
        return ApiResponse.success(data).model_dump()

    except Exception as exc:
        logger.exception("[/agent/market-intel-synthesis] Unexpected error")
        return ApiResponse.failure(
            code="MARKET_INTEL_ERROR",
            message=f"Market intel synthesis failed: {exc}",
        ).model_dump()


@app.post("/agent/fundamental-compare")
async def fundamental_compare(req: dict):
    """
    Side-by-side fundamental comparison of 2–5 tickers.

    Request body
    ------------
    {
      "tickers":  ["AAPL", "MSFT", "NVDA"],
      "exchange": "US"
    }

    Reads from DB snapshots; runs live pipeline for any ticker not yet in DB.
    """
    try:
        from agents.fundamental.contracts import FundamentalCompareRequest
        from scripts.lib.fundamental_helpers import get_fundamental_snapshot
        from agents.fundamental.fundamental_pipeline import run_fundamental_pipeline

        parsed = FundamentalCompareRequest(**req)
        results = []

        for ticker in parsed.tickers:
            snap = get_fundamental_snapshot(ticker=ticker, exchange=parsed.exchange)
            if snap:
                for k, v in snap.items():
                    if hasattr(v, "isoformat"):
                        snap[k] = v.isoformat()
                results.append(snap)
            else:
                # Run live pipeline (no DB write) to fill the gap
                logger.info("fundamental-compare: running live pipeline for %s", ticker)
                result = run_fundamental_pipeline(
                    ticker=ticker,
                    exchange=parsed.exchange,
                    dry_run=True,
                    llm=_get_llm(),
                    google_llm=_get_google_llm(),
                )
                results.append(result.model_dump())

        return ApiResponse.success({"tickers": parsed.tickers, "results": results}).model_dump()

    except Exception as exc:
        logger.exception("[/agent/fundamental-compare] Unexpected error")
        return ApiResponse.failure(
            code="FUNDAMENTAL_COMPARE_ERROR",
            message=f"Fundamental compare failed: {exc}",
        ).model_dump()


# ─────────────────────────────────────────────────────────────────────────────
# AG2 Stock Signal Synthesis — multi-agent debate
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/agent/synthesize-signals")
async def synthesize_signals_endpoint(req: dict):
    """
    Run AG2 multi-agent debate to synthesize conflicting TA/FA/MA signals.

    Request body:
        { "ticker": "BHP", "exchange": "ASX" }

    Optional:
        { "ticker": "BHP", "exchange": "ASX", "model": "gpt-4o" }

    Response:
        Unified recommendation with direction, confidence, thesis,
        bull/bear arguments, key risk, and debate transcript.
    """
    try:
        from agents.stock_synthesis import run_synthesis, AgentSignalInput
        from agents.stock_synthesis.signal_gatherer import gather_signals

        ticker = req.get("ticker", "").strip().upper()
        exchange = req.get("exchange", "US").strip().upper()
        model = req.get("model")

        if not ticker:
            return ApiResponse.failure(
                code="MISSING_TICKER",
                message="ticker is required",
            ).model_dump()

        # Gather signals from DB
        signals = await gather_signals(ticker, exchange)
        if not signals:
            return ApiResponse.failure(
                code="NO_SIGNALS",
                message=f"No TA/FA/MA signals found for {ticker}/{exchange}. "
                        "Run TA and FA pipelines first.",
            ).model_dump()

        # Run AG2 synthesis
        result = await run_synthesis(ticker, exchange, signals, model=model)

        return ApiResponse.success(result.model_dump(mode="json")).model_dump()

    except Exception as exc:
        logger.exception("[/agent/synthesize-signals] Unexpected error")
        return ApiResponse.failure(
            code="SYNTHESIS_ERROR",
            message=f"Signal synthesis failed: {exc}",
        ).model_dump()


@app.post("/agent/synthesize-signals-batch")
async def synthesize_signals_batch_endpoint(req: dict):
    """
    Run synthesis for multiple tickers.

    Request body:
        { "exchange": "ASX", "tickers": ["BHP", "CBA", "CSL"] }

    If tickers is empty, processes all tickers with available signals.
    """
    try:
        from agents.stock_synthesis import run_synthesis
        from agents.stock_synthesis.signal_gatherer import gather_signals
        from agents.stock_chat.db import query as db_query

        exchange = req.get("exchange", "US").strip().upper()
        tickers = req.get("tickers", [])
        model = req.get("model")

        # If no tickers specified, get all that have TA signals
        if not tickers:
            rows = await db_query(
                """SELECT DISTINCT ticker FROM datapai.ta_indicators
                   WHERE exchange = $1 AND timeframe = '1d'
                   ORDER BY ticker""",
                [exchange],
            )
            tickers = [r["ticker"] for r in rows]

        results = []
        for ticker in tickers:
            try:
                signals = await gather_signals(ticker, exchange)
                if signals:
                    result = await run_synthesis(ticker, exchange, signals, model=model)
                    results.append(result.model_dump(mode="json"))
                else:
                    results.append({
                        "ticker": ticker, "exchange": exchange,
                        "direction": "HOLD", "confidence": 0.0,
                        "thesis": "No signals available",
                    })
            except Exception as exc:
                logger.warning("Synthesis failed for %s: %s", ticker, str(exc)[:120])
                results.append({
                    "ticker": ticker, "exchange": exchange,
                    "direction": "HOLD", "confidence": 0.0,
                    "thesis": f"Synthesis error: {str(exc)[:100]}",
                })

        return ApiResponse.success({
            "exchange": exchange,
            "count": len(results),
            "results": results,
        }).model_dump()

    except Exception as exc:
        logger.exception("[/agent/synthesize-signals-batch] Unexpected error")
        return ApiResponse.failure(
            code="SYNTHESIS_BATCH_ERROR",
            message=f"Batch synthesis failed: {exc}",
        ).model_dump()


# ─────────────────────────────────────────────────────────────────────────────
# Investment Committee v2 — Debate Consensus, Risk, Exit
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/agent/run-debate-consensus")
async def run_debate_consensus_endpoint(req: dict):
    """
    Run the Investment Committee structured debate (v2).

    Three-phase debate: Draft → Challenge → Vote with regime-aware weighting,
    quantitative risk gating, and exit strategy levels.

    Request body:
        { "ticker": "BHP", "exchange": "ASX" }

    Response:
        StockSynthesis + ConsensusReport (consensus_score, conflict_level,
        risk_score, exit_strategy, debate_phases)
    """
    try:
        from agents.stock_synthesis.debate_consensus import run_debate_consensus
        from agents.stock_synthesis.signal_gatherer import gather_signals
        from agents.stock_synthesis.contracts import ConsensusReport
        from agents.stock_synthesis.db import upsert_consensus_report
        from agents.fundamental.macro_agent import (
            classify_regime,
            fetch_macro_context,
            get_regime_weights,
        )

        ticker = req.get("ticker", "").strip().upper()
        exchange = req.get("exchange", "US").strip().upper()
        sector = req.get("sector")

        if not ticker:
            return ApiResponse.failure(
                code="MISSING_TICKER",
                message="ticker is required",
            ).model_dump()

        # Gather signals
        signals = await gather_signals(ticker, exchange)
        if not signals:
            return ApiResponse.failure(
                code="NO_SIGNALS",
                message=f"No signals found for {ticker}/{exchange}. Run TA/FA pipelines first.",
            ).model_dump()

        # Get macro regime
        macro = fetch_macro_context(exchange, sector or "General")
        regime = classify_regime(macro)
        weights = get_regime_weights(regime)

        # Run debate
        result = await run_debate_consensus(
            ticker=ticker,
            exchange=exchange,
            signals=signals,
            regime_weights=weights,
            macro_view=regime.value,
            sector=sector,
        )

        # Build and persist ConsensusReport
        debate_text = "\n".join(
            f"[{dp.agent}] {dp.argument}" for dp in result.synthesis.debate_points
        )
        report = ConsensusReport(
            ticker=ticker,
            exchange=exchange,
            macro_view=regime.value,
            consensus_score=result.consensus.consensus_score,
            conflict_level=result.consensus.conflict_level,
            consensus_direction=result.synthesis.direction.value,
            agent_scores=result.consensus.agent_scores,
            regime_weights=result.consensus.regime_weights,
            risk_score=result.risk.risk_score,
            risk_flags=result.risk.risk_flags,
            position_size=result.risk.position_size.value,
            exit_strategy=result.exit_strategy,
            debate_transcript=debate_text,
            debate_phases=result.debate_phases,
        )
        await upsert_consensus_report(report)

        return ApiResponse.success({
            "synthesis": result.synthesis.model_dump(mode="json"),
            "consensus": {
                "consensus_score": result.consensus.consensus_score,
                "conflict_level": result.consensus.conflict_level,
                "macro_view": result.consensus.macro_view,
                "agent_scores": result.consensus.agent_scores,
                "dominant_side": result.consensus.dominant_side,
            },
            "risk": {
                "risk_score": result.risk.risk_score,
                "risk_flags": result.risk.risk_flags,
                "position_size": result.risk.position_size.value,
                "max_loss_estimate_pct": result.risk.max_loss_estimate_pct,
                "risk_breakdown": result.risk.risk_breakdown,
            },
            "exit_strategy": result.exit_strategy,
        }).model_dump()

    except Exception as exc:
        logger.exception("[/agent/run-debate-consensus] Unexpected error")
        return ApiResponse.failure(
            code="DEBATE_CONSENSUS_ERROR",
            message=f"Debate consensus failed: {exc}",
        ).model_dump()


@app.get("/agent/consensus-report/{ticker}")
async def get_consensus_report_endpoint(ticker: str, exchange: str = "US"):
    """
    Get the most recent consensus report for a ticker.

    Query params: exchange (default: US)
    """
    try:
        from agents.stock_synthesis.db import get_latest_consensus_report

        result = await get_latest_consensus_report(ticker.upper(), exchange.upper())
        if not result:
            return ApiResponse.failure(
                code="NOT_FOUND",
                message=f"No consensus report found for {ticker}/{exchange}",
            ).model_dump()

        return ApiResponse.success(result).model_dump()

    except Exception as exc:
        logger.exception("[/agent/consensus-report] Unexpected error")
        return ApiResponse.failure(
            code="CONSENSUS_REPORT_ERROR",
            message=f"Failed to fetch consensus report: {exc}",
        ).model_dump()


@app.post("/agent/assess-risk")
async def assess_risk_endpoint(req: dict):
    """
    Standalone quantitative risk assessment.

    Request body:
        { "ticker": "BHP", "exchange": "ASX" }

    Response:
        risk_score, risk_flags, position_size, max_loss_estimate, breakdown
    """
    try:
        from agents.stock_synthesis.risk_agent import assess_risk
        from agents.stock_synthesis.signal_gatherer import gather_signals
        from agents.fundamental.macro_agent import (
            classify_regime,
            fetch_macro_context,
        )

        ticker = req.get("ticker", "").strip().upper()
        exchange = req.get("exchange", "US").strip().upper()
        sector = req.get("sector")

        if not ticker:
            return ApiResponse.failure(code="MISSING_TICKER", message="ticker is required").model_dump()

        # Get TA data from DB
        signals = await gather_signals(ticker, exchange)
        ta_data = {}
        fa_data = {}
        news_data = {}
        for s in (signals or []):
            if s.source.value == "TECHNICAL":
                ta_data = s.data
            elif s.source.value == "FUNDAMENTAL":
                fa_data = s.data
            elif s.source.value == "NEWS":
                news_data = s.data

        macro = fetch_macro_context(exchange, sector or "General")
        regime = classify_regime(macro)

        risk = assess_risk(
            ta_data=ta_data,
            fa_data=fa_data,
            regime=regime.value,
            news_data=news_data,
            sector=sector,
        )

        return ApiResponse.success({
            "ticker": ticker,
            "exchange": exchange,
            "risk_score": risk.risk_score,
            "risk_flags": risk.risk_flags,
            "position_size": risk.position_size.value,
            "max_loss_estimate_pct": risk.max_loss_estimate_pct,
            "risk_breakdown": risk.risk_breakdown,
            "regime": regime.value,
        }).model_dump()

    except Exception as exc:
        logger.exception("[/agent/assess-risk] Unexpected error")
        return ApiResponse.failure(
            code="RISK_ASSESSMENT_ERROR",
            message=f"Risk assessment failed: {exc}",
        ).model_dump()


@app.post("/agent/exit-signal")
async def exit_signal_endpoint(req: dict):
    """
    Check exit conditions for an open position.

    Request body:
        {
            "ticker": "BHP",
            "exchange": "ASX",
            "entry_price": 45.50,
            "current_price": 48.20,
            "highest_since_entry": 49.10,
            "days_held": 12,
            "timeframe": "weeks"
        }

    Response:
        action, reason, urgency, current_pnl_pct, trailing_drawdown_pct
    """
    try:
        from agents.stock_synthesis.exit_agent import check_exit

        entry_price = req.get("entry_price", 0)
        current_price = req.get("current_price", 0)
        highest = req.get("highest_since_entry", current_price)
        days_held = req.get("days_held", 0)
        timeframe = req.get("timeframe", "weeks")

        if entry_price <= 0 or current_price <= 0:
            return ApiResponse.failure(
                code="INVALID_PRICES",
                message="entry_price and current_price must be positive",
            ).model_dump()

        ta_data = req.get("ta_data", {})
        news_data = req.get("news_data")
        fa_score = req.get("fa_score")

        signal = check_exit(
            entry_price=entry_price,
            current_price=current_price,
            highest_since_entry=highest,
            days_held=days_held,
            timeframe=timeframe,
            ta_data=ta_data,
            news_data=news_data,
            fa_score=fa_score,
        )

        return ApiResponse.success({
            "ticker": req.get("ticker", ""),
            "action": signal.action.value,
            "reason": signal.reason,
            "urgency": signal.urgency.value,
            "current_pnl_pct": signal.current_pnl_pct,
            "trailing_drawdown_pct": signal.trailing_drawdown_pct,
        }).model_dump()

    except Exception as exc:
        logger.exception("[/agent/exit-signal] Unexpected error")
        return ApiResponse.failure(
            code="EXIT_SIGNAL_ERROR",
            message=f"Exit signal check failed: {exc}",
        ).model_dump()


# ─────────────────────────────────────────────────────────────────────────────
# Watchlist AI Overview — multi-agent watchlist analysis
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/agent/watchlist-overview")
async def watchlist_overview_endpoint(user_id: str = "", fast: bool = False):
    """
    Generate AI-powered watchlist overview: sector grouping, diversity score,
    risk clusters, opportunity ranking, and actionable recommendations.
    """
    try:
        from agents.stock_synthesis.watchlist_overview import (
            gather_watchlist_data,
            generate_watchlist_overview,
        )

        stocks = gather_watchlist_data(user_id=user_id if user_id else None)
        if not stocks:
            return ApiResponse.failure(
                code="EMPTY_WATCHLIST",
                message="No stocks in watchlist. Add stocks first.",
            ).model_dump()

        overview = await generate_watchlist_overview(skip_llm=fast, stocks=stocks)
        return ApiResponse.success(overview.model_dump(mode="json")).model_dump()

    except Exception as exc:
        logger.exception("[/agent/watchlist-overview] Unexpected error")
        return ApiResponse.failure(
            code="WATCHLIST_OVERVIEW_ERROR",
            message=f"Watchlist overview failed: {exc}",
        ).model_dump()


# ─────────────────────────────────────────────────────────────────────────────
# Breaking News / Material Event Agent
# ─────────────────────────────────────────────────────────────────────────────

class CheckNewsRequest(BaseModel):
    ticker: str
    exchange: str = "US"
    persist: bool = True


@app.post("/agent/check-news", dependencies=[Depends(_check_api_key)])
def check_news_endpoint(req: CheckNewsRequest) -> dict:
    """
    Check breaking news for a ticker — fetch from Google News RSS, Finnhub,
    and SEC EDGAR 8-K filings, then classify material events using LLM.

    Returns classified material events with severity, sentiment, and summaries.
    """
    try:
        from agents.news_agent import run_news_agent

        ticker = req.ticker.strip().upper()
        if not ticker:
            return ApiResponse.failure(
                code="MISSING_TICKER",
                message="ticker is required",
            ).model_dump()

        result = run_news_agent(
            ticker=ticker,
            exchange=req.exchange.strip().upper(),
            persist=req.persist,
        )

        data = {
            "ticker": result.ticker,
            "exchange": result.exchange,
            "news_items_fetched": result.news_items_fetched,
            "material_events": [e.model_dump(mode="json") for e in result.material_events],
            "has_critical_event": result.has_critical_event,
            "highest_severity": result.highest_severity.value,
            "overall_sentiment": result.overall_sentiment.value,
            "fetched_at": result.fetched_at.isoformat(),
        }
        return ApiResponse.success(data).model_dump()

    except Exception as exc:
        logger.exception("[/agent/check-news] Unexpected error")
        return ApiResponse.failure(
            code="NEWS_CHECK_ERROR",
            message=f"News check failed: {exc}",
        ).model_dump()


@app.get("/agent/material-events/{ticker}", dependencies=[Depends(_check_api_key)])
def get_material_events_endpoint(ticker: str, exchange: str = None, hours: int = 72) -> dict:
    """
    Get stored material events for a ticker from the database.
    Query params: ?exchange=US&hours=72
    """
    try:
        from agents.news_agent.db import get_latest_events

        ticker = ticker.strip().upper()
        if not ticker:
            return ApiResponse.failure(
                code="MISSING_TICKER",
                message="ticker is required",
            ).model_dump()

        events = get_latest_events(
            ticker=ticker,
            exchange=exchange.strip().upper() if exchange else None,
            hours=min(hours, 720),  # cap at 30 days
        )

        return ApiResponse.success({
            "ticker": ticker,
            "events": events,
            "count": len(events),
        }).model_dump()

    except Exception as exc:
        logger.exception("[/agent/material-events] Unexpected error")
        return ApiResponse.failure(
            code="MATERIAL_EVENTS_ERROR",
            message=f"Material events retrieval failed: {exc}",
        ).model_dump()


# ══════════════════════════════════════════════════════════════════════════════
# i18n — DB-driven internationalisation
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/i18n")
async def get_i18n(lang: str = "en", category: str | None = None):
    """Return all UI labels for a language.  Cached 5 min.

    Query params:
      ?lang=vi            — language code (default: en)
      ?category=nav       — optional: filter by category
    """
    try:
        from agents.i18n import get_translations

        labels = get_translations(lang, category=category)
        return {"lang": lang, "labels": labels, "count": len(labels)}
    except Exception as exc:
        logger.exception("[/api/i18n] error")
        return ApiResponse.failure(
            code="I18N_ERROR",
            message=f"Failed to load translations: {exc}",
        ).model_dump()


@app.get("/api/i18n/languages")
async def get_i18n_languages():
    """Return supported languages list (active only)."""
    try:
        from agents.i18n import get_supported_languages

        languages = get_supported_languages()
        return {"languages": languages}
    except Exception as exc:
        logger.exception("[/api/i18n/languages] error")
        return ApiResponse.failure(
            code="I18N_LANGUAGES_ERROR",
            message=f"Failed to load languages: {exc}",
        ).model_dump()


# ── Welcome Email ────────────────────────────────────────────────────────────

class WelcomeEmailRequest(BaseModel):
    email: str
    badge_number: int
    lang: str = "en"


@app.post("/api/send-welcome-email")
async def send_welcome_email_endpoint(body: WelcomeEmailRequest):
    """Trigger welcome email for new Early Supporter. Fire-and-forget from frontend."""
    try:
        import sys, os

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        from send_welcome_email import send_welcome_email

        success = send_welcome_email(body.email, body.badge_number, body.lang)
        return {"ok": True, "sent": success}
    except Exception as exc:
        logger.exception("[/api/send-welcome-email] error")
        return {"ok": False, "error": str(exc)}


# ── Screenshot Import ────────────────────────────────────────────────────────

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB


@app.post("/agent/extract-screenshot")
async def extract_screenshot(file: UploadFile = File(...)):
    """Extract stock holdings from a broker app screenshot using Gemini Vision."""
    try:
        if file.content_type not in ALLOWED_IMAGE_TYPES:
            return {"ok": False, "error": f"Unsupported file type: {file.content_type}. Use PNG, JPG, or WEBP."}

        image_bytes = await file.read()
        if len(image_bytes) > MAX_IMAGE_SIZE:
            return {"ok": False, "error": f"File too large ({len(image_bytes) // 1024 // 1024}MB). Max 10MB."}

        from agents.screenshot_extract import extract_holdings_from_screenshot
        holdings = extract_holdings_from_screenshot(image_bytes, file.content_type)

        return {"ok": True, "data": {"holdings": holdings}}
    except Exception as exc:
        logger.exception("[/agent/extract-screenshot] error")
        return {"ok": False, "error": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# GET /agent/intraday-bars  —  On-demand intraday bars (AKShare for China, yfinance for others)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/agent/intraday-bars")
def get_intraday_bars(ticker: str, exchange: str = "US"):
    """
    Fetch intraday 5-min bars for a single ticker.
    China A-shares (SSE/SZSE): uses AKShare (includes actual close bar).
    Other markets: uses yfinance.
    Caches result into per-market intraday table.
    """
    try:
        ticker = ticker.upper().strip()
        exchange = exchange.upper().strip()

        if exchange in ("SSE", "SZSE"):
            from scripts.lib.sina_helpers import fetch_intraday_sina
            raw = fetch_intraday_sina(ticker, exchange, period="5", bars=50)
            bars = [{"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}
                    for ts, o, h, l, c, v in raw]

            # Cache into intraday table
            if raw:
                from scripts.lib.db_helpers import upsert_intraday_rows
                db_rows = [(ticker, ts, o, h, l, c, v, exchange, "sina") for ts, o, h, l, c, v in raw]
                upsert_intraday_rows(db_rows, batch_label="on_demand", exchange=exchange)

        else:
            import yfinance as yf
            suffix_map = {"ASX": ".AX", "HKEX": ".HK", "HOSE": ".VN", "SET": ".BK",
                          "KLSE": ".KL", "IDX": ".JK", "LSE": ".L"}
            yf_sym = f"{ticker}{suffix_map.get(exchange, '')}"
            df = yf.download(yf_sym, period="1d", interval="5m", progress=False, auto_adjust=True)
            if df is None or df.empty:
                return {"ok": True, "data": []}

            bars = []
            for ts_idx, row in df.iterrows():
                c = row.get("Close")
                if c is None or (hasattr(c, '__iter__') and len(c) == 0):
                    continue
                c_val = float(c.iloc[0]) if hasattr(c, 'iloc') else float(c)
                if c_val == 0:
                    continue
                o_val = float(row.get("Open", c_val).iloc[0]) if hasattr(row.get("Open", c_val), 'iloc') else float(row.get("Open", c_val))
                h_val = float(row.get("High", c_val).iloc[0]) if hasattr(row.get("High", c_val), 'iloc') else float(row.get("High", c_val))
                l_val = float(row.get("Low", c_val).iloc[0]) if hasattr(row.get("Low", c_val), 'iloc') else float(row.get("Low", c_val))
                v_val = int(row.get("Volume", 0).iloc[0]) if hasattr(row.get("Volume", 0), 'iloc') else int(row.get("Volume", 0))
                ts_str = ts_idx.strftime("%Y-%m-%d %H:%M:%S")
                bars.append({"ts": ts_str, "open": round(o_val, 2), "high": round(h_val, 2),
                             "low": round(l_val, 2), "close": round(c_val, 2), "volume": v_val})

        return {"ok": True, "data": bars}
    except Exception as exc:
        logger.exception("[/agent/intraday-bars] error for %s/%s", ticker, exchange)
        return {"ok": False, "data": [], "error": str(exc)}
