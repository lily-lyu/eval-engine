"""
Prompt program compiler: turn eval_families + intent_spec into list of prompt_blueprint.
Supports mode=deterministic | llm | hybrid.
"""
from pathlib import Path
from typing import Any, Dict, List

import json

from ..config import PLANNER_MODE, PLANNER_MODEL, PLANNER_TEMPERATURE, require_gemini_key_if_llm
from ..core.failure_codes import BLUEPRINT_SCHEMA_INVALID, LLM_BLUEPRINT_UNCOMPILABLE
from ..core.schema import validate_or_raise
from ..llm.structured import generate_and_parse_list, generate_and_validate

_PROMPT_DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts"


def _load_prompt(name: str) -> str:
    path = _PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def _blueprint_diversity_target(slot_weight: int, intent_spec: Dict[str, Any]) -> int:
    """Number of distinct blueprints to create for this family. >= 2 when slots allow, >= 3 for large/hard batches."""
    n = 1
    if slot_weight >= 2:
        n = 2
    if slot_weight >= 4:
        n = 3
    difficulty_mix = intent_spec.get("difficulty_mix") or {}
    if (difficulty_mix.get("hard", 0) or difficulty_mix.get("expert", 0)) and slot_weight >= 2:
        n = max(n, 3)
    return n


def _compile_blueprints_deterministic(
    eval_families: List[Dict[str, Any]],
    intent_spec: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """One or more blueprints per family; multiple when slot_weight >= 2/4 or hard-heavy batch."""
    blueprints: List[Dict[str, Any]] = []
    scenario_subtypes = ["default", "noisy", "multi", "distractor", "minimal", "wrapped"]
    for fam in eval_families:
        family_id = fam["family_id"]
        materializer_type = fam.get("materializer_type", family_id)
        slot_weight = fam.get("slot_weight", 10)
        difficulty = fam.get("difficulty", "easy")
        n_bp = _blueprint_diversity_target(slot_weight, intent_spec)

        for i in range(n_bp):
            suffix = f"v{i + 1}" if n_bp > 1 else ""
            blueprint_id = f"bp_{family_id.replace('.', '_')}_{difficulty}{suffix}".replace(" ", "_")[:64]
            subtype = scenario_subtypes[i % len(scenario_subtypes)]
            materializer_config = dict(fam.get("materializer_config") or {})
            materializer_config["scenario_subtype"] = subtype

            blueprint = {
                "blueprint_id": blueprint_id,
                "family_id": family_id,
                "blueprint_type": materializer_type,
                "instruction_template": "",
                "input_schema": {},
                "output_schema": {},
                "variation_axes": ["difficulty", "domain"],
                "grounding_recipe": {"mode": fam.get("grounding_mode", "synthetic")},
                "constraints": [],
                "negative_constraints": [],
                "dedup_fingerprint_fields": ["task_type", "difficulty", "domain_tags", "blueprint_id"],
                "materializer_type": materializer_type,
                "materializer_config": materializer_config,
            }

            try:
                validate_or_raise("prompt_blueprint.schema.json", blueprint)
            except ValueError as e:
                raise ValueError(f"{BLUEPRINT_SCHEMA_INVALID}: {e}") from e

            blueprints.append(blueprint)

    return blueprints


def _normalize_blueprints_to_families(
    blueprints: List[Dict[str, Any]],
    eval_families: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Hybrid: ensure each blueprint matches a family and has valid materializer_type."""
    family_by_id = {f["family_id"]: f for f in eval_families}
    normalized: List[Dict[str, Any]] = []
    for bp in blueprints:
        family_id = bp.get("family_id") or ""
        fam = family_by_id.get(family_id)
        if not fam:
            raise ValueError(
                f"{LLM_BLUEPRINT_UNCOMPILABLE}: blueprint family_id '{family_id}' not in eval_families."
            )
        materializer_type = fam.get("materializer_type") or fam.get("task_type", "")
        blueprint_id = bp.get("blueprint_id") or f"bp_{family_id.replace('.', '_')}_{fam.get('difficulty', 'easy')}"
        norm = {
            **bp,
            "family_id": family_id,
            "blueprint_id": blueprint_id,
            "blueprint_type": materializer_type,
            "materializer_type": materializer_type,
            "grounding_recipe": bp.get("grounding_recipe") or {"mode": fam.get("grounding_mode", "synthetic")},
        }
        try:
            validate_or_raise("prompt_blueprint.schema.json", norm)
        except ValueError as e:
            raise ValueError(f"{BLUEPRINT_SCHEMA_INVALID}: {e}") from e
        normalized.append(norm)
    return normalized


def compile_prompt_blueprints(
    eval_families: List[Dict[str, Any]],
    intent_spec: Dict[str, Any],
    *,
    mode: str | None = None,
    planner_model: str | None = None,
    planner_temperature: float | None = None,
) -> List[Dict[str, Any]]:
    """
    Compile eval_families + intent_spec to prompt_blueprints.
    - deterministic: one blueprint per family (v1).
    - llm: Gemini proposes blueprints; schema-validated.
    - hybrid: Gemini proposes, then normalize to families (family_id, materializer_type).
    """
    mode = (mode or PLANNER_MODE).lower()

    if mode == "deterministic":
        return _compile_blueprints_deterministic(eval_families, intent_spec)

    require_gemini_key_if_llm(mode)
    template = _load_prompt("prompt_program_compiler")
    payload = {"eval_families": eval_families, "intent_spec": intent_spec}
    prompt = template + "\n\n## Input\n\n```json\n" + json.dumps(payload, indent=2) + "\n```\n\nOutput only the JSON object with key `prompt_blueprints`."
    model = planner_model or PLANNER_MODEL
    temperature = planner_temperature if planner_temperature is not None else PLANNER_TEMPERATURE

    if mode == "hybrid":
        # Order: raw Gemini → parse JSON → normalize → validate (inside _normalize_blueprints_to_families)
        raw_list = generate_and_parse_list(
            prompt,
            parse_list_from_key="prompt_blueprints",
            model=model,
            temperature=temperature,
        )
        if not isinstance(raw_list, list):
            raise ValueError(f"{BLUEPRINT_SCHEMA_INVALID}: expected list of prompt_blueprints, got {type(raw_list).__name__}")
        return _normalize_blueprints_to_families(raw_list, eval_families)
    raw_list = generate_and_validate(
        prompt,
        "prompt_blueprint.schema.json",
        model=model,
        temperature=temperature,
        parse_list_from_key="prompt_blueprints",
    )
    if not isinstance(raw_list, list):
        raise ValueError(f"{BLUEPRINT_SCHEMA_INVALID}: expected list of prompt_blueprints, got {type(raw_list).__name__}")
    return raw_list
