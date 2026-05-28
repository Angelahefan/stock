-- migrations/045_stock_synthesis_transparency.sql
-- 2026-05-28 — AI agent transparency layer.
--
-- Adds structured columns to datapai.stock_synthesis so the FE can render
-- per-agent attribution instead of black-box "AI Analyst Call". Backs the
-- "How the AI Decided" panel on /ticker/[X]/intel and the /methodology page.
--
-- Currently gate-fire reasons (Quality, Regime, Sanity, CRITICAL News
-- overrides) get jammed into the `key_risk` free-text field as a prose
-- prefix like "[Quality gate] Demoted BUY → HOLD (quality tier C)". That
-- works for humans but the FE can't render structured chips/icons. New
-- columns separate machine-readable governance from user-facing narrative.
--
-- WHERE
--   stock_db (port 5434) — local table, no FDW. Other consumer DBs use this
--   table read-only via app-level queries, not foreign tables.
--
-- ROLLBACK at bottom.

BEGIN;

-- ── gate_decisions: structured record of every gate evaluated ───────────────
--
-- Shape (each gate is a key; value is {fired, reason, demoted_from, demoted_to}):
--   {
--     "quality_gate":     {"fired": true,  "reason": "tier C/D",
--                          "demoted_from": "BUY", "demoted_to": "HOLD"},
--     "regime_gate":      {"fired": false},
--     "sanity_override":  {"fired": false},
--     "critical_news":    {"fired": true,  "headline": "...",
--                          "demoted_from": "BUY", "demoted_to": "SELL"}
--   }
ALTER TABLE datapai.stock_synthesis
    ADD COLUMN IF NOT EXISTS gate_decisions jsonb NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN datapai.stock_synthesis.gate_decisions IS
'Structured record of all post-debate governance gates. Each key is a gate
name (quality_gate, regime_gate, sanity_override, critical_news); each value
{fired, reason, demoted_from, demoted_to, ...}. FE renders chips per gate.';

-- ── agent_signals: per-source-agent direction + confidence + summary ────────
--
-- Today we store ta_direction / fa_direction / ma_direction as varchar columns
-- separately. For the FE panel we need MORE: per-agent confidence + 1-line
-- summary + the sub-agents inside FA (valuation, quality, growth, analyst).
--
-- Shape:
--   {
--     "technical":   {"direction": "SELL", "confidence": 0.72,
--                     "summary": "RSI overbought, MACD bearish cross"},
--     "fundamental": {"direction": "HOLD", "confidence": 0.60,
--                     "summary": "...", "sub_agents": {
--                        "valuation":      {"direction": "SELL", "score": 0.11},
--                        "quality":        {"direction": "BUY",  "tier":  "A"},
--                        "growth":         {"direction": "BUY",  "score": 0.70},
--                        "analyst":        {"direction": "HOLD", "upside_pct": 5.86}
--                     }},
--     "macro":       {"direction": "HOLD", "confidence": 0.50, "summary": "..."},
--     "market_activity": {"direction": null, "summary": "no IR changes"},
--     "news":        {"direction": "HOLD", "confidence": 0.55,
--                     "summary": "BoA downgrade, MEDIUM severity",
--                     "top_event_headline": "..."}
--   }
ALTER TABLE datapai.stock_synthesis
    ADD COLUMN IF NOT EXISTS agent_signals jsonb NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN datapai.stock_synthesis.agent_signals IS
'Per-input-agent contribution to the debate: direction + confidence +
summary, plus sub-agent breakdown inside fundamental. Drives the
"Behind the call" panel on /ticker/[X]/intel.';

-- ── reflector_lessons: which past lessons fed into this debate ──────────────
--
-- When Reflector compounds learning, the lessons it injected into each
-- persona's prompt should be visible to users as "we learned from N past
-- debates" with the actual lesson text. Shape:
--   {
--     "lessons_count": 2,
--     "lessons": [
--       "When FA=BUY + News=HOLD on commodities, hit-rate 58% over 30d",
--       "..."
--     ]
--   }
ALTER TABLE datapai.stock_synthesis
    ADD COLUMN IF NOT EXISTS reflector_lessons jsonb NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN datapai.stock_synthesis.reflector_lessons IS
'Past lessons (from Reflector loop) that were injected into agent system
prompts before this debate ran. Visible to users as "learned from N debates".';

-- ── Index for filtering by gate-fired status ────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_stock_synthesis_any_gate_fired
ON datapai.stock_synthesis
USING gin (gate_decisions jsonb_path_ops);

COMMIT;

-- Verification query:
--   SELECT column_name, data_type, column_default
--   FROM information_schema.columns
--   WHERE table_schema='datapai' AND table_name='stock_synthesis'
--     AND column_name IN ('gate_decisions', 'agent_signals', 'reflector_lessons');
--   (expect 3 rows, all jsonb, default '{}'::jsonb)

-- ROLLBACK pattern (if needed — preserves existing rows; columns drop is safe
-- because nothing else references these new columns yet):
--
-- BEGIN;
-- DROP INDEX IF EXISTS datapai.idx_stock_synthesis_any_gate_fired;
-- ALTER TABLE datapai.stock_synthesis DROP COLUMN IF EXISTS reflector_lessons;
-- ALTER TABLE datapai.stock_synthesis DROP COLUMN IF EXISTS agent_signals;
-- ALTER TABLE datapai.stock_synthesis DROP COLUMN IF EXISTS gate_decisions;
-- COMMIT;
