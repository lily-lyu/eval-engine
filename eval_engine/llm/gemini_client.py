"""
Gemini API client for planner and LLM workers. Server-side only; never expose API key to frontend.
Uses the official Google GenAI SDK (google.genai). Install with: pip install google-genai
"""
from __future__ import annotations

from typing import Any

from ..config import GEMINI_API_KEY, PLANNER_MODEL, PLANNER_TEMPERATURE
from ..core.failure_codes import LLM_CALL_FAILED, LLM_PROVIDER_NOT_CONFIGURED

_client: Any = None


def get_client():
    """Lazy-init Gemini client. Raises if API key is not set."""
    global _client
    if _client is not None:
        return _client
    if not GEMINI_API_KEY:
        raise ValueError(
            f"{LLM_PROVIDER_NOT_CONFIGURED}: GEMINI_API_KEY is not set. "
            "Configure it in the backend environment."
        )
    try:
        from google import genai

        _client = genai.Client(api_key=GEMINI_API_KEY)
        return _client
    except ImportError as e:
        raise ValueError(
            f"{LLM_PROVIDER_NOT_CONFIGURED}: google-genai is not installed. "
            "Install with: pip install google-genai"
        ) from e


def _model_name(name: str) -> str:
    """Ensure model name has 'models/' prefix if missing (SDK accepts both)."""
    if not name.startswith("models/"):
        return f"models/{name}"
    return name


def generate(
    prompt: str,
    *,
    model: str | None = None,
    temperature: float | None = None,
) -> str:
    """
    Send prompt to Gemini and return the generated text.
    Raises ValueError with LLM_CALL_FAILED on API or generation errors.
    """
    model_id = _model_name(model or PLANNER_MODEL)
    temperature = temperature if temperature is not None else PLANNER_TEMPERATURE
    client = get_client()
    try:
        from google.genai import types

        config = types.GenerateContentConfig(temperature=temperature)
        response = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=config,
        )
        if not response:
            raise ValueError(
                f"{LLM_CALL_FAILED}: empty response from model={model_id}"
            )
        text = getattr(response, "text", None)
        if text is None or (isinstance(text, str) and not text.strip()):
            raise ValueError(
                f"{LLM_CALL_FAILED}: no text in response from model={model_id}"
            )
        return text.strip()
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(
            f"{LLM_CALL_FAILED}: {type(e).__name__}: {e}"
        ) from e
