import json
from typing import Any, Dict, Tuple

from jsonschema import Draft202012Validator


def run_schema_check(output_schema: Dict[str, Any], raw_output: str) -> Tuple[bool, str, Any]:
    try:
        obj = json.loads(raw_output)
    except Exception as e:
        return False, f"output is not valid JSON: {e}", None

    v = Draft202012Validator(output_schema)
    errors = sorted(v.iter_errors(obj), key=lambda e: e.path)
    if errors:
        msg = "; ".join([f"{list(e.path)}: {e.message}" for e in errors[:3]])
        return False, f"output violates output_schema: {msg}", obj

    return True, "schema_check passed", obj
