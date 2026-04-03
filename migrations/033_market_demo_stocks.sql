-- 033: Lightweight demo stocks table for exchange landing pages
--
-- ~20 featured stocks per market, refreshed by screener_metrics nightly.
-- Exchange pages read ONLY this table — no joins, no LATERAL, instant.
-- ─────────────────────────────────────────────────────────────────────────

BEGIN;

CREATE TABLE IF NOT EXISTS datapai.market_demo_stocks (
  ticker        TEXT    NOT NULL,
  exchange      TEXT    NOT NULL,
  company_name  TEXT,
  sector        TEXT,
  price         DOUBLE PRECISION,
  change_1d_pct DOUBLE PRECISION,
  trade_date    DATE,
  display_order INT     DEFAULT 999,
  updated_at    TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (ticker, exchange)
);

CREATE INDEX ON datapai.market_demo_stocks (exchange, display_order);

COMMENT ON TABLE datapai.market_demo_stocks IS
  '~20 featured stocks per market for exchange landing pages. Refreshed nightly from screener_metrics.';

-- ── Populate from ticker_universe (featured) + screener_metrics (prices) ─
-- JOIN screener_metrics on both base ticker and yf_symbol (suffixed variant)
-- because screener_metrics may store tickers as BHP.AX (ASX) or 0700.HK (HKEX)
INSERT INTO datapai.market_demo_stocks
  (ticker, exchange, company_name, sector, price, change_1d_pct, trade_date, display_order)
SELECT
  tu.ticker,
  tu.exchange,
  COALESCE(tu.company_name, tu.ticker),
  tu.sector,
  COALESCE(sm1.latest_close, sm2.latest_close),
  COALESCE(sm1.change_1d_pct, sm2.change_1d_pct),
  COALESCE(sm1.trade_date, sm2.trade_date)::date,
  COALESCE(tu.featured_order, 999)
FROM datapai.ticker_universe tu
LEFT JOIN datapai.screener_metrics sm1
  ON sm1.ticker = tu.ticker AND sm1.exchange = tu.exchange
LEFT JOIN datapai.screener_metrics sm2
  ON sm2.ticker = tu.yf_symbol AND sm2.exchange = tu.exchange
WHERE tu.is_featured = TRUE AND tu.is_active = TRUE
ON CONFLICT (ticker, exchange) DO UPDATE SET
  company_name  = EXCLUDED.company_name,
  sector        = EXCLUDED.sector,
  price         = EXCLUDED.price,
  change_1d_pct = EXCLUDED.change_1d_pct,
  trade_date    = EXCLUDED.trade_date,
  display_order = EXCLUDED.display_order,
  updated_at    = NOW();

COMMIT;
