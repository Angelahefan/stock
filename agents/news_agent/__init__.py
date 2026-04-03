"""
agents/news_agent — Material Event / Breaking News Agent
=========================================================
Fetches breaking news from free sources (Google News RSS, Finnhub, SEC EDGAR, ASX Announcements),
classifies material events using LLM, and stores them in Postgres.

Integrates with the AG2 multi-agent synthesis pipeline to bias recommendations
when CRITICAL events are detected.

Public API:
    fetch_news()           — fetch breaking news from all sources
    classify_events()      — LLM-classify news items as material events
    run_news_agent()       — full pipeline: fetch + classify + store
    save_material_events() — persist events to DB
    get_latest_events()    — read stored events from DB
    ensure_table()         — create DB table if missing
"""

from agents.news_agent.news_fetcher import fetch_news
from agents.news_agent.event_classifier import classify_events
from agents.news_agent.db import (
    save_material_events,
    get_latest_events,
    ensure_table,
)
from agents.news_agent.contracts import (
    NewsItem,
    MaterialEvent,
    NewsAgentResult,
    EventType,
    Severity,
    Sentiment,
)

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def run_news_agent(
    ticker: str,
    exchange: str = "US",
    persist: bool = True,
) -> NewsAgentResult:
    """
    Full news agent pipeline: fetch news -> classify events -> optionally store.

    Args:
        ticker: Stock ticker symbol (e.g. "AAPL")
        exchange: Exchange code ("US" or "ASX")
        persist: If True, save material events to Postgres

    Returns:
        NewsAgentResult with all classified material events
    """
    # 1. Fetch news from all sources (exchange-aware)
    news_items = fetch_news(ticker, exchange=exchange)

    if not news_items:
        logger.info("No news items found for %s — returning empty result", ticker)
        return NewsAgentResult(
            ticker=ticker,
            exchange=exchange,
            news_items_fetched=0,
        )

    # 2. Classify events using LLM
    events = classify_events(ticker, news_items)

    # 3. Compute aggregate metrics
    has_critical = any(e.severity == Severity.CRITICAL for e in events)

    severity_rank = {
        Severity.CRITICAL: 4,
        Severity.HIGH: 3,
        Severity.MEDIUM: 2,
        Severity.LOW: 1,
        Severity.NONE: 0,
    }
    highest = Severity.NONE
    for e in events:
        if severity_rank.get(e.severity, 0) > severity_rank.get(highest, 0):
            highest = e.severity

    # Overall sentiment: weighted by severity
    sentiment_score = 0.0
    total_weight = 0.0
    sentiment_map = {
        Sentiment.VERY_NEGATIVE: -2,
        Sentiment.NEGATIVE: -1,
        Sentiment.NEUTRAL: 0,
        Sentiment.POSITIVE: 1,
        Sentiment.VERY_POSITIVE: 2,
    }
    for e in events:
        weight = severity_rank.get(e.severity, 0) + 1
        sentiment_score += sentiment_map.get(e.sentiment, 0) * weight
        total_weight += weight

    if total_weight > 0:
        avg = sentiment_score / total_weight
        if avg <= -1.5:
            overall_sentiment = Sentiment.VERY_NEGATIVE
        elif avg <= -0.5:
            overall_sentiment = Sentiment.NEGATIVE
        elif avg >= 1.5:
            overall_sentiment = Sentiment.VERY_POSITIVE
        elif avg >= 0.5:
            overall_sentiment = Sentiment.POSITIVE
        else:
            overall_sentiment = Sentiment.NEUTRAL
    else:
        overall_sentiment = Sentiment.NEUTRAL

    # 4. Persist to DB
    if persist and events:
        try:
            ensure_table()
            save_material_events(ticker, exchange, events)
        except Exception as exc:
            logger.warning("Failed to persist material events for %s: %s", ticker, exc)

    return NewsAgentResult(
        ticker=ticker,
        exchange=exchange,
        news_items_fetched=len(news_items),
        material_events=events,
        has_critical_event=has_critical,
        highest_severity=highest,
        overall_sentiment=overall_sentiment,
    )


__all__ = [
    "fetch_news",
    "classify_events",
    "run_news_agent",
    "save_material_events",
    "get_latest_events",
    "ensure_table",
    "NewsItem",
    "MaterialEvent",
    "NewsAgentResult",
    "EventType",
    "Severity",
    "Sentiment",
]
