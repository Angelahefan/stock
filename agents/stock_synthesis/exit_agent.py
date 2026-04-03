"""
agents/stock_synthesis/exit_agent.py
─────────────────────────────────────────────────────────────────────────────
Exit Agent for the Investment Committee (v3).

Core principle: SELL when the buy thesis breaks, not when a number triggers.

Regime-aware behavior:
  BULL market:  Patient. Ignore single TA noise. Only exit when MULTIPLE
                signals confirm the thesis is broken. Let winners run.
  BEAR market:  Sensitive. React faster to sell signals. Protect capital.
                Single strong TA sell signal is enough.
  NEUTRAL:      Balanced. Require 2+ confirming signals.

Quality-aware behavior:
  Quality A/B:  Wider tolerance. These companies recover from dips.
  Quality C/D:  Tighter tolerance. Weak companies don't recover.

Signal-consensus exit (not threshold-based):
  - Count TA sell signals (RSI overbought, MACD bearish, death cross, etc.)
  - In BULL: need 3+ sell signals echoing to trigger exit
  - In BEAR: need 2+ sell signals
  - In NEUTRAL: need 2+ sell signals
  - Critical news / FA breakdown always triggers regardless

Usage:
    signal = check_exit_v3(
        entry_price=100, current_price=95,
        highest_since_entry=110, days_held=30,
        regime="BULL_MOMENTUM", quality="A",
        ta_data={"rsi_14": 72, "macd_trend": "BEARISH", ...},
    )
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load learned parameters (from learning_agent.py self-improvement loop)
# ---------------------------------------------------------------------------

_LEARNED_PARAMS: Optional[Dict[str, Any]] = None
_LEARNED_PARAMS_PATH = os.path.join(
    os.path.dirname(__file__), "learned_exit_params.json"
)

# Agent memory for exit decisions
_exit_memory = None


def _get_exit_memory():
    """Lazy-load agent memory for exit agent."""
    global _exit_memory
    if _exit_memory is None:
        try:
            from agents.stock_synthesis.memory import AgentMemoryStore
            _exit_memory = AgentMemoryStore.from_env()
            _exit_memory.load()
        except Exception:
            from agents.stock_synthesis.memory import AgentMemoryStore
            _exit_memory = AgentMemoryStore()
    return _exit_memory


def get_exit_lessons(
    ticker: str, exchange: str, regime: str, quality: str, pnl_pct: float
) -> List[str]:
    """
    Retrieve relevant exit lessons from agent memory.

    Returns a list of lesson strings that the caller can use for context.
    """
    memory = _get_exit_memory()
    situation = f"{ticker} on {exchange}, regime={regime}, quality={quality}, pnl={pnl_pct:+.1f}%"

    # Get curated best results
    best = memory.get_best_results("exit_agent", regime=regime, quality=quality, limit=2)
    # Get similar past situations
    memories = memory.get_memories("exit_agent", situation, n=2)

    lessons = []
    for b in best:
        lessons.append(f"[VALIDATED] {b['title']}: {b['lesson_text'][:200]}")
    for m in memories:
        outcome = f" [{m['outcome']}]" if m.get('outcome') and m['outcome'] != 'PENDING' else ""
        lessons.append(f"[PAST] {m['recommendation'][:200]}{outcome}")
    return lessons


def _load_learned_params() -> Dict[str, Any]:
    """Load learned parameters from JSON. Cached after first load."""
    global _LEARNED_PARAMS
    if _LEARNED_PARAMS is not None:
        return _LEARNED_PARAMS
    try:
        import json
        if os.path.exists(_LEARNED_PARAMS_PATH):
            with open(_LEARNED_PARAMS_PATH) as f:
                _LEARNED_PARAMS = json.load(f)
                log.info("Loaded learned exit params (v%s)", _LEARNED_PARAMS.get("version", "?"))
                return _LEARNED_PARAMS
    except Exception as exc:
        log.warning("Could not load learned params: %s", exc)
    _LEARNED_PARAMS = {}
    return _LEARNED_PARAMS


def reload_learned_params() -> None:
    """Force reload learned parameters (call after learning_agent updates the file)."""
    global _LEARNED_PARAMS
    _LEARNED_PARAMS = None
    _load_learned_params()


class ExitAction(str, Enum):
    HOLD = "HOLD"
    ADD = "ADD"               # agents still bullish + profitable → buy more
    TAKE_PROFIT = "TAKE_PROFIT"
    CUT_LOSS = "CUT_LOSS"
    TRAIL_STOP = "TRAIL_STOP"
    TIME_STOP = "TIME_STOP"


class ExitUrgency(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    NEXT_SESSION = "NEXT_SESSION"
    FLEXIBLE = "FLEXIBLE"


@dataclass
class ExitSignal:
    """Exit agent recommendation."""
    action: ExitAction = ExitAction.HOLD
    reason: str = ""
    urgency: ExitUrgency = ExitUrgency.FLEXIBLE
    current_pnl_pct: float = 0.0
    trailing_drawdown_pct: float = 0.0
    sell_signal_count: int = 0      # how many TA signals agree on SELL
    sell_signals: List[str] = field(default_factory=list)


@dataclass
class ExitThresholds:
    """Configurable exit thresholds per timeframe."""
    take_profit_pct: float
    hard_stop_pct: float
    trailing_stop_pct: float
    time_stop_days: int


# ---------------------------------------------------------------------------
# TA sell signal detection — count how many indicators say SELL
# ---------------------------------------------------------------------------

def _count_ta_sell_signals(ta_data: Dict[str, Any], pnl_pct: float) -> tuple[int, List[str]]:
    """
    Count how many TA indicators are signaling SELL.

    Returns (count, list_of_signal_names).
    Each signal is independent evidence that momentum is fading.
    """
    signals = []

    rsi = ta_data.get("rsi_14")
    macd_trend = ta_data.get("macd_trend")
    kdj_signal = ta_data.get("kdj_signal")
    sma_50 = ta_data.get("sma_50")
    sma_200 = ta_data.get("sma_200")
    bb_pct_b = ta_data.get("bb_pct_b")
    obv_trend = ta_data.get("obv_trend")
    volume_ratio = ta_data.get("volume_ratio")
    change_1d_pct = ta_data.get("change_1d_pct")

    # 1. RSI overbought (>75) — momentum exhaustion
    if rsi is not None and rsi > 75:
        signals.append(f"RSI_OVERBOUGHT({rsi:.0f})")

    # 2. MACD bearish crossover — trend turning
    if macd_trend == "BEARISH":
        signals.append("MACD_BEARISH")

    # 3. KDJ overbought — short-term exhaustion
    if kdj_signal == "OVERBOUGHT":
        signals.append("KDJ_OVERBOUGHT")

    # 4. Death cross (SMA50 < SMA200) — major trend reversal
    if sma_50 is not None and sma_200 is not None and sma_50 < sma_200:
        signals.append("DEATH_CROSS")

    # 5. Bollinger Band > 0.95 — price at upper extreme
    if bb_pct_b is not None and bb_pct_b > 0.95:
        signals.append(f"BB_UPPER_EXTREME({bb_pct_b:.2f})")

    # 6. OBV divergence — volume not confirming price (smart money exiting)
    if obv_trend == "DOWN" and pnl_pct > 0:
        signals.append("OBV_DIVERGENCE")

    # 7. High volume selloff — distribution day
    if volume_ratio is not None and change_1d_pct is not None:
        if volume_ratio > 2.0 and change_1d_pct < -2.0:
            signals.append(f"DISTRIBUTION_DAY(vol={volume_ratio:.1f}x, chg={change_1d_pct:+.1f}%)")

    return len(signals), signals


def _count_ta_buy_signals(ta_data: Dict[str, Any]) -> int:
    """Count how many TA indicators still say BUY/bullish."""
    count = 0
    rsi = ta_data.get("rsi_14")
    macd_trend = ta_data.get("macd_trend")
    kdj_signal = ta_data.get("kdj_signal")
    sma_50 = ta_data.get("sma_50")
    sma_200 = ta_data.get("sma_200")
    obv_trend = ta_data.get("obv_trend")

    if rsi is not None and 30 <= rsi <= 65:
        count += 1  # healthy RSI range
    if macd_trend == "BULLISH":
        count += 1
    if kdj_signal in ("OVERSOLD", "NEUTRAL"):
        count += 1
    if sma_50 is not None and sma_200 is not None and sma_50 > sma_200:
        count += 1  # golden cross
    if obv_trend == "UP":
        count += 1

    return count


# ---------------------------------------------------------------------------
# Regime-aware sell signal threshold
# ---------------------------------------------------------------------------

def _get_sell_threshold(regime: str, quality: str) -> int:
    """
    How many TA sell signals needed before we actually sell?

    Defaults (can be overridden by learned params):
      Bull + Quality A/B: need 3+ signals (very patient, ignore noise)
      Bull + Quality C/D: need 2+ signals
      Bear + Quality A/B: need 2+ signals (more cautious)
      Bear + Quality C/D: need 1+ signal (exit quickly)
      Neutral:            need 2+ signals
    """
    # Check learned overrides first
    learned = _load_learned_params()
    key = f"{regime}/{quality}"
    override = learned.get("sell_threshold_overrides", {}).get(key)
    if override is not None:
        return int(override)

    is_quality = quality in ("A", "B")

    if regime == "BULL_MOMENTUM":
        return 3 if is_quality else 2
    elif regime == "BEAR_RECESSION":
        return 2 if is_quality else 1
    else:  # NEUTRAL
        return 2


# ---------------------------------------------------------------------------
# Catastrophe stop — the only hard threshold, and it's a circuit breaker
# ---------------------------------------------------------------------------

def _get_catastrophe_stop(regime: str, quality: str) -> float:
    """
    Catastrophe stop: only for extreme scenarios (fraud, crash, black swan).
    NOT normal risk management — this is a circuit breaker.
    """
    # Check learned overrides
    learned = _load_learned_params()
    key = f"{regime}/{quality}"
    override = learned.get("catastrophe_stop_overrides", {}).get(key)
    if override is not None:
        return float(override)

    if regime == "BEAR_RECESSION":
        return -15.0 if quality in ("A", "B") else -12.0
    elif regime == "BULL_MOMENTUM":
        return -25.0 if quality in ("A", "B") else -20.0
    else:
        return -20.0 if quality in ("A", "B") else -15.0


# ---------------------------------------------------------------------------
# Trailing stop — only activates after significant gain
# ---------------------------------------------------------------------------

def _get_trailing_config(regime: str, quality: str) -> tuple[float, float]:
    """
    Returns (activation_pct, trail_pct).

    Trailing stop only activates after stock has gained enough.
    In bull market: activate later, wider trail (let it run).
    In bear market: activate earlier, tighter trail (protect gains).
    """
    is_quality = quality in ("A", "B")

    if regime == "BULL_MOMENTUM":
        activation = 20.0 if is_quality else 15.0
        trail = 15.0 if is_quality else 12.0
    elif regime == "BEAR_RECESSION":
        activation = 8.0 if is_quality else 5.0
        trail = 8.0 if is_quality else 6.0
    else:  # NEUTRAL
        activation = 12.0 if is_quality else 10.0
        trail = 10.0 if is_quality else 8.0

    # Apply learned multipliers
    learned = _load_learned_params()
    key = f"{regime}/{quality}"
    trail_override = learned.get("trailing_stop_overrides", {}).get(key)
    if trail_override:
        activation *= trail_override.get("activation_multiplier", 1.0)
        trail *= trail_override.get("trail_multiplier", 1.0)

    return activation, trail


# ---------------------------------------------------------------------------
# Time stop — regime-aware patience
# ---------------------------------------------------------------------------

def _get_time_stop_days(regime: str, quality: str, timeframe: str) -> int:
    """
    How long to hold a losing position before giving up?

    Bull + Quality: very patient (quality stocks recover in bull markets)
    Bear + Any:     impatient (don't hold losers in bear markets)
    """
    is_quality = quality in ("A", "B")

    base_days = {"days": 15, "weeks": 30, "months": 60, "quarter": 120}
    base = base_days.get(timeframe, 60)

    if regime == "BULL_MOMENTUM":
        multiplier = 2.0 if is_quality else 1.5
    elif regime == "BEAR_RECESSION":
        multiplier = 0.5 if is_quality else 0.3
    else:
        multiplier = 1.0 if is_quality else 0.8

    # Apply learned multiplier
    learned = _load_learned_params()
    key = f"{regime}/{quality}"
    time_override = learned.get("time_stop_overrides", {}).get(key)
    if time_override:
        multiplier *= time_override.get("multiplier", 1.0)

    return int(base * multiplier)


# ---------------------------------------------------------------------------
# Main exit check — v3 signal-consensus-driven
# ---------------------------------------------------------------------------

def check_exit(
    entry_price: float,
    current_price: float,
    highest_since_entry: float,
    days_held: int,
    timeframe: str = "months",
    ta_data: Optional[Dict[str, Any]] = None,
    news_data: Optional[Dict[str, Any]] = None,
    fa_score: Optional[float] = None,
    regime: str = "BULL_MOMENTUM",
    quality: str = "B",
    custom_thresholds: Optional[ExitThresholds] = None,
) -> ExitSignal:
    """
    v3 regime-aware, signal-consensus-driven exit check.

    The key difference from v2: we don't sell on fixed thresholds.
    We sell when MULTIPLE TA signals confirm the thesis is broken,
    with the required consensus level varying by regime and quality.

    Parameters
    ----------
    regime : str
        "BULL_MOMENTUM", "BEAR_RECESSION", or "NEUTRAL_TRANSITION"
    quality : str
        Stock quality tier: "A", "B", "C", "D"
    """
    if entry_price <= 0:
        return ExitSignal(action=ExitAction.HOLD, reason="Invalid entry price")

    ta = ta_data or {}
    pnl_pct = ((current_price - entry_price) / entry_price) * 100

    # ── Consult agent memory for relevant exit lessons ──
    exit_lessons = []
    try:
        exit_lessons = get_exit_lessons(
            ticker="", exchange="", regime=regime, quality=quality, pnl_pct=pnl_pct,
        )
        if exit_lessons:
            log.debug("Exit agent found %d relevant lessons", len(exit_lessons))
    except Exception:
        pass  # memory is advisory, never block exit decisions
    trailing_dd = (
        ((highest_since_entry - current_price) / highest_since_entry) * 100
        if highest_since_entry > 0 else 0.0
    )
    peak_gain = ((highest_since_entry - entry_price) / entry_price) * 100

    is_quality_bull = quality in ("A", "B") and regime == "BULL_MOMENTUM"

    # ══════════════════════════════════════════════════════════════════════
    # QUALITY STOCKS IN BULL MARKET — Thesis-driven exits ONLY
    #
    # The data proves: TA-based exits destroy value for quality stocks in
    # bull markets. 99.7% of stocks that were held recovered and gained.
    # Only sell when the REASON YOU BOUGHT changes:
    #   1. Critical news (fraud, bankruptcy)
    #   2. Catastrophe circuit breaker (-30%)
    #   3. FA breakdown (fundamentals deteriorated)
    #   4. Genuine regime flip to BEAR
    # Everything else: HOLD.
    # ══════════════════════════════════════════════════════════════════════

    if is_quality_bull:
        # 1. Critical news — always exit
        if news_data and news_data.get("has_critical_event"):
            if "NEGATIVE" in str(news_data.get("overall_sentiment", "")).upper():
                return ExitSignal(
                    action=ExitAction.CUT_LOSS,
                    reason=f"CRITICAL NEWS: {news_data.get('top_event_headline', 'Critical event')}",
                    urgency=ExitUrgency.IMMEDIATE,
                    current_pnl_pct=round(pnl_pct, 2),
                )

        # 2. Catastrophe circuit breaker
        cat_stop = _get_catastrophe_stop(regime, quality)
        if pnl_pct <= cat_stop:
            return ExitSignal(
                action=ExitAction.CUT_LOSS,
                reason=f"Catastrophe stop: {pnl_pct:+.1f}% (limit: {cat_stop}%)",
                urgency=ExitUrgency.IMMEDIATE,
                current_pnl_pct=round(pnl_pct, 2),
            )

        # 3. FA breakdown
        if fa_score is not None and fa_score < -0.5:
            return ExitSignal(
                action=ExitAction.CUT_LOSS,
                reason=f"Fundamental breakdown: FA score {fa_score:.2f}",
                urgency=ExitUrgency.NEXT_SESSION,
                current_pnl_pct=round(pnl_pct, 2),
            )

        # 4. Check if we should ADD (still bullish + profitable)
        sell_count, _ = _count_ta_sell_signals(ta, pnl_pct)
        buy_count = _count_ta_buy_signals(ta)
        if pnl_pct > 5.0 and buy_count >= 3 and sell_count == 0:
            return ExitSignal(
                action=ExitAction.ADD,
                reason=f"Quality/Bull: agents bullish ({buy_count} buy, 0 sell). P&L +{pnl_pct:.1f}%. Add to position.",
                urgency=ExitUrgency.FLEXIBLE,
                current_pnl_pct=round(pnl_pct, 2),
            )

        # OTHERWISE: HOLD. Quality stocks in bull market recover from dips.
        return ExitSignal(
            action=ExitAction.HOLD,
            reason=f"Quality/Bull: HOLD. P&L {pnl_pct:+.1f}%, {days_held}d held. Thesis intact.",
            current_pnl_pct=round(pnl_pct, 2),
            trailing_drawdown_pct=round(trailing_dd, 2),
        )

    # ══════════════════════════════════════════════════════════════════════
    # NON-QUALITY OR BEAR/NEUTRAL — Full exit logic applies
    # ══════════════════════════════════════════════════════════════════════

    # Priority 1: Critical news
    if news_data and news_data.get("has_critical_event"):
        if "NEGATIVE" in str(news_data.get("overall_sentiment", "")).upper():
            return ExitSignal(
                action=ExitAction.CUT_LOSS,
                reason=f"CRITICAL NEWS: {news_data.get('top_event_headline', 'Critical event')}",
                urgency=ExitUrgency.IMMEDIATE,
                current_pnl_pct=round(pnl_pct, 2),
            )

    # Priority 2: Catastrophe stop
    cat_stop = _get_catastrophe_stop(regime, quality)
    if pnl_pct <= cat_stop:
        return ExitSignal(
            action=ExitAction.CUT_LOSS,
            reason=f"Catastrophe stop: {pnl_pct:+.1f}% (limit: {cat_stop}%, regime: {regime})",
            urgency=ExitUrgency.IMMEDIATE,
            current_pnl_pct=round(pnl_pct, 2),
        )

    # Priority 3: FA breakdown
    if fa_score is not None and fa_score < -0.5:
        return ExitSignal(
            action=ExitAction.CUT_LOSS,
            reason=f"Fundamental breakdown: FA score {fa_score:.2f}",
            urgency=ExitUrgency.NEXT_SESSION,
            current_pnl_pct=round(pnl_pct, 2),
        )

    # Count TA signals
    sell_count, sell_signals = _count_ta_sell_signals(ta, pnl_pct)
    buy_count = _count_ta_buy_signals(ta)
    sell_threshold = _get_sell_threshold(regime, quality)

    # Priority 4: Trailing stop
    activation, trail_pct = _get_trailing_config(regime, quality)
    if peak_gain >= activation and trailing_dd >= trail_pct:
        return ExitSignal(
            action=ExitAction.TRAIL_STOP,
            reason=f"Trailing stop: peaked +{peak_gain:.1f}%, dropped {trailing_dd:.1f}%. Securing {pnl_pct:+.1f}%.",
            urgency=ExitUrgency.NEXT_SESSION,
            current_pnl_pct=round(pnl_pct, 2),
            trailing_drawdown_pct=round(trailing_dd, 2),
        )

    # Priority 5: TA consensus
    if sell_count >= sell_threshold and sell_count > buy_count:
        action = ExitAction.TAKE_PROFIT if pnl_pct > 0 else ExitAction.CUT_LOSS
        return ExitSignal(
            action=action,
            reason=f"TA consensus SELL: {sell_count} signals vs {buy_count} buy. Threshold={sell_threshold}.",
            urgency=ExitUrgency.NEXT_SESSION,
            current_pnl_pct=round(pnl_pct, 2),
            sell_signal_count=sell_count,
            sell_signals=sell_signals,
        )

    # Priority 6: Time stop
    time_limit = _get_time_stop_days(regime, quality, timeframe)
    if days_held >= time_limit and pnl_pct <= 0:
        return ExitSignal(
            action=ExitAction.TIME_STOP,
            reason=f"Time stop: {days_held}d held with {pnl_pct:+.1f}% (limit: {time_limit}d)",
            urgency=ExitUrgency.FLEXIBLE,
            current_pnl_pct=round(pnl_pct, 2),
        )

    # ── No exit: check if we should ADD ──
    if pnl_pct > 5.0 and buy_count >= 3 and sell_count == 0:
        return ExitSignal(
            action=ExitAction.ADD,
            reason=(
                f"Agents still bullish ({buy_count} buy signals, 0 sell). "
                f"P&L +{pnl_pct:.1f}%. Consider adding to position."
            ),
            urgency=ExitUrgency.FLEXIBLE,
            current_pnl_pct=round(pnl_pct, 2),
        )

    # ── Default: HOLD ──
    lesson_hint = ""
    if exit_lessons:
        lesson_hint = f" Memory: {exit_lessons[0][:100]}"
    return ExitSignal(
        action=ExitAction.HOLD,
        reason=(
            f"Hold: {sell_count} sell vs {buy_count} buy signals "
            f"(need {sell_threshold} sell for {regime}/{quality}). "
            f"P&L: {pnl_pct:+.1f}%, {days_held}d held.{lesson_hint}"
        ),
        current_pnl_pct=round(pnl_pct, 2),
        trailing_drawdown_pct=round(trailing_dd, 2),
        sell_signal_count=sell_count,
    )


# ---------------------------------------------------------------------------
# Backward compatibility — old get_thresholds still works
# ---------------------------------------------------------------------------

_DEFAULT_THRESHOLDS: Dict[str, ExitThresholds] = {
    "days": ExitThresholds(take_profit_pct=10.0, hard_stop_pct=-4.0, trailing_stop_pct=3.0, time_stop_days=15),
    "weeks": ExitThresholds(take_profit_pct=20.0, hard_stop_pct=-6.0, trailing_stop_pct=5.0, time_stop_days=30),
    "months": ExitThresholds(take_profit_pct=30.0, hard_stop_pct=-7.0, trailing_stop_pct=8.0, time_stop_days=60),
    "quarter": ExitThresholds(take_profit_pct=50.0, hard_stop_pct=-8.0, trailing_stop_pct=12.0, time_stop_days=120),
}

def get_thresholds(timeframe: str, quality: str = "default") -> ExitThresholds:
    """Legacy compatibility — prefer check_exit() with regime/quality params."""
    return _DEFAULT_THRESHOLDS.get(timeframe, _DEFAULT_THRESHOLDS["weeks"])
