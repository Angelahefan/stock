"""
datapai_recon_asia — Asia + ASX EOD data reconciliation.
Runs after all Asia/ASX EOD jobs complete.
Checks last 5 trading days for gaps, backfills automatically if found.

Schedule: 19:00 WIB (12:00 UTC) Mon-Fri
  - Latest Asia close: IDX 16:45 WIB → EOD job finishes ~18:00 WIB
  - 1hr buffer → recon at 19:00 WIB
"""
from datetime import datetime, timedelta
import pendulum
from airflow.decorators import dag
from datapai_common import DEFAULT_ARGS, datapai_bash_task

JKT_TZ = pendulum.timezone("Asia/Jakarta")


@dag(
    dag_id="datapai_recon_asia",
    default_args=DEFAULT_ARGS,
    schedule="0 19 * * 1-5",  # 19:00 WIB Mon-Fri
    start_date=datetime(2026, 3, 26, tzinfo=JKT_TZ),
    catchup=False,
    tags=["datapai", "recon", "asia"],
    max_active_runs=1,
)
def datapai_recon_asia():
    recon = datapai_bash_task(
        "recon_asia_eod",
        "recon_eod_asia.sh",
        execution_timeout=timedelta(hours=3),
        retries=1,
    )
    recon


datapai_recon_asia()
