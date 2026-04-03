-- Migration 010: Global market index support
-- Adds asset_type + region to ticker_universe, seeds 16 global indexes

-- 1. Add columns
ALTER TABLE datapai.ticker_universe
  ADD COLUMN IF NOT EXISTS asset_type TEXT NOT NULL DEFAULT 'STOCK',
  ADD COLUMN IF NOT EXISTS region TEXT;

-- 2. Seed global market indexes
INSERT INTO datapai.ticker_universe (ticker, exchange, yf_symbol, company_name, asset_type, region, source, is_active)
VALUES
  -- US
  ('^GSPC',     'INDEX', '^GSPC',     'S&P 500',             'INDEX', 'US',   'manual', TRUE),
  ('^IXIC',     'INDEX', '^IXIC',     'NASDAQ Composite',    'INDEX', 'US',   'manual', TRUE),
  ('^DJI',      'INDEX', '^DJI',      'Dow Jones',           'INDEX', 'US',   'manual', TRUE),
  ('^RUT',      'INDEX', '^RUT',      'Russell 2000',        'INDEX', 'US',   'manual', TRUE),
  ('^VIX',      'INDEX', '^VIX',      'VIX Volatility',      'INDEX', 'US',   'manual', TRUE),
  ('^NDX',      'INDEX', '^NDX',      'NASDAQ-100',          'INDEX', 'US',   'manual', TRUE),
  -- Australia
  ('^AXJO',     'INDEX', '^AXJO',     'ASX 200',             'INDEX', 'ASX',  'manual', TRUE),
  ('^AXKO',     'INDEX', '^AXKO',     'ASX 300',             'INDEX', 'ASX',  'manual', TRUE),
  ('^AORD',     'INDEX', '^AORD',     'All Ordinaries',      'INDEX', 'ASX',  'manual', TRUE),
  -- Asia
  ('^N225',     'INDEX', '^N225',     'Nikkei 225',          'INDEX', 'ASIA', 'manual', TRUE),
  ('^HSI',      'INDEX', '^HSI',      'Hang Seng',           'INDEX', 'ASIA', 'manual', TRUE),
  ('000001.SS', 'INDEX', '000001.SS', 'Shanghai Composite',  'INDEX', 'ASIA', 'manual', TRUE),
  ('399001.SZ', 'INDEX', '399001.SZ', 'Shenzhen Component',  'INDEX', 'ASIA', 'manual', TRUE),
  ('^STI',      'INDEX', '^STI',      'Straits Times',       'INDEX', 'ASIA', 'manual', TRUE),
  -- Europe
  ('^FTSE',     'INDEX', '^FTSE',     'FTSE 100',            'INDEX', 'EU',   'manual', TRUE),
  ('^GDAXI',    'INDEX', '^GDAXI',    'DAX',                 'INDEX', 'EU',   'manual', TRUE)
ON CONFLICT (ticker, exchange) DO UPDATE SET
  company_name = EXCLUDED.company_name,
  asset_type = EXCLUDED.asset_type,
  region = EXCLUDED.region,
  is_active = TRUE,
  updated_at = NOW();
