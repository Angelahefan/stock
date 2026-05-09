"""
Top-level reusable entry points for controlm_converter.

Single-job:
    convert_job(job_dict, model="...") -> {"dag_id": ..., "source": "...", "ok": True}

Batch (folder export → one DAG per Control-M folder):
    convert_folder(payload, output_dir=Path("./out")) -> [ {dag_id, path, ok, msg}, ... ]
"""
from __future__ import annotations
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .agent import classify_job
from .parser import parse_controlm_export, extract_dependencies
from .renderer import render_dag, render_task, _safe_id
from .validator import validate_dag_source

log = logging.getLogger(__name__)


def _build_edges(rendered_tasks: List[Dict[str, Any]],
                 raw_jobs: List[Dict[str, Any]]) -> List[tuple]:
    """
    Translate Control-M IN/OUT conditions to Airflow upstream/downstream edges.

    Control-M model: a job emits OutConditions and waits on InConditions.
    Two jobs are linked if `producer.OutConditions ∩ consumer.InConditions` is non-empty.
    """
    by_index = list(zip(rendered_tasks, raw_jobs))
    deps = [extract_dependencies(j) for _, j in by_index]
    edges = []
    for i, (rt_i, _) in enumerate(by_index):
        produced = set(deps[i]["produced_conditions"])
        if not produced:
            continue
        for k, (rt_k, _) in enumerate(by_index):
            if i == k:
                continue
            if produced & set(deps[k]["upstream_conditions"]):
                edges.append((rt_i["task_id"], rt_k["task_id"]))
    return edges


def convert_job(job: Dict[str, Any], *, model: Optional[str] = None) -> Dict[str, Any]:
    """Convert a single Control-M job dict to a one-task DAG (handy for unit tests)."""
    classification = classify_job(job, model=model) if model else classify_job(job)
    rendered = render_task(job, classification.get("fields", {}))
    dag_id = f"ctm_{_safe_id(job.get('_name', 'job'))}"
    source = render_dag(
        dag_id=dag_id,
        schedule=None,
        tasks=[rendered],
        edges=[],
        description=f"Single Control-M job: {job.get('_name')}",
    )
    ok, msg = validate_dag_source(source)
    return {"dag_id": dag_id, "source": source, "ok": ok, "validation": msg,
            "classification": classification}


def convert_folder(
    payload: Union[str, dict, Path],
    *,
    output_dir: Optional[Path] = None,
    model: Optional[str] = None,
    dag_id_prefix: str = "ctm_",
) -> List[Dict[str, Any]]:
    """
    Convert a Control-M export (dict / JSON / XML / file path) into one Airflow
    DAG per Control-M folder. Returns one result entry per generated DAG.
    """
    jobs = parse_controlm_export(payload)
    if not jobs:
        return []

    # Group jobs by Control-M folder (each folder → one Airflow DAG).
    by_folder: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for j in jobs:
        by_folder[j.get("_folder") or "default"].append(j)

    results = []
    for folder, folder_jobs in by_folder.items():
        rendered_tasks = []
        for j in folder_jobs:
            classification = classify_job(j, model=model) if model else classify_job(j)
            rendered_tasks.append(render_task(j, classification.get("fields", {})))

        edges = _build_edges(rendered_tasks, folder_jobs)
        dag_id = f"{dag_id_prefix}{_safe_id(folder)}"
        source = render_dag(
            dag_id=dag_id,
            schedule=None,
            tasks=rendered_tasks,
            edges=edges,
            description=f"Migrated Control-M folder: {folder} ({len(folder_jobs)} jobs)",
        )
        ok, msg = validate_dag_source(source)
        out_path = None
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            out_path = output_dir / f"{dag_id}.py"
            out_path.write_text(source)

        results.append({
            "folder": folder,
            "dag_id": dag_id,
            "n_jobs": len(folder_jobs),
            "ok": ok,
            "validation": msg,
            "path": str(out_path) if out_path else None,
            "source": source if not out_path else None,
        })
    return results
