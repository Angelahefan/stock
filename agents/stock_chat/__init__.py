# ═══════════════════════════════════════════════════════════════════════════════
# MODULE: agents/stock_chat/
# PURPOSE: Conversational AI co-pilot grounded in TinyFish scan history
#
# SEALED MODULE — isolation contract:
#   DEPENDS ON : agents/llm_client.py (import only, never modified)
#   TOUCHES    : datapai schema in lightdash postgres (new, isolated)
#   TOUCHES    : LanceDB S3 collection 'tinyfish_scans' (new collection only)
#   DOES NOT TOUCH: tinyfish_signals/, etl/, rag/, ag2, existing SQLite
# ═══════════════════════════════════════════════════════════════════════════════

from .endpoint import router

__all__ = ["router"]
