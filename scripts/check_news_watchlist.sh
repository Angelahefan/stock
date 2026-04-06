#!/usr/bin/env bash
# scripts/check_news_watchlist.sh — Check breaking news for all watchlist tickers
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/check_news_watchlist.py 2>&1 | tee scripts/logs/check_news_watchlist.log
