-- migrations/047_debate_log_per_horizon_correctness.sql
-- 2026-05-28 — Per-horizon was_correct columns for multi-horizon Reflector.
--
-- WHY
--   The existing was_correct boolean collapses 7d / 30d / 90d outcomes into
--   one number. That hides the real signal — equity AI calls are noisy at
--   7d (random walk dominates) and meaningful at 30d/90d. Different
--   horizons tell different stories about the AI:
--     - 7d hit-rate  = caught the immediate catalyst (news, earnings)
--     - 30d hit-rate = read the trend correctly (TA, sector rotation)
--     - 90d hit-rate = valued the company right (fundamentals, macro)
--   Surfacing them separately is honest and matches institutional practice.
--
-- WHERE
--   Base table: datapai.sys_agent_debate_log on framework_db
--     (database: datapai_auth_db, port 5433 host, 5432 inside container).
--   Foreign tables on consumer DBs (stock 5434, health 5435, trade 5436)
--   must be recreated to expose the new columns. The write-side
--   sys_agent_debate_log foreign table stays at 22 cols (id + created_at
--   still hidden — those are auto-generated remotely; see migration 044).
--   The read-side sys_agent_debate_log_full foreign table grows to include
--   the new columns so Reflector and the FE can SELECT/UPDATE them.
--
-- ROLLBACK at bottom.

-- ╭───────────────────────────────────────────────────────────────────────╮
-- │ STEP 1 — Base table on framework_db / datapai_auth_db                 │
-- ╰───────────────────────────────────────────────────────────────────────╯
-- Apply via:
--   docker cp 047.sql datapai_framework_db:/tmp/047_base.sql
--   docker exec datapai_framework_db psql -U postgres -d datapai_auth_db \
--     -c "ALTER TABLE datapai.sys_agent_debate_log
--          ADD COLUMN IF NOT EXISTS was_correct_7d  BOOLEAN,
--          ADD COLUMN IF NOT EXISTS was_correct_30d BOOLEAN,
--          ADD COLUMN IF NOT EXISTS was_correct_90d BOOLEAN;
--         COMMENT ON COLUMN datapai.sys_agent_debate_log.was_correct_7d
--          IS 'True if direction agreed with 7-day return sign. Short-term, noisy.';
--         COMMENT ON COLUMN datapai.sys_agent_debate_log.was_correct_30d
--          IS 'True if direction agreed with 30-day return sign. Medium-term.';
--         COMMENT ON COLUMN datapai.sys_agent_debate_log.was_correct_90d
--          IS 'True if direction agreed with 90-day return sign. Long-term, best signal.';"
--
-- The migration script (run_migration_047.sh) handles this remotely.

-- ╭───────────────────────────────────────────────────────────────────────╮
-- │ STEP 2 — Recreate sys_agent_debate_log_full FDW on consumer DBs       │
-- ╰───────────────────────────────────────────────────────────────────────╯
-- Run this against stock_db / health_db / trade_db (postgres database).

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
    was_correct_7d    boolean,
    was_correct_30d   boolean,
    was_correct_90d   boolean,
    lessons_extracted text[],
    created_at        timestamptz  NOT NULL
) SERVER framework_db OPTIONS (
    schema_name 'datapai',
    table_name  'sys_agent_debate_log'
);

-- The write-side foreign table (22 cols, omits id + created_at) does NOT
-- need to change — Python's INSERT doesn't reference was_correct_* (those
-- are written later by Reflector via UPDATE on the _full table).

-- ╭───────────────────────────────────────────────────────────────────────╮
-- │ Verification                                                          │
-- ╰───────────────────────────────────────────────────────────────────────╯
-- After applying:
--
--   docker exec datapai_framework_db psql -U postgres -d datapai_auth_db \
--     -c "\d datapai.sys_agent_debate_log" | grep was_correct
--   -- expect 4 rows: was_correct, was_correct_7d, was_correct_30d, was_correct_90d
--
--   docker exec datapai_stock_db psql -U postgres -d postgres \
--     -c "SELECT COUNT(*) FROM information_schema.columns
--          WHERE table_schema='datapai' AND table_name='sys_agent_debate_log_full'
--            AND column_name LIKE 'was_correct%'"
--   -- expect 4

-- ╭───────────────────────────────────────────────────────────────────────╮
-- │ ROLLBACK                                                              │
-- ╰───────────────────────────────────────────────────────────────────────╯
-- On framework_db / datapai_auth_db:
--   ALTER TABLE datapai.sys_agent_debate_log
--     DROP COLUMN IF EXISTS was_correct_90d,
--     DROP COLUMN IF EXISTS was_correct_30d,
--     DROP COLUMN IF EXISTS was_correct_7d;
-- On each consumer DB: re-run migration 044's DROP+CREATE for the _full
-- foreign table (the 24-col version without was_correct_7d/30d/90d).
