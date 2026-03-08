"""
Compiler: intent_spec + eval_families + prompt_blueprints + judge_specs -> compiled_plan.
Produces backward-compatible dataset_spec for the existing execution engine.
"""
from typing import Any, Dict, List

from ..core.failure_codes import COMPILE_CONTRACT_MISMATCH, MATERIALIZER_UNSUPPORTED
from ..core.family_catalog import FAMILY_CATALOG_VERSION, SUPPORTED_TASK_TYPES
from ..core.schema import validate_or_raise
from ..core.timeutil import now_iso

PLANNER_VERSION = "1.0.0"
COMPILER_VERSION = "1.0.0"
BLUEPRINT_SCHEMA_VERSION = "1.0.0"
JUDGE_SPEC_SCHEMA_VERSION = "1.0.0"


def compile_to_plan(
    intent_spec: Dict[str, Any],
    eval_families: List[Dict[str, Any]],
    prompt_blueprints: List[Dict[str, Any]],
    judge_specs: List[Dict[str, Any]],
    compile_metadata_extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Compile to a full compiled_plan containing compiled_dataset_spec executable by current engine.
    compile_metadata_extra: optional keys (e.g. planner_mode, planner_model, fallback_used, llm_round_trips) merged into compile_metadata.
    """
    intent_name = intent_spec.get("intent_name", "unnamed")
    intent_version = intent_spec.get("intent_spec_version", "1.0.0")
    batch_size = intent_spec.get("batch_size", 10)
    defaults = intent_spec.get("defaults") or {}
    seed = int(defaults.get("seed", 42))
    defaults = {
        "seed": seed,
        "max_prompt_length": int(defaults.get("max_prompt_length", 20000)),
        "max_retries_per_stage": int(defaults.get("max_retries_per_stage", 2)),
    }

    # Build capability_targets from families + judge_specs
    judge_by_family = {j["family_id"]: j for j in judge_specs}
    blueprint_by_family = {b["family_id"]: b for b in prompt_blueprints}

    capability_targets: List[Dict[str, Any]] = []
    domain_tags = intent_spec.get("target_domain") or ["general"]
    for fam in eval_families:
        family_id = fam["family_id"]
        task_type = fam.get("materializer_type") or fam.get("task_type", "")
        if task_type not in SUPPORTED_TASK_TYPES:
            raise ValueError(
                f"{MATERIALIZER_UNSUPPORTED}: materializer_type/task_type '{task_type}' "
                f"for family '{family_id}' is not in task registry."
            )
        judge = judge_by_family.get(family_id, {})
        blueprint = blueprint_by_family.get(family_id, {})

        target_id = f"t_{family_id.replace('.', '_')}_{fam.get('difficulty', 'easy')}"
        ct = {
            "target_id": target_id,
            "domain_tags": list(domain_tags),
            "difficulty": fam.get("difficulty", "easy"),
            "task_type": task_type,
            "quota_weight": fam.get("slot_weight", 10),
            "family_id": family_id,
            "blueprint_id": blueprint.get("blueprint_id", ""),
            "judge_spec_id": judge.get("judge_spec_id", ""),
            "materializer_config": fam.get("materializer_config") or {},
        }
        capability_targets.append(ct)

    if not capability_targets:
        raise ValueError(
            f"{COMPILE_CONTRACT_MISMATCH}: compiled capability_targets is empty; "
            "at least one eval_family must produce a target."
        )

    dataset_name = intent_spec.get("dataset_name") or f"intent_{intent_name}_{intent_version}".replace(" ", "_")
    allowed_domain_tags = list(set(domain_tags)) if domain_tags else ["general"]

    compiled_dataset_spec = {
        "dataset_name": dataset_name,
        "dataset_spec_version": intent_version,
        "allowed_domain_tags": allowed_domain_tags,
        "capability_targets": capability_targets,
        "defaults": defaults,
    }

    validate_or_raise("dataset_spec.schema.json", compiled_dataset_spec)

    compile_metadata = {
        "intent_spec_version": intent_version,
        "family_catalog_version": FAMILY_CATALOG_VERSION,
        "blueprint_schema_version": BLUEPRINT_SCHEMA_VERSION,
        "judge_spec_schema_version": JUDGE_SPEC_SCHEMA_VERSION,
        "planner_version": PLANNER_VERSION,
        "compiler_version": COMPILER_VERSION,
        "compiled_at": now_iso(),
        "warnings": [],
    }
    if compile_metadata_extra:
        compile_metadata = {**compile_metadata, **compile_metadata_extra}

    compiled_plan = {
        "intent_spec": intent_spec,
        "eval_families": eval_families,
        "prompt_blueprints": prompt_blueprints,
        "judge_specs": judge_specs,
        "compiled_dataset_spec": compiled_dataset_spec,
        "compile_metadata": compile_metadata,
    }

    validate_or_raise("compiled_plan.schema.json", compiled_plan)
    return compiled_plan
