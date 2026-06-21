-- =============================================================================
-- Migration 051: add KDJ (9, 3, 3) columns to datapai.ta_indicators
--
-- KDJ is the Chinese-market standard short-term momentum indicator. It is
-- conceptually close to Stochastic (which is already present as stoch_k /
-- stoch_d / stoch_label) but uses (9, 3, 3) parameters by default and adds
-- the J line — J = 3K - 2D — which traders use as a leading-momentum signal
-- (often crosses overbought / oversold thresholds before K).
--
-- We add four columns (kdj_k, kdj_d, kdj_j, kdj_signal) without touching the
-- existing Stochastic columns so the screener path (which relies on the
-- (9, 3, 3) KDJ computed by scripts/compute_screener_metrics.py) and the
-- chat path (which formats the (14, 3) Stochastic) keep their current
-- behaviour while new compute paths populate KDJ alongside.
--
-- Run once on EC2 Postgres:
--   psql -h $DATAPAI_PG_HOST -U $DATAPAI_PG_USER -d $DATAPAI_PG_DB -f this_file.sql
-- =============================================================================

ALTER TABLE datapai.ta_indicators
    ADD COLUMN IF NOT EXISTS kdj_k       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS kdj_d       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS kdj_j       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS kdj_signal  VARCHAR(12);  -- OVERBOUGHT | NEUTRAL | OVERSOLD

-- Optional index for screener-style queries that filter on weekly KDJ signal.
CREATE INDEX IF NOT EXISTS idx_ta_indicators_kdj_weekly
    ON datapai.ta_indicators (timeframe, trade_date DESC, kdj_signal)
    WHERE timeframe = '1w' AND quality_ok = TRUE;

-- Verification:
--   SELECT column_name, data_type
--   FROM information_schema.columns
--   WHERE table_schema = 'datapai'
--     AND table_name   = 'ta_indicators'
--     AND column_name LIKE 'kdj%'
--   ORDER BY ordinal_position;

-- Rollback (only if absolutely needed — KDJ is additive and harmless):
--   ALTER TABLE datapai.ta_indicators
--       DROP COLUMN IF EXISTS kdj_k,
--       DROP COLUMN IF EXISTS kdj_d,
--       DROP COLUMN IF EXISTS kdj_j,
--       DROP COLUMN IF EXISTS kdj_signal;
--   DROP INDEX IF EXISTS datapai.idx_ta_indicators_kdj_weekly;
