#!/usr/bin/env python3
"""
scripts/run_stock_synthesis.py
─────────────────────────────────────────────────────────────────────────────
Nightly batch: run AG2 multi-agent signal synthesis for all tracked tickers.

Reads TA, FA, and MA signals from Postgres, runs AG2 debate, and saves
unified recommendations to datapai.stock_synthesis.

Usage:
    python3 scripts/run_stock_synthesis.py --exchange ASX
    python3 scripts/run_stock_synthesis.py --exchange US
    python3 scripts/run_stock_synthesis.py --exchange ASX --tickers BHP,CBA
    python3 scripts/run_stock_synthesis.py --exchange US --dry-run

Cron / Airflow: runs after TA daily + FA daily are complete.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

# ── Logging ────────────────────────────────────────────────────────────────
LOG_DIR = Path("/var/log/datapai")
LOG_FILE = LOG_DIR / "stock_synthesis.log"

log = logging.getLogger("stock_synthesis")
log.setLevel(logging.INFO)

_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Console
_ch = logging.StreamHandler()
_ch.setFormatter(_formatter)
log.addHandler(_ch)

# File (if dir exists)
if LOG_DIR.is_dir():
    _fh = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=10_000_000, backupCount=5
    )
    _fh.setFormatter(_formatter)
    log.addHandler(_fh)


async def run(
    exchange: str,
    tickers: list[str] | None = None,
    dry_run: bool = False,
    model: str | None = None,
) -> None:
    from agents.stock_synthesis import run_synthesis
    from agents.stock_synthesis.signal_gatherer import gather_signals
    from agents.stock_synthesis.db import save_synthesis, ensure_table

    await ensure_table()

    # Load tickers — default is the dynamic synthesis universe
    # (landing-page top-N + all user watchlists, filtered to ones with
    # fundamental data). See scripts/lib/ticker_loader.py.
    if not tickers:
        try:
            from scripts.lib.ticker_loader import load_synthesis_universe
            # Universe returns (ticker, exchange) pairs; for a single-exchange
            # batch we just keep tickers.
            pairs = load_synthesis_universe(exchange=exchange)
            tickers = [t for (t, _ex) in pairs]
        except Exception as exc:
            log.warning("load_synthesis_universe failed (%s) — falling back to fundamental_lite", exc)
            try:
                from scripts.lib.ticker_loader import load_monitored_tickers
                tickers = load_monitored_tickers(exchange=exchange)
            except Exception as exc2:
                log.warning("Could not load tickers: %s", exc2)
                tickers = []

    if not tickers:
        log.warning("No tickers to process for exchange=%s", exchange)
        return

    log.info("=== Stock Synthesis  exchange=%s  tickers=%d  dry_run=%s ===",
             exchange, len(tickers), dry_run)

    processed = 0
    errors = 0
    t0 = time.time()

    for i, ticker in enumerate(tickers, 1):
        try:
            signals = await gather_signals(ticker, exchange)
            if not signals:
                log.info("[%d/%d] %s — no signals, skip", i, len(tickers), ticker)
                continue

            result = await run_synthesis(ticker, exchange, signals, model=model)

            if dry_run:
                log.info("[%d/%d] %s  %s  conf=%.0f%%  conviction=%s  [DRY RUN]",
                         i, len(tickers), ticker,
                         result.direction.value, result.confidence * 100,
                         result.conviction)
            else:
                await save_synthesis(result)
                log.info("[%d/%d] %s  %s  conf=%.0f%%  conviction=%s  thesis=%s",
                         i, len(tickers), ticker,
                         result.direction.value, result.confidence * 100,
                         result.conviction, result.thesis[:80])
            processed += 1

        except Exception as exc:
            log.error("[%d/%d] %s — synthesis failed: %s",
                      i, len(tickers), ticker, str(exc)[:200])
            errors += 1

    elapsed = time.time() - t0
    log.info("=== Stock Synthesis DONE | %s | processed=%d errors=%d | %.0fs ===",
             exchange, processed, errors, elapsed)


def main():
    ap = argparse.ArgumentParser(description="Run AG2 stock signal synthesis")
    ap.add_argument("--exchange", required=True)
    ap.add_argument("--tickers", default="", help="Comma-separated override")
    ap.add_argument("--model", default=None, help="LLM model override")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_DIR / ".env")
    except ImportError:
        pass

    override = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if args.tickers else None
    )
    asyncio.run(run(
        exchange=args.exchange,
        tickers=override,
        dry_run=args.dry_run,
        model=args.model,
    ))


if __name__ == "__main__":
    main()
