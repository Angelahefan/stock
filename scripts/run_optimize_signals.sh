#!/usr/bin/env bash
# =============================================================================
# run_optimize_signals.sh — Weekly signal optimizer (walk-forward validation)
# =============================================================================
#
# Grid-searches threshold parameters for Buy/Hold/Sell signals using
# walk-forward optimization. Saves best params to signal_params.json
# which the screener reads at runtime.
#
# Runs weekly (Sunday) after markets are closed.
#
# MANUAL RUN
#   bash scripts/run_optimize_signals.sh [--exchange US|ASX] [--sample 200]
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

EXCHANGE="US"
SAMPLE="200"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --exchange) EXCHANGE="$2"; shift 2 ;;
        --sample) SAMPLE="$2"; shift 2 ;;
        *) shift ;;
    esac
done

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

echo "$(date '+%F %T') [optimizer] Starting walk-forward optimization for $EXCHANGE (sample=$SAMPLE)"
python3 "$SCRIPT_DIR/optimize_signals.py" --exchange "$EXCHANGE" --sample "$SAMPLE" 2>&1
echo "$(date '+%F %T') [optimizer] Done"
