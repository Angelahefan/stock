#!/usr/bin/env bash
# =============================================================================
# intraday_runner.sh — self-throttling intraday data collector
# Runs continuously during market hours, exits when all markets close.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="/var/log/datapai"

set +u
[[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true
set -u

[[ ! -d "$LOG_DIR" ]] && mkdir -p "$LOG_DIR" 2>/dev/null || true

cd "$PROJECT_DIR"
exec python3 "$SCRIPT_DIR/intraday_runner.py" "$@"
