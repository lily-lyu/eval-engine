"""
Compiler: intent_spec + eval_families + prompt_blueprints + judge_specs -> compiled_plan.
Produces backward-compatible dataset_spec for the existing execution engine.
Enforces hard_min_fraction for failure-seeking intents.
"""
import math
from typing import Any, Dict, List

from ..core.failure_codes import COMPILE_CONTRACT_MISMATCH, MATERIALIZER_UNSUPPORTED
from ..core.family_catalog import FAMILY_CATALOG_VERSION, SUPPORTED_TASK_TYPES
from ..core.schema import validate_or_raise
from ..core.timeutil import now_iso

PLANNER_VERSION = "1.0.0"
COMPILER_VERSION = "1.0.0"
BLUEPRINT_SCHEMA_VERSION = "1.0.0"
JUDGE_SPEC_SCHEMA_VERSION = "1.0.0"

# Hard families that get min_count guarantees in failure-seeking runs
COMPILER_HARD_FAMILY_IDS = frozenset({
    "trajectory.email_lookup",
    "grounded.qa.factual",
    "extraction.structured",
})


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

    # Build capability_targets: one per blueprint (not one per family) so slots spread across blueprint variants
    judge_by_family = {j["family_id"]: j for j in judge_specs}
    family_by_id = {f["family_id"]: f for f in eval_families}
    blueprints_by_family: Dict[str, List[Dict[str, Any]]] = {}
    for b in prompt_blueprints:
        fid = b.get("family_id", "")
        if fid not in blueprints_by_family:
            blueprints_by_family[fid] = []
        blueprints_by_family[fid].append(b)

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
        blueprints = blueprints_by_family.get(family_id, [])
        if not blueprints:
            # Fallback: one target per family when no blueprints (e.g. legacy)
            bid = f"bp_{family_id.replace('.', '_')}_{fam.get('difficulty', 'easy')}"
            target_id = f"t_{family_id.replace('.', '_')}_{fam.get('difficulty', 'easy')}"
            capability_targets.append({
                "target_id": target_id,
                "domain_tags": list(domain_tags),
                "difficulty": fam.get("difficulty", "easy"),
                "task_type": task_type,
                "quota_weight": fam.get("slot_weight", 10),
                "family_id": family_id,
                "blueprint_id": bid,
                "judge_spec_id": judge.get("judge_spec_id", ""),
                "materializer_config": fam.get("materializer_config") or {},
            })
            continue
        slot_weight = fam.get("slot_weight", 10)
        weight_per_bp = max(1, slot_weight // len(blueprints))
        for bp in blueprints:
            bid = bp.get("blueprint_id", "")
            target_id = f"t_{family_id.replace('.', '_')}_{bid.replace('.', '_')}"[:64]
            ct = {
                "target_id": target_id,
                "domain_tags": list(domain_tags),
                "difficulty": fam.get("difficulty", "easy"),
                "task_type": task_type,
                "quota_weight": weight_per_bp,
                "family_id": family_id,
                "blueprint_id": bid,
                "judge_spec_id": judge.get("judge_spec_id", ""),
                "materializer_config": bp.get("materializer_config") or fam.get("materializer_config") or {},
            }
            capability_targets.append(ct)

    if not capability_targets:
        raise ValueError(
            f"{COMPILE_CONTRACT_MISMATCH}: compiled capability_targets is empty; "
            "at least one eval_family must produce a target."
        )

    # Failure-seeking: at least one slot per hard family (trajectory, grounded_qa, extraction.structured); honor hard_min_fraction
    planner_objective = (intent_spec.get("planner_objective") or "balanced").lower()
    difficulty_floor = (intent_spec.get("difficulty_floor") or "").lower()
    if (planner_objective == "failure_seeking" or difficulty_floor == "hard") and batch_size:
        hard_targets = [t for t in capability_targets if (t.get("family_id") or "") in COMPILER_HARD_FAMILY_IDS]
        if hard_targets:
            hard_families_seen = {t["family_id"] for t in hard_targets}
            # At least 1 slot per hard family (spread across blueprints of that family)
            hard_min_slots = max(len(hard_families_seen), int(math.ceil(batch_size * (intent_spec.get("hard_min_fraction") if isinstance(intent_spec.get("hard_min_fraction"), (int, float)) else 0.3))))
            per_target = max(1, int(math.ceil(hard_min_slots / len(hard_targets))))
            for t in capability_targets:
                if (t.get("family_id") or "") in COMPILER_HARD_FAMILY_IDS:
                    t["min_count"] = per_target

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
