-- ─────────────────────────────────────────────────────────────────────────
-- Phase 4B enhancement — DB-driven exchange name normalization
-- ─────────────────────────────────────────────────────────────────────────
-- Applied: 2026-04-11
-- Target:  datapai_framework_db, datapai.sys_common_config
--
-- Replaces the hardcoded EXCHANGE_ALIASES = {"NASDAQ": "US", ...} dict in
-- scripts/stock_crm_client_sync.py with a config-table lookup. This maps
-- source-side exchange names (in datapai.watchlist.exchange) to Twenty's
-- preferredMarkets SELECT enum values.
--
-- Example: a user has 'NASDAQ' in their watchlist, but Twenty only knows
-- 'US' as the enum value. The alias config lets the sync script normalize
-- NASDAQ→US before upserting to Twenty.
--
-- To add a new alias (e.g. SGX_MAIN → SGX when SGX renames its main board):
--   INSERT INTO datapai.sys_common_config
--     (config_type, config_key, config_value, description, created_by)
--   VALUES ('exchange_aliases', 'SGX_MAIN', 'SGX', '...', 'your_name');
--
-- Run via:
--   docker exec -i datapai_framework_db psql -U postgres -d datapai_auth_db < this_file.sql
-- ─────────────────────────────────────────────────────────────────────────

INSERT INTO datapai.sys_common_config (config_type, config_key, config_value, description, created_by)
VALUES
  ('exchange_aliases', 'NASDAQ', 'US',
   'NASDAQ is a US exchange; Twenty preferredMarkets groups all US boards under US.',
   'phase4b_2026-04-11'),
  ('exchange_aliases', 'NYSE', 'US',
   'NYSE is a US exchange; Twenty preferredMarkets groups all US boards under US.',
   'phase4b_2026-04-11'),
  ('exchange_aliases', 'AMEX', 'US',
   'AMEX is a US exchange; Twenty preferredMarkets groups all US boards under US.',
   'phase4b_2026-04-11')
ON CONFLICT (config_type, config_key) DO UPDATE SET
  config_value = EXCLUDED.config_value,
  description  = EXCLUDED.description,
  updated_at   = NOW();

-- Verification
-- SELECT config_key, config_value, description
-- FROM datapai.sys_common_config
-- WHERE config_type = 'exchange_aliases'
-- ORDER BY config_key;
