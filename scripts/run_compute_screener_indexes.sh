#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
set +u; [[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true; set -u
export PGHOST="${PGHOST:-localhost}" PGPORT="${PGPORT:-5432}" PGDATABASE="${PGDATABASE:-postgres}" PGUSER="${PGUSER:-postgres}" PGPASSWORD="${PGPASSWORD:-postgres}"
cd "$PROJECT_DIR"
exec python3 "$SCRIPT_DIR/compute_screener_metrics.py" --exchange INDEX
