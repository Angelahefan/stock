-- ============================================================================
-- 037_sgx_market.sql — Add Singapore Exchange (SGX) market support
-- ============================================================================

-- 1. Per-market intraday table
CREATE TABLE IF NOT EXISTS datapai.ohlcv_intraday_sgx (
    ticker      TEXT NOT NULL,
    ts          TIMESTAMP NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION,
    volume      BIGINT,
    exchange    TEXT DEFAULT 'SGX',
    source      TEXT DEFAULT 'yfinance',
    inserted_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (ticker, ts)
);

CREATE TABLE IF NOT EXISTS datapai.ohlcv_intraday_sgx_archive (
    LIKE datapai.ohlcv_intraday_sgx INCLUDING ALL
);

-- 2. Recreate the unified view to include SGX
CREATE OR REPLACE VIEW datapai.ohlcv_intraday AS
    SELECT * FROM datapai.ohlcv_intraday_us
    UNION ALL SELECT * FROM datapai.ohlcv_intraday_asx
    UNION ALL SELECT * FROM datapai.ohlcv_intraday_hkex
    UNION ALL SELECT * FROM datapai.ohlcv_intraday_hose
    UNION ALL SELECT * FROM datapai.ohlcv_intraday_set
    UNION ALL SELECT * FROM datapai.ohlcv_intraday_klse
    UNION ALL SELECT * FROM datapai.ohlcv_intraday_idx
    UNION ALL SELECT * FROM datapai.ohlcv_intraday_sse
    UNION ALL SELECT * FROM datapai.ohlcv_intraday_szse
    UNION ALL SELECT * FROM datapai.ohlcv_intraday_lse
    UNION ALL SELECT * FROM datapai.ohlcv_intraday_twse
    UNION ALL SELECT * FROM datapai.ohlcv_intraday_sgx;

-- 3. Seed featured SGX stocks into ticker_universe + market_demo_stocks + stock_directory
-- Top 20 Singapore blue chips by market cap
INSERT INTO datapai.ticker_universe (ticker, yf_symbol, exchange, is_active, is_featured) VALUES
('D05', 'D05.SI', 'SGX', true, true),
('O39', 'O39.SI', 'SGX', true, true),
('U11', 'U11.SI', 'SGX', true, true),
('Z74', 'Z74.SI', 'SGX', true, true),
('C6L', 'C6L.SI', 'SGX', true, true),
('9CI', '9CI.SI', 'SGX', true, true),
('A17U', 'A17U.SI', 'SGX', true, true),
('S58', 'S58.SI', 'SGX', true, true),
('BN4', 'BN4.SI', 'SGX', true, true),
('H78', 'H78.SI', 'SGX', true, true),
('Y92', 'Y92.SI', 'SGX', true, true),
('F34', 'F34.SI', 'SGX', true, true),
('S63', 'S63.SI', 'SGX', true, true),
('V03', 'V03.SI', 'SGX', true, true),
('BS6', 'BS6.SI', 'SGX', true, true),
('M44U', 'M44U.SI', 'SGX', true, true),
('N2IU', 'N2IU.SI', 'SGX', true, true),
('ME8U', 'ME8U.SI', 'SGX', true, true),
('S68', 'S68.SI', 'SGX', true, true),
('CC3', 'CC3.SI', 'SGX', true, true)
ON CONFLICT (ticker, exchange) DO UPDATE SET yf_symbol = EXCLUDED.yf_symbol, is_active = true, is_featured = true;

