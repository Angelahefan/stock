-- =============================================================================
-- 006_ticker_universe.sql  —  Registered ticker universe (replaces hardcoded lists)
-- =============================================================================
--
-- APPLY:
--   docker exec -i lightdash_db_1 psql -U postgres -d postgres < scripts/migrations/006_ticker_universe.sql
--
-- PURPOSE:
--   Central registry of all monitored tickers. Daily refresh scripts read from
--   this table instead of hardcoded lists. New tickers can be added via SQL
--   without code changes.
-- =============================================================================

CREATE TABLE IF NOT EXISTS datapai.ticker_universe (
    ticker      TEXT NOT NULL,               -- e.g. "BHP" (without .AX suffix)
    exchange    TEXT NOT NULL DEFAULT 'US',   -- "US" or "ASX"
    yf_symbol   TEXT NOT NULL,               -- yfinance symbol: "BHP.AX" for ASX, "AAPL" for US
    company_name TEXT,
    sector      TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    source      TEXT DEFAULT 'manual',       -- how it was added: manual, asx_csv, nasdaq_api
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (ticker, exchange)
);

CREATE INDEX IF NOT EXISTS idx_ticker_universe_active
    ON datapai.ticker_universe (exchange, is_active) WHERE is_active = TRUE;

COMMENT ON TABLE datapai.ticker_universe IS
    'Central registry of all monitored tickers. Daily EOD refresh scripts read active tickers from here.';
