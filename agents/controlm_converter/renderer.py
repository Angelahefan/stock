"""
Render an Airflow DAG file from a list of normalised + classified Control-M
jobs.

We build the DAG body by stitching per-job snippets emitted from Jinja
templates (one per Control-M job type), then wrap them in a DAG header.

Why per-task snippets in templates rather than one giant DAG template:
  - new job types = drop a new .j2 file + registry entry, no central edit
  - safer for the LLM agent (it only fills slot variables, never DAG control flow)
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
except ImportError as e:  # pragma: no cover
    raise RuntimeError("controlm_converter requires Jinja2 (already an Airflow dep)") from e

from .job_types import resolve_type, ControlMJobType

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(disabled_extensions=("py.j2",)),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def _safe_id(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", name or "task").strip("_")
    if not s or s[0].isdigit():
        s = f"t_{s}"
    return s.lower()[:62]


def render_task(job: Dict[str, Any], extracted: Dict[str, Any]) -> Dict[str, Any]:
    """
    Render the per-task snippet.

    `extracted` comes from the LLM agent: it's the normalised field dict
    matching `job_type.expected_fields`, plus optional `notes`.
    """
    job_type: ControlMJobType = resolve_type(job.get("Type", ""))
    template = _env.get_template(job_type.template)
    task_id = _safe_id(job.get("_name") or job.get("jobname") or "task")
    snippet = template.render(
        task_id=task_id,
        job=job,
        fields=extracted,
        operator_fqn=job_type.airflow_operator,
        notes=job_type.notes,
    )
    return {
        "task_id": task_id,
        "snippet": snippet,
        "operator_fqn": job_type.airflow_operator,
        "job_type": job_type.name,
    }


def render_dag(
    *,
    dag_id: str,
    schedule: Optional[str],
    tasks: List[Dict[str, Any]],
    edges: List[tuple],
    description: str = "",
    tags: Optional[List[str]] = None,
) -> str:
    header = _env.get_template("_dag_header.py.j2")
    imports = sorted({t["operator_fqn"] for t in tasks})
    return header.render(
        dag_id=_safe_id(dag_id),
        schedule=schedule,
        description=description or f"Converted from Control-M folder {dag_id}",
        tags=tags or ["controlm", "converted"],
        imports=imports,
        tasks=tasks,
        edges=edges,
    )
