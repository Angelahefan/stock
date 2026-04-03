"""
datapai_fundamentals_weekly — Weekly bulk fundamentals crawl for ALL exchanges.
Runs Saturday morning UTC (no market interference).

Pass 1: Yahoo batch quote API (~2 min per 5000 tickers) — basic fundamentals
Pass 2: yfinance .info for priority stocks (~5 min) — full fundamentals
"""
from datetime import datetime, timedelta
import pendulum
from airflow.decorators import dag
from datapai_common import DEFAULT_ARGS, datapai_bash_task

UTC = pendulum.timezone("UTC")


@dag(
    dag_id="datapai_fundamentals_weekly",
    default_args=DEFAULT_ARGS,
    schedule="0 6 * * 6",  # Saturday 06:00 UTC
    start_date=datetime(2026, 3, 28, tzinfo=UTC),
    catchup=False,
    tags=["datapai", "fundamentals", "weekly"],
    max_active_runs=1,
)
def datapai_fundamentals_weekly():
    crawl = datapai_bash_task(
        "crawl_fundamentals_all",
        "crawl_fundamentals_weekly.sh",
        args="--exchange all --threads 10",
        execution_timeout=timedelta(hours=2),
        retries=1,
    )
    crawl


datapai_fundamentals_weekly()
