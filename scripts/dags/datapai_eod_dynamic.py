"""
datapai_eod_dynamic — DB-driven EOD DAGs for ALL markets.

ONE file generates separate DAGs per market, each running independently.
Market config (schedule, timezone) comes from datapai.market_trading_hours.

Chain per market:
  refresh_daily → sync_close → fundamental_lite → ta_daily → [ta_weekly, ta_monthly] → screener_metrics

US/ASX get extra steps: eod_rollup, parallel refresh workers, fundamental, multi_factor.

Adding a new market = INSERT into market_trading_hours → DAG auto-appears.
"""
from datetime import datetime, timedelta
import pendulum
from airflow.decorators import dag
from airflow.timetables.trigger import CronTriggerTimetable
from datapai_common import DEFAULT_ARGS, datapai_bash_task

# Markets with extra steps (full pipeline)
_FULL_PIPELINE = {"US", "ASX"}
_NUM_REFRESH_WORKERS_US = 3


def _load_markets():
    """Load active markets from DB. Falls back to hardcoded if DB unavailable."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost", port=5432, dbname="postgres", user="postgres", password="postgres",
            options="-c search_path=datapai,public", connect_timeout=5,
        )
        cur = conn.cursor()
        cur.execute("""
            SELECT exchange, timezone, close_hour, close_minute
            FROM datapai.market_trading_hours WHERE is_active = TRUE
        """)
        markets = []
        for ex, tz, ch, cm in cur.fetchall():
            markets.append({"exchange": ex, "timezone": tz, "close_hour": ch, "close_minute": cm})
        cur.close()
        conn.close()
        return markets
    except Exception:
        # Fallback — minimal set
        return [
            {"exchange": "US", "timezone": "America/New_York", "close_hour": 16, "close_minute": 0},
            {"exchange": "ASX", "timezone": "Australia/Sydney", "close_hour": 16, "close_minute": 0},
        ]


def _create_eod_dag(market: dict):
    """Create one EOD DAG for a single market."""
    exchange = market["exchange"]
    tz = pendulum.timezone(market["timezone"])
    ex_lower = exchange.lower()

    # Schedule: 10 minutes after market close
    cron_minute = (market["close_minute"] + 10) % 60
    cron_hour = market["close_hour"] + ((market["close_minute"] + 10) // 60)

    @dag(
        dag_id=f"datapai_{ex_lower}_eod",
        default_args=DEFAULT_ARGS,
        timetable=CronTriggerTimetable(f"{cron_minute} {cron_hour} * * 1-5", timezone=tz),
        start_date=datetime(2026, 3, 18, tzinfo=tz),
        catchup=False,
        tags=["datapai", ex_lower, "eod", "dynamic"],
        max_active_runs=1,
    )
    def eod_pipeline():
        # ── Common steps for ALL markets ──────────────────────────────

        if exchange == "US":
            # US: 3 parallel refresh workers (6,700+ tickers)
            refresh_workers = []
            for i in range(_NUM_REFRESH_WORKERS_US):
                w = datapai_bash_task(
                    f"refresh_{ex_lower}_batch_{i}",
                    "refresh_ohlcv_daily_us.sh",
                    args=f"--batch-num {i} --total-batches {_NUM_REFRESH_WORKERS_US}",
                    execution_timeout=timedelta(minutes=45), retries=2,
                )
                refresh_workers.append(w)
            refresh_step = refresh_workers
        else:
            # All other markets: single refresh
            refresh_step = datapai_bash_task(
                f"refresh_daily_{ex_lower}",
                f"refresh_ohlcv_daily_{ex_lower}.sh" if exchange != "ASX" else "refresh_ohlcv_daily_asx.sh",
                execution_timeout=timedelta(hours=2), retries=2,
            )

        sync_close = datapai_bash_task(
            f"sync_close_to_intraday_{ex_lower}", "run_sync_close_to_intraday.sh",
            args=f"--exchange {exchange}", execution_timeout=timedelta(minutes=5),
        )
        fundamental_lite = datapai_bash_task(
            f"compute_fundamental_lite_{ex_lower}", "run_compute_fundamental_lite.sh",
            args=f"--exchange {exchange}", execution_timeout=timedelta(hours=2),
        )
        ta_daily = datapai_bash_task(
            f"compute_ta_daily_{ex_lower}", "run_compute_ta_daily.sh",
            args=f"--exchange {exchange}", execution_timeout=timedelta(minutes=30),
        )
        ta_weekly = datapai_bash_task(
            f"compute_ta_weekly_{ex_lower}", "run_compute_ta_weekly.sh",
            args=f"--exchange {exchange}", execution_timeout=timedelta(minutes=30),
        )
        ta_monthly = datapai_bash_task(
            f"compute_ta_monthly_{ex_lower}", "run_compute_ta_monthly.sh",
            args=f"--exchange {exchange}", execution_timeout=timedelta(minutes=30),
        )
        screener_metrics = datapai_bash_task(
            f"compute_screener_{ex_lower}", "run_compute_screener_us.sh",
            args=f"--exchange {exchange}", execution_timeout=timedelta(minutes=10),
        )

        # Common chain
        refresh_step >> sync_close >> fundamental_lite >> ta_daily >> [ta_weekly, ta_monthly] >> screener_metrics

        # ── Extra steps for US/ASX (full pipeline) ────────────────────
        if exchange in _FULL_PIPELINE:
            fundamental = datapai_bash_task(
                f"compute_fundamental_{ex_lower}", "run_compute_fundamental.sh",
                args=f"--exchange {exchange}", execution_timeout=timedelta(hours=2),
            )
            multi_factor = datapai_bash_task(
                f"compute_multi_factor_{ex_lower}", "run_compute_multi_factor.sh",
                args=f"--exchange {exchange}", execution_timeout=timedelta(minutes=30),
            )
            screener_metrics >> fundamental >> multi_factor

    # Must set function name to avoid Airflow collision
    eod_pipeline.__name__ = f"datapai_{ex_lower}_eod"
    return eod_pipeline()


# ── Generate all DAGs ─────────────────────────────────────────────────────
for _market in _load_markets():
    _create_eod_dag(_market)
