"""
agents/fundamental/fundamental_classifier.py
=============================================
Combines component scores into a composite fundamental score and
maps it to a signal label.

Scoring weights
---------------
  Valuation : 35%  (cheap stocks rewarded)
  Quality   : 30%  (moat / profitability)
  Growth    : 20%  (revenue / earnings trajectory)
  Macro     : 15%  (macro-economic + geopolitical backdrop)

Signal thresholds (composite score range -1.0 to +1.0)
-------------------------------------------------------
  ≥ +0.50  →  STRONG_BUY
  ≥ +0.20  →  BUY
  > -0.20  →  NEUTRAL
  > -0.50  →  SELL
  ≤ -0.50  →  STRONG_SELL

Public API
----------
classify_fundamental(valuation, quality, growth, macro) -> tuple[float, str]
    Returns (fundamental_score, fundamental_signal). Never raises.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

log = logging.getLogger(__name__)

_W_VALUATION = 0.35
_W_QUALITY   = 0.30
_W_GROWTH    = 0.20
_W_MACRO     = 0.15


def classify_fundamental(
    valuation_score: Optional[float],
    quality_score: Optional[float],
    growth_score: Optional[float],
    macro_score: Optional[float],
) -> Tuple[float, str]:
    """
    Compute composite fundamental score and signal label.

    All component scores should be in [-1.0, +1.0] for valuation/macro,
    and [0.0, +1.0] for quality/growth (internally recentred to [-1, +1]
    before weighting so the composite is in the same range).

    Parameters
    ----------
    valuation_score : float | None  in [-1, +1]
    quality_score   : float | None  in [0, +1] — recentred to [-1, +1]
    growth_score    : float | None  in [0, +1] — recentred to [-1, +1]
    macro_score     : float | None  in [-1, +1]

    Returns
    -------
    (fundamental_score, fundamental_signal)
    """
    try:
        scores_weights: list[tuple[Optional[float], float]] = []

        # Valuation: already in [-1, +1]
        scores_weights.append((_resolve(valuation_score, 0.0), _W_VALUATION))

        # Quality: [0, 1] → recentre to [-1, +1]  i.e.  score*2 - 1
        q = _resolve(quality_score, 0.5)
        scores_weights.append((q * 2.0 - 1.0, _W_QUALITY))

        # Growth: [0, 1] → recentre to [-1, +1]
        g = _resolve(growth_score, 0.4)
        scores_weights.append((g * 2.0 - 1.0, _W_GROWTH))

        # Macro: already in [-1, +1]
        scores_weights.append((_resolve(macro_score, 0.0), _W_MACRO))

        # Weighted sum (all weights present and accounted for)
        composite = sum(s * w for s, w in scores_weights)
        composite = max(-1.0, min(1.0, composite))
        composite = round(composite, 4)

        signal = _label(composite)
        return composite, signal

    except Exception as exc:
        log.warning("classify_fundamental error: %s", exc)
        return 0.0, "NEUTRAL"


def _resolve(v: Optional[float], default: float) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _label(score: float) -> str:
    if score >= 0.50:
        return "STRONG_BUY"
    if score >= 0.20:
        return "BUY"
    if score > -0.20:
        return "NEUTRAL"
    if score > -0.50:
        return "SELL"
    return "STRONG_SELL"
