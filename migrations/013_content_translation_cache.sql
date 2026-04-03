-- 013_content_translation_cache.sql
-- Cache for on-the-fly translated AI content (signal summaries, investigation, etc.)
-- Key: (source_table, source_id, field_name, lang) → translated text
-- TTL managed by application (re-translate if source text changes)

BEGIN;

CREATE TABLE IF NOT EXISTS datapai.content_translation_cache (
    source_table  TEXT NOT NULL,       -- e.g. 'analyses', 'material_events'
    source_id     TEXT NOT NULL,       -- row ID from source table
    field_name    TEXT NOT NULL,       -- e.g. 'agent_what_changed', 'validation_summary'
    lang          TEXT NOT NULL,       -- target language code
    source_hash   TEXT NOT NULL,       -- MD5 of English source text (invalidation)
    translated    TEXT NOT NULL,       -- translated text
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_table, source_id, field_name, lang)
);

CREATE INDEX IF NOT EXISTS idx_content_translation_lookup
  ON datapai.content_translation_cache (source_table, source_id, lang);

COMMIT;
