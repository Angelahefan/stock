-- 034: Archive tables for per-market intraday data
--
-- Flow at each market open (first intraday run of the day):
--   1. INSERT INTO archive SELECT * FROM live WHERE ts::date < today
--   2. TRUNCATE live table
--   3. Start fresh for today
--
-- Archive is append-only, no upsert needed.
-- ─────────────────────────────────────────────────────────────────────────

BEGIN;

CREATE TABLE datapai.ohlcv_intraday_us_archive (LIKE datapai.ohlcv_intraday_us INCLUDING DEFAULTS);
CREATE TABLE datapai.ohlcv_intraday_asx_archive (LIKE datapai.ohlcv_intraday_asx INCLUDING DEFAULTS);
CREATE TABLE datapai.ohlcv_intraday_hkex_archive (LIKE datapai.ohlcv_intraday_hkex INCLUDING DEFAULTS);
CREATE TABLE datapai.ohlcv_intraday_hose_archive (LIKE datapai.ohlcv_intraday_hose INCLUDING DEFAULTS);
CREATE TABLE datapai.ohlcv_intraday_set_archive (LIKE datapai.ohlcv_intraday_set INCLUDING DEFAULTS);
CREATE TABLE datapai.ohlcv_intraday_klse_archive (LIKE datapai.ohlcv_intraday_klse INCLUDING DEFAULTS);
CREATE TABLE datapai.ohlcv_intraday_idx_archive (LIKE datapai.ohlcv_intraday_idx INCLUDING DEFAULTS);
CREATE TABLE datapai.ohlcv_intraday_sse_archive (LIKE datapai.ohlcv_intraday_sse INCLUDING DEFAULTS);
CREATE TABLE datapai.ohlcv_intraday_szse_archive (LIKE datapai.ohlcv_intraday_szse INCLUDING DEFAULTS);
CREATE TABLE datapai.ohlcv_intraday_lse_archive (LIKE datapai.ohlcv_intraday_lse INCLUDING DEFAULTS);

-- Index on ts for time-range queries on archive
CREATE INDEX ON datapai.ohlcv_intraday_us_archive (ticker, ts DESC);
CREATE INDEX ON datapai.ohlcv_intraday_asx_archive (ticker, ts DESC);
CREATE INDEX ON datapai.ohlcv_intraday_hkex_archive (ticker, ts DESC);
CREATE INDEX ON datapai.ohlcv_intraday_hose_archive (ticker, ts DESC);
CREATE INDEX ON datapai.ohlcv_intraday_set_archive (ticker, ts DESC);
CREATE INDEX ON datapai.ohlcv_intraday_klse_archive (ticker, ts DESC);
CREATE INDEX ON datapai.ohlcv_intraday_idx_archive (ticker, ts DESC);
CREATE INDEX ON datapai.ohlcv_intraday_sse_archive (ticker, ts DESC);
CREATE INDEX ON datapai.ohlcv_intraday_szse_archive (ticker, ts DESC);
CREATE INDEX ON datapai.ohlcv_intraday_lse_archive (ticker, ts DESC);

COMMIT;
