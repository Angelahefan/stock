# datapai-stock-be/agents/__init__.py
# ─────────────────────────────────────────────────────────────────────────────
# Extend the agents package path to include the platform's agents directory.
# This allows `from agents.llm_client import ...` to resolve to the platform
# while `from agents.technical_analysis import ...` resolves locally.
# ─────────────────────────────────────────────────────────────────────────────
import os as _os

_platform_dir = _os.environ.get(
    "DATAPAI_PLATFORM_DIR",
    _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "datapai-streamlit"),
)
_platform_agents = _os.path.join(_os.path.abspath(_platform_dir), "agents")

if _os.path.isdir(_platform_agents) and _platform_agents not in __path__:
    __path__.append(_platform_agents)
