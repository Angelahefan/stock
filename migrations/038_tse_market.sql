-- ============================================================================
-- 038_tse_market.sql — Add Tokyo Stock Exchange (TSE) market support
-- ============================================================================

-- 1. Per-market intraday table
CREATE TABLE IF NOT EXISTS datapai.ohlcv_intraday_tse (
    ticker      TEXT NOT NULL,
    ts          TIMESTAMP NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION,
    volume      BIGINT,
    exchange    TEXT DEFAULT 'TSE',
    source      TEXT DEFAULT 'yfinance',
    inserted_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (ticker, ts)
);

CREATE TABLE IF NOT EXISTS datapai.ohlcv_intraday_tse_archive (
    LIKE datapai.ohlcv_intraday_tse INCLUDING ALL
);

-- 2. Recreate the unified view to include TSE
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
    UNION ALL SELECT * FROM datapai.ohlcv_intraday_sgx
    UNION ALL SELECT * FROM datapai.ohlcv_intraday_tse;

-- 3. Seed featured TSE stocks into ticker_universe + market_demo_stocks + stock_directory
-- Top 20 Japanese blue chips by market cap
INSERT INTO datapai.ticker_universe (ticker, yf_symbol, exchange, is_active, is_featured) VALUES
('7203', '7203.T', 'TSE', true, true),
('6758', '6758.T', 'TSE', true, true),
('9984', '9984.T', 'TSE', true, true),
('6861', '6861.T', 'TSE', true, true),
('8306', '8306.T', 'TSE', true, true),
('6098', '6098.T', 'TSE', true, true),
('9432', '9432.T', 'TSE', true, true),
('6367', '6367.T', 'TSE', true, true),
('8035', '8035.T', 'TSE', true, true),
('7741', '7741.T', 'TSE', true, true),
('4063', '4063.T', 'TSE', true, true),
('6501', '6501.T', 'TSE', true, true),
('7974', '7974.T', 'TSE', true, true),
('4502', '4502.T', 'TSE', true, true),
('8766', '8766.T', 'TSE', true, true),
('9433', '9433.T', 'TSE', true, true),
('6902', '6902.T', 'TSE', true, true),
('3382', '3382.T', 'TSE', true, true),
('4568', '4568.T', 'TSE', true, true),
('6954', '6954.T', 'TSE', true, true)
ON CONFLICT (ticker, exchange) DO UPDATE SET yf_symbol = EXCLUDED.yf_symbol, is_active = true, is_featured = true;

INSERT INTO datapai.market_demo_stocks (ticker, company_name, exchange, sector, display_order) VALUES
('7203', 'Toyota Motor', 'TSE', 'Automotive', 1),
('6758', 'Sony Group', 'TSE', 'Technology', 2),
('9984', 'SoftBank Group', 'TSE', 'Technology', 3),
('6861', 'Keyence', 'TSE', 'Technology', 4),
('8306', 'Mitsubishi UFJ Financial', 'TSE', 'Finance', 5),
('6098', 'Recruit Holdings', 'TSE', 'Industrials', 6),
('9432', 'NTT', 'TSE', 'Telecom', 7),
('6367', 'Daikin Industries', 'TSE', 'Industrials', 8),
('8035', 'Tokyo Electron', 'TSE', 'Technology', 9),
('7741', 'HOYA Corp', 'TSE', 'Healthcare', 10),
('4063', 'Shin-Etsu Chemical', 'TSE', 'Materials', 11),
('6501', 'Hitachi', 'TSE', 'Industrials', 12),
('7974', 'Nintendo', 'TSE', 'Technology', 13),
('4502', 'Takeda Pharmaceutical', 'TSE', 'Healthcare', 14),
('8766', 'Tokio Marine Holdings', 'TSE', 'Finance', 15),
('9433', 'KDDI', 'TSE', 'Telecom', 16),
('6902', 'DENSO', 'TSE', 'Automotive', 17),
('3382', 'Seven & i Holdings', 'TSE', 'Consumer', 18),
('4568', 'Daiichi Sankyo', 'TSE', 'Healthcare', 19),
('6954', 'Fanuc', 'TSE', 'Industrials', 20)
ON CONFLICT (ticker, exchange) DO UPDATE SET company_name = EXCLUDED.company_name, sector = EXCLUDED.sector, display_order = EXCLUDED.display_order;

