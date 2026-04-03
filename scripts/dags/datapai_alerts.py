"""
datapai_alerts — Signal change alert sender (Telegram).
Runs every 30 minutes during extended market hours (Mon-Fri 06:00-22:00 UTC)
to cover Asian, European, and US sessions.

Checks for BUY/SELL signal flips on watchlist stocks, sends Telegram alerts
to subscribed users. Respects daily send limits.
"""
from datetime import datetime, timedelta
import pendulum
from airflow.decorators import dag
from airflow.timetables.trigger import CronTriggerTimetable
from datapai_common import DEFAULT_ARGS, datapai_bash_task

UTC = pendulum.timezone("UTC")


@dag(
    dag_id="datapai_alerts",
    default_args={**DEFAULT_ARGS, "retries": 1, "execution_timeout": timedelta(minutes=10)},
    timetable=CronTriggerTimetable("*/30 6-22 * * 1-5", timezone=UTC),
    start_date=datetime(2026, 3, 28, tzinfo=UTC),
    catchup=False,
    tags=["datapai", "alerts", "telegram", "notification"],
    max_active_runs=1,
    is_paused_upon_creation=True,  # disabled by default
)
def datapai_alerts():
    send = datapai_bash_task(
        "send_signal_alerts",
        "run_send_alerts.sh",
        execution_timeout=timedelta(minutes=10),
        retries=1,
    )
    send


datapai_alerts()
