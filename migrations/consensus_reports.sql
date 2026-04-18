-- Migration: Create consensus_reports table for Investment Committee v2
-- Date: 2026-03-23
-- Stores regime-weighted debate consensus, risk assessment, and exit strategy

CREATE TABLE IF NOT EXISTS datapai.consensus_reports (
    id                  SERIAL PRIMARY KEY,
    ticker              VARCHAR(20)       NOT NULL,
    exchange            VARCHAR(10)       NOT NULL,
    macro_view          VARCHAR(30)       NOT NULL,      -- BULL_MOMENTUM / BEAR_RECESSION / NEUTRAL_TRANSITION
    consensus_score     DOUBLE PRECISION  NOT NULL,      -- -1.0 to +1.0
    conflict_level      DOUBLE PRECISION  NOT NULL,      -- 0.0 to 1.0
    consensus_direction VARCHAR(20)       NOT NULL,      -- STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL
    agent_scores_json   JSONB             NOT NULL DEFAULT '{}',  -- {TECHNICAL: 0.6, ...}
    regime_weights_json JSONB             NOT NULL DEFAULT '{}',  -- weights applied
    risk_score          DOUBLE PRECISION  NOT NULL DEFAULT 0,     -- 0.0 to 1.0
    risk_flags_json     JSONB             NOT NULL DEFAULT '[]',  -- ["flag1", "flag2"]
    position_size       VARCHAR(10)       NOT NULL DEFAULT 'FULL', -- FULL/HALF/QUARTER/NONE
    exit_strategy_json  JSONB             NOT NULL DEFAULT '{}',  -- {take_profit_pct, stop_loss_pct, ...}
    debate_transcript   TEXT              NOT NULL DEFAULT '',     -- full debate text
    debate_phases_json  JSONB             NOT NULL DEFAULT '{}',  -- draft/challenge/vote details
    computed_at         TIMESTAMPTZ       NOT NULL DEFAULT NOW(),
    UNIQUE (ticker, exchange, computed_at)
);

-- Index for fast latest-report lookups
CREATE INDEX IF NOT EXISTS idx_consensus_reports_latest
    ON datapai.consensus_reports (ticker, exchange, computed_at DESC);

-- Index for regime-based queries
CREATE INDEX IF NOT EXISTS idx_consensus_reports_regime
    ON datapai.consensus_reports (macro_view, computed_at DESC);

COMMENT ON TABLE datapai.consensus_reports IS
    'Investment Committee v2 debate consensus reports — regime-weighted agent scores, risk, and exit strategy';