INSERT INTO datapai.stock_directory (symbol, name, exchange, sector, lang) VALUES
('7203', 'Toyota Motor Corp', 'TSE', 'Automotive', 'en'),
('6758', 'Sony Group Corp', 'TSE', 'Technology', 'en'),
('9984', 'SoftBank Group Corp', 'TSE', 'Technology', 'en'),
('6861', 'Keyence Corp', 'TSE', 'Technology', 'en'),
('8306', 'Mitsubishi UFJ Financial Group', 'TSE', 'Finance', 'en'),
('6098', 'Recruit Holdings Co', 'TSE', 'Industrials', 'en'),
('9432', 'Nippon Telegraph and Telephone', 'TSE', 'Telecom', 'en'),
('6367', 'Daikin Industries Ltd', 'TSE', 'Industrials', 'en'),
('8035', 'Tokyo Electron Ltd', 'TSE', 'Technology', 'en'),
('7741', 'HOYA Corp', 'TSE', 'Healthcare', 'en'),
('4063', 'Shin-Etsu Chemical Co', 'TSE', 'Materials', 'en'),
('6501', 'Hitachi Ltd', 'TSE', 'Industrials', 'en'),
('7974', 'Nintendo Co Ltd', 'TSE', 'Technology', 'en'),
('4502', 'Takeda Pharmaceutical Co', 'TSE', 'Healthcare', 'en'),
('8766', 'Tokio Marine Holdings Inc', 'TSE', 'Finance', 'en'),
('9433', 'KDDI Corp', 'TSE', 'Telecom', 'en'),
('6902', 'DENSO Corp', 'TSE', 'Automotive', 'en'),
('3382', 'Seven & i Holdings Co', 'TSE', 'Consumer', 'en'),
('4568', 'Daiichi Sankyo Co', 'TSE', 'Healthcare', 'en'),
('6954', 'Fanuc Corp', 'TSE', 'Industrials', 'en'),
-- Japanese names
('7203', 'トヨタ自動車', 'TSE', 'Automotive', 'ja'),
('6758', 'ソニーグループ', 'TSE', 'Technology', 'ja'),
('9984', 'ソフトバンクグループ', 'TSE', 'Technology', 'ja'),
('6861', 'キーエンス', 'TSE', 'Technology', 'ja'),
('8306', '三菱UFJフィナンシャル', 'TSE', 'Finance', 'ja'),
('6098', 'リクルートホールディングス', 'TSE', 'Industrials', 'ja'),
('9432', '日本電信電話(NTT)', 'TSE', 'Telecom', 'ja'),
('6367', 'ダイキン工業', 'TSE', 'Industrials', 'ja'),
('8035', '東京エレクトロン', 'TSE', 'Technology', 'ja'),
('7741', 'HOYA', 'TSE', 'Healthcare', 'ja'),
('4063', '信越化学工業', 'TSE', 'Materials', 'ja'),
('6501', '日立製作所', 'TSE', 'Industrials', 'ja'),
('7974', '任天堂', 'TSE', 'Technology', 'ja'),
('4502', '武田薬品工業', 'TSE', 'Healthcare', 'ja'),
('8766', '東京海上ホールディングス', 'TSE', 'Finance', 'ja'),
('9433', 'KDDI', 'TSE', 'Telecom', 'ja'),
('6902', 'デンソー', 'TSE', 'Automotive', 'ja'),
('3382', 'セブン&アイ', 'TSE', 'Consumer', 'ja'),
('4568', '第一三共', 'TSE', 'Healthcare', 'ja'),
('6954', 'ファナック', 'TSE', 'Industrials', 'ja'),
-- Chinese Simplified names
('7203', 'Toyota Motor Corp', 'TSE', 'Automotive', 'zh'),
('6758', 'Sony Group Corp', 'TSE', 'Technology', 'zh'),
('9984', 'SoftBank Group Corp', 'TSE', 'Technology', 'zh'),
('6861', 'Keyence Corp', 'TSE', 'Technology', 'zh'),
('8306', 'Mitsubishi UFJ Financial Group', 'TSE', 'Finance', 'zh'),
('6098', 'Recruit Holdings Co', 'TSE', 'Industrials', 'zh'),
('9432', 'NTT', 'TSE', 'Telecom', 'zh'),
('6367', 'Daikin Industries Ltd', 'TSE', 'Industrials', 'zh'),
('8035', 'Tokyo Electron Ltd', 'TSE', 'Technology', 'zh'),
('7741', 'HOYA Corp', 'TSE', 'Healthcare', 'zh'),
-- Chinese Traditional names
('7203', 'Toyota Motor Corp', 'TSE', 'Automotive', 'zh-TW'),
('6758', 'Sony Group Corp', 'TSE', 'Technology', 'zh-TW'),
('9984', 'SoftBank Group Corp', 'TSE', 'Technology', 'zh-TW'),
('6861', 'Keyence Corp', 'TSE', 'Technology', 'zh-TW'),
('8306', 'Mitsubishi UFJ Financial Group', 'TSE', 'Finance', 'zh-TW')
ON CONFLICT (symbol, exchange, lang) DO UPDATE SET name = EXCLUDED.name, sector = EXCLUDED.sector;

