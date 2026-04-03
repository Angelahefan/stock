-- 031_exchange_ref_and_fx_rates.sql
-- Creates exchange_ref (static reference) and fx_rates_daily (daily FX rates)
-- Run: docker exec -i lightdash_db_1 psql -U postgres -d postgres < scripts/migrations/031_exchange_ref_and_fx_rates.sql

BEGIN;

-- ── 1. Exchange reference table ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS datapai.exchange_ref (
    exchange        TEXT PRIMARY KEY,
    currency_code   TEXT NOT NULL,
    currency_symbol TEXT NOT NULL,
    currency_name_en TEXT NOT NULL,
    country         TEXT NOT NULL
);

-- Seed exchange_ref with all 10 exchanges
INSERT INTO datapai.exchange_ref (exchange, currency_code, currency_symbol, currency_name_en, country) VALUES
    ('US',   'USD', '$',   'US Dollar',           'United States'),
    ('ASX',  'AUD', 'A$',  'Australian Dollar',   'Australia'),
    ('HKEX', 'HKD', 'HK$', 'Hong Kong Dollar',    'Hong Kong'),
    ('HOSE', 'VND', '₫',   'Vietnamese Dong',     'Vietnam'),
    ('SET',  'THB', '฿',   'Thai Baht',           'Thailand'),
    ('KLSE', 'MYR', 'RM',  'Malaysian Ringgit',   'Malaysia'),
    ('IDX',  'IDR', 'Rp',  'Indonesian Rupiah',   'Indonesia'),
    ('SSE',  'CNY', '¥',   'Chinese Yuan',        'China'),
    ('SZSE', 'CNY', '¥',   'Chinese Yuan',        'China'),
    ('LSE',  'GBX', 'p',   'Pence Sterling',      'United Kingdom')
ON CONFLICT (exchange) DO UPDATE SET
    currency_code    = EXCLUDED.currency_code,
    currency_symbol  = EXCLUDED.currency_symbol,
    currency_name_en = EXCLUDED.currency_name_en,
    country          = EXCLUDED.country;

-- ── 2. Daily FX rates table ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS datapai.fx_rates_daily (
    base_currency   TEXT NOT NULL,
    quote_currency  TEXT NOT NULL,
    rate            NUMERIC NOT NULL,
    trade_date      TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'yahoo',
    PRIMARY KEY (base_currency, quote_currency, trade_date)
);

-- Index for fast lookups by quote currency + date
CREATE INDEX IF NOT EXISTS idx_fx_rates_daily_quote_date
    ON datapai.fx_rates_daily (quote_currency, trade_date DESC);

COMMIT;
