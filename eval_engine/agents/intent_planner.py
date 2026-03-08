"""
Intent planner: decompose high-level intent_spec into a list of eval_family.
Supports mode=deterministic | llm | hybrid. Catalog-anchored; LLM may propose, compiler validates.
"""
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..config import (
    PLANNER_MODE,
    PLANNER_MODEL,
    PLANNER_TEMPERATURE,
    require_gemini_key_if_llm,
)
from ..core.failure_codes import (
    FAMILY_CATALOG_MISS,
    INTENT_SCHEMA_INVALID,
    INTENT_UNDER_SPECIFIED,
    LLM_FAMILY_UNSUPPORTED,
    UNSUPPORTED_CAPABILITY_FOCUS,
)
from ..core.family_catalog import (
    SUPPORTED_TASK_TYPES,
    canonicalize_family_id,
    get_family,
    get_family_alias_map,
    resolve_capability_focus_to_families,
)
from ..core.schema import validate_or_raise
from ..llm.structured import generate_and_validate

_PROMPT_DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts"
ALLOWED_EVAL_METHODS_WHITELIST = frozenset(
    {"programmatic_check", "exact_match", "trajectory_check", "schema_check", "rubric_judge"}
)

# Families we upweight for failure_seeking / difficulty_floor=hard (trajectory, grounded_qa, extraction.structured)
HARD_FAMILY_IDS = frozenset({
    "trajectory.email_lookup",
    "grounded.qa.factual",
    "extraction.structured",
})
# Families we downweight in failure_seeking so batch does not collapse to easy-only
EASY_FAMILY_IDS = frozenset({
    "math.add",
    "classification.canonical",
})
# Map family_id prefix/category to hard_family_bias key (e.g. trajectory, grounded_qa, extraction, classification, math)
FAMILY_TO_BIAS_KEY = {
    "trajectory.email_lookup": "trajectory",
    "grounded.qa.factual": "grounded_qa",
    "extraction.structured": "extraction",
    "extraction.email": "extraction",
    "classification.sentiment": "classification",
    "classification.canonical": "classification",
    "math.add": "math",
}


