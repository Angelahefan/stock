"""Bridge between stock_chat streaming endpoint and the platform-be
ai_governance_guardrail pipeline.

The live chatbot needs to *visibly demonstrate* policy-as-data:
  1. Gate every turn; if blocked, stream a cited refusal
  2. Always append a governance footer (rules evaluated / fired / cited)
     so buyers see APRA/ASIC/OWASP cited in their own session
  3. Persist every decision into datapai.fct_ai_guardrail_decision for
     write-once audit evidence (joins to dim_ai_control for point-in-time
     policy reconstruction via SCD2)

Post-call validator is skipped on streams (output isn't known until
close); run it as background audit later if needed.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

log = logging.getLogger(__name__)

# Footer verbosity: verbose (default) / summary / off
FOOTER_MODE = os.environ.get("GUARDRAIL_SHOW_FOOTER", "verbose").lower()


def _safe_import():
    try:
        from agents.ai_governance_guardrail.gate import run_gate  # type: ignore
        from agents.ai_governance_guardrail.contracts import Verdict  # type: ignore
        from agents.llm_client import RouterChatClient  # type: ignore
        return run_gate, Verdict, RouterChatClient
    except Exception as e:
        log.warning("guardrail unavailable: %s — turn will pass through ungated", e)
        return None, None, None


# ─────────────────────────────────────────────────────────────────────────────
# Sensitivity Dial — 5 governance levels
# ─────────────────────────────────────────────────────────────────────────────
# Customers tune the gate to match their market strategy + risk tolerance.
# Same engine, same catalog, same audit trail — only the *blocking* threshold
# moves. The catalog is always evaluated; logs are always written; only what
# the end-user sees changes.
#
#   🟢 PERMISSIVE   Answer almost anything. Only hard-illegal gets blocked.
#                   Use case: marketing chat, lead-gen, growth phase.
#   🟡 LIGHT        Warn on advisory; allow with disclaimer. Block clearly
#                   illegal. Use case: support chat, pre-renewal phase.
#   🔵 BALANCED     Current default. Refuse personal advice; factual OK with
#                   disclaimer. Use case: retail support, post-onboarding.
#   🟠 STRICT       Refuse anything advisory-adjacent. Terse, factual-only.
#                   Use case: 30 days before AFSL renewal, post-ASIC inquiry.
#   🔴 LOCKDOWN     Product info + factual price/market data only. No opinions.
#                   Use case: active examination, AFSL renewal week.
#
# Mapping shape: { gate_verdict → effective_verdict_at_this_level }
_LEVELS = {"PERMISSIVE", "LIGHT", "BALANCED", "STRICT", "LOCKDOWN"}

_LEVEL_VERDICT_MAP = {
    "PERMISSIVE": {
        "block":                  "allow_with_conditions",
        "escalate":               "allow_with_conditions",
        "allow_with_conditions":  "allow",
        "allow":                  "allow",
    },
    "LIGHT": {
        "block":                  "allow_with_conditions",
        "escalate":               "block",
        "allow_with_conditions":  "allow",
        "allow":                  "allow",
    },
    "BALANCED": {
        # Pass-through — current production behaviour
        "block":                  "block",
        "escalate":               "escalate",
        "allow_with_conditions":  "allow_with_conditions",
        "allow":                  "allow",
    },
    "STRICT": {
        "block":                  "block",
        "escalate":               "block",
        "allow_with_conditions":  "block",
        "allow":                  "allow_with_conditions",  # add disclaimer
    },
    "LOCKDOWN": {
        # Almost everything blocks. Only factual info_request stays allowed.
        # The endpoint inspects classification to enforce this — see comment.
        "block":                  "block",
        "escalate":               "block",
        "allow_with_conditions":  "block",
        "allow":                  "block",  # endpoint overrides to allow_with_conditions if classification in {"info_request","price_query","factual"}
    },
}


def normalise_level(level: Optional[str]) -> str:
    """Coerce + validate a level string. Unknown → BALANCED (safe default)."""
    if not level:
        return "BALANCED"
    lv = str(level).upper().strip()
    return lv if lv in _LEVELS else "BALANCED"


# ─── DB-backed tenant policy resolution (5-min cache, fail-open) ────────────
_POLICY_CACHE: Dict[str, Any] = {"value": {}, "expires_at": 0.0}
_POLICY_TTL_S = int(os.environ.get("GOVERNANCE_POLICY_TTL_S", "300"))


def _load_tenant_policies() -> Dict[tuple, dict]:
    """Load active policies from datapai.ai_governance_policy in framework_db.

    Returns: { (tenant_slug, surface_key, segment_key): policy_row_dict }

    Cached 5 min. Fail-open: if DB unavailable, returns {} and the call site
    falls back to the explicit `level` arg or BALANCED default. Never blocks
    chat availability over a config-DB hiccup.
    """
    now = time.time()
    if _POLICY_CACHE["value"] and now < _POLICY_CACHE["expires_at"]:
        return _POLICY_CACHE["value"]
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.environ.get("FRAMEWORK_DB_HOST", "localhost"),
            port=int(os.environ.get("FRAMEWORK_DB_PORT", "5433")),
            user=os.environ.get("FRAMEWORK_DB_USER", "postgres"),
            password=os.environ.get("FRAMEWORK_DB_PASSWORD", "postgres"),
            dbname=os.environ.get("FRAMEWORK_DB_NAME", "datapai_auth_db"),
        )
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT tenant_slug, surface_key, segment_key,
                           level, coach_mode, audit_visibility, overrides_json
                    FROM datapai.ai_governance_policy
                    WHERE is_active = TRUE
                      AND (effective_from IS NULL OR effective_from <= NOW())
                      AND (effective_until IS NULL OR effective_until >  NOW())
                """)
                out = {}
                for tenant, surface, segment, lvl, coach, vis, overrides in cur.fetchall():
                    out[(tenant, surface, segment)] = {
                        "level": lvl, "coach_mode": coach,
                        "audit_visibility": vis, "overrides": overrides or {},
                    }
        conn.close()
        _POLICY_CACHE["value"] = out
        _POLICY_CACHE["expires_at"] = now + _POLICY_TTL_S
        return out
    except Exception as e:
        log.warning("ai_governance_policy load failed (fail-open): %s", e)
        # Don't poison cache — retry next call.
        return _POLICY_CACHE["value"] or {}


