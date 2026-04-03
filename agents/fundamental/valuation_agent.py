"""
agents/fundamental/valuation_agent.py
======================================
Scores a stock's valuation relative to its sector peers.

Public API
----------
score_valuation(data: dict) -> tuple[float, dict]
    Returns (valuation_score, detail_dict).
    valuation_score: -1.0 (very expensive) to +1.0 (very cheap)
    Never raises.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

log = logging.getLogger(__name__)

# Sector median P/E ratios (used for relative P/E scoring)
# Source: long-run historical medians; updated manually ~annually
SECTOR_PE_MEDIANS: dict[str, float] = {
    "Technology":                28.0,
    "Healthcare":                22.0,
    "Financials":                12.0,
    "Financial Services":        12.0,
    "Energy":                    14.0,
    "Materials":                 16.0,
    "Basic Materials":           16.0,
    "Consumer Discretionary":    22.0,
    "Consumer Cyclical":         22.0,
    "Consumer Staples":          20.0,
    "Consumer Defensive":        20.0,
    "Industrials":               20.0,
    "Real Estate":               30.0,
    "Utilities":                 18.0,
    "Communication Services":    20.0,
    "Communication":             20.0,
    "Unknown":                   18.0,
}

# Component weights (must sum to 1.0)
_W_PE       = 0.30
_W_EVEBITDA = 0.25
_W_PB       = 0.20
_W_PEG      = 0.15
_W_FCFYIELD = 0.10


def _clip(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _score_pe(pe: Optional[float], sector: Optional[str]) -> Optional[float]:
    """Relative P/E vs sector median. Positive = cheaper than median."""
    if pe is None or pe <= 0:
        return None
    median = SECTOR_PE_MEDIANS.get(sector or "Unknown", 18.0)
    if median == 0:
        return None
    raw = (median - pe) / median
    return _clip(raw)


def _score_ev_ebitda(ev_ebitda: Optional[float]) -> Optional[float]:
    if ev_ebitda is None or ev_ebitda <= 0:
        return None
    if ev_ebitda < 8:
        return 1.0
    if ev_ebitda < 12:
        return 0.5
    if ev_ebitda < 18:
        return 0.0
    if ev_ebitda < 25:
        return -0.5
    return -1.0


def _score_pb(pb: Optional[float]) -> Optional[float]:
    if pb is None or pb <= 0:
        return None
    if pb < 1.0:
        return 1.0
    if pb < 2.0:
        return 0.5
    if pb < 4.0:
        return 0.0
    if pb < 7.0:
        return -0.5
    return -1.0


def _score_peg(peg: Optional[float]) -> Optional[float]:
    if peg is None or peg <= 0:
        return None
    if peg < 1.0:
        return 1.0
    if peg < 1.5:
        return 0.5
    if peg < 2.5:
        return 0.0
    return -0.5


def _score_fcf_yield(fcf_yield: Optional[float]) -> Optional[float]:
    """FCF yield as decimal (e.g. 0.05 = 5%)."""
    if fcf_yield is None:
        return None
    if fcf_yield > 0.08:
        return 1.0
    if fcf_yield > 0.04:
        return 0.5
    if fcf_yield > 0.01:
        return 0.0
    return -0.5


def _weighted_avg(scores: list[tuple[Optional[float], float]]) -> float:
    """Weighted average ignoring None components; fall back to 0 if all None."""
    total_weight = 0.0
    total_score = 0.0
    for score, weight in scores:
        if score is not None:
            total_score += score * weight
            total_weight += weight
    if total_weight == 0:
        return 0.0
    return total_score / total_weight


def score_valuation(data: dict) -> Tuple[float, dict]:
    """
    Score the stock's valuation.

    Parameters
    ----------
    data : dict
        Flat fundamental data dict from fetcher.fetch_fundamentals().

    Returns
    -------
    (valuation_score, detail)
        valuation_score : float in [-1.0, +1.0]
        detail : dict with per-metric sub-scores
    """
    try:
        sector = data.get("sector")

        pe_s      = _score_pe(data.get("pe_ratio"),    sector)
        ev_s      = _score_ev_ebitda(data.get("ev_ebitda"))
        pb_s      = _score_pb(data.get("pb_ratio"))
        peg_s     = _score_peg(data.get("peg_ratio"))
        fcfy_s    = _score_fcf_yield(data.get("fcf_yield"))

        composite = _weighted_avg([
            (pe_s,   _W_PE),
            (ev_s,   _W_EVEBITDA),
            (pb_s,   _W_PB),
            (peg_s,  _W_PEG),
            (fcfy_s, _W_FCFYIELD),
        ])

        detail = {
            "pe_score":         pe_s,
            "ev_ebitda_score":  ev_s,
            "pb_score":         pb_s,
            "peg_score":        peg_s,
            "fcf_yield_score":  fcfy_s,
            "sector_pe_median": SECTOR_PE_MEDIANS.get(sector or "Unknown", 18.0),
        }

        return round(composite, 4), detail

    except Exception as exc:
        log.warning("valuation scoring error for %s: %s", data.get("ticker"), exc)
        return 0.0, {}
