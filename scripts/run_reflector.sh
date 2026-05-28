#!/usr/bin/env bash
# run_reflector.sh — Reflector batch wrapper for Airflow.
#
# Usage:
#   scripts/run_reflector.sh --horizon-days 7   # grade 7-day-old debates against 7d return
#   scripts/run_reflector.sh --horizon-days 30  # grade 30-day-old debates against 30d return
#   scripts/run_reflector.sh --horizon-days 90  # grade 90-day-old debates against 90d return
#
# Sequential per-horizon design: the Airflow DAG calls this script 3 times
# in a row (7 → 30 → 90), each pass writes only the corresponding
# was_correct_Nd column on rows that have reached that horizon AND haven't
# yet been graded at that horizon. Re-running is idempotent.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
set +u
[[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true
set -u
mkdir -p /var/log/datapai 2>/dev/null || true
cd "$PROJECT_DIR"
exec python3 "$SCRIPT_DIR/run_reflector.py" "$@"
