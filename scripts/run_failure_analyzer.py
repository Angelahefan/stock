#!/usr/bin/env python3
"""
scripts/run_failure_analyzer.py
─────────────────────────────────────────────────────────────────────────────
Macro learning loop — turn losses into actionable strategy fixes.

For each horizon (7d / 30d / 90d), reads all losing debates from
sys_agent_debate_log_full, clusters them by feature signature, and
writes the dominant failure patterns into datapai.failure_patterns
with an LLM-generated `suggested_action`.

CLUSTERING SIGNATURE (the dimensions we GROUP BY)
─────────────────────────────────────────────────
  direction        STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL
  conf_band        0.00-0.40 / 0.40-0.60 / 0.60-0.80 / 0.80-1.00
  thesis_empty     thesis IS NULL or LENGTH < 20    (broken-fallback marker)
  quality_tier     A / B / C / D / NULL
  regime           NULL or whatever stored
  any_gate_fired   true / false   (enriched from stock_synthesis gate_decisions)
  signals_aligned  true / false   (enriched from stock_synthesis)

Each unique combination becomes a candidate "pattern". We keep clusters
where n_observations >= MIN_CLUSTER (default 5) AND loss_rate >= 60%.

USAGE
    python3 scripts/run_failure_analyzer.py --horizon-days 30
    python3 scripts/run_failure_analyzer.py --horizon-days 30 --min-cluster 3 --dry-run

Designed for stock_failure_analyzer Airflow DAG (3 sequential tasks,
one per horizon, daily 06:30 UTC — runs AFTER stock_reflector at 06:00).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

LOG_DIR = Path("/var/log/datapai")
LOG_FILE = LOG_DIR / "failure_analyzer.log"

log = logging.getLogger("failure_analyzer")
log.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
ch = logging.StreamHandler()
ch.setFormatter(fmt)
log.addHandler(ch)
if LOG_DIR.is_dir():
    fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=10_000_000, backupCount=5)
    fh.setFormatter(fmt)
    log.addHandler(fh)


def _conf_band(c: Optional[float]) -> str:
    """Bucket confidence into bands so similar-confidence rows group."""
    if c is None:
        return "?"
    if c < 0.40: return "0.00-0.40"
    if c < 0.60: return "0.40-0.60"
    if c < 0.80: return "0.60-0.80"
    return "0.80-1.00"


def _any_gate_fired(gate_decisions: Any) -> bool:
    """gate_decisions is JSONB — look for any {fired: true} entry."""
    if not isinstance(gate_decisions, dict):
        if isinstance(gate_decisions, str):
            try:
                gate_decisions = json.loads(gate_decisions)
            except Exception:
                return False
        else:
            return False
    return any(
        isinstance(v, dict) and v.get("fired") is True
        for v in gate_decisions.values()
    )


def _signature_for_row(row: dict, horizon_days: int) -> Dict[str, Any]:
    """Build the cluster signature for one debate row.

    NOTE: conviction + signals_aligned + gate_decisions live on
    stock_synthesis, not sys_agent_debate_log. They're enriched from
    the synthesis-row join in main_async, then folded in here.
    """
    return {
        "horizon_days":    horizon_days,
        "direction":       row.get("direction"),
        "conf_band":       _conf_band(row.get("confidence")),
        "thesis_empty":    not (row.get("thesis") and len((row.get("thesis") or "").strip()) >= 20),
        "quality_tier":    row.get("quality_tier") or "NULL",
        "regime":          row.get("regime") or "NULL",
        "any_gate_fired":  _any_gate_fired(row.get("gate_decisions")),
        "signals_aligned": bool(row.get("signals_aligned")),
    }


def _signature_to_text(sig: Dict[str, Any]) -> str:
    """Human-readable form for UI + LLM input."""
    parts = [
        f"direction={sig['direction']}",
        f"confidence{sig['conf_band']}",
    ]
    if sig["thesis_empty"]:
        parts.append("thesis_empty (likely broken-fallback)")
    if sig["quality_tier"] != "NULL":
        parts.append(f"quality_tier={sig['quality_tier']}")
    if sig["regime"] != "NULL":
        parts.append(f"regime={sig['regime']}")
    if sig["any_gate_fired"]:
        parts.append("any_gate=FIRED")
    parts.append(f"signals_aligned={sig['signals_aligned']}")
    return " · ".join(parts)


def _llm_suggested_action(sig_text: str, n_obs: int, n_loss: int, avg_miss: float, examples: List[str]) -> str:
    """Ask Gemini to write a 2-3 sentence concrete remediation."""
    try:
        from agents.llm_client import RouterChatClient
        client = RouterChatClient()
        prompt = (
            "You are reviewing failure clusters from a stock-recommendation engine.\n\n"
            f"PATTERN: {sig_text}\n"
            f"OBSERVATIONS: {n_obs}\n"
            f"LOSSES: {n_loss}\n"
            f"LOSS RATE: {(n_loss/max(n_obs,1))*100:.0f}%\n"
            f"AVG ABSOLUTE RETURN MISSED: {avg_miss:.1f}%\n"
            f"EXAMPLE TICKERS: {', '.join(examples[:5])}\n\n"
            "Write a SHORT (2-3 sentences, ≤80 words) actionable remediation. "
            "Focus on:\n"
            "  1. What this pattern likely means about the engine's failure mode\n"
            "  2. A concrete code/config/threshold change to try\n"
            "If the pattern signature includes 'thesis_empty' it strongly suggests the synthesis "
            "fell to its hardcoded default (already fixed 2026-05-24) — say so.\n"
            "Output plain text. No preamble."
        )
        resp = client.chat(messages=[{"role": "user", "content": prompt}], temperature=0.2)
        if isinstance(resp, dict):
            return (resp.get("content") or "").strip()[:600]
        return str(resp or "").strip()[:600]
    except Exception as exc:
        log.warning("LLM suggested_action failed (%s) — using fallback heuristic", str(exc)[:120])
        if "thesis_empty" in sig_text:
            return (
                "This pattern matches the broken fallback HOLD/conf<0.4/LOW that fired pre-2026-05-24. "
                "Resolved by the AG2+thinkingBudget=0 fix. Mark RESOLVED unless new instances appear after May 24."
            )
        return f"Investigate manually. Pattern {sig_text} ({n_loss}/{n_obs} losses, avg miss {avg_miss:.1f}%)."


def _get_framework_conn():
    """Direct connection to framework_db (datapai_auth_db).

    Writing through the FDW foreign-table fails the same way the
    sys_agent_debate_log INSERT did (postgres_fdw sends NULL for the
    auto-increment pattern_id column). Migration 044 fixed that for
    debate_log via a split write/read FDW; for failure_patterns we
    sidestep entirely by connecting directly — the analyzer is a
    backend script, it doesn't need to use FDW.
    """
    import psycopg2
    return psycopg2.connect(
        host=os.environ.get("DATAPAI_FRAMEWORK_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DATAPAI_FRAMEWORK_DB_PORT", "5433")),
        user=os.environ.get("DATAPAI_FRAMEWORK_DB_USER", "postgres"),
        password=os.environ.get("DATAPAI_FRAMEWORK_DB_PASSWORD", "auth_root_2026"),
        dbname=os.environ.get("DATAPAI_FRAMEWORK_DB_NAME", "datapai_auth_db"),
        connect_timeout=5,
    )


async def main_async(horizon_days: int, min_cluster: int, min_loss_rate: float, dry_run: bool) -> int:
    """Mine + persist failure patterns for one horizon."""
    if horizon_days not in (7, 30, 90):
        raise ValueError(f"horizon_days must be 7, 30, or 90 (got {horizon_days})")

    from scripts.lib.db_helpers import get_conn
    import psycopg2.extras

    column_filter = {7: "was_correct_7d", 30: "was_correct_30d", 90: "was_correct_90d"}[horizon_days]
    ret_col       = {7: "actual_return_7d", 30: "actual_return_30d", 90: "actual_return_90d"}[horizon_days]

    log.info("=== Failure Analyzer · horizon=%dd · min_cluster=%d · min_loss_rate=%.2f ===",
             horizon_days, min_cluster, min_loss_rate)

    # ── 1. Load ALL graded debates at this horizon (both wins + losses) ────
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # NOTE: sys_agent_debate_log doesn't have conviction / signals_aligned /
            # gate_decisions columns — those live on stock_synthesis. We enrich
            # via a Python-side join below.
            cur.execute(
                f"""
                SELECT ticker, exchange, debate_date, direction,
                       confidence, thesis,
                       quality_tier, regime,
                       agent_scores, {ret_col} AS ret,
                       {column_filter} AS was_correct
                FROM datapai.sys_agent_debate_log_full
                WHERE {column_filter} IS NOT NULL
                  AND {ret_col} IS NOT NULL
                """
            )
            rows = list(cur.fetchall())

    log.info("Loaded %d graded debates at horizon=%dd", len(rows), horizon_days)
    if not rows:
        log.info("No graded debates — nothing to analyze yet")
        return 0

    # Cross-reference with stock_synthesis to pull conviction / signals_aligned /
    # gate_decisions (debate_log on framework_db, stock_synthesis on stock_db).
    # Best-effort: if synthesis is unreachable, defaults are sensible (no gate
    # fired, signals not aligned).
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT ticker, exchange, computed_at::date AS computed_date,
                           gate_decisions, signals_aligned
                    FROM datapai.stock_synthesis
                    """
                )
                synth = {
                    (r["ticker"], r["exchange"], r["computed_date"]): r
                    for r in cur.fetchall()
                }
        for r in rows:
            key = (r["ticker"], r["exchange"], r["debate_date"])
            ext = synth.get(key) or {}
            r["gate_decisions"]  = ext.get("gate_decisions") or {}
            r["signals_aligned"] = bool(ext.get("signals_aligned"))
    except Exception as exc:
        log.warning("Could not enrich with stock_synthesis: %s — proceeding without", str(exc)[:120])
        for r in rows:
            r.setdefault("gate_decisions", {})
            r.setdefault("signals_aligned", False)

    # ── 2. Cluster by signature ─────────────────────────────────────────────
    clusters: Dict[str, dict] = {}
    for row in rows:
        sig = _signature_for_row(row, horizon_days)
        sig_text = _signature_to_text(sig)
        c = clusters.setdefault(sig_text, {
            "signature": sig,
            "signature_text": sig_text,
            "n_obs": 0,
            "n_loss": 0,
            "loss_returns": [],
            "loss_tickers": [],
        })
        c["n_obs"] += 1
        if row["was_correct"] is False:
            c["n_loss"] += 1
            c["loss_returns"].append(abs(float(row["ret"] or 0)))
            c["loss_tickers"].append((row["ticker"], abs(float(row["ret"] or 0))))

    # ── 3. Filter to "interesting" clusters ────────────────────────────────
    promoted = []
    for sig_text, c in clusters.items():
        if c["n_obs"] < min_cluster:
            continue
        loss_rate = (c["n_loss"] / c["n_obs"]) * 100.0
        if loss_rate < min_loss_rate:
            continue
        avg_miss = (sum(c["loss_returns"]) / len(c["loss_returns"])) if c["loss_returns"] else 0.0
        # Top 5 worst tickers by abs return
        c["loss_tickers"].sort(key=lambda t: -t[1])
        examples = [t[0] for t in c["loss_tickers"][:5]]
        promoted.append({
            "signature": c["signature"],
            "signature_text": sig_text,
            "n_observations": c["n_obs"],
            "n_losses": c["n_loss"],
            "loss_rate": round(loss_rate, 2),
            "avg_return_missed": round(avg_miss, 2),
            "example_tickers": examples,
        })

    promoted.sort(key=lambda p: -(p["loss_rate"] * p["n_observations"]))
    log.info("Promoted %d patterns (n_obs>=%d, loss_rate>=%.0f%%) out of %d unique signatures",
             len(promoted), min_cluster, min_loss_rate, len(clusters))

    if not promoted:
        return 0

    # ── 4. Ask LLM to suggest action per cluster (best-effort) ─────────────
    for p in promoted[:20]:  # cap LLM calls per run
        p["suggested_action"] = _llm_suggested_action(
            p["signature_text"], p["n_observations"], p["n_losses"],
            p["avg_return_missed"], p["example_tickers"],
        )

    # ── 5. Persist (or dry-run) ────────────────────────────────────────────
    if dry_run:
        log.info("DRY RUN — would have written %d patterns", len(promoted))
        for p in promoted[:5]:
            log.info("  %s — %d/%d losses (%.1f%%) avg miss %.1f%% — %s",
                     p["signature_text"], p["n_losses"], p["n_observations"],
                     p["loss_rate"], p["avg_return_missed"],
                     (p.get("suggested_action") or "")[:120])
        return len(promoted)

    # Write directly to framework_db (NOT via FDW — see _get_framework_conn docstring)
    fwk_conn = _get_framework_conn()
    try:
        with fwk_conn:
            with fwk_conn.cursor() as cur:
                for p in promoted:
                    cur.execute(
                        """
                        INSERT INTO datapai.failure_patterns
                          (horizon_days, signature, signature_text,
                           n_observations, n_losses, loss_rate,
                           avg_return_missed, example_tickers, suggested_action, status)
                        VALUES (%s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, 'open')
                        """,
                        (
                            horizon_days,
                            json.dumps(p["signature"]),
                            p["signature_text"],
                            p["n_observations"],
                            p["n_losses"],
                            p["loss_rate"],
                            p["avg_return_missed"],
                            p["example_tickers"],
                            p.get("suggested_action"),
                        ),
                    )
    finally:
        fwk_conn.close()
    log.info("=== Failure Analyzer DONE · horizon=%dd · %d patterns written ===",
             horizon_days, len(promoted))
    return len(promoted)


def main():
    ap = argparse.ArgumentParser(description="Failure-pattern analyzer for the macro learning loop")
    ap.add_argument("--horizon-days", type=int, required=True, choices=(7, 30, 90))
    ap.add_argument("--min-cluster", type=int, default=5,
                    help="Skip clusters with fewer observations than this (default 5)")
    ap.add_argument("--min-loss-rate", type=float, default=40.0,
                    help="Skip clusters with loss rate below this percentage (default 40). "
                         "Equity HOLD calls naturally have ~40-50%% loss rate when stocks "
                         "move >10%% — that's still meaningful signal for the analyzer.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_DIR / ".env")
    except ImportError:
        pass
    n = asyncio.run(main_async(
        horizon_days=args.horizon_days,
        min_cluster=args.min_cluster,
        min_loss_rate=args.min_loss_rate,
        dry_run=args.dry_run,
    ))
    sys.exit(0 if n >= 0 else 1)


if __name__ == "__main__":
    main()
