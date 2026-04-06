"""
stock_intraday_runner_west — Consolidated US + UK intraday bar collector.
Handles: US, LSE in a single process.
Triggers at 08:00 London time (LSE opens first), runs until US market close.
The runner auto-detects which markets are currently open and refreshes them sequentially.

Cost-saving: 1 process instead of 2. When infra scales up, re-enable per-market DAGs
from scripts/dags/_archived/ for parallel execution.
"""
from datetime import datetime, timedelta
import pendulum
from airflow.decorators import dag
from airflow.timetables.trigger import CronTriggerTimetable
from stock_common import DEFAULT_ARGS, stock_bash_task

LON_TZ = pendulum.timezone("Europe/London")

@dag(
    dag_id="stock_intraday_runner_west",
    default_args=DEFAULT_ARGS,
    timetable=CronTriggerTimetable("0 8 * * 1-5", timezone=LON_TZ),
    start_date=datetime(2026, 3, 30, tzinfo=LON_TZ),
    catchup=False,
    tags=["datapai", "intraday", "us", "lse", "runner", "consolidated"],
    max_active_runs=1,
)
def stock_intraday_runner_west():
    stock_bash_task(
        "intraday_runner_west",
        "intraday_runner.sh",
        args="--exchange ALL",
        execution_timeout=timedelta(hours=12),
        retries=1,
    )

stock_intraday_runner_west()
