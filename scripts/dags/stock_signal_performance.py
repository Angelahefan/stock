"""
stock_signal_performance — Daily signal performance computation.
Runs at 03:00 UTC (after all markets closed).
"""
from datetime import datetime, timedelta
import pendulum
from airflow.decorators import dag
from airflow.timetables.trigger import CronTriggerTimetable
from stock_common import DEFAULT_ARGS, stock_bash_task

UTC = pendulum.timezone("UTC")


@dag(
    dag_id="stock_signal_performance",
    default_args=DEFAULT_ARGS,
    timetable=CronTriggerTimetable("0 3 * * *", timezone=UTC),
    start_date=datetime(2026, 3, 27, tzinfo=UTC),
    catchup=False,
    tags=["datapai", "signal", "performance"],
    max_active_runs=1,
)
def stock_signal_performance():
    compute = stock_bash_task(
        "compute_signal_performance",
        "run_compute_signal_performance.sh",
        execution_timeout=timedelta(minutes=30),
    )
    compute

stock_signal_performance()
