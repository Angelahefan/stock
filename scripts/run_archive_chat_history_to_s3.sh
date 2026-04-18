#!/usr/bin/env bash
# =============================================================================
# Thin forwarding shim — archival moved to platform-be (2026-04-18).
#
# The chat-history archival logic is now a platform governance primitive,
# shared across stock + healthcare + future customer deployments, driven
# by sys_common_config. See:
#   platform-be/agents/archival/                    (reusable class)
#   platform-be/scripts/archive_chat_history_to_s3.py  (chat-specific CLI)
#   platform-be/scripts/archive_table_to_s3.py      (generic table CLI)
#   platform-be/docs/ai-governance-framework-design.md
#
# This shim exists so the existing Airflow DAG (chat_history_archival.py in
# datapai-airflow) which calls /opt/datapai-stock/scripts/run_archive_chat_history_to_s3.sh
# continues to work without a DAG edit. When the DAG is updated to point at
# /opt/datapai/scripts/run_archive_chat_history_to_s3.sh directly, this shim
# can be removed.
# =============================================================================

set -euo pipefail

# Resolve platform-be script location. Order:
#   1. Airflow container bind-mount path
#   2. Host path (for manual runs from EC2 ec2-user)
#   3. Local dev path
PLATFORM_SCRIPT=""
for candidate in \
    /opt/datapai/scripts/run_archive_chat_history_to_s3.sh \
    "$HOME/git/datapai-platform-be/scripts/run_archive_chat_history_to_s3.sh" \
    "$(dirname "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)")/../datapai-platform-be/scripts/run_archive_chat_history_to_s3.sh"
do
    if [[ -f "$candidate" ]]; then
        PLATFORM_SCRIPT="$candidate"
        break
    fi
done

if [[ -z "$PLATFORM_SCRIPT" ]]; then
    echo "ERROR: platform-be run_archive_chat_history_to_s3.sh not found in any known location." >&2
    echo "Checked:" >&2
    echo "  /opt/datapai/scripts/" >&2
    echo "  \$HOME/git/datapai-platform-be/scripts/" >&2
    echo "  ../datapai-platform-be/scripts/" >&2
    exit 2
fi

exec bash "$PLATFORM_SCRIPT" "$@"
