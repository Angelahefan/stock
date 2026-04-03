"""
datapai_user_backtests — Nightly backtest runner for Personalized Agent Studio.
Picks up strategies with status='pending' or config changed, runs backtests,
stores results in usr_backtest_results.

Schedule: 02:00 UTC daily (after all EOD jobs complete)
Max: 50 strategies per run, 5-min timeout per strategy
"""
from datetime import datetime, timedelta
import pendulum
from airflow.decorators import dag
from datapai_common import DEFAULT_ARGS, datapai_bash_task

UTC = pendulum.timezone("UTC")


@dag(
    dag_id="datapai_user_backtests",
    default_args=DEFAULT_ARGS,
    schedule="0 2 * * *",  # 02:00 UTC daily
    start_date=datetime(2026, 3, 28, tzinfo=UTC),
    catchup=False,
    tags=["datapai", "studio", "backtest"],
    max_active_runs=1,
)
def datapai_user_backtests():
    run = datapai_bash_task(
        "run_user_backtests",
        "run_user_backtests.sh",
        args="--max 50",
        execution_timeout=timedelta(hours=4),
        retries=1,
    )
    run


datapai_user_backtests()
