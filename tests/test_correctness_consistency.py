"""
Must-checks for correctness and consistency beyond schema drift and e2e contract:
- Determinism: same intent + seed yields same plan shape and batch sum.
- Oracle + mock_sut roundtrip: generated item -> oracle -> mock_sut output -> verify passes.
- Judge coverage: every eval_family has a judge_spec.
- Version bundle validates against schema.
- Catalog consistency: families and task_types in plan exist in catalog/registry.
"""
import json
import random
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_determinism_same_intent_same_seed_same_plan_shape():
    """Same intent + seed -> same number of families, same capability_targets length, same batch_plan sum."""
    from eval_engine.agents.compile_pipeline import compile_intent_to_plan
    from eval_engine.agents.batch_planner import compile_batch_plan

    intent = {
        "intent_name": "det",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Determinism check.",
        "capability_focus": ["extraction", "trajectory", "math"],
        "batch_size": 8,
        "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    plan1 = compile_intent_to_plan(intent, planner_mode="deterministic")
    plan2 = compile_intent_to_plan(intent, planner_mode="deterministic")

    assert len(plan1["eval_families"]) == len(plan2["eval_families"])
    ds1 = plan1["compiled_dataset_spec"]
    ds2 = plan2["compiled_dataset_spec"]
    assert len(ds1["capability_targets"]) == len(ds2["capability_targets"])
    assert ds1["dataset_spec_version"] == ds2["dataset_spec_version"]

    rng = random.Random(42)
    quota = intent["batch_size"]
    batch1 = compile_batch_plan(ds1, quota, rng)
    rng2 = random.Random(42)
    batch2 = compile_batch_plan(ds2, quota, rng2)
    assert sum(e["count"] for e in batch1) == quota
    assert sum(e["count"] for e in batch2) == quota
    assert sum(e["count"] for e in batch1) == sum(e["count"] for e in batch2)


def test_oracle_mock_sut_verify_roundtrip_per_task_type():
    """For each task_type (except trajectory): generate item -> oracle -> mock_sut -> verify -> pass. Trajectory needs tool_trace from SUT envelope."""
    from eval_engine.agents.a1_item_generator import generate_item_from_target
    from eval_engine.agents.a1b_oracle_builder import build_oracle
    from eval_engine.agents.a2_verifier import verify
    from eval_engine.core.hashing import sha256_bytes
    from eval_engine.tasks.registry import get_task_registry

    spec = {
        "dataset_name": "roundtrip",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["general"],
        "capability_targets": [],
        "defaults": {"seed": 99, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    rng = random.Random(99)
    registry = get_task_registry()
    # trajectory_email_then_answer requires tool_trace from SUT envelope; mock_sut returns JSON only
    skip_trajectory = {"trajectory_email_then_answer"}

    for task_type in registry:
        if task_type in skip_trajectory:
            continue
        target = {
            "target_id": f"t_{task_type}",
            "domain_tags": ["general"],
            "difficulty": "easy",
            "task_type": task_type,
            "source_policy": "synthetic",
        }
        item = generate_item_from_target(spec, target, "1.0.0", rng)
        oracle = build_oracle(item)
        raw_output = registry[task_type].mock_sut(item)
        b = raw_output.encode("utf-8")
        raw_output_ref = {
            "sha256": sha256_bytes(b),
            "uri": "test://roundtrip/raw.txt",
            "mime": "application/json",
            "bytes": len(b),
        }
        er = verify(
            item, oracle, raw_output, model_version="mock-1", seed=99, raw_output_ref=raw_output_ref
        )
        assert er["verdict"] == "pass", (
            f"task_type={task_type} expected pass got verdict={er['verdict']} error_type={er.get('error_type')}"
        )


def test_compile_judge_spec_coverage():
    """After compile, every eval_family has at least one judge_spec (by family_id)."""
    from eval_engine.agents.compile_pipeline import compile_intent_to_plan

    intent = {
        "intent_name": "judge_cov",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Judge coverage.",
        "capability_focus": ["extraction", "classification", "math", "trajectory", "grounded_qa"],
        "batch_size": 6,
        "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    plan = compile_intent_to_plan(intent, planner_mode="deterministic")
    families = plan["eval_families"]
    judge_specs = plan["judge_specs"]
    family_ids = {f["family_id"] for f in families}
    judge_family_ids = {j["family_id"] for j in judge_specs}
    missing = family_ids - judge_family_ids
    assert not missing, f"Families without judge_spec: {missing}"


def test_version_bundle_validates():
    """build_version_bundle(...) output validates against version_bundle.schema.json."""
    from eval_engine.core.schema import validate_or_raise
    from eval_engine.core.versioning import build_version_bundle

    spec = {"dataset_spec_version": "1.0.0"}
    bundle = build_version_bundle(spec, "mock-1", "a" * 64, 42)
    validate_or_raise("version_bundle.schema.json", bundle)
    assert bundle["dataset_spec_version"] == "1.0.0"
    assert bundle["model_version"] == "mock-1"
    assert bundle["seed"] == 42
    assert len(bundle["tool_snapshot_hash"]) == 64


def test_catalog_consistency_plan_families_in_catalog():
    """Every family_id in eval_families is in family catalog (or resolved via alias)."""
    from eval_engine.agents.compile_pipeline import compile_intent_to_plan
    from eval_engine.core.family_catalog import get_family, get_supported_family_ids

    intent = {
        "intent_name": "cat",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Catalog consistency.",
        "capability_focus": ["extraction", "classification", "math", "trajectory", "grounded_qa"],
        "batch_size": 4,
        "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    plan = compile_intent_to_plan(intent, planner_mode="deterministic")
    supported = set(get_supported_family_ids())
    for f in plan["eval_families"]:
        fid = f["family_id"]
        assert get_family(fid, allow_experimental=False) is not None or fid in supported, (
            f"family_id {fid} not in catalog"
        )


def test_catalog_consistency_task_types_in_registry():
    """Every task_type in compiled_dataset_spec.capability_targets is in task registry."""
    from eval_engine.agents.compile_pipeline import compile_intent_to_plan
    from eval_engine.tasks.registry import get_task_registry

    intent = {
        "intent_name": "reg",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Registry consistency.",
        "capability_focus": ["extraction", "math", "trajectory"],
        "batch_size": 4,
        "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    plan = compile_intent_to_plan(intent, planner_mode="deterministic")
    targets = plan["compiled_dataset_spec"]["capability_targets"]
    registry = get_task_registry()
    for t in targets:
        tt = t["task_type"]
        assert tt in registry, f"task_type {tt} not in task registry"


def test_batch_plan_sum_equals_quota():
    """For a few specs, compile_batch_plan(spec, quota, rng) yields sum(count) == quota."""
    from eval_engine.agents.batch_planner import compile_batch_plan

    spec = {
        "dataset_name": "q",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["a"],
        "capability_targets": [
            {"target_id": "t1", "domain_tags": ["a"], "difficulty": "easy", "task_type": "json_math_add", "quota_weight": 1},
            {"target_id": "t2", "domain_tags": ["a"], "difficulty": "easy", "task_type": "json_extract_email", "quota_weight": 1},
        ],
        "defaults": {"seed": 1, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    for quota in (1, 3, 10):
        rng = random.Random(7)
        plan = compile_batch_plan(spec, quota, rng)
        assert sum(e["count"] for e in plan) == quota


def test_min_count_satisfied_when_set():
    """When capability_targets have min_count, batch_plan satisfies sum(count) >= sum(min_count)."""
    from eval_engine.agents.batch_planner import compile_batch_plan

    spec = {
        "dataset_name": "minq",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["a"],
        "capability_targets": [
            {"target_id": "t1", "domain_tags": ["a"], "difficulty": "easy", "task_type": "json_math_add", "quota_weight": 1, "min_count": 2},
            {"target_id": "t2", "domain_tags": ["a"], "difficulty": "easy", "task_type": "json_extract_email", "quota_weight": 1, "min_count": 1},
        ],
        "defaults": {"seed": 1, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    quota = 5
    rng = random.Random(11)
    plan = compile_batch_plan(spec, quota, rng)
    by_target = {e["target"]["target_id"]: e["count"] for e in plan}
    assert by_target.get("t1", 0) >= 2
    assert by_target.get("t2", 0) >= 1
    assert sum(e["count"] for e in plan) == quota
