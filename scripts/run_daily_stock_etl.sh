#!/usr/bin/env bash
# =============================================================================
# run_daily_stock_etl.sh  —  cron wrapper for the daily stock ETL pipeline
# =============================================================================
#
# PURPOSE
#   Sources the ec2-user environment (Snowflake + Postgres credentials in
#   ~/.bash_profile), ensures the log directory exists, then hands off to the
#   Python orchestrator (run_daily_stock_etl.py).
#
#   The Python orchestrator runs two steps and writes rotating logs:
#     Step 1: sync_postgres_to_s3_daily.py   → /var/log/datapai/sync_postgres_to_s3_daily.log
#     Step 2: sync_snowflake_iceberg.py       → /var/log/datapai/sync_snowflake_iceberg.log
#     Markers: run_daily_stock_etl.py         → /var/log/datapai/daily_stock_etl.log
#
# CRONTAB  (install on EC2 with: crontab -e  or  crontab /path/to/crontab.txt)
# ─────────────────────────────────────────────────────────────────────────────
#   # refresh US stocks after NYSE closes  (23:15 UTC Mon-Fri)
#   15 23 * * 1-5  /home/ec2-user/git/vanna-streamlit/scripts/refresh_ohlcv_daily.sh
#
#   # refresh ASX stocks after ASX closes  (06:15 UTC Mon-Fri)
#   15  6 * * 1-5  /home/ec2-user/git/vanna-streamlit/scripts/refresh_ohlcv_asx.sh
#
#   # delta sync: Postgres → S3 → Snowflake Iceberg  (00:30 UTC Tue-Sat)
#   # runs after both US (23:15 UTC) and ASX (06:15 UTC prev day) refreshes
#   30  0 * * 2-6  /home/ec2-user/git/vanna-streamlit/scripts/run_daily_stock_etl.sh
# ─────────────────────────────────────────────────────────────────────────────
#
# MANUAL RUN
#   bash scripts/run_daily_stock_etl.sh
#   bash scripts/run_daily_stock_etl.sh --days 5 --dry-run
#
# VIEWING LOGS
#   tail -f /var/log/datapai/daily_stock_etl.log
#   tail -f /var/log/datapai/sync_postgres_to_s3_daily.log
#   tail -f /var/log/datapai/sync_snowflake_iceberg.log
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="/var/log/datapai"

# ── 1. Load environment ───────────────────────────────────────────────────────
# Snowflake + Postgres credentials are exported from ~/.bash_profile on EC2.
# Cron does NOT source .bash_profile automatically, so we do it explicitly.
set +u
[[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true
set -u

# ── 2. Ensure log directory ───────────────────────────────────────────────────
if [[ ! -d "$LOG_DIR" ]]; then
    mkdir -p "$LOG_DIR" 2>/dev/null \
        || { echo "WARN: cannot create $LOG_DIR; Python will fall back to scripts/logs/"; }
fi

# ── 3. Run Python orchestrator ────────────────────────────────────────────────
cd "$PROJECT_DIR"
exec python3 "$SCRIPT_DIR/run_daily_stock_etl.py" "$@"
