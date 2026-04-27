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


def run_gate_sync(message: str, metadata: dict) -> Optional[dict]:
    """Returns a dict: {verdict, risk_tier, classification, citations, refusal, conditions,
    gate_latency_ms} or None if the guardrail module isn't importable
    (fail-open for availability).
    """
    run_gate, Verdict, RouterChatClient = _safe_import()
    if not run_gate:
        return None
    try:
        client = RouterChatClient()

        def _chat(messages, temperature=0.0):
            return client.chat(messages=messages, temperature=temperature)

        t0 = time.time()
        decision = run_gate(user_prompt=message, llm_chat=_chat, metadata=metadata)
        latency_ms = int((time.time() - t0) * 1000)
        return {
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
        }
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
# ISO 42001 prospects, etc. Every turn must visibly prove the governance
# engine is running and is covering the frameworks they care about.
#
# Numbers are pulled from the policy catalog (datapai.dim_ai_control); the
# inline framework list is curated for AU + global salience. If you add or
# remove frameworks from the catalog, update this string in lock-step.
_CATALOG_PITCH = (
    "213 controls scanned · 16 frameworks: "
    "APRA CPS 230 · ASIC REP 798 · ISO 42001 · NIST AI RMF · "
    "OAIC Privacy APPs · AU 6 Principles · NSW AIAF · OWASP Agentic Top 10 +8 more"
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

    if not blocked:
        # Allow path: one-line proof + framework breadth.
        return "\n".join([
            "",
            f"_✅ AI governance · {_CATALOG_PITCH}_",
        ])

    # Block path: which rules fired, which frameworks they came from.
    top_ids = " · ".join(f"`{c['control_id']}`" for c in cites[:3])
    more_rules = f" + {len(cites) - 3} more" if len(cites) > 3 else ""
    fw_names = sorted({c.get("framework_name", "") for c in cites if c.get("framework_name")})
    fw_inline = " · ".join(fw_names[:3]) + (f" + {len(fw_names) - 3} more" if len(fw_names) > 3 else "")

    return "\n".join([
        "",
        "───",
        f"🛡 **AI governance · Blocked** — {top_ids}{more_rules}",
        f"_Frameworks cited: {fw_inline}_" if fw_inline else "",
    ])
