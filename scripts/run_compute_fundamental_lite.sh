#!/usr/bin/env bash
# =============================================================================
# run_compute_fundamental_lite.sh  —  bulk fundamental data fetch wrapper
# =============================================================================
#
# Fetches fundamental data (P/E, ROE, margins, quality tier) from yfinance
# for all tickers with price data. No LLM cost — pure yfinance API.
# Updates datapai.fundamental_lite table.
#
# USAGE
#   bash scripts/run_compute_fundamental_lite.sh --exchange US
#   bash scripts/run_compute_fundamental_lite.sh --exchange ASX
#   bash scripts/run_compute_fundamental_lite.sh --exchange ALL
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="/var/log/datapai"

set +u
[[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true
set -u

if [[ ! -d "$LOG_DIR" ]]; then
    mkdir -p "$LOG_DIR" 2>/dev/null || true
fi

cd "$PROJECT_DIR"
exec python3 "$SCRIPT_DIR/compute_fundamental_lite.py" "$@"
