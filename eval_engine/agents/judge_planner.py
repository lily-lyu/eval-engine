"""
Judge planner: compile judge_spec from eval_families + prompt_blueprints.
Supports mode=deterministic | llm | hybrid. Method priority: strongest machine-checkable; rubric_judge with evidence.
"""
from pathlib import Path
from typing import Any, Dict, List

import json

from ..config import PLANNER_MODE, PLANNER_MODEL, PLANNER_TEMPERATURE, require_gemini_key_if_llm
from ..core.failure_codes import JUDGE_SPEC_INVALID, LLM_JUDGE_METHOD_INVALID, RUBRIC_JUDGE_MISSING_EVIDENCE
from ..core.family_catalog import get_family
from ..core.schema import validate_or_raise
from ..llm.structured import generate_and_parse_list, generate_and_validate

_PROMPT_DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts"
METHOD_PRIORITY = [
    "programmatic_check",
    "exact_match",
    "trajectory_check",
    "schema_check",
    "rubric_judge",
]
ALLOWED_EVAL_METHODS = frozenset(METHOD_PRIORITY)


def _load_prompt(name: str) -> str:
    path = _PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def _select_method_for_family(fam: Dict[str, Any]) -> str:
    allowed = fam.get("allowed_eval_methods") or []
    for m in METHOD_PRIORITY:
        if m in allowed:
            return m
    return "rubric_judge"


