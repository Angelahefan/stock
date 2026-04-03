#!/usr/bin/env python3
"""
scripts/check_news_watchlist.py
─────────────────────────────────────────────────────────────────────────────
Check breaking news for all watchlist tickers.
Runs via Airflow every 20 minutes during market hours.
"""
import sys
import os
import logging
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load environment variables (.env.dev first, .env fills gaps)
from dotenv import load_dotenv
if (PROJECT_ROOT / ".env.dev").exists():
    load_dotenv(PROJECT_ROOT / ".env.dev")
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("check_news")


def main():
    from scripts.lib.db_helpers import get_conn
    from agents.news_agent import run_news_agent, Severity

    # Get all distinct watchlist tickers
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT symbol, exchange FROM datapai.watchlist")
            tickers = [(row[0], row[1]) for row in cur.fetchall()]

    if not tickers:
        logger.info("No watchlist tickers found — nothing to check")
        return

    logger.info("Checking news for %d watchlist tickers", len(tickers))

    critical_count = 0
    high_count = 0

    for ticker, exchange in tickers:
        try:
            result = run_news_agent(ticker, exchange=exchange, persist=True)
            level = "INFO"
            if result.has_critical_event:
                level = "CRITICAL"
                critical_count += 1
            elif result.highest_severity == Severity.HIGH:
                level = "HIGH"
                high_count += 1

            if result.news_items_fetched > 0:
                logger.log(
                    logging.CRITICAL if level == "CRITICAL" else logging.WARNING if level == "HIGH" else logging.INFO,
                    "[%s] %s — %d news items, %d material events, severity=%s, sentiment=%s",
                    level, ticker, result.news_items_fetched,
                    len(result.material_events),
                    result.highest_severity.value if result.highest_severity else "NONE",
                    result.overall_sentiment.value if result.overall_sentiment else "NEUTRAL",
                )
        except Exception as exc:
            logger.error("Failed to check news for %s: %s", ticker, str(exc)[:200])

    logger.info(
        "News check complete: %d tickers checked, %d CRITICAL, %d HIGH",
        len(tickers), critical_count, high_count,
    )


if __name__ == "__main__":
    main()
