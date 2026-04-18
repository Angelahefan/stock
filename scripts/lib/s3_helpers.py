"""
scripts/lib/s3_helpers.py
─────────────────────────────────────────────────────────────────────────────
S3 + Parquet helpers for the DataPAI ETL pipeline.

Writes Pandas DataFrames as partitioned Parquet files to S3.

Partition layout (Hive-style, works with Snowflake stages + Athena):
    s3://codepais3/stock/raw/prices/exchange=US/year=2024/month=01/part-0001.parquet
    s3://codepais3/stock/raw/prices/exchange=ASX/year=2024/month=01/part-0001.parquet

Credentials:
    Uses boto3 default credential chain — no explicit vars needed.
    On EC2: automatically uses the instance IAM role.
    Locally: uses ~/.aws/credentials or AWS_PROFILE.
    AWS_DEFAULT_REGION is already set in .bash_profile.
"""
from __future__ import annotations

import io
import logging
import os
from typing import Iterator

import boto3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────

S3_BUCKET       = os.getenv("S3_BUCKET_STOCK",  "codepais3")
S3_RAW_PREFIX   = os.getenv("S3_RAW_PREFIX",    "stock/raw")
S3_BRONZE_PREFIX = os.getenv("S3_BRONZE_PREFIX", "stock/bronze")
AWS_REGION      = os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2")

# Parquet row-group size — balance between memory and read efficiency
_ROW_GROUP_SIZE = 100_000


def get_s3_client():
    """
    Return a boto3 S3 client.
    Uses the default credential chain: IAM instance role (EC2) → ~/.aws/credentials (local).
    AWS_DEFAULT_REGION is already exported in .bash_profile.
    """
    return boto3.client("s3", region_name=AWS_REGION)


# ── Prices (daily OHLCV) ───────────────────────────────────────────────────

# Arrow schema matching datapai.prices
PRICES_SCHEMA = pa.schema([
    pa.field("ticker",      pa.string(),  nullable=False),
    pa.field("trade_date",  pa.date32(),  nullable=False),
    pa.field("open",      pa.float64(), nullable=True),
    pa.field("high",      pa.float64(), nullable=True),
    pa.field("low",       pa.float64(), nullable=True),
    pa.field("close",     pa.float64(), nullable=False),
    pa.field("adj_close", pa.float64(), nullable=True),
    pa.field("volume",    pa.int64(),   nullable=True),
    pa.field("exchange",  pa.string(),  nullable=True),
    pa.field("source",    pa.string(),  nullable=True),
])

# Arrow schema matching datapai.ohlcv_intraday
INTRADAY_SCHEMA = pa.schema([
    pa.field("ticker",    pa.string(),              nullable=False),
    pa.field("ts",        pa.timestamp("us", "UTC"), nullable=False),
    pa.field("open",      pa.float64(),             nullable=True),
    pa.field("high",      pa.float64(),             nullable=True),
    pa.field("low",       pa.float64(),             nullable=True),
    pa.field("close",     pa.float64(),             nullable=False),
    pa.field("volume",    pa.int64(),               nullable=True),
    pa.field("exchange",  pa.string(),              nullable=True),
    pa.field("source",    pa.string(),              nullable=True),
])


# ── Write helpers ──────────────────────────────────────────────────────────

def _df_to_parquet_bytes(df: pd.DataFrame, schema: pa.Schema) -> bytes:
    """Serialize a DataFrame to Parquet bytes using the given schema."""
    table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    buf = io.BytesIO()
    pq.write_table(
        table, buf,
        row_group_size=_ROW_GROUP_SIZE,
        compression="snappy",
        use_dictionary=True,
    )
    return buf.getvalue()


