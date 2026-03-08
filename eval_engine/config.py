"""
Backend-only planner configuration. Never expose API keys to the frontend.
"""
import os
from typing import Literal

PlannerMode = Literal["deterministic", "llm", "hybrid"]


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key, "").strip().lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    return default


def _env_int(key: str, default: int, min_val: int | None = None, max_val: int | None = None) -> int:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
        if min_val is not None and v < min_val:
            return min_val
        if max_val is not None and v > max_val:
            return max_val
        return v
    except ValueError:
        return default


def _env_float(key: str, default: float, min_val: float | None = None, max_val: float | None = None) -> float:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
        if min_val is not None and v < min_val:
            return min_val
        if max_val is not None and v > max_val:
            return max_val
        return v
    except ValueError:
        return default


# Gemini planner (backend only)
GEMINI_API_KEY: str = (os.getenv("GEMINI_API_KEY") or "").strip()

PLANNER_MODE: PlannerMode = (
    os.getenv("PLANNER_MODE", "deterministic").strip().lower() or "deterministic"
)
if PLANNER_MODE not in ("deterministic", "llm", "hybrid"):
    PLANNER_MODE = "deterministic"

PLANNER_MODEL: str = os.getenv("PLANNER_MODEL", "gemini-3-flash-preview").strip() or "gemini-3-flash-preview"
PLANNER_TEMPERATURE: float = _env_float("PLANNER_TEMPERATURE", 0.2, 0.0, 2.0)
PLANNER_MAX_RETRIES: int = _env_int("PLANNER_MAX_RETRIES", 3, 1, 10)
PLANNER_ALLOW_EXPERIMENTAL_FAMILIES: bool = _env_bool("PLANNER_ALLOW_EXPERIMENTAL_FAMILIES", False)


def require_gemini_key_if_llm(mode: str | None = None) -> None:
    """Raise if mode is llm or hybrid and GEMINI_API_KEY is missing."""
    from .core.failure_codes import LLM_PROVIDER_NOT_CONFIGURED

    m = (mode or PLANNER_MODE).lower()
    if m in ("llm", "hybrid") and not GEMINI_API_KEY:
        raise ValueError(
            f"{LLM_PROVIDER_NOT_CONFIGURED}: planner_mode={m} requires GEMINI_API_KEY. "
            "Set GEMINI_API_KEY in the backend environment or use planner_mode=deterministic."
        )
