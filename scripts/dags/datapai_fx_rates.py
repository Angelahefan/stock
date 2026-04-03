"""
datapai_fx_rates — Daily FX rate refresh from Yahoo Finance.
Runs daily at 00:30 UTC (after all major markets close).
Fetches USD-based exchange rates for AUD, HKD, CNY, VND, THB, MYR, IDR, GBP, GBX.
"""
from datetime import datetime, timedelta
import pendulum
from airflow.decorators import dag
from airflow.timetables.trigger import CronTriggerTimetable
from datapai_common import DEFAULT_ARGS, datapai_bash_task

UTC = pendulum.timezone("UTC")


@dag(
    dag_id="datapai_fx_rates",
    default_args={**DEFAULT_ARGS, "retries": 3, "execution_timeout": timedelta(minutes=15)},
    timetable=CronTriggerTimetable("30 0 * * *", timezone=UTC),
    start_date=datetime(2026, 3, 28, tzinfo=UTC),
    catchup=False,
    tags=["datapai", "fx", "rates", "currency"],
    max_active_runs=1,
    is_paused_upon_creation=False,
)
def datapai_fx_rates():
    refresh = datapai_bash_task(
        "refresh_fx_rates",
        "refresh_fx_rates.sh",
        execution_timeout=timedelta(minutes=15),
        retries=3,
    )
    refresh


datapai_fx_rates()