def _compile_judge_specs_deterministic(
    eval_families: List[Dict[str, Any]],
    prompt_blueprints: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Current v1 behavior."""
    judge_specs: List[Dict[str, Any]] = []
    family_by_id = {f["family_id"]: f for f in eval_families}
    blueprint_by_family = {b["family_id"]: b for b in prompt_blueprints}

    for fam in eval_families:
        family_id = fam["family_id"]
        blueprint = blueprint_by_family.get(family_id, {})
        blueprint_id = blueprint.get("blueprint_id", family_id)

        catalog_fam = get_family(family_id, allow_experimental=True)
        selected = _select_method_for_family(fam)
        allowed = fam.get("allowed_eval_methods") or []

        if selected == "rubric_judge" and "rubric_judge" not in allowed:
            selected = "schema_check" if "schema_check" in allowed else (allowed[0] if allowed else "schema_check")

        failure_taxonomy = fam.get("failure_taxonomy") or []
        if catalog_fam:
            failure_taxonomy = catalog_fam.get("failure_taxonomy") or failure_taxonomy

        checker_name = None
        if catalog_fam and selected == "programmatic_check":
            checker_name = catalog_fam.get("checker_name")
        checker_config = {}
        if catalog_fam and selected == "programmatic_check":
            checker_config = {}

        if selected == "rubric_judge":
            evidence_requirements = {
                "required_evidence": ["reasoning", "citation"],
                "min_length": 1,
            }
        else:
            evidence_requirements = {}

        justification = (
            f"Selected {selected} for family {family_id} (observables: {fam.get('observable_targets', [])}); "
            "strongest machine-checkable method for observable targets."
        )

        spec = {
            "judge_spec_id": f"judge_{family_id.replace('.', '_')}",
            "family_id": family_id,
            "blueprint_id": blueprint_id,
            "eval_method": selected,
            "checker_config": checker_config,
            "expected_shape": {},
            "canonicalization_rules": [],
            "pass_fail_observables": list(fam.get("observable_targets", [])),
            "evidence_requirements": evidence_requirements,
            "adjudication_policy": "strict",
            "failure_taxonomy": failure_taxonomy,
            "method_justification": justification,
        }
        if checker_name is not None:
            spec["checker_name"] = checker_name

        try:
            validate_or_raise("judge_spec.schema.json", spec)
        except ValueError as e:
            raise ValueError(f"{JUDGE_SPEC_INVALID}: {e}") from e

        judge_specs.append(spec)

    return judge_specs


def _infer_checker_name(spec: Dict[str, Any], catalog_fam: Dict[str, Any] | None) -> str | None:
    """Derive checker_name from catalog/family when eval_method is programmatic_check. Never invent."""
    if not catalog_fam:
        return None
    if (spec.get("eval_method") or "") != "programmatic_check":
        return None
    return catalog_fam.get("checker_name")


def _normalize_judge_specs(
    judge_specs: List[Dict[str, Any]],
    eval_families: List[Dict[str, Any]],
    prompt_blueprints: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Hybrid: enforce eval_method in allowed list; fill checker_name from catalog; evidence_requirements default {}."""
    family_by_id = {f["family_id"]: f for f in eval_families}
    blueprint_by_family = {b["family_id"]: b for b in prompt_blueprints}
    normalized: List[Dict[str, Any]] = []
    for spec in judge_specs:
        family_id = spec.get("family_id") or ""
        fam = family_by_id.get(family_id)
        if not fam:
            raise ValueError(
                f"{LLM_JUDGE_METHOD_INVALID}: judge_spec family_id '{family_id}' not in eval_families."
            )
        blueprint = blueprint_by_family.get(family_id, {})
        blueprint_id = blueprint.get("blueprint_id", family_id)

        selected = spec.get("eval_method") or "schema_check"
        allowed = fam.get("allowed_eval_methods") or []
        if selected not in ALLOWED_EVAL_METHODS:
            selected = _select_method_for_family(fam)
        elif selected not in allowed:
            selected = _select_method_for_family(fam)

        catalog_fam = get_family(family_id, allow_experimental=True)
        failure_taxonomy = spec.get("failure_taxonomy") or fam.get("failure_taxonomy") or []
        if catalog_fam:
            failure_taxonomy = catalog_fam.get("failure_taxonomy") or failure_taxonomy

        # checker_name: fill from catalog when None (deterministic; do not rely on Gemini)
        checker_name = spec.get("checker_name")
        if checker_name is None:
            checker_name = _infer_checker_name({**spec, "eval_method": selected}, catalog_fam)
        checker_config = spec.get("checker_config") if spec.get("checker_config") is not None else {}

        # evidence_requirements: never leave null; use {} when not rubric
        evidence_requirements = spec.get("evidence_requirements")
        if selected == "rubric_judge":
            evidence_requirements = evidence_requirements if evidence_requirements else {
                "required_evidence": ["reasoning", "citation"],
                "min_length": 1,
            }
            if not evidence_requirements:
                raise ValueError(
                    f"{RUBRIC_JUDGE_MISSING_EVIDENCE}: rubric_judge requires evidence_requirements; family_id={family_id}"
                )
        else:
            evidence_requirements = evidence_requirements if evidence_requirements is not None else {}

        pass_fail_observables = list(fam.get("observable_targets", spec.get("pass_fail_observables", [])))

        expected_shape = spec.get("expected_shape")
        if expected_shape is not None and not isinstance(expected_shape, dict):
            expected_shape = {}
        if expected_shape is None:
            expected_shape = {}
        canonicalization_rules = spec.get("canonicalization_rules")
        if canonicalization_rules is None or not isinstance(canonicalization_rules, list):
            canonicalization_rules = []

        norm = {
            **spec,
            "family_id": family_id,
            "blueprint_id": blueprint_id,
            "eval_method": selected,
            "checker_config": checker_config,
            "expected_shape": expected_shape,
            "canonicalization_rules": canonicalization_rules,
            "pass_fail_observables": pass_fail_observables,
            "evidence_requirements": evidence_requirements,
            "failure_taxonomy": failure_taxonomy,
        }
        if checker_name is not None:
            norm["checker_name"] = checker_name
        elif "checker_name" in norm:
            del norm["checker_name"]
        for key in ("checker_config", "evidence_requirements", "expected_shape"):
            if norm.get(key) is None:
                norm[key] = {}
        try:
            validate_or_raise("judge_spec.schema.json", norm)
        except ValueError as e:
            raise ValueError(f"{JUDGE_SPEC_INVALID}: {e}") from e
        normalized.append(norm)
    return normalized


def compile_judge_specs(
    eval_families: List[Dict[str, Any]],
    prompt_blueprints: List[Dict[str, Any]],
    *,
    mode: str | None = None,
    planner_model: str | None = None,
    planner_temperature: float | None = None,
) -> List[Dict[str, Any]]:
    """
    Compile eval_families + prompt_blueprints to judge_specs.
    - deterministic: v1 behavior (method priority, evidence for rubric).
    - llm: Gemini proposes judge_specs; schema-validated.
    - hybrid: Gemini proposes, then normalize (allowed methods, evidence_requirements, observables).
    """
    mode = (mode or PLANNER_MODE).lower()

    if mode == "deterministic":
        return _compile_judge_specs_deterministic(eval_families, prompt_blueprints)

    require_gemini_key_if_llm(mode)
    template = _load_prompt("judge_planner")
    payload = {"eval_families": eval_families, "prompt_blueprints": prompt_blueprints}
    prompt = template + "\n\n## Input\n\n```json\n" + json.dumps(payload, indent=2) + "\n```\n\nOutput only the JSON object with key `judge_specs`."
    model = planner_model or PLANNER_MODEL
    temperature = planner_temperature if planner_temperature is not None else PLANNER_TEMPERATURE

    if mode == "hybrid":
        # Order: raw Gemini → parse JSON → normalize (fill checker_name, evidence_requirements) → validate
        raw_list = generate_and_parse_list(
            prompt,
            parse_list_from_key="judge_specs",
            model=model,
            temperature=temperature,
        )
        if not isinstance(raw_list, list):
            raise ValueError(f"{JUDGE_SPEC_INVALID}: expected list of judge_specs, got {type(raw_list).__name__}")
        return _normalize_judge_specs(raw_list, eval_families, prompt_blueprints)
    # llm: parse then validate (no normalization)
    raw_list = generate_and_validate(
        prompt,
        "judge_spec.schema.json",
        model=model,
        temperature=temperature,
        parse_list_from_key="judge_specs",
    )
    if not isinstance(raw_list, list):
        raise ValueError(f"{JUDGE_SPEC_INVALID}: expected list of judge_specs, got {type(raw_list).__name__}")
    return raw_list
