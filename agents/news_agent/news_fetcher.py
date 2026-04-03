"""
agents/news_agent/news_fetcher.py — Fetch breaking news from free sources.

Sources:
  1. Google News RSS (free, no API key)
  2. Finnhub company news (optional, needs FINNHUB_API_KEY env var)
  3. SEC EDGAR 8-K search (free, no API key)
  4. ASX announcements (free, no API key — for .AX tickers)

All results filtered to last 48 hours.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

from agents.news_agent.contracts import NewsItem

logger = logging.getLogger(__name__)

_FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
_REQUEST_TIMEOUT = 15  # seconds


def _parse_rss_date(date_str: str) -> Optional[datetime]:
    """Try common RSS date formats."""
    import email.utils
    try:
        parsed = email.utils.parsedate_to_datetime(date_str)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        pass
    # ISO 8601 fallback
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _cutoff() -> datetime:
    """48 hours ago, UTC."""
    return datetime.now(timezone.utc) - timedelta(hours=48)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Google News RSS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_google_news(ticker: str) -> List[NewsItem]:
    """Fetch recent news from Google News RSS for a ticker."""
    try:
        import feedparser
    except ImportError:
        logger.warning("feedparser not installed — skipping Google News RSS")
        return []

    url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
    items: List[NewsItem] = []
    cutoff = _cutoff()

    try:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            pub_date = None
            if hasattr(entry, "published"):
                pub_date = _parse_rss_date(entry.published)
            elif hasattr(entry, "updated"):
                pub_date = _parse_rss_date(entry.updated)

            # Filter to last 48 hours (skip if no date — include it cautiously)
            if pub_date and pub_date < cutoff:
                continue

            title = getattr(entry, "title", "")
            link = getattr(entry, "link", "")
            snippet = getattr(entry, "summary", "")
            # Google News summaries can be HTML — strip tags simply
            if "<" in snippet:
                import re
                snippet = re.sub(r"<[^>]+>", " ", snippet).strip()
                snippet = snippet[:300]

            items.append(NewsItem(
                title=title,
                source="Google News",
                url=link,
                published_at=pub_date,
                snippet=snippet[:300],
            ))
    except Exception as exc:
        logger.warning("Google News RSS fetch failed for %s: %s", ticker, exc)

    logger.info("Google News: fetched %d items for %s", len(items), ticker)
    return items


# ─────────────────────────────────────────────────────────────────────────────
# 2. Finnhub company news (optional)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_finnhub_news(ticker: str) -> List[NewsItem]:
    """Fetch company news from Finnhub free tier. Requires FINNHUB_API_KEY."""
    if not _FINNHUB_API_KEY:
        logger.debug("FINNHUB_API_KEY not set — skipping Finnhub news")
        return []

    now = datetime.now(timezone.utc)
    from_date = (now - timedelta(hours=48)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")

    url = (
        f"https://finnhub.io/api/v1/company-news"
        f"?symbol={ticker}&from={from_date}&to={to_date}"
        f"&token={_FINNHUB_API_KEY}"
    )

    items: List[NewsItem] = []
    cutoff = _cutoff()

    try:
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if not isinstance(data, list):
            logger.warning("Finnhub returned unexpected format for %s", ticker)
            return []

        for article in data:
            pub_ts = article.get("datetime")
            pub_date = None
            if pub_ts:
                try:
                    pub_date = datetime.fromtimestamp(pub_ts, tz=timezone.utc)
                except (ValueError, OSError):
                    pass

            if pub_date and pub_date < cutoff:
                continue

            items.append(NewsItem(
                title=article.get("headline", ""),
                source="Finnhub",
                url=article.get("url", ""),
                published_at=pub_date,
                snippet=(article.get("summary", "") or "")[:300],
            ))
    except Exception as exc:
        logger.warning("Finnhub news fetch failed for %s: %s", ticker, exc)

    logger.info("Finnhub: fetched %d items for %s", len(items), ticker)
    return items


# ─────────────────────────────────────────────────────────────────────────────
# 3. SEC EDGAR 8-K filings
# ─────────────────────────────────────────────────────────────────────────────

def fetch_sec_8k(ticker: str) -> List[NewsItem]:
    """Fetch recent 8-K filings from SEC EDGAR full-text search."""
    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(hours=48)).strftime("%Y-%m-%d")
    end_date = now.strftime("%Y-%m-%d")

    url = (
        f"https://efts.sec.gov/LATEST/search-index"
        f"?q={ticker}&dateRange=custom&startdt={start_date}&enddt={end_date}&forms=8-K"
    )

    items: List[NewsItem] = []

    try:
        headers = {
            "User-Agent": "DataPAI/1.0 (datap.ai; research@datap.ai)",
            "Accept": "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        hits = data.get("hits", {}).get("hits", [])
        for hit in hits:
            src = hit.get("_source", {})
            title = src.get("display_name_main", "") or src.get("file_description", "8-K Filing")
            filed_date_str = src.get("file_date", "")
            pub_date = _parse_rss_date(filed_date_str) if filed_date_str else None

            accession = src.get("accession_no", "").replace("-", "")
            filing_url = ""
            if accession:
                filing_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=8-K"

            items.append(NewsItem(
                title=f"SEC 8-K: {title}",
                source="SEC EDGAR",
                url=filing_url,
                published_at=pub_date,
                snippet=src.get("file_description", "")[:300],
            ))
    except Exception as exc:
        logger.warning("SEC EDGAR 8-K fetch failed for %s: %s", ticker, exc)

    logger.info("SEC EDGAR: fetched %d 8-K items for %s", len(items), ticker)
    return items


# ─────────────────────────────────────────────────────────────────────────────
# 4. ASX Announcements (for Australian stocks)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_asx_announcements(ticker: str) -> List[NewsItem]:
    """
    Fetch recent ASX announcements for an Australian stock.
    Uses the ASX company announcements JSON API (free, no API key).
    Ticker can be 'BHP' or 'BHP.AX' — we strip the .AX suffix.
    """
    # Strip .AX suffix if present
    asx_code = ticker.replace(".AX", "").upper()

    # ASX announcements API — returns JSON
    url = (
        f"https://www.asx.com.au/asx/1/company/{asx_code}/announcements"
        f"?count=20&market_sensitive=true"
    )

    items: List[NewsItem] = []
    cutoff = _cutoff()

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; DataPAI/1.0)",
            "Accept": "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        for ann in data.get("data", []):
            title = ann.get("header", "")
            doc_date = ann.get("document_date", "")
            pub_date = _parse_rss_date(doc_date) if doc_date else None

            if pub_date and pub_date < cutoff:
                continue

            # Build link to the announcement PDF
            doc_id = ann.get("document_release_id", "")
            ann_url = f"https://www.asx.com.au/asx/statistics/announcements.do?by=asxCode&asxCode={asx_code}"
            if doc_id:
                ann_url = f"https://www.asx.com.au/asxpdf/{doc_id}"

            is_sensitive = ann.get("market_sensitive", False)
            size = ann.get("size", "")
            num_pages = ann.get("number_of_pages", "")

            snippet_parts = []
            if is_sensitive:
                snippet_parts.append("MARKET SENSITIVE")
            if ann.get("issuer_full_name"):
                snippet_parts.append(ann["issuer_full_name"])
            if size:
                snippet_parts.append(f"Size: {size}")
            if num_pages:
                snippet_parts.append(f"Pages: {num_pages}")

            items.append(NewsItem(
                title=f"ASX: {title}" if not title.startswith("ASX") else title,
                source="ASX Announcements",
                url=ann_url,
                published_at=pub_date,
                snippet=" | ".join(snippet_parts)[:300],
            ))
    except Exception as exc:
        logger.warning("ASX announcements fetch failed for %s: %s", asx_code, exc)

    logger.info("ASX Announcements: fetched %d items for %s", len(items), asx_code)
    return items


# Also fetch ASX-specific Google News (with ASX context)
def fetch_google_news_asx(ticker: str) -> List[NewsItem]:
    """Fetch Google News with ASX-specific search terms."""
    asx_code = ticker.replace(".AX", "").upper()
    try:
        import feedparser
    except ImportError:
        return []

    url = f"https://news.google.com/rss/search?q={asx_code}+ASX+stock&hl=en-AU&gl=AU&ceid=AU:en"
    items: List[NewsItem] = []
    cutoff = _cutoff()

    try:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            pub_date = None
            if hasattr(entry, "published"):
                pub_date = _parse_rss_date(entry.published)
            if pub_date and pub_date < cutoff:
                continue

            title = getattr(entry, "title", "")
            link = getattr(entry, "link", "")
            snippet = getattr(entry, "summary", "")
            if "<" in snippet:
                import re
                snippet = re.sub(r"<[^>]+>", " ", snippet).strip()

            items.append(NewsItem(
                title=title,
                source="Google News AU",
                url=link,
                published_at=pub_date,
                snippet=snippet[:300],
            ))
    except Exception as exc:
        logger.warning("Google News AU fetch failed for %s: %s", asx_code, exc)

    return items


# ─────────────────────────────────────────────────────────────────────────────
# Main fetch function — aggregates all sources
# ─────────────────────────────────────────────────────────────────────────────

def fetch_news(ticker: str, exchange: str = "US") -> List[NewsItem]:
    """
    Fetch breaking news from all available sources for a ticker.
    Returns de-duplicated list of NewsItem sorted by published_at desc.
    Works without any API keys (Google News RSS + SEC/ASX are free).

    Args:
        ticker: Stock ticker (e.g. "SMCI", "BHP", "BHP.AX")
        exchange: "US", "ASX", "NASDAQ", "NYSE" etc.
    """
    is_asx = exchange == "ASX" or ticker.endswith(".AX")
    all_items: List[NewsItem] = []

    # Common sources
    all_items.extend(fetch_google_news(ticker))
    all_items.extend(fetch_finnhub_news(ticker))

    if is_asx:
        # ASX-specific sources
        all_items.extend(fetch_asx_announcements(ticker))
        all_items.extend(fetch_google_news_asx(ticker))
    else:
        # US-specific sources
        all_items.extend(fetch_sec_8k(ticker))

    # De-duplicate by title similarity (exact match)
    seen_titles = set()
    unique: List[NewsItem] = []
    for item in all_items:
        key = item.title.strip().lower()
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(item)

    # Sort by published_at desc (None last)
    unique.sort(
        key=lambda x: x.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    logger.info("Total unique news items for %s: %d", ticker, len(unique))
    return unique
