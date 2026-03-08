"""
Controlled family catalog for the intent planning layer.
Planners select/compose from this catalog; no arbitrary ontology invention.
"""
from typing import Any, Dict, List, Optional, Tuple

FAMILY_CATALOG_VERSION = "1.0.0"

# Safe near-miss aliases for hybrid normalization (alias -> canonical family_id).
FAMILY_ID_ALIAS_MAP: Dict[str, str] = {
    "trajectory.email_tool": "trajectory.email_lookup",
    "trajectory.email_search": "trajectory.email_lookup",
    "structured.extraction": "extraction.structured",
    "email.extraction": "extraction.email",
    "factual.qa": "grounded.qa.factual",
    "sentiment.classification": "classification.sentiment",
    "canonical.classification": "classification.canonical",
    "addition.math": "math.add",
}

# Supported task_type values that map to materializers (must match task registry).
SUPPORTED_TASK_TYPES = frozenset({
    "json_math_add",
    "json_extract_email",
    "json_classify_sentiment",
    "trajectory_email_then_answer",
    "json_extract_structured",
    "json_classify_canonical",
    "factual_grounded_qa",
})

# Capability focus tokens that map to family_id(s).
CAPABILITY_TO_FAMILIES: Dict[str, List[str]] = {
    "extraction": ["extraction.email", "extraction.structured"],
    "email": ["extraction.email", "trajectory.email_lookup"],
    "structured": ["extraction.structured"],
    "classification": ["classification.sentiment", "classification.canonical"],
    "sentiment": ["classification.sentiment"],
    "canonical": ["classification.canonical"],
    "trajectory": ["trajectory.email_lookup"],
    "tool_use": ["trajectory.email_lookup"],
    "grounded_qa": ["grounded.qa.factual"],
    "factual": ["grounded.qa.factual"],
    "math": ["math.add"],
}


def _family(
    family_id: str,
    family_label: str,
    description: str,
    task_type: str,
    observable_targets: List[str],
    allowed_eval_methods: List[str],
    default_difficulty: str = "easy",
    grounding_mode: str = "synthetic",
    failure_taxonomy: Optional[List[str]] = None,
    checker_name: Optional[str] = None,
    experimental: bool = False,
) -> Dict[str, Any]:
    return {
        "family_id": family_id,
        "family_label": family_label,
        "description": description,
        "task_type": task_type,
        "observable_targets": observable_targets,
        "allowed_eval_methods": allowed_eval_methods,
        "default_difficulty": default_difficulty,
        "grounding_mode": grounding_mode,
        "failure_taxonomy": failure_taxonomy or [],
        "checker_name": checker_name,
        "experimental": experimental,
        "materializer_type": task_type,
    }


