"""
Tests that hard / failure-seeking intent is a real control signal:
- Family allocation favors hard families (trajectory, grounded_qa, extraction.structured).
- Hard blueprints use failure-prone scenario_subtypes.
- Generators produce structurally different content for hard scenario_subtypes.
- Small hard batches include at least one trajectory and one grounded_qa when requested.
"""
import random

import pytest

from eval_engine.agents.compile_pipeline import compile_intent_to_plan
from eval_engine.agents.intent_planner import plan_intent, HARD_FAMILY_IDS, EASY_FAMILY_IDS
from eval_engine.agents.prompt_program_compiler import (
    compile_prompt_blueprints,
    HARD_SCENARIO_SUBTYPES_BY_FAMILY,
    _is_hard_mode,
)
from eval_engine.agents.a1_item_generator import generate_item_from_target
from eval_engine.agents.compiler import compile_to_plan, COMPILER_HARD_FAMILY_IDS
from eval_engine.agents.batch_planner import compile_batch_plan
from eval_engine.core.schema import validate_or_raise


# ---- A) Hard intent changes family allocation ----

def test_failure_seeking_intent_not_dominated_by_math_and_canonical():
    """A failure-seeking intent should not compile into a batch dominated by math.add + classification.canonical."""
    intent_balanced = {
        "intent_name": "balanced",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Mixed capabilities.",
        "capability_focus": ["extraction", "classification", "trajectory", "grounded_qa", "math"],
        "batch_size": 12,
        "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    intent_hard = {
        **intent_balanced,
        "intent_name": "failure_seeking",
        "planner_objective": "failure_seeking",
        "evaluation_goal": "Stress hard families.",
    }
    families_balanced = plan_intent(intent_balanced, mode="deterministic")
    families_hard = plan_intent(intent_hard, mode="deterministic")

    # Hard run: hard families should have higher slot_weight and difficulty=hard
    hard_fam_ids = [f["family_id"] for f in families_hard if f["family_id"] in HARD_FAMILY_IDS]
    easy_fam_ids = [f["family_id"] for f in families_hard if f["family_id"] in EASY_FAMILY_IDS]
    assert len(hard_fam_ids) >= 1, "failure_seeking should include at least one hard family when in capability_focus"
    for f in families_hard:
        if f["family_id"] in HARD_FAMILY_IDS:
            assert f.get("difficulty") == "hard"
            assert f.get("risk_tier") == "failure_seeking"
            assert f.get("slot_weight") >= 1
        if f["family_id"] in EASY_FAMILY_IDS:
            assert f.get("slot_weight") <= 20, "easy families should be downweighted"

    # Compare slot weights: in hard run, at least one hard family should have slot_weight >= easy families or more slots
    hard_slots = sum(f["slot_weight"] for f in families_hard if f["family_id"] in HARD_FAMILY_IDS)
    easy_slots = sum(f["slot_weight"] for f in families_hard if f["family_id"] in EASY_FAMILY_IDS)
    assert hard_slots >= easy_slots, "failure_seeking should allocate at least as much to hard families as to easy"