-- 4. i18n labels for Japan market
INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category) VALUES
('nav_japan', 'en', 'Japan', 'nav'),
('nav_japan', 'zh', '日本', 'nav'),
('nav_japan', 'zh-TW', '日本', 'nav'),
('nav_japan', 'ja', '日本', 'nav'),
('nav_japan', 'ko', '일본', 'nav'),
('nav_japan', 'vi', 'Nhat Ban', 'nav'),
('nav_japan', 'th', 'ญี่ปุ่น', 'nav'),
('nav_japan', 'ms', 'Jepun', 'nav'),
('hero_title_tse', 'en', 'Tokyo Stock Exchange (TSE)', 'hero'),
('hero_title_tse', 'zh', '东京证券交易所 (TSE)', 'hero'),
('hero_title_tse', 'zh-TW', '東京證券交易所 (TSE)', 'hero'),
('hero_title_tse', 'ja', '東京証券取引所 (TSE)', 'hero'),
('hero_title_tse', 'ko', '도쿄 증권거래소 (TSE)', 'hero'),
('hero_title_tse', 'vi', 'San Giao dich Chung khoan Tokyo (TSE)', 'hero'),
('hero_title_tse', 'th', 'ตลาดหลักทรัพย์โตเกียว (TSE)', 'hero'),
('hero_title_tse', 'ms', 'Bursa Saham Tokyo (TSE)', 'hero'),
('section_tse_stocks', 'en', 'Top Stocks', 'section'),
('section_tse_stocks', 'zh', '热门股票', 'section'),
('section_tse_stocks', 'zh-TW', '熱門股票', 'section'),
('section_tse_stocks', 'ja', '注目銘柄', 'section'),
('section_tse_stocks', 'ko', '인기 종목', 'section'),
('section_tse_stocks', 'vi', 'Co phieu noi bat', 'section'),
('section_tse_stocks', 'th', 'หุ้นยอดนิยม', 'section'),
('section_tse_stocks', 'ms', 'Saham Teratas', 'section'),
('section_tse_label', 'en', '🇯🇵 TSE', 'section'),
('section_tse_label', 'zh', '🇯🇵 东京证券交易所', 'section'),
('section_tse_label', 'zh-TW', '🇯🇵 東京證券交易所', 'section'),
('section_tse_label', 'ja', '🇯🇵 TSE', 'section'),
('section_tse_label', 'ko', '🇯🇵 TSE', 'section'),
('section_tse_label', 'vi', '🇯🇵 TSE', 'section'),
('section_tse_label', 'th', '🇯🇵 TSE', 'section'),
('section_tse_label', 'ms', '🇯🇵 TSE', 'section')
ON CONFLICT (label_key, lang) DO UPDATE SET text = EXCLUDED.text, category = EXCLUDED.category;
