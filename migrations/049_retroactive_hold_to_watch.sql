-- migrations/049_retroactive_hold_to_watch.sql
-- 2026-05-28 — Stop misrepresenting historical broken-fallback HOLDs.
--
-- PROBLEM
--   From late March through May 24, the synthesis pipeline silently fell
--   to a hardcoded HOLD/0.30/LOW default when AG2 failed (the 2-month
--   silent breakage we diagnosed on May-24). Those rows display on
--   /performance as "HOLD" — which in user-facing language means
--   "we recommend you keep this stock." That was never the case; those
--   rows were really "engine couldn't form an opinion."
--
--   The 61 losing HOLDs include AEHR which then ran +200%, MARA +53%,
--   HIMS +44% — making the AI look like it actively told users to
--   miss those moves. It didn't; it punted.
--
-- FIX
--   Relabel the broken-fallback signature rows from HOLD → WATCH:
--     direction = HOLD
--     AND confidence < 0.50
--     AND (signals_aligned = FALSE OR signals_aligned IS NULL)
--
--   This is honest data correction, not revisionism:
--     - WATCH is the truthful semantic (active deferral, not "keep it")
--     - was_correct_{Nd} will be re-graded under WATCH thresholds
--       (range-bound = correct) on next Reflector pass
--     - Failure-pattern analyzer's "broken HOLD" cluster will dissolve
--
--   Real HOLDs (conf >= 0.50 AND signals_aligned) are LEFT ALONE.
--
-- BLAST RADIUS
--   stock_synthesis on stock_db, sys_agent_debate_log on framework_db
--   /datapai_auth_db. Counts: ~137 rows in each (audit before commit).
--
-- ROLLBACK
--   Audit columns (original_direction_before_relabel, relabeled_at) make
--   the inverse trivial — see bottom.

BEGIN;

-- ╭───────────────────────────────────────────────────────────────────────╮
-- │ stock_db / datapai.stock_synthesis                                    │
-- ╰───────────────────────────────────────────────────────────────────────╯
ALTER TABLE datapai.stock_synthesis
    ADD COLUMN IF NOT EXISTS relabeled_at        TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS relabeled_from_dir  VARCHAR(20);

UPDATE datapai.stock_synthesis
SET direction          = 'WATCH',
    relabeled_at       = NOW(),
    relabeled_from_dir = 'HOLD'
WHERE direction = 'HOLD'
  AND confidence < 0.50
  AND (signals_aligned = FALSE OR signals_aligned IS NULL)
  AND relabeled_at IS NULL;   -- idempotent — won't double-relabel

-- Audit count (read after committing to confirm):
--   SELECT COUNT(*) FROM datapai.stock_synthesis WHERE relabeled_from_dir = 'HOLD';

COMMIT;

-- ╭───────────────────────────────────────────────────────────────────────╮
-- │ framework_db / datapai_auth_db / datapai.sys_agent_debate_log         │
-- ╰───────────────────────────────────────────────────────────────────────╯
-- Run separately against framework_db (the base table for the debate log).
-- Same logic — relabel HOLD rows that were broken-fallback. Clear
-- was_correct_* so Reflector regrades them under WATCH thresholds.

BEGIN;

ALTER TABLE datapai.sys_agent_debate_log
    ADD COLUMN IF NOT EXISTS relabeled_at        TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS relabeled_from_dir  VARCHAR(20);

UPDATE datapai.sys_agent_debate_log
SET direction          = 'WATCH',
    relabeled_at       = NOW(),
    relabeled_from_dir = 'HOLD',
    was_correct        = NULL,   -- force Reflector to regrade
    was_correct_7d     = NULL,
    was_correct_30d    = NULL,
    was_correct_90d    = NULL
WHERE direction = 'HOLD'
  AND confidence < 0.50
  AND relabeled_at IS NULL;

COMMIT;

-- ╭───────────────────────────────────────────────────────────────────────╮
-- │ ROLLBACK pattern                                                      │
-- ╰───────────────────────────────────────────────────────────────────────╯
-- UPDATE datapai.stock_synthesis
-- SET direction = relabeled_from_dir, relabeled_at = NULL, relabeled_from_dir = NULL
-- WHERE relabeled_from_dir IS NOT NULL;
--
-- UPDATE datapai.sys_agent_debate_log
-- SET direction = relabeled_from_dir, relabeled_at = NULL, relabeled_from_dir = NULL
-- WHERE relabeled_from_dir IS NOT NULL;
-- (Then re-run Reflector to restore was_correct_* values.)
