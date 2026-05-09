"""
controlm_converter — reusable agentic converter from Control-M job definitions
to Apache Airflow DAGs.

Typical use:
    from agents.controlm_converter import convert_job, convert_folder
    dag_py = convert_job(controlm_job_dict, model="gemini-2.5-flash")

The Airflow-side orchestrator lives at:
    scripts/dags/controlm_to_airflow_converter.py
"""
from .api import convert_job, convert_folder, classify_job
from .job_types import JOB_TYPE_REGISTRY, ControlMJobType

__all__ = [
    "convert_job",
    "convert_folder",
    "classify_job",
    "JOB_TYPE_REGISTRY",
    "ControlMJobType",
]
