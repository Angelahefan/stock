#!/usr/bin/env bash
# =============================================================================
# run_compute_multi_factor.sh — Priority tickers + Multi-factor signals
# =============================================================================
#
# Runs after screener_metrics + fundamental. Chains 3 scripts:
#   1. compute_priority_tickers.py — identifies ~600 tickers worth analyzing
#   2. compute_fundamental_lite.py — fetches Yahoo Finance data for priority list
#   3. compute_multi_factor_signals.py — combines TA + FA into signal scores
#
# MANUAL RUN
#   bash scripts/run_compute_multi_factor.sh [--exchange US|ASX]
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Parse exchange arg (default: US)
EXCHANGE="US"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --exchange) EXCHANGE="$2"; shift 2 ;;
        *) shift ;;
    esac
done

# ── Load environment ─────────────────────────────────────────────────────────
set +u
[[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true
set -u

export PGHOST="${PGHOST:-localhost}"
export PGPORT="${PGPORT:-5432}"
export PGDATABASE="${PGDATABASE:-postgres}"
export PGUSER="${PGUSER:-postgres}"
export PGPASSWORD="${PGPASSWORD:-postgres}"

mkdir -p /var/log/datapai 2>/dev/null || true

cd "$PROJECT_DIR"

echo "$(date '+%F %T') [multi-factor] Starting for exchange=$EXCHANGE"

# Step 1: Compute priority tickers
echo "$(date '+%F %T') [multi-factor] Step 1: Priority tickers..."
python3 "$SCRIPT_DIR/compute_priority_tickers.py" --exchange "$EXCHANGE" 2>&1

# Step 2: Fundamental lite (Yahoo Finance) — only for priority tickers
echo "$(date '+%F %T') [multi-factor] Step 2: Fundamental lite..."
python3 "$SCRIPT_DIR/compute_fundamental_lite.py" --exchange "$EXCHANGE" 2>&1

# Step 3: Multi-factor signals
echo "$(date '+%F %T') [multi-factor] Step 3: Multi-factor signals..."
python3 "$SCRIPT_DIR/compute_multi_factor_signals.py" --exchange "$EXCHANGE" 2>&1

echo "$(date '+%F %T') [multi-factor] Done for $EXCHANGE"
