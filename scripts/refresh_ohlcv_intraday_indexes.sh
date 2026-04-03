#!/usr/bin/env bash
# =============================================================================
# refresh_ohlcv_intraday_indexes.sh  —  Refresh 16 global index prices
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="${DATAPAI_LOG_DIR:-/var/log/datapai}"

# ── 1. Load environment ───────────────────────────────────────────────────────
set +u
[[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true
set -u

# ── 2. Ensure log directory ───────────────────────────────────────────────────
mkdir -p "$LOG_DIR" 2>/dev/null || true

# ── 3. Run refresh ──────────────────────────────────────────────────────────
cd "$PROJECT_DIR"
exec python3 "$SCRIPT_DIR/refresh_ohlcv_daily_indexes.py" "$@"
