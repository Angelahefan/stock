"""
scripts/lib/snowflake_helpers.py
─────────────────────────────────────────────────────────────────────────────
Snowflake connector helpers for the DataPAI stock pipeline.

Architecture:
    S3 raw  (Parquet, written by Python)
        └─► Snowflake permanent tables  (DATAPAI.STOCK schema)

Tables:
    • DATAPAI.STOCK.PRICES          — daily OHLCV, ~7M rows
    • DATAPAI.STOCK.OHLCV_INTRADAY  — 30-minute bars

Credentials:
    Uses existing env vars from .bash_profile / .streamlit/secrets.toml —
    no new variables needed:
        SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD,
        SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE, SNOWFLAKE_ROLE

    S3 access for Snowflake stage uses a storage integration (IAM role trust).
    One-time admin step: create DATAPAI_S3_INTEGRATION in Snowflake,
    then attach the Snowflake-provided policy to the EC2 instance IAM role.
    See: https://docs.snowflake.com/en/user-guide/data-load-s3-config-storage-integration
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Generator

logger = logging.getLogger(__name__)

# ── Connection config — uses existing .bash_profile vars ──────────────────
SF_ACCOUNT   = os.getenv("SNOWFLAKE_ACCOUNT",   "")
SF_USER      = os.getenv("SNOWFLAKE_USER",      "")
SF_PASSWORD  = os.getenv("SNOWFLAKE_PASSWORD",  "")
SF_WAREHOUSE = os.getenv("SNOWFLAKE_WAREHOUSE", "DATAPAI_WAREHOUSE")
SF_DATABASE  = os.getenv("SNOWFLAKE_DATABASE",  "DATAPAI")
SF_ROLE      = os.getenv("SNOWFLAKE_ROLE",      "AIRBYTE_ROLE")

# Stock tables live in the STOCK schema inside the existing DATAPAI database
# (DATAPAI database + credentials already set up in .bash_profile)
SF_ICEBERG_SCHEMA = "STOCK"

# S3 config — bucket from env var, region from existing AWS_DEFAULT_REGION
S3_BUCKET        = os.getenv("S3_BUCKET_STOCK",      "codepais3")
S3_RAW_PREFIX    = "stock/raw"
AWS_REGION       = os.getenv("AWS_DEFAULT_REGION",   "ap-southeast-2")

# IAM role ARN that Snowflake uses to access S3
# Created once: Snowflake → AWS trust relationship for the DATAPAI_S3_INTEGRATION
SNOWFLAKE_S3_ROLE_ARN = os.getenv("SNOWFLAKE_S3_ROLE_ARN", "")

STORAGE_INTEGRATION = "DATAPAI_S3_INTEGRATION"   # created once by Snowflake admin
S3_RAW_URL         = f"s3://{S3_BUCKET}/{S3_RAW_PREFIX}/"


# ── Connection ─────────────────────────────────────────────────────────────

@contextmanager
def get_sf_conn() -> Generator:
    """Yield a Snowflake connection using existing env vars, close on exit."""
    try:
        import snowflake.connector as sf
    except ImportError:
        raise RuntimeError(
            "snowflake-connector-python not installed. "
            "Run: pip install snowflake-connector-python"
        )

    if not SF_ACCOUNT or not SF_USER:
        raise RuntimeError(
            "Snowflake credentials missing. "
            "Ensure SNOWFLAKE_ACCOUNT + SNOWFLAKE_USER are in .bash_profile."
        )

    conn = sf.connect(
        account=SF_ACCOUNT,
        user=SF_USER,
        password=SF_PASSWORD,
        warehouse=SF_WAREHOUSE,
        database=SF_DATABASE,
        schema=SF_ICEBERG_SCHEMA,
        role=SF_ROLE,
    )
    try:
        logger.info("Snowflake → %s / %s / %s", SF_ACCOUNT, SF_DATABASE, SF_ICEBERG_SCHEMA)
        yield conn
    finally:
        conn.close()


def execute(conn, sql: str, params=None, log: bool = True) -> list[dict]:
    """Execute SQL and return rows as list of dicts."""
    if log:
        preview = sql.strip()[:120].replace("\n", " ")
        logger.info("SF ▶ %s", preview)
    cur = conn.cursor()
    cur.execute(sql, params)
    cols = [d[0].lower() for d in (cur.description or [])]
    rows = [dict(zip(cols, row)) for row in (cur.fetchall() or [])]
    cur.close()
    return rows


# ── DDL: one-time setup ────────────────────────────────────────────────────

# Storage integration: Snowflake IAM role trust (no AWS keys needed in stage)
# Run this as ACCOUNTADMIN once, then attach the Snowflake-generated policy to
# the DATAPAI_S3_INTEGRATION IAM role via AWS console.
DDL_STORAGE_INTEGRATION = f"""
CREATE STORAGE INTEGRATION IF NOT EXISTS {STORAGE_INTEGRATION}
  TYPE = EXTERNAL_STAGE
  STORAGE_PROVIDER = 'S3'
  ENABLED = TRUE
  STORAGE_AWS_ROLE_ARN = '{SNOWFLAKE_S3_ROLE_ARN}'
  STORAGE_ALLOWED_LOCATIONS = ('s3://{S3_BUCKET}/stock/');
