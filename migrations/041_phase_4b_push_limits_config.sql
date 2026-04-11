-- ─────────────────────────────────────────────────────────────────────────
-- Phase 4B enhancement — plan-driven push notification daily limits
-- ─────────────────────────────────────────────────────────────────────────
-- Applied: 2026-04-11
-- Target:  datapai_framework_db, datapai.sys_common_config
--
-- Replaces the hardcoded PUSH_MAX_DAILY_DEFAULT = 5 in scripts/send_alerts.py
-- with a config-table lookup per user plan. Parallels the existing chat_limits
-- config_type structure.
--
-- Plan ids come from datapai.sys_pricing_tiers.tier_id:
--   watch, individual, professional, business
--
-- The 'default_daily_limit' row is a safety net for any unknown/legacy plan
-- value in datapai.users.plan.
--
-- Run via:
--   docker exec -i datapai_framework_db psql -U postgres -d datapai_auth_db < this_file.sql
-- ─────────────────────────────────────────────────────────────────────────

INSERT INTO datapai.sys_common_config (config_type, config_key, config_value, description, created_by)
VALUES
  ('push_limits', 'watch_daily_limit',        '5',
   'Free (watch) plan: max push notifications per user per day. Loose default — tighten if abuse seen.',
   'phase4b_2026-04-11'),
  ('push_limits', 'individual_daily_limit',   '20',
   'Individual ($49 AUD/mo): higher limit for paying users who want real-time alerts.',
   'phase4b_2026-04-11'),
  ('push_limits', 'professional_daily_limit', '50',
   'Professional ($299 AUD/mo): active traders running multiple watchlists.',
   'phase4b_2026-04-11'),
  ('push_limits', 'business_daily_limit',     '100',
   'Business ($999 AUD/mo): team accounts, higher throughput.',
   'phase4b_2026-04-11'),
  ('push_limits', 'default_daily_limit',      '5',
   'Fallback for unknown/legacy plan values. Matches the free tier so abuse via misconfigured plan is bounded.',
   'phase4b_2026-04-11')
ON CONFLICT (config_type, config_key) DO UPDATE SET
  config_value = EXCLUDED.config_value,
  description  = EXCLUDED.description,
  updated_at   = NOW();

-- Verification
-- SELECT config_key, config_value, description
-- FROM datapai.sys_common_config
-- WHERE config_type = 'push_limits'
-- ORDER BY
--   CASE config_key
--     WHEN 'default_daily_limit'      THEN 0
--     WHEN 'watch_daily_limit'        THEN 1
--     WHEN 'individual_daily_limit'   THEN 2
--     WHEN 'professional_daily_limit' THEN 3
--     WHEN 'business_daily_limit'     THEN 4
--     ELSE 99
--   END;
