#!/usr/bin/env bash
# run_failure_analyzer.sh — macro learning loop wrapper for Airflow.
#
# Usage:
#   scripts/run_failure_analyzer.sh --horizon-days 7
#   scripts/run_failure_analyzer.sh --horizon-days 30
#   scripts/run_failure_analyzer.sh --horizon-days 90
#
# Runs AFTER stock_reflector finishes — so any newly-graded debates
# are available to cluster.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
set +u
[[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true
set -u
mkdir -p /var/log/datapai 2>/dev/null || true
cd "$PROJECT_DIR"
exec python3 "$SCRIPT_DIR/run_failure_analyzer.py" "$@"
