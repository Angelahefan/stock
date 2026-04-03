"""
agents/stock_synthesis/risk_agent.py
─────────────────────────────────────────────────────────────────────────────
Quantitative Risk Agent for the Investment Committee.

Computes hard risk metrics from TA indicators, fundamentals, macro regime,
and news events. Unlike the AG2 Risk_Manager (qualitative debate), this
agent outputs a numeric risk_score that gates trade entry.

Usage:
    from agents.stock_synthesis.risk_agent import assess_risk, RiskAssessment

    risk = assess_risk(
        ta_data={...},
        fa_data={...},
        regime=MarketRegime.BEAR_RECESSION,
        news_data={...},
    )
    if risk.risk_score > 0.7:
        # suppress BUY signal
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class PositionSize(str, Enum):
    FULL = "FULL"
    HALF = "HALF"
    QUARTER = "QUARTER"
    NONE = "NONE"


@dataclass
class RiskAssessment:
    """Quantitative risk assessment output."""
    risk_score: float = 0.0                # 0.0 (safe) to 1.0 (extreme risk)
    risk_flags: List[str] = field(default_factory=list)
    position_size: PositionSize = PositionSize.FULL
    max_loss_estimate_pct: float = 0.0     # expected max drawdown %
    risk_breakdown: Dict[str, float] = field(default_factory=dict)  # per-factor scores


# ---------------------------------------------------------------------------
# Risk factor scoring functions
# ---------------------------------------------------------------------------

def _volatility_risk(ta_data: Dict[str, Any]) -> tuple[float, Optional[str]]:
    """
    Score volatility risk: 20-day realized vol vs threshold.

    Returns (score, flag_or_none).
    """
    vol_20d = ta_data.get("volatility_20d")
    if vol_20d is None:
        return 0.0, None

    if vol_20d > 0.50:
        return 1.0, f"EXTREME volatility ({vol_20d:.0%} annualized)"
    if vol_20d > 0.35:
        return 0.7, f"HIGH volatility ({vol_20d:.0%} annualized)"
    if vol_20d > 0.25:
        return 0.4, None
    return 0.1, None


def _drawdown_risk(ta_data: Dict[str, Any]) -> tuple[float, Optional[str]]:
    """
    Score drawdown risk: current price vs 52-week high.
    """
    pct_from_high = ta_data.get("pct_from_52w_high")
    if pct_from_high is None:
        return 0.0, None

    if pct_from_high < -30:
        return 1.0, f"SEVERE drawdown ({pct_from_high:.1f}% from 52w high)"
    if pct_from_high < -20:
        return 0.7, f"SIGNIFICANT drawdown ({pct_from_high:.1f}% from 52w high)"
    if pct_from_high < -10:
        return 0.4, None
    return 0.1, None


def _volume_anomaly_risk(ta_data: Dict[str, Any]) -> tuple[float, Optional[str]]:
    """
    Score volume anomaly: unusual spikes on down days.
    """
    vol_ratio = ta_data.get("volume_ratio")
    change_1d = ta_data.get("change_1d_pct")
    if vol_ratio is None or change_1d is None:
        return 0.0, None

    # High volume on a down day = distribution (smart money selling)
    if vol_ratio > 3.0 and change_1d < -2:
        return 0.9, f"DISTRIBUTION: {vol_ratio:.1f}x volume on {change_1d:+.1f}% day"
    if vol_ratio > 2.0 and change_1d < -1:
        return 0.5, None
    return 0.1, None


def _fundamental_risk(fa_data: Dict[str, Any]) -> tuple[float, Optional[str]]:
    """
    Score fundamental deterioration risk.
    """
    if not fa_data:
        return 0.2, None  # no data = mild uncertainty

    flags = []
    scores = []

    # Valuation risk
    pe = fa_data.get("pe_ratio")
    if pe is not None:
        if pe > 50 or pe < 0:
            scores.append(0.8)
            flags.append(f"Extreme P/E: {pe:.1f}")
        elif pe > 30:
            scores.append(0.4)
        else:
            scores.append(0.1)

    # Quality risk — low ROE
    roe = fa_data.get("roe")
    if roe is not None:
        if roe < 0:
            scores.append(0.9)
            flags.append(f"Negative ROE: {roe:.1f}%")
        elif roe < 5:
            scores.append(0.5)
        else:
            scores.append(0.1)

    # Growth risk — negative revenue growth
    rev_yoy = fa_data.get("revenue_yoy")
    if rev_yoy is not None:
        if rev_yoy < -10:
            scores.append(0.8)
            flags.append(f"Revenue declining {rev_yoy:.1f}% YoY")
        elif rev_yoy < 0:
            scores.append(0.4)
        else:
            scores.append(0.1)

    # Fundamental score from FA pipeline
    fund_score = fa_data.get("fundamental_score")
    if fund_score is not None and fund_score < -0.3:
        scores.append(0.7)
        flags.append(f"Weak fundamental score: {fund_score:.2f}")
    elif fund_score is not None:
        scores.append(max(0.0, 0.5 - fund_score))

    avg_score = sum(scores) / len(scores) if scores else 0.2
    flag = "; ".join(flags) if flags else None
    return avg_score, flag


def _macro_regime_risk(
    regime: str,
    sector: Optional[str] = None,
) -> tuple[float, Optional[str]]:
    """
    Score macro headwind risk based on regime + sector cyclicality.
    """
    cyclical_sectors = {
        "Consumer Cyclical", "Financial Services", "Real Estate",
        "Basic Materials", "Energy", "Industrials",
    }
    is_cyclical = sector in cyclical_sectors if sector else False

    if regime == "BEAR_RECESSION":
        if is_cyclical:
            return 0.9, f"BEAR regime + cyclical sector ({sector})"
        return 0.6, "BEAR_RECESSION regime"
    if regime == "NEUTRAL_TRANSITION":
        return 0.3, None
    return 0.1, None  # BULL_MOMENTUM


def _news_risk(news_data: Dict[str, Any]) -> tuple[float, Optional[str]]:
    """
    Score news risk from material events.
    """
    if not news_data:
        return 0.0, None

    severity = news_data.get("highest_severity", "LOW")
    sentiment = news_data.get("overall_sentiment", "NEUTRAL")
    has_critical = news_data.get("has_critical_event", False)

    if has_critical:
        headline = news_data.get("top_event_headline", "Unknown critical event")
        return 1.0, f"CRITICAL NEWS: {headline}"
    if severity == "HIGH" and "NEGATIVE" in sentiment.upper():
        return 0.8, f"HIGH severity negative news"
    if severity == "HIGH":
        return 0.5, None
    if severity == "MEDIUM" and "NEGATIVE" in sentiment.upper():
        return 0.4, None
    return 0.1, None


# ---------------------------------------------------------------------------
# Main risk assessment
# ---------------------------------------------------------------------------

# Factor weights — sum to 1.0
_FACTOR_WEIGHTS = {
    "volatility": 0.15,
    "drawdown": 0.15,
    "volume_anomaly": 0.15,
    "fundamental": 0.20,
    "macro_regime": 0.15,
    "news": 0.20,
}


def assess_risk(
    ta_data: Dict[str, Any],
    fa_data: Optional[Dict[str, Any]] = None,
    regime: str = "NEUTRAL_TRANSITION",
    news_data: Optional[Dict[str, Any]] = None,
    sector: Optional[str] = None,
) -> RiskAssessment:
    """
    Compute quantitative risk assessment.

    Parameters
    ----------
    ta_data : dict
        TA indicators (rsi_14, volatility_20d, pct_from_52w_high, volume_ratio, change_1d_pct)
    fa_data : dict, optional
        Fundamental data (pe_ratio, roe, revenue_yoy, fundamental_score)
    regime : str
        Market regime label from classify_regime()
    news_data : dict, optional
        News event data (highest_severity, overall_sentiment, has_critical_event, top_event_headline)
    sector : str, optional
        Stock sector for cyclicality assessment

    Returns
    -------
    RiskAssessment
    """
    all_flags: List[str] = []
    breakdown: Dict[str, float] = {}

    # Evaluate each risk factor
    factors = {
        "volatility": _volatility_risk(ta_data),
        "drawdown": _drawdown_risk(ta_data),
        "volume_anomaly": _volume_anomaly_risk(ta_data),
        "fundamental": _fundamental_risk(fa_data or {}),
        "macro_regime": _macro_regime_risk(regime, sector),
        "news": _news_risk(news_data or {}),
    }

    weighted_score = 0.0
    for factor_name, (score, flag) in factors.items():
        weight = _FACTOR_WEIGHTS[factor_name]
        weighted_score += score * weight
        breakdown[factor_name] = round(score, 3)
        if flag:
            all_flags.append(flag)

    risk_score = min(1.0, weighted_score)

    # Critical news override — always max risk
    news_score = factors["news"][0]
    if news_score >= 1.0:
        risk_score = max(risk_score, 0.95)

    # Position sizing based on risk score
    if risk_score >= 0.7:
        position_size = PositionSize.NONE
    elif risk_score >= 0.5:
        position_size = PositionSize.QUARTER
    elif risk_score >= 0.3:
        position_size = PositionSize.HALF
    else:
        position_size = PositionSize.FULL

    # Max loss estimate — based on volatility + drawdown
    vol_20d = ta_data.get("volatility_20d", 0.20)
    daily_vol = vol_20d / (252 ** 0.5) if vol_20d else 0.01
    max_loss_estimate = round(daily_vol * 5 * 100, 1)  # ~5 daily moves

    return RiskAssessment(
        risk_score=round(risk_score, 4),
        risk_flags=all_flags,
        position_size=position_size,
        max_loss_estimate_pct=max_loss_estimate,
        risk_breakdown=breakdown,
    )


def assess_risk_from_row(
    row: dict,
    fa_data: Optional[dict] = None,
    regime: str = "NEUTRAL_TRANSITION",
    news_data: Optional[dict] = None,
    sector: Optional[str] = None,
) -> RiskAssessment:
    """
    Convenience: assess risk from a backtest DataFrame row dict.
    Maps common column names to the ta_data format.
    """
    ta_data = {
        "volatility_20d": row.get("volatility_20d"),
        "pct_from_52w_high": row.get("pct_from_52w_high"),
        "volume_ratio": row.get("volume_ratio"),
        "change_1d_pct": row.get("change_1d_pct"),
        "rsi_14": row.get("rsi_14"),
    }
    return assess_risk(ta_data, fa_data, regime, news_data, sector)
