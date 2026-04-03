-- ============================================================================
-- 036_twse_market.sql — Add Taiwan Stock Exchange (TWSE) market support
-- ============================================================================

-- 1. Per-market intraday table
CREATE TABLE IF NOT EXISTS datapai.ohlcv_intraday_twse (
    ticker      TEXT NOT NULL,
    ts          TIMESTAMP NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION,
    volume      BIGINT,
    exchange    TEXT DEFAULT 'TWSE',
    source      TEXT DEFAULT 'yfinance',
    inserted_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (ticker, ts)
);

CREATE TABLE IF NOT EXISTS datapai.ohlcv_intraday_twse_archive (
    LIKE datapai.ohlcv_intraday_twse INCLUDING ALL
);

-- 2. Recreate the unified view to include TWSE
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
    UNION ALL SELECT * FROM datapai.ohlcv_intraday_twse;

-- 3. Seed featured TWSE stocks into ticker_universe + market_demo_stocks + stock_directory
-- Top 30 Taiwan blue chips by market cap
INSERT INTO datapai.ticker_universe (ticker, yf_symbol, exchange, is_active, is_featured) VALUES
('2330', '2330.TW', 'TWSE', true, true),
('2317', '2317.TW', 'TWSE', true, true),
('2454', '2454.TW', 'TWSE', true, true),
('2308', '2308.TW', 'TWSE', true, true),
('2382', '2382.TW', 'TWSE', true, true),
('2881', '2881.TW', 'TWSE', true, true),
('2882', '2882.TW', 'TWSE', true, true),
('2303', '2303.TW', 'TWSE', true, true),
('2891', '2891.TW', 'TWSE', true, true),
('2886', '2886.TW', 'TWSE', true, true),
('2884', '2884.TW', 'TWSE', true, true),
('3711', '3711.TW', 'TWSE', true, true),
('2412', '2412.TW', 'TWSE', true, true),
('2357', '2357.TW', 'TWSE', true, true),
('3231', '3231.TW', 'TWSE', true, true),
('2002', '2002.TW', 'TWSE', true, true),
('1301', '1301.TW', 'TWSE', true, true),
('1303', '1303.TW', 'TWSE', true, true),
('2892', '2892.TW', 'TWSE', true, true),
('5880', '5880.TW', 'TWSE', true, true)
ON CONFLICT (ticker, exchange) DO UPDATE SET yf_symbol = EXCLUDED.yf_symbol, is_active = true, is_featured = true;

INSERT INTO datapai.market_demo_stocks (ticker, company_name, exchange, sector, display_order) VALUES
('2330', 'TSMC', 'TWSE', 'Semiconductors', 1),
('2317', 'Hon Hai (Foxconn)', 'TWSE', 'Electronics', 2),
('2454', 'MediaTek', 'TWSE', 'Semiconductors', 3),
('2308', 'Delta Electronics', 'TWSE', 'Electronics', 4),
('2382', 'Quanta Computer', 'TWSE', 'Technology', 5),
('2881', 'Fubon Financial', 'TWSE', 'Finance', 6),
('2882', 'Cathay Financial', 'TWSE', 'Finance', 7),
('2303', 'United Microelectronics', 'TWSE', 'Semiconductors', 8),
('2891', 'CTBC Financial', 'TWSE', 'Finance', 9),
('2886', 'Mega Financial', 'TWSE', 'Finance', 10),
('2884', 'E.SUN Financial', 'TWSE', 'Finance', 11),
('3711', 'ASE Technology', 'TWSE', 'Semiconductors', 12),
('2412', 'Chunghwa Telecom', 'TWSE', 'Telecom', 13),
('2357', 'ASUSTEK Computer', 'TWSE', 'Technology', 14),
('3231', 'Wistron', 'TWSE', 'Technology', 15),
('2002', 'China Steel', 'TWSE', 'Materials', 16),
('1301', 'Formosa Plastics', 'TWSE', 'Materials', 17),
('1303', 'Nan Ya Plastics', 'TWSE', 'Materials', 18),
('2892', 'First Financial', 'TWSE', 'Finance', 19),
('5880', 'Taiwan Cooperative Financial', 'TWSE', 'Finance', 20)
ON CONFLICT (ticker, exchange) DO UPDATE SET company_name = EXCLUDED.company_name, sector = EXCLUDED.sector, display_order = EXCLUDED.display_order;

