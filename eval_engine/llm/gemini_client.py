"""
Gemini API client for planner agents. Server-side only; never expose API key to frontend.
Uses the official Google GenAI SDK (google-generativeai).
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
        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
        _client = genai
        return _client
    except ImportError as e:
        raise ValueError(
            f"{LLM_PROVIDER_NOT_CONFIGURED}: google-generativeai is not installed. "
            "Install with: pip install google-generativeai"
        ) from e


def _model_name(name: str) -> str:
    """Ensure model name has 'models/' prefix if missing."""
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
        gen_config_cls = getattr(client, "GenerationConfig", None)
        if gen_config_cls is not None:
            generation_config = gen_config_cls(temperature=temperature)
        else:
            generation_config = {"temperature": temperature}
        gm = client.GenerativeModel(
            model_name=model_id,
            generation_config=generation_config,
        )
        response = gm.generate_content(prompt)
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
