-- =============================================================================
-- 005_screener_metrics.sql  —  Pre-computed price metrics for stock screener
-- =============================================================================
--
-- APPLY:
--   docker exec -i lightdash_db_1 psql -U postgres -d postgres < scripts/migrations/005_screener_metrics.sql
--
-- PURPOSE:
--   Enables screening across ALL 7,000+ tickers using price-based metrics
--   computed nightly from the datapai.prices table.
--   Joins with fundamental_snapshot (when available) for full screening.
-- =============================================================================

CREATE TABLE IF NOT EXISTS datapai.screener_metrics (
    -- identity
    ticker               TEXT NOT NULL,
    exchange             TEXT NOT NULL,

    -- latest price
    latest_close         DOUBLE PRECISION,
    latest_volume        DOUBLE PRECISION,
    trade_date           TEXT,              -- latest trade date

    -- % price changes
    change_1d_pct        DOUBLE PRECISION,  -- 1-day change
    change_5d_pct        DOUBLE PRECISION,  -- 5-day (1 week)
    change_1m_pct        DOUBLE PRECISION,  -- ~21 trading days
    change_3m_pct        DOUBLE PRECISION,  -- ~63 trading days
    change_6m_pct        DOUBLE PRECISION,  -- ~126 trading days
    change_1y_pct        DOUBLE PRECISION,  -- ~252 trading days

    -- 52-week range
    high_52w             DOUBLE PRECISION,
    low_52w              DOUBLE PRECISION,
    pct_from_52w_high    DOUBLE PRECISION,  -- negative = below high
    pct_from_52w_low     DOUBLE PRECISION,  -- positive = above low

    -- moving averages
    sma_5                DOUBLE PRECISION,
    sma_10               DOUBLE PRECISION,
    sma_20               DOUBLE PRECISION,
    sma_30               DOUBLE PRECISION,
    sma_50               DOUBLE PRECISION,
    sma_200              DOUBLE PRECISION,
    price_vs_sma5_pct    DOUBLE PRECISION,  -- % above/below SMA5
    price_vs_sma10_pct   DOUBLE PRECISION,
    price_vs_sma20_pct   DOUBLE PRECISION,
    price_vs_sma30_pct   DOUBLE PRECISION,
    price_vs_sma50_pct   DOUBLE PRECISION,
    price_vs_sma200_pct  DOUBLE PRECISION,

    -- MA crossover signals
    golden_cross         BOOLEAN DEFAULT FALSE,  -- SMA50 > SMA200 (bullish)
    death_cross          BOOLEAN DEFAULT FALSE,  -- SMA50 < SMA200 (bearish)

    -- volume
    avg_volume_20d       DOUBLE PRECISION,
    volume_ratio         DOUBLE PRECISION,  -- latest_volume / avg_volume_20d

    -- volatility
    volatility_20d       DOUBLE PRECISION,  -- 20-day annualised std dev of returns

    -- simple momentum / RSI approximation
    rsi_14               DOUBLE PRECISION,  -- 14-day RSI

    -- metadata
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (ticker, exchange)
);

-- Screener indexes
CREATE INDEX IF NOT EXISTS idx_screener_metrics_exchange
    ON datapai.screener_metrics (exchange, change_1d_pct DESC);

CREATE INDEX IF NOT EXISTS idx_screener_metrics_momentum
    ON datapai.screener_metrics (exchange, change_1m_pct DESC);

CREATE INDEX IF NOT EXISTS idx_screener_metrics_volume
    ON datapai.screener_metrics (exchange, volume_ratio DESC);

COMMENT ON TABLE datapai.screener_metrics IS
    'Pre-computed price metrics for stock screener. Updated nightly from datapai.prices. Covers ALL tickers.';
