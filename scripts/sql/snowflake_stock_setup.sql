-- =============================================================================
-- Snowflake STOCK schema — one-time infrastructure setup
-- =============================================================================
-- Run ALL statements in this file as ACCOUNTADMIN.
--
-- Prerequisites (already done):
--   1. EC2 IAM role:  arn:aws:iam::<YOUR_AWS_ACCOUNT_ID>:role/ec2_manager_connection_role
--   2. S3 bucket:     codepais3  (EC2 role already has read/write access)
--
-- Run order:
--   Step 1  — Storage Integration  (trust Snowflake IAM user → EC2 role)
--   Step 2  — Describe integration to get IAM user ARN + external ID
--   Step 3  — Update AWS trust policy on ec2_manager_connection_role (AWS Console)
--   Step 4  — External Volume      (Iceberg bronze layer on S3)
--   Step 5  — Grants to AIRBYTE_ROLE
--   Step 6  — Schema
--   Step 7  — S3 Stage             (run as AIRBYTE_ROLE or via Python script)
--
-- After this file:
--   dbt run --select stock.*       (creates PRICES + OHLCV_INTRADAY Iceberg tables)
--   python3 scripts/sync_postgres_to_s3_oneoff.py --table prices
--   python3 scripts/sync_snowflake_iceberg.py --mode full
-- =============================================================================

USE ROLE ACCOUNTADMIN;

-- =============================================================================
-- STEP 1: Storage Integration
-- Allows Snowflake to read from S3 raw stage using EC2 IAM role.
-- =============================================================================
CREATE STORAGE INTEGRATION IF NOT EXISTS DATAPAI_S3_INTEGRATION
  TYPE                      = EXTERNAL_STAGE
  STORAGE_PROVIDER          = 'S3'
  ENABLED                   = TRUE
  STORAGE_AWS_ROLE_ARN      = 'arn:aws:iam::<YOUR_AWS_ACCOUNT_ID>:role/ec2_manager_connection_role'
  STORAGE_ALLOWED_LOCATIONS = ('s3://codepais3/stock/');

-- =============================================================================
-- STEP 2: Retrieve IAM user ARN + external ID for AWS trust policy
-- Copy STORAGE_AWS_IAM_USER_ARN and STORAGE_AWS_EXTERNAL_ID from the output.
-- =============================================================================
DESC INTEGRATION DATAPAI_S3_INTEGRATION;

-- =============================================================================
-- STEP 3: AWS Console — update trust policy on ec2_manager_connection_role
-- Replace the trust policy with:
--
-- {
--   "Version": "2012-10-17",
--   "Statement": [
--     {
--       "Effect": "Allow",
--       "Principal": { "Service": "ec2.amazonaws.com" },
--       "Action": "sts:AssumeRole"
--     },
--     {
--       "Effect": "Allow",
--       "Principal": { "AWS": "<STORAGE_AWS_IAM_USER_ARN>" },
--       "Action": "sts:AssumeRole",
--       "Condition": {
--         "StringLike": { "sts:ExternalId": "DN97074_SFCRole=2_*" }
--       }
--     }
--   ]
-- }
--
-- Confirmed values (2026-03-14):
--   STORAGE_AWS_IAM_USER_ARN  = arn:aws:iam::891377375664:user/fshl0000-s
--   STORAGE_AWS_EXTERNAL_ID   = DN97074_SFCRole=2_TqhlwaIN7Sxuoo0QLldzG2UgmfM  (integration)
--   STORAGE_AWS_EXTERNAL_ID   = DN97074_SFCRole=2_s/yMb6q9V9NHYUiHw9etXIrukh8= (ext volume)
--   → using StringLike DN97074_SFCRole=2_* to cover both
-- =============================================================================

-- =============================================================================
-- STEP 4: External Volume
-- Snowflake writes Managed Iceberg format to s3://codepais3/stock/bronze/
-- =============================================================================
CREATE EXTERNAL VOLUME IF NOT EXISTS DATAPAI_S3_VOL
  STORAGE_LOCATIONS = (
    (
      NAME                 = 'datapai-ap-southeast-2'
      STORAGE_PROVIDER     = 'S3'
      STORAGE_BASE_URL     = 's3://codepais3/stock/bronze/'
      STORAGE_AWS_ROLE_ARN = 'arn:aws:iam::<YOUR_AWS_ACCOUNT_ID>:role/ec2_manager_connection_role'
    )
  );

-- Verify the external volume storage location and IAM user
DESCRIBE EXTERNAL VOLUME DATAPAI_S3_VOL;

-- =============================================================================
-- STEP 5: Grants to AIRBYTE_ROLE
-- Allows dbt (running as AIRBYTE_USER / AIRBYTE_ROLE) to create Iceberg tables.
-- =============================================================================
GRANT USAGE ON INTEGRATION   DATAPAI_S3_INTEGRATION TO ROLE AIRBYTE_ROLE;
GRANT USAGE ON EXTERNAL VOLUME DATAPAI_S3_VOL        TO ROLE AIRBYTE_ROLE;
GRANT USAGE   ON SCHEMA DATAPAI.STOCK                TO ROLE AIRBYTE_ROLE;
GRANT CREATE TABLE ON SCHEMA DATAPAI.STOCK            TO ROLE AIRBYTE_ROLE;

-- =============================================================================
-- STEP 6: Schema (also created by Python script / dbt macro — idempotent)
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS DATAPAI.STOCK;

-- =============================================================================
-- STEP 7: S3 Stage  (can also be run as AIRBYTE_ROLE via Python script)
-- Points to raw Parquet files written by sync_postgres_to_s3_oneoff.py
-- =============================================================================
USE ROLE AIRBYTE_ROLE;

CREATE STAGE IF NOT EXISTS DATAPAI.STOCK.S3_RAW_STAGE
  URL                 = 's3://codepais3/stock/raw/'
  STORAGE_INTEGRATION = DATAPAI_S3_INTEGRATION
  FILE_FORMAT         = (TYPE = PARQUET SNAPPY_COMPRESSION = TRUE);

-- Verify stage can list files (run after sync_postgres_to_s3_oneoff.py completes)
LIST @DATAPAI.STOCK.S3_RAW_STAGE/prices/;

-- =============================================================================
-- POST-SETUP: verify row counts after full load
-- =============================================================================
USE ROLE AIRBYTE_ROLE;

SELECT 'PRICES'        AS tbl, exchange, COUNT(*) AS rows FROM DATAPAI.STOCK.PRICES        GROUP BY exchange
UNION ALL
SELECT 'OHLCV_INTRADAY' AS tbl, exchange, COUNT(*) AS rows FROM DATAPAI.STOCK.OHLCV_INTRADAY GROUP BY exchange
ORDER BY 1, 2;
