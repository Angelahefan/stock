#!/usr/bin/env bash
# scripts/smoke_test_synthesis.sh
# ─────────────────────────────────────────────────────────────────────────
# End-to-end smoke test for the synthesis pipeline. Runs a real synthesis
# on AAPL/US, then asserts the row that landed isn't a broken-fallback
# signature.
#
# Usage:
#   scripts/smoke_test_synthesis.sh                 # default ticker AAPL
#   scripts/smoke_test_synthesis.sh MSFT US         # custom ticker/exchange
#
# Exit codes:
#   0   ✓ healthy synthesis row landed
#   1   ✗ exit from python script
#   2   ✗ no row appeared in DB (synthesis didn't write)
#   3   ✗ thesis too short (<100 chars — likely broken-fallback)
#   4   ✗ direction is HOLD with confidence=0.30 (the smoking gun signature)
#   5   ✗ direction not in valid 7-state set
#
# Wire this into systemd ExecStartPre on datapai-agent.service or run
# manually before any deploy. Should take ~60-90s.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

TICKER="${1:-AAPL}"
EXCHANGE="${2:-US}"

echo "════════════════════════════════════════════════════════════════"
echo "  SMOKE TEST · synthesis · ${TICKER}/${EXCHANGE}"
echo "════════════════════════════════════════════════════════════════"
echo

# Run synthesis
cd "$PROJECT_DIR"
set +u
[[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" || true
set -u
T0=$(date +%s)
echo "→ running synthesis (this takes ~60-90s)..."
if ! timeout 240 python3 scripts/run_stock_synthesis.py --ticker "$TICKER" --exchange "$EXCHANGE" >/tmp/smoke_synth.log 2>&1; then
    echo "✗ python script exited non-zero. tail of log:"
    tail -20 /tmp/smoke_synth.log
    exit 1
fi
T1=$(date +%s)
echo "→ ran in $((T1-T0))s"

# Query the row we just wrote
echo "→ querying datapai.stock_synthesis for the row we just wrote..."
ROW=$(docker exec datapai_stock_db psql -U postgres -d postgres -tAc "
    SELECT direction || '|' ||
           confidence || '|' ||
           conviction || '|' ||
           LENGTH(COALESCE(thesis, '')) || '|' ||
           computed_at::text
    FROM datapai.stock_synthesis
    WHERE ticker='${TICKER}' AND exchange='${EXCHANGE}'
      AND computed_at > NOW() - INTERVAL '5 minutes'
    ORDER BY computed_at DESC LIMIT 1;
" 2>/dev/null || true)

if [[ -z "$ROW" ]]; then
    echo "✗ no row appeared in the last 5 minutes. Synthesis ran but didn't write."
    exit 2
fi

IFS='|' read -r DIRECTION CONFIDENCE CONVICTION THESIS_LEN COMPUTED_AT <<< "$ROW"

echo
echo "  direction:    $DIRECTION"
echo "  confidence:   $CONFIDENCE"
echo "  conviction:   $CONVICTION"
echo "  thesis chars: $THESIS_LEN"
echo "  computed_at:  $COMPUTED_AT"
echo

# Assertions
VALID_DIRS=("STRONG_BUY" "BUY" "HOLD" "WATCH" "AVOID" "SELL" "STRONG_SELL")
DIR_VALID=0
for d in "${VALID_DIRS[@]}"; do
    if [[ "$DIRECTION" == "$d" ]]; then DIR_VALID=1; break; fi
done
if (( DIR_VALID == 0 )); then
    echo "✗ direction '$DIRECTION' is not in valid 7-state set: ${VALID_DIRS[*]}"
    exit 5
fi
echo "✓ direction is a valid 7-state value"

if (( THESIS_LEN < 100 )); then
    echo "✗ thesis is only $THESIS_LEN chars — broken-fallback or PM JSON truncated"
    exit 3
fi
echo "✓ thesis length $THESIS_LEN >= 100"

# The smoking-gun signature of the broken fallback: HOLD/0.30/LOW with empty thesis
if [[ "$DIRECTION" == "HOLD" ]] && [[ "$CONFIDENCE" == "0.3" ]] && [[ "$CONVICTION" == "LOW" ]]; then
    echo "✗ broken-fallback signature detected: HOLD/0.30/LOW"
    echo "  This is the exact signature of the 2-month silent failure."
    echo "  Check synthesis_pipeline.py logs for ImportError / fallback fires."
    exit 4
fi
echo "✓ not broken-fallback signature"

echo
echo "════════════════════════════════════════════════════════════════"
echo "  ✓ SMOKE TEST PASSED · synthesis pipeline healthy"
echo "════════════════════════════════════════════════════════════════"
