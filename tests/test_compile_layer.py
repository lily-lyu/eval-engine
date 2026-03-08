"""
Tests for the intent planning / compile layer.
- Backward compatibility: dataset_spec runs still pass.
- Compile-only: intent_spec compiles into valid compiled_plan and dataset_spec.
- Failure handling: invalid intent or unsupported family rejected with explicit failure code.
- API: intent_json accepted, compile preview endpoint works.
"""
import json
import pytest

from eval_engine.agents.compile_pipeline import compile_intent_to_plan
from eval_engine.agents.intent_planner import plan_intent
from eval_engine.agents.prompt_program_compiler import compile_prompt_blueprints
from eval_engine.agents.judge_planner import compile_judge_specs
from eval_engine.agents.compiler import compile_to_plan
from eval_engine.core.failure_codes import (
    INTENT_SCHEMA_INVALID,
    INTENT_UNDER_SPECIFIED,
    UNSUPPORTED_CAPABILITY_FOCUS,
)
from eval_engine.core.schema import validate_or_raise
from eval_engine.agents.batch_planner import compile_batch_plan


# ---- Backward compatibility: dataset_spec ----

def test_dataset_spec_still_validates_and_batch_planner_works():
    spec = {
        "dataset_name": "smoke",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["extraction"],
        "capability_targets": [
            {
                "target_id": "t_email",
                "domain_tags": ["extraction"],
                "difficulty": "easy",
                "task_type": "json_extract_email",
                "quota_weight": 1,
            }
        ],
        "defaults": {"max_prompt_length": 20000, "max_retries_per_stage": 2, "seed": 42},
    }
    validate_or_raise("dataset_spec.schema.json", spec)
    rng = __import__("random").Random(42)
    plan = compile_batch_plan(spec, quota=2, rng=rng)
    assert len(plan) >= 1
    assert sum(p["count"] for p in plan) == 2


def test_dataset_spec_optional_family_id_allowed():
    spec = {
        "dataset_name": "smoke",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["extraction"],
        "capability_targets": [
            {
                "target_id": "t_email",
                "family_id": "extraction.email",
                "domain_tags": ["extraction"],
                "difficulty": "easy",
                "task_type": "json_extract_email",
                "quota_weight": 1,
            }
        ],
        "defaults": {"max_prompt_length": 20000, "max_retries_per_stage": 2, "seed": 42},
    }
    validate_or_raise("dataset_spec.schema.json", spec)


# ---- Compile-only: intent -> compiled_plan ----

def test_intent_spec_compiles_to_valid_compiled_plan_and_dataset_spec():
    intent = {
        "intent_name": "smoke",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Email extraction and trajectory.",
        "capability_focus": ["extraction", "trajectory"],
        "batch_size": 4,
        "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    plan = compile_intent_to_plan(intent)
    assert "intent_spec" in plan
    assert "eval_families" in plan
    assert "prompt_blueprints" in plan
    assert "judge_specs" in plan
    assert "compiled_dataset_spec" in plan
    assert "compile_metadata" in plan
    validate_or_raise("compiled_plan.schema.json", plan)
    ds = plan["compiled_dataset_spec"]
    validate_or_raise("dataset_spec.schema.json", ds)
    assert ds["dataset_name"]
    assert len(ds["capability_targets"]) >= 1
    assert "extraction.email" in [f["family_id"] for f in plan["eval_families"]] or "trajectory.email_lookup" in [f["family_id"] for f in plan["eval_families"]]


# ---- Failure handling ----

def test_invalid_intent_empty_capability_focus_rejected():
    intent = {
        "intent_name": "x",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Test.",
        "capability_focus": [],
    }
    with pytest.raises(ValueError) as exc_info:
        plan_intent(intent, mode="deterministic")
    assert INTENT_UNDER_SPECIFIED in str(exc_info.value)


def test_invalid_intent_missing_required_field_rejected():
    intent = {
        "intent_name": "x",
        "evaluation_goal": "Test.",
        "capability_focus": ["extraction"],
    }
    with pytest.raises(ValueError) as exc_info:
        plan_intent(intent, mode="deterministic")
    assert INTENT_SCHEMA_INVALID in str(exc_info.value)


def test_unsupported_capability_focus_rejected():
    intent = {
        "intent_name": "x",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Test.",
        "capability_focus": ["nonexistent_capability_xyz"],
    }
    with pytest.raises(ValueError) as exc_info:
        plan_intent(intent, mode="deterministic")
    assert UNSUPPORTED_CAPABILITY_FOCUS in str(exc_info.value)


# ---- Pipeline stages ----

def test_plan_intent_returns_eval_families():
    intent = {
        "intent_name": "x",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Extraction.",
        "capability_focus": ["extraction"],
    }
    families = plan_intent(intent, mode="deterministic")
    assert len(families) >= 1
    for f in families:
        assert f["family_id"]
        assert f["slot_weight"] >= 1
        assert "materializer_type" in f


def test_compile_judge_specs_rubric_has_evidence_requirements():
    families = [
        {
            "family_id": "extraction.email",
            "family_label": "Email",
            "objective": "Extract email.",
            "observable_targets": ["email"],
            "allowed_eval_methods": ["exact_match", "rubric_judge"],
            "difficulty": "easy",
            "slot_weight": 10,
            "materializer_type": "json_extract_email",
            "materializer_config": {},
            "dedup_group": "extraction.email",
            "failure_taxonomy": [],
        }
    ]
    blueprints = compile_prompt_blueprints(
        families, {"intent_name": "x", "intent_spec_version": "1.0.0", "evaluation_goal": "G"}, mode="deterministic"
    )
    judges = compile_judge_specs(families, blueprints, mode="deterministic")
    assert len(judges) == len(families)
    for j in judges:
        assert j["eval_method"] in ("exact_match", "trajectory_check", "programmatic_check", "schema_check", "rubric_judge")
        assert j["method_justification"]


# ---- API compile endpoint ----

def test_compile_endpoint_returns_compiled_plan():
    from fastapi.testclient import TestClient
    from eval_engine.api.app import app

    client = TestClient(app)
    intent = {
        "intent_name": "api_smoke",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Extraction.",
        "capability_focus": ["extraction"],
    }
    resp = client.post("/compile", json={"intent_json": json.dumps(intent)})
    assert resp.status_code == 200
    data = resp.json()
    assert "compiled_dataset_spec" in data
    assert "compile_metadata" in data


def test_compile_endpoint_invalid_json_returns_400():
    from fastapi.testclient import TestClient
    from eval_engine.api.app import app

    client = TestClient(app)
    resp = client.post("/compile", json={"intent_json": "not valid json {"})
    assert resp.status_code == 400


def test_compile_endpoint_invalid_intent_returns_400():
    from fastapi.testclient import TestClient
    from eval_engine.api.app import app

    client = TestClient(app)
    intent = {"intent_name": "x", "evaluation_goal": "G", "capability_focus": []}
    resp = client.post("/compile", json={"intent_json": json.dumps(intent)})
    assert resp.status_code == 400
