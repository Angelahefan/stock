-- migrations/048_failure_patterns.sql
-- 2026-05-28 — Failure-pattern aggregation table for the macro learning loop.
--
-- WHY
--   Reflector grades each debate individually and writes per-debate lessons.
--   That's the *micro* loop. It can't answer "across our 61 losses, what's
--   the common failure mode?" — for that we need to aggregate.
--
--   This table holds the output of stock_failure_analyzer DAG (runs daily
--   06:30 UTC, after Reflector finishes at ~06:15). Each row is a cluster
--   of debates that share a feature signature and lost together. The
--   analyzer asks Gemini to generate a one-paragraph suggested_action
--   for each dominant cluster.
--
--   This is the input to the future strategy-proposal engine: when a
--   pattern has high loss-rate × n_obs × avg-return-missed, it warrants
--   either a code change or a config-driven tuning.
--
-- WHERE
--   Base table lives on framework_db / datapai_auth_db (same as
--   sys_agent_debate_log — keeps audit data colocated).
--   Stock-db / health-db / trade-db get FDW foreign tables so the
--   FE can read without crossing the network themselves.

BEGIN;

-- ╭───────────────────────────────────────────────────────────────────────╮
-- │ Base table — on framework_db / datapai_auth_db                        │
-- ╰───────────────────────────────────────────────────────────────────────╯
CREATE TABLE IF NOT EXISTS datapai.failure_patterns (
    pattern_id        SERIAL PRIMARY KEY,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Which horizon this pattern was mined over (7d / 30d / 90d)
    horizon_days      INTEGER NOT NULL,

    -- The feature combination that defines this cluster
    -- Example: {direction: "HOLD", conviction: "LOW", confidence_band: "0.20-0.40",
    --           thesis_empty: true, gates_fired: []}
    signature         JSONB NOT NULL,

    -- Human-readable summary of the signature (for UI + LLM input)
    signature_text    TEXT NOT NULL,

    -- Cluster statistics
    n_observations    INTEGER NOT NULL,
    n_losses          INTEGER NOT NULL,
    loss_rate         NUMERIC(5, 2) NOT NULL,
    avg_return_missed NUMERIC(8, 2),   -- avg |actual_return| on losses

    -- Concrete examples (5 worst-ranked debates by abs return)
    example_tickers   TEXT[],

    -- LLM-generated remediation: "this is happening because X, fix is Y"
    suggested_action  TEXT,

    -- Lifecycle — flips when an admin reviews + applies a fix
    status            VARCHAR(20) NOT NULL DEFAULT 'open',
        -- open / triaged / fix_proposed / fix_applied / resolved / wontfix
    reviewed_by       TEXT,
    reviewed_at       TIMESTAMPTZ,
    resolution_note   TEXT
);

CREATE INDEX IF NOT EXISTS idx_failure_patterns_status
    ON datapai.failure_patterns (status, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_failure_patterns_horizon_loss
    ON datapai.failure_patterns (horizon_days, loss_rate DESC, n_observations DESC);

COMMENT ON TABLE datapai.failure_patterns IS
'Macro learning loop — clusters of failed debates that share a feature
signature, with LLM-suggested remediation. Populated daily by stock_failure_analyzer DAG.';

COMMIT;

-- ╭───────────────────────────────────────────────────────────────────────╮
-- │ FDW foreign tables on consumer DBs (stock / health / trade)           │
-- ╰───────────────────────────────────────────────────────────────────────╯
-- Run on each consumer database:
--
-- CREATE FOREIGN TABLE datapai.failure_patterns (
--     pattern_id        integer,
--     computed_at       timestamptz NOT NULL,
--     horizon_days      integer NOT NULL,
--     signature         jsonb NOT NULL,
--     signature_text    text NOT NULL,
--     n_observations    integer NOT NULL,
--     n_losses          integer NOT NULL,
--     loss_rate         numeric(5,2) NOT NULL,
--     avg_return_missed numeric(8,2),
--     example_tickers   text[],
--     suggested_action  text,
--     status            varchar(20) NOT NULL,
--     reviewed_by       text,
--     reviewed_at       timestamptz,
--     resolution_note   text
-- ) SERVER framework_db OPTIONS (
--     schema_name 'datapai',
--     table_name  'failure_patterns'
-- );

-- ╭───────────────────────────────────────────────────────────────────────╮
-- │ Verification                                                          │
-- ╰───────────────────────────────────────────────────────────────────────╯
-- On framework_db / datapai_auth_db:
--   \d datapai.failure_patterns
--   SELECT COUNT(*) FROM datapai.failure_patterns;

-- ╭───────────────────────────────────────────────────────────────────────╮
-- │ ROLLBACK                                                              │
-- ╰───────────────────────────────────────────────────────────────────────╯
-- BEGIN;
-- DROP FOREIGN TABLE IF EXISTS datapai.failure_patterns;  -- on each consumer DB
-- DROP TABLE IF EXISTS datapai.failure_patterns;          -- on framework_db
-- COMMIT;