""".strip()

# STOCK schema for stock tables
DDL_SCHEMA = f"CREATE SCHEMA IF NOT EXISTS {SF_DATABASE}.{SF_ICEBERG_SCHEMA};"

# S3 stage for reading raw Parquet — uses storage integration (no keys)
DDL_RAW_STAGE = f"""
CREATE STAGE IF NOT EXISTS {SF_DATABASE}.{SF_ICEBERG_SCHEMA}.S3_RAW_STAGE
  URL = '{S3_RAW_URL}'
  STORAGE_INTEGRATION = {STORAGE_INTEGRATION}
  FILE_FORMAT = (TYPE = PARQUET SNAPPY_COMPRESSION = TRUE);
""".strip()

# Regular permanent table: daily prices
DDL_PRICES = f"""
CREATE TABLE IF NOT EXISTS {SF_DATABASE}.{SF_ICEBERG_SCHEMA}.PRICES (
    ticker      VARCHAR(20)  NOT NULL    COMMENT 'Stock ticker symbol',
    trade_date  DATE         NOT NULL    COMMENT 'Trading date',
    open        DOUBLE                   COMMENT 'Open price',
    high        DOUBLE                   COMMENT 'Intraday high',
    low         DOUBLE                   COMMENT 'Intraday low',
    close       DOUBLE       NOT NULL    COMMENT 'Close price',
    adj_close   DOUBLE                   COMMENT 'Dividend/split-adjusted close',
    volume      BIGINT                   COMMENT 'Volume traded',
    exchange    VARCHAR(10)              COMMENT 'Exchange: US or ASX',
    source      VARCHAR(20)              COMMENT 'Data source: yahoo or polygon'
) COMMENT = 'Daily OHLCV for US + ASX stocks.';
""".strip()

# Regular permanent table: 30m intraday
DDL_INTRADAY = f"""
CREATE TABLE IF NOT EXISTS {SF_DATABASE}.{SF_ICEBERG_SCHEMA}.OHLCV_INTRADAY (
    ticker      VARCHAR(20)  NOT NULL    COMMENT 'Stock ticker symbol',
    ts          TIMESTAMP_TZ NOT NULL    COMMENT 'Bar open timestamp (UTC)',
    open        DOUBLE                   COMMENT 'Open price',
    high        DOUBLE                   COMMENT 'Intraday high',
    low         DOUBLE                   COMMENT 'Intraday low',
    close       DOUBLE       NOT NULL    COMMENT 'Close price',
    volume      BIGINT                   COMMENT 'Volume',
    exchange    VARCHAR(10)              COMMENT 'Exchange: US or ASX',
    source      VARCHAR(20)              COMMENT 'Data source: polygon or yahoo'
) COMMENT = '30-minute OHLCV bars.';
""".strip()


def setup_snowflake(conn) -> None:
    """
    One-time DDL: schema → storage integration → stage → permanent tables.

    Step requiring ACCOUNTADMIN (run manually or with elevated role):
      1. CREATE STORAGE INTEGRATION  (needs ACCOUNTADMIN)
      2. Run: DESC INTEGRATION DATAPAI_S3_INTEGRATION;
         Copy STORAGE_AWS_IAM_USER_ARN and STORAGE_AWS_EXTERNAL_ID
         Attach the generated policy to the IAM role in AWS console.
    """
    if not SNOWFLAKE_S3_ROLE_ARN:
        raise RuntimeError(
            "SNOWFLAKE_S3_ROLE_ARN env var is required for setup. "
            "Set it to the IAM role ARN that Snowflake uses to access S3 "
            "(e.g. arn:aws:iam::123456789012:role/snowflake-datapai-role)."
        )

    logger.info("=== Snowflake Stock Setup ===")
    execute(conn, DDL_SCHEMA)
    logger.info("Schema %s.%s ready", SF_DATABASE, SF_ICEBERG_SCHEMA)

    # Requires ACCOUNTADMIN — will fail with insufficient privileges if role is wrong.
    # Re-run with SNOWFLAKE_ROLE=ACCOUNTADMIN if needed.
    execute(conn, DDL_STORAGE_INTEGRATION)

    execute(conn, DDL_RAW_STAGE)
    execute(conn, DDL_PRICES)
    execute(conn, DDL_INTRADAY)
    logger.info("=== Setup complete ===")


# ── Load helpers ───────────────────────────────────────────────────────────

def load_prices_from_stage(conn, exchange: str, year: int, month: int) -> int:
    """
    Reload one monthly partition from S3 raw Parquet into Snowflake PRICES table.
    DELETE first (idempotent), then INSERT from stage.
    """
    stage_path = (
        f"@{SF_DATABASE}.{SF_ICEBERG_SCHEMA}.S3_RAW_STAGE"
        f"/prices/exchange={exchange}/year={year:04d}/month={month:02d}/"
    )
    execute(conn, f"""
        DELETE FROM {SF_DATABASE}.{SF_ICEBERG_SCHEMA}.PRICES
        WHERE exchange = '{exchange}'
          AND YEAR(trade_date) = {year}
          AND MONTH(trade_date) = {month};
    """)
    execute(conn, f"""
        INSERT INTO {SF_DATABASE}.{SF_ICEBERG_SCHEMA}.PRICES
        SELECT
            $1:ticker::VARCHAR,
            $1:trade_date::DATE,
            $1:open::DOUBLE,
            $1:high::DOUBLE,
            $1:low::DOUBLE,
            $1:close::DOUBLE,
            $1:adj_close::DOUBLE,
            $1:volume::BIGINT,
            $1:exchange::VARCHAR,
            $1:source::VARCHAR
        FROM {stage_path};
    """)
    rows = execute(conn, f"""
        SELECT COUNT(*) AS cnt FROM {SF_DATABASE}.{SF_ICEBERG_SCHEMA}.PRICES
        WHERE exchange = '{exchange}' AND YEAR(trade_date) = {year} AND MONTH(trade_date) = {month};
    """)
    count = rows[0]["cnt"] if rows else 0
    logger.info("prices  %s  %d-%02d → %d rows", exchange, year, month, count)
    return count


def load_intraday_from_stage(conn, exchange: str, year: int, month: int) -> int:
    """Reload one monthly intraday partition into Snowflake."""
    stage_path = (
        f"@{SF_DATABASE}.{SF_ICEBERG_SCHEMA}.S3_RAW_STAGE"
        f"/ohlcv_intraday/exchange={exchange}/year={year:04d}/month={month:02d}/"
    )
    execute(conn, f"""
        DELETE FROM {SF_DATABASE}.{SF_ICEBERG_SCHEMA}.OHLCV_INTRADAY
        WHERE exchange = '{exchange}'
          AND YEAR(ts) = {year}
          AND MONTH(ts) = {month};
    """)
    execute(conn, f"""
        INSERT INTO {SF_DATABASE}.{SF_ICEBERG_SCHEMA}.OHLCV_INTRADAY
        SELECT
            $1:ticker::VARCHAR,
            $1:ts::TIMESTAMP_TZ,
            $1:open::DOUBLE,
            $1:high::DOUBLE,
            $1:low::DOUBLE,
            $1:close::DOUBLE,
            $1:volume::BIGINT,
            $1:exchange::VARCHAR,
            $1:source::VARCHAR
        FROM {stage_path};
    """)
    rows = execute(conn, f"""
        SELECT COUNT(*) AS cnt FROM {SF_DATABASE}.{SF_ICEBERG_SCHEMA}.OHLCV_INTRADAY
        WHERE exchange = '{exchange}' AND YEAR(ts) = {year} AND MONTH(ts) = {month};
    """)
    count = rows[0]["cnt"] if rows else 0
    logger.info("intraday  %s  %d-%02d → %d rows", exchange, year, month, count)
    return count


def get_row_counts(conn) -> dict:
    """Return row counts for both stock tables."""
    prices   = execute(conn, f"SELECT COUNT(*) AS cnt FROM {SF_DATABASE}.{SF_ICEBERG_SCHEMA}.PRICES;")
    intraday = execute(conn, f"SELECT COUNT(*) AS cnt FROM {SF_DATABASE}.{SF_ICEBERG_SCHEMA}.OHLCV_INTRADAY;")
    return {
        "prices":         prices[0]["cnt"]   if prices   else 0,
        "ohlcv_intraday": intraday[0]["cnt"] if intraday else 0,
    }


# ── Analytics tables: DDL + Load ───────────────────────────────────────────

_ANALYTICS_DDLS = {}

def _build_ddls():
    """Build DDLs using module-level SF_DATABASE and SF_ICEBERG_SCHEMA."""
    db = SF_DATABASE
    sc = SF_ICEBERG_SCHEMA
    return {
        "TA_INDICATORS": f"""CREATE TABLE IF NOT EXISTS {db}.{sc}.TA_INDICATORS (
    ticker VARCHAR(20) NOT NULL, exchange VARCHAR(10) NOT NULL,
    timeframe VARCHAR(5) NOT NULL, ts TIMESTAMP_TZ NOT NULL, trade_date DATE NOT NULL,
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT, change_pct DOUBLE,
    rsi DOUBLE, rsi_label VARCHAR(12),
    macd_line DOUBLE, macd_signal DOUBLE, macd_hist DOUBLE, macd_label VARCHAR(8),
    bb_upper DOUBLE, bb_middle DOUBLE, bb_lower DOUBLE, bb_pct DOUBLE, bb_label VARCHAR(20),
    ema_5 DOUBLE, ema_9 DOUBLE, ema_10 DOUBLE, ema_20 DOUBLE, ema_21 DOUBLE,
    ema_30 DOUBLE, ema_50 DOUBLE, ema_200 DOUBLE,
    stoch_k DOUBLE, stoch_d DOUBLE, stoch_label VARCHAR(12),
    atr DOUBLE, atr_pct DOUBLE, adx DOUBLE, plus_di DOUBLE, minus_di DOUBLE, adx_label VARCHAR(15),
    obv DOUBLE, obv_trend VARCHAR(5),
    vol_ma_5 DOUBLE, vol_ma_10 DOUBLE, vol_ma_30 DOUBLE,
    vol_ratio_5 DOUBLE, vol_ratio_10 DOUBLE, vol_ratio_30 DOUBLE,
    overall_signal VARCHAR(12), signal_score DOUBLE,
    quality_ok BOOLEAN, low_volume BOOLEAN, suspicious_move BOOLEAN,
    source VARCHAR(20), computed_at TIMESTAMP_TZ);""",

        "TA_SIGNALS": f"""CREATE TABLE IF NOT EXISTS {db}.{sc}.TA_SIGNALS (
    id VARCHAR NOT NULL, ticker VARCHAR NOT NULL, exchange VARCHAR NOT NULL,
    signal_md VARCHAR, current_price DOUBLE, change_pct DOUBLE,
    rsi DOUBLE, rsi_label VARCHAR, trend VARCHAR, macd_label VARCHAR, bb_label VARCHAR,
    indicators_json VARCHAR, generated_at VARCHAR NOT NULL, expires_at VARCHAR NOT NULL);""",

        "FUNDAMENTAL_SNAPSHOT": f"""CREATE TABLE IF NOT EXISTS {db}.{sc}.FUNDAMENTAL_SNAPSHOT (
    ticker VARCHAR(20) NOT NULL, exchange VARCHAR(10) NOT NULL,
    company_name VARCHAR(255), sector VARCHAR(100), industry VARCHAR(100),
    currency VARCHAR(10), market_cap BIGINT, enterprise_value BIGINT,
    pe_ratio DOUBLE, forward_pe DOUBLE, peg_ratio DOUBLE, pb_ratio DOUBLE,
    ps_ratio DOUBLE, ev_ebitda DOUBLE, ev_revenue DOUBLE,
    gross_margin DOUBLE, operating_margin DOUBLE, net_margin DOUBLE,
    roe DOUBLE, roa DOUBLE, roic DOUBLE,
    revenue_yoy DOUBLE, earnings_yoy DOUBLE, revenue_growth_5yr DOUBLE, eps_growth_5yr DOUBLE,
    current_ratio DOUBLE, quick_ratio DOUBLE, debt_to_equity DOUBLE, interest_coverage DOUBLE,
    total_cash BIGINT, total_debt BIGINT, net_cash BIGINT,
    free_cash_flow BIGINT, fcf_per_share DOUBLE, fcf_yield DOUBLE, operating_cf_margin DOUBLE,
    dividend_yield DOUBLE, payout_ratio DOUBLE, beta DOUBLE, short_ratio DOUBLE,
    next_earnings_date DATE,
    valuation_score DOUBLE, quality_score DOUBLE, growth_score DOUBLE, macro_score DOUBLE,
    fundamental_score DOUBLE, fundamental_signal VARCHAR(20),
    analyst_consensus VARCHAR(20), analyst_target_price DOUBLE, analyst_upside_pct DOUBLE,
    macro_summary VARCHAR, tech_disruption_risk VARCHAR(20),
    fundamental_summary VARCHAR, source VARCHAR(50), computed_at TIMESTAMP_TZ NOT NULL);""",

        "FUNDAMENTAL_HISTORY": f"""CREATE TABLE IF NOT EXISTS {db}.{sc}.FUNDAMENTAL_HISTORY (
    ticker VARCHAR(20) NOT NULL, exchange VARCHAR(10) NOT NULL,
    period_end DATE NOT NULL, period_type VARCHAR(10) NOT NULL,
    revenue BIGINT, gross_profit BIGINT, operating_income BIGINT, net_income BIGINT,
    ebitda BIGINT, eps DOUBLE, free_cash_flow BIGINT, operating_cash_flow BIGINT,
    capex BIGINT, total_assets BIGINT, total_debt BIGINT, shareholders_equity BIGINT,
    cash_and_equivalents BIGINT,
    revenue_yoy DOUBLE, earnings_yoy DOUBLE, fcf_yoy DOUBLE,
    source VARCHAR(50), computed_at TIMESTAMP_TZ NOT NULL);""",

        "ANALYSES": f"""CREATE TABLE IF NOT EXISTS {db}.{sc}.ANALYSES (
    id VARCHAR NOT NULL, snapshot_new_id VARCHAR, diff_id VARCHAR,
    ticker VARCHAR, url VARCHAR,
    commitment_delta DOUBLE, hedging_delta DOUBLE, risk_delta DOUBLE,
    alert_score DOUBLE, confidence DOUBLE, categories_json VARCHAR,
    llm_summary_paid VARCHAR, llm_summary_private VARCHAR, reasoning_evidence_json VARCHAR,
    signal_type VARCHAR, agent_signal_type VARCHAR, agent_severity VARCHAR, agent_confidence DOUBLE,
    agent_financial_relevance VARCHAR, agent_evidence_json VARCHAR,
    validation_status VARCHAR, validation_summary VARCHAR, validation_evidence_json VARCHAR,
    agent_what_changed VARCHAR, agent_why_matters VARCHAR,
    change_type VARCHAR, change_quality_score DOUBLE, financial_relevance_score DOUBLE,
    investigation_summary VARCHAR, investigation_sources VARCHAR, corroborating_count INT);""",

        
        "STOCK_SYNTHESIS": f"""CREATE TABLE IF NOT EXISTS {db}.{sc}.STOCK_SYNTHESIS (
    ticker VARCHAR(20) NOT NULL, exchange VARCHAR(10) NOT NULL,
    direction VARCHAR(20) NOT NULL, confidence DOUBLE NOT NULL,
    conviction VARCHAR(10) NOT NULL,
    thesis VARCHAR, what_bulls_say VARCHAR, what_bears_say VARCHAR, key_risk VARCHAR,
    ta_direction VARCHAR(20), fa_direction VARCHAR(20), ma_direction VARCHAR(20),
    signals_aligned BOOLEAN, disagreement_summary VARCHAR,
    debate_points_json VARCHAR, debate_rounds INT,
    model_used VARCHAR(50), total_tokens INT,
    computed_at TIMESTAMP_TZ NOT NULL);""",
        "BROKER_RATINGS": f"""CREATE TABLE IF NOT EXISTS {db}.{sc}.BROKER_RATINGS (
    ticker VARCHAR NOT NULL, exchange VARCHAR, broker VARCHAR, rating VARCHAR,
    target_price DOUBLE, date VARCHAR, source VARCHAR);""",
    }


def setup_analytics_tables(conn) -> None:
    """Create analytics tables in Snowflake STOCK schema."""
    ddls = _build_ddls()
    logger.info("=== Creating analytics tables ===")
    for name, ddl in ddls.items():
        execute(conn, ddl)
        logger.info("Table %s.%s.%s ready", SF_DATABASE, SF_ICEBERG_SCHEMA, name)


def load_generic_from_stage(conn, s3_table_name: str, sf_table_name: str, exchange: str) -> int:
    """Load analytics table from S3 stage into Snowflake (DELETE+INSERT)."""
    stage_path = (
        f"@{SF_DATABASE}.{SF_ICEBERG_SCHEMA}.S3_RAW_STAGE"
        f"/{s3_table_name}/exchange={exchange}/"
    )
    cols = execute(conn, f"""
        SELECT COLUMN_NAME FROM {SF_DATABASE}.INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = '{SF_ICEBERG_SCHEMA}' AND TABLE_NAME = '{sf_table_name}'
        ORDER BY ORDINAL_POSITION;
    """, log=False)
    if not cols:
        logger.warning("No columns for %s.%s — skip", SF_ICEBERG_SCHEMA, sf_table_name)
        return 0

    col_names = [c["column_name"].lower() for c in cols]

    if "exchange" in col_names:
        execute(conn, f"DELETE FROM {SF_DATABASE}.{SF_ICEBERG_SCHEMA}.{sf_table_name} WHERE exchange = '{exchange}';")
    else:
        execute(conn, f"DELETE FROM {SF_DATABASE}.{SF_ICEBERG_SCHEMA}.{sf_table_name};")

    select_cols = ", ".join(f"$1:{c}::VARCHAR" for c in col_names)
    execute(conn, f"""
        INSERT INTO {SF_DATABASE}.{SF_ICEBERG_SCHEMA}.{sf_table_name}
        SELECT {select_cols} FROM {stage_path};
    """)

    rows = execute(conn, f"SELECT COUNT(*) AS cnt FROM {SF_DATABASE}.{SF_ICEBERG_SCHEMA}.{sf_table_name};")
    count = rows[0]["cnt"] if rows else 0
    logger.info("%s  %s -> %d total rows", sf_table_name, exchange, count)
    return count
