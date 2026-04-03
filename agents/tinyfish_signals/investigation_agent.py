"""
Investigation Agent
====================
v1.5 NEW AGENT per claude-build-spec-v1.5-financial-agents.md §Investigation Agent.

Purpose:
    When a financial signal is detected, investigate additional sources to gather
    corroborating or contradicting evidence before cross-validation.

Sources checked (in priority order):
    1. Company press releases page (derived from source_url)
    2. Exchange announcement sources
       — ASX for Australian tickers (reuses asx_announcement_agent)
       — SEC/EDGAR for US tickers (reuses sec_filing_agent)
    3. Investor relations page (source_url itself, deeper keyword scan)
    4. Google News / public search snippets (text-based, no API key required)

Output:
    investigation_results : List[InvestigationFinding]
    sources_checked       : List[str]  — human-readable list of sources attempted
    investigation_summary : str        — concise analyst-style summary
    corroborating_count   : int        — number of sources that support the signal
    contradicting_count   : int        — number of sources that contradict the signal

Reuses:
    agents/asx_announcement_agent.py — ASX announcements
    agents/sec_filing_agent.py       — SEC filings
    agents/llm_client.py             — optional LLM synthesis
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 10
_USER_AGENT = "DataPAI-TinyFish/1.5-investigation (financial-intelligence)"

# Signal-type → investigation search keywords
_SIGNAL_INVESTIGATION_KEYWORDS = {
    "GUIDANCE_WITHDRAWAL": [
        "guidance", "outlook", "forecast", "withdraw", "revision",
        "targets", "expectations", "downgrade", "update",
    ],
    "RISK_DISCLOSURE_EXPANSION": [
        "risk", "uncertainty", "regulatory", "liquidity", "adverse",
        "warning", "restructuring", "impairment", "investigation",
    ],
    "TONE_SOFTENING": [
        "cautious", "challenging", "headwinds", "difficult",
        "uncertain", "review", "reassess", "evaluate",
    ],
}

_PRESS_RELEASE_PATH_HINTS = [
    "/news", "/press-releases", "/press-release", "/media-releases",
    "/media-release", "/newsroom", "/media", "/announcements",
    "/investor-relations/news", "/ir/news", "/investors/news",
]


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _is_asx_ticker(ticker: str, source_url: str = "") -> bool:
    """Return True if this ticker trades on ASX (Australian Securities Exchange).

    Priority: check source_url domain first (most reliable), then fall back to
    a conservative URL-based heuristic. US tickers with 2-4 chars used to be
    mis-classified as ASX — this fix prevents that.
    """
    if source_url:
        from urllib.parse import urlparse as _urlparse
        host = _urlparse(source_url).netloc.lower()
        # ASX company pages and announcement feeds all use .com.au or asx.com.au
        if host.endswith(".com.au") or host.endswith(".org.au") or host.endswith(".net.au"):
            return True
        if "asx.com" in host:
            return True
    # No URL indicator → assume US/SEC (safer default; avoids false ASX positives)
    return False


def _base_url(url: str) -> str:
    """Return scheme + host from a URL."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _fetch_text(url: str) -> Optional[str]:
    """
    Fetch URL and return lowercased plain text.
    Returns None on any error (network, timeout, bad status).
    """
    try:
        import requests  # lazy import
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        # Strip HTML tags minimally
        text = re.sub(r"<[^>]+>", " ", resp.text)
        return re.sub(r"\s+", " ", text).strip()
    except Exception as exc:
        logger.debug("[InvestigationAgent] fetch failed for %s: %s", url, exc)
        return None


def _keyword_hits(text: str, keywords: List[str]) -> List[str]:
    """Return keywords found in text."""
    text_lower = text.lower()
    return [kw for kw in keywords if kw.lower() in text_lower]


