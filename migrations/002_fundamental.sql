-- =============================================================================
-- 002_fundamental.sql  —  Fundamental Analysis tables
-- =============================================================================
--
-- APPLY:
--   psql $DATABASE_URL -f scripts/migrations/002_fundamental.sql
--
-- TABLES:
--   datapai.fundamental_snapshot  — latest fundamental snapshot per ticker
--   datapai.fundamental_history   — time series of reported financials
-- =============================================================================

-- ── fundamental_snapshot ─────────────────────────────────────────────────────
-- One row per (ticker, exchange). Upserted on every nightly compute run.
CREATE TABLE IF NOT EXISTS datapai.fundamental_snapshot (
    -- identity
    ticker               VARCHAR(20)  NOT NULL,
    exchange             VARCHAR(10)  NOT NULL,
    company_name         VARCHAR(255),
    sector               VARCHAR(100),
    industry             VARCHAR(100),
    currency             VARCHAR(10),

    -- size / enterprise value
    market_cap           BIGINT,
    enterprise_value     BIGINT,

    -- valuation multiples
    pe_ratio             DOUBLE PRECISION,
    forward_pe           DOUBLE PRECISION,
    peg_ratio            DOUBLE PRECISION,
    pb_ratio             DOUBLE PRECISION,
    ps_ratio             DOUBLE PRECISION,
    ev_ebitda            DOUBLE PRECISION,
    ev_revenue           DOUBLE PRECISION,

    -- profitability
    gross_margin         DOUBLE PRECISION,
    operating_margin     DOUBLE PRECISION,
    net_margin           DOUBLE PRECISION,
    roe                  DOUBLE PRECISION,
    roa                  DOUBLE PRECISION,
    roic                 DOUBLE PRECISION,

    -- growth
    revenue_yoy          DOUBLE PRECISION,
    earnings_yoy         DOUBLE PRECISION,
    revenue_growth_5yr   DOUBLE PRECISION,
    eps_growth_5yr       DOUBLE PRECISION,

    -- financial health
    current_ratio        DOUBLE PRECISION,
    quick_ratio          DOUBLE PRECISION,
    debt_to_equity       DOUBLE PRECISION,
    interest_coverage    DOUBLE PRECISION,
    total_cash           BIGINT,
    total_debt           BIGINT,
    net_cash             BIGINT,

    -- cash flow
    free_cash_flow       BIGINT,
    fcf_per_share        DOUBLE PRECISION,
    fcf_yield            DOUBLE PRECISION,
    operating_cf_margin  DOUBLE PRECISION,

    -- dividend
    dividend_yield       DOUBLE PRECISION,
    payout_ratio         DOUBLE PRECISION,

    -- market / risk
    beta                 DOUBLE PRECISION,
    short_ratio          DOUBLE PRECISION,
    next_earnings_date   DATE,

    -- component scores
    valuation_score      DOUBLE PRECISION,   -- -1.0 to +1.0  (cheap → expensive)
    quality_score        DOUBLE PRECISION,   --  0.0 to  1.0
    growth_score         DOUBLE PRECISION,   --  0.0 to  1.0
    macro_score          DOUBLE PRECISION,   -- -1.0 to +1.0  (tailwind → headwind)

    -- composite
    fundamental_score    DOUBLE PRECISION,   -- -1.0 to +1.0
    fundamental_signal   VARCHAR(20),        -- STRONG_BUY / BUY / NEUTRAL / SELL / STRONG_SELL

    -- analyst consensus (Gemini grounding)
    analyst_consensus    VARCHAR(20),        -- STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL
    analyst_target_price DOUBLE PRECISION,
    analyst_upside_pct   DOUBLE PRECISION,

    -- macro / geopolitical context (macro_agent)
    macro_summary        TEXT,
    macro_factors        TEXT[],             -- e.g. {"Fed rate cuts supportive", "China tariffs headwind"}
    geopolitical_flags   TEXT[],             -- e.g. {"US-China trade war", "Middle East supply risk"}
    tech_disruption_risk VARCHAR(20),        -- LOW / MEDIUM / HIGH

    -- LLM narrative
    fundamental_summary  TEXT,
    key_strengths        TEXT[],
    key_risks            TEXT[],

    -- metadata
    source               VARCHAR(50),
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (ticker, exchange)
);

-- Screener index: filter by exchange + signal, order by score
CREATE INDEX IF NOT EXISTS idx_fundamental_snapshot_signal
    ON datapai.fundamental_snapshot (exchange, fundamental_signal, fundamental_score DESC);

-- Sector screener
CREATE INDEX IF NOT EXISTS idx_fundamental_snapshot_sector
    ON datapai.fundamental_snapshot (exchange, sector, fundamental_score DESC);

COMMENT ON TABLE datapai.fundamental_snapshot IS
    'Latest fundamental analysis snapshot per ticker. Upserted nightly by compute_fundamental_daily.py';

-- ── fundamental_history ──────────────────────────────────────────────────────
-- Time series of reported financials (annual + quarterly).
-- Populated from yfinance income_stmt / balance_sheet / cashflow DataFrames.
CREATE TABLE IF NOT EXISTS datapai.fundamental_history (
    ticker               VARCHAR(20)  NOT NULL,
    exchange             VARCHAR(10)  NOT NULL,
    period_end           DATE         NOT NULL,
    period_type          VARCHAR(10)  NOT NULL,  -- 'annual' | 'quarterly'

    -- income statement
    revenue              BIGINT,
    gross_profit         BIGINT,
    operating_income     BIGINT,
    net_income           BIGINT,
    ebitda               BIGINT,
    eps                  DOUBLE PRECISION,

    -- cash flow
    free_cash_flow       BIGINT,
    operating_cash_flow  BIGINT,
    capex                BIGINT,

    -- balance sheet
    total_assets         BIGINT,
    total_debt           BIGINT,
    shareholders_equity  BIGINT,
    cash_and_equivalents BIGINT,

    -- YoY growth (computed)
    revenue_yoy          DOUBLE PRECISION,
    earnings_yoy         DOUBLE PRECISION,
    fcf_yoy              DOUBLE PRECISION,

    source               VARCHAR(50),
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (ticker, exchange, period_end, period_type)
);

CREATE INDEX IF NOT EXISTS idx_fundamental_history_ticker
    ON datapai.fundamental_history (ticker, exchange, period_type, period_end DESC);

COMMENT ON TABLE datapai.fundamental_history IS
    'Historical reported financials (annual + quarterly) per ticker. Sourced from yfinance.';
