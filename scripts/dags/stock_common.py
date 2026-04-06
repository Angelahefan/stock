"""
dags/stock_common.py — shared helpers for all DataPAI Airflow DAGs.
Scripts use container Python 3.11 with all deps installed.

Key fix: uses /tmp paths for caches and logs to avoid permission issues
when Airflow worker runs as 'airflow' user but HOME is ec2-user.
"""
from __future__ import annotations
from datetime import timedelta
from airflow.operators.bash import BashOperator

SCRIPTS_DIR = "/opt/datapai-stock/scripts"
PROJECT_DIR = "/opt/datapai-stock"
PLATFORM_DIR = "/opt/datapai"

DEFAULT_ARGS = {
    "owner": "datapai",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=30),
    "execution_timeout": timedelta(hours=1),
}

# Log + cache dirs scoped by DAG name to avoid collisions and permission issues.
# yfinance, HOME, and log dirs all under /tmp — writable by any user.
# DAG_ID and TASK_ID injected by Airflow template; fallback to 'default'.
BASH_ENV_PREAMBLE = """
set -euo pipefail

# Scope caches by DAG + task to avoid collisions between parallel DAGs
_DAG_ID="$${AIRFLOW_CTX_DAG_ID:-default}"
_TASK_ID="$${AIRFLOW_CTX_TASK_ID:-default}"

export DATAPAI_LOG_DIR="/tmp/stock_logs/$${_DAG_ID}"
export YF_CACHE_DIR="/tmp/yfinance_cache/$${_DAG_ID}/$${_TASK_ID}"
export HOME="/tmp/stock_home/$${_DAG_ID}"

mkdir -p "$DATAPAI_LOG_DIR" "$YF_CACHE_DIR" "$HOME/.cache" 2>/dev/null || true
mkdir -p /opt/datapai-stock/scripts/logs 2>/dev/null || true

# Source credentials (env vars, API keys)
set +u
[[ -f /opt/airflow/.bash_profile ]] && source /opt/airflow/.bash_profile || true
[[ -f /opt/datapai/.env.dev ]] && set -a && source /opt/datapai/.env.dev && set +a || true
[[ -f /opt/datapai/.env ]] && set -a && source /opt/datapai/.env && set +a || true
set -u

# Platform framework on PYTHONPATH so stock scripts can import agents.llm_client etc.
export DATAPAI_PLATFORM_DIR="/opt/datapai"
export PYTHONPATH="/opt/datapai-stock:/opt/datapai:$${PYTHONPATH:-}"

cd /opt/datapai-stock
"""


def stock_bash_task(task_id: str, script_name: str, args: str = "", **kwargs) -> BashOperator:
    """Factory for BashOperator tasks that run existing .sh wrappers."""
    return BashOperator(
        task_id=task_id,
        bash_command=f"{BASH_ENV_PREAMBLE}\nbash {SCRIPTS_DIR}/{script_name} {args}",
        **kwargs,
    )
