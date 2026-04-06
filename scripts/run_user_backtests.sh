#!/usr/bin/env bash
# scripts/run_user_backtests.sh — Shell wrapper for Airflow DAG
# Runs nightly user strategy backtests
set -euo pipefail

cd "$(dirname "$0")/.."
python3 scripts/run_user_backtests.py "$@"
