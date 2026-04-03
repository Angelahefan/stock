"""
Cross-Validation Agent
=======================
Critical capability: validates a detected signal across other public sources.

Validation targets (per spec):
  1. company press release page
  2. exchange filing source (ASX for AU, SEC/EDGAR for US)
  3. investor relations page
  4. optional news transcript (via existing framework agents)

Reuses:
  - agents/asx_announcement_agent.py  — ASX filings fetch
  - agents/sec_filing_agent.py        — SEC EDGAR filings fetch
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)
# requests is imported lazily inside _validate_via_ir_page to avoid
# import errors in test environments that don't have it installed.

_REQUEST_TIMEOUT = 12
_USER_AGENT = "DataPAI-TinyFish/1.0 (financial-signal-validator)"


# ══════════════════════════════════════════════════════════════════════════════
# Exchange detection helper
# ══════════════════════════════════════════════════════════════════════════════

def _is_asx_ticker(ticker: str) -> bool:
    """Heuristic: ASX tickers are 2–3 uppercase alpha chars (e.g. BHP, CBA, WTC)."""
    return bool(re.fullmatch(r"[A-Z]{2,4}", ticker))


# ══════════════════════════════════════════════════════════════════════════════
# Source 1 — ASX filings
# ══════════════════════════════════════════════════════════════════════════════

def _validate_via_asx(ticker: str, signal_keywords: List[str]) -> List[dict]:
    """
    Fetch recent ASX announcements and check for signal keyword presence.
    Reuses the ASX API from asx_announcement_agent.py.
    """
    from agents.asx_announcement_agent import fetch_asx_announcements  # lazy import

    evidence = []
    try:
        announcements = fetch_asx_announcements(ticker, count=5)
        for ann in announcements[:3]:
            title = (ann.get("document_date", "") + " " + ann.get("header", "")).lower()
            if any(kw.lower() in title for kw in signal_keywords):
                evidence.append({
                    "url":     ann.get("url", ""),
                    "snippet": ann.get("header", ""),
                    "source":  "ASX filing",
                })
    except Exception as exc:
        logger.warning("[CrossValidationAgent] ASX fetch failed for %s: %s", ticker, exc)

    return evidence


# ══════════════════════════════════════════════════════════════════════════════
# Source 2 — SEC EDGAR filings (US companies)
# ══════════════════════════════════════════════════════════════════════════════

def _validate_via_sec(ticker: str, signal_keywords: List[str]) -> List[dict]:
    """
    Fetch recent SEC filings (8-K is most market-sensitive) and check keywords.
    Reuses sec_filing_agent.py.
    """
    from agents.sec_filing_agent import get_cik, fetch_sec_filings  # lazy import

    evidence = []
    try:
        cik = get_cik(ticker)
        if not cik:
            return evidence
        filings = fetch_sec_filings(ticker, form_types=["8-K"], count=5)
        for f in filings[:3]:
            desc = (f.get("form", "") + " " + f.get("description", "")).lower()
            if any(kw.lower() in desc for kw in signal_keywords):
                evidence.append({
                    "url":     f.get("url", ""),
                    "snippet": f.get("description", ""),
                    "source":  "SEC 8-K filing",
                })
    except Exception as exc:
        logger.warning("[CrossValidationAgent] SEC fetch failed for %s: %s", ticker, exc)

    return evidence


# ══════════════════════════════════════════════════════════════════════════════
# Source 3 — Company investor relations page (simple keyword check)
# ══════════════════════════════════════════════════════════════════════════════

def _validate_via_ir_page(
    company_name: str,
    source_url: str,
    signal_keywords: List[str],
) -> List[dict]:
    """
    Fetch the company's IR page (source_url) and check for signal keyword presence.
    This is a simple text fetch — does not scrape JS-heavy pages.
    """
    evidence = []
    if not source_url:
        return evidence

    try:
        import requests  # lazy import — only needed at runtime
        resp = requests.get(
            source_url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return evidence

        text_lower = resp.text.lower()
        hits = [kw for kw in signal_keywords if kw.lower() in text_lower]
        if hits:
            evidence.append({
                "url":     source_url,
                "snippet": f"IR page contains signal-related language: {hits}",
                "source":  "company IR page",
            })
    except Exception as exc:
        logger.warning("[CrossValidationAgent] IR page fetch failed for %s: %s", company_name, exc)

    return evidence


# ══════════════════════════════════════════════════════════════════════════════
# Signal → keyword mapping
# ══════════════════════════════════════════════════════════════════════════════

_SIGNAL_KEYWORDS = {
    "GUIDANCE_WITHDRAWAL": [
        "guidance", "forecast", "outlook", "withdraw", "withdrawn",
        "lower", "revised", "update", "downgrade",
    ],
    "RISK_DISCLOSURE_EXPANSION": [
        "risk", "uncertainty", "regulatory", "liquidity", "adverse",
        "volatility", "disruption", "headwind",
    ],
    "TONE_SOFTENING": [
        "cautious", "prudent", "uncertain", "challenging", "headwinds",
        "evaluate", "explore",
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# Main cross-validation function
# ══════════════════════════════════════════════════════════════════════════════

def run_cross_validation_agent(
    ticker: str,
    company_name: str,
    signal_type: str,
    changed_snippet: str = "",
    source_url: str = "",
) -> dict:
    """
    Validate a detected signal across public filing and IR sources.

    Returns a dict compatible with CrossValidateData.
    """
    keywords = _SIGNAL_KEYWORDS.get(signal_type, [])
    all_evidence: List[dict] = []

    # Source 1: exchange filing
    if _is_asx_ticker(ticker):
        all_evidence.extend(_validate_via_asx(ticker, keywords))
    else:
        all_evidence.extend(_validate_via_sec(ticker, keywords))

    # Source 2: company IR page
    if source_url:
        all_evidence.extend(_validate_via_ir_page(company_name, source_url, keywords))

    # Determine validation status
    status, summary, confidence_adjustment = _derive_status(all_evidence, signal_type)

    return {
        "validation_status":     status,
        "validation_summary":    summary,
        "validation_evidence":   all_evidence,
        "confidence_adjustment": confidence_adjustment,
    }


def _derive_status(
    evidence: List[dict],
    signal_type: str,
) -> Tuple[str, str, float]:
    """
    Derive validation_status, summary, and confidence_adjustment from evidence found.
    """
    filing_sources = [e for e in evidence if "filing" in e.get("source", "").lower()]
    ir_sources     = [e for e in evidence if "ir" in e.get("source", "").lower()]

    if filing_sources and ir_sources:
        return (
            "CONFIRMED",
            (
                f"Signal language found in both exchange filings and the company IR page. "
                f"Found {len(filing_sources)} filing reference(s) and {len(ir_sources)} IR page reference(s)."
            ),
            0.25,
        )

    if filing_sources:
        return (
            "CONFIRMED",
            (
                f"Signal language corroborated in {len(filing_sources)} recent exchange filing(s). "
                "The website change appears consistent with official filings."
            ),
            0.20,
        )

    if ir_sources:
        return (
            "PARTIALLY_CONFIRMED",
            (
                "Signal language found on the company IR page but not yet confirmed in "
                "official exchange filings. May indicate early disclosure."
            ),
            0.10,
        )

    if not evidence:
        # No sources had any matching evidence
        return (
            "NOT_CONFIRMED_YET",
            (
                f"Signal detected on the monitored website but not yet visible in "
                "official exchange filings or press releases. "
                "This could indicate early website-only disclosure — worth monitoring."
            ),
            0.0,
        )

    # Fallback
    return (
        "SOURCE_UNAVAILABLE",
        "Unable to retrieve filing or IR sources for cross-validation.",
        -0.05,
    )