INSERT INTO datapai.market_demo_stocks (ticker, company_name, exchange, sector, display_order) VALUES
('D05', 'DBS Group', 'SGX', 'Finance', 1),
('O39', 'OCBC Bank', 'SGX', 'Finance', 2),
('U11', 'UOB', 'SGX', 'Finance', 3),
('Z74', 'Singtel', 'SGX', 'Telecom', 4),
('C6L', 'Singapore Airlines', 'SGX', 'Airlines', 5),
('9CI', 'CapitaLand Investment', 'SGX', 'Real Estate', 6),
('A17U', 'CapitaLand Ascendas REIT', 'SGX', 'REIT', 7),
('S58', 'SATS', 'SGX', 'Industrials', 8),
('BN4', 'Keppel Corp', 'SGX', 'Industrials', 9),
('H78', 'Hongkong Land', 'SGX', 'Real Estate', 10),
('Y92', 'Thai Beverage', 'SGX', 'Consumer', 11),
('F34', 'Wilmar International', 'SGX', 'Agriculture', 12),
('S63', 'ST Engineering', 'SGX', 'Industrials', 13),
('V03', 'Venture Corp', 'SGX', 'Technology', 14),
('BS6', 'Yangzijiang Shipbuilding', 'SGX', 'Industrials', 15),
('M44U', 'Mapletree Logistics Trust', 'SGX', 'REIT', 16),
('N2IU', 'Mapletree Pan Asia Commercial Trust', 'SGX', 'REIT', 17),
('ME8U', 'Mapletree Industrial Trust', 'SGX', 'REIT', 18),
('S68', 'SGX Ltd', 'SGX', 'Finance', 19),
('CC3', 'StarHub', 'SGX', 'Telecom', 20)
ON CONFLICT (ticker, exchange) DO UPDATE SET company_name = EXCLUDED.company_name, sector = EXCLUDED.sector, display_order = EXCLUDED.display_order;

INSERT INTO datapai.stock_directory (symbol, name, exchange, sector, lang) VALUES
('D05', 'DBS Group Holdings', 'SGX', 'Finance', 'en'),
('O39', 'Oversea-Chinese Banking Corp', 'SGX', 'Finance', 'en'),
('U11', 'United Overseas Bank', 'SGX', 'Finance', 'en'),
('Z74', 'Singapore Telecommunications', 'SGX', 'Telecom', 'en'),
('C6L', 'Singapore Airlines', 'SGX', 'Airlines', 'en'),
('9CI', 'CapitaLand Investment', 'SGX', 'Real Estate', 'en'),
('A17U', 'CapitaLand Ascendas REIT', 'SGX', 'REIT', 'en'),
('S58', 'SATS Ltd', 'SGX', 'Industrials', 'en'),
('BN4', 'Keppel Corp', 'SGX', 'Industrials', 'en'),
('H78', 'Hongkong Land Holdings', 'SGX', 'Real Estate', 'en'),
('Y92', 'Thai Beverage Public Co', 'SGX', 'Consumer', 'en'),
('F34', 'Wilmar International', 'SGX', 'Agriculture', 'en'),
('S63', 'ST Engineering', 'SGX', 'Industrials', 'en'),
('V03', 'Venture Corp', 'SGX', 'Technology', 'en'),
('BS6', 'Yangzijiang Shipbuilding Holdings', 'SGX', 'Industrials', 'en'),
('M44U', 'Mapletree Logistics Trust', 'SGX', 'REIT', 'en'),
('N2IU', 'Mapletree Pan Asia Commercial Trust', 'SGX', 'REIT', 'en'),
('ME8U', 'Mapletree Industrial Trust', 'SGX', 'REIT', 'en'),
('S68', 'Singapore Exchange Ltd', 'SGX', 'Finance', 'en'),
('CC3', 'StarHub Ltd', 'SGX', 'Telecom', 'en'),
-- Chinese Simplified names
('D05', 'DBS Group Holdings', 'SGX', 'Finance', 'zh'),
('O39', 'OCBC Bank', 'SGX', 'Finance', 'zh'),
('U11', 'UOB', 'SGX', 'Finance', 'zh'),
('Z74', 'Singtel', 'SGX', 'Telecom', 'zh'),
('C6L', 'Singapore Airlines', 'SGX', 'Airlines', 'zh'),
('9CI', 'CapitaLand Investment', 'SGX', 'Real Estate', 'zh'),
('A17U', 'CapitaLand Ascendas REIT', 'SGX', 'REIT', 'zh'),
('S58', 'SATS Ltd', 'SGX', 'Industrials', 'zh'),
('BN4', 'Keppel Corp', 'SGX', 'Industrials', 'zh'),
('H78', 'Hongkong Land Holdings', 'SGX', 'Real Estate', 'zh'),
-- Chinese Traditional names
('D05', 'DBS Group Holdings', 'SGX', 'Finance', 'zh-TW'),
('O39', 'OCBC Bank', 'SGX', 'Finance', 'zh-TW'),
('U11', 'UOB', 'SGX', 'Finance', 'zh-TW'),
('Z74', 'Singtel', 'SGX', 'Telecom', 'zh-TW'),
('C6L', 'Singapore Airlines', 'SGX', 'Airlines', 'zh-TW')
ON CONFLICT (symbol, exchange, lang) DO UPDATE SET name = EXCLUDED.name, sector = EXCLUDED.sector;

