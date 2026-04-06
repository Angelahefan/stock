#!/usr/bin/env bash
# =============================================================================
# run_compute_ta_daily.sh  —  daily TA indicator compute wrapper
# =============================================================================
#
# PURPOSE
#   Sources EC2 credentials, then runs compute_ta_daily.py to pre-compute
#   daily TA indicators from datapai.prices and write to datapai.ta_indicators.
#
# CRONTAB  (install with: crontab -e)
# ─────────────────────────────────────────────────────────────────────────────
#   # US: after EOD rollup + nightly price refresh (21:00 UTC)
#   0 21 * * 1-5  /home/ec2-user/git/datapai-streamlit/scripts/run_compute_ta_daily.sh --exchange US
#
#   # ASX: after ASX EOD rollup (07:00 UTC)
#   0  7 * * 1-5  /home/ec2-user/git/datapai-streamlit/scripts/run_compute_ta_daily.sh --exchange ASX
# ─────────────────────────────────────────────────────────────────────────────
#
# MANUAL RUN
#   bash scripts/run_compute_ta_daily.sh --exchange US
#   bash scripts/run_compute_ta_daily.sh --exchange US --full-refresh
#   bash scripts/run_compute_ta_daily.sh --exchange US --dry-run
#
# VIEWING LOGS
#   tail -f /var/log/datapai/compute_ta_daily.log
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
exec python3 "$SCRIPT_DIR/compute_ta_daily.py" "$@"
