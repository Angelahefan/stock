"""
datapai_portfolio_snapshots — Daily portfolio snapshot computation.
Runs at 03:30 UTC daily (after signal performance, after all EOD).
"""
from datetime import datetime, timedelta
import pendulum
from airflow.decorators import dag
from airflow.timetables.trigger import CronTriggerTimetable
from datapai_common import DEFAULT_ARGS, datapai_bash_task

UTC = pendulum.timezone("UTC")


@dag(
    dag_id="datapai_portfolio_snapshots",
    default_args=DEFAULT_ARGS,
    timetable=CronTriggerTimetable("30 3 * * *", timezone=UTC),
    start_date=datetime(2026, 3, 27, tzinfo=UTC),
    catchup=False,
    tags=["datapai", "portfolio"],
    max_active_runs=1,
)
def datapai_portfolio_snapshots():
    compute = datapai_bash_task(
        "compute_portfolio_snapshots",
        "run_compute_portfolio_snapshots.sh",
        execution_timeout=timedelta(minutes=15),
    )
    compute

datapai_portfolio_snapshots()