-- 4. i18n labels for Singapore market
INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category) VALUES
('nav_singapore', 'en', 'Singapore', 'nav'),
('nav_singapore', 'zh', '新加坡', 'nav'),
('nav_singapore', 'zh-TW', '新加坡', 'nav'),
('nav_singapore', 'ja', 'シンガポール', 'nav'),
('nav_singapore', 'ko', '싱가포르', 'nav'),
('nav_singapore', 'vi', 'Singapore', 'nav'),
('nav_singapore', 'th', 'สิงคโปร์', 'nav'),
('nav_singapore', 'ms', 'Singapura', 'nav'),
('hero_title_sgx', 'en', 'Singapore Exchange (SGX)', 'hero'),
('hero_title_sgx', 'zh', '新加坡交易所 (SGX)', 'hero'),
('hero_title_sgx', 'zh-TW', '新加坡交易所 (SGX)', 'hero'),
('hero_title_sgx', 'ja', 'シンガポール取引所 (SGX)', 'hero'),
('hero_title_sgx', 'ko', '싱가포르 거래소 (SGX)', 'hero'),
('hero_title_sgx', 'vi', 'San Giao dich Chung khoan Singapore (SGX)', 'hero'),
('hero_title_sgx', 'th', 'ตลาดหลักทรัพย์สิงคโปร์ (SGX)', 'hero'),
('hero_title_sgx', 'ms', 'Bursa Saham Singapura (SGX)', 'hero'),
('section_sgx_stocks', 'en', 'Top Stocks', 'section'),
('section_sgx_stocks', 'zh', '热门股票', 'section'),
('section_sgx_stocks', 'zh-TW', '熱門股票', 'section'),
('section_sgx_stocks', 'ja', '注目銘柄', 'section'),
('section_sgx_stocks', 'ko', '인기 종목', 'section'),
('section_sgx_stocks', 'vi', 'Co phieu noi bat', 'section'),
('section_sgx_stocks', 'th', 'หุ้นยอดนิยม', 'section'),
('section_sgx_stocks', 'ms', 'Saham Teratas', 'section'),
('section_sgx_label', 'en', '🇸🇬 SGX', 'section'),
('section_sgx_label', 'zh', '🇸🇬 新加坡交易所', 'section'),
('section_sgx_label', 'zh-TW', '🇸🇬 新加坡交易所', 'section'),
('section_sgx_label', 'ja', '🇸🇬 SGX', 'section'),
('section_sgx_label', 'ko', '🇸🇬 SGX', 'section'),
('section_sgx_label', 'vi', '🇸🇬 SGX', 'section'),
('section_sgx_label', 'th', '🇸🇬 SGX', 'section'),
('section_sgx_label', 'ms', '🇸🇬 SGX', 'section')
ON CONFLICT (label_key, lang) DO UPDATE SET text = EXCLUDED.text, category = EXCLUDED.category;
