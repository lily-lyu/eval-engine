import json
from pathlib import Path
from typing import Any, Dict

from jsonschema import Draft202012Validator


SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"

_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}
_VALIDATOR_CACHE: Dict[str, Draft202012Validator] = {}


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
    v = Draft202012Validator(schema)
    _VALIDATOR_CACHE[schema_filename] = v
    return v


def validate_or_raise(schema_filename: str, instance: Any) -> None:
    v = get_validator(schema_filename)
    errors = sorted(v.iter_errors(instance), key=lambda e: e.path)
    if errors:
        msg = "; ".join([f"{list(e.path)}: {e.message}" for e in errors[:5]])
        raise ValueError(f"[{schema_filename}] validation failed: {msg}")
