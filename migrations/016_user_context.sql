-- Migration 016: Continuous User Context Learning
-- Date: 2026-03-25
-- Purpose: Accumulates what we learn about each user from chat, behavior, and onboarding.
-- Replaces shallow keyword extraction with structured, confidence-scored context.

CREATE TABLE IF NOT EXISTS datapai.sys_user_context (
    id              SERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL,          -- Next.js UUID (canonical user ID)
    context_key     VARCHAR(60) NOT NULL,   -- structured key: pref/*, behavior/*, knowledge/*, style/*, portfolio/*, goal/*
    context_value   TEXT NOT NULL,           -- the learned fact
    context_type    VARCHAR(20) NOT NULL DEFAULT 'preference',
    -- 'preference', 'behavior', 'knowledge', 'style', 'portfolio', 'goal'
    confidence      REAL NOT NULL DEFAULT 0.5,
    -- 0.0-1.0: explicit statement=0.9, inferred=0.5, onboarding=1.0
    source          VARCHAR(30) NOT NULL DEFAULT 'chat_extraction',
    -- 'chat_extraction', 'onboarding', 'watchlist_pattern', 'scan_pattern', 'manual'
    source_detail   TEXT,                   -- session_id or message excerpt
    mention_count   INTEGER DEFAULT 1,      -- how many times user mentioned this
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active       BOOLEAN DEFAULT TRUE,
    UNIQUE (user_id, context_key)
);

CREATE INDEX IF NOT EXISTS idx_user_context_user ON datapai.sys_user_context(user_id);
CREATE INDEX IF NOT EXISTS idx_user_context_type ON datapai.sys_user_context(context_type);
CREATE INDEX IF NOT EXISTS idx_user_context_conf ON datapai.sys_user_context(user_id, confidence DESC);

COMMENT ON TABLE datapai.sys_user_context IS 'Continuous user context learning — accumulated from chat, onboarding, behavior';

-- Migrate existing user_preferences into sys_user_context
INSERT INTO datapai.sys_user_context (user_id, context_key, context_value, context_type, confidence, source, first_seen, last_seen)
SELECT user_id,
       'pref/' || pref_key,
       pref_value,
       'preference',
       COALESCE(confidence, 0.7),
       'chat_extraction',
       COALESCE(created_at, NOW()),
       COALESCE(updated_at, NOW())
FROM datapai.user_preferences
ON CONFLICT (user_id, context_key) DO NOTHING;