def resolve_tenant_policy(
    tenant_slug: Optional[str] = None,
    surface_key: Optional[str] = None,
    segment_key: Optional[str] = None,
) -> dict:
    """Resolve effective policy for (tenant, surface, segment) with fallback.

    Lookup order:
      1. exact (tenant, surface, segment)
      2. (tenant, surface, "default")
      3. (tenant, "default", "default")
      4. ("stockdatapai", "default", "default")  # global default tenant
      5. hardcoded BALANCED fallback
    Returns dict: {level, coach_mode, audit_visibility, overrides, source}
    """
    policies = _load_tenant_policies()
    tenant = (tenant_slug or "stockdatapai").lower()
    surface = (surface_key or "default").lower()
    segment = (segment_key or "default").lower()

    for key, src_tag in [
        ((tenant, surface, segment), "exact"),
        ((tenant, surface, "default"), "surface-default-segment"),
        ((tenant, "default", "default"), "tenant-default"),
        (("stockdatapai", "default", "default"), "global-default"),
    ]:
        row = policies.get(key)
        if row:
            return {**row, "source": src_tag, "matched_key": key}

    return {"level": "BALANCED", "coach_mode": False,
            "audit_visibility": "footer_visible",
            "overrides": {}, "source": "hardcoded-fallback"}


