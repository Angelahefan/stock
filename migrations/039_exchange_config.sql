-- 039_exchange_config.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- DB-driven exchange configuration — replaces all hardcoded SUFFIX_MAP,
-- ALL_EXCHANGES, ASIA_EXCHANGES, US_EXCHANGES scattered across scripts.
--
-- Part of Platform Split Phase 1 (see docs/claude-build-spec-platform-split.md)
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. Exchange operational config (extends exchange_ref with runtime config)
CREATE TABLE IF NOT EXISTS datapai.exchange_config (
    exchange        TEXT PRIMARY KEY,
    yf_suffix       TEXT NOT NULL DEFAULT '',       -- '.AX', '.VN', '.HK', '' for US
    region          TEXT NOT NULL DEFAULT 'asia',    -- 'asia', 'us', 'europe'
    data_provider   TEXT NOT NULL DEFAULT 'yahoo',   -- 'yahoo', 'polygon', 'eodhd'
    batch_size      INTEGER NOT NULL DEFAULT 500,    -- yfinance download batch size
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE datapai.exchange_config IS
    'Single source of truth for exchange operational config. Replaces all hardcoded SUFFIX_MAP / ALL_EXCHANGES in Python code.';

INSERT INTO datapai.exchange_config (exchange, yf_suffix, region, data_provider, batch_size) VALUES
    ('US',   '',    'us',     'yahoo', 500),
    ('ASX',  '.AX', 'asia',   'yahoo', 200),
    ('HKEX', '.HK', 'asia',   'yahoo', 300),
    ('HOSE', '.VN', 'asia',   'yahoo', 200),
    ('HNX',  '.VN', 'asia',   'yahoo', 200),
    ('SET',  '.BK', 'asia',   'yahoo', 300),
    ('KLSE', '.KL', 'asia',   'yahoo', 300),
    ('IDX',  '.JK', 'asia',   'yahoo', 300),
    ('SSE',  '.SS', 'asia',   'yahoo', 300),
    ('SZSE', '.SZ', 'asia',   'yahoo', 300),
    ('LSE',  '.L',  'europe', 'yahoo', 300),
    ('TSE',  '.T',  'asia',   'yahoo', 300),
    ('TWSE', '.TW', 'asia',   'yahoo', 300),
    ('SGX',  '.SI', 'asia',   'yahoo', 300)
ON CONFLICT (exchange) DO NOTHING;


-- 2. Per-ticker sector/commodity/FX context config
--    Replaces hardcoded CONTEXT_MAP in agents/market_context.py
CREATE TABLE IF NOT EXISTS datapai.ticker_context_config (
    ticker          TEXT NOT NULL,
    exchange        TEXT NOT NULL,
    sector_etf      TEXT,
    sector_label    TEXT,
    commodity       TEXT,
    commodity_label TEXT,
    fx_pair         TEXT,
    fx_label        TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, exchange)
);

COMMENT ON TABLE datapai.ticker_context_config IS
    'Per-ticker sector ETF, commodity, and FX context for LLM enrichment. Replaces hardcoded CONTEXT_MAP in agents/market_context.py.';

