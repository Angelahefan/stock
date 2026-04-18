-- Migration: Agent-owned tables for multi-agent Investment Committee
-- Date: 2026-03-23
-- Naming convention: agt_ prefix for all agent tables
-- Purpose: Store decisions, learned parameters, trade signals, learning history

-- 1. Agent decisions log — every BUY/SELL/HOLD decision with reasoning
CREATE TABLE IF NOT EXISTS datapai.agt_decisions (
    id                  SERIAL PRIMARY KEY,
    ticker              VARCHAR(20)       NOT NULL,
    exchange            VARCHAR(10)       NOT NULL,
    decision            VARCHAR(20)       NOT NULL,  -- BUY, SELL, HOLD, ADD
    decision_source     VARCHAR(50)       NOT NULL,  -- CONSENSUS, EXIT_AGENT, RISK_AGENT
    confidence          DOUBLE PRECISION,
    regime              VARCHAR(30),                 -- BULL_MOMENTUM, BEAR_RECESSION, NEUTRAL
    quality_tier        VARCHAR(5),                  -- A, B, C, D
    sector              VARCHAR(50),
    agent_scores_json   JSONB DEFAULT '{}',          -- {TECHNICAL: 0.5, FUNDAMENTAL: 0.3, ...}
    reasoning           TEXT,                        -- human-readable explanation
    ta_signals_json     JSONB DEFAULT '{}',          -- raw TA indicators at decision time
    entry_price         DOUBLE PRECISION,            -- price at decision time
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agt_decisions_ticker
    ON datapai.agt_decisions (ticker, exchange, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agt_decisions_date
    ON datapai.agt_decisions (created_at DESC);

-- 2. Active positions — what the system currently recommends holding
CREATE TABLE IF NOT EXISTS datapai.agt_positions (
    id                  SERIAL PRIMARY KEY,
    ticker              VARCHAR(20)       NOT NULL,
    exchange            VARCHAR(10)       NOT NULL,
    entry_date          DATE              NOT NULL,
    entry_price         DOUBLE PRECISION  NOT NULL,
    current_price       DOUBLE PRECISION,
    highest_since_entry DOUBLE PRECISION,
    unrealized_pnl_pct  DOUBLE PRECISION,
    days_held           INT DEFAULT 0,
    quality_tier        VARCHAR(5),
    sector              VARCHAR(50),
    regime_at_entry     VARCHAR(30),
    status              VARCHAR(20) NOT NULL DEFAULT 'OPEN',  -- OPEN, CLOSED, ADDED
    exit_date           DATE,
    exit_price          DOUBLE PRECISION,
    exit_reason         VARCHAR(50),
    realized_pnl_pct    DOUBLE PRECISION,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (ticker, exchange, entry_date)
);

CREATE INDEX IF NOT EXISTS idx_agt_positions_open
    ON datapai.agt_positions (status, ticker);

-- 3. Learned parameters — what the learning agent has discovered
CREATE TABLE IF NOT EXISTS datapai.agt_learned_params (
    id                  SERIAL PRIMARY KEY,
    param_key           VARCHAR(100)      NOT NULL,  -- e.g. "sell_threshold/BULL_MOMENTUM/A"
    param_value         JSONB             NOT NULL,  -- the value (number, object, etc.)
    source              VARCHAR(50)       NOT NULL DEFAULT 'learning_agent',
    reason              TEXT,                        -- why this param was adjusted
    backtest_improvement DOUBLE PRECISION,            -- % improvement this change produced
    version             INT               NOT NULL DEFAULT 1,
    is_active           BOOLEAN           NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ       NOT NULL DEFAULT NOW(),
    UNIQUE (param_key, version)
);

CREATE INDEX IF NOT EXISTS idx_agt_learned_active
    ON datapai.agt_learned_params (is_active, param_key);

-- 4. Learning history — record of each learning cycle
CREATE TABLE IF NOT EXISTS datapai.agt_learning_runs (
    id                  SERIAL PRIMARY KEY,
    run_type            VARCHAR(30)       NOT NULL,  -- REGRET_ANALYSIS, PARAM_OPTIMIZATION
    exchange            VARCHAR(10),
    tickers_analyzed    INT,
    exit_events_total   INT,
    mistake_pct         DOUBLE PRECISION,            -- % of exits that were mistakes
    avg_regret_90d      DOUBLE PRECISION,            -- average 90-day regret
    params_adjusted     INT DEFAULT 0,               -- how many params were changed
    improvement_pct     DOUBLE PRECISION,            -- backtest improvement after adjustment
    summary_json        JSONB DEFAULT '{}',          -- full analysis summary
    patterns_json       JSONB DEFAULT '[]',          -- mistake patterns found
    created_at          TIMESTAMPTZ       NOT NULL DEFAULT NOW()
);

-- 5. Agent config — runtime configuration for each agent
CREATE TABLE IF NOT EXISTS datapai.agt_config (
    agent_name          VARCHAR(50)       NOT NULL,  -- exit_agent, risk_agent, macro_agent
    config_key          VARCHAR(100)      NOT NULL,
    config_value        JSONB             NOT NULL,
    description         TEXT,
    updated_at          TIMESTAMPTZ       NOT NULL DEFAULT NOW(),
    PRIMARY KEY (agent_name, config_key)
);

-- 6. Backtest results — store every backtest run for comparison
CREATE TABLE IF NOT EXISTS datapai.agt_backtest_runs (
    id                  SERIAL PRIMARY KEY,
    strategy            VARCHAR(50)       NOT NULL,
    exchange            VARCHAR(10),
    hold_days           INT,
    start_date          DATE,
    tickers_tested      INT,
    total_trades        INT,
    win_rate            DOUBLE PRECISION,
    avg_return          DOUBLE PRECISION,
    median_return       DOUBLE PRECISION,
    profit_factor       DOUBLE PRECISION,
    avg_drawdown        DOUBLE PRECISION,
    annualized_return   DOUBLE PRECISION,
    params_version      INT,                         -- which learned params version was used
    details_json        JSONB DEFAULT '{}',          -- full breakdown
    created_at          TIMESTAMPTZ       NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE datapai.agt_decisions IS 'Every BUY/SELL/HOLD decision with full reasoning';
COMMENT ON TABLE datapai.agt_positions IS 'Currently recommended positions and closed trade history';
COMMENT ON TABLE datapai.agt_learned_params IS 'Self-learned exit/entry parameters from regret analysis';
COMMENT ON TABLE datapai.agt_learning_runs IS 'History of each learning cycle run';
COMMENT ON TABLE datapai.agt_config IS 'Runtime agent configuration';
COMMENT ON TABLE datapai.agt_backtest_runs IS 'Historical backtest results for comparison';