def apply_sensitivity_level(gate_result: Optional[dict], level: str) -> Optional[dict]:
    """Transform the raw gate verdict according to the customer's chosen level.

    Mutates a copy of the gate_result and adds:
      - `raw_verdict` (the catalog-derived verdict, audit truth)
      - `verdict` (the effective verdict at the configured level, UI truth)
      - `sensitivity_level` (the level applied)
    """
    if not gate_result:
        return gate_result
    lv = normalise_level(level)
    out = dict(gate_result)
    raw = out.get("verdict") or "allow"
    out["raw_verdict"] = raw
    mapped = _LEVEL_VERDICT_MAP.get(lv, _LEVEL_VERDICT_MAP["BALANCED"]).get(raw, raw)

    # LOCKDOWN escape hatch — never block clearly factual info_requests,
    # otherwise the product becomes useless ("what is BHP" can't be blocked).
    if lv == "LOCKDOWN" and mapped == "block":
        cls = (out.get("classification") or "").lower()
        if cls in ("info_request", "price_query", "factual", "data_lookup"):
            mapped = "allow_with_conditions"

    out["verdict"] = mapped
    out["sensitivity_level"] = lv
    return out


def run_gate_sync(message: str, metadata: dict, *, level: Optional[str] = None) -> Optional[dict]:
    """Returns a dict: {verdict, raw_verdict, sensitivity_level, risk_tier,
    classification, citations, refusal, conditions, gate_latency_ms,
    policy_source} or None if the guardrail module isn't importable
    (fail-open for availability).

    `level` resolution order (highest precedence first):
      1. explicit `level` kwarg (demo URL ?level= or request body)
      2. DB policy row for (tenant_slug, surface_key, segment_key) — read
         from metadata.{tenant_slug, surface_key, segment_key}
      3. DB policy row fallback chain (surface-default, tenant-default,
         global-default) — see resolve_tenant_policy()
      4. hardcoded BALANCED
    """
    run_gate, Verdict, RouterChatClient = _safe_import()
    if not run_gate:
        return None
    try:
        # Resolve effective level + audit visibility from DB if not overridden.
        if level:
            effective_level = normalise_level(level)
            policy = {"level": effective_level, "source": "explicit-arg"}
        else:
            policy = resolve_tenant_policy(
                tenant_slug=metadata.get("tenant_slug"),
                surface_key=metadata.get("surface_key"),
                segment_key=metadata.get("segment_key"),
            )
            effective_level = normalise_level(policy.get("level"))

        client = RouterChatClient()

        def _chat(messages, temperature=0.0):
            return client.chat(messages=messages, temperature=temperature)

        t0 = time.time()
        decision = run_gate(user_prompt=message, llm_chat=_chat, metadata=metadata)
        latency_ms = int((time.time() - t0) * 1000)
        raw = {
            "verdict": decision.verdict.value,
            "risk_tier": decision.risk_tier,
            "classification": decision.classification,
            "conditions": decision.conditions,
            "refusal": decision.refusal_message,
            "gate_latency_ms": latency_ms,
            "citations": [
                {
                    "control_nk": c.control_nk,
                    "framework_code": c.framework_code,
                    "framework_name": c.framework_name,
                    "control_id": c.control_id,
                    "control_name": c.control_name,
                    "obligation_family": c.obligation_family,
                    "source_url": c.source_url,
                }
                for c in decision.citations
            ],
            "policy_source": policy.get("source"),
            "audit_visibility": policy.get("audit_visibility", "footer_visible"),
            "coach_mode": policy.get("coach_mode", False),
        }
        return apply_sensitivity_level(raw, effective_level)
    except Exception as e:
        log.exception("gate invocation failed: %s", e)
        return None


# ─── Audit persistence ────────────────────────────────────────────────────
# Delegates to the shared helper in agents.ai_governance_guardrail.persistence
# so the same write-once INSERT path is used by both in-process callers
# (stock_chat) and HTTP callers (governance_api for MCP/Control-M/etc.).

