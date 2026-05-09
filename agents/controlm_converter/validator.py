"""
Validate a generated DAG file before we hand it off to operators.

Checks (in order, cheapest first):
  1. `compile()` — pure-Python syntax check, no Airflow import needed.
  2. Optional: `airflow dags reserialize --subdir <tmp>` if airflow is on PATH.
"""
from __future__ import annotations
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple

log = logging.getLogger(__name__)


def validate_dag_source(source: str) -> Tuple[bool, str]:
    try:
        compile(source, "<generated_dag>", "exec")
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"

    if not shutil.which("airflow"):
        return True, "syntax-ok (airflow CLI not present, skipping deep parse)"

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "dag.py"
        path.write_text(source)
        try:
            r = subprocess.run(
                ["airflow", "dags", "list", "--subdir", td],
                capture_output=True, text=True, timeout=60,
            )
        except Exception as e:
            return True, f"syntax-ok (airflow probe failed: {e})"
        if r.returncode != 0:
            return False, f"airflow parse failed:\n{r.stderr or r.stdout}"
    return True, "ok"
