-- 032: Split ohlcv_intraday into separate per-market tables
--
-- Why: The old single table gets TRUNCATED at EOD, wiping ALL markets.
--      Markets operate in different timezones — truncating US data
--      at US close destroys Asian data users still need.
--
-- Design:
--   - One table per market (not partitions) — enables independent TRUNCATE
--   - Each table is tiny: ~20 demo stocks × 3 days × ~13 bars ≈ 800 rows
--   - Keep 3 days of data (covers Friday over weekend)
--   - Old parent table renamed to _old, can be dropped after verification
-- ─────────────────────────────────────────────────────────────────────────

BEGIN;

-- ── Rename old table ─────────────────────────────────────────────────────
ALTER TABLE IF EXISTS datapai.ohlcv_intraday RENAME TO ohlcv_intraday_old;

-- ── Helper: create one intraday table ────────────────────────────────────
-- Each table has identical schema, no BIGSERIAL id (not needed for small tables)

CREATE TABLE datapai.ohlcv_intraday_us (
  ticker      TEXT             NOT NULL,
  ts          TIMESTAMPTZ      NOT NULL,
  open        DOUBLE PRECISION,
  high        DOUBLE PRECISION,
  low         DOUBLE PRECISION,
  close       DOUBLE PRECISION,
  volume      BIGINT,
  exchange    TEXT             NOT NULL DEFAULT 'US',
  source      TEXT             NOT NULL DEFAULT 'yfinance',
  inserted_at TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
  PRIMARY KEY (ticker, ts)
);
CREATE INDEX ON datapai.ohlcv_intraday_us (ts DESC);

CREATE TABLE datapai.ohlcv_intraday_asx (LIKE datapai.ohlcv_intraday_us INCLUDING ALL);
ALTER TABLE datapai.ohlcv_intraday_asx ALTER COLUMN exchange SET DEFAULT 'ASX';

CREATE TABLE datapai.ohlcv_intraday_hkex (LIKE datapai.ohlcv_intraday_us INCLUDING ALL);
ALTER TABLE datapai.ohlcv_intraday_hkex ALTER COLUMN exchange SET DEFAULT 'HKEX';

CREATE TABLE datapai.ohlcv_intraday_hose (LIKE datapai.ohlcv_intraday_us INCLUDING ALL);
ALTER TABLE datapai.ohlcv_intraday_hose ALTER COLUMN exchange SET DEFAULT 'HOSE';

CREATE TABLE datapai.ohlcv_intraday_set (LIKE datapai.ohlcv_intraday_us INCLUDING ALL);
ALTER TABLE datapai.ohlcv_intraday_set ALTER COLUMN exchange SET DEFAULT 'SET';

CREATE TABLE datapai.ohlcv_intraday_klse (LIKE datapai.ohlcv_intraday_us INCLUDING ALL);
ALTER TABLE datapai.ohlcv_intraday_klse ALTER COLUMN exchange SET DEFAULT 'KLSE';

CREATE TABLE datapai.ohlcv_intraday_idx (LIKE datapai.ohlcv_intraday_us INCLUDING ALL);
ALTER TABLE datapai.ohlcv_intraday_idx ALTER COLUMN exchange SET DEFAULT 'IDX';

CREATE TABLE datapai.ohlcv_intraday_sse (LIKE datapai.ohlcv_intraday_us INCLUDING ALL);
ALTER TABLE datapai.ohlcv_intraday_sse ALTER COLUMN exchange SET DEFAULT 'SSE';

CREATE TABLE datapai.ohlcv_intraday_szse (LIKE datapai.ohlcv_intraday_us INCLUDING ALL);
ALTER TABLE datapai.ohlcv_intraday_szse ALTER COLUMN exchange SET DEFAULT 'SZSE';

CREATE TABLE datapai.ohlcv_intraday_lse (LIKE datapai.ohlcv_intraday_us INCLUDING ALL);
ALTER TABLE datapai.ohlcv_intraday_lse ALTER COLUMN exchange SET DEFAULT 'LSE';

-- ── View: unified read access (backwards-compatible) ─────────────────────
-- Code that reads ohlcv_intraday can use this view without changes.
-- Writes must target the specific table.

CREATE OR REPLACE VIEW datapai.ohlcv_intraday AS
  SELECT ticker, ts, open, high, low, close, volume, exchange, source, inserted_at FROM datapai.ohlcv_intraday_us
  UNION ALL
  SELECT ticker, ts, open, high, low, close, volume, exchange, source, inserted_at FROM datapai.ohlcv_intraday_asx
  UNION ALL
  SELECT ticker, ts, open, high, low, close, volume, exchange, source, inserted_at FROM datapai.ohlcv_intraday_hkex
  UNION ALL
  SELECT ticker, ts, open, high, low, close, volume, exchange, source, inserted_at FROM datapai.ohlcv_intraday_hose
  UNION ALL
  SELECT ticker, ts, open, high, low, close, volume, exchange, source, inserted_at FROM datapai.ohlcv_intraday_set
  UNION ALL
  SELECT ticker, ts, open, high, low, close, volume, exchange, source, inserted_at FROM datapai.ohlcv_intraday_klse
  UNION ALL
  SELECT ticker, ts, open, high, low, close, volume, exchange, source, inserted_at FROM datapai.ohlcv_intraday_idx
  UNION ALL
  SELECT ticker, ts, open, high, low, close, volume, exchange, source, inserted_at FROM datapai.ohlcv_intraday_sse
  UNION ALL
  SELECT ticker, ts, open, high, low, close, volume, exchange, source, inserted_at FROM datapai.ohlcv_intraday_szse
  UNION ALL
  SELECT ticker, ts, open, high, low, close, volume, exchange, source, inserted_at FROM datapai.ohlcv_intraday_lse;

COMMENT ON VIEW datapai.ohlcv_intraday IS
  'Unified read view over per-market intraday tables. For writes, target ohlcv_intraday_{exchange}.';

-- ── Drop old table (data is empty anyway) ────────────────────────────────
-- DROP TABLE IF EXISTS datapai.ohlcv_intraday_old;
-- Uncomment after verifying everything works.

COMMIT;