INSERT INTO datapai.stock_directory (symbol, name, exchange, sector, lang) VALUES
('2330', 'TSMC', 'TWSE', 'Semiconductors', 'en'),
('2317', 'Hon Hai Precision (Foxconn)', 'TWSE', 'Electronics', 'en'),
('2454', 'MediaTek Inc', 'TWSE', 'Semiconductors', 'en'),
('2308', 'Delta Electronics', 'TWSE', 'Electronics', 'en'),
('2382', 'Quanta Computer', 'TWSE', 'Technology', 'en'),
('2881', 'Fubon Financial Holding', 'TWSE', 'Finance', 'en'),
('2882', 'Cathay Financial Holding', 'TWSE', 'Finance', 'en'),
('2303', 'United Microelectronics Corp', 'TWSE', 'Semiconductors', 'en'),
('2891', 'CTBC Financial Holding', 'TWSE', 'Finance', 'en'),
('2886', 'Mega Financial Holding', 'TWSE', 'Finance', 'en'),
('2884', 'E.SUN Financial Holding', 'TWSE', 'Finance', 'en'),
('3711', 'ASE Technology Holding', 'TWSE', 'Semiconductors', 'en'),
('2412', 'Chunghwa Telecom', 'TWSE', 'Telecom', 'en'),
('2357', 'ASUSTEK Computer', 'TWSE', 'Technology', 'en'),
('3231', 'Wistron Corp', 'TWSE', 'Technology', 'en'),
('2002', 'China Steel Corp', 'TWSE', 'Materials', 'en'),
('1301', 'Formosa Plastics Corp', 'TWSE', 'Materials', 'en'),
('1303', 'Nan Ya Plastics Corp', 'TWSE', 'Materials', 'en'),
('2892', 'First Financial Holding', 'TWSE', 'Finance', 'en'),
('5880', 'Taiwan Cooperative Financial', 'TWSE', 'Finance', 'en'),
-- Chinese names
('2330', '台積電', 'TWSE', 'Semiconductors', 'zh'),
('2317', '鴻海精密', 'TWSE', 'Electronics', 'zh'),
('2454', '聯發科', 'TWSE', 'Semiconductors', 'zh'),
('2308', '台達電', 'TWSE', 'Electronics', 'zh'),
('2382', '廣達', 'TWSE', 'Technology', 'zh'),
('2881', '富邦金控', 'TWSE', 'Finance', 'zh'),
('2882', '國泰金控', 'TWSE', 'Finance', 'zh'),
('2303', '聯電', 'TWSE', 'Semiconductors', 'zh'),
('2891', '中信金控', 'TWSE', 'Finance', 'zh'),
('2886', '兆豐金控', 'TWSE', 'Finance', 'zh'),
('2330', '台積電', 'TWSE', 'Semiconductors', 'zh-TW'),
('2317', '鴻海精密', 'TWSE', 'Electronics', 'zh-TW'),
('2454', '聯發科', 'TWSE', 'Semiconductors', 'zh-TW'),
('2308', '台達電', 'TWSE', 'Electronics', 'zh-TW'),
('2382', '廣達', 'TWSE', 'Technology', 'zh-TW')
ON CONFLICT (symbol, exchange, lang) DO UPDATE SET name = EXCLUDED.name, sector = EXCLUDED.sector;

-- 4. i18n labels for Taiwan market
INSERT INTO datapai.sys_lang_labels (label_key, lang, text, category) VALUES
('nav_taiwan', 'en', 'Taiwan', 'nav'),
('nav_taiwan', 'zh', '台湾', 'nav'),
('nav_taiwan', 'zh-TW', '台灣', 'nav'),
('nav_taiwan', 'ja', '台湾', 'nav'),
('nav_taiwan', 'ko', '대만', 'nav'),
('nav_taiwan', 'vi', 'Đài Loan', 'nav'),
('nav_taiwan', 'th', 'ไต้หวัน', 'nav'),
('nav_taiwan', 'ms', 'Taiwan', 'nav'),
('hero_title_twse', 'en', 'Taiwan Stock Exchange (TWSE)', 'hero'),
('hero_title_twse', 'zh', '台湾证券交易所 (TWSE)', 'hero'),
('hero_title_twse', 'zh-TW', '台灣證券交易所 (TWSE)', 'hero'),
('hero_title_twse', 'ja', '台湾証券取引所 (TWSE)', 'hero'),
('hero_title_twse', 'ko', '대만 증권거래소 (TWSE)', 'hero'),
('hero_title_twse', 'vi', 'Sàn Giao dịch Chứng khoán Đài Loan (TWSE)', 'hero'),
('hero_title_twse', 'th', 'ตลาดหลักทรัพย์ไต้หวัน (TWSE)', 'hero'),
('hero_title_twse', 'ms', 'Bursa Saham Taiwan (TWSE)', 'hero'),
('section_twse_stocks', 'en', 'Top Stocks', 'section'),
('section_twse_stocks', 'zh', '热门股票', 'section'),
('section_twse_stocks', 'zh-TW', '熱門股票', 'section'),
('section_twse_stocks', 'ja', '注目銘柄', 'section'),
('section_twse_stocks', 'ko', '인기 종목', 'section'),
('section_twse_stocks', 'vi', 'Cổ phiếu nổi bật', 'section'),
('section_twse_stocks', 'th', 'หุ้นยอดนิยม', 'section'),
('section_twse_stocks', 'ms', 'Saham Teratas', 'section'),
('section_twse_label', 'en', '🇹🇼 TWSE', 'section'),
('section_twse_label', 'zh', '🇹🇼 台灣證交所', 'section'),
('section_twse_label', 'zh-TW', '🇹🇼 台灣證交所', 'section'),
('section_twse_label', 'ja', '🇹🇼 TWSE', 'section'),
('section_twse_label', 'ko', '🇹🇼 TWSE', 'section'),
('section_twse_label', 'vi', '🇹🇼 TWSE', 'section'),
('section_twse_label', 'th', '🇹🇼 TWSE', 'section'),
('section_twse_label', 'ms', '🇹🇼 TWSE', 'section')
ON CONFLICT (label_key, lang) DO UPDATE SET text = EXCLUDED.text, category = EXCLUDED.category;
