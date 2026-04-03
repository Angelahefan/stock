#!/usr/bin/env python3
"""
select_synthesis_candidates.py — Find "interesting" stocks from screener_metrics.

Queries screener_metrics for stocks in market_top_stocks that match actionable patterns:
  - Oversold bounce (RSI < 30, high volume)
  - Overbought reversal (RSI > 70, bearish MACD)
  - Bullish breakout (golden cross, big move)
  - Deep drawdown (>30% from 52w high)
  - Big movers (>5% daily change)

Inserts into datapai.synthesis_candidates for the synthesis pipeline to process.

Usage:
    python3 scripts/select_synthesis_candidates.py
    python3 scripts/select_synthesis_candidates.py --exchange US
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.lib.db_helpers import get_conn
from scripts.lib.log_setup import setup_logging

logger = setup_logging("select_synthesis_candidates")


def select_candidates(exchange: str = None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Create candidates table if not exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS datapai.synthesis_candidates (
                    ticker TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    reason TEXT,
                    priority INT DEFAULT 2,  -- 1=MUST, 2=SHOULD, 3=NICE
                    selected_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (ticker, exchange)
                )
            """)

            # Clear previous candidates
            if exchange:
                cur.execute("DELETE FROM datapai.synthesis_candidates WHERE exchange = %s", [exchange])
            else:
                cur.execute("DELETE FROM datapai.synthesis_candidates")

            # Tier 1 (MUST): demo stocks + all watchlisted stocks
            cur.execute("""
                INSERT INTO datapai.synthesis_candidates (ticker, exchange, reason, priority)
                SELECT DISTINCT ticker, exchange, 'demo_stock', 1
                FROM datapai.market_demo_stocks
                WHERE (%s IS NULL OR exchange = %s)
                ON CONFLICT (ticker, exchange) DO NOTHING
            """, [exchange, exchange])
            demo_count = cur.rowcount

            cur.execute("""
                INSERT INTO datapai.synthesis_candidates (ticker, exchange, reason, priority)
                SELECT DISTINCT w.symbol AS ticker,
                       COALESCE(w.exchange, 'US') AS exchange,
                       'watchlist', 1
                FROM datapai.watchlist w
                WHERE (%s IS NULL OR w.exchange = %s)
                ON CONFLICT (ticker, exchange) DO NOTHING
            """, [exchange, exchange])
            watch_count = cur.rowcount

            # Tier 2 (SHOULD): screener candidates with strong signals
            # Only from market_top_stocks (top 300 per market)
            cur.execute("""
                INSERT INTO datapai.synthesis_candidates (ticker, exchange, reason, priority)
                SELECT sm.ticker, sm.exchange,
                    CASE
                        WHEN sm.rsi_14 < 30 AND sm.volume_ratio > 1.5 THEN 'oversold_bounce'
                        WHEN sm.rsi_14 > 70 AND sm.macd_trend = 'BEARISH' THEN 'overbought_reversal'
                        WHEN sm.golden_cross AND sm.change_1d_pct > 2 THEN 'bullish_breakout'
                        WHEN sm.pct_from_52w_high < -30 THEN 'deep_drawdown'
                        WHEN ABS(sm.change_1d_pct) > 5 THEN 'big_mover'
                        ELSE 'screener_signal'
                    END AS reason,
                    2 AS priority
                FROM datapai.screener_metrics sm
                INNER JOIN datapai.market_top_stocks mts
                    ON mts.ticker = sm.ticker AND mts.exchange = sm.exchange
                WHERE (%s IS NULL OR sm.exchange = %s)
                  AND (
                    (sm.rsi_14 < 30 AND sm.volume_ratio > 1.5)
                    OR (sm.rsi_14 > 70 AND sm.macd_trend = 'BEARISH')
                    OR (sm.golden_cross AND sm.change_1d_pct > 2)
                    OR (sm.pct_from_52w_high < -30)
                    OR (ABS(sm.change_1d_pct) > 5)
                  )
                ON CONFLICT (ticker, exchange) DO NOTHING
            """, [exchange, exchange])
            screener_count = cur.rowcount

            # Summary
            cur.execute("""
                SELECT priority, COUNT(*) FROM datapai.synthesis_candidates
                WHERE (%s IS NULL OR exchange = %s)
                GROUP BY priority ORDER BY priority
            """, [exchange, exchange])
            for row in cur.fetchall():
                logger.info("  Priority %d: %d candidates", row[0], row[1])

            total = demo_count + watch_count + screener_count
            logger.info("Selected %d candidates (demo=%d, watchlist=%d, screener=%d)",
                        total, demo_count, watch_count, screener_count)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange", default=None, help="Filter to one exchange")
    args = parser.parse_args()
    select_candidates(args.exchange)


if __name__ == "__main__":
    main()
