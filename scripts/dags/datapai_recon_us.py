"""
datapai_recon_us — US EOD data reconciliation.
Runs after US EOD job completes.
Checks last 5 trading days for gaps, backfills automatically if found.

Schedule: 18:30 ET (22:30 UTC) Mon-Fri
  - US close: 16:00 ET → EOD job at 16:30 ET → finishes ~17:30 ET
  - 1hr buffer → recon at 18:30 ET
"""
from datetime import datetime, timedelta
import pendulum
from airflow.decorators import dag
from datapai_common import DEFAULT_ARGS, datapai_bash_task

NY_TZ = pendulum.timezone("America/New_York")


@dag(
    dag_id="datapai_recon_us",
    default_args=DEFAULT_ARGS,
    schedule="30 18 * * 1-5",  # 18:30 ET Mon-Fri
    start_date=datetime(2026, 3, 26, tzinfo=NY_TZ),
    catchup=False,
    tags=["datapai", "recon", "us"],
    max_active_runs=1,
)
def datapai_recon_us():
    recon = datapai_bash_task(
        "recon_us_eod",
        "recon_eod_us.sh",
        execution_timeout=timedelta(hours=2),
        retries=1,
    )
    recon


datapai_recon_us()
