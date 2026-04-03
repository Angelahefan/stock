"""
agents/news_agent/contracts.py — Pydantic models for the Material Event / Breaking News Agent.

No business logic here — pure data contracts.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════════════════════════
# Enumerations
# ══════════════════════════════════════════════════════════════════════════════

class EventType(str, Enum):
    LEGAL = "LEGAL"
    REGULATORY = "REGULATORY"
    EXECUTIVE = "EXECUTIVE"
    FRAUD = "FRAUD"
    SANCTIONS = "SANCTIONS"
    PRODUCT_RECALL = "PRODUCT_RECALL"
    ACCOUNTING = "ACCOUNTING"
    BANKRUPTCY = "BANKRUPTCY"
    ACQUISITION = "ACQUISITION"
    EARNINGS_MISS = "EARNINGS_MISS"
    NONE = "NONE"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"   # expect >15% move
    HIGH = "HIGH"           # expect 5-15% move
    MEDIUM = "MEDIUM"       # expect 2-5% move
    LOW = "LOW"             # minor
    NONE = "NONE"


class Sentiment(str, Enum):
    VERY_NEGATIVE = "VERY_NEGATIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    POSITIVE = "POSITIVE"
    VERY_POSITIVE = "VERY_POSITIVE"


# ══════════════════════════════════════════════════════════════════════════════
# Data models
# ══════════════════════════════════════════════════════════════════════════════

class NewsItem(BaseModel):
    """A single news article / filing fetched from an external source."""
    title: str
    source: str = Field(description="e.g. 'Google News', 'Finnhub', 'SEC EDGAR'")
    url: str = ""
    published_at: Optional[datetime] = None
    snippet: str = ""


class MaterialEvent(BaseModel):
    """LLM-classified material event derived from a NewsItem."""
    title: str
    source: str
    url: str = ""
    published_at: Optional[datetime] = None
    event_type: EventType = EventType.NONE
    severity: Severity = Severity.NONE
    sentiment: Sentiment = Sentiment.NEUTRAL
    summary: str = Field("", description="1-2 sentence plain English summary")


class NewsAgentResult(BaseModel):
    """Full result from the news agent for a single ticker."""
    ticker: str
    exchange: str
    news_items_fetched: int = 0
    material_events: List[MaterialEvent] = Field(default_factory=list)
    has_critical_event: bool = False
    highest_severity: Severity = Severity.NONE
    overall_sentiment: Sentiment = Sentiment.NEUTRAL
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
