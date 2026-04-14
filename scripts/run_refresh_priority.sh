#!/usr/bin/env bash
# scripts/run_refresh_priority.sh — Refresh only priority tickers (demo + watchlist)
# Called by stock_eod_dynamic DAG as the first step before full refresh.
# Wraps refresh_prices_watchlist.py which handles both US + ASX priority tickers.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

source ~/.bash_profile 2>/dev/null || true
[[ -f .env.dev ]] && set -a && source .env.dev && set +a
[[ -f .env ]]     && set -a && source .env     && set +a

echo "[run_refresh_priority] Starting priority ticker refresh (demo + watchlist)..."
exec python3 scripts/refresh_prices_watchlist.py
