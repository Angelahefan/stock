"""
agents/fundamental/growth_agent.py
=====================================
Scores a stock's growth trajectory from fundamental data.

Public API
----------
score_growth(data: dict) -> tuple[float, dict]
    Returns (growth_score, detail_dict).
    growth_score: 0.0 (declining / no growth) to 1.0 (exceptional growth)
    Never raises.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

log = logging.getLogger(__name__)

# Component weights (must sum to 1.0)
_W_REV_YOY   = 0.35
_W_EPS_YOY   = 0.35
_W_FCF_TREND = 0.20
_W_CAGR      = 0.10


def _clip01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _score_yoy(growth: Optional[float]) -> Optional[float]:
    """
    Score YoY growth rate (decimal, e.g. 0.20 = 20%).
    Returns 0.0–1.0.
    """
    if growth is None:
        return None
    if growth > 0.30:
        return 1.0
    if growth > 0.15:
        return 0.8
    if growth > 0.05:
        return 0.6
    if growth > 0.0:
        return 0.4
    if growth > -0.05:
        return 0.2
    if growth > -0.15:
        return 0.1
    return 0.0


def _score_cagr(cagr: Optional[float]) -> Optional[float]:
    """5-year revenue CAGR (decimal)."""
    if cagr is None:
        return None
    if cagr > 0.20:
        return 1.0
    if cagr > 0.10:
        return 0.75
    if cagr > 0.05:
        return 0.5
    if cagr > 0.0:
        return 0.25
    return 0.0


def _score_fcf_trend(data: dict) -> Optional[float]:
    """
    Infer FCF growth trend from history list (annual periods).
    Returns 0.0–1.0 or None if insufficient data.
    """
    history = data.get("history") or []
    annual = sorted(
        [p for p in history if p.get("period_type") == "annual" and p.get("free_cash_flow")],
        key=lambda x: x["period_end"],
    )
    if len(annual) < 2:
        return None

    # Take last 3 years
    recent = annual[-3:]
    fcfs = [p["free_cash_flow"] for p in recent]

    # Check monotonic increase
    if len(fcfs) >= 2:
        increases = sum(1 for i in range(1, len(fcfs)) if fcfs[i] > fcfs[i - 1])
        trend_ratio = increases / (len(fcfs) - 1)

        # Also check if most recent FCF > oldest in the window
        total_growth = (fcfs[-1] - fcfs[0]) / abs(fcfs[0]) if fcfs[0] != 0 else None

        if total_growth is not None and total_growth > 0.30 and trend_ratio >= 0.5:
            return 1.0
        if total_growth is not None and total_growth > 0.10 and trend_ratio >= 0.5:
            return 0.75
        if trend_ratio >= 0.5:
            return 0.5
        if trend_ratio > 0:
            return 0.25
        return 0.0
    return None


def _weighted_avg(scores: list[tuple[Optional[float], float]]) -> float:
    total_weight = 0.0
    total_score = 0.0
    for score, weight in scores:
        if score is not None:
            total_score += score * weight
            total_weight += weight
    if total_weight == 0:
        return 0.4   # neutral-low default when no data
    return total_score / total_weight


def score_growth(data: dict) -> Tuple[float, dict]:
    """
    Score growth trajectory.

    Parameters
    ----------
    data : dict
        Flat fundamental data dict from fetcher.fetch_fundamentals()
        (must include 'history' key for FCF trend).

    Returns
    -------
    (growth_score, detail)
        growth_score : float in [0.0, 1.0]
        detail : dict with per-metric sub-scores
    """
    try:
        rev_s  = _score_yoy(data.get("revenue_yoy"))
        eps_s  = _score_yoy(data.get("earnings_yoy"))
        fcf_s  = _score_fcf_trend(data)
        cagr_s = _score_cagr(data.get("revenue_growth_5yr"))

        composite = _clip01(_weighted_avg([
            (rev_s,  _W_REV_YOY),
            (eps_s,  _W_EPS_YOY),
            (fcf_s,  _W_FCF_TREND),
            (cagr_s, _W_CAGR),
        ]))

        detail = {
            "revenue_yoy_score": rev_s,
            "eps_yoy_score":     eps_s,
            "fcf_trend_score":   fcf_s,
            "cagr_score":        cagr_s,
        }

        return round(composite, 4), detail

    except Exception as exc:
        log.warning("growth scoring error for %s: %s", data.get("ticker"), exc)
        return 0.4, {}
