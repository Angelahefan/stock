"""
agents/tinyfish_signals — TinyFish Financial Signal Detection Plugin
=====================================================================
Modular plugin for the DataP.ai framework.
Detects and validates financial signals in corporate website language changes.

Public API:
    run_tinyfish_signal_pipeline()   — full orchestration (v1.5 upgraded)
    run_forward_guidance_agent()     — Signal Agent 1
    run_risk_disclosure_agent()      — Signal Agent 2
    run_tone_shift_agent()           — Signal Agent 3
    run_cross_validation_agent()     — multi-source confirmation
    classify_signals()               — combine + prioritise (noise-aware v1.5)
    classify_change_type()           — v1.5: CONTENT/ARCHIVE/LAYOUT quality filter
    get_confidence_multiplier()      — v1.5: noise-to-confidence mapping
    run_investigation_agent()        — v1.5: NEW investigation agent

Per shared-api-contract.md:
    Repo: datapai-streamlit (backend)
    Called by: datapai-tinyfish (Next.js frontend) via HTTP on port 8000
"""

from .forward_guidance_agent   import run_forward_guidance_agent
from .risk_disclosure_agent    import run_risk_disclosure_agent
from .tone_shift_agent         import run_tone_shift_agent
from .cross_validation_agent   import run_cross_validation_agent
from .signal_classifier        import classify_signals
from .tinyfish_signal_pipeline import run_tinyfish_signal_pipeline
from .change_type_classifier   import classify_change_type, get_confidence_multiplier
from .investigation_agent      import run_investigation_agent

__all__ = [
    "run_forward_guidance_agent",
    "run_risk_disclosure_agent",
    "run_tone_shift_agent",
    "run_cross_validation_agent",
    "classify_signals",
    "run_tinyfish_signal_pipeline",
    "classify_change_type",
    "get_confidence_multiplier",
    "run_investigation_agent",
]
