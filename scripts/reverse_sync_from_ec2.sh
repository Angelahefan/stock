#!/bin/bash
# Reverse-sync EC2 → local for all rsync-deployed repos. Run this at the
# START of any session that will touch EC2-deployed code, BEFORE any local
# commit or push. EC2 is the source of truth — hotfixes land there first.
#
# Default mode: DRY-RUN (shows what would change, touches nothing).
# Apply: pass --apply.
#
# Usage:
#   scripts/reverse_sync_from_ec2.sh           # dry-run, show divergence
#   scripts/reverse_sync_from_ec2.sh --apply   # actually pull EC2 → local
#
# Does NOT touch repos that have their own .git on EC2 (platform-be,
# airflow) — those need `git bundle` for EC2-only commits; reminder
# printed at the end.

set -u

EC2="ec2-user@platform.datap.ai"
KEY="$HOME/.ssh/Linux-CodeCambat.pem"
SSH_OPTS="-i $KEY -o StrictHostKeyChecking=no"

# Standard excludes — keep aligned with CLAUDE.md / memory.
EXCLUDES=(
    --exclude .git
    --exclude __pycache__
    --exclude node_modules
    --exclude .next
    --exclude target
    --exclude dbt_packages
    --exclude logs
    --exclude ".env*"
    --exclude out
    --exclude .venv
)

# rsync-deployed repos (no .git on EC2)
RSYNC_REPOS=(
    datapai-stock-be
    datapai-platform-menu
    datapai-dbt-governance
)

# git repos on EC2 — flagged for bundle-based sync, not covered here
GIT_REPOS=(
    datapai-platform-be
    datapai-airflow
)

APPLY=0
if [[ "${1:-}" == "--apply" ]]; then APPLY=1; fi

FLAGS=(-avz --itemize-changes)
[[ $APPLY -eq 0 ]] && FLAGS+=(--dry-run)

echo "EC2 reverse-sync — mode: $([[ $APPLY -eq 1 ]] && echo APPLY || echo dry-run)"
echo "───────────────────────────────────────────────────────────"

# SAFETY — refuse --apply if any target repo has uncommitted working-tree
# changes. Prevents the exact incident from 2026-04-21 where my local
# in-flight edits were silently clobbered by older EC2 versions.
if [[ $APPLY -eq 1 ]]; then
    dirty=""
    for repo in "${RSYNC_REPOS[@]}"; do
        d="$HOME/git/$repo"
        [[ ! -d "$d/.git" ]] && continue
        if ! git -C "$d" diff --quiet || ! git -C "$d" diff --cached --quiet; then
            dirty="$dirty\n  - $repo"
        fi
    done
    if [[ -n "$dirty" ]]; then
        echo "ABORT: uncommitted changes in:" >&2
        echo -e "$dirty" >&2
        echo >&2
        echo "Commit, stash, or discard them first. EC2 sync would overwrite." >&2
        echo "  git -C ~/git/<repo> stash       # to keep work, pull, then stash pop" >&2
        exit 1
    fi
fi

for repo in "${RSYNC_REPOS[@]}"; do
    local_dir="$HOME/git/$repo"
    remote_dir="/home/ec2-user/git/$repo/"
    if [[ ! -d "$local_dir" ]]; then
        echo "⚠  $repo  — local dir missing, skipped"
        continue
    fi
    echo "▶ $repo"
    rsync "${FLAGS[@]}" "${EXCLUDES[@]}" \
        -e "ssh $SSH_OPTS" \
        "$EC2:$remote_dir" "$local_dir/" \
        | grep -vE "^(sending|sent|total|receiving|\./$|^$)" | sed 's/^/    /'
    echo
done

echo "───────────────────────────────────────────────────────────"
echo "Not covered above (have .git on EC2 — use git bundle):"
for repo in "${GIT_REPOS[@]}"; do
    echo "  $repo"
done
echo
echo "Bundle pattern for those:"
echo "  ssh $EC2 'cd ~/git/<repo> && git bundle create /tmp/<repo>.bundle origin/<branch>..<branch>'"
echo "  scp $EC2:/tmp/<repo>.bundle /tmp/"
echo "  cd ~/git/<repo> && git fetch /tmp/<repo>.bundle <branch>"
echo "  git log --oneline HEAD..FETCH_HEAD    # see EC2-only commits"
echo "  git merge --no-edit FETCH_HEAD        # or cherry-pick"
