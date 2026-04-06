#!/usr/bin/env bash
# =============================================================================
# run_compute_ta_weekly.sh  —  weekly TA indicator compute wrapper
# =============================================================================
#
# PURPOSE
#   Sources EC2 credentials, then runs compute_ta_weekly.py to pre-compute
#   weekly TA indicators (resampled from daily bars) and write to
#   datapai.ta_indicators.
#
# CRONTAB  (install with: crontab -e)
# ─────────────────────────────────────────────────────────────────────────────
#   # Every Sunday at 01:00 UTC (after US Friday market closes)
#   0 1 * * 0  /home/ec2-user/git/datapai-streamlit/scripts/run_compute_ta_weekly.sh --exchange US
#   0 1 * * 0  /home/ec2-user/git/datapai-streamlit/scripts/run_compute_ta_weekly.sh --exchange ASX
# ─────────────────────────────────────────────────────────────────────────────
#
# MANUAL RUN
#   bash scripts/run_compute_ta_weekly.sh --exchange US
#   bash scripts/run_compute_ta_weekly.sh --exchange US --full-refresh
#   bash scripts/run_compute_ta_weekly.sh --exchange US --dry-run
#
# VIEWING LOGS
#   tail -f /var/log/datapai/compute_ta_weekly.log
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="/var/log/datapai"

# ── 1. Load environment ───────────────────────────────────────────────────────
set +u
[[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true
set -u

if [[ ! -d "$LOG_DIR" ]]; then
    mkdir -p "$LOG_DIR" 2>/dev/null \
        || { echo "WARN: cannot create $LOG_DIR; Python will fall back to scripts/logs/"; }
fi

cd "$PROJECT_DIR"
exec python3 "$SCRIPT_DIR/compute_ta_weekly.py" "$@"
