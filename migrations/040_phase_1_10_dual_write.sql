-- ─────────────────────────────────────────────────────────────────────────
-- Phase 1.10 — Dual-write from auth.users to datapai.users + device registration
-- ─────────────────────────────────────────────────────────────────────────
-- Applied: 2026-04-11
--
-- This migration has TWO parts because datapai.users is a real table on
-- datapai_framework_db and a foreign-table alias on datapai_stock_db. Schema
-- changes must go to framework_db FIRST, then mirror to the stock_db FDW
-- alias. See docs/architecture/fdw-gotchas.md for full context.
--
-- Related:
--   - docs/phase-journals/2026-04-11-phase-1.10-to-4b.md
--   - datapai-auth-be/agents/auth/endpoint.py ::_dual_write_stock_profile
-- ─────────────────────────────────────────────────────────────────────────

-- ╔═══════════════════════════════════════════════════════════════════════╗
-- ║ PART 1 — Apply on datapai_framework_db (port 5433, db=datapai_auth_db) ║
-- ╚═══════════════════════════════════════════════════════════════════════╝
--
-- docker exec -i datapai_framework_db psql -U postgres -d datapai_auth_db < this_file.sql
--
-- (Comment out PART 2 before running against framework_db.)

-- 1.10.2 — signup_source column on the legacy stock vertical profile table
ALTER TABLE datapai.users
  ADD COLUMN IF NOT EXISTS signup_source TEXT NOT NULL DEFAULT 'unknown';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'users_signup_source_check'
      AND conrelid = 'datapai.users'::regclass
  ) THEN
    ALTER TABLE datapai.users
      ADD CONSTRAINT users_signup_source_check
      CHECK (signup_source IN ('web', 'mobile_ios', 'mobile_android', 'google_oauth', 'unknown'));
  END IF;
END $$;

COMMENT ON COLUMN datapai.users.signup_source IS
  'Where the user first registered. Populated at register time by datapai-auth-be /api/auth/register dual-write. Added 2026-04-11 as part of Phase 1.10.';

-- 1.10.4 — user_devices table for mobile push notification tokens
CREATE TABLE IF NOT EXISTS datapai.user_devices (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT NOT NULL,
    platform        TEXT NOT NULL CHECK (platform IN ('ios', 'android', 'web')),
    expo_push_token TEXT,
    device_name     TEXT,
    device_model    TEXT,
    os_version      TEXT,
    app_version     TEXT,
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled_at     TIMESTAMPTZ,
    UNIQUE (user_id, expo_push_token)
);

CREATE INDEX IF NOT EXISTS idx_user_devices_user
  ON datapai.user_devices(user_id) WHERE disabled_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_user_devices_push_token
  ON datapai.user_devices(expo_push_token)
  WHERE expo_push_token IS NOT NULL AND disabled_at IS NULL;

COMMENT ON TABLE datapai.user_devices IS
  'Mobile / web push notification tokens. user_id matches datapai.users.id (which for new users = auth.users.uuid). Written by datapai-auth-be /api/auth/device/register endpoint. Added 2026-04-11 as part of Phase 1.10.';

-- Grants for auth_service role (auth-be connects as this role)
GRANT USAGE ON SCHEMA datapai TO auth_service;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA datapai TO auth_service;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA datapai TO auth_service;
ALTER DEFAULT PRIVILEGES IN SCHEMA datapai
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO auth_service;


-- ╔═══════════════════════════════════════════════════════════════════════╗
-- ║ PART 2 — Apply on datapai_stock_db (port 5434, db=postgres)            ║
-- ╚═══════════════════════════════════════════════════════════════════════╝
--
-- docker exec -i datapai_stock_db psql -U postgres -d postgres < this_file.sql
--
-- (Uncomment when running against stock_db; comment out PART 1.)
-- (Or split into two files if you prefer — both halves are separable.)

-- Refresh the FDW foreign-table alias on stock_db to add the new column
-- Note: ALTER FOREIGN TABLE only changes LOCAL metadata, does NOT touch the
-- remote table. The remote was already altered in PART 1 above.
-- ALTER FOREIGN TABLE datapai.users ADD COLUMN signup_source TEXT;

-- Create the foreign-table alias for datapai.user_devices
-- CREATE FOREIGN TABLE IF NOT EXISTS datapai.user_devices (
--     id              UUID,
--     user_id         TEXT,
--     platform        TEXT,
--     expo_push_token TEXT,
--     device_name     TEXT,
--     device_model    TEXT,
--     os_version      TEXT,
--     app_version     TEXT,
--     last_seen_at    TIMESTAMPTZ,
--     created_at      TIMESTAMPTZ,
--     disabled_at     TIMESTAMPTZ
-- )
-- SERVER framework_db
-- OPTIONS (schema_name 'datapai', table_name 'user_devices');


-- ╔═══════════════════════════════════════════════════════════════════════╗
-- ║ Verification (run against either DB — the FDW propagates READS fine)  ║
-- ╚═══════════════════════════════════════════════════════════════════════╝

-- SELECT 'users.signup_source exists?' AS check,
--   EXISTS(SELECT 1 FROM information_schema.columns
--          WHERE table_schema='datapai' AND table_name='users' AND column_name='signup_source') AS result;
--
-- SELECT 'user_devices table exists?' AS check,
--   EXISTS(SELECT 1 FROM information_schema.tables
--          WHERE table_schema='datapai' AND table_name='user_devices') AS result;
--
-- SELECT signup_source, COUNT(*) FROM datapai.users GROUP BY signup_source;
