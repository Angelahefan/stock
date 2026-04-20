"""Bridge between stock_chat streaming endpoint and the platform-be
ai_governance_guardrail pipeline.

The live chatbot needs to *visibly demonstrate* policy-as-data:
  1. Gate every turn; if blocked, stream a cited refusal
  2. Always append a governance footer (rules evaluated / fired / cited)
     so buyers see APRA/ASIC/OWASP cited in their own session

Post-call validator is skipped on streams (output isn't known until
close); run it as background audit later if needed.
"""
from __future__ import annotations

import json
import logging
import os
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
    """Returns a dict: {verdict, risk_tier, classification, citations, refusal, conditions}
    or None if the guardrail module isn't importable (fail-open for availability).
    """
    run_gate, Verdict, RouterChatClient = _safe_import()
    if not run_gate:
        return None
    try:
        client = RouterChatClient()

        def _chat(messages, temperature=0.0):
            return client.chat(messages=messages, temperature=temperature)

        decision = run_gate(user_prompt=message, llm_chat=_chat, metadata=metadata)
        return {
            "verdict": decision.verdict.value,
            "risk_tier": decision.risk_tier,
            "classification": decision.classification,
            "conditions": decision.conditions,
            "refusal": decision.refusal_message,
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


def footer_markdown(gate_result: Optional[dict]) -> str:
    """Human-readable footer text for chat UIs that don't render the
    structured event. Empty string when hidden."""
    if not gate_result or FOOTER_MODE == "off":
        return ""
    cites = gate_result["citations"]
    lines = [
        "",
        "───",
        f"🛡 **Governance check** — `{gate_result['verdict']}` "
        f"(risk: {gate_result['risk_tier']}, class: {gate_result['classification']})",
    ]
    if cites:
        lines.append(f"Rules cited ({len(cites)}):")
        show = cites if FOOTER_MODE == "verbose" else cites[:3]
        for c in show:
            nm = c["control_name"] or c["control_id"]
            lines.append(f"  • `{c['control_id']}` — {nm}  _({c['framework_name']})_")
        if FOOTER_MODE == "summary" and len(cites) > 3:
            lines.append(f"  • …and {len(cites) - 3} more")
    conds = gate_result.get("conditions") or []
    if conds:
        lines.append(f"Conditions: {', '.join(conds)}")
    lines.append("_Source: `datapai.dim_ai_control` · 213 rules · 16 frameworks · v2026-04-20_")
    return "\n".join(lines)
