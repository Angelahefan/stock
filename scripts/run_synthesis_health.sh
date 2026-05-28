#!/usr/bin/env bash
# run_synthesis_health.sh — Airflow wrapper for the synthesis health monitor.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
set +u
[[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true
set -u
mkdir -p /var/log/datapai 2>/dev/null || true
cd "$PROJECT_DIR"
exec python3 "$SCRIPT_DIR/run_synthesis_health.py" "$@"
