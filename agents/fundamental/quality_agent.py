"""
agents/fundamental/quality_agent.py
=====================================
Scores business quality / moat strength from fundamental data.

Public API
----------
score_quality(data: dict) -> tuple[float, dict]
    Returns (quality_score, detail_dict).
    quality_score: 0.0 (poor) to 1.0 (exceptional)
    Never raises.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

log = logging.getLogger(__name__)

# Component weights (must sum to 1.0)
_W_ROE            = 0.25
_W_NET_MARGIN     = 0.20
_W_GROSS_MARGIN   = 0.15
_W_DEBT           = 0.20
_W_CURRENT_RATIO  = 0.10
_W_INT_COVERAGE   = 0.10


def _clip01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _score_roe(roe: Optional[float]) -> Optional[float]:
    """ROE as decimal (e.g. 0.20 = 20%)."""
    if roe is None:
        return None
    if roe > 0.25:
        return 1.0
    if roe > 0.15:
        return 0.75
    if roe > 0.08:
        return 0.5
    if roe > 0.0:
        return 0.25
    return 0.0   # negative ROE


def _score_net_margin(nm: Optional[float]) -> Optional[float]:
    """Net margin as decimal."""
    if nm is None:
        return None
    if nm > 0.20:
        return 1.0
    if nm > 0.10:
        return 0.75
    if nm > 0.05:
        return 0.5
    if nm > 0.0:
        return 0.25
    return 0.0


def _score_gross_margin(gm: Optional[float]) -> Optional[float]:
    """Gross margin as decimal."""
    if gm is None:
        return None
    if gm > 0.60:
        return 1.0
    if gm > 0.40:
        return 0.75
    if gm > 0.25:
        return 0.5
    if gm > 0.10:
        return 0.25
    return 0.0


def _score_debt(de: Optional[float]) -> Optional[float]:
    """D/E ratio (lower is better). yfinance returns raw ratio (e.g. 50 = 50%)."""
    if de is None:
        return None
    # yfinance debtToEquity is expressed as percentage (e.g. 150 means 1.5x)
    de_ratio = de / 100.0 if de > 5 else de   # normalise if reported as %
    if de_ratio <= 0.0:
        return 1.0   # net cash
    if de_ratio < 0.30:
        return 0.9
    if de_ratio < 0.70:
        return 0.7
    if de_ratio < 1.50:
        return 0.4
    if de_ratio < 3.0:
        return 0.2
    return 0.0


def _score_current_ratio(cr: Optional[float]) -> Optional[float]:
    if cr is None:
        return None
    if cr >= 2.0:
        return 1.0
    if cr >= 1.5:
        return 0.75
    if cr >= 1.0:
        return 0.5
    if cr >= 0.75:
        return 0.25
    return 0.0


def _score_interest_coverage(ic: Optional[float]) -> Optional[float]:
    """Interest coverage = EBIT / interest expense."""
    if ic is None:
        return None
    if ic > 10:
        return 1.0
    if ic > 5:
        return 0.75
    if ic > 2:
        return 0.5
    if ic > 1:
        return 0.25
    return 0.0


def _weighted_avg(scores: list[tuple[Optional[float], float]]) -> float:
    total_weight = 0.0
    total_score = 0.0
    for score, weight in scores:
        if score is not None:
            total_score += score * weight
            total_weight += weight
    if total_weight == 0:
        return 0.5   # neutral default when no data available
    return total_score / total_weight


def score_quality(data: dict) -> Tuple[float, dict]:
    """
    Score business quality / moat.

    Parameters
    ----------
    data : dict
        Flat fundamental data dict from fetcher.fetch_fundamentals().

    Returns
    -------
    (quality_score, detail)
        quality_score : float in [0.0, 1.0]
        detail : dict with per-metric sub-scores
    """
    try:
        roe_s  = _score_roe(data.get("roe"))
        nm_s   = _score_net_margin(data.get("net_margin"))
        gm_s   = _score_gross_margin(data.get("gross_margin"))
        de_s   = _score_debt(data.get("debt_to_equity"))
        cr_s   = _score_current_ratio(data.get("current_ratio"))
        ic_s   = _score_interest_coverage(data.get("interest_coverage"))

        composite = _clip01(_weighted_avg([
            (roe_s, _W_ROE),
            (nm_s,  _W_NET_MARGIN),
            (gm_s,  _W_GROSS_MARGIN),
            (de_s,  _W_DEBT),
            (cr_s,  _W_CURRENT_RATIO),
            (ic_s,  _W_INT_COVERAGE),
        ]))

        detail = {
            "roe_score":               roe_s,
            "net_margin_score":        nm_s,
            "gross_margin_score":      gm_s,
            "debt_score":              de_s,
            "current_ratio_score":     cr_s,
            "interest_coverage_score": ic_s,
        }

        return round(composite, 4), detail

    except Exception as exc:
        log.warning("quality scoring error for %s: %s", data.get("ticker"), exc)
        return 0.5, {}
