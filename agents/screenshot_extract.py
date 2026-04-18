"""
agents/screenshot_extract.py
─────────────────────────────────────────────────────────────────────────────
Extract stock holdings from a broker app screenshot using Gemini Vision.
Returns structured JSON with ticker, exchange, shares, avg_cost, name.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are analyzing a screenshot from a stock trading or brokerage application.
Extract ALL stock holdings, positions, or watchlist items visible in the screenshot.

For each stock, extract:
- ticker: The stock ticker symbol (e.g., "CBA", "AAPL", "0700", "600519")
- exchange: Infer the exchange from context:
  * Australian stocks (A$, ASX, .AX suffix) → "ASX"
  * US stocks ($, NYSE, NASDAQ) → "US"
  * Hong Kong stocks (HK$, .HK suffix, 4-digit codes) → "HKEX"
  * China A-shares (.SS, .SZ, 6-digit codes) → "SSE" or "SZSE" (6xxxxx=SSE, 0xxxxx/3xxxxx=SZSE)
  * Vietnam stocks (VND, .VN) → "HOSE"
  * Thailand stocks (THB, .BK) → "SET"
  * Malaysia stocks (RM, .KL) → "KLSE"
  * Indonesia stocks (IDR, .JK) → "IDX"
  * UK stocks (GBP, .L, pence) → "LSE"
  * If unclear, use "US" as default
- shares: Number of shares/units held (null if not visible)
- avg_cost: Average purchase price per share (null if not visible)
- name: Company name (null if not visible)
- current_price: Current market price (null if not visible)

Common broker apps to recognize:
- CommSec, Stake, SelfWealth (Australian)
- Tiger Brokers, moomoo, Futu (Multi-market, popular in Asia)
- Interactive Brokers, TD Ameritrade, Fidelity (US/Global)
- Webull, Robinhood (US-focused)
- Snowball (雪球), East Money (东方财富) (China)

IMPORTANT: Return ONLY a valid JSON array. No markdown, no code fences, no explanation.
If no stocks are found, return: []
If a field is not visible in the screenshot, use null for that field.

Example output:
[{"ticker": "CBA", "exchange": "ASX", "shares": 100, "avg_cost": 115.50, "name": "Commonwealth Bank", "current_price": 118.20}]
"""


def extract_holdings_from_screenshot(
    image_bytes: bytes,
    mime_type: str = "image/png",
) -> list[dict[str, Any]]:
    """
    Send a broker screenshot to Gemini Vision and extract holdings.

    Returns a list of dicts with keys: ticker, exchange, shares, avg_cost, name, current_price.
    """
    from agents.llm_client import GoogleChatClient

    client = GoogleChatClient()
    result = client.chat_vision(
        prompt=EXTRACTION_PROMPT,
        image_bytes=image_bytes,
        mime_type=mime_type,
        temperature=0.1,
    )

    content = result.get("content", "")
    logger.info("[screenshot_extract] Vision response length: %d chars", len(content))

    # Parse JSON from response
    try:
        # Strip markdown fences if present
        text = content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        holdings = json.loads(text)
        if not isinstance(holdings, list):
            holdings = [holdings]

        # Normalize fields
        cleaned = []
        for h in holdings:
            if not isinstance(h, dict):
                continue
            ticker = h.get("ticker")
            if not ticker:
                continue
            cleaned.append({
                "ticker": str(ticker).upper().strip(),
                "exchange": str(h.get("exchange") or "US").upper().strip(),
                "shares": h.get("shares"),
                "avg_cost": h.get("avg_cost"),
                "name": h.get("name"),
                "current_price": h.get("current_price"),
            })

        logger.info("[screenshot_extract] Extracted %d holdings", len(cleaned))
        return cleaned

    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("[screenshot_extract] Failed to parse JSON: %s\nRaw: %s", e, content[:500])
        return []
