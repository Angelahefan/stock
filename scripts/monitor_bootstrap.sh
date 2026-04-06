#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# scripts/monitor_bootstrap.sh
# Live bootstrap progress monitor — runs on EC2 or locally via SSH.
#
# Usage (on EC2):
#   bash scripts/monitor_bootstrap.sh
#
# Usage (from laptop):
#   ssh -i ~/.ssh/Linux-CodeCambat.pem ec2-user@platform.datap.ai \
#       "bash /home/ec2-user/git/vanna-streamlit/scripts/monitor_bootstrap.sh"
#
# Press Ctrl+C to exit.
# ─────────────────────────────────────────────────────────────────────────────

REFRESH=300       # seconds between refreshes
LOG=/var/log/datapai/bootstrap_ohlcv.log
PSQL="docker exec lightdash_db_1 psql -U postgres -d postgres"

# ── colours ──────────────────────────────────────────────────────────────────
BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
CYAN="\033[36m"
RED="\033[31m"
RESET="\033[0m"

header() { printf "${BOLD}${CYAN}%-70s${RESET}\n" "$1"; }
label()  { printf "  ${BOLD}%-28s${RESET}" "$1"; }

# ── helpers ───────────────────────────────────────────────────────────────────

db_stats() {
    $PSQL -t -A -F'|' -c "
        SELECT
            COALESCE(exchange,'?') AS exchange,
            COUNT(*)              AS rows,
            COUNT(DISTINCT ticker) AS tickers,
            MIN(date)             AS earliest,
            MAX(date)             AS latest
        FROM datapai.prices
        WHERE open IS NOT NULL
        GROUP BY exchange
        ORDER BY exchange;
    " 2>/dev/null
}

db_total() {
    $PSQL -t -A -c "
        SELECT COUNT(*) FROM datapai.prices WHERE open IS NOT NULL;
    " 2>/dev/null | tr -d ' '
}

screen_status() {
    screen -ls 2>/dev/null | grep -c bootstrap || echo 0
}

last_log_lines() {
    tail -n 8 "$LOG" 2>/dev/null || echo "  (log not found: $LOG)"
}

batch_progress() {
    # pull the last "Batch X/Y" line per exchange
    grep -E '\[.*\] Batch [0-9]+/[0-9]+.*tickers=' "$LOG" 2>/dev/null | tail -6
}

# ── main loop ─────────────────────────────────────────────────────────────────

while true; do
    clear
    NOW=$(date '+%Y-%m-%d %H:%M:%S')
    SCREEN_COUNT=$(screen_status)

    printf "${BOLD}╔══════════════════════════════════════════════════════════════════════╗${RESET}\n"
    printf "${BOLD}║   DataPAI Bootstrap Monitor   %-40s║${RESET}\n" "$NOW"
    printf "${BOLD}╚══════════════════════════════════════════════════════════════════════╝${RESET}\n\n"

    # ── Bootstrap screen ─────────────────────────────────────────────────────
    header "▶  Bootstrap Process"
    label "Screen session:"
    if [ "$SCREEN_COUNT" -gt 0 ]; then
        printf "${GREEN}RUNNING${RESET}  (attach: screen -r bootstrap)\n"
    else
        # check if log says 'complete'
        if grep -q "Bootstrap complete" "$LOG" 2>/dev/null; then
            printf "${GREEN}DONE${RESET}  (process finished)\n"
        else
            printf "${RED}NOT RUNNING${RESET}  (crashed or not started)\n"
        fi
    fi

    # ── DB row counts ─────────────────────────────────────────────────────────
    echo ""
    header "▶  DB Rows (datapai.prices)"
    printf "  ${BOLD}%-12s  %10s  %8s  %12s  %12s${RESET}\n" \
        "Exchange" "Rows" "Tickers" "Earliest" "Latest"
    printf "  %-12s  %10s  %8s  %12s  %12s\n" \
        "────────" "──────────" "────────" "────────────" "────────────"

    TOTAL=0
    while IFS='|' read -r exch rows tickers earliest latest; do
        [ -z "$exch" ] && continue
        printf "  ${GREEN}%-12s${RESET}  %10s  %8s  %12s  %12s\n" \
            "$exch" "$rows" "$tickers" "$earliest" "$latest"
        TOTAL=$((TOTAL + rows))
    done < <(db_stats)

    printf "  %-12s  ${BOLD}%10s${RESET}\n" "TOTAL" "$TOTAL"

    # ── Batch progress ────────────────────────────────────────────────────────
    echo ""
    header "▶  Batch Progress (from log)"
    batch_progress | while read -r line; do
        printf "  %s\n" "$line"
    done

    # ── Last log lines ────────────────────────────────────────────────────────
    echo ""
    header "▶  Last 8 Log Lines  ($LOG)"
    last_log_lines | while read -r line; do
        # colour ERROR lines red, INFO green, WARNING yellow
        if echo "$line" | grep -q "ERROR"; then
            printf "  ${RED}%s${RESET}\n" "$line"
        elif echo "$line" | grep -q "WARNING"; then
            printf "  ${YELLOW}%s${RESET}\n" "$line"
        elif echo "$line" | grep -q "Bootstrap complete"; then
            printf "  ${GREEN}${BOLD}%s${RESET}\n" "$line"
        else
            printf "  %s\n" "$line"
        fi
    done

    # ── Footer ────────────────────────────────────────────────────────────────
    echo ""
    printf "${CYAN}  Refreshing every 5 min — Ctrl+C to quit${RESET}\n"

    sleep "$REFRESH"
done
