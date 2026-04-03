-- 011_stock_directory_i18n.sql
-- Add lang column to stock_directory, change PK to (symbol, exchange, lang)
-- Existing rows get lang='en' by default

BEGIN;

-- Drop old PK and indexes
ALTER TABLE datapai.stock_directory DROP CONSTRAINT IF EXISTS stock_directory_pkey;
DROP INDEX IF EXISTS datapai.idx_stock_dir_symbol;

-- Add lang column (existing rows default to 'en')
ALTER TABLE datapai.stock_directory ADD COLUMN IF NOT EXISTS lang TEXT NOT NULL DEFAULT 'en';

-- New composite PK
ALTER TABLE datapai.stock_directory ADD CONSTRAINT stock_directory_pkey PRIMARY KEY (symbol, exchange, lang);

-- Rebuild indexes for query performance
CREATE INDEX IF NOT EXISTS idx_stock_dir_symbol_lang ON datapai.stock_directory (symbol, lang);
CREATE INDEX IF NOT EXISTS idx_stock_dir_exchange_lang ON datapai.stock_directory (exchange, lang);
CREATE INDEX IF NOT EXISTS idx_stock_dir_name_search ON datapai.stock_directory (exchange, lang, UPPER(name) text_pattern_ops);

COMMIT;
