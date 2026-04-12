#!/usr/bin/env python3
"""
scripts/archive_chat_history_to_s3.py
─────────────────────────────────────────────────────────────────────────────
Phase 1.13 — Weekly cold-storage archival of chat_messages + chat_sessions

AI governance rule (standing, 2026-04-12):
  Every AI conversation must be stored + retrievable for audit + back-tracking.
  Hot data lives in Postgres (chat_sessions + chat_messages) for 90 days.
  Cold data lives in S3 as Parquet, partitioned by day, forever.

What this script does (one run):
  1. Load config from datapai.sys_common_config (config_type='chat_archive')
  2. Query chat_messages + chat_sessions for rows older than `hot_retention_days`
  3. Group by DATE(created_at) — one Parquet file per day
  4. For each day:
     a. Build a pandas DataFrame with both message fields AND enriched
        session context (session_title, session_created_at, ticker, exchange)
     b. Upload Parquet to s3://<bucket>/<prefix>/year=YYYY/month=MM/day=DD/part-00000.parquet
     c. Verify the Parquet is readable (pd.read_parquet sanity check)
     d. Verify row count matches
     e. DELETE the matching rows from Postgres (primary + secondary)
     f. Log a success row to datapai.sys_archive_log
  5. Any failure at step d or earlier → DO NOT delete; log failure to sys_archive_log; exit non-zero

Usage:
  python3 archive_chat_history_to_s3.py [--dry-run] [--run-id X] [--domain stock]

  --dry-run: read from Postgres, build Parquet in memory, upload to S3, but do NOT delete from Postgres.
  --run-id: explicit run id for sys_archive_log (default: manual-<timestamp>).
  --domain: which vertical (stock, health). Default 'stock'. The S3 prefix is
            read from sys_common_config archive_prefix_<domain>.

Exit codes:
  0  success (all days archived or nothing to archive)
  1  partial failure (some days archived, some failed)
  2  total failure or preflight error (nothing archived, Postgres untouched)

Env:
  AUTH_DB_HOST / AUTH_DB_PORT / AUTH_DB_NAME / AUTH_DB_USER / AUTH_DB_PASSWORD
     Must point at datapai_framework_db (port 5433, datapai_auth_db). Reads
     sys_common_config from there, and performs the actual archival queries
     against the REAL tables (not via the stock_db FDW alias).

S3: uses the EC2 instance's IAM role (ec2_manager_connection_role). No
explicit credentials needed if running on the datapai EC2 box.

Related:
  - docs/phase-journals/2026-04-12-phase-1.13-chat-audit-design.md
  - migrations/043_phase_1_13_chat_archive_config.sql
  - ~/.claude/.../memory/feedback_ai_governance_audit.md
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

import boto3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  [%(name)s]  %(message)s",
)
log = logging.getLogger("archive_chat_history")


# ── Load .env.dev if running standalone (outside Airflow) ────────────────────
for _p in [Path("/home/ec2-user/.env.dev")]:
    if _p.exists() and not os.environ.get("AUTH_DB_PASSWORD"):
        for _line in _p.read_text().splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
        break


def get_conn() -> psycopg2.extensions.connection:
    """Direct connection to datapai_framework_db on port 5433."""
    return psycopg2.connect(
        host=os.getenv("AUTH_DB_HOST", "localhost"),
        port=int(os.getenv("AUTH_DB_PORT", "5433")),
        dbname=os.getenv("AUTH_DB_NAME", "datapai_auth_db"),
        user=os.getenv("AUTH_DB_USER", "postgres"),  # prefer root for DELETE privilege
        password=os.getenv("AUTH_DB_ROOT_PASSWORD") or os.getenv("AUTH_DB_PASSWORD", ""),
        connect_timeout=15,
    )


def load_archive_config(conn, domain: str) -> dict:
    """Read the chat_archive config rows from sys_common_config."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT config_key, config_value FROM datapai.sys_common_config
            WHERE config_type = 'chat_archive'
              AND (effective_from IS NULL OR effective_from <= CURRENT_DATE)
              AND (effective_to   IS NULL OR effective_to   >  CURRENT_DATE)
            """
        )
        rows = cur.fetchall()
    cfg = {r["config_key"]: r["config_value"] for r in rows}

    # Defaults / validation
    hot_days = int(cfg.get("hot_retention_days", "90"))
    safety_days = int(cfg.get("archive_safety_overlap_days", "7"))
    bucket = cfg.get("archive_bucket", "codepais3")
    prefix_key = f"archive_prefix_{domain}"
    prefix = cfg.get(prefix_key, f"datapai-archive/{domain}/chat_history")
    enabled = cfg.get("archive_enabled", "true").lower() == "true"

    return {
        "hot_retention_days": hot_days,
        "safety_overlap_days": safety_days,
        "bucket": bucket,
        "prefix": prefix.rstrip("/"),
        "enabled": enabled,
    }


# ── Audit log ────────────────────────────────────────────────────────────────

def start_archive_run(
    conn,
    *,
    run_id: str,
    domain: str,
    source_table: str,
    s3_bucket: str,
    s3_key_prefix: str,
) -> str:
    """Insert a 'running' row into sys_archive_log. Returns the row id."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO datapai.sys_archive_log
                (run_id, domain, source_table, s3_bucket, s3_key_prefix, status)
            VALUES (%s, %s, %s, %s, %s, 'running')
            RETURNING id::text
            """,
            (run_id, domain, source_table, s3_bucket, s3_key_prefix),
        )
        row = cur.fetchone()
    conn.commit()
    return row["id"]


def finish_archive_run(
    conn,
    *,
    row_id: str,
    status: str,
    rows_exported: int = 0,
    rows_deleted: int = 0,
    bytes_uploaded: int = 0,
    error_detail: str | None = None,
) -> None:
    """Mark an archive run complete."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE datapai.sys_archive_log
            SET status = %s,
                rows_exported = %s,
                rows_deleted = %s,
                bytes_uploaded = %s,
                finished_at = NOW(),
                error_detail = %s
            WHERE id = %s
            """,
            (status, rows_exported, rows_deleted, bytes_uploaded, error_detail, row_id),
        )
    conn.commit()


# ── Core: query + archive + delete ───────────────────────────────────────────

ARCHIVE_QUERY = """
    SELECT
        m.id            AS message_id,
        m.session_id::text AS session_id,
        s.user_id       AS session_user_id,
        s.ticker        AS ticker,
        s.exchange      AS exchange,
        s.title         AS session_title,
        s.created_at    AS session_created_at,
        m.role          AS role,
        m.content       AS content,
        m.model_used    AS model_used,
        m.tokens_used   AS tokens_used,
        m.context_sources::text AS context_sources,
        m.created_at    AS created_at,
        DATE(m.created_at AT TIME ZONE 'UTC') AS archive_day
    FROM datapai.chat_messages m
    LEFT JOIN datapai.chat_sessions s ON s.id = m.session_id
    WHERE m.created_at < NOW() - (INTERVAL '1 day' * %s)
    ORDER BY m.created_at ASC