# Canonical family definitions. materializer_type = task_type for registry compatibility.
FAMILIES: Dict[str, Dict[str, Any]] = {
    "extraction.email": _family(
        "extraction.email",
        "Email extraction",
        "Extract email address from text.",
        "json_extract_email",
        ["email"],
        ["exact_match", "schema_check", "rubric_judge"],
        failure_taxonomy=["EXACT_MATCH_FAILED"],
    ),
    "extraction.structured": _family(
        "extraction.structured",
        "Structured extraction",
        "Extract multiple fields (e.g. email, name) from text.",
        "json_extract_structured",
        ["email", "name"],
        ["programmatic_check", "schema_check", "rubric_judge"],
        failure_taxonomy=["PROGRAMMATIC_CHECK_FAILED"],
        checker_name="structured_extraction_v1",
    ),
    "classification.sentiment": _family(
        "classification.sentiment",
        "Sentiment classification",
        "Classify sentiment into positive/neutral/negative.",
        "json_classify_sentiment",
        ["label"],
        ["exact_match", "schema_check", "rubric_judge"],
        failure_taxonomy=["EXACT_MATCH_FAILED"],
    ),
    "classification.canonical": _family(
        "classification.canonical",
        "Classification with canonicalization",
        "Classify with label canonicalization (e.g. Positive -> positive).",
        "json_classify_canonical",
        ["label"],
        ["programmatic_check", "schema_check", "rubric_judge"],
        failure_taxonomy=["PROGRAMMATIC_CHECK_FAILED"],
        checker_name="classification_canonical_v1",
    ),
    "trajectory.email_lookup": _family(
        "trajectory.email_lookup",
        "Trajectory: email lookup then answer",
        "Use search_email_db tool then return email.",
        "trajectory_email_then_answer",
        ["email", "trajectory"],
        ["trajectory_check", "schema_check", "rubric_judge"],
        failure_taxonomy=["TRAJECTORY_CHECK_FAILED"],
    ),
    "grounded.qa.factual": _family(
        "grounded.qa.factual",
        "Factual grounded QA",
        "Answer question using only provided context.",
        "factual_grounded_qa",
        ["answer"],
        ["exact_match", "schema_check", "rubric_judge"],
        failure_taxonomy=["EXACT_MATCH_FAILED"],
    ),
    "math.add": _family(
        "math.add",
        "Integer addition",
        "Add two integers; output JSON with answer.",
        "json_math_add",
        ["answer"],
        ["programmatic_check", "exact_match", "schema_check", "rubric_judge"],
        failure_taxonomy=["PROGRAMMATIC_CHECK_FAILED"],
        checker_name="math_add_v1",
    ),
}


def get_supported_family_ids() -> List[str]:
    """Return the exact list of supported (non-experimental) catalog family IDs."""
    return [f["family_id"] for f in FAMILIES.values() if not f.get("experimental")]


def get_family_alias_map() -> Dict[str, str]:
    """Return the map from alias family_id -> canonical family_id for hybrid normalization."""
    return dict(FAMILY_ID_ALIAS_MAP)


def canonicalize_family_id(
    family_id: str,
    allow_experimental: bool = False,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Resolve family_id to a supported catalog ID or None.
    - If family_id is already supported, return (family_id, None).
    - Else if family_id is in alias map, return (mapped_family_id, repair_info).
    - Else if allow_experimental is True, return (family_id, None).
    - Else return (None, repair_info).
    repair_info: {"field": "family_id", "from": "<original>", "to": "<mapped or None>", "reason": "alias_map"|"unsupported"}
    """
    if not family_id:
        return (None, {"field": "family_id", "from": family_id, "to": None, "reason": "unsupported"})
    if get_family(family_id, allow_experimental=allow_experimental) is not None:
        return (family_id, None)
    alias_map = get_family_alias_map()
    if family_id in alias_map:
        mapped = alias_map[family_id]
        return (mapped, {"field": "family_id", "from": family_id, "to": mapped, "reason": "alias_map"})
    if allow_experimental:
        return (family_id, None)
    return (None, {"field": "family_id", "from": family_id, "to": None, "reason": "unsupported"})


def get_family(family_id: str, allow_experimental: bool = False) -> Optional[Dict[str, Any]]:
    """Return family definition if present and allowed (experimental gated)."""
    fam = FAMILIES.get(family_id)
    if fam is None:
        return None
    if fam.get("experimental") and not allow_experimental:
        return None
    return fam


def resolve_capability_focus_to_families(
    capability_focus: List[str],
    allow_experimental: bool = False,
) -> List[Dict[str, Any]]:
    """Map user capability_focus to a list of family definitions (deduplicated by family_id)."""
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for cap in (c.strip().lower() for c in capability_focus if c):
        for fid in CAPABILITY_TO_FAMILIES.get(cap, []):
            if fid in seen:
                continue
            fam = get_family(fid, allow_experimental=allow_experimental)
            if fam is not None:
                seen.add(fid)
                out.append(fam)
    return out


def list_families(allow_experimental: bool = False) -> List[Dict[str, Any]]:
    """Return all catalog families (optionally including experimental)."""
    return [
        dict(fam)
        for fam in FAMILIES.values()
        if allow_experimental or not fam.get("experimental")
    ]