def persist_decision(
    gate_result: Optional[dict],
    *,
    user_prompt: str,
    metadata: dict,
    session_id: Optional[str],
    user_id: Optional[str],
) -> None:
    """Insert one row into datapai.fct_ai_guardrail_decision. Never raises."""
    try:
        from agents.ai_governance_guardrail.persistence import persist_gate_decision
    except Exception as e:
        log.warning("governance persistence unavailable: %s", e)
        return
    persist_gate_decision(
        gate_result,
        user_prompt=user_prompt,
        metadata=metadata,
        session_id=session_id,
        user_id=user_id,
    )


def governance_sse_event(gate_result: Optional[dict]) -> str:
    """Structured SSE event for frontend consumption. Frontend can render
    it however it likes (collapsed badge, sidebar, footer)."""
    if not gate_result or FOOTER_MODE == "off":
        return ""
    payload = {
        "type": "governance",
        "verdict": gate_result["verdict"],
        "raw_verdict": gate_result.get("raw_verdict") or gate_result["verdict"],
        "sensitivity_level": gate_result.get("sensitivity_level") or "BALANCED",
        "risk_tier": gate_result["risk_tier"],
        "classification": gate_result["classification"],
        "conditions": gate_result.get("conditions") or [],
        "citations": gate_result["citations"],
        "policy_catalog": {
            "source": "datapai.dim_ai_control",
            "version_tag": "v2026-04-20",
        },
    }
    return f"data: {json.dumps(payload)}\n\n"


_STATUS_LABEL = {
    "allow":                 "Compliant",
    "allow_with_conditions": "Compliant",
    "block":                 "Blocked",
    "escalate":              "Needs human review",
}

# B2B demo pitch — the chat is a sales surface, not an end-user product.
# Buyers come from APRA-regulated banks, ASIC-licensed financial firms,
# AFSL holders, AUSTRAC reporting entities, ISO 42001 prospects, etc.
# Every turn must visibly prove the governance engine is running and is
# covering the frameworks they care about.
#
# Numbers + framework names are pulled live from datapai.dim_ai_control_finance
# every 5 min so when the policy team adds/removes a framework the demo
# updates without a code change. The DB call is fail-open: if the catalog
# DB is unreachable we fall back to a hardcoded pitch so the demo never
# regresses to "I don't know what I cover".
_CATALOG_FALLBACK = (
    "258 controls · 20 frameworks: "
    "APRA CPS 230 · ASIC REP 798 · AFSL · AUSTRAC AML/CTF · "
    "ISO 42001 · NIST AI RMF · OAIC Privacy APPs · OWASP Agentic Top 10 +12 more"
)
_CATALOG_CACHE: Dict[str, Any] = {"value": None, "expires_at": 0.0}
_CATALOG_TTL_S = int(os.environ.get("GOVERNANCE_CATALOG_TTL_S", "300"))

# Curated salience order — frameworks the AU FS demo audience cares about
# most appear FIRST in the inline list. Anything else falls into "+N more".
_PREFERRED_FRAMEWORKS = [
    "APRA_AI_2025", "APRA_CPS_234", "APRA_CPS_220", "APRA_CPG_235",
    "ASIC_AI_2024", "ASIC_AFSL_2025",
    "AUSTRAC_AML_2025",
    "ISO_42001_2023", "ISO_27001_2022",
    "NIST_AI_RMF_10", "NIST_AI_GENAI_PROFILE_2024", "NIST_CSF_20",
    "AU_PRIVACY_APPS",
    "AU_6_2025", "AU_AI_ETHICS_8_2019", "AU_VOLUNTARY_AI_SAFETY_2024",
    "NSW_AIAF_2024",
    "OWASP_AGENTIC_2026",
    "FINRA_24_09",
    "FCA_AI_DP5_22",
    "CO_AI_ACT_2024",
]


