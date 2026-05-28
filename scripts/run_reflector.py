#!/usr/bin/env python3
"""
scripts/run_reflector.py
─────────────────────────────────────────────────────────────────────────────
Reflector batch — graded post-trade reflection over past debates.

For each debate row in sys_agent_debate_log whose `was_correct_{horizon}d`
column is still NULL AND the debate is at least `horizon` days old:

  1. Pulls realised return at that horizon from the prices table
  2. Calls Reflector.reflect_on_debate(..., horizon_days=horizon)
     which:
       - Per persona (Bull/Bear/Risk/PM), asks Gemini to extract a 2-3
         sentence lesson tagged with `horizon:{N}d`
       - Writes lessons into sys_agent_memory
       - UPDATEs the debate row with was_correct_{horizon}d + lessons_extracted

Usage:
    python3 scripts/run_reflector.py --horizon-days 30
    python3 scripts/run_reflector.py --horizon-days 7
    python3 scripts/run_reflector.py --horizon-days 90 --min-age-days 90

Designed for Airflow stock_reflector DAG (3 sequential bash tasks, one per
horizon, daily at 06:00 UTC).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

# Configure logging
LOG_DIR = Path("/var/log/datapai")
LOG_FILE = LOG_DIR / "reflector.log"

log = logging.getLogger("reflector")
log.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
ch = logging.StreamHandler()
ch.setFormatter(fmt)
log.addHandler(ch)
if LOG_DIR.is_dir():
    import logging.handlers
    fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=10_000_000, backupCount=5)
    fh.setFormatter(fmt)
    log.addHandler(fh)


async def main_async(horizon_days: int, min_age_days: int) -> int:
    from agents.stock_synthesis.memory import AgentMemoryStore
    from agents.stock_synthesis.reflector import Reflector

    log.info("=== Reflector starting · horizon=%dd · min_age=%dd ===", horizon_days, min_age_days)
    store = AgentMemoryStore.from_env()
    store.load()
    log.info("Loaded agent memory: %s", store.stats())

    reflector = Reflector(store)
    total_memories = await reflector.reflect_pending(
        horizon_days=horizon_days, min_age_days=min_age_days
    )
    log.info("=== Reflector DONE · horizon=%dd · %d new memories ===", horizon_days, total_memories)
    return total_memories


def main():
    ap = argparse.ArgumentParser(description="Reflector multi-horizon batch")
    ap.add_argument("--horizon-days", type=int, required=True, choices=(7, 30, 90),
                    help="Horizon to grade against: 7, 30, or 90 days")
    ap.add_argument("--min-age-days", type=int, default=None,
                    help="Optional override; defaults to horizon-days (debates must be at least this old)")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_DIR / ".env")
    except ImportError:
        pass

    n = asyncio.run(main_async(
        horizon_days=args.horizon_days,
        min_age_days=args.min_age_days if args.min_age_days is not None else args.horizon_days,
    ))
    sys.exit(0 if n >= 0 else 1)


if __name__ == "__main__":
    main()
