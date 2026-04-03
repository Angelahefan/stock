"""
agents/news_agent/event_classifier.py — LLM-based material event classifier.

Takes a list of NewsItem for a ticker and uses RouterChatClient to classify
each news item by event_type, severity, sentiment, and summary.

All items are batched into a single LLM call for efficiency.
"""
from __future__ import annotations

import json
import logging
import re
from typing import List

from agents.news_agent.contracts import (
    EventType,
    MaterialEvent,
    NewsItem,
    Sentiment,
    Severity,
)

logger = logging.getLogger(__name__)

_CLASSIFIER_SYSTEM_PROMPT = """You are a financial news classifier for an institutional stock intelligence platform.

Given a list of news items about a stock ticker, classify EACH item with:

1. event_type — one of: LEGAL, REGULATORY, EXECUTIVE, FRAUD, SANCTIONS, PRODUCT_RECALL, ACCOUNTING, BANKRUPTCY, ACQUISITION, EARNINGS_MISS, NONE
2. severity — one of:
   - CRITICAL: expect >15% stock price move (e.g. fraud discovery, bankruptcy filing, major acquisition, regulatory ban)
   - HIGH: expect 5-15% move (e.g. earnings miss, executive departure, lawsuit filing)
   - MEDIUM: expect 2-5% move (e.g. product recall, regulatory inquiry, downgrade)
   - LOW: minor impact
   - NONE: not material to stock price
3. sentiment — one of: VERY_NEGATIVE, NEGATIVE, NEUTRAL, POSITIVE, VERY_POSITIVE
4. summary — 1-2 sentence plain English summary of the material impact

IMPORTANT:
- Be conservative with CRITICAL severity — only use for truly market-moving events
- If a news item is routine (e.g. scheduled earnings call, routine filing), classify as NONE severity
- If you cannot determine the event type from the title/snippet, use NONE
- Focus on financial materiality, not general interest

Respond with ONLY a JSON array. Each element must have: event_type, severity, sentiment, summary.
The array length MUST match the number of input items exactly, in the same order.

Example response:
[
  {"event_type": "FRAUD", "severity": "CRITICAL", "sentiment": "VERY_NEGATIVE", "summary": "Company under SEC investigation for accounting fraud; potential restatement of 3 years of financials."},
  {"event_type": "NONE", "severity": "NONE", "sentiment": "NEUTRAL", "summary": "Routine quarterly earnings conference call scheduled."}
]"""


def classify_events(ticker: str, news_items: List[NewsItem]) -> List[MaterialEvent]:
    """
    Classify a batch of news items using a single LLM call.

    Args:
        ticker: Stock ticker symbol
        news_items: List of NewsItem to classify

    Returns:
        List of MaterialEvent with LLM-assigned classifications
    """
    if not news_items:
        return []

    # Build the user prompt with all news items
    items_text = []
    for i, item in enumerate(news_items, 1):
        pub_str = item.published_at.strftime("%Y-%m-%d %H:%M UTC") if item.published_at else "unknown"
        items_text.append(
            f"[{i}] Title: {item.title}\n"
            f"    Source: {item.source}\n"
            f"    Published: {pub_str}\n"
            f"    Snippet: {item.snippet[:200] if item.snippet else '(none)'}"
        )

    user_prompt = (
        f"Classify these {len(news_items)} news items for ticker {ticker}:\n\n"
        + "\n\n".join(items_text)
    )

    try:
        from agents.llm_client import GeminiChatClient, RouterChatClient

        # Prefer Gemini for news classification — better real-time knowledge
        try:
            client = GeminiChatClient()
            response = client.chat(
                messages=[
                    {"role": "system", "content": _CLASSIFIER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
            )
        except Exception:
            # Fallback to router if Gemini fails
            client = RouterChatClient()
            response = client.chat(
                messages=[
                    {"role": "system", "content": _CLASSIFIER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
            )

        raw = response.get("content", "") if isinstance(response, dict) else str(response)
        classifications = _parse_classifications(raw)

    except Exception as exc:
        logger.error("LLM classification failed for %s: %s", ticker, str(exc)[:200])
        classifications = []

    # Build MaterialEvent list, matching with original news items
    events: List[MaterialEvent] = []
    for i, item in enumerate(news_items):
        cls = classifications[i] if i < len(classifications) else {}

        event_type = _safe_enum(EventType, cls.get("event_type"), EventType.NONE)
        severity = _safe_enum(Severity, cls.get("severity"), Severity.NONE)
        sentiment = _safe_enum(Sentiment, cls.get("sentiment"), Sentiment.NEUTRAL)
        summary = cls.get("summary", "")

        events.append(MaterialEvent(
            title=item.title,
            source=item.source,
            url=item.url,
            published_at=item.published_at,
            event_type=event_type,
            severity=severity,
            sentiment=sentiment,
            summary=summary,
        ))

    # Filter out NONE events (keep only material ones)
    material = [e for e in events if e.severity != Severity.NONE or e.event_type != EventType.NONE]
    logger.info("Classified %d/%d news items as material for %s", len(material), len(events), ticker)

    return material if material else events  # Return all if nothing material found


def _parse_classifications(raw: str) -> list:
    """Parse JSON array from LLM response, handling markdown fences."""
    raw = raw.strip()

    # Strip markdown code fences
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
    if raw.endswith("```"):
        raw = raw[:-3].rstrip()

    # Try direct parse
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, TypeError):
        pass

    # Try extracting array from text
    match = re.search(r"\[[\s\S]*\]", raw)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    logger.warning("Failed to parse LLM classification response")
    return []


def _safe_enum(enum_cls, value, default):
    """Safely convert a string to an enum, returning default on failure."""
    if value is None:
        return default
    try:
        return enum_cls(str(value).upper())
    except (ValueError, KeyError):
        return default
