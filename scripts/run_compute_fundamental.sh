#!/usr/bin/env bash
# =============================================================================
# run_compute_fundamental.sh  —  fundamental analysis compute wrapper
# =============================================================================
#
# PURPOSE
#   Sources EC2 credentials, then runs compute_fundamental_daily.py to
#   pre-compute fundamental analysis (valuation, quality, growth, macro,
#   analyst consensus) for all tracked tickers and write to
#   datapai.fundamental_snapshot and datapai.fundamental_history.
#
# CRONTAB  (install with: crontab -e)
# ─────────────────────────────────────────────────────────────────────────────
#   # ASX: after ASX nightly price refresh (06:15 UTC)
#   0  7 * * 1-5  /home/ec2-user/git/datapai-streamlit/scripts/run_compute_fundamental.sh --exchange ASX
#
#   # US: after US nightly price refresh + Snowflake ETL (00:30 UTC Tue-Sat)
#   0  1 * * 2-6  /home/ec2-user/git/datapai-streamlit/scripts/run_compute_fundamental.sh --exchange US
# ─────────────────────────────────────────────────────────────────────────────
#
# MANUAL RUN
#   bash scripts/run_compute_fundamental.sh --exchange US
#   bash scripts/run_compute_fundamental.sh --exchange US --tickers AAPL,MSFT
#   bash scripts/run_compute_fundamental.sh --exchange US --dry-run
#   bash scripts/run_compute_fundamental.sh --exchange US --full-refresh
#
# VIEWING LOGS
#   tail -f /var/log/datapai/compute_fundamental_daily.log
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
exec python3 "$SCRIPT_DIR/compute_fundamental_daily.py" "$@"
