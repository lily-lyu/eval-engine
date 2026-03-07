"""
Programmatic checkers: (item_input, parsed_output, plan?) -> (ok, message).
Schema is already enforced by the verifier; checkers validate correctness.
"""
from typing import Any, Dict, Optional, Tuple


# ---- Normalizers for extraction (used by structured_extraction_v1) ----
def _normalize_strip_lower(s: Any) -> str:
    if s is None:
        return ""
    return str(s).strip().lower()


def _normalize_strip(s: Any) -> str:
    if s is None:
        return ""
    return str(s).strip()


NORMALIZERS: Dict[str, Any] = {
    "strip_lower": _normalize_strip_lower,
    "strip": _normalize_strip,
}


# ---- math_add_v1 (unchanged logic; accepts optional plan for signature consistency) ----
def run_programmatic_check_math_add(
    item_input: Dict[str, Any],
    parsed_output: Dict[str, Any],
    plan: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    try:
        a = int(item_input["a"])
        b = int(item_input["b"])
        ans = int(parsed_output["answer"])
    except Exception as e:
        return False, f"programmatic_check parse error: {e}"

    expected = a + b
    if ans == expected:
        return True, "programmatic_check passed (answer == a+b)"
    return False, f"programmatic_check failed: expected {expected}, got {ans}"


# ---- structured_extraction_v1: schema + exact field correctness + optional normalization ----
def run_programmatic_check_structured_extraction(
    item_input: Dict[str, Any],
    parsed_output: Dict[str, Any],
    plan: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, str, Dict[str, Any]]:
    """
    Check extracted JSON fields against expected. Returns (ok, msg, evidence_code, details).
    Uses plan["expected"] and plan.get("checker_config", {}).get("field_normalize") e.g. {"email": "strip_lower", "name": "strip"}.
    """
    empty_details: Dict[str, Any] = {}
    if not plan or plan.get("expected") is None:
        return (
            False,
            "structured_extraction checker requires plan with expected",
            "STRUCTURED_CHECK_CONFIG_ERROR",
            empty_details,
        )

    expected = plan["expected"]
    if not isinstance(expected, dict):
        return (
            False,
            "structured_extraction expected must be a dict",
            "STRUCTURED_CHECK_CONFIG_ERROR",
            empty_details,
        )

    config = plan.get("checker_config") or {}
    required_fields = config.get("required_fields", list(expected.keys()))
    field_normalize = config.get("field_normalize") or {}

    # missing field
    for field in required_fields:
        if field not in parsed_output:
            return (
                False,
                f"missing required field: {field}",
                "STRUCTURED_FIELD_MISSING",
                {
                    "field": field,
                    "expected": expected.get(field),
                    "observed": None,
                },
            )

    # extra field
    allowed = set(required_fields)
    extra_fields = [k for k in parsed_output.keys() if k not in allowed]
    if extra_fields:
        return (
            False,
            f"unexpected extra field(s): {extra_fields}",
            "STRUCTURED_EXTRA_FIELD_PRESENT",
            {"fields": extra_fields},
        )

    # value mismatch (with optional normalization)
    for field in required_fields:
        exp_val = expected.get(field)
        raw_val = parsed_output.get(field)
        norm_name = field_normalize.get(field)
        if norm_name:
            fn = NORMALIZERS.get(norm_name)
            if fn:
                raw_val = fn(raw_val)
                exp_val = fn(exp_val) if exp_val is not None else ""
        obs_val = raw_val
        if obs_val != exp_val:
            return (
                False,
                f"value mismatch for field '{field}': expected={exp_val!r}, observed={obs_val!r}",
                "STRUCTURED_FIELD_VALUE_MISMATCH",
                {
                    "field": field,
                    "expected": exp_val,
                    "observed": obs_val,
                },
            )

    return True, "structured extraction check passed", "", empty_details


# ---- classification_canonical_v1: label set enforcement + canonicalization ----
def run_programmatic_check_classification_canonical(
    item_input: Dict[str, Any],
    parsed_output: Dict[str, Any],
    plan: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """
    Check classification label: must be in allowed set, then canonicalize and compare to expected.
    plan["expected"] = {"label": "positive"}. plan.get("checker_config", {}).get("allowed_labels") = ["positive", "neutral", "negative"].
    plan.get("canonicalization_rules") = [{"from": "Positive", "to": "positive"}, ...] or dict mapping variant -> canonical.
    """
    if not plan or plan.get("expected") is None:
        return False, "classification_canonical checker requires plan with expected"

    expected = plan["expected"]
    if not isinstance(expected, dict) or "label" not in expected:
        return False, "classification_canonical expected must have 'label'"

    if "label" not in parsed_output:
        return False, "classification_canonical output missing 'label'"

    config = plan.get("checker_config") or {}
    oracle = plan.get("oracle") or {}
    # Canonicalize first, then enforce allowed set on canonical form
    label = parsed_output["label"]
    rules = oracle.get("canonicalization_rules") or plan.get("canonicalization_rules")
    if rules and isinstance(rules, list):
        for r in rules:
            if isinstance(r, dict) and r.get("from") == label:
                label = r.get("to", label)
                break
    label_map = config.get("label_map")
    if isinstance(label_map, dict) and label in label_map:
        label = label_map[label]
    if not rules and not label_map and isinstance(label, str):
        label = label.strip().lower()

    allowed = config.get("allowed_labels")
    if allowed is not None and label not in allowed:
        return False, f"classification_canonical label {parsed_output['label']!r} (canonical: {label!r}) not in allowed set {allowed}"

    exp_label = expected["label"]
    if isinstance(exp_label, str):
        exp_label = exp_label.strip().lower()

    if label != exp_label:
        return False, f"classification_canonical label mismatch: expected {expected['label']!r}, got {parsed_output['label']!r} (canonicalized: {label!r})"

    return True, "programmatic_check passed (classification_canonical: label matches)"
