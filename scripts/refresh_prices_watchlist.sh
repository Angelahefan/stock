#!/usr/bin/env bash
# scripts/refresh_prices_watchlist.sh — Refresh prices for watchlist + homepage tickers only
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

source ~/.bash_profile 2>/dev/null || true
[[ -f .env.dev ]] && set -a && source .env.dev && set +a
[[ -f .env ]]     && set -a && source .env     && set +a

exec python3 scripts/refresh_prices_watchlist.py "$@"
