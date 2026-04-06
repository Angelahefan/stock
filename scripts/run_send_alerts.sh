#!/usr/bin/env bash
# scripts/run_send_alerts.sh — Check signal changes and send Telegram alerts
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
set +u
[[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true
set -u
mkdir -p "$SCRIPT_DIR/logs" 2>/dev/null || true
cd "$PROJECT_DIR"
python3 "$SCRIPT_DIR/send_alerts.py" "$@" 2>&1 | tee "$SCRIPT_DIR/logs/send_alerts.log" || true