def _short_name(framework_code: str, framework_name: str) -> str:
    """Pretty short label for a framework code — buyers don't read full names."""
    aliases = {
        "APRA_AI_2025":           "APRA CPS 230",
        "APRA_CPS_220":           "APRA CPS 220",
        "APRA_CPS_234":           "APRA CPS 234",
        "APRA_CPG_235":           "APRA CPG 235",
        "ASIC_AI_2024":           "ASIC REP 798",
        "ASIC_AFSL_2025":         "AFSL (s911A/s961B)",
        "AUSTRAC_AML_2025":       "AUSTRAC AML/CTF",
        "ISO_42001_2023":         "ISO 42001",
        "ISO_27001_2022":         "ISO 27001",
        "NIST_AI_RMF_10":         "NIST AI RMF",
        "NIST_AI_GENAI_PROFILE_2024": "NIST GenAI Profile",
        "NIST_CSF_20":            "NIST CSF 2.0",
        "AU_PRIVACY_APPS":        "OAIC Privacy APPs",
        "AU_6_2025":              "AU 6 Principles",
        "AU_AI_ETHICS_8_2019":    "AU AI Ethics",
        "AU_VOLUNTARY_AI_SAFETY_2024": "AU Voluntary AI Safety",
        "NSW_AIAF_2024":          "NSW AIAF",
        "OWASP_AGENTIC_2026":     "OWASP Agentic Top 10",
        "FINRA_24_09":            "FINRA 24-09",
        "FCA_AI_DP5_22":          "FCA DP5/22",
        "CO_AI_ACT_2024":         "Colorado AI Act",
    }
    return aliases.get(framework_code, framework_name or framework_code)


def _load_catalog_summary() -> Dict[str, Any]:
    """Read total controls + framework list from the policy catalog.

    Cached for 5 min (configurable via GOVERNANCE_CATALOG_TTL_S). Fails
    open to a hardcoded fallback so the chat demo never regresses to a
    blank or stale pitch when the framework DB is briefly unreachable.
    """
    now = time.time()
    if _CATALOG_CACHE["value"] is not None and _CATALOG_CACHE["expires_at"] > now:
        return _CATALOG_CACHE["value"]
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.environ.get("FRAMEWORK_DB_HOST", "localhost"),
            port=int(os.environ.get("FRAMEWORK_DB_PORT", "5433")),
            user=os.environ.get("FRAMEWORK_DB_USER", "postgres"),
            password=os.environ.get("FRAMEWORK_DB_PASSWORD", "postgres"),
            dbname=os.environ.get("FRAMEWORK_DB_NAME", "datapai_auth_db"),
            connect_timeout=3,
        )
        try:
            with conn.cursor() as cur:
                # status='complete' is the production-ready bar in the
                # catalog. NULL is treated as complete for legacy rows.
                # 'stub' / 'top_level_only' are placeholders and excluded.
                cur.execute("""
                    SELECT framework_code, framework_name, COUNT(*) AS n
                    FROM datapai.dim_ai_control_finance
                    WHERE COALESCE(status, 'complete') IN ('complete', 'active')
                    GROUP BY framework_code, framework_name
                """)
                rows = cur.fetchall()
        finally:
            conn.close()
        total = sum(r[2] for r in rows)
        # Sort: preferred order first, then alphabetical for the rest
        preferred_set = set(_PREFERRED_FRAMEWORKS)
        preferred_rows = sorted(
            (r for r in rows if r[0] in preferred_set),
            key=lambda r: _PREFERRED_FRAMEWORKS.index(r[0]),
        )
        other_rows = sorted((r for r in rows if r[0] not in preferred_set), key=lambda r: r[0])
        all_rows = preferred_rows + other_rows
        result = {
            "total_controls": total,
            "framework_count": len(rows),
            "frameworks": [
                {"code": r[0], "name": r[1], "short": _short_name(r[0], r[1]), "count": r[2]}
                for r in all_rows
            ],
        }
        _CATALOG_CACHE["value"] = result
        _CATALOG_CACHE["expires_at"] = now + _CATALOG_TTL_S
        return result
    except Exception as e:
        log.warning("Catalog summary load failed (using fallback): %s", e)
        return {"total_controls": 364, "framework_count": 34, "frameworks": []}


