#!/usr/bin/env bash
# =============================================================================
# run_compute_ta_intraday.sh  —  30m TA indicator compute wrapper
# =============================================================================
#
# PURPOSE
#   Sources EC2 credentials, then runs compute_ta_intraday.py to pre-compute
#   TA indicators from datapai.ohlcv_intraday and write to datapai.ta_indicators.
#
# CRONTAB  (install with: crontab -e)
# ─────────────────────────────────────────────────────────────────────────────
#   # US: every 30min during market hours, 5 min after intraday refresh
#   5,35 13-20 * * 1-5  /home/ec2-user/git/datapai-streamlit/scripts/run_compute_ta_intraday.sh --exchange US
#
#   # ASX: every 30min during ASX market hours
#   5,35 23    * * 0-4  /home/ec2-user/git/datapai-streamlit/scripts/run_compute_ta_intraday.sh --exchange ASX
#   5,35  0-6  * * 1-5  /home/ec2-user/git/datapai-streamlit/scripts/run_compute_ta_intraday.sh --exchange ASX
# ─────────────────────────────────────────────────────────────────────────────
#
# MANUAL RUN
#   bash scripts/run_compute_ta_intraday.sh --exchange US
#   bash scripts/run_compute_ta_intraday.sh --exchange ASX --dry-run
#
# VIEWING LOGS
#   tail -f /var/log/datapai/compute_ta_intraday.log
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

# ── 3. Run compute ────────────────────────────────────────────────────────────
cd "$PROJECT_DIR"
exec python3 "$SCRIPT_DIR/compute_ta_intraday.py" "$@"
