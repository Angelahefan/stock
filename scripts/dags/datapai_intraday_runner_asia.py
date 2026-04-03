"""
datapai_intraday_runner_asia — Consolidated Asia-Pacific intraday bar collector.
Uses --exchange ALL: runner reads active markets from datapai.market_trading_hours DB table.
Auto-detects which markets are currently open and refreshes them sequentially.
Triggers at 09:00 HKT (earliest Asia open), runs until all markets close.

DB-driven: to add a new market, just INSERT into market_trading_hours — no DAG change needed.
"""
from datetime import datetime, timedelta
import pendulum
from airflow.decorators import dag
from airflow.timetables.trigger import CronTriggerTimetable
from datapai_common import DEFAULT_ARGS, datapai_bash_task

HK_TZ = pendulum.timezone("Asia/Hong_Kong")

@dag(
    dag_id="datapai_intraday_runner_asia",
    default_args=DEFAULT_ARGS,
    # ASX opens earliest (10:00 AEDT = ~23:00 UTC prev day / 07:00 HKT)
    # Start at 07:00 HKT to catch ASX open. Runner auto-detects which markets are open.
    timetable=CronTriggerTimetable("0 7 * * 1-5", timezone=HK_TZ),
    start_date=datetime(2026, 3, 30, tzinfo=HK_TZ),
    catchup=False,
    tags=["datapai", "intraday", "asia", "runner", "consolidated"],
    max_active_runs=1,
)
def datapai_intraday_runner_asia():
    datapai_bash_task(
        "intraday_runner_asia",
        "intraday_runner.sh",
        args="--exchange ALL",
        execution_timeout=timedelta(hours=12),
        retries=1,
    )

datapai_intraday_runner_asia()
