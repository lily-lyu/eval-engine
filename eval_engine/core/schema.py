import json
from pathlib import Path
from typing import Any, Dict

from jsonschema import Draft202012Validator
from jsonschema.validators import RefResolver


SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"

_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}
_VALIDATOR_CACHE: Dict[str, Draft202012Validator] = {}

# Base URI for resolving relative $ref (e.g. version_bundle.schema.json)
_SCHEMAS_BASE_URI = "file://" + str(SCHEMAS_DIR.resolve()).replace("\\", "/") + "/"


def load_schema(schema_filename: str) -> Dict[str, Any]:
    if schema_filename in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[schema_filename]
    path = SCHEMAS_DIR / schema_filename
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    _SCHEMA_CACHE[schema_filename] = data
    return data


def get_validator(schema_filename: str) -> Draft202012Validator:
    if schema_filename in _VALIDATOR_CACHE:
        return _VALIDATOR_CACHE[schema_filename]
    schema = load_schema(schema_filename)
    schema_copy = {**schema, "$id": _SCHEMAS_BASE_URI + schema_filename}
    resolver = RefResolver(base_uri=_SCHEMAS_BASE_URI, referrer=schema_copy)
    v = Draft202012Validator(schema_copy, resolver=resolver)
    _VALIDATOR_CACHE[schema_filename] = v
    return v


def validate_or_raise(schema_filename: str, instance: Any) -> None:
    v = get_validator(schema_filename)
    errors = sorted(v.iter_errors(instance), key=lambda e: (list(e.absolute_path), e.message))
    if errors:
        parts = []
        for e in errors[:5]:
            path_str = "".join(f"[{repr(p)}]" for p in e.absolute_path)
            schema_ref = getattr(e, "schema_path", None) or getattr(e, "ref", None)
            ref_str = f" ref={schema_ref}" if schema_ref else ""
            parts.append(f"{path_str}: {e.message}{ref_str}")
        msg = "; ".join(parts)
        raise ValueError(f"[{schema_filename}] validation failed: {msg}")
