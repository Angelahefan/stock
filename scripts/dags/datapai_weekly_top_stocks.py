"""
datapai_weekly_top_stocks — Weekly refresh of market_top_stocks from index constituents.

Reads from market_index_constituents (manually curated ref table),
populates market_top_stocks (used by screener, synthesis, TA/FA pipelines).

Runs every Sunday at 06:00 UTC (before Monday market opens).
"""
from datetime import datetime, timedelta
import pendulum
from airflow.decorators import dag
from airflow.timetables.trigger import CronTriggerTimetable
from datapai_common import DEFAULT_ARGS, datapai_bash_task

UTC_TZ = pendulum.timezone("UTC")


@dag(
    dag_id="datapai_weekly_top_stocks",
    default_args=DEFAULT_ARGS,
    timetable=CronTriggerTimetable("0 6 * * 0", timezone=UTC_TZ),
    start_date=datetime(2026, 3, 31, tzinfo=UTC_TZ),
    catchup=False,
    tags=["datapai", "weekly", "ref-data"],
    max_active_runs=1,
)
def datapai_weekly_top_stocks():
    # Step 1: Refresh index constituent lists (S&P 500, Nikkei 225, TradingView top by market cap)
    refresh_constituents = datapai_bash_task(
        "refresh_index_constituents",
        "run_refresh_index_constituents.sh",
        execution_timeout=timedelta(minutes=10),
    )
    # Step 2: Rebuild market_top_stocks from refreshed constituents + enrich with market data
    rebuild_top_stocks = datapai_bash_task(
        "rebuild_top_stocks",
        "run_compute_market_top_stocks.sh",
        execution_timeout=timedelta(minutes=10),
    )
    refresh_constituents >> rebuild_top_stocks

datapai_weekly_top_stocks()
