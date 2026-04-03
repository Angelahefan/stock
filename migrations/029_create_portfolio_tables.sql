-- 029_create_portfolio_tables.sql
-- Creates tables for:
--   1. Signal performance tracking (Feature 1)
--   2. Portfolio holdings & snapshots (Feature 2)

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════
-- FEATURE 1: Signal Performance
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS datapai.signal_performance (
    id                    BIGSERIAL PRIMARY KEY,
    ticker                VARCHAR(20)   NOT NULL,
    exchange              VARCHAR(10)   NOT NULL,
    signal_direction      VARCHAR(20)   NOT NULL,
    signal_date           DATE          NOT NULL,
    signal_price          DOUBLE PRECISION,
    return_7d             DOUBLE PRECISION,
    return_30d            DOUBLE PRECISION,
    return_90d            DOUBLE PRECISION,
    benchmark_return_7d   DOUBLE PRECISION,
    benchmark_return_30d  DOUBLE PRECISION,
    benchmark_return_90d  DOUBLE PRECISION,
    alpha_7d              DOUBLE PRECISION,
    alpha_30d             DOUBLE PRECISION,
    alpha_90d             DOUBLE PRECISION,
    outcome               VARCHAR(10),  -- 'win' or 'loss'
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signal_perf_date
    ON datapai.signal_performance (signal_date DESC);
CREATE INDEX IF NOT EXISTS idx_signal_perf_ticker
    ON datapai.signal_performance (ticker, exchange);
CREATE UNIQUE INDEX IF NOT EXISTS uq_signal_perf_ticker_date
    ON datapai.signal_performance (ticker, exchange, signal_date, signal_direction);

-- ══════════════════════════════════════════════════════════════════════════════
-- FEATURE 2: Portfolio Holdings & Snapshots
-- ══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS datapai.usr_holdings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     TEXT            NOT NULL,
    ticker      TEXT            NOT NULL,
    exchange    TEXT            NOT NULL DEFAULT 'US',
    shares      NUMERIC         NOT NULL,
    avg_cost    NUMERIC         NOT NULL,
    added_at    TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS idx_usr_holdings_user
    ON datapai.usr_holdings (user_id);

CREATE TABLE IF NOT EXISTS datapai.usr_portfolio_snapshots (
    id                BIGSERIAL PRIMARY KEY,
    user_id           TEXT            NOT NULL,
    snapshot_date     DATE            NOT NULL,
    total_value       NUMERIC,
    total_cost        NUMERIC,
    daily_pnl         NUMERIC,
    total_pnl         NUMERIC,
    total_pnl_pct     NUMERIC,
    benchmark_return   NUMERIC,
    created_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_portfolio_snap_user_date
    ON datapai.usr_portfolio_snapshots (user_id, snapshot_date DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_snap_user_date
    ON datapai.usr_portfolio_snapshots (user_id, snapshot_date);

COMMIT;
