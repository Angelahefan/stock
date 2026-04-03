-- =============================================================================
-- Migration 001: datapai.ta_indicators
-- Pre-computed technical indicators for all timeframes.
-- Run once on EC2 Postgres:
--   psql -h $DATAPAI_PG_HOST -U $DATAPAI_PG_USER -d $DATAPAI_PG_DB -f this_file.sql
-- =============================================================================

CREATE TABLE IF NOT EXISTS datapai.ta_indicators (

    -- ── Keys ──────────────────────────────────────────────────────────────────
    ticker          VARCHAR(20)       NOT NULL,
    exchange        VARCHAR(10)       NOT NULL,           -- US | ASX
    timeframe       VARCHAR(5)        NOT NULL,           -- 30m | 1d | 1w | 1mo
    ts              TIMESTAMPTZ       NOT NULL,           -- bar close timestamp
    trade_date      DATE              NOT NULL,           -- ts::date (for easy filtering)

    -- ── Price snapshot ────────────────────────────────────────────────────────
    open            DOUBLE PRECISION,
    high            DOUBLE PRECISION,
    low             DOUBLE PRECISION,
    close           DOUBLE PRECISION,
    volume          BIGINT,
    change_pct      DOUBLE PRECISION,                    -- vs previous bar close

    -- ── RSI(14) ───────────────────────────────────────────────────────────────
    rsi             DOUBLE PRECISION,
    rsi_label       VARCHAR(12),                         -- OVERBOUGHT | NEUTRAL | OVERSOLD

    -- ── MACD(12/26/9) ─────────────────────────────────────────────────────────
    macd_line       DOUBLE PRECISION,
    macd_signal     DOUBLE PRECISION,
    macd_hist       DOUBLE PRECISION,
    macd_label      VARCHAR(8),                          -- BULLISH | BEARISH

    -- ── Bollinger Bands(20/2) ─────────────────────────────────────────────────
    bb_upper        DOUBLE PRECISION,
    bb_middle       DOUBLE PRECISION,
    bb_lower        DOUBLE PRECISION,
    bb_pct          DOUBLE PRECISION,                    -- 0=lower band, 1=upper band
    bb_label        VARCHAR(20),                         -- NEAR UPPER BAND | MID BAND | NEAR LOWER BAND

    -- ── EMAs ──────────────────────────────────────────────────────────────────
    ema_5           DOUBLE PRECISION,
    ema_9           DOUBLE PRECISION,
    ema_10          DOUBLE PRECISION,
    ema_20          DOUBLE PRECISION,
    ema_21          DOUBLE PRECISION,
    ema_30          DOUBLE PRECISION,
    ema_50          DOUBLE PRECISION,
    ema_200         DOUBLE PRECISION,

    -- ── Stochastic(14, 3) ─────────────────────────────────────────────────────
    stoch_k         DOUBLE PRECISION,                    -- fast %K
    stoch_d         DOUBLE PRECISION,                    -- slow %D (3-period MA of %K)
    stoch_label     VARCHAR(12),                         -- OVERBOUGHT | NEUTRAL | OVERSOLD

    -- ── ATR(14) — volatility ──────────────────────────────────────────────────
    atr             DOUBLE PRECISION,                    -- Average True Range
    atr_pct         DOUBLE PRECISION,                    -- ATR as % of price

    -- ── ADX(14) + Directional Index ───────────────────────────────────────────
    adx             DOUBLE PRECISION,                    -- 0-100, >25 = strong trend
    plus_di         DOUBLE PRECISION,                    -- +DI (bullish pressure)
    minus_di        DOUBLE PRECISION,                    -- -DI (bearish pressure)
    adx_label       VARCHAR(15),                         -- STRONG_TREND | WEAK_TREND

    -- ── OBV (On-Balance Volume) ───────────────────────────────────────────────
    obv             DOUBLE PRECISION,
    obv_trend       VARCHAR(5),                          -- UP | DOWN | FLAT

    -- ── Volume indicators ─────────────────────────────────────────────────────
    vol_ma_5        DOUBLE PRECISION,
    vol_ma_10       DOUBLE PRECISION,
    vol_ma_30       DOUBLE PRECISION,
    vol_ratio_5     DOUBLE PRECISION,                    -- today vol / 5d MA
    vol_ratio_10    DOUBLE PRECISION,
    vol_ratio_30    DOUBLE PRECISION,

    -- ── Overall composite signal ──────────────────────────────────────────────
    overall_signal  VARCHAR(12),                         -- STRONG_BUY | BUY | NEUTRAL | SELL | STRONG_SELL
    signal_score    DOUBLE PRECISION,                    -- weighted score: -1.0 (strong sell) to +1.0 (strong buy)

    -- ── Quality filters ───────────────────────────────────────────────────────
    quality_ok      BOOLEAN           DEFAULT TRUE,      -- passes all filters
    low_volume      BOOLEAN           DEFAULT FALSE,     -- 30d avg vol < 50K
    suspicious_move BOOLEAN           DEFAULT FALSE,     -- |change_pct| > 40%

    -- ── Metadata ──────────────────────────────────────────────────────────────
    source          VARCHAR(20),                         -- polygon | yahoo
    computed_at     TIMESTAMPTZ       DEFAULT NOW(),

    PRIMARY KEY (ticker, exchange, timeframe, ts)
);

-- Fast screener indexes
CREATE INDEX IF NOT EXISTS idx_ta_indicators_screener_daily
    ON datapai.ta_indicators (timeframe, trade_date DESC, rsi)
    WHERE quality_ok = TRUE;

CREATE INDEX IF NOT EXISTS idx_ta_indicators_screener_signal
    ON datapai.ta_indicators (timeframe, trade_date DESC, overall_signal)
    WHERE quality_ok = TRUE;

CREATE INDEX IF NOT EXISTS idx_ta_indicators_ticker_tf
    ON datapai.ta_indicators (ticker, exchange, timeframe, trade_date DESC);

COMMENT ON TABLE datapai.ta_indicators IS
    'Pre-computed TA indicators per ticker/timeframe. Updated by compute_ta_*.py batch jobs.';
