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


def footer_markdown(gate_result: Optional[dict]) -> str:
    """Human-readable footer for chat UIs that don't render the structured
    governance event. Tuned for B2B demo: leads with AU regulatory coverage,
    hides internal mechanics (risk tier, classification, conditions)."""
    if not gate_result or FOOTER_MODE == "off":
        return ""
    cites = gate_result["citations"]
    status = _STATUS_LABEL.get(gate_result["verdict"], gate_result["verdict"])
    lines = [
        "",
        "───",
        f"🛡 **AI governance** — {status}",
    ]
    if cites:
        lines.append(f"Rules cited ({len(cites)}):")
        show = cites if FOOTER_MODE == "verbose" else cites[:3]
        for c in show:
            nm = c["control_name"] or c["control_id"]
            lines.append(f"  • `{c['control_id']}` — {nm}  _({c['framework_name']})_")
        if FOOTER_MODE == "summary" and len(cites) > 3:
            lines.append(f"  • …and {len(cites) - 3} more")
    lines.append("_Source: datapai · 213 AI governance controls · 16 regulatory & industry frameworks (APRA CPS 230, ASIC REP 798, OAIC Privacy APPs, AU 6 Principles, NSW AIAF, OWASP Agentic Top 10, NIST AI RMF, ISO 42001, …)_")
    return "\n".join(lines)