def _load_prompt(name: str) -> str:
    path = _PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def _plan_intent_deterministic(intent_spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Current v1 behavior: catalog-only resolution."""
    try:
        validate_or_raise("intent_spec.schema.json", intent_spec)
    except ValueError as e:
        raise ValueError(f"{INTENT_SCHEMA_INVALID}: {e}") from e

    capability_focus = intent_spec.get("capability_focus") or []
    if not capability_focus:
        raise ValueError(
            f"{INTENT_UNDER_SPECIFIED}: capability_focus is required and must be non-empty; "
            "specify at least one capability (e.g. extraction, classification, trajectory)."
        )

    planner_defaults = intent_spec.get("planner_defaults") or {}
    allow_experimental = bool(planner_defaults.get("allow_experimental_families", False))
    max_families = int(planner_defaults.get("max_families", 20))

    families_raw = resolve_capability_focus_to_families(capability_focus, allow_experimental=allow_experimental)
    if not families_raw:
        raise ValueError(
            f"{UNSUPPORTED_CAPABILITY_FOCUS}: no catalog families for capability_focus={capability_focus}; "
            "use supported capabilities (e.g. extraction, classification, trajectory, grounded_qa, math)."
        )

    if len(families_raw) > max_families:
        families_raw = families_raw[:max_families]

    target_domain = intent_spec.get("target_domain") or []
    difficulty_mix = intent_spec.get("difficulty_mix") or {}
    planner_objective = (intent_spec.get("planner_objective") or "balanced").lower()
    difficulty_floor = (intent_spec.get("difficulty_floor") or "").lower()
    hard_family_bias = intent_spec.get("hard_family_bias") or {}

    default_difficulty = "easy"
    if difficulty_floor in ("medium", "hard"):
        default_difficulty = difficulty_floor
    elif difficulty_mix:
        for d in ("easy", "medium", "hard", "expert"):
            if difficulty_mix.get(d, 0) > 0:
                default_difficulty = d
                break

    failure_seeking = planner_objective == "failure_seeking" or default_difficulty == "hard" or difficulty_floor == "hard"

    grounding_requirements = intent_spec.get("grounding_requirements") or ["synthetic"]
    grounding_mode = grounding_requirements[0] if grounding_requirements else "synthetic"

    eval_families: List[Dict[str, Any]] = []
    for fam in families_raw:
        family_id = fam["family_id"]
        task_type = fam["task_type"]
        allowed_eval = fam.get("allowed_eval_methods", [])
        catalog_grounding = fam.get("grounding_mode", "synthetic")
        use_grounding = catalog_grounding if catalog_grounding in grounding_requirements else "synthetic"

        slot_weight = 10
        if intent_spec.get("batch_size"):
            slot_weight = max(1, min(100, intent_spec["batch_size"] // max(1, len(families_raw))))

        difficulty = default_difficulty
        risk_tier = (intent_spec.get("risk_focus") or [""])[0] or "default"
        if failure_seeking:
            if family_id in HARD_FAMILY_IDS:
                slot_weight = max(1, min(100, slot_weight * 3))
                difficulty = "hard"
                risk_tier = "failure_seeking"
            elif family_id in EASY_FAMILY_IDS:
                slot_weight = max(1, slot_weight // 3)
        if hard_family_bias:
            bias_key = FAMILY_TO_BIAS_KEY.get(family_id)
            if bias_key is not None and isinstance(hard_family_bias.get(bias_key), (int, float)):
                slot_weight = max(1, min(100, int(slot_weight * hard_family_bias[bias_key])))

        eval_fam = {
            "family_id": family_id,
            "family_label": fam.get("family_label", family_id),
            "objective": fam.get("description", ""),
            "observable_targets": list(fam.get("observable_targets", [])),
            "grounding_mode": use_grounding,
            "allowed_eval_methods": allowed_eval,
            "difficulty": difficulty,
            "risk_tier": risk_tier,
            "slot_weight": slot_weight,
            "materializer_type": fam.get("materializer_type", task_type),
            "materializer_config": {},
            "dedup_group": family_id,
            "failure_taxonomy": list(fam.get("failure_taxonomy", [])),
        }
        eval_families.append(eval_fam)

    if not eval_families:
        raise ValueError(
            f"{FAMILY_CATALOG_MISS}: no families could be selected for capability_focus={capability_focus}."
        )

    return eval_families


def _normalize_eval_families_to_catalog(
    eval_families: List[Dict[str, Any]],
    allow_experimental: bool,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Map LLM-proposed families to catalog where possible; enforce whitelist and task types.
    Uses canonicalize_family_id for safe alias mapping (e.g. trajectory.email_tool -> trajectory.email_lookup).
    Returns (normalized_families, repair_warnings)."""
    normalized: List[Dict[str, Any]] = []
    warnings: List[str] = []
    alias_map = get_family_alias_map()

    for fam in eval_families:
        original_id = fam.get("family_id") or ""
        canonical_id, repair_info = canonicalize_family_id(original_id, allow_experimental=allow_experimental)
        if canonical_id is None:
            # Unsupported and no alias; suggest alias if one exists (for error message)
            suggested = alias_map.get(original_id)
            msg = (
                f"{LLM_FAMILY_UNSUPPORTED}: family_id '{original_id}' is not in the catalog and allow_experimental is false."
            )
            if suggested:
                msg += f" Did you mean '{suggested}'?"
            raise ValueError(msg)
        if repair_info and repair_info.get("reason") == "alias_map":
            warnings.append(
                f"Normalized family_id from '{repair_info['from']}' to '{repair_info['to']}' via alias_map"
            )
        family_id = canonical_id
        catalog_fam = get_family(family_id, allow_experimental=allow_experimental)
        if catalog_fam:
            # Overlay catalog: allowed_eval_methods, materializer_type, observable_targets, etc.
            allowed = list(catalog_fam.get("allowed_eval_methods", []))
            allowed = [m for m in allowed if m in ALLOWED_EVAL_METHODS_WHITELIST]
            if not allowed:
                allowed = ["schema_check"]
            materializer_type = catalog_fam.get("materializer_type") or catalog_fam.get("task_type", "")
            if materializer_type not in SUPPORTED_TASK_TYPES:
                raise ValueError(
                    f"{LLM_FAMILY_UNSUPPORTED}: family_id={family_id} materializer_type '{materializer_type}' not in task registry."
                )
            norm = {
                **fam,
                "family_id": family_id,
                "allowed_eval_methods": allowed,
                "materializer_type": materializer_type,
                "observable_targets": list(catalog_fam.get("observable_targets", fam.get("observable_targets", []))),
                "failure_taxonomy": list(catalog_fam.get("failure_taxonomy", fam.get("failure_taxonomy", []))),
            }
            normalized.append(norm)
        else:
            # allow_experimental and canonical_id passed but get_family returned None (experimental family?)
            if not allow_experimental:
                raise ValueError(
                    f"{LLM_FAMILY_UNSUPPORTED}: family_id '{original_id}' is not in the catalog and allow_experimental is false."
                )
            allowed = list(fam.get("allowed_eval_methods", []))
            allowed = [m for m in allowed if m in ALLOWED_EVAL_METHODS_WHITELIST]
            if not allowed:
                allowed = ["schema_check"]
            materializer_type = (fam.get("materializer_type") or "").strip()
            if materializer_type and materializer_type not in SUPPORTED_TASK_TYPES:
                raise ValueError(
                    f"{LLM_FAMILY_UNSUPPORTED}: experimental family_id={family_id} materializer_type '{materializer_type}' not in task registry."
                )
            if not materializer_type:
                raise ValueError(
                    f"{LLM_FAMILY_UNSUPPORTED}: experimental family_id={family_id} requires materializer_type from catalog or supported list."
                )
            norm = {**fam, "family_id": family_id, "allowed_eval_methods": allowed, "materializer_type": materializer_type}
            normalized.append(norm)
    return normalized, warnings


def plan_intent(
    intent_spec: Dict[str, Any],
    *,
    mode: str | None = None,
    planner_model: str | None = None,
    planner_temperature: float | None = None,
    allow_experimental: bool | None = None,
    warnings_out: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """
    Decompose intent_spec into eval_families. Supports deterministic | llm | hybrid.
    - deterministic: catalog-only (current v1).
    - llm: Gemini proposes schema-validated eval_families.
    - hybrid: Gemini proposes, then catalog normalization / whitelist enforcement (including alias map).
    If warnings_out is provided and hybrid normalization repairs family_ids, repair messages are appended.
    """
    mode = (mode or PLANNER_MODE).lower()
    planner_defaults = intent_spec.get("planner_defaults") or {}
    allow_exp = allow_experimental if allow_experimental is not None else bool(planner_defaults.get("allow_experimental_families", False))

    if mode == "deterministic":
        return _plan_intent_deterministic(intent_spec)

    require_gemini_key_if_llm(mode)
    template = _load_prompt("intent_planner")
    import json
    prompt = template + "\n\n## Input intent_spec\n\n```json\n" + json.dumps(intent_spec, indent=2) + "\n```\n\nOutput only the JSON object with key `eval_families`."
    raw_list = generate_and_validate(
        prompt,
        "eval_family.schema.json",
        model=planner_model or PLANNER_MODEL,
        temperature=planner_temperature if planner_temperature is not None else PLANNER_TEMPERATURE,
        parse_list_from_key="eval_families",
    )
    if not isinstance(raw_list, list):
        raise ValueError(f"{INTENT_SCHEMA_INVALID}: expected list of eval_families, got {type(raw_list).__name__}")
    if mode == "hybrid":
        raw_list, norm_warnings = _normalize_eval_families_to_catalog(raw_list, allow_experimental=allow_exp)
        if warnings_out is not None:
            warnings_out.extend(norm_warnings)
    if not raw_list:
        raise ValueError(
            f"{FAMILY_CATALOG_MISS}: no eval_families produced (or all filtered out)."
        )
    return raw_list
