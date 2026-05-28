-- migrations/046_stock_synthesis_price_snapshot.sql
-- 2026-05-28 — Snapshot price at debate time into the synthesis row.
--
-- WHY
--   The /debate/[ticker] page currently shows "Price at debate" by looking
--   up the close price from datapai.prices for the debate date. That works
--   today but is fragile:
--     - Price tables get reloaded with split adjustments retroactively
--     - Lookup could return null if the FDW/source changes
--     - Different price tables (intraday/daily, raw/adjusted) can disagree
--     - User trust dies in seconds when price displayed is "wrong" — even
--       if the AI saw the right number originally
--
--   Solution: at debate write time, capture the exact close price the AI
--   based its recommendation on. Store with the synthesis row. The UI then
--   displays this stored value, not a re-derived lookup. The AI's view of
--   the world becomes the canonical record.
--
-- WHERE
--   stock_db (port 5434) — local table, no FDW.
--
-- ROLLBACK at bottom.

BEGIN;

ALTER TABLE datapai.stock_synthesis
    ADD COLUMN IF NOT EXISTS price_at_debate  NUMERIC(18, 6),
    ADD COLUMN IF NOT EXISTS price_currency   VARCHAR(4),
    ADD COLUMN IF NOT EXISTS price_as_of_date DATE;

COMMENT ON COLUMN datapai.stock_synthesis.price_at_debate IS
'Close price the AI agents saw when this debate ran. Frozen at write time
so the /debate page always shows what the AI based its call on, even if
the underlying price tables get reloaded or re-adjusted later.';

COMMENT ON COLUMN datapai.stock_synthesis.price_currency IS
'ISO-ish currency code at debate time (USD/AUD/HKD/VND/...). Best-effort
mapping by exchange, no FX conversion implied.';

COMMENT ON COLUMN datapai.stock_synthesis.price_as_of_date IS
'Trade date of the close price stored in price_at_debate. Usually the day
the debate ran or the most recent trading day before it.';

COMMIT;

-- Verification:
--   SELECT column_name, data_type
--   FROM information_schema.columns
--   WHERE table_schema='datapai' AND table_name='stock_synthesis'
--     AND column_name IN ('price_at_debate', 'price_currency', 'price_as_of_date');
--   (expect 3 rows)

-- ROLLBACK pattern:
-- BEGIN;
-- ALTER TABLE datapai.stock_synthesis
--     DROP COLUMN IF EXISTS price_as_of_date,
--     DROP COLUMN IF EXISTS price_currency,
--     DROP COLUMN IF EXISTS price_at_debate;
-- COMMIT;
