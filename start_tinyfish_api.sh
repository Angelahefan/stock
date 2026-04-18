#!/usr/bin/env bash
# start_tinyfish_api.sh
# Starts the TinyFish Financial Signal API (FastAPI / uvicorn) on port 8005.
# Run from the datapai-streamlit repo root:
#   ./start_tinyfish_api.sh
#   ./start_tinyfish_api.sh --no-reload     # production mode (no hot-reload)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

UVICORN=/opt/anaconda3/bin/uvicorn
PORT="${PORT:-8005}"
RELOAD="--reload"

# Parse optional --no-reload flag
for arg in "$@"; do
  case "$arg" in
    --no-reload) RELOAD="" ;;
  esac
done

# Load environment — ~/.bash_profile first (EC2 credentials: POLYGON_KEY, Snowflake, etc.)
# then .env.dev overrides.  Both are optional; missing files are silently skipped.
[[ -f "$HOME/.bash_profile" ]] && { set -a; source "$HOME/.bash_profile"; set +a; echo "[start_tinyfish_api] Loaded ~/.bash_profile"; } || true
[[ -f "$HOME/.bashrc"       ]] && { set -a; source "$HOME/.bashrc";       set +a; } || true
if [ -f "$REPO_DIR/.env.dev" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_DIR/.env.dev"
  set +a
  echo "[start_tinyfish_api] Loaded .env.dev"
fi

echo "[start_tinyfish_api] Starting on port $PORT $RELOAD"
exec "$UVICORN" agents.tinyfish_api:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  $RELOAD
