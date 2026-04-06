#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# scripts/bootstrap_asx_missing.sh
#
# Load the ~1400 ASX tickers not covered by the default hardcoded-614 list.
#
# HOW TO GET THE FULL ASX TICKER FILE (one-time, ~30 seconds):
#   1. Open: https://www.asx.com.au/markets/company
#   2. Scroll to bottom → click "Download" → save as: scripts/cache/asx_all.csv
#   3. Run this script
#
# OR use curl (if ASX cookie works):
#   curl -b "your_cookie" "https://www.asx.com.au/asx/1/company?count=3000" \
#        -o scripts/cache/asx_all.csv
#
# Usage:
#   bash scripts/bootstrap_asx_missing.sh                       # uses cache/asx_all.csv
#   bash scripts/bootstrap_asx_missing.sh --file my_tickers.csv # custom file
#   bash scripts/bootstrap_asx_missing.sh --dry-run             # no DB write
#
# The CSV must have a column with ASX codes (e.g. "BHP", "CBA").
# The .AX suffix will be added automatically if missing.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_FILE="$SCRIPT_DIR/cache/asx_all.csv"

TICKER_FILE="$DEFAULT_FILE"
DRY_RUN=""

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --file)   TICKER_FILE="$2"; shift 2 ;;
    --dry-run) DRY_RUN="--dry-run"; shift ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# ── Validate ──────────────────────────────────────────────────────────────────
if [[ ! -f "$TICKER_FILE" ]]; then
  echo ""
  echo "ERROR: Ticker file not found: $TICKER_FILE"
  echo ""
  echo "To get the full ASX list (no login required):"
  echo "  1. Visit: https://www.asx.com.au/markets/company"
  echo "  2. Click Download CSV at the bottom of the page"
  echo "  3. Save to: scripts/cache/asx_all.csv"
  echo "  4. Re-run this script"
  echo ""
  echo "Or generate ticker list manually and pass with --file:"
  echo "  bash $0 --file /path/to/your_asx_tickers.csv"
  exit 1
fi

# ── Extract tickers from CSV and run bootstrap ────────────────────────────────
echo "=== ASX Missing Ticker Bootstrap ==="
echo "Source file : $TICKER_FILE"
echo "Dry run     : ${DRY_RUN:-no}"
echo ""

# Convert CSV → space-separated list with .AX suffix using Python
TICKER_LIST=$(python3 - <<PYEOF
import csv, re, sys

path = "$TICKER_FILE"
tickers = []
with open(path, newline='', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    headers = reader.fieldnames or []
    # Find the ticker/code column (try common names)
    code_col = None
    for col in headers:
        if col.strip().upper() in ('ASX CODE', 'CODE', 'TICKER', 'SYMBOL', 'ASX_CODE'):
            code_col = col
            break
    if not code_col and headers:
        code_col = headers[0]  # fall back to first column

    for row in reader:
        raw = row.get(code_col, '').strip().upper()
        if not raw or not re.match(r'^[A-Z0-9]{1,6}$', raw):
            continue
        ticker = raw if raw.endswith('.AX') else f"{raw}.AX"
        tickers.append(ticker)

print(' '.join(sorted(set(tickers))))
PYEOF
)

COUNT=$(echo "$TICKER_LIST" | wc -w | tr -d ' ')
echo "Tickers in file : $COUNT"
echo ""

if [[ "$COUNT" -eq 0 ]]; then
  echo "ERROR: No tickers found in file. Check the CSV format."
  exit 1
fi

# Write to a temp file so bootstrap can use load_tickers_from_file
TEMP_TICKER_FILE="$SCRIPT_DIR/cache/asx_missing_run.txt"
echo "$TICKER_LIST" | tr ' ' '\n' > "$TEMP_TICKER_FILE"
echo "Ticker list written to: $TEMP_TICKER_FILE"
echo ""

# Run bootstrap using the file-based loader (--ticker-file flag)
cd "$REPO_ROOT"
echo "Running: python3 scripts/bootstrap_ohlcv.py --exchanges ASX --resume $DRY_RUN --ticker-file $TEMP_TICKER_FILE"
echo ""
python3 scripts/bootstrap_ohlcv.py \
  --exchanges ASX \
  --resume \
  --years 5 \
  ${DRY_RUN} \
  --ticker-file "$TEMP_TICKER_FILE"
