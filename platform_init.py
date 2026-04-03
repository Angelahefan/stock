"""
Platform framework linkage for datapai-stock-be.
─────────────────────────────────────────────────
Import this module at the TOP of app.py (before any agents.* imports) to
make the common datapai-streamlit framework available via sys.path.

Resolution order:
  1. Local agents/ (stock-specific: technical_analysis, fundamental, etc.)
  2. Platform agents/ via sys.path (generic: llm_client, agent_base, etc.)

Environment:
  DATAPAI_PLATFORM_DIR  — path to datapai-streamlit repo
    Local dev default:   ../datapai-streamlit  (sibling directory)
    EC2 default:         /home/ec2-user/git/vanna-streamlit
    Airflow container:   /opt/datapai
"""
import os
import sys

_PLATFORM_DIR = os.environ.get(
    "DATAPAI_PLATFORM_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "datapai-streamlit"),
)

# Resolve to absolute path
_PLATFORM_DIR = os.path.abspath(_PLATFORM_DIR)

if _PLATFORM_DIR not in sys.path:
    # Append (not insert) so local agents/ takes priority over platform agents/
    sys.path.append(_PLATFORM_DIR)
