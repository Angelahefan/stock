#!/usr/bin/env bash
# scripts/run_telegram_bot.sh — DataPAI Telegram bot (long-running)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
set +u
[[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true
set -u
cd "$PROJECT_DIR"
exec python3 "$SCRIPT_DIR/telegram_bot.py" "$@"
