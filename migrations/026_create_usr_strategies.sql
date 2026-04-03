-- ============================================================================
-- 026_create_usr_strategies.sql
-- Personalized Agent Studio: user-defined strategies + backtest results
-- ============================================================================

-- ── User strategies ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS datapai.usr_strategies (
    id              SERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    exchange        TEXT NOT NULL,
    tickers         JSONB,                          -- ["AAPL","MSFT"] or "all_featured"
    strategy_type   TEXT DEFAULT 'custom',           -- momentum, mean_reversion, breakout, custom
    config          JSONB NOT NULL DEFAULT '{}',     -- entry_rules, exit_rules, filters, position_sizing, backtest_params
    is_active       BOOLEAN DEFAULT TRUE,
    backtest_status TEXT DEFAULT 'pending',           -- pending / running / completed / failed
    last_backtest_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usr_strategies_user    ON datapai.usr_strategies (user_id);
CREATE INDEX IF NOT EXISTS idx_usr_strategies_status  ON datapai.usr_strategies (backtest_status);

-- ── Backtest results ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS datapai.usr_backtest_results (
    id              SERIAL PRIMARY KEY,
    strategy_id     INTEGER NOT NULL REFERENCES datapai.usr_strategies(id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL,
    run_date        DATE NOT NULL,
    config_snapshot JSONB,                           -- frozen copy of strategy config at run time
    results         JSONB NOT NULL DEFAULT '{}',     -- summary, trades, equity_curve, monthly_returns
    status          TEXT DEFAULT 'completed',         -- completed / failed
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usr_backtest_strategy  ON datapai.usr_backtest_results (strategy_id);
CREATE INDEX IF NOT EXISTS idx_usr_backtest_user      ON datapai.usr_backtest_results (user_id);
CREATE INDEX IF NOT EXISTS idx_usr_backtest_date      ON datapai.usr_backtest_results (run_date);
