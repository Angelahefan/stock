-- 007_fundamental_lite.sql
-- Lightweight fundamental data for ALL tickers (yfinance only, no LLM).
-- Refreshed weekly. Used by multi-factor signal engine.

CREATE TABLE IF NOT EXISTS datapai.fundamental_lite (
    ticker          TEXT NOT NULL,
    exchange        TEXT NOT NULL,
    -- Identity
    company_name    TEXT,
    sector          TEXT,
    industry        TEXT,
    -- Size
    market_cap      BIGINT,
    -- Valuation
    pe_ratio        DOUBLE PRECISION,
    forward_pe      DOUBLE PRECISION,
    pb_ratio        DOUBLE PRECISION,
    ps_ratio        DOUBLE PRECISION,
    peg_ratio       DOUBLE PRECISION,
    ev_ebitda       DOUBLE PRECISION,
    -- Profitability
    gross_margin    DOUBLE PRECISION,
    operating_margin DOUBLE PRECISION,
    net_margin      DOUBLE PRECISION,
    roe             DOUBLE PRECISION,
    roa             DOUBLE PRECISION,
    -- Growth
    revenue_yoy     DOUBLE PRECISION,
    earnings_yoy    DOUBLE PRECISION,
    -- Financial health
    current_ratio   DOUBLE PRECISION,
    quick_ratio     DOUBLE PRECISION,
    debt_to_equity  DOUBLE PRECISION,
    -- Cash flow
    free_cash_flow  BIGINT,
    operating_cash_flow BIGINT,
    -- Dividend
    dividend_yield  DOUBLE PRECISION,
    payout_ratio    DOUBLE PRECISION,
    -- Risk
    beta            DOUBLE PRECISION,
    short_ratio     DOUBLE PRECISION,
    -- Analyst
    analyst_target  DOUBLE PRECISION,   -- consensus target price
    analyst_rating  TEXT,               -- buy/hold/sell string from yfinance
    num_analysts    INTEGER,
    -- Computed quality flags (rule-based, no LLM)
    is_profitable   BOOLEAN,            -- net_margin > 0
    is_growing      BOOLEAN,            -- revenue_yoy > 0
    is_healthy      BOOLEAN,            -- current_ratio > 1 AND debt_to_equity < 3
    quality_tier    TEXT,               -- A / B / C / D (simple rule-based)
    -- Meta
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, exchange)
);

-- Index for screener joins
CREATE INDEX IF NOT EXISTS idx_fundamental_lite_exchange ON datapai.fundamental_lite (exchange);
CREATE INDEX IF NOT EXISTS idx_fundamental_lite_quality ON datapai.fundamental_lite (exchange, quality_tier);
CREATE INDEX IF NOT EXISTS idx_fundamental_lite_sector ON datapai.fundamental_lite (exchange, sector);
