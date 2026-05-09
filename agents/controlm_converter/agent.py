"""
LLM agent that takes a single Control-M job dict and returns:
  { "job_type": <registry name>, "fields": {...expected_fields...}, "notes": "..." }

We use the project's standard LLM client (gemini-2.5-flash — *not* lite, per
project memory: lite drops responses after function-call rounds).

The agent is given exactly ONE tool: `submit_classification`. The model is
instructed to produce a single tool call. We deliberately keep the LLM step
small — heuristic classification handles the obvious cases first, and the
agent is only invoked when the registry can't pick a job type by alias, OR
when expected fields aren't present.
"""
from __future__ import annotations
import json
import logging
import os
from typing import Any, Dict, List, Optional

from .job_types import JOB_TYPE_REGISTRY, ControlMJobType, resolve_type

log = logging.getLogger(__name__)

_DEFAULT_MODEL = os.environ.get("CONTROLM_CONVERTER_MODEL", "gemini-2.5-flash")

_SYSTEM_PROMPT = """You convert BMC Control-M job definitions to Apache Airflow.

You will be given:
  1. A single Control-M job dict (raw, possibly partial / oddly-named keys).
  2. The list of supported Airflow job types and the fields each one needs.

Your job: pick the BEST matching `job_type` from the supported list and extract
the fields needed by that type from the raw job. If a field is missing, OMIT
it (do NOT invent values). If you genuinely cannot match any specific type,
return job_type="generic" and put the original command/script in fields.raw.

Output exactly ONE call to the `submit_classification` tool. No prose.
"""


def _supported_summary() -> str:
    lines = []
    for jt in JOB_TYPE_REGISTRY.values():
        lines.append(
            f"- {jt.name}: aliases={list(jt.aliases)} fields={list(jt.expected_fields)}"
            + (f" — {jt.notes}" if jt.notes else "")
        )
    return "\n".join(lines)


_TOOL_SCHEMA = {
    "name": "submit_classification",
    "description": "Submit the job_type + extracted fields for this Control-M job.",
    "parameters": {
        "type": "object",
        "properties": {
            "job_type": {
                "type": "string",
                "enum": list(JOB_TYPE_REGISTRY.keys()),
            },
            "fields": {
                "type": "object",
                "description": "Field dict matching expected_fields for the chosen job_type.",
                "additionalProperties": True,
            },
            "confidence": {"type": "number"},
            "notes": {"type": "string"},
        },
        "required": ["job_type", "fields", "confidence"],
    },
}


def _heuristic_classify(job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Cheap path: registry alias match + obvious field copy. Skips LLM entirely."""
    jt: ControlMJobType = resolve_type(job.get("Type", ""))
    if jt.name == "generic":
        return None
    fields: Dict[str, Any] = {}
    # Direct case-insensitive copy of expected fields if the job dict has them.
    lower = {k.lower(): v for k, v in job.items() if not isinstance(v, dict)}
    for f in jt.expected_fields:
        if f in lower:
            fields[f] = lower[f]
    # Type-specific quick wins
    if jt.name == "command" and "Command" in job:
        fields.setdefault("command", job["Command"])
    if jt.name == "embedded_script" and "Script" in job:
        fields.setdefault("script", job["Script"])
        fields.setdefault("interpreter", job.get("Interpreter", "bash"))
    if jt.name == "web_services":
        fields.setdefault("url", job.get("URL") or job.get("Endpoint"))
        fields.setdefault("method", job.get("HTTPMethod") or job.get("Method") or "POST")
    if jt.name == "database":
        fields.setdefault("connection", job.get("ConnectionProfile") or job.get("Connection"))
        fields.setdefault("sql", job.get("SQLScript") or job.get("Query"))
    return {"job_type": jt.name, "fields": fields, "confidence": 0.9, "notes": "heuristic"}


def classify_job(
    job: Dict[str, Any],
    *,
    model: str = _DEFAULT_MODEL,
    force_llm: bool = False,
) -> Dict[str, Any]:
    """Return classification dict. Uses heuristics first, LLM as fallback."""
    if not force_llm:
        cheap = _heuristic_classify(job)
        if cheap and cheap["fields"]:
            return cheap

    # LLM fallback
    try:
        # Project-local LLM client (lives in the platform repo, attached via
        # agents/__init__.py path-extension trick).
        from agents.llm_client import call_with_tools  # type: ignore
    except Exception as e:
        log.warning("LLM client unavailable (%s) — returning heuristic-or-generic.", e)
        return _heuristic_classify(job) or {
            "job_type": "generic",
            "fields": {"raw": job.get("Command") or job.get("Script") or ""},
            "confidence": 0.0,
            "notes": f"no LLM available: {e}",
        }

    user_msg = (
        f"Supported job types:\n{_supported_summary()}\n\n"
        f"Control-M job:\n{json.dumps(job, default=str, indent=2)[:8000]}"
    )
    try:
        result = call_with_tools(
            model=model,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            tools=[_TOOL_SCHEMA],
            tool_choice={"name": "submit_classification"},
        )
    except Exception as e:
        log.exception("LLM classification failed for job %s", job.get("_name"))
        return _heuristic_classify(job) or {
            "job_type": "generic",
            "fields": {"raw": str(job.get("Command") or "")},
            "confidence": 0.0,
            "notes": f"LLM error: {e}",
        }

    # call_with_tools is expected to return the tool-call args dict.
    if isinstance(result, dict) and "job_type" in result:
        return result
    if isinstance(result, list) and result:
        return result[0]
    return {
        "job_type": "generic",
        "fields": {"raw": str(job.get("Command") or "")},
        "confidence": 0.0,
        "notes": "LLM returned unexpected shape",
    }


def classify_batch(jobs: List[Dict[str, Any]], **kwargs) -> List[Dict[str, Any]]:
    return [classify_job(j, **kwargs) for j in jobs]