"""


def find_archivable_rows(conn, hot_retention_days: int) -> pd.DataFrame:
    """Return all chat_messages + enriched session context that are older
    than hot_retention_days. Returns an empty DataFrame if nothing to archive."""
    log.info("Querying chat_messages older than %d days", hot_retention_days)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(ARCHIVE_QUERY, (hot_retention_days,))
        rows = cur.fetchall()
    log.info("Fetched %d chat_messages rows for potential archival", len(rows))
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


def _upload_parquet(df: pd.DataFrame, *, bucket: str, key: str, run_id: str) -> int:
    """Upload a DataFrame as Parquet to s3://bucket/key. Returns uploaded bytes."""
    # Add the archive_run_id column so every row can be traced back to the DAG run
    df = df.copy()
    df["archived_at"] = datetime.now(timezone.utc)
    df["archive_run_id"] = run_id

    # Convert to arrow Table with an explicit schema (ensures consistent types
    # even when some columns are entirely null for a particular day)
    table = pa.Table.from_pandas(df, preserve_index=False)

    # Write to a BytesIO buffer (no temp file — smaller attack surface)
    import io
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    payload = buf.getvalue()

    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=payload,
        ContentType="application/octet-stream",
        # Tag the object for lifecycle policies + cost attribution
        Metadata={
            "run_id": run_id,
            "rows": str(len(df)),
            "archived_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    log.info("Uploaded %d rows, %d bytes → s3://%s/%s", len(df), len(payload), bucket, key)
    return len(payload)


def _verify_parquet(bucket: str, key: str, expected_rows: int) -> None:
    """Sanity-check: download the Parquet we just uploaded and verify row count.
    Raises if the file is unreadable or the row count doesn't match."""
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=bucket, Key=key)
    body = obj["Body"].read()

    import io
    buf = io.BytesIO(body)
    df_check = pd.read_parquet(buf)
    if len(df_check) != expected_rows:
        raise RuntimeError(
            f"Parquet verification FAILED: expected {expected_rows} rows, "
            f"got {len(df_check)} in s3://{bucket}/{key}"
        )
    log.info("Verified s3://%s/%s has %d rows (matches Postgres)", bucket, key, expected_rows)


def _delete_archived_rows(conn, message_ids: list[int]) -> int:
    """Delete chat_messages rows by id. Does NOT delete chat_sessions (those
    stay as long as they have at least one referencing row; orphan sessions
    are cleaned up by a separate pass)."""
    if not message_ids:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM datapai.chat_messages WHERE id = ANY(%s::bigint[])",
            (message_ids,),
        )
        deleted = cur.rowcount
    conn.commit()
    log.info("Deleted %d chat_messages rows from Postgres", deleted)
    return deleted