-- Seed from current CONTEXT_MAP (~37 tickers)
INSERT INTO datapai.ticker_context_config (ticker, exchange, sector_etf, sector_label, commodity, commodity_label, fx_pair, fx_label) VALUES
    -- ASX Materials
    ('BHP',  'ASX', 'XMM.AX', 'ASX Materials',   'IRON30Y=EX', 'Iron Ore',    'AUDUSD=X', 'AUD/USD'),
    ('RIO',  'ASX', 'XMM.AX', 'ASX Materials',   'IRON30Y=EX', 'Iron Ore',    'AUDUSD=X', 'AUD/USD'),
    ('FMG',  'ASX', 'XMM.AX', 'ASX Materials',   'IRON30Y=EX', 'Iron Ore',    'AUDUSD=X', 'AUD/USD'),
    ('MIN',  'ASX', 'XMM.AX', 'ASX Materials',   'LIT',         'Lithium ETF', 'AUDUSD=X', 'AUD/USD'),
    ('S32',  'ASX', 'XMM.AX', 'ASX Materials',   'GC=F',        'Gold',        'AUDUSD=X', 'AUD/USD'),
    -- ASX Gold
    ('NST',  'ASX', 'XGD.AX', 'ASX Gold',        'GC=F',        'Gold',        'AUDUSD=X', 'AUD/USD'),
    ('NCM',  'ASX', 'XGD.AX', 'ASX Gold',        'GC=F',        'Gold',        'AUDUSD=X', 'AUD/USD'),
    ('EVN',  'ASX', 'XGD.AX', 'ASX Gold',        'GC=F',        'Gold',        'AUDUSD=X', 'AUD/USD'),
    -- ASX Energy
    ('WDS',  'ASX', 'XEJ.AX', 'ASX Energy',      'CL=F',        'Crude Oil',   'AUDUSD=X', 'AUD/USD'),
    ('STO',  'ASX', 'XEJ.AX', 'ASX Energy',      'CL=F',        'Crude Oil',   'AUDUSD=X', 'AUD/USD'),
    ('BPT',  'ASX', 'XEJ.AX', 'ASX Energy',      'CL=F',        'Crude Oil',   'AUDUSD=X', 'AUD/USD'),
    -- ASX Financials
    ('CBA',  'ASX', 'XFJ.AX', 'ASX Financials',  NULL,           NULL,          'AUDUSD=X', 'AUD/USD'),
    ('ANZ',  'ASX', 'XFJ.AX', 'ASX Financials',  NULL,           NULL,          'AUDUSD=X', 'AUD/USD'),
    ('NAB',  'ASX', 'XFJ.AX', 'ASX Financials',  NULL,           NULL,          'AUDUSD=X', 'AUD/USD'),
    ('WBC',  'ASX', 'XFJ.AX', 'ASX Financials',  NULL,           NULL,          'AUDUSD=X', 'AUD/USD'),
    ('MQG',  'ASX', 'XFJ.AX', 'ASX Financials',  NULL,           NULL,          'AUDUSD=X', 'AUD/USD'),
    -- ASX Healthcare
    ('CSL',  'ASX', 'XHJ.AX', 'ASX Healthcare',  NULL,           NULL,          'AUDUSD=X', 'AUD/USD'),
    ('RMD',  'ASX', 'XHJ.AX', 'ASX Healthcare',  NULL,           NULL,          'AUDUSD=X', 'AUD/USD'),
    -- ASX Technology
    ('WTC',  'ASX', 'XTJ.AX', 'ASX Technology',  NULL,           NULL,          'AUDUSD=X', 'AUD/USD'),
    ('XRO',  'ASX', 'XTJ.AX', 'ASX Technology',  NULL,           NULL,          'AUDUSD=X', 'AUD/USD'),
    -- US Semiconductors
    ('NVDA', 'US',  'SOXX',   'US Semiconductors', NULL,          NULL,          NULL,        NULL),
    ('AMD',  'US',  'SOXX',   'US Semiconductors', NULL,          NULL,          NULL,        NULL),
    ('INTC', 'US',  'SOXX',   'US Semiconductors', NULL,          NULL,          NULL,        NULL),
    ('QCOM', 'US',  'SOXX',   'US Semiconductors', NULL,          NULL,          NULL,        NULL),
    ('AVGO', 'US',  'SOXX',   'US Semiconductors', NULL,          NULL,          NULL,        NULL),
    ('MU',   'US',  'SOXX',   'US Semiconductors', NULL,          NULL,          NULL,        NULL),
    ('AMAT', 'US',  'SOXX',   'US Semiconductors', NULL,          NULL,          NULL,        NULL),
    -- US Mega-cap Tech
    ('AAPL', 'US',  'QQQ',    'US Mega-cap Tech',  NULL,          NULL,          NULL,        NULL),
    ('MSFT', 'US',  'QQQ',    'US Mega-cap Tech',  NULL,          NULL,          NULL,        NULL),
    ('GOOGL','US',  'QQQ',    'US Mega-cap Tech',  NULL,          NULL,          NULL,        NULL),
    ('AMZN', 'US',  'QQQ',    'US Mega-cap Tech',  NULL,          NULL,          NULL,        NULL),
    ('META', 'US',  'QQQ',    'US Mega-cap Tech',  NULL,          NULL,          NULL,        NULL),
    ('TSLA', 'US',  'XLY',    'US Consumer Discretionary / EV', 'LIT', 'Lithium ETF', NULL,  NULL),
    -- US Energy
    ('XOM',  'US',  'XLE',    'US Energy',         'CL=F',        'WTI Crude',   NULL,        NULL),
    ('CVX',  'US',  'XLE',    'US Energy',         'CL=F',        'WTI Crude',   NULL,        NULL),
    ('COP',  'US',  'XLE',    'US Energy',         'CL=F',        'WTI Crude',   NULL,        NULL),
    -- US Financials
    ('JPM',  'US',  'XLF',    'US Financials',     NULL,           NULL,          NULL,        NULL),
    ('BAC',  'US',  'XLF',    'US Financials',     NULL,           NULL,          NULL,        NULL),
    ('GS',   'US',  'XLF',    'US Financials',     NULL,           NULL,          NULL,        NULL),
    ('MS',   'US',  'XLF',    'US Financials',     NULL,           NULL,          NULL,        NULL)
ON CONFLICT (ticker, exchange) DO NOTHING;
