"""
Structured LLM output: send prompt to Gemini, parse JSON, validate against schema, retry on failure.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from ..config import PLANNER_MAX_RETRIES
from ..core.failure_codes import (
    LLM_OUTPUT_REPAIR_EXHAUSTED,
    LLM_RESPONSE_NOT_JSON,
    LLM_SCHEMA_NONCOMPLIANT,
)
from ..core.schema import validate_or_raise
from .gemini_client import generate


def _extract_json_block(text: str) -> str | None:
    """Try to extract a JSON object or array from markdown code block or raw text."""
    text = text.strip()
    # ```json ... ``` or ``` ... ```
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()
    # Raw { ... } or [ ... ]
    s = text.find("{")
    if s >= 0:
        depth = 0
        for i in range(s, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[s : i + 1]
    s = text.find("[")
    if s >= 0:
        depth = 0
        for i in range(s, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    return text[s : i + 1]
    return None


def _parse_json(text: str) -> Any:
    """Parse JSON from raw or code-block text. Raises ValueError with LLM_RESPONSE_NOT_JSON on failure."""
    extracted = _extract_json_block(text)
    if extracted is None:
        extracted = text.strip()
    try:
        return json.loads(extracted)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"{LLM_RESPONSE_NOT_JSON}: could not parse JSON from LLM response: {e}"
        ) from e


def generate_and_validate(
    prompt: str,
    schema_filename: str,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_retries: int | None = None,
    parse_list_from_key: str | None = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    """
    Call Gemini with prompt, parse response as JSON, validate against schema.
    If parse_list_from_key is set (e.g. "eval_families"), expect a single object and return obj[parse_list_from_key].
    Retries up to max_retries on invalid JSON or schema validation failure.
    Returns validated artifact (dict or list of dicts). Raises ValueError with typed failure code.
    """
    max_retries = max_retries if max_retries is not None else PLANNER_MAX_RETRIES
    last_error: ValueError | None = None
    for attempt in range(max_retries + 1):
        try:
            raw = generate(prompt, model=model, temperature=temperature)
            data = _parse_json(raw)
            if parse_list_from_key and isinstance(data, dict):
                data = data.get(parse_list_from_key)
                if data is None:
                    raise ValueError(
                        f"{LLM_RESPONSE_NOT_JSON}: missing key '{parse_list_from_key}' in LLM response"
                    )
            if isinstance(data, list):
                for i, item in enumerate(data):
                    if isinstance(item, dict):
                        validate_or_raise(schema_filename, item)
                return data
            if isinstance(data, dict):
                validate_or_raise(schema_filename, data)
                return data
            raise ValueError(
                f"{LLM_RESPONSE_NOT_JSON}: expected JSON object or array, got {type(data).__name__}"
            )
        except ValueError as e:
            last_error = e
            if attempt == max_retries:
                if LLM_SCHEMA_NONCOMPLIANT in str(e) or "validation failed" in str(e).lower():
                    raise ValueError(
                        f"{LLM_SCHEMA_NONCOMPLIANT}: after {max_retries + 1} attempts: {e}"
                    ) from e
                if LLM_RESPONSE_NOT_JSON in str(e):
                    raise ValueError(
                        f"{LLM_OUTPUT_REPAIR_EXHAUSTED}: could not obtain valid JSON after {max_retries + 1} attempts: {e}"
                    ) from e
                raise
            continue
    raise last_error or ValueError(
        f"{LLM_OUTPUT_REPAIR_EXHAUSTED}: exceeded max_retries={max_retries}"
    )


def generate_object_and_validate(
    prompt: str,
    schema_filename: str,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_retries: int | None = None,
) -> dict[str, Any]:
    """Convenience: ensure result is a single dict validated against schema."""
    out = generate_and_validate(
        prompt,
        schema_filename,
        model=model,
        temperature=temperature,
        max_retries=max_retries,
    )
    if isinstance(out, list):
        raise ValueError(
            f"{LLM_SCHEMA_NONCOMPLIANT}: expected single object, got array of length {len(out)}"
        )
    return out