def _build_catalog_pitch() -> str:
    """One-line catalog pitch for the allow-path chat footer.

    Uses live numbers + the curated salience order so the AU regulators
    (APRA, ASIC, AFSL, AUSTRAC, OAIC) appear first.
    """
    summary = _load_catalog_summary()
    fw = summary.get("frameworks") or []
    if not fw:
        return _CATALOG_FALLBACK
    SHOW = 8
    inline = [f["short"] for f in fw[:SHOW]]
    extra = max(0, summary["framework_count"] - SHOW)
    extra_suffix = f" +{extra} more" if extra else ""
    return (
        f"{summary['total_controls']} controls · "
        f"{summary['framework_count']} frameworks: "
        f"{' · '.join(inline)}{extra_suffix}"
    )


def footer_markdown(gate_result: Optional[dict], *, blocked: bool = False) -> str:
    """Footer rendered on every chat turn — this is the B2B demo surface.

    Allow / Compliant path: one tasteful italic line proving the gate ran
    and listing the framework coverage buyers want to see (APRA, ASIC,
    ISO 42001, NIST AI RMF, OAIC, AU 6 Principles, NSW AIAF, OWASP, etc).
    Designed to be visible-but-not-noisy — small visual weight, no rule
    list, no clinical jargon.

    Block path: shows WHICH controls fired (`control_id` in code-format),
    which frameworks they came from, and the total rules cited count.
    This is the compliance evidence prospects screenshot for their CISO.

    The structured `governance` SSE event still carries the full citation
    list separately for any sidebar/badge UI that wants to render it.
    """
    if not gate_result or FOOTER_MODE == "off":
        return ""
    cites = gate_result.get("citations") or []
    level = gate_result.get("sensitivity_level") or "BALANCED"
    # Tiny level badge — visible proof to demo audience that the dial is real.
    # Buyer-friendly labels (Option B — pure 1-5 strictness scale) so anyone
    # can tell at a glance how tight the dial is set. Internal codes
    # (PERMISSIVE/LIGHT/BALANCED/STRICT/LOCKDOWN) stay as-is in DB + API for
    # backwards compatibility — only the *display* label changes.
    _LEVEL_DISPLAY = {
        "PERMISSIVE": ("🟢", "1 — Most Open"),
        "LIGHT":      ("🟡", "2 — Light"),
        "BALANCED":   ("🔵", "3 — Standard"),
        "STRICT":     ("🟠", "4 — Strict"),
        "LOCKDOWN":   ("🔴", "5 — Maximum"),
    }
    level_emoji, level_display = _LEVEL_DISPLAY.get(level, ("🔵", "3 — Standard"))
    # Only render the badge when the dial is NOT at the everyday default
    # (BALANCED / "3 — Standard"), so the chat UI stays clean most of the time
    # but PERMISSIVE / STRICT / LOCKDOWN stand out.
    level_badge = f"  ·  {level_emoji} {level_display}" if level != "BALANCED" else ""

    if not blocked:
        # Allow path: one-line proof + framework breadth (live from DB).
        return "\n".join([
            "",
            f"_✅ AI governance · {_build_catalog_pitch()}{level_badge}_",
        ])

    # Block path: which rules fired, which frameworks they came from.
    top_ids = " · ".join(f"`{c['control_id']}`" for c in cites[:3])
    more_rules = f" + {len(cites) - 3} more" if len(cites) > 3 else ""
    fw_names = sorted({c.get("framework_name", "") for c in cites if c.get("framework_name")})
    fw_inline = " · ".join(fw_names[:3]) + (f" + {len(fw_names) - 3} more" if len(fw_names) > 3 else "")

    return "\n".join([
        "",
        "───",
        f"🛡 **AI governance · Blocked** — {top_ids}{more_rules}{level_badge}",
        f"_Frameworks cited: {fw_inline}_" if fw_inline else "",
    ])
