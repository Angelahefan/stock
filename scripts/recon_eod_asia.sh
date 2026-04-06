#!/usr/bin/env bash
# =============================================================================
# recon_eod_asia.sh — Asia + ASX EOD data reconciliation
# Checks for missing data, backfills gaps automatically
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
exec python3 "$SCRIPT_DIR/recon_eod_data.py" --region asia "$@"
