-- =============================================================================
-- Migration: rename `date` → `trade_date` in datapai.prices
-- =============================================================================
-- Run ONCE on the PostgreSQL database AFTER the S3 sync has completed
-- (so the in-flight S3 writes finish using the old column name first).
--
-- After this migration:
--   1. Re-run the S3 sync to rewrite Parquet files with the new column name:
--        python3 scripts/sync_postgres_to_s3_oneoff.py --resume
--      (skips partitions already in S3 unless you pass no --resume to force rewrite)
--      To force a full rewrite of all partitions:
--        python3 scripts/sync_postgres_to_s3_oneoff.py
--   2. Then load into Snowflake Iceberg:
--        python3 scripts/sync_snowflake_iceberg.py --mode full
-- =============================================================================

BEGIN;

-- Rename the column
ALTER TABLE datapai.prices
  RENAME COLUMN date TO trade_date;

-- Drop and recreate the primary key constraint if it references the old name
-- (PostgreSQL renames PK column references automatically, but run EXPLAIN to verify)

-- Verify
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'datapai'
  AND table_name   = 'prices'
  AND column_name  IN ('date', 'trade_date')
ORDER BY column_name;

COMMIT;
