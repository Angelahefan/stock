-- 008_priority_tickers.sql
-- Smart priority list: which tickers deserve fundamental analysis.
-- Updated daily. Drives compute_fundamental_lite to only fetch what matters.

CREATE TABLE IF NOT EXISTS datapai.priority_tickers (
    ticker          TEXT NOT NULL,
    exchange        TEXT NOT NULL,
    priority        INTEGER NOT NULL DEFAULT 5,   -- 1=highest (watchlist), 5=lowest
    reason          TEXT NOT NULL,                 -- why this ticker is prioritized
    source          TEXT NOT NULL,                 -- watchlist / screener_oversold / screener_momentum / etc
    added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,                  -- NULL = never expires (watchlist), else auto-remove
    PRIMARY KEY (ticker, exchange, source)
);

CREATE INDEX IF NOT EXISTS idx_priority_tickers_exchange ON datapai.priority_tickers (exchange, priority);
CREATE INDEX IF NOT EXISTS idx_priority_tickers_expires ON datapai.priority_tickers (expires_at) WHERE expires_at IS NOT NULL;