def write_prices_partition(
    df: pd.DataFrame,
    exchange: str,
    year: int,
    month: int,
    part: int = 0,
    dry_run: bool = False,
) -> str:
    """
    Write a chunk of daily prices to S3 raw as Parquet.

    Returns the S3 key written.
    """
    key = (
        f"{S3_RAW_PREFIX}/prices/"
        f"exchange={exchange}/"
        f"year={year:04d}/month={month:02d}/"
        f"part-{part:04d}.parquet"
    )
    if dry_run:
        logger.info("[DRY RUN] Would write %d rows → s3://%s/%s", len(df), S3_BUCKET, key)
        return key

    data = _df_to_parquet_bytes(df, PRICES_SCHEMA)
    s3 = get_s3_client()
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=data)
    logger.info("Wrote %d rows (%d KB) → s3://%s/%s", len(df), len(data) // 1024, S3_BUCKET, key)
    return key


def write_intraday_partition(
    df: pd.DataFrame,
    exchange: str,
    year: int,
    month: int,
    part: int = 0,
    dry_run: bool = False,
) -> str:
    """Write a chunk of intraday bars to S3 raw as Parquet."""
    key = (
        f"{S3_RAW_PREFIX}/ohlcv_intraday/"
        f"exchange={exchange}/"
        f"year={year:04d}/month={month:02d}/"
        f"part-{part:04d}.parquet"
    )
    if dry_run:
        logger.info("[DRY RUN] Would write %d rows → s3://%s/%s", len(df), S3_BUCKET, key)
        return key

    data = _df_to_parquet_bytes(df, INTRADAY_SCHEMA)
    s3 = get_s3_client()
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=data)
    logger.info("Wrote %d rows (%d KB) → s3://%s/%s", len(df), len(data) // 1024, S3_BUCKET, key)
    return key


# ── Partition management ───────────────────────────────────────────────────

def delete_prices_partition(exchange: str, year: int, month: int) -> int:
    """
    Delete all Parquet files in a given prices partition on S3.
    Returns number of objects deleted.
    """
    prefix = (
        f"{S3_RAW_PREFIX}/prices/"
        f"exchange={exchange}/"
        f"year={year:04d}/month={month:02d}/"
    )
    return _delete_prefix(prefix)


def delete_intraday_partition(exchange: str, year: int, month: int) -> int:
    """Delete all intraday files in a given partition. Returns deleted count."""
    prefix = (
        f"{S3_RAW_PREFIX}/ohlcv_intraday/"
        f"exchange={exchange}/"
        f"year={year:04d}/month={month:02d}/"
    )
    return _delete_prefix(prefix)


def _delete_prefix(prefix: str) -> int:
    """Delete all S3 objects under prefix. Returns count deleted."""
    s3 = get_s3_client()
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append({"Key": obj["Key"]})

    if not keys:
        return 0

    # S3 delete_objects accepts max 1000 at a time
    for i in range(0, len(keys), 1000):
        s3.delete_objects(
            Bucket=S3_BUCKET,
            Delete={"Objects": keys[i:i + 1000]},
        )

    logger.info("Deleted %d objects at s3://%s/%s", len(keys), S3_BUCKET, prefix)
    return len(keys)


def list_raw_partitions(table: str = "prices") -> list[dict]:
    """
    List all existing partitions in the raw layer.
    Returns list of dicts: {exchange, year, month, key_prefix}.
    """
    s3 = get_s3_client()
    paginator = s3.get_paginator("list_objects_v2")
    prefix = f"{S3_RAW_PREFIX}/{table}/"
    partitions = set()
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            # Drill down: exchange=US/
            for page2 in paginator.paginate(
                Bucket=S3_BUCKET, Prefix=cp["Prefix"], Delimiter="/"
            ):
                for cp2 in page2.get("CommonPrefixes", []):
                    # year=YYYY/
                    for page3 in paginator.paginate(
                        Bucket=S3_BUCKET, Prefix=cp2["Prefix"], Delimiter="/"
                    ):
                        for cp3 in page3.get("CommonPrefixes", []):
                            # month=MM/
                            parts = cp3["Prefix"].rstrip("/").split("/")
                            result = {}
                            for p in parts:
                                if "=" in p:
                                    k, v = p.split("=", 1)
                                    result[k] = v
                            if result:
                                partitions.add(
                                    (result.get("exchange"), result.get("year"), result.get("month"))
                                )
    return [
        {"exchange": e, "year": int(y), "month": int(m)}
        for e, y, m in sorted(partitions)
    ]


# ── Generic table sync (for analytics tables: ta_indicators, fundamental, etc.) ──

def write_generic_table(
    df: pd.DataFrame,
    table_name: str,
    exchange: str,
    part: int = 0,
    dry_run: bool = False,
) -> str:
    """
    Write a DataFrame to S3 raw as Parquet for any analytics table.
    Path: s3://{bucket}/stock/raw/{table_name}/exchange={exchange}/latest.parquet
    Uses a simple overwrite strategy (no year/month partitions for small tables).
    """
    key = f"{S3_RAW_PREFIX}/{table_name}/exchange={exchange}/part-{part:04d}.parquet"

    if dry_run:
        logger.info("[DRY RUN] Would write %d rows → s3://%s/%s", len(df), S3_BUCKET, key)
        return key

    # Auto-detect schema from DataFrame
    table = pa.Table.from_pandas(df, preserve_index=False)
    buf = io.BytesIO()
    pq.write_table(table, buf, row_group_size=_ROW_GROUP_SIZE, compression="snappy", use_dictionary=True)
    data = buf.getvalue()

    s3 = get_s3_client()
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=data)
    logger.info("Wrote %d rows (%d KB) → s3://%s/%s", len(df), len(data) // 1024, S3_BUCKET, key)
    return key


def delete_generic_table(table_name: str, exchange: str) -> int:
    """Delete all S3 objects for a generic table/exchange partition."""
    prefix = f"{S3_RAW_PREFIX}/{table_name}/exchange={exchange}/"
    return _delete_prefix(prefix)
