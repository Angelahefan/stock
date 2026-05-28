#!/usr/bin/env python3
"""
scripts/run_synthesis_health.py
─────────────────────────────────────────────────────────────────────────────
Nightly health monitor for the synthesis pipeline. Runs at 23:00 UTC,
one hour after stock_synthesis_us (22:00 UTC). Reads tonight's batch,
computes 6 metrics, alerts on threshold breaches, and persists a row
into datapai.synthesis_health_runs for trend analysis.

If we'd had this in March, we'd have caught the broken-fallback bug
within 24h instead of 7 weeks.

METRICS + THRESHOLDS (any single breach trips overall_status to RED)
────────────────────────────────────────────────────────────────────
  pct_low_conviction   > 50%      → engine likely defaulting to HOLD/0.3/LOW
  distinct_directions  < 3        → engine likely emitting only one value
  pct_empty_thesis     > 20%      → PM JSON parse likely broken
  pct_broken_fallback  > 30%      → broken-fallback signature dominating
  pct_fallback_path    > 30%      → AG2 path failing → single-LLM fallback
  hit_rate_30d         drops > 10pp WoW → quality regression

USAGE
    python3 scripts/run_synthesis_health.py
    python3 scripts/run_synthesis_health.py --dry-run   # don't write row
    python3 scripts/run_synthesis_health.py --window-hours 48   # custom cohort
"""
from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

LOG_DIR = Path("/var/log/datapai")
LOG_FILE = LOG_DIR / "synthesis_health.log"

log = logging.getLogger("synthesis_health")
log.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
ch = logging.StreamHandler()
ch.setFormatter(fmt)
log.addHandler(ch)
if LOG_DIR.is_dir():
    fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=10_000_000, backupCount=5)
    fh.setFormatter(fmt)
    log.addHandler(fh)


# ── Thresholds (tune in production) ────────────────────────────────────────
THRESHOLDS = {
    "pct_low_conviction":   50.0,   # > → alert
    "distinct_directions":   3,      # < → alert
    "pct_empty_thesis":     20.0,
    "pct_broken_fallback":  30.0,
    "pct_fallback_path":    30.0,
    "hit_rate_30d_drop_pp": 10.0,    # week-over-week
}


def _pct(num: int, denom: int) -> float:
    return round((num / denom) * 100.0, 2) if denom > 0 else 0.0


