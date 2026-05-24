"""
agents/stock_synthesis/gemini_ag2_client.py — AG2 custom ModelClient wrapping
the already-proven GoogleChatClient (HTTP-only, no google-generativeai SDK).

WHY THIS EXISTS
---------------
AG2 0.5.3's native Gemini path (``api_type="google"``) imports
``google.ai.generativelanguage.Content`` which only exists in
``google-generativeai >= 0.3``. That package version requires Python 3.9+,
but EC2 is pinned to Python 3.8.20 — so PyPI caps us at the ancient
``google-generativeai 0.1.0rc1`` which is missing ``Content``. Result: AG2's
GroupChat silently fell back to the OpenAI default client for 2 months,
which itself failed → "AG2 debate failed: ... — falling back" log every call.

Rather than upgrade Python (separate maintenance window) or drop AG2,
we plug our existing ``GoogleChatClient`` (pure ``requests`` against
``https://generativelanguage.googleapis.com``) into AG2 via the documented
``register_model_client`` protocol. Same Gemini endpoint the chat bot uses
— proven reliable.

USAGE in synthesis_pipeline.py
------------------------------
    from agents.stock_synthesis.gemini_ag2_client import (
        GeminiHTTPModelClient,
        build_llm_config,
    )

    llm_config = build_llm_config(model="gemini-2.5-flash", temperature=0.3)

    bull = ConversableAgent(name="Bull_Analyst", llm_config=llm_config, ...)
    bull.register_model_client(model_client_cls=GeminiHTTPModelClient)
    # ...same for bear, risk_mgr, portfolio_mgr, manager

The model_client_cls name "GeminiHTTPModelClient" must match the
``model_client_cls`` string in the llm_config — that's how AG2 routes.
"""
from __future__ import annotations

import logging
import os
from types import SimpleNamespace
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ── llm_config helper ────────────────────────────────────────────────────────
def build_llm_config(model: str = "gemini-2.5-flash", temperature: float = 0.3) -> Dict[str, Any]:
    """
    Build an AG2 llm_config that routes through GeminiHTTPModelClient.

    Note: NEVER use 'gemini-2.5-flash-lite' for function-call / multi-turn
    chats — it returns silent empty responses after the first tool round.
    """
    return {
        "config_list": [{
            "model": model,
            "model_client_cls": "GeminiHTTPModelClient",
            "api_key": os.environ.get("GOOGLE_API_KEY", ""),
        }],
        "temperature": temperature,
        "cache_seed": None,  # disable AG2's disk cache; we rely on CostGuard upstream
    }


# ── AG2 ModelClient implementation ───────────────────────────────────────────
class GeminiHTTPModelClient:
    """
    Implements AG2's ModelClient protocol by delegating to GoogleChatClient.

    AG2 protocol requires:
      - __init__(self, config, **kwargs)
      - create(self, params) -> ModelClientResponseProtocol
      - message_retrieval(self, response) -> List[str]
      - cost(self, response) -> float
      - @staticmethod get_usage(response) -> Dict[str, Any]
    """

    RESPONSE_USAGE_KEYS = ["prompt_tokens", "completion_tokens", "total_tokens", "cost", "model"]

    def __init__(self, config: Dict[str, Any], **kwargs: Any):
        # Lazy import — keeps this file importable on the local Mac even though
        # GoogleChatClient only resolves on EC2 (via DATAPAI_PLATFORM_DIR).
        from agents.llm_client import GoogleChatClient
        self.model_name = config.get("model", "gemini-2.5-flash")
        self._client = GoogleChatClient(model=self.model_name)
        self._default_temperature = config.get("temperature", 0.3)

    # ── AG2 calls this once per LLM round ────────────────────────────────────
    def create(self, params: Dict[str, Any]) -> Any:
        messages: List[Dict[str, str]] = params.get("messages") or []
        temperature = params.get("temperature", self._default_temperature)

        try:
            raw = self._client.chat(messages=messages, temperature=temperature)
        except Exception as exc:
            logger.error("GeminiHTTPModelClient.chat() failed: %s", str(exc)[:200])
            # Return an empty-but-valid response so AG2 doesn't crash mid-debate.
            return _build_response(content="", model=self.model_name)

        content = raw.get("content", "") if isinstance(raw, dict) else str(raw or "")
        usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
        return _build_response(
            content=content,
            model=self.model_name,
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
        )

    # ── AG2 extracts assistant text via this ─────────────────────────────────
    def message_retrieval(self, response: Any) -> List[str]:
        try:
            return [choice.message.content or "" for choice in response.choices]
        except Exception:
            return [""]

    # ── Cost tracking lives in our own CostGuard; report 0 to AG2 ────────────
    def cost(self, response: Any) -> float:
        return 0.0

    @staticmethod
    def get_usage(response: Any) -> Dict[str, Any]:
        usage = getattr(response, "usage", None) or {}
        return {
            "prompt_tokens":     int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens":      int(getattr(usage, "total_tokens", 0) or 0),
            "cost":              0.0,
            "model":             getattr(response, "model", ""),
        }


# ── Helper: build a SimpleNamespace shaped like OpenAI's ChatCompletion ─────
def _build_response(
    content: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> SimpleNamespace:
    """
    AG2's ModelClientResponseProtocol expects:
      response.choices[i].message.content : str
      response.model : str
      response.usage.{prompt,completion,total}_tokens : int
    """
    message = SimpleNamespace(
        content=content,
        role="assistant",
        function_call=None,
        tool_calls=None,
    )
    choice = SimpleNamespace(
        message=message,
        finish_reason="stop",
        index=0,
    )
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    return SimpleNamespace(
        choices=[choice],
        model=model,
        usage=usage,
        id="gemini-http-" + str(id(message)),
        object="chat.completion",
        created=0,
        # AG2 sets this attribute on the response when it picks the right client
        message_retrieval_function=None,
    )
