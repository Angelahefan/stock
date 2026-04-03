#!/usr/bin/env bash
# =============================================================================
# refresh_ohlcv_daily_lse.sh — LSE daily OHLCV refresh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="/var/log/datapai"

# ── 1. Load environment ───────────────────────────────────────────────────────
set +u
[[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true
set -u

# ── 2. Ensure log directory ───────────────────────────────────────────────────
if [[ ! -d "$LOG_DIR" ]]; then
    mkdir -p "$LOG_DIR" 2>/dev/null \
        || { echo "WARN: cannot create $LOG_DIR; Python will fall back to scripts/logs/"; }
fi

# ── 3. Run refresh ──────────────────────────────────────────────────────────
cd "$PROJECT_DIR"
exec python3 "$SCRIPT_DIR/refresh_ohlcv_daily.py" --exchange LSE "$@"
