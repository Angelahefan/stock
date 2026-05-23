#!/usr/bin/env bash
# Misnamed historically — this script is the GENERIC screener-metrics
# refresher invoked by stock_eod_dynamic.py for EVERY exchange (US, ASX,
# HKEX, TSE, ...). The DAG passes `--exchange {EXCHANGE}` so we forward
# all args verbatim. If invoked manually with no args, fall back to ALL.
#
# BUG HISTORY (2026-05-23): this used to hardcode `--exchange INDEX`,
# which silently restricted nightly refresh to the 16 index tickers
# (^GSPC, ^DJI, etc) and left every real exchange's screener_metrics
# stuck at 2026-04-03. UI returned 0 rows from /api/screener/technical
# because the endpoint filters `trade_date >= CURRENT_DATE - 5 days`.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
set +u; [[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true; set -u
export PGHOST="${PGHOST:-localhost}" PGPORT="${PGPORT:-5432}" PGDATABASE="${PGDATABASE:-postgres}" PGUSER="${PGUSER:-postgres}" PGPASSWORD="${PGPASSWORD:-postgres}"
cd "$PROJECT_DIR"
if [ "$#" -eq 0 ]; then
  exec python3 "$SCRIPT_DIR/compute_screener_metrics.py" --exchange ALL
else
  exec python3 "$SCRIPT_DIR/compute_screener_metrics.py" "$@"
fi
