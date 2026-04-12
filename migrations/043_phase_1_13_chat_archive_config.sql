-- ─────────────────────────────────────────────────────────────────────────
-- Phase 1.13 — Chat history archival configuration + audit log table
-- ─────────────────────────────────────────────────────────────────────────
-- Applied: 2026-04-12
-- Target:  datapai_framework_db (port 5433), datapai schema
--
-- This migration has two parts:
--   1. sys_common_config rows for chat_archive (retention window, S3 target, kill switch)
--   2. sys_archive_log table for DAG run audit trail
--
-- Run via:
--   docker exec -i datapai_framework_db psql -U postgres -d datapai_auth_db \
--     < migrations/043_phase_1_13_chat_archive_config.sql
--
-- Related:
--   - docs/phase-journals/2026-04-12-phase-1.13-chat-audit-design.md
--   - Standing rule: ~/.claude/.../memory/feedback_ai_governance_audit.md
-- ─────────────────────────────────────────────────────────────────────────

-- ╔══ 1. sys_common_config rows for chat archival ═══════════════════════════╗

INSERT INTO datapai.sys_common_config (config_type, config_key, config_value, description, created_by)
VALUES
  ('chat_archive', 'hot_retention_days', '90',
   'Number of days chat messages stay in Postgres before archival to S3. Tune via UPDATE. Rule: AI governance (feedback_ai_governance_audit.md).',
   'phase_1_13_2026-04-12'),

  ('chat_archive', 'archive_bucket', 'codepais3',
   'S3 bucket name for chat history cold storage. Existing bucket in ap-southeast-2, EC2 IAM role has access.',
   'phase_1_13_2026-04-12'),

  ('chat_archive', 'archive_prefix_stock', 'datapai-archive/stock/chat_history',
   'S3 key prefix for stock-vertical chat history. Partitioned by year/month/day under this prefix.',
   'phase_1_13_2026-04-12'),

  ('chat_archive', 'archive_prefix_health', 'datapai-archive/health/chat_history',
   'S3 key prefix for healthcare-vertical chat history. Reserved for when the healthcare copilot ships.',
   'phase_1_13_2026-04-12'),

  ('chat_archive', 'archive_enabled', 'true',
   'Master kill-switch for the archival DAG. Set to false to pause archival without disabling the DAG entirely.',
   'phase_1_13_2026-04-12'),

  ('chat_archive', 'archive_safety_overlap_days', '7',
   'Safety overlap: keep rows this many days beyond hot_retention_days in Postgres even after S3 upload, as a belt-and-braces backup. Deleted on the NEXT weekly run if S3 upload was verified.',
   'phase_1_13_2026-04-12')
ON CONFLICT (config_type, config_key) DO UPDATE SET
  config_value = EXCLUDED.config_value,
  description  = EXCLUDED.description,
  updated_at   = NOW();


-- ╔══ 2. sys_archive_log table for DAG run audit trail ══════════════════════╗

CREATE TABLE IF NOT EXISTS datapai.sys_archive_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          TEXT NOT NULL,                  -- Airflow run id or manual invocation tag
    domain          TEXT NOT NULL,                  -- 'stock' | 'health' | ...
    source_table    TEXT NOT NULL,                  -- 'chat_messages', 'chat_sessions', etc.
    s3_bucket       TEXT NOT NULL,
    s3_key_prefix   TEXT NOT NULL,                  -- datapai-archive/<domain>/chat_history/year=YYYY/month=MM/day=DD/
    rows_exported   INTEGER NOT NULL DEFAULT 0,
    rows_deleted    INTEGER NOT NULL DEFAULT 0,
    bytes_uploaded  BIGINT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','success','failed','skipped')),
    error_detail    TEXT
);

CREATE INDEX IF NOT EXISTS idx_sys_archive_log_domain_table_started
  ON datapai.sys_archive_log(domain, source_table, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_sys_archive_log_status_started
  ON datapai.sys_archive_log(status, started_at DESC)
  WHERE status IN ('running','failed');

COMMENT ON TABLE datapai.sys_archive_log IS
  'Audit trail for cold-storage archival DAG runs. Each row represents one archival batch (typically one day of chat_messages exported to S3 Parquet). Query by (domain, source_table) for a clean history. Rule: AI governance — every archival action must leave a paper trail.';

-- Ensure the auth_service role can read + write for auth-be integration (future)
GRANT SELECT, INSERT, UPDATE ON datapai.sys_archive_log TO auth_service;


-- ╔══ 3. Indexes on chat tables for efficient archival query ════════════════╗
-- The weekly archival DAG will do:
--   SELECT * FROM chat_messages WHERE created_at < NOW() - interval '90 days'
-- Make sure this is indexed.

CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at
  ON datapai.chat_messages(created_at);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated_at
  ON datapai.chat_sessions(updated_at);


-- ╔══ 4. Verification ═══════════════════════════════════════════════════════╗

\echo
\echo === chat_archive config rows ===
SELECT config_key, config_value FROM datapai.sys_common_config
WHERE config_type = 'chat_archive' ORDER BY config_key;

\echo
\echo === sys_archive_log structure ===
SELECT column_name, data_type, is_nullable FROM information_schema.columns
WHERE table_schema='datapai' AND table_name='sys_archive_log' ORDER BY ordinal_position;

\echo
\echo === new indexes on chat tables ===
SELECT indexname FROM pg_indexes
WHERE schemaname='datapai' AND tablename IN ('chat_messages','chat_sessions')
ORDER BY indexname;