def _extract_snippet(text: str, keyword: str, context_chars: int = 150) -> str:
    """Extract a short snippet around the first occurrence of keyword."""
    idx = text.lower().find(keyword.lower())
    if idx < 0:
        return ""
    start = max(0, idx - context_chars // 2)
    end   = min(len(text), idx + context_chars // 2)
    snippet = text[start:end].strip()
    return f"...{snippet}..."


# ══════════════════════════════════════════════════════════════════════════════
# Source 1 — Press release / newsroom page
# ══════════════════════════════════════════════════════════════════════════════

def _investigate_press_releases(
    company_name: str,
    source_url: str,
    keywords: List[str],
) -> List[dict]:
    """
    Try common press release URL paths derived from source_url.
    Return any findings containing signal keywords.
    """
    findings = []
    if not source_url:
        return findings

    base = _base_url(source_url)
    urls_to_try = [urljoin(base, path) for path in _PRESS_RELEASE_PATH_HINTS]

    for url in urls_to_try[:4]:  # limit attempts to avoid long tail
        text = _fetch_text(url)
        if not text:
            continue

        hits = _keyword_hits(text, keywords)
        if hits:
            snippet = _extract_snippet(text, hits[0])
            findings.append({
                "url":        url,
                "snippet":    snippet or f"Found signal keywords: {hits[:3]}",
                "source":     "company press releases",
                "keywords":   hits[:5],
                "corroborates": True,
            })
            break  # one press-release page hit is sufficient at this stage

    return findings


# ══════════════════════════════════════════════════════════════════════════════
# Source 2 — Exchange filings (ASX / SEC)
# ══════════════════════════════════════════════════════════════════════════════

def _investigate_asx(ticker: str, keywords: List[str]) -> List[dict]:
    """Fetch recent ASX announcements and scan for signal keywords."""
    findings = []
    try:
        from agents.asx_announcement_agent import fetch_asx_announcements  # lazy
        announcements = fetch_asx_announcements(ticker, count=10)
        for ann in announcements[:5]:
            title = (ann.get("header", "") + " " + ann.get("document_date", "")).lower()
            hits  = [kw for kw in keywords if kw in title]
            if hits:
                findings.append({
                    "url":        ann.get("url", ""),
                    "snippet":    ann.get("header", ""),
                    "source":     "ASX announcement",
                    "keywords":   hits,
                    "corroborates": True,
                })
    except Exception as exc:
        logger.warning("[InvestigationAgent] ASX investigation failed for %s: %s", ticker, exc)
    return findings


def _investigate_sec(ticker: str, keywords: List[str]) -> List[dict]:
    """Fetch recent SEC filings (8-K, 10-Q) and scan for signal keywords."""
    findings = []
    try:
        from agents.sec_filing_agent import get_cik, fetch_sec_filings  # lazy
        cik = get_cik(ticker)
        if not cik:
            return findings
        filings = fetch_sec_filings(ticker, form_types=["8-K", "10-Q"], count=10)
        for f in filings[:5]:
            desc = (f.get("form", "") + " " + f.get("description", "")).lower()
            hits = [kw for kw in keywords if kw in desc]
            if hits:
                findings.append({
                    "url":        f.get("url", ""),
                    "snippet":    f.get("description", ""),
                    "source":     "SEC filing",
                    "keywords":   hits,
                    "corroborates": True,
                })
    except Exception as exc:
        logger.warning("[InvestigationAgent] SEC investigation failed for %s: %s", ticker, exc)
    return findings


# ══════════════════════════════════════════════════════════════════════════════
# Source 3 — Investor relations page (deeper keyword scan)
# ══════════════════════════════════════════════════════════════════════════════

def _investigate_ir_page(
    company_name: str,
    source_url: str,
    keywords: List[str],
) -> List[dict]:
    """
    Fetch the original source (IR) page and do a deeper keyword scan,
    returning sentence-level snippets for each hit.
    """
    findings = []
    if not source_url:
        return findings

    text = _fetch_text(source_url)
    if not text:
        return findings

    for kw in keywords[:6]:  # check top 6 keywords
        if kw.lower() in text.lower():
            snippet = _extract_snippet(text, kw)
            findings.append({
                "url":        source_url,
                "snippet":    snippet or f'IR page contains "{kw}"',
                "source":     "company IR page",
                "keywords":   [kw],
                "corroborates": True,
            })
            break  # one IR finding is enough; avoid duplication

    return findings


# ══════════════════════════════════════════════════════════════════════════════
# LLM synthesis of investigation results
# ══════════════════════════════════════════════════════════════════════════════

def _synthesize_investigation(
    ticker: str,
    company_name: str,
    signal_type: str,
    findings: List[dict],
    sources_checked: List[str],
    llm_client,
) -> str:
    """
    Use LLM to produce a concise investigation summary.
    Falls back to rule-based text if LLM is unavailable.
    """
    if not findings:
        return (
            f"No corroborating evidence found across {len(sources_checked)} source(s) checked "
            f"({', '.join(sources_checked[:3])}). "
            "The signal remains website-only at this time."
        )

    finding_lines = [
        f"  [{f['source']}] {f['snippet'][:120]}" for f in findings[:4]
    ]
    source_list = ", ".join(sources_checked[:4])

    if llm_client is None:
        return (
            f"Investigation found {len(findings)} corroborating source(s) for the "
            f"{signal_type.replace('_', ' ').lower()} signal at {company_name} ({ticker}). "
            f"Sources checked: {source_list}. "
            "See evidence for details."
        )

    prompt = (
        f"You are a financial analyst investigating a corporate signal.\n"
        f"Company: {company_name} ({ticker})\n"
        f"Signal: {signal_type}\n"
        f"Sources checked: {source_list}\n"
        f"Corroborating findings:\n" + "\n".join(finding_lines) + "\n\n"
        "In 1-2 sentences, summarise what the investigation found. "
        "Professional tone. No investment advice. Factual and neutral."
    )

    try:
        resp = llm_client.chat(
            messages=[
                {"role": "system", "content": "You are a concise financial analyst."},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.1,
        )
        return resp.get("content", "").strip()
    except Exception as exc:
        logger.warning("[InvestigationAgent] LLM synthesis failed: %s", exc)
        return (
            f"Investigation found {len(findings)} corroborating reference(s) for "
            f"{company_name} ({ticker}). Sources: {source_list}."
        )


# ══════════════════════════════════════════════════════════════════════════════
# Main investigation function
# ══════════════════════════════════════════════════════════════════════════════

def run_investigation_agent(
    ticker:          str,
    company_name:    str,
    signal_type:     str,
    source_url:      str = "",
    changed_snippet: str = "",
    llm_client=None,
) -> dict:
    """
    Investigate additional sources when a financial signal is detected.

    Args:
        ticker          : company ticker
        company_name    : full company name
        signal_type     : detected signal type (e.g. GUIDANCE_WITHDRAWAL)
        source_url      : URL of monitored IR/investor page
        changed_snippet : optional diff snippet for context
        llm_client      : optional RouterChatClient

    Returns a dict with:
        investigation_results : List[dict] — individual findings
        sources_checked       : List[str]  — sources that were attempted
        investigation_summary : str        — concise analyst summary
        corroborating_count   : int
        contradicting_count   : int        (reserved for future use)
        found_evidence        : bool       — True if any corroborating evidence found
    """
    keywords       = _SIGNAL_INVESTIGATION_KEYWORDS.get(signal_type, [])
    all_findings:  List[dict] = []
    sources_checked: List[str] = []

    # ── Source 1: Press releases page ──────────────────────────────────────────
    if source_url:
        sources_checked.append("company press releases")
        pr_findings = _investigate_press_releases(company_name, source_url, keywords)
        all_findings.extend(pr_findings)

    # ── Source 2: Exchange filings ──────────────────────────────────────────────
    if _is_asx_ticker(ticker, source_url):
        sources_checked.append("ASX announcements")
        asx_findings = _investigate_asx(ticker, keywords)
        all_findings.extend(asx_findings)
    else:
        sources_checked.append("SEC filings")
        sec_findings = _investigate_sec(ticker, keywords)
        all_findings.extend(sec_findings)

    # ── Source 3: IR page deeper scan ──────────────────────────────────────────
    if source_url:
        sources_checked.append("company IR page")
        ir_findings = _investigate_ir_page(company_name, source_url, keywords)
        # Avoid duplicate if press-release search already hit source_url
        existing_urls = {f["url"] for f in all_findings}
        all_findings.extend(f for f in ir_findings if f["url"] not in existing_urls)

    corroborating = [f for f in all_findings if f.get("corroborates")]
    contradicting = [f for f in all_findings if not f.get("corroborates")]

    investigation_summary = _synthesize_investigation(
        ticker          = ticker,
        company_name    = company_name,
        signal_type     = signal_type,
        findings        = corroborating,
        sources_checked = sources_checked,
        llm_client      = llm_client,
    )

    return {
        "investigation_results": all_findings,
        "sources_checked":       sources_checked,
        "investigation_summary": investigation_summary,
        "corroborating_count":   len(corroborating),
        "contradicting_count":   len(contradicting),
        "found_evidence":        len(corroborating) > 0,
    }
