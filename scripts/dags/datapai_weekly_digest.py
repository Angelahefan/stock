"""
datapai_weekly_digest — Weekly portfolio summary email via AWS SES.
Runs every Saturday at 09:00 UTC.

Sends each subscribed user a summary of their watchlist:
stock name, price, weekly change%, AI signal, key EMA level.
Respects user language preference for i18n.
"""
from datetime import datetime, timedelta
import pendulum
from airflow.decorators import dag
from airflow.timetables.trigger import CronTriggerTimetable
from datapai_common import DEFAULT_ARGS, datapai_bash_task

UTC = pendulum.timezone("UTC")


@dag(
    dag_id="datapai_weekly_digest",
    default_args={**DEFAULT_ARGS, "retries": 1, "execution_timeout": timedelta(minutes=30)},
    timetable=CronTriggerTimetable("0 9 * * 6", timezone=UTC),
    start_date=datetime(2026, 3, 28, tzinfo=UTC),
    catchup=False,
    tags=["datapai", "email", "digest", "notification", "weekly"],
    max_active_runs=1,
    is_paused_upon_creation=True,  # disabled by default
)
def datapai_weekly_digest():
    digest = datapai_bash_task(
        "send_weekly_digest",
        "run_send_weekly_digest.sh",
        execution_timeout=timedelta(minutes=30),
        retries=1,
    )
    digest


datapai_weekly_digest()
