"""
agents/stock_synthesis/watchlist_overview.py
─────────────────────────────────────────────────────────────────────────────
AG2 multi-agent watchlist overview: analyzes a user's watchlist to provide
sector grouping, diversity assessment, risk clustering, and opportunity ranking.

This is WATCHLIST-focused (stocks you're watching), not portfolio-focused
(stocks you own). Portfolio analysis is a separate feature.

Agents:
    - Sector Analyst: groups stocks by sector/industry, identifies concentration
    - Risk Analyst: finds correlated risks across watchlist
    - Opportunity Analyst: ranks stocks by entry attractiveness
    - Watchlist Strategist: synthesizes into actionable overview
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from agents.stock_synthesis.contracts import SignalDirection

logger = logging.getLogger(__name__)


# ── Data models ────────────────────────────────────────────────────────────

class WatchlistStock(BaseModel):
    """Enriched watchlist item with latest signals."""
    ticker: str
    exchange: str
    company_name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    # Latest synthesis
    direction: Optional[SignalDirection] = None
    confidence: Optional[float] = None
    thesis: Optional[str] = None
    # TA snapshot
    rsi: Optional[float] = None
    overall_signal: Optional[str] = None
    change_pct: Optional[float] = None
    # FA snapshot
    fundamental_score: Optional[float] = None
    fundamental_signal: Optional[str] = None
    pe_ratio: Optional[float] = None


class SectorGroup(BaseModel):
    """Stocks grouped by sector."""
    sector: str
    count: int
    tickers: List[str]
    avg_confidence: float = 0.0
    dominant_direction: str = "HOLD"


class RiskCluster(BaseModel):
    """Group of stocks sharing a common risk factor."""
    risk_factor: str
    severity: str  # HIGH / MEDIUM / LOW
    affected_tickers: List[str]
    description: str


class WatchlistOverview(BaseModel):
    """Complete AI-generated watchlist overview."""
    # Summary
    total_stocks: int = 0
    buy_count: int = 0
    hold_count: int = 0
    sell_count: int = 0
    diversity_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="0=concentrated in 1 sector, 1=perfectly diversified"
    )
    diversity_assessment: str = ""  # e.g. "Over-concentrated in mining"

    # Sector breakdown
    sector_groups: List[SectorGroup] = Field(default_factory=list)

    # Risk analysis
    risk_clusters: List[RiskCluster] = Field(default_factory=list)
    top_risk: str = ""  # Single most important risk across watchlist

    # Opportunities
    top_opportunities: List[str] = Field(
        default_factory=list,
        description="Top 3 tickers ranked by entry attractiveness"
    )
    opportunity_summary: str = ""

    # AI narrative
    ai_summary: str = Field(
        default="",
        description="2-4 sentence overview of watchlist health and recommendations"
    )
    ai_action_items: List[str] = Field(
        default_factory=list,
        description="3-5 specific actionable recommendations"
    )

    # Metadata
    computed_at: datetime = Field(default_factory=datetime.utcnow)
    model_used: str = "gpt-4o-mini"
    stocks_analyzed: int = 0


# ── Data gathering ─────────────────────────────────────────────────────────

def _query_sync(sql: str, params: tuple) -> list[dict]:
    from scripts.lib.db_helpers import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    return []


def gather_watchlist_data(user_id: Optional[str] = None) -> List[WatchlistStock]:
    """
    Load watchlist tickers and enrich with latest TA, FA, and synthesis data.
    If user_id is None, loads all watchlist entries (for demo/single-user mode).
    """
    # Get watchlist tickers
    if user_id:
        wl_rows = _query_sync(
            "SELECT symbol AS ticker, exchange FROM datapai.watchlist WHERE user_id = %s",
            (user_id,),
        )
    else:
        wl_rows = _query_sync(
            "SELECT DISTINCT symbol AS ticker, exchange FROM datapai.watchlist", ()
        )

    if not wl_rows:
        return []

    stocks: List[WatchlistStock] = []
    for wl in wl_rows:
        ticker = wl["ticker"]
        exchange = wl.get("exchange", "US")
        stock = WatchlistStock(ticker=ticker, exchange=exchange)

        # Enrich with FA data
        try:
            fa = _query_sync(
                """SELECT company_name, sector, industry, fundamental_score,
                          fundamental_signal, pe_ratio
                   FROM datapai.fundamental_snapshot
                   WHERE ticker = %s AND exchange = %s""",
                (ticker, exchange),
            )
            if fa:
                stock.company_name = fa[0].get("company_name")
                stock.sector = fa[0].get("sector")
                stock.industry = fa[0].get("industry")
                stock.fundamental_score = fa[0].get("fundamental_score")
                stock.fundamental_signal = fa[0].get("fundamental_signal")
                stock.pe_ratio = fa[0].get("pe_ratio")
        except Exception:
            pass

        # Enrich with TA data
        try:
            ta = _query_sync(
                """SELECT rsi, overall_signal, change_pct
                   FROM datapai.ta_indicators
                   WHERE ticker = %s AND exchange = %s AND timeframe = '1d'
                   ORDER BY trade_date DESC LIMIT 1""",
                (ticker, exchange),
            )
            if ta:
                stock.rsi = ta[0].get("rsi")
                stock.overall_signal = ta[0].get("overall_signal")
                stock.change_pct = ta[0].get("change_pct")
        except Exception:
            pass

        # Enrich with synthesis
        try:
            syn = _query_sync(
                """SELECT direction, confidence, thesis
                   FROM datapai.stock_synthesis
                   WHERE ticker = %s AND exchange = %s
                   ORDER BY computed_at DESC LIMIT 1""",
                (ticker, exchange),
            )
            if syn:
                try:
                    stock.direction = SignalDirection(syn[0]["direction"])
                except ValueError:
                    pass
                stock.confidence = syn[0].get("confidence")
                stock.thesis = syn[0].get("thesis")
        except Exception:
            pass

        stocks.append(stock)

    return stocks


# ── Analysis (local, no LLM needed) ───────────────────────────────────────

def compute_sector_groups(stocks: List[WatchlistStock]) -> List[SectorGroup]:
    """Group watchlist stocks by sector."""
    sectors: dict[str, list[WatchlistStock]] = {}
    for s in stocks:
        sector = s.sector or "Unknown"
        sectors.setdefault(sector, []).append(s)

    groups = []
    for sector, sector_stocks in sorted(sectors.items(), key=lambda x: -len(x[1])):
        confidences = [s.confidence for s in sector_stocks if s.confidence]
        directions = [s.direction.value for s in sector_stocks if s.direction]
        # Most common direction
        if directions:
            from collections import Counter
            dominant = Counter(directions).most_common(1)[0][0]
        else:
            dominant = "HOLD"

        groups.append(SectorGroup(
            sector=sector,
            count=len(sector_stocks),
            tickers=[s.ticker for s in sector_stocks],
            avg_confidence=sum(confidences) / len(confidences) if confidences else 0,
            dominant_direction=dominant,
        ))
    return groups


def compute_diversity_score(sector_groups: List[SectorGroup], total: int) -> float:
    """
    Calculate diversity score (0-1).
    Uses Herfindahl-Hirschman Index (HHI) normalized.
    1 sector = 0.0, perfectly spread = 1.0.
    """
    if total <= 1 or not sector_groups:
        return 0.0
    shares = [g.count / total for g in sector_groups]
    hhi = sum(s ** 2 for s in shares)
    # Normalize: HHI ranges from 1/n (perfect) to 1 (concentrated)
    n = len(sector_groups)
    min_hhi = 1.0 / n if n > 0 else 1.0
    if min_hhi >= 1.0:
        return 0.0
    diversity = (1.0 - hhi) / (1.0 - min_hhi)
    return max(0.0, min(1.0, diversity))


# ── AG2 / LLM Synthesis ───────────────────────────────────────────────────

async def generate_watchlist_overview(
    stocks: List[WatchlistStock],
    skip_llm: bool = False,
    model: Optional[str] = None,
) -> WatchlistOverview:
    """
    Generate a complete watchlist overview using local analysis + LLM synthesis.
    """
    use_model = model or "gpt-4o-mini"

    # Local analysis
    sector_groups = compute_sector_groups(stocks)
    total = len(stocks)
    diversity = compute_diversity_score(sector_groups, total)

    buy_count = sum(1 for s in stocks if s.direction and s.direction.value in ("BUY", "STRONG_BUY"))
    sell_count = sum(1 for s in stocks if s.direction and s.direction.value in ("SELL", "STRONG_SELL"))
    hold_count = total - buy_count - sell_count

    # Find top opportunities (highest confidence BUY signals + oversold RSI)
    opportunities = sorted(
        [s for s in stocks if s.direction and s.direction.value in ("BUY", "STRONG_BUY")],
        key=lambda s: (s.confidence or 0),
        reverse=True,
    )[:3]

    # If no BUY signals, pick lowest RSI (most oversold)
    if not opportunities:
        opportunities = sorted(
            [s for s in stocks if s.rsi is not None],
            key=lambda s: s.rsi or 100,
        )[:3]

    # Diversity assessment
    if diversity > 0.7:
        diversity_text = "Well diversified across sectors"
    elif diversity > 0.4:
        diversity_text = "Moderate diversification — some sector concentration"
    else:
        top_sector = sector_groups[0] if sector_groups else None
        if top_sector:
            diversity_text = f"Over-concentrated in {top_sector.sector} ({top_sector.count}/{total} stocks)"
        else:
            diversity_text = "Insufficient data to assess diversification"

    # LLM synthesis for narrative
    ai_summary = ""
    if skip_llm:
        return WatchlistOverview(
            total_stocks=total, buy_count=buy_count, hold_count=hold_count,
            sell_count=sell_count, diversity_score=diversity,
            diversity_assessment=diversity_text, sector_groups=sector_groups,
            risk_clusters=[], top_risk="", top_opportunities=[],
            opportunity_summary="", ai_summary="", ai_action_items=[],
            computed_at=datetime.utcnow().isoformat(), model_used="local",
            stocks_analyzed=total,
        )
    ai_actions: List[str] = []
    risk_clusters: List[RiskCluster] = []
    top_risk = ""

    try:
        context = _build_llm_context(stocks, sector_groups, diversity, diversity_text)
        ai_result = await _llm_synthesize(context, use_model)
        if ai_result:
            ai_summary = ai_result.get("summary", "")
            ai_actions = ai_result.get("action_items", [])
            top_risk = ai_result.get("top_risk", "")
            for rc in ai_result.get("risk_clusters", []):
                risk_clusters.append(RiskCluster(**rc))
    except Exception as exc:
        logger.warning("LLM watchlist synthesis failed: %s", str(exc)[:200])
        ai_summary = f"Your watchlist has {total} stocks across {len(sector_groups)} sectors. " \
                     f"{diversity_text}. {buy_count} stocks showing BUY signals."

    return WatchlistOverview(
        total_stocks=total,
        buy_count=buy_count,
        hold_count=hold_count,
        sell_count=sell_count,
        diversity_score=diversity,
        diversity_assessment=diversity_text,
        sector_groups=sector_groups,
        risk_clusters=risk_clusters,
        top_risk=top_risk,
        top_opportunities=[s.ticker for s in opportunities],
        opportunity_summary=", ".join(
            f"{s.ticker} ({s.direction.value if s.direction else 'N/A'}, "
            f"RSI={s.rsi:.0f})" if s.rsi else f"{s.ticker}"
            for s in opportunities
        ),
        ai_summary=ai_summary,
        ai_action_items=ai_actions,
        model_used=use_model,
        stocks_analyzed=total,
    )


def _build_llm_context(
    stocks: List[WatchlistStock],
    sector_groups: List[SectorGroup],
    diversity: float,
    diversity_text: str,
) -> str:
    lines = [
        f"Watchlist: {len(stocks)} stocks",
        f"Diversity score: {diversity:.2f} — {diversity_text}",
        "",
        "=== SECTOR BREAKDOWN ===",
    ]
    for sg in sector_groups:
        lines.append(f"  {sg.sector}: {sg.count} stocks ({', '.join(sg.tickers)}) — "
                     f"dominant direction: {sg.dominant_direction}")

    lines.append("\n=== STOCK DETAILS ===")
    for s in stocks:
        parts = [f"{s.ticker} ({s.exchange})"]
        if s.sector:
            parts.append(f"sector={s.sector}")
        if s.direction:
            parts.append(f"signal={s.direction.value}")
        if s.confidence:
            parts.append(f"conf={s.confidence:.0%}")
        if s.rsi is not None:
            parts.append(f"RSI={s.rsi:.0f}")
        if s.fundamental_signal:
            parts.append(f"FA={s.fundamental_signal}")
        if s.change_pct is not None:
            parts.append(f"chg={s.change_pct:.1f}%")
        lines.append("  " + " | ".join(parts))

    return "\n".join(lines)


async def _llm_synthesize(context: str, model: str) -> Optional[dict]:
    """Call LLM to generate watchlist narrative and risk analysis."""
    try:
        from agents.llm_client import RouterChatClient

        client = RouterChatClient()
        prompt = (
            "You are a senior portfolio strategist reviewing a client's stock watchlist. "
            "Analyze the following watchlist data and provide:\n\n"
            f"{context}\n\n"
            "Respond with ONLY valid JSON:\n"
            '{\n'
            '  "summary": "2-4 sentence overview of watchlist health",\n'
            '  "top_risk": "single most important risk across the watchlist",\n'
            '  "risk_clusters": [\n'
            '    {"risk_factor": "...", "severity": "HIGH|MEDIUM|LOW", '
            '"affected_tickers": ["..."], "description": "..."}\n'
            '  ],\n'
            '  "action_items": ["actionable recommendation 1", "...", "..."]\n'
            '}'
        )

        response = client.chat(
            messages=[{"role": "user", "content": prompt}],
            
        )
        # Parse JSON from response — chat() returns {role, content} dict
        import re
        content = response.get("content", "") if isinstance(response, dict) else str(response)
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            return json.loads(match.group(0))
        return None
    except Exception as exc:
        logger.warning("LLM synthesis failed: %s", str(exc)[:200])
        return None
