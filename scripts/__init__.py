# Extend scripts package path to include platform's scripts directory
import os as _os

_platform_dir = _os.environ.get(
    "DATAPAI_PLATFORM_DIR",
    _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "datapai-streamlit"),
)
_platform_scripts = _os.path.join(_os.path.abspath(_platform_dir), "scripts")

if _os.path.isdir(_platform_scripts) and _platform_scripts not in __path__:
    __path__.append(_platform_scripts)
