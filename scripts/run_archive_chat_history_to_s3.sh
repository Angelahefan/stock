#!/usr/bin/env bash
# =============================================================================
# run_archive_chat_history_to_s3.sh  —  Weekly chat history archival wrapper
# =============================================================================
#
# PURPOSE
#   Runs archive_chat_history_to_s3.py to move chat_messages/chat_sessions rows
#   older than hot_retention_days (config in sys_common_config) out of Postgres
#   and into S3 as Parquet files, partitioned by year/month/day.
#
#   Part of the AI Governance audit trail (Phase 1.13, 2026-04-12). Hot tier
#   in framework_db (fast reads for active UI), cold tier in S3 (forever, for
#   audit / back-tracking / compliance).
#
# SCHEDULE  (via Airflow DAG chat_history_archival)
#   Every Sunday at 02:00 UTC — runs when user traffic is lowest.
#
# MANUAL RUN
#   bash scripts/run_archive_chat_history_to_s3.sh                  # live
#   bash scripts/run_archive_chat_history_to_s3.sh --dry-run        # upload
#                                                                     but keep
#                                                                     Postgres
#                                                                     rows
#
# CONFIG (DB-driven — edit sys_common_config, no code changes)
#   config_type='chat_archive' keys:
#     hot_retention_days         (default 90)
#     archive_bucket             (default codepais3)
#     archive_prefix_stock       (default datapai-archive/stock/chat_history)
#     archive_enabled            (default true)
#     archive_safety_overlap_days (default 7)
#
# VIEWING LOGS
#   tail -f /var/log/datapai/archive_chat_history_to_s3.log
#   SELECT * FROM datapai.sys_archive_log ORDER BY started_at DESC LIMIT 10;
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="/var/log/datapai"

# ── 1. Load environment ───────────────────────────────────────────────────────
# First try the EC2 host paths (most specific), then the container bind-mount
# paths, then bash_profile as a last resort. First match wins since set -a
# exports keep their initial value until explicitly overwritten.
set +u
[[ -f "$HOME/.env.dev" ]]      && set -a && source "$HOME/.env.dev"      && set +a || true
[[ -f /opt/datapai/.env.dev ]] && set -a && source /opt/datapai/.env.dev && set +a || true
[[ -f /opt/datapai/.env ]]     && set -a && source /opt/datapai/.env     && set +a || true
[[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true
set -u

# ── 2. Ensure log directory ───────────────────────────────────────────────────
if [[ ! -d "$LOG_DIR" ]]; then
    mkdir -p "$LOG_DIR" 2>/dev/null \
        || { echo "WARN: cannot create $LOG_DIR; falling back to scripts/logs/"; }
fi
mkdir -p "$SCRIPT_DIR/logs" 2>/dev/null || true

# ── 3. Run archival ───────────────────────────────────────────────────────────
cd "$PROJECT_DIR"
exec python3 "$SCRIPT_DIR/archive_chat_history_to_s3.py" "$@"
