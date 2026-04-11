#!/usr/bin/env bash
# run_stock_crm_client_sync.sh — shell wrapper for nightly Twenty CRM sync.
# Follows the standard datapai-stock-be/scripts/run_*.sh pattern.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

set +u
[[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true
set -u

cd "$PROJECT_DIR"
exec python3 "$SCRIPT_DIR/stock_crm_client_sync.py" "$@"
