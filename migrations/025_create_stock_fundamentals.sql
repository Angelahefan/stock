-- ============================================================================
-- 025_create_stock_fundamentals.sql
-- Stock fundamentals snapshot — one row per ticker, updated weekly (full crawl)
-- and daily (price-derived fields only for popular stocks).
-- ============================================================================

CREATE TABLE IF NOT EXISTS datapai.stock_fundamentals (
    ticker          TEXT NOT NULL,
    exchange        TEXT NOT NULL,

    -- ── Valuation ──
    market_cap          BIGINT,          -- in local currency units
    enterprise_value    BIGINT,
    pe_ttm              NUMERIC(12,4),   -- trailing P/E
    pe_forward          NUMERIC(12,4),   -- forward P/E
    pb_ratio            NUMERIC(12,4),   -- price-to-book
    ps_ratio            NUMERIC(12,4),   -- price-to-sales
    peg_ratio           NUMERIC(12,4),

    -- ── Shares ──
    shares_outstanding  BIGINT,
    float_shares        BIGINT,
    held_by_insiders    NUMERIC(8,4),    -- % held by insiders
    held_by_institutions NUMERIC(8,4),   -- % held by institutions

    -- ── Dividends ──
    dividend_rate       NUMERIC(12,6),   -- annual dividend per share
    dividend_yield      NUMERIC(8,6),    -- decimal (0.026 = 2.6%)
    ex_dividend_date    DATE,
    payout_ratio        NUMERIC(8,4),

    -- ── Risk & Volatility ──
    beta                NUMERIC(10,4),
    fifty_two_week_high NUMERIC(16,4),
    fifty_two_week_low  NUMERIC(16,4),
    all_time_high       NUMERIC(16,4),
    all_time_low        NUMERIC(16,4),
    avg_volume_10d      BIGINT,
    avg_volume_3m       BIGINT,

    -- ── Profitability ──
    profit_margin       NUMERIC(10,6),
    operating_margin    NUMERIC(10,6),
    return_on_equity    NUMERIC(10,6),
    return_on_assets    NUMERIC(10,6),
    revenue_ttm         BIGINT,
    net_income_ttm      BIGINT,
    ebitda              BIGINT,
    earnings_growth     NUMERIC(10,6),   -- YoY
    revenue_growth      NUMERIC(10,6),   -- YoY

    -- ── Balance Sheet ──
    total_cash          BIGINT,
    total_debt          BIGINT,
    debt_to_equity      NUMERIC(12,4),
    current_ratio       NUMERIC(10,4),
    book_value          NUMERIC(16,4),

    -- ── Company Info (static-ish) ──
    sector              TEXT,
    industry            TEXT,
    lot_size            INT DEFAULT 1,   -- min tradeable unit
    currency            TEXT,            -- e.g. USD, HKD, THB

    -- ── Meta ──
    source              TEXT DEFAULT 'yfinance',
    updated_at          TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (ticker, exchange)
);

CREATE INDEX IF NOT EXISTS idx_stock_fundamentals_exchange
    ON datapai.stock_fundamentals (exchange);

CREATE INDEX IF NOT EXISTS idx_stock_fundamentals_sector
    ON datapai.stock_fundamentals (sector) WHERE sector IS NOT NULL;

COMMENT ON TABLE datapai.stock_fundamentals IS
    'Per-ticker fundamentals snapshot. Weekly full crawl via yfinance .info, daily price-derived update for popular stocks.';
