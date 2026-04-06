-- stock_market_closed_dates: prevents intraday truncation on public holidays
-- Used by archive_and_truncate_intraday() in db_helpers.py

CREATE TABLE IF NOT EXISTS datapai.stock_market_closed_dates (
    market_code TEXT NOT NULL,
    closed_date DATE NOT NULL,
    reason TEXT,
    PRIMARY KEY (market_code, closed_date)
);

CREATE INDEX IF NOT EXISTS idx_closed_dates_date
    ON datapai.stock_market_closed_dates (closed_date);
