"""
controlm_to_airflow_converter — agentic DAG that converts BMC Control-M job
exports into Airflow DAG files.

Reusable: drop a Control-M Automation-API JSON (or legacy XML) export into the
input directory and trigger the DAG. The agent (gemini-2.5-flash) classifies
each job, the renderer emits a DAG file per Control-M folder, the validator
syntax-checks each one, and the writer drops them into the output directory
ready for human review (`is_paused_upon_creation=True` so nothing auto-runs).

Trigger via DAG params:
  - input_path:  folder OR single file (.json / .xml). Default = ${CONTROLM_INPUT_DIR}
  - output_dir:  where to write generated DAG .py files. Default = ${CONTROLM_OUTPUT_DIR}
  - model:       LLM model to use for the agent classifier (default gemini-2.5-flash)

The DAG uses dynamic task mapping so each Control-M FILE becomes its own
mapped instance — keeps logs clean per source export.
"""
from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pendulum
from airflow.decorators import dag, task

UTC = pendulum.timezone("UTC")
log = logging.getLogger(__name__)

DEFAULT_INPUT = os.environ.get("CONTROLM_INPUT_DIR", "/opt/airflow/data/controlm_in")
DEFAULT_OUTPUT = os.environ.get("CONTROLM_OUTPUT_DIR", "/opt/airflow/data/controlm_out")


@dag(
    dag_id="controlm_to_airflow_converter",
    default_args={
        "owner": "datapai-platform",
        "retries": 0,
        "execution_timeout": timedelta(minutes=30),
    },
    schedule=None,  # manual trigger only
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    tags=["datapai", "controlm", "migration", "agentic", "tool"],
    max_active_runs=1,
    is_paused_upon_creation=True,
    params={
        "input_path": DEFAULT_INPUT,
        "output_dir": DEFAULT_OUTPUT,
        "model": "gemini-2.5-flash",
        "force_llm": False,
    },
    doc_md=__doc__,
)
def controlm_to_airflow_converter():

    @task
    def read_params(**context) -> Dict[str, Any]:
        return dict(context["params"])

    @task
    def discover_inputs(params: Dict[str, Any]) -> List[str]:
        p = Path(params["input_path"])
        if p.is_file():
            return [str(p)]
        if not p.is_dir():
            raise FileNotFoundError(f"input_path not found: {p}")
        files = sorted(
            str(f) for f in p.iterdir()
            if f.is_file() and f.suffix.lower() in (".json", ".xml")
        )
        if not files:
            log.warning("No .json or .xml files in %s", p)
        return files

    @task
    def convert_one(input_file: str, params: Dict[str, Any]) -> Dict[str, Any]:
        # Lazy import — keeps the scheduler-time DAG parse cheap and avoids
        # forcing google-genai to import on every Airflow scheduler heartbeat.
        from agents.controlm_converter import convert_folder

        out_dir = Path(params["output_dir"]) / Path(input_file).stem
        results = convert_folder(
            Path(input_file),
            output_dir=out_dir,
            model=params.get("model"),
        )
        # Strip the inlined source from the summary so XCom stays small;
        # files are already on disk.
        for r in results:
            r.pop("source", None)
        log.info("Converted %s → %d DAG(s) under %s", input_file, len(results), out_dir)
        return {"input": input_file, "results": results}

    @task
    def summarise(all_results: List[Dict[str, Any]]) -> str:
        total_dags = sum(len(r["results"]) for r in all_results)
        bad = [
            (r["input"], dr["dag_id"], dr["validation"])
            for r in all_results for dr in r["results"] if not dr["ok"]
        ]
        msg = (
            f"Converted {len(all_results)} input file(s) → {total_dags} DAG(s). "
            f"{len(bad)} failed validation."
        )
        if bad:
            msg += "\nFailures:\n" + "\n".join(f"  - {i}::{d}: {m}" for i, d, m in bad)
        log.info(msg)
        return msg

    p = read_params()
    files = discover_inputs(p)
    converted = convert_one.partial(params=p).expand(input_file=files)
    summarise(converted)


controlm_to_airflow_converter()
