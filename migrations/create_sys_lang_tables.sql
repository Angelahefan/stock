-- DB-driven i18n tables for DataPAI
-- Convention: sys_ prefix for system tables, sys_lang_ for language tables

CREATE TABLE IF NOT EXISTS datapai.sys_lang_supported (
    lang         TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    flag_emoji   TEXT,
    is_active    BOOLEAN DEFAULT TRUE,
    sort_order   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS datapai.sys_lang_labels (
    label_key  TEXT NOT NULL,
    lang       TEXT NOT NULL REFERENCES datapai.sys_lang_supported(lang),
    text       TEXT NOT NULL,
    category   TEXT DEFAULT 'common',
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (label_key, lang)
);

CREATE INDEX IF NOT EXISTS idx_sys_lang_labels_lang ON datapai.sys_lang_labels (lang);
CREATE INDEX IF NOT EXISTS idx_sys_lang_labels_cat ON datapai.sys_lang_labels (category);

-- Seed supported languages
INSERT INTO datapai.sys_lang_supported (lang, display_name, flag_emoji, sort_order) VALUES
    ('en',    'English',       '🇺🇸', 1),
    ('zh',    '简体中文',       '🇨🇳', 2),
    ('zh-TW', '繁體中文',       '🇹🇼', 3),
    ('ja',    '日本語',         '🇯🇵', 4),
    ('ko',    '한국어',         '🇰🇷', 5),
    ('vi',    'Tiếng Việt',    '🇻🇳', 6),
    ('th',    'ภาษาไทย',       '🇹🇭', 7),
    ('ms',    'Bahasa Melayu', '🇲🇾', 8)
ON CONFLICT (lang) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    flag_emoji = EXCLUDED.flag_emoji,
    sort_order = EXCLUDED.sort_order;