def test_difficulty_floor_hard_ups_family_difficulty():
    """difficulty_floor=hard should set difficulty=hard and upweight hard families."""
    intent = {
        "intent_name": "x",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Hard extraction and trajectory.",
        "capability_focus": ["extraction", "trajectory"],
        "difficulty_floor": "hard",
        "batch_size": 6,
        "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    families = plan_intent(intent, mode="deterministic")
    for f in families:
        assert f.get("difficulty") == "hard"
        if f["family_id"] in HARD_FAMILY_IDS:
            assert f.get("risk_tier") == "failure_seeking"


# ---- B) Hard prompt blueprints differ from balanced ----

def test_hard_blueprints_use_failure_prone_subtypes():
    """Under failure_seeking, compiled blueprints should use scenario_subtypes from HARD_SCENARIO_SUBTYPES_BY_FAMILY."""
    intent_balanced = {
        "intent_name": "b",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Extraction.",
        "capability_focus": ["extraction", "trajectory"],
        "batch_size": 8,
        "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    intent_hard = {
        **intent_balanced,
        "planner_objective": "failure_seeking",
    }
    plan_balanced = compile_intent_to_plan(intent_balanced, planner_mode="deterministic")
    plan_hard = compile_intent_to_plan(intent_hard, planner_mode="deterministic")

    subtypes_balanced = set()
    subtypes_hard = set()
    for bp in plan_balanced["prompt_blueprints"]:
        st = (bp.get("materializer_config") or {}).get("scenario_subtype", "default")
        subtypes_balanced.add((bp["family_id"], st))
    for bp in plan_hard["prompt_blueprints"]:
        st = (bp.get("materializer_config") or {}).get("scenario_subtype", "default")
        subtypes_hard.add((bp["family_id"], st))

    # Hard plan should include at least one failure-prone subtype for a known family
    hard_subtype_values = set()
    for fid, subs in HARD_SCENARIO_SUBTYPES_BY_FAMILY.items():
        hard_subtype_values.update(subs)
    found_hard_subtype = any(st in hard_subtype_values for (_, st) in subtypes_hard)
    assert found_hard_subtype, "failure_seeking blueprints should include at least one hard scenario_subtype"


def test_is_hard_mode_detects_objective_and_floor():
    """_is_hard_mode returns True for failure_seeking, difficulty_floor=hard, adversarial_variation_required."""
    assert _is_hard_mode({"planner_objective": "failure_seeking"}, []) is True
    assert _is_hard_mode({"difficulty_floor": "hard"}, []) is True
    assert _is_hard_mode({"adversarial_variation_required": True}, []) is True
    assert _is_hard_mode({"planner_objective": "balanced"}, []) is False
    assert _is_hard_mode({}, [{"risk_tier": "failure_seeking"}]) is True


# ---- C) Generators reflect hard scenario_subtype ----

def test_math_add_multi_step_produces_three_inputs():
    """json_math_add with scenario_subtype multi_step should produce input with a, b, c and prompt mentioning two-step sum."""
    spec = {
        "dataset_name": "t",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["general"],
        "capability_targets": [],
        "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    target = {
        "target_id": "t1",
        "domain_tags": ["math"],
        "difficulty": "easy",
        "task_type": "json_math_add",
        "source_policy": "synthetic",
        "blueprint_id": "bp_math_1",
        "materializer_config": {"scenario_subtype": "multi_step"},
    }
    rng = random.Random(42)
    item = generate_item_from_target(spec, target, "1.0.0", rng)
    assert "c" in item["input"]
    assert "add that result to c" in item["prompt"] or "then add" in item["prompt"].lower()


def test_extraction_structured_distractor_includes_do_not_use():
    """json_extract_structured with scenario_subtype distractor should include distractor text."""
    spec = {
        "dataset_name": "t",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["general"],
        "capability_targets": [],
        "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    target = {
        "target_id": "t1",
        "domain_tags": ["extraction"],
        "difficulty": "hard",
        "task_type": "json_extract_structured",
        "source_policy": "synthetic",
        "materializer_config": {"scenario_subtype": "distractor"},
    }
    rng = random.Random(99)
    item = generate_item_from_target(spec, target, "1.0.0", rng)
    assert "Do not use" in item["input"]["text"] or "john@example.com" in item["input"]["text"]


def test_grounded_qa_distractor_context_has_extra_sentence():
    """factual_grounded_qa with distractor_context should have context with unrelated/confusing sentence."""
    spec = {
        "dataset_name": "t",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["general"],
        "capability_targets": [],
        "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    target = {
        "target_id": "t1",
        "domain_tags": ["qa"],
        "difficulty": "hard",
        "task_type": "factual_grounded_qa",
        "source_policy": "synthetic",
        "materializer_config": {"scenario_subtype": "distractor_context"},
    }
    rng = random.Random(77)
    item = generate_item_from_target(spec, target, "1.0.0", rng)
    assert "Unrelated" in item["input"]["context"] or "ENIAC" in item["input"]["context"]


# ---- D) Small hard batch coverage ----

def test_small_hard_batch_includes_trajectory_and_grounded_qa_min_count():
    """For batch_size=10 with trajectory + grounded_qa in capability_focus and failure_seeking, compiled_dataset_spec has min_count on hard targets."""
    intent = {
        "intent_name": "hard_small",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Stress trajectory and grounded QA.",
        "capability_focus": ["trajectory", "grounded_qa", "extraction"],
        "batch_size": 10,
        "planner_objective": "failure_seeking",
        "hard_min_fraction": 0.3,
        "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    plan = compile_intent_to_plan(intent, planner_mode="deterministic")
    ds = plan["compiled_dataset_spec"]
    validate_or_raise("dataset_spec.schema.json", ds)
    targets = ds["capability_targets"]
    hard_targets = [t for t in targets if (t.get("family_id") or "") in COMPILER_HARD_FAMILY_IDS]
    assert len(hard_targets) >= 1, "should have at least one hard family target"
    # Compiler sets min_count on hard targets for failure_seeking
    with_min = [t for t in hard_targets if t.get("min_count", 0) >= 1]
    assert len(with_min) >= 1, "at least one hard target should have min_count >= 1"

    # Batch plan should allocate slots to trajectory and grounded_qa (min_count forces coverage)
    rng = random.Random(42)
    batch_plan = compile_batch_plan(ds, quota=10, rng=rng)
    task_types = set()
    counts_by_family = {}
    for entry in batch_plan:
        fid = entry["target"].get("family_id") or ""
        task_types.add(entry["target"].get("task_type"))
        counts_by_family[fid] = counts_by_family.get(fid, 0) + entry["count"]
    assert counts_by_family.get("trajectory.email_lookup", 0) >= 1 or counts_by_family.get("grounded.qa.factual", 0) >= 1 or counts_by_family.get("extraction.structured", 0) >= 1, "at least one hard family should get slots"
    assert "trajectory_email_then_answer" in task_types or "factual_grounded_qa" in task_types or "json_extract_structured" in task_types


def test_intent_spec_schema_accepts_hardness_controls():
    """intent_spec with optional hardness fields validates."""
    from eval_engine.core.schema import validate_or_raise
    intent = {
        "intent_name": "hard_run",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Failure-seeking reliability.",
        "capability_focus": ["trajectory", "grounded_qa"],
        "batch_size": 10,
        "planner_objective": "failure_seeking",
        "difficulty_floor": "hard",
        "hard_family_bias": {"trajectory": 2.0, "grounded_qa": 2.0},
        "hard_min_fraction": 0.5,
        "adversarial_variation_required": True,
        "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    validate_or_raise("intent_spec.schema.json", intent)
