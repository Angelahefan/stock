"""
agents/stock_synthesis/signal_gatherer.py
─────────────────────────────────────────────────────────────────────────────
Gathers signals from TA, FA, and MA (TinyFish IR) agents into
AgentSignalInput objects for the synthesis pipeline.

Reads from Postgres tables:
    - datapai.ta_indicators → TA signal
    - datapai.fundamental_snapshot → FA signal
    - datapai.analyses → MA signal (TinyFish IR scan)

Uses psycopg2 (sync) for batch scripts, with async wrapper for FastAPI.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from agents.stock_synthesis.contracts import (
    AgentSignalInput,
    SignalDirection,
    SignalSource,
)

logger = logging.getLogger(__name__)


def _ta_to_direction(overall_signal: Optional[str], rsi: Optional[float]) -> SignalDirection:
    if not overall_signal:
        return SignalDirection.HOLD
    sig = overall_signal.upper()
    if sig in ("STRONG_BUY", "STRONGBUY"):
        return SignalDirection.STRONG_BUY
    if sig == "BUY":
        return SignalDirection.BUY
    if sig in ("STRONG_SELL", "STRONGSELL"):
        return SignalDirection.STRONG_SELL
    if sig == "SELL":
        return SignalDirection.SELL
    if rsi is not None:
        if rsi < 30:
            return SignalDirection.BUY
        if rsi > 70:
            return SignalDirection.SELL
    return SignalDirection.HOLD


def _fa_to_direction(score: Optional[float], signal: Optional[str]) -> SignalDirection:
    if signal:
        s = signal.upper()
        if "STRONG" in s and "BUY" in s:
            return SignalDirection.STRONG_BUY
        if "BUY" in s:
            return SignalDirection.BUY
        if "STRONG" in s and "SELL" in s:
            return SignalDirection.STRONG_SELL
        if "SELL" in s:
            return SignalDirection.SELL
    if score is not None:
        if score > 0.3:
            return SignalDirection.BUY
        if score < -0.3:
            return SignalDirection.SELL
    return SignalDirection.HOLD


def _ma_to_direction(agent_signal_type: Optional[str], agent_confidence: Optional[float]) -> SignalDirection:
    if not agent_signal_type or agent_signal_type == "NO_SIGNAL":
        return SignalDirection.HOLD
    sig = agent_signal_type.upper()
    conf = agent_confidence or 0.5
    if "GUIDANCE_WITHDRAWAL" in sig:
        return SignalDirection.SELL if conf > 0.6 else SignalDirection.HOLD
    if "RISK_DISCLOSURE" in sig:
        return SignalDirection.SELL if conf > 0.5 else SignalDirection.HOLD
    if "TONE_SOFTENING" in sig:
        return SignalDirection.HOLD
    return SignalDirection.HOLD


def _news_to_direction(severity: str, sentiment: str) -> SignalDirection:
    """Map news severity + sentiment to a signal direction."""
    sev = (severity or "").upper()
    sent = (sentiment or "").upper()

    if sev == "CRITICAL":
        if "NEGATIVE" in sent:
            return SignalDirection.STRONG_SELL
        if "POSITIVE" in sent:
            return SignalDirection.STRONG_BUY
        return SignalDirection.SELL  # CRITICAL + neutral = defensive
    if sev == "HIGH":
        if "NEGATIVE" in sent:
            return SignalDirection.SELL
        if "POSITIVE" in sent:
            return SignalDirection.BUY
        return SignalDirection.HOLD
    return SignalDirection.HOLD


def gather_news_signals(ticker: str, exchange: str) -> Optional[AgentSignalInput]:
    """
    Fetch and classify breaking news for a ticker, returning an AgentSignalInput.
    Uses the news_agent module: fetch -> LLM classify -> return signal.
    Returns None if no material news found.
    """
    try:
        from agents.news_agent import run_news_agent, Severity, Sentiment
    except ImportError:
        logger.warning("news_agent module not available — skipping news signals")
        return None

    try:
        result = run_news_agent(ticker, exchange, persist=True)
    except Exception as exc:
        logger.warning("News agent failed for %s: %s", ticker, str(exc)[:200])
        return None

    if not result.material_events:
        return None

    # Use highest severity event to drive the signal
    direction = _news_to_direction(
        result.highest_severity.value,
        result.overall_sentiment.value,
    )

    # Confidence: scale by severity
    severity_conf = {
        "CRITICAL": 0.95,
        "HIGH": 0.75,
        "MEDIUM": 0.55,
        "LOW": 0.35,
        "NONE": 0.1,
    }
    confidence = severity_conf.get(result.highest_severity.value, 0.3)

    # Key factors from top events
    factors = []
    for ev in result.material_events[:5]:
        tag = f"[{ev.severity.value}] {ev.event_type.value}: {ev.title[:80]}"
        factors.append(tag)

    # Summary from the most severe event
    top_event = max(
        result.material_events,
        key=lambda e: {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "NONE": 0}.get(e.severity.value, 0),
    )

    summary_text = (
        f"Breaking news: {result.highest_severity.value} severity — "
        f"{top_event.summary or top_event.title}"
    )

    return AgentSignalInput(
        source=SignalSource.NEWS,
        direction=direction,
        confidence=confidence,
        summary=summary_text[:200],
        key_factors=factors,
        data={
            "news_items_fetched": result.news_items_fetched,
            "material_events_count": len(result.material_events),
            "has_critical_event": result.has_critical_event,
            "highest_severity": result.highest_severity.value,
            "overall_sentiment": result.overall_sentiment.value,
            "top_event_type": top_event.event_type.value,
            "top_event_headline": top_event.title[:120],
        },
    )


def _query_sync(sql: str, params: tuple) -> list[dict]:
    """Run a sync query using psycopg2 (for batch scripts)."""
    from scripts.lib.db_helpers import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    return []


async def gather_signals(
    ticker: str,
    exchange: str,
) -> List[AgentSignalInput]:
    """
    Gather the latest TA, FA, and MA signals for a ticker from Postgres.
    Works in both sync (batch scripts) and async (FastAPI) contexts.
    """
    signals: List[AgentSignalInput] = []

    # ── TA Signal ──
    try:
        ta_rows = _query_sync(
            """SELECT overall_signal, signal_score, rsi, rsi_label, macd_label,
                      bb_label, close, change_pct, trade_date
               FROM datapai.ta_indicators
               WHERE ticker = %s AND exchange = %s AND timeframe = '1d'
               ORDER BY trade_date DESC LIMIT 1""",
            (ticker, exchange),
        )
        if ta_rows:
            ta = ta_rows[0]
            direction = _ta_to_direction(ta.get("overall_signal"), ta.get("rsi"))
            confidence = min(abs(ta.get("signal_score") or 0) / 2, 1.0)
            factors = []
            if ta.get("rsi_label"):
                factors.append(f"RSI {ta['rsi']:.0f} ({ta['rsi_label']})")
            if ta.get("macd_label"):
                factors.append(f"MACD: {ta['macd_label']}")
            if ta.get("bb_label"):
                factors.append(f"BB: {ta['bb_label']}")
            if ta.get("change_pct"):
                factors.append(f"Change: {ta['change_pct']:.1f}%")

            signals.append(AgentSignalInput(
                source=SignalSource.TECHNICAL,
                direction=direction,
                confidence=confidence,
                summary=f"TA signal: {ta.get('overall_signal', 'NEUTRAL')} "
                        f"(RSI={ta.get('rsi', 'N/A')}, MACD={ta.get('macd_label', 'N/A')})",
                key_factors=factors,
                data={
                    "overall_signal": ta.get("overall_signal"),
                    "signal_score": ta.get("signal_score"),
                    "rsi": ta.get("rsi"),
                    "macd_label": ta.get("macd_label"),
                    "bb_label": ta.get("bb_label"),
                    "close": ta.get("close"),
                    "change_pct": ta.get("change_pct"),
                },
            ))
    except Exception as exc:
        logger.warning("Failed to gather TA signal for %s: %s", ticker, exc)

    # ── FA Signal ──
    try:
        fa_rows = _query_sync(
            """SELECT fundamental_score, fundamental_signal, valuation_score,
                      quality_score, growth_score, macro_score,
                      pe_ratio, roe, revenue_yoy, analyst_consensus,
                      analyst_upside_pct, fundamental_summary
               FROM datapai.fundamental_snapshot
               WHERE ticker = %s AND exchange = %s""",
            (ticker, exchange),
        )
        if fa_rows:
            fa = fa_rows[0]
            direction = _fa_to_direction(fa.get("fundamental_score"), fa.get("fundamental_signal"))
            confidence = min(abs(fa.get("fundamental_score") or 0) * 2, 1.0)
            factors = []
            if fa.get("valuation_score") is not None:
                factors.append(f"Valuation: {fa['valuation_score']:.2f}")
            if fa.get("quality_score") is not None:
                factors.append(f"Quality: {fa['quality_score']:.2f}")
            if fa.get("growth_score") is not None:
                factors.append(f"Growth: {fa['growth_score']:.2f}")
            if fa.get("analyst_consensus"):
                factors.append(f"Analyst: {fa['analyst_consensus']}")

            signals.append(AgentSignalInput(
                source=SignalSource.FUNDAMENTAL,
                direction=direction,
                confidence=confidence,
                summary=(fa.get("fundamental_summary") or "")[:200] or
                        f"FA signal: {fa.get('fundamental_signal', 'NEUTRAL')} "
                        f"(score={fa.get('fundamental_score', 0):.2f})",
                key_factors=factors,
                data={
                    "fundamental_score": fa.get("fundamental_score"),
                    "fundamental_signal": fa.get("fundamental_signal"),
                    "pe_ratio": fa.get("pe_ratio"),
                    "roe": fa.get("roe"),
                    "revenue_yoy": fa.get("revenue_yoy"),
                    "analyst_consensus": fa.get("analyst_consensus"),
                    "analyst_upside_pct": fa.get("analyst_upside_pct"),
                },
            ))
    except Exception as exc:
        logger.warning("Failed to gather FA signal for %s: %s", ticker, exc)

    # ── MA Signal (TinyFish IR) ──
    try:
        ma_rows = _query_sync(
            """SELECT a.agent_signal_type, a.agent_severity, a.agent_confidence,
                      a.agent_what_changed, a.agent_why_matters,
                      a.change_type, a.validation_status,
                      s.ticker
               FROM datapai.analyses a
               JOIN datapai.snapshots s ON a.snapshot_new_id = s.id
               WHERE s.ticker = %s
                 AND a.agent_signal_type IS NOT NULL
                 AND a.agent_signal_type != 'NO_SIGNAL'
               ORDER BY a.id DESC LIMIT 1""",
            (ticker,),
        )
        if ma_rows:
            ma = ma_rows[0]
            direction = _ma_to_direction(ma.get("agent_signal_type"), ma.get("agent_confidence"))
            factors = []
            if ma.get("agent_signal_type"):
                factors.append(f"Signal: {ma['agent_signal_type']}")
            if ma.get("agent_severity"):
                factors.append(f"Severity: {ma['agent_severity']}")
            if ma.get("validation_status"):
                factors.append(f"Validation: {ma['validation_status']}")

            signals.append(AgentSignalInput(
                source=SignalSource.MARKET_ACTIVITY,
                direction=direction,
                confidence=ma.get("agent_confidence") or 0.5,
                summary=ma.get("agent_what_changed") or "IR page change detected",
                key_factors=factors,
                data={
                    "signal_type": ma.get("agent_signal_type"),
                    "severity": ma.get("agent_severity"),
                    "validation_status": ma.get("validation_status"),
                    "what_changed": ma.get("agent_what_changed"),
                    "why_matters": ma.get("agent_why_matters"),
                },
            ))
    except Exception as exc:
        logger.warning("Failed to gather MA signal for %s: %s", ticker, exc)

    # ── NEWS Signal (Material Events / Breaking News) ──
    try:
        news_signal = gather_news_signals(ticker, exchange)
        if news_signal:
            signals.append(news_signal)
    except Exception as exc:
        logger.warning("Failed to gather NEWS signal for %s: %s", ticker, exc)

    logger.info("Gathered %d signals for %s/%s: %s",
                len(signals), ticker, exchange,
                ", ".join(f"{s.source.value}={s.direction.value}" for s in signals))
    return signals
