# Extend scripts.lib package path to include platform's scripts/lib directory
import os as _os

_platform_dir = _os.environ.get(
    "DATAPAI_PLATFORM_DIR",
    _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "..", "datapai-streamlit"),
)
_platform_lib = _os.path.join(_os.path.abspath(_platform_dir), "scripts", "lib")

if _os.path.isdir(_platform_lib) and _platform_lib not in __path__:
    __path__.append(_platform_lib)
