-- ============================================================================
-- 030: Partition datapai.prices by exchange (LIST partitioning)
--
-- Converts the monolithic prices table into exchange-based partitions.
-- Zero downtime: creates new partitioned table, migrates data, swaps names.
--
-- Benefits:
-- - Parallel EOD inserts hit different partitions (zero lock contention)
-- - Exchange-scoped queries only scan relevant partition
-- - Each partition can be independently vacuumed/analyzed
-- - Future: can move partitions to different tablespaces
-- ============================================================================

BEGIN;

-- 1. Create new partitioned table with same schema
CREATE TABLE datapai.prices_partitioned (
    ticker      TEXT NOT NULL,
    trade_date  TEXT NOT NULL,
    close       NUMERIC,
    volume      BIGINT,
    open        NUMERIC,
    high        NUMERIC,
    low         NUMERIC,
    adj_close   NUMERIC,
    exchange    TEXT NOT NULL DEFAULT 'US',
    source      TEXT
) PARTITION BY LIST (exchange);

-- 2. Create partitions for each exchange
CREATE TABLE datapai.prices_us     PARTITION OF datapai.prices_partitioned FOR VALUES IN ('US');
CREATE TABLE datapai.prices_asx    PARTITION OF datapai.prices_partitioned FOR VALUES IN ('ASX');
CREATE TABLE datapai.prices_hkex   PARTITION OF datapai.prices_partitioned FOR VALUES IN ('HKEX');
CREATE TABLE datapai.prices_hose   PARTITION OF datapai.prices_partitioned FOR VALUES IN ('HOSE');
CREATE TABLE datapai.prices_set    PARTITION OF datapai.prices_partitioned FOR VALUES IN ('SET');
CREATE TABLE datapai.prices_klse   PARTITION OF datapai.prices_partitioned FOR VALUES IN ('KLSE');
CREATE TABLE datapai.prices_idx    PARTITION OF datapai.prices_partitioned FOR VALUES IN ('IDX');
CREATE TABLE datapai.prices_sse    PARTITION OF datapai.prices_partitioned FOR VALUES IN ('SSE');
CREATE TABLE datapai.prices_szse   PARTITION OF datapai.prices_partitioned FOR VALUES IN ('SZSE');
CREATE TABLE datapai.prices_lse    PARTITION OF datapai.prices_partitioned FOR VALUES IN ('LSE');
CREATE TABLE datapai.prices_index  PARTITION OF datapai.prices_partitioned FOR VALUES IN ('INDEX');
-- Default partition for any future exchanges
CREATE TABLE datapai.prices_other  PARTITION OF datapai.prices_partitioned DEFAULT;

-- 3. Create indexes on partitioned table (Postgres auto-creates per partition)
CREATE UNIQUE INDEX idx_pp_ticker_date_exchange ON datapai.prices_partitioned (ticker, trade_date, exchange);
CREATE INDEX idx_pp_exchange_date ON datapai.prices_partitioned (exchange, trade_date DESC);
CREATE INDEX idx_pp_ticker_date ON datapai.prices_partitioned (ticker, trade_date DESC);

-- 4. Migrate data (this is the slow part — ~21M rows)
INSERT INTO datapai.prices_partitioned
SELECT ticker, trade_date, close, volume, open, high, low, adj_close, exchange, source
FROM datapai.prices;

-- 5. Swap tables atomically
ALTER TABLE datapai.prices RENAME TO prices_old;
ALTER TABLE datapai.prices_partitioned RENAME TO prices;

-- 6. Done — verify
-- SELECT tableoid::regclass, COUNT(*) FROM datapai.prices GROUP BY 1 ORDER BY 1;

COMMIT;

-- After verifying everything works:
-- DROP TABLE datapai.prices_old;
