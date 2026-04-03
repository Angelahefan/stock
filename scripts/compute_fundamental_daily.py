#!/usr/bin/env python3
"""
scripts/compute_fundamental_daily.py
======================================
Nightly batch job: run fundamental analysis pipeline for all tracked tickers
on a given exchange and persist results to datapai.fundamental_snapshot
and datapai.fundamental_history.

Usage
-----
  python3 scripts/compute_fundamental_daily.py --exchange US
  python3 scripts/compute_fundamental_daily.py --exchange ASX
  python3 scripts/compute_fundamental_daily.py --exchange US --tickers AAPL,MSFT,NVDA
  python3 scripts/compute_fundamental_daily.py --exchange US --dry-run
  python3 scripts/compute_fundamental_daily.py --exchange US --full-refresh

Options
-------
  --exchange      US or ASX (required)
  --tickers       comma-separated override; default = all from datapai.prices
  --dry-run       skip DB writes; log scores only
  --full-refresh  recompute all tickers regardless of computed_at recency

Logging
-------
  Console + /var/log/datapai/compute_fundamental_daily.log (rotating, 10 MB x 5)
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

# ── Ensure project root is on sys.path ────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

# ── Logging setup ─────────────────────────────────────────────────────────────
LOG_DIR = Path("/var/log/datapai")
LOG_FILE = LOG_DIR / "compute_fundamental_daily.log"
FALLBACK_LOG_FILE = SCRIPT_DIR / "logs" / "compute_fundamental_daily.log"

_HANDLERS: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=10_485_760, backupCount=5)
    _HANDLERS.append(_fh)
except PermissionError:
    FALLBACK_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _fh = logging.handlers.RotatingFileHandler(
        FALLBACK_LOG_FILE, maxBytes=10_485_760, backupCount=5
    )
    _HANDLERS.append(_fh)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=_HANDLERS,
)
log = logging.getLogger("compute_fundamental_daily")

# ── Recency threshold: skip if computed < N hours ago (incremental mode) ─────
_RECENCY_HOURS = 20


# ---------------------------------------------------------------------------
# Ticker universe
# ---------------------------------------------------------------------------

def _get_tickers(exchange: str, override: Optional[List[str]] = None) -> List[str]:
    """Return list of tickers to process."""
    if override:
        return [t.strip().upper() for t in override if t.strip()]

    try:
        from scripts.lib.ticker_loader import load_monitored_tickers
        tickers = load_monitored_tickers(exchange=exchange)
        log.info("loaded %d tickers for exchange=%s from datapai.prices", len(tickers), exchange)
        return tickers
    except Exception as exc:
        log.warning("could not load ticker universe: %s — falling back to empty list", exc)
        return []


def _should_skip(ticker: str, exchange: str, full_refresh: bool) -> bool:
    """Return True if the ticker was computed recently and full_refresh is False."""
    if full_refresh:
        return False
    try:
        from scripts.lib.fundamental_helpers import get_fundamental_snapshot
        snap = get_fundamental_snapshot(ticker, exchange)
        if snap and snap.get("computed_at"):
            age = datetime.utcnow() - snap["computed_at"].replace(tzinfo=None)
            if age < timedelta(hours=_RECENCY_HOURS):
                return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run(
    exchange: str,
    tickers: Optional[List[str]] = None,
    dry_run: bool = False,
    full_refresh: bool = False,
) -> dict:
    """
    Run fundamental pipeline for all tickers on the given exchange.

    Returns summary stats dict.
    """
    from agents.fundamental.fundamental_pipeline import run_fundamental_pipeline

    # Initialise LLM clients once
    llm = None
    google_llm = None
    try:
        from agents.llm_client import RouterChatClient
        llm = RouterChatClient()
        log.info("RouterChatClient initialised (LLM_MODE=%s)", os.environ.get("LLM_MODE", "paid"))
    except Exception as exc:
        log.warning("RouterChatClient unavailable — summaries will be skipped: %s", exc)

    try:
        from agents.llm_client import GoogleChatClient
        google_llm = GoogleChatClient()
        log.info("GoogleChatClient initialised (grounding enabled)")
    except Exception as exc:
        log.warning("GoogleChatClient unavailable — macro/analyst steps will be skipped: %s", exc)

    ticker_list = _get_tickers(exchange, override=tickers)
    if not ticker_list:
        log.error("no tickers to process for exchange=%s", exchange)
        return {"processed": 0, "skipped": 0, "errors": 0}

    total   = len(ticker_list)
    processed = 0
    skipped   = 0
    errors    = 0
    start_ts  = time.time()

    log.info(
        "=== compute_fundamental_daily START | exchange=%s | tickers=%d | dry_run=%s ===",
        exchange, total, dry_run,
    )

    for i, ticker in enumerate(ticker_list, 1):
        if _should_skip(ticker, exchange, full_refresh):
            log.debug("[%d/%d] %s skipped (computed recently)", i, total, ticker)
            skipped += 1
            continue

        t0 = time.time()
        try:
            result = run_fundamental_pipeline(
                ticker=ticker,
                exchange=exchange,
                dry_run=dry_run,
                llm=llm,
                google_llm=google_llm,
            )
            elapsed = time.time() - t0
            processed += 1

            score_str = (
                f"score={result.fundamental_score:.3f} signal={result.fundamental_signal}"
                if result.fundamental_score is not None
                else "score=N/A"
            )
            err_str = f" ERRORS={result.errors}" if result.errors else ""
            log.info(
                "[%d/%d] %-10s  %s  val=%.2f qual=%.2f grow=%.2f macro=%.2f  %.1fs%s",
                i, total, ticker, score_str,
                result.valuation_score or 0.0,
                result.quality_score or 0.0,
                result.growth_score or 0.0,
                result.macro_score or 0.0,
                elapsed, err_str,
            )
            if result.errors:
                errors += 1

        except Exception as exc:
            elapsed = time.time() - t0
            log.error("[%d/%d] %s FAILED in %.1fs: %s", i, total, ticker, elapsed, exc)
            errors += 1

        # Polite delay to avoid hammering yfinance
        time.sleep(0.5)

    total_elapsed = time.time() - start_ts
    stats = {
        "exchange": exchange,
        "total": total,
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
        "elapsed_s": round(total_elapsed, 1),
        "dry_run": dry_run,
    }
    log.info(
        "=== compute_fundamental_daily DONE | %s | processed=%d skipped=%d errors=%d | %.0fs ===",
        exchange, processed, skipped, errors, total_elapsed,
    )
    return stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute fundamental analysis for all tickers on an exchange",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--exchange", required=True,
        help="Exchange to process (US or ASX)",
    )
    parser.add_argument(
        "--tickers",
        help="Comma-separated ticker override. Default: all from datapai.prices",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip DB writes; log scores only",
    )
    parser.add_argument(
        "--full-refresh", action="store_true",
        help="Recompute all tickers regardless of last computed_at",
    )

    args = parser.parse_args()
    ticker_list = [t.strip() for t in args.tickers.split(",")] if args.tickers else None

    stats = run(
        exchange=args.exchange,
        tickers=ticker_list,
        dry_run=args.dry_run,
        full_refresh=args.full_refresh,
    )

    # Exit with non-zero code if >10% errors
    if stats["processed"] > 0 and stats["errors"] / stats["processed"] > 0.10:
        sys.exit(1)


if __name__ == "__main__":
    main()
