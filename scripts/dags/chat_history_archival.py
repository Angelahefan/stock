"""
chat_history_archival — Weekly chat audit-trail archival to S3.

Runs every Sunday at 02:00 UTC (low-traffic window) to move chat messages
older than `hot_retention_days` (default 90) out of framework_db and into
the `codepais3` S3 bucket as Parquet files, partitioned by year/month/day.

Why this DAG exists — AI Governance (Phase 1.13, 2026-04-12)
────────────────────────────────────────────────────────────
Every AI chat at DATAP.AI must be auditable forever: hot tier in Postgres
for live UI, cold tier in S3 as Parquet for audit / back-tracking / legal.
No black-box AI. This rule applies to stock AND healthcare verticals.

What this DAG does (one task, idempotent)
─────────────────────────────────────────
1. Loads config (bucket, prefix, retention, enabled flag) from
   datapai.sys_common_config where config_type='chat_archive'.
2. Finds chat_messages.created_at < (NOW - hot_retention_days).
3. Groups by UTC day; one Parquet file per day under
     s3://<bucket>/<prefix>/year=YYYY/month=MM/day=DD/part-00000-<run_id>.parquet
4. Verifies each upload by re-reading the Parquet file and checking
   row count matches the source query.
5. Deletes the archived rows from Postgres (unless --dry-run).
6. Logs every run to datapai.sys_archive_log.

Tunables (DB-driven, no code change required):
  hot_retention_days         (default 90)
  archive_bucket             (default codepais3)
  archive_prefix_stock       (default stock/raw/chat_history)
  archive_enabled            (default true)
  archive_safety_overlap_days (default 7 — unused, reserved for future)

Rollback: the Parquet files are canonical — if a run deletes and a human
later wants the rows back, they can be re-read from S3 at any time.
"""
from datetime import datetime, timedelta
import pendulum
from airflow.decorators import dag
from airflow.timetables.trigger import CronTriggerTimetable
from stock_common import DEFAULT_ARGS, stock_bash_task

UTC = pendulum.timezone("UTC")


@dag(
    dag_id="chat_history_archival",
    default_args={
        **DEFAULT_ARGS,
        "retries": 1,
        "execution_timeout": timedelta(minutes=45),
    },
    # Every Sunday at 02:00 UTC — user traffic is minimal then.
    timetable=CronTriggerTimetable("0 2 * * 0", timezone=UTC),
    start_date=datetime(2026, 4, 1, tzinfo=UTC),
    catchup=False,
    tags=["datapai", "audit", "governance", "archive", "weekly", "s3", "parquet"],
    max_active_runs=1,
    # Paused on creation — enable manually after first dry-run passes.
    is_paused_upon_creation=True,
)
def chat_history_archival():
    archive = stock_bash_task(
        "archive_chat_history_to_s3",
        "run_archive_chat_history_to_s3.sh",
        execution_timeout=timedelta(minutes=45),
        retries=1,
    )
    archive


chat_history_archival()
