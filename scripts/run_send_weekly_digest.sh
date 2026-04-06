#!/usr/bin/env bash
# scripts/run_send_weekly_digest.sh — Send weekly portfolio digest emails via SES
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
set +u
[[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true
set -u
mkdir -p "$SCRIPT_DIR/logs" 2>/dev/null || true
cd "$PROJECT_DIR"
python3 "$SCRIPT_DIR/send_weekly_digest.py" "$@" 2>&1 | tee "$SCRIPT_DIR/logs/send_weekly_digest.log" || true
