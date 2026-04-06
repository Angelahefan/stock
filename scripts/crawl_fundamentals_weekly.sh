#!/usr/bin/env bash
# =============================================================================
# crawl_fundamentals_weekly.sh — weekly bulk fundamentals crawl
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
exec python3 "$SCRIPT_DIR/crawl_fundamentals_weekly.py" "$@"
