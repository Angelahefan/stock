-- migrations/050_synthesis_health_runs.sql
-- 2026-05-28 — Health-monitor audit log.
--
-- Records every nightly health-check run. Lets us see WHEN a regression
-- started rather than only WHAT today's metrics look like.
--
-- If we'd had this back in March, we'd have seen low_conviction_pct flip
-- from <20% to 100% the day AG2 broke — and fixed it that week.

BEGIN;

CREATE TABLE IF NOT EXISTS datapai.synthesis_health_runs (
    run_id              SERIAL PRIMARY KEY,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_date            DATE         NOT NULL,

    -- Cohort the metrics were computed over
    cohort_window       VARCHAR(50)  NOT NULL DEFAULT 'last_24h',
    cohort_row_count    INTEGER      NOT NULL,

    -- The 6 metrics
    pct_low_conviction      NUMERIC(5,2),   -- % of rows with conviction = LOW
    distinct_directions     INTEGER,         -- count of distinct direction values
    pct_empty_thesis        NUMERIC(5,2),   -- % of rows where thesis < 50 chars
    pct_broken_fallback     NUMERIC(5,2),   -- % matching HOLD/conf<0.5 signature
    pct_fallback_path       NUMERIC(5,2),   -- % rows where model_used != gemini-2.5-flash
    hit_rate_30d            NUMERIC(5,2),   -- 30d hit rate at this run

    -- Did we trip any thresholds?
    alerts_fired            TEXT[],          -- array of alert reasons (empty = clean)
    overall_status          VARCHAR(20) NOT NULL DEFAULT 'green',
                                            -- green / yellow / red

    -- Free-form details
    metrics_detail          JSONB           -- per-metric raw counters
);

CREATE INDEX IF NOT EXISTS idx_synthesis_health_runs_date
    ON datapai.synthesis_health_runs (run_date DESC);

CREATE INDEX IF NOT EXISTS idx_synthesis_health_runs_status_date
    ON datapai.synthesis_health_runs (overall_status, run_date DESC)
    WHERE overall_status != 'green';

COMMIT;

-- Verification:
--   \d datapai.synthesis_health_runs
--   SELECT COUNT(*) FROM datapai.synthesis_health_runs;
--
-- Sample query for the future health dashboard:
--   SELECT run_date, pct_low_conviction, pct_broken_fallback, hit_rate_30d, overall_status
--   FROM datapai.synthesis_health_runs ORDER BY run_date DESC LIMIT 30;

-- ROLLBACK:
-- DROP TABLE IF EXISTS datapai.synthesis_health_runs;