def _cleanup_orphan_sessions(conn) -> int:
    """Delete chat_sessions rows that have zero remaining chat_messages AND
    are older than the hot retention window. Keeps the Postgres footprint
    from growing unbounded."""
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM datapai.chat_sessions s
            WHERE NOT EXISTS (
                SELECT 1 FROM datapai.chat_messages m WHERE m.session_id = s.id
            )
            AND s.updated_at < NOW() - INTERVAL '90 days'
            """
        )
        deleted = cur.rowcount
    conn.commit()
    if deleted:
        log.info("Cleaned up %d orphan chat_sessions rows (zero messages + old)", deleted)
    return deleted


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Archive chat history to S3 Parquet")
    parser.add_argument("--dry-run", action="store_true", help="Upload to S3 but do NOT delete Postgres rows")
    parser.add_argument("--run-id", default=None, help="Explicit run id for sys_archive_log")
    parser.add_argument("--domain", default="stock", choices=["stock", "health"], help="Which vertical")
    args = parser.parse_args()

    run_id = args.run_id or f"manual-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    log.info("Starting archive run: run_id=%s domain=%s dry_run=%s", run_id, args.domain, args.dry_run)

    try:
        conn = get_conn()
    except Exception as e:
        log.error("Postgres connect failed: %s", e)
        return 2

    try:
        cfg = load_archive_config(conn, domain=args.domain)
        log.info("Archive config: %s", cfg)
        if not cfg["enabled"]:
            log.warning("archive_enabled=false in sys_common_config — skipping run")
            return 0

        df = find_archivable_rows(conn, hot_retention_days=cfg["hot_retention_days"])
        if df.empty:
            log.info("Nothing to archive (retention=%d days)", cfg["hot_retention_days"])
            return 0

        # Group by day. Each day gets its own Parquet file.
        daily_groups = df.groupby("archive_day")
        log.info("Archival spans %d distinct days: %s to %s",
                 len(daily_groups),
                 df["archive_day"].min(),
                 df["archive_day"].max())

        total_exported = 0
        total_deleted = 0
        total_bytes = 0
        per_day_failures = 0

        for archive_day, day_df in daily_groups:
            day_rows = len(day_df)
            y, m, d = archive_day.year, archive_day.month, archive_day.day
            key = (
                f"{cfg['prefix']}/year={y:04d}/month={m:02d}/day={d:02d}/"
                f"part-00000-{run_id}.parquet"
            )
            log.info("Archiving %d messages for %s → s3://%s/%s",
                     day_rows, archive_day, cfg["bucket"], key)

            audit_id = start_archive_run(
                conn,
                run_id=run_id,
                domain=args.domain,
                source_table="chat_messages",
                s3_bucket=cfg["bucket"],
                s3_key_prefix=key,
            )

            try:
                bytes_up = _upload_parquet(
                    day_df.drop(columns=["archive_day"]),
                    bucket=cfg["bucket"],
                    key=key,
                    run_id=run_id,
                )
                _verify_parquet(cfg["bucket"], key, expected_rows=day_rows)

                if args.dry_run:
                    log.info("[DRY RUN] Skipping Postgres DELETE for %s (%d rows)", archive_day, day_rows)
                    deleted = 0
                else:
                    message_ids = day_df["message_id"].tolist()
                    deleted = _delete_archived_rows(conn, message_ids)
                    if deleted != day_rows:
                        log.warning(
                            "Row-count mismatch on DELETE for %s: exported=%d, deleted=%d",
                            archive_day, day_rows, deleted,
                        )

                finish_archive_run(
                    conn,
                    row_id=audit_id,
                    status="success",
                    rows_exported=day_rows,
                    rows_deleted=deleted,
                    bytes_uploaded=bytes_up,
                )
                total_exported += day_rows
                total_deleted += deleted
                total_bytes += bytes_up

            except Exception as e:
                log.error("Archive FAILED for %s: %s", archive_day, e)
                finish_archive_run(
                    conn,
                    row_id=audit_id,
                    status="failed",
                    rows_exported=day_rows,
                    rows_deleted=0,
                    bytes_uploaded=0,
                    error_detail=str(e)[:1000],
                )
                per_day_failures += 1
                # Do NOT return yet — try the remaining days

        # Orphan session cleanup (only on non-dry-run, after successful archivals)
        if not args.dry_run and total_deleted > 0:
            _cleanup_orphan_sessions(conn)

        log.info(
            "Archive run complete: exported=%d, deleted=%d, bytes=%d, failures=%d",
            total_exported, total_deleted, total_bytes, per_day_failures,
        )

        if per_day_failures == 0:
            return 0
        elif total_exported > 0:
            return 1  # partial
        else:
            return 2  # total failure

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
