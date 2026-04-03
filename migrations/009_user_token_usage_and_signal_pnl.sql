-- Migration 009: Per-user token usage limits + Signal recommendation P&L tracking

-- 1. Per-user daily token usage
CREATE TABLE IF NOT EXISTS datapai.user_token_usage (
  user_id     TEXT NOT NULL,
  usage_date  DATE NOT NULL DEFAULT CURRENT_DATE,
  tokens_used BIGINT NOT NULL DEFAULT 0,
  cost_usd    DOUBLE PRECISION NOT NULL DEFAULT 0,
  request_count INT NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, usage_date)
);
CREATE INDEX IF NOT EXISTS idx_user_token_usage_date ON datapai.user_token_usage (usage_date);

-- 2. Buy/Sell recommendation tracking for P&L
CREATE TABLE IF NOT EXISTS datapai.signal_recommendations (
  id              BIGSERIAL PRIMARY KEY,
  user_id         TEXT NOT NULL,
  ticker          TEXT NOT NULL,
  exchange        TEXT NOT NULL DEFAULT 'US',
  signal_type     TEXT NOT NULL,
  signal_source   TEXT NOT NULL DEFAULT 'screener',
  entry_price     DOUBLE PRECISION,
  entry_date      DATE NOT NULL DEFAULT CURRENT_DATE,
  exit_price      DOUBLE PRECISION,
  exit_date       DATE,
  pnl_pct         DOUBLE PRECISION,
  pnl_usd         DOUBLE PRECISION,
  status          TEXT NOT NULL DEFAULT 'open',
  signal_metadata JSONB,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_signal_recs_user ON datapai.signal_recommendations (user_id, status);
CREATE INDEX IF NOT EXISTS idx_signal_recs_ticker ON datapai.signal_recommendations (ticker, entry_date);

-- 3. Daily P&L snapshot (mark-to-market for open positions)
CREATE TABLE IF NOT EXISTS datapai.signal_pnl_daily (
  recommendation_id BIGINT NOT NULL REFERENCES datapai.signal_recommendations(id),
  snapshot_date     DATE NOT NULL,
  current_price     DOUBLE PRECISION,
  unrealized_pnl_pct DOUBLE PRECISION,
  PRIMARY KEY (recommendation_id, snapshot_date)
);
