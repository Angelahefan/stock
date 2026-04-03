"""
dags/datapai_news_monitor.py
─────────────────────────────────────────────────────────────────────────────
Monitor breaking news for all watchlist tickers.
Runs every 2 hours on weekdays. News can break outside market hours
so we cover the full day.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from airflow import DAG
from datapai_common import DEFAULT_ARGS, BASH_ENV_PREAMBLE
from airflow.operators.bash import BashOperator

with DAG(
    dag_id="datapai_news_monitor",
    default_args={**DEFAULT_ARGS, "retries": 1, "execution_timeout": timedelta(minutes=15)},
    description="Check breaking news for watchlist tickers every 2 hours",
    schedule="7 */2 * * 1-5",  # Every 2 hours at :07, weekdays only
    start_date=datetime(2026, 3, 21),
    catchup=False,
    max_active_runs=1,
    tags=["datapai", "news", "watchlist"],
) as dag:

    check_news = BashOperator(
        task_id="check_watchlist_news",
        bash_command=f"""{BASH_ENV_PREAMBLE}
python3 scripts/check_news_watchlist.py
""",
    )
