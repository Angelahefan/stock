-- 035: Change intraday ts column from TIMESTAMPTZ to TIMESTAMP
-- Per-market tables store LOCAL time (e.g. AEDT for ASX, HKT for HKEX)
-- No timezone needed — each table IS the timezone context.
-- Also truncate all tables to clear UTC data and let DAGs refill with local time.

BEGIN;

-- Live tables
ALTER TABLE datapai.ohlcv_intraday_us    ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'America/New_York';
ALTER TABLE datapai.ohlcv_intraday_asx   ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Australia/Sydney';
ALTER TABLE datapai.ohlcv_intraday_hkex  ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Asia/Hong_Kong';
ALTER TABLE datapai.ohlcv_intraday_hose  ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Asia/Ho_Chi_Minh';
ALTER TABLE datapai.ohlcv_intraday_set   ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Asia/Bangkok';
ALTER TABLE datapai.ohlcv_intraday_klse  ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Asia/Kuala_Lumpur';
ALTER TABLE datapai.ohlcv_intraday_idx   ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Asia/Jakarta';
ALTER TABLE datapai.ohlcv_intraday_sse   ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Asia/Shanghai';
ALTER TABLE datapai.ohlcv_intraday_szse  ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Asia/Shanghai';
ALTER TABLE datapai.ohlcv_intraday_lse   ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Europe/London';

-- Archive tables
ALTER TABLE datapai.ohlcv_intraday_us_archive    ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'America/New_York';
ALTER TABLE datapai.ohlcv_intraday_asx_archive   ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Australia/Sydney';
ALTER TABLE datapai.ohlcv_intraday_hkex_archive  ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Asia/Hong_Kong';
ALTER TABLE datapai.ohlcv_intraday_hose_archive  ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Asia/Ho_Chi_Minh';
ALTER TABLE datapai.ohlcv_intraday_set_archive   ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Asia/Bangkok';
ALTER TABLE datapai.ohlcv_intraday_klse_archive  ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Asia/Kuala_Lumpur';
ALTER TABLE datapai.ohlcv_intraday_idx_archive   ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Asia/Jakarta';
ALTER TABLE datapai.ohlcv_intraday_sse_archive   ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Asia/Shanghai';
ALTER TABLE datapai.ohlcv_intraday_szse_archive  ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Asia/Shanghai';
ALTER TABLE datapai.ohlcv_intraday_lse_archive   ALTER COLUMN ts TYPE TIMESTAMP USING ts AT TIME ZONE 'Europe/London';

COMMIT;
