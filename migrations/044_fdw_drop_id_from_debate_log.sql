-- migrations/044_fdw_drop_id_from_debate_log.sql
-- 2026-05-24 — Fix postgres_fdw NOT-NULL violation on sys_agent_debate_log.id
--
-- PROBLEM
--   Foreign table datapai.sys_agent_debate_log on consumer DBs (stock 5434,
--   health 5435, trade 5436) includes columns `id` and `created_at` in its
--   definition. Even when Python omits them from the INSERT column list,
--   postgres_fdw rewrites the statement to include EVERY column in the
--   foreign-table definition, sending NULL for `id` and `created_at`. The
--   remote base table (datapai_auth_db.datapai.sys_agent_debate_log) declares
--   both as NOT NULL with defaults (nextval / now()), but the explicit NULL
--   from the FDW wins → constraint violation → debate log silently dropped
--   for 2 months → Reflector loop never had data → compound learning blocked.
--
-- FIX (two foreign tables, same base — split read/write)
--   1. `datapai.sys_agent_debate_log` (write-side, 22 cols) — omits id +
--      created_at so postgres_fdw stops sending NULL for them and the remote
--      defaults (nextval, now()) fire normally.
--   2. `datapai.sys_agent_debate_log_full` (read-side, 24 cols) — exposes
--      id and created_at so Python can read the auto-id back after insert
--      and Reflector can UPDATE WHERE id=... Both foreign tables point at
--      the same base table on framework_db; existing 256 rows untouched.
--
-- BLAST RADIUS
--   3 consumer DBs (stock_db, health_db, trade_db). Base table in
--   datapai_auth_db on framework_db is NOT modified. Existing rows preserved.
--
-- VERIFICATION
--   After applying, the Python INSERT in agents/stock_synthesis/memory.py
--   succeeds and a fresh row appears with auto-id and auto-created_at.
--
-- ROLLBACK
--   See bottom of file — recreates the original 24-column foreign table.

-- ============================================================================
-- Apply on stock_db (port 5434)
-- ============================================================================
-- docker exec datapai_stock_db psql -U postgres -d postgres -f /tmp/044.sql

DROP FOREIGN TABLE IF EXISTS datapai.sys_agent_debate_log;

CREATE FOREIGN TABLE datapai.sys_agent_debate_log (
    ticker            varchar(20)  NOT NULL,
    exchange          varchar(10)  NOT NULL,
    debate_date       date         NOT NULL,
    debate_type       varchar(20)  NOT NULL,
    input_signals     jsonb        NOT NULL,
    bull_arguments    text[],
    bear_arguments    text[],
    risk_arguments    text[],
    pm_arguments      text[],
    direction         varchar(20)  NOT NULL,
    confidence        double precision,
    thesis            text,
    recommendation    text,
    regime            varchar(30),
    quality_tier      varchar(5),
    conflict_level    double precision,
    agent_scores      jsonb,
    actual_return_7d  double precision,
    actual_return_30d double precision,
    actual_return_90d double precision,
    was_correct       boolean,
    lessons_extracted text[]
) SERVER framework_db OPTIONS (
    schema_name 'datapai',
    table_name  'sys_agent_debate_log'
);

-- Read-side foreign table for SELECT id / UPDATE WHERE id=... (Reflector).
DROP FOREIGN TABLE IF EXISTS datapai.sys_agent_debate_log_full;

CREATE FOREIGN TABLE datapai.sys_agent_debate_log_full (
    id                integer,
    ticker            varchar(20)  NOT NULL,
    exchange          varchar(10)  NOT NULL,
    debate_date       date         NOT NULL,
    debate_type       varchar(20)  NOT NULL,
    input_signals     jsonb        NOT NULL,
    bull_arguments    text[],
    bear_arguments    text[],
    risk_arguments    text[],
    pm_arguments      text[],
    direction         varchar(20)  NOT NULL,
    confidence        double precision,
    thesis            text,
    recommendation    text,
    regime            varchar(30),
    quality_tier      varchar(5),
    conflict_level    double precision,
    agent_scores      jsonb,
    actual_return_7d  double precision,
    actual_return_30d double precision,
    actual_return_90d double precision,
    was_correct       boolean,
    lessons_extracted text[],
    created_at        timestamptz  NOT NULL
) SERVER framework_db OPTIONS (
    schema_name 'datapai',
    table_name  'sys_agent_debate_log'
);

-- ============================================================================
-- Apply on health_db (port 5435) — IDENTICAL DDL (both foreign tables)
-- ============================================================================
-- docker exec datapai_health_db psql -U postgres -d postgres -f /tmp/044.sql
-- (run the same DROP + CREATE as above)

-- ============================================================================
-- Apply on trade_db (port 5436) — IDENTICAL DDL
-- ============================================================================
-- docker exec datapai_trade_db psql -U postgres -d postgres -f /tmp/044.sql
-- (run the same DROP + CREATE as above)

-- ============================================================================
-- Verification query (run on any consumer DB after apply)
-- ============================================================================
-- Should return 22 columns (was 24 — id + created_at removed):
--   \d datapai.sys_agent_debate_log
--
-- Round-trip smoke test (run on stock_db):
--   INSERT INTO datapai.sys_agent_debate_log
--     (ticker, exchange, debate_date, debate_type, input_signals, direction)
--   VALUES ('TEST', 'ASX', CURRENT_DATE, 'synthesis', '{}'::jsonb, 'HOLD');
--   SELECT id, created_at, ticker FROM datapai.sys_agent_debate_log
--     WHERE ticker='TEST' ORDER BY id DESC LIMIT 1;
--   -- id should be non-null, created_at = now(). Cleanup:
--   DELETE FROM datapai.sys_agent_debate_log WHERE ticker='TEST';

-- ============================================================================
-- ROLLBACK (if needed, re-add id and created_at to foreign table)
-- ============================================================================
-- DROP FOREIGN TABLE IF EXISTS datapai.sys_agent_debate_log;
-- CREATE FOREIGN TABLE datapai.sys_agent_debate_log (
--     id                integer,
--     ticker            varchar(20)  NOT NULL,
--     ... (all 22 above) ...
--     created_at        timestamptz  NOT NULL
-- ) SERVER framework_db OPTIONS (schema_name 'datapai', table_name 'sys_agent_debate_log');