def main(window_hours: int, dry_run: bool) -> int:
    """Return 0 = green, 1 = yellow (warn), 2 = red (page someone)."""
    from scripts.lib.db_helpers import get_conn
    import psycopg2.extras

    log.info("=== Synthesis Health · cohort=last_%dh · dry_run=%s ===", window_hours, dry_run)

    cohort_window = f"last_{window_hours}h"

    # ── Load cohort ─────────────────────────────────────────────────────────
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT direction, confidence, conviction, thesis,
                       signals_aligned, model_used, computed_at
                FROM datapai.stock_synthesis
                WHERE computed_at >= NOW() - INTERVAL '{window_hours} hours'
                """
            )
            rows = list(cur.fetchall())

    n = len(rows)
    log.info("Loaded %d rows in cohort", n)

    if n == 0:
        log.warning("Cohort is empty — DAGs might not have run, or window too small")
        # This is itself an alert condition
        return _persist_and_decide(
            run_date=date.today(),
            cohort_window=cohort_window,
            cohort_row_count=0,
            metrics={"n_rows": 0},
            alerts=["empty_cohort: synthesis produced 0 rows in last_%dh" % window_hours],
            dry_run=dry_run,
        )

    # ── Metrics ─────────────────────────────────────────────────────────────
    n_low_conv     = sum(1 for r in rows if (r["conviction"] or "").upper() == "LOW")
    n_empty_thesis = sum(1 for r in rows if not (r["thesis"] or "").strip() or len((r["thesis"] or "").strip()) < 50)
    n_broken_fb    = sum(
        1 for r in rows
        if (r["direction"] or "").upper() == "HOLD"
        and (r["confidence"] is not None and float(r["confidence"]) < 0.5)
        and not r.get("signals_aligned")
    )
    n_fallback_path = sum(1 for r in rows if r["model_used"] and "fallback" in (r["model_used"] or "").lower())

    distinct_dirs = len({(r["direction"] or "").upper() for r in rows if r["direction"]})

    metrics: Dict[str, Any] = {
        "n_rows": n,
        "n_low_conviction": n_low_conv,
        "n_empty_thesis": n_empty_thesis,
        "n_broken_fallback": n_broken_fb,
        "n_fallback_path": n_fallback_path,
        "distinct_directions": distinct_dirs,
        "pct_low_conviction":  _pct(n_low_conv,     n),
        "pct_empty_thesis":    _pct(n_empty_thesis, n),
        "pct_broken_fallback": _pct(n_broken_fb,    n),
        "pct_fallback_path":   _pct(n_fallback_path, n),
    }

    # ── Hit-rate trend (30d window) ─────────────────────────────────────────
    # Read latest hit rate + last-week's hit rate from sys_agent_debate_log_full
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      COUNT(*) FILTER (WHERE was_correct_30d = TRUE)::float /
                      NULLIF(COUNT(*) FILTER (WHERE was_correct_30d IS NOT NULL), 0) AS hit_rate_now
                    FROM datapai.sys_agent_debate_log_full
                    WHERE debate_date >= CURRENT_DATE - INTERVAL '30 days'
                    """
                )
                r1 = cur.fetchone()
                cur.execute(
                    """
                    SELECT
                      COUNT(*) FILTER (WHERE was_correct_30d = TRUE)::float /
                      NULLIF(COUNT(*) FILTER (WHERE was_correct_30d IS NOT NULL), 0) AS hit_rate_lastweek
                    FROM datapai.sys_agent_debate_log_full
                    WHERE debate_date >= CURRENT_DATE - INTERVAL '37 days'
                      AND debate_date <  CURRENT_DATE - INTERVAL '7 days'
                    """
                )
                r2 = cur.fetchone()
                hr_now      = (r1[0] or 0) * 100.0 if r1 and r1[0] is not None else None
                hr_lastweek = (r2[0] or 0) * 100.0 if r2 and r2[0] is not None else None
                metrics["hit_rate_30d"]          = round(hr_now, 2) if hr_now is not None else None
                metrics["hit_rate_30d_lastweek"] = round(hr_lastweek, 2) if hr_lastweek is not None else None
                metrics["hit_rate_drop_pp"] = (
                    round(hr_lastweek - hr_now, 2)
                    if hr_now is not None and hr_lastweek is not None else None
                )
    except Exception as exc:
        log.warning("hit-rate trend lookup failed: %s", str(exc)[:120])

    # ── Threshold checks → alerts list ──────────────────────────────────────
    alerts: List[str] = []
    if metrics["pct_low_conviction"] > THRESHOLDS["pct_low_conviction"]:
        alerts.append(f"pct_low_conviction={metrics['pct_low_conviction']}% > {THRESHOLDS['pct_low_conviction']}% — engine likely defaulting")
    if metrics["distinct_directions"] < THRESHOLDS["distinct_directions"]:
        alerts.append(f"distinct_directions={metrics['distinct_directions']} < {THRESHOLDS['distinct_directions']} — engine likely emitting one value")
    if metrics["pct_empty_thesis"] > THRESHOLDS["pct_empty_thesis"]:
        alerts.append(f"pct_empty_thesis={metrics['pct_empty_thesis']}% > {THRESHOLDS['pct_empty_thesis']}% — PM JSON parse likely broken")
    if metrics["pct_broken_fallback"] > THRESHOLDS["pct_broken_fallback"]:
        alerts.append(f"pct_broken_fallback={metrics['pct_broken_fallback']}% > {THRESHOLDS['pct_broken_fallback']}% — broken-fallback signature dominant")
    if metrics["pct_fallback_path"] > THRESHOLDS["pct_fallback_path"]:
        alerts.append(f"pct_fallback_path={metrics['pct_fallback_path']}% > {THRESHOLDS['pct_fallback_path']}% — AG2 path failing")
    drop = metrics.get("hit_rate_drop_pp")
    if drop is not None and drop > THRESHOLDS["hit_rate_30d_drop_pp"]:
        alerts.append(f"hit_rate_drop_pp={drop:.1f} > {THRESHOLDS['hit_rate_30d_drop_pp']} — quality regression vs last week")

    return _persist_and_decide(
        run_date=date.today(),
        cohort_window=cohort_window,
        cohort_row_count=n,
        metrics=metrics,
        alerts=alerts,
        dry_run=dry_run,
    )


def _persist_and_decide(
    run_date: date,
    cohort_window: str,
    cohort_row_count: int,
    metrics: Dict[str, Any],
    alerts: List[str],
    dry_run: bool,
) -> int:
    """Write the row, log the verdict, return exit code."""
    status = "red" if alerts else "green"
    log.info("Metrics: %s", json.dumps(metrics, default=str))
    if alerts:
        log.error("=" * 70)
        log.error("HEALTH CHECK FAILED — %d alerts", len(alerts))
        for a in alerts:
            log.error("  ⚠  %s", a)
        log.error("=" * 70)
        log.error("If this fires for >2 consecutive nights, INVESTIGATE the synthesis pipeline.")
    else:
        log.info("HEALTH CHECK GREEN — all thresholds passed")

    if not dry_run:
        try:
            from scripts.lib.db_helpers import get_conn
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO datapai.synthesis_health_runs
                          (run_date, cohort_window, cohort_row_count,
                           pct_low_conviction, distinct_directions,
                           pct_empty_thesis, pct_broken_fallback,
                           pct_fallback_path, hit_rate_30d,
                           alerts_fired, overall_status, metrics_detail)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            run_date, cohort_window, cohort_row_count,
                            metrics.get("pct_low_conviction"),
                            metrics.get("distinct_directions"),
                            metrics.get("pct_empty_thesis"),
                            metrics.get("pct_broken_fallback"),
                            metrics.get("pct_fallback_path"),
                            metrics.get("hit_rate_30d"),
                            alerts, status,
                            json.dumps(metrics, default=str),
                        ),
                    )
                conn.commit()
            log.info("Persisted to synthesis_health_runs")
        except Exception as exc:
            log.error("Failed to persist health row: %s", str(exc)[:200])

    return 2 if alerts else 0


def cli():
    ap = argparse.ArgumentParser(description="Nightly synthesis-pipeline health monitor")
    ap.add_argument("--window-hours", type=int, default=24,
                    help="Cohort window (hours) of recent stock_synthesis rows (default 24)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_DIR / ".env")
    except ImportError:
        pass
    sys.exit(main(window_hours=args.window_hours, dry_run=args.dry_run))


if __name__ == "__main__":
    cli()
