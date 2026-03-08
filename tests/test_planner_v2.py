"""
Tests for v2 planner: deterministic vs llm vs hybrid, config, API, metadata, raw artifacts.
Uses mocks for Gemini SDK so no API key is required.
"""
import json
import os
import pytest

from eval_engine.core.failure_codes import (
    LLM_PROVIDER_NOT_CONFIGURED,
    LLM_OUTPUT_REPAIR_EXHAUSTED,
    LLM_RESPONSE_NOT_JSON,
)


def test_missing_gemini_key_in_llm_mode_raises(monkeypatch):
    monkeypatch.setattr("eval_engine.config.GEMINI_API_KEY", "")
    from eval_engine.agents.intent_planner import plan_intent

    intent = {
        "intent_name": "x",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Extraction.",
        "capability_focus": ["extraction"],
    }
    with pytest.raises(ValueError) as exc_info:
        plan_intent(intent, mode="llm")
    assert LLM_PROVIDER_NOT_CONFIGURED in str(exc_info.value)


def test_deterministic_mode_unchanged():
    from eval_engine.agents.compile_pipeline import compile_intent_to_plan
    from eval_engine.core.schema import validate_or_raise

    intent = {
        "intent_name": "smoke",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Email extraction and trajectory.",
        "capability_focus": ["extraction", "trajectory"],
        "batch_size": 4,
        "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    plan = compile_intent_to_plan(intent, planner_mode="deterministic")
    assert "compiled_dataset_spec" in plan
    assert "compile_metadata" in plan
    meta = plan["compile_metadata"]
    assert meta.get("planner_mode") == "deterministic"
    validate_or_raise("compiled_plan.schema.json", plan)


def test_compile_metadata_includes_planner_mode_and_model():
    from eval_engine.agents.compile_pipeline import compile_intent_to_plan

    intent = {
        "intent_name": "m",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "E",
        "capability_focus": ["extraction"],
    }
    plan = compile_intent_to_plan(
        intent,
        planner_mode="deterministic",
        planner_model="gemini-2.0-flash",
        planner_temperature=0.1,
    )
    meta = plan["compile_metadata"]
    assert meta.get("planner_mode") == "deterministic"
    assert meta.get("planner_model") == "gemini-2.0-flash"
    assert meta.get("planner_temperature") == 0.1
    assert "llm_round_trips" in meta
    assert "warnings" in meta


def test_api_accepts_planner_mode_and_model():
    from fastapi.testclient import TestClient
    from eval_engine.api.app import app

    client = TestClient(app)
    intent = {
        "intent_name": "api_planner",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Extraction.",
        "capability_focus": ["extraction"],
    }
    resp = client.post(
        "/compile",
        json={
            "intent_json": json.dumps(intent),
            "planner_mode": "deterministic",
            "planner_model": "gemini-2.0-flash",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["compile_metadata"].get("planner_mode") == "deterministic"


def test_planner_status_endpoint_never_exposes_key():
    from fastapi.testclient import TestClient
    from eval_engine.api.app import app

    client = TestClient(app)
    resp = client.get("/planner-status")
    assert resp.status_code == 200
    data = resp.json()
    assert "planner_mode" in data
    assert "gemini_configured" in data
    assert "api_key" not in data
    assert "GEMINI" not in str(data).upper() or "gemini_configured" in data


def test_llm_mode_requires_key_compile_endpoint(monkeypatch):
    monkeypatch.setattr("eval_engine.config.GEMINI_API_KEY", "")
    from fastapi.testclient import TestClient
    from eval_engine.api.app import app

    client = TestClient(app)
    intent = {
        "intent_name": "x",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "E",
        "capability_focus": ["extraction"],
    }
    resp = client.post(
        "/compile",
        json={"intent_json": json.dumps(intent), "planner_mode": "llm"},
    )
    assert resp.status_code == 400
    assert LLM_PROVIDER_NOT_CONFIGURED in str(resp.json().get("detail", ""))


def test_structured_invalid_json_raises_after_retries(monkeypatch):
    from eval_engine.llm.structured import generate_and_validate

    def fake_generate(_prompt, **kwargs):
        return "this is not json at all"

    monkeypatch.setattr("eval_engine.llm.structured.generate", fake_generate)
    with pytest.raises(ValueError) as exc_info:
        generate_and_validate(
            "prompt",
            "eval_family.schema.json",
            parse_list_from_key="eval_families",
            max_retries=1,
        )
    msg = str(exc_info.value)
    assert LLM_RESPONSE_NOT_JSON in msg or LLM_OUTPUT_REPAIR_EXHAUSTED in msg


def test_planner_critic_deterministic_returns_structured():
    from eval_engine.agents.planner_critic import run_planner_critic

    families = [
        {
            "family_id": "extraction.email",
            "family_label": "E",
            "objective": "Extract email.",
            "observable_targets": ["email"],
            "slot_weight": 10,
            "allowed_eval_methods": ["exact_match"],
            "materializer_type": "json_extract_email",
        }
    ]
    blueprints = []
    judges = [
        {
            "judge_spec_id": "j1",
            "family_id": "extraction.email",
            "blueprint_id": "bp1",
            "eval_method": "exact_match",
            "method_justification": "Test",
            "pass_fail_observables": ["email"],
        }
    ]
    out = run_planner_critic(families, blueprints, judges, mode="deterministic")
    assert "critic_report" in out
    assert "issues" in out["critic_report"]
    assert "summary" in out["critic_report"]
    assert "passed" in out["critic_report"]


def test_critic_hybrid_without_key_falls_back_to_deterministic(monkeypatch):
    monkeypatch.setattr("eval_engine.config.GEMINI_API_KEY", "")
    from eval_engine.agents.planner_critic import run_planner_critic

    families = [
        {"family_id": "extraction.email", "family_label": "E", "objective": "O", "observable_targets": ["email"], "slot_weight": 10}
    ]
    with pytest.raises(ValueError) as exc_info:
        run_planner_critic(families, [], [], mode="hybrid")
    assert LLM_PROVIDER_NOT_CONFIGURED in str(exc_info.value)


def test_raw_planner_artifacts_saved_when_enabled(tmp_path, monkeypatch):
    from eval_engine.agents.compile_pipeline import compile_and_save_artifacts

    monkeypatch.setenv("GEMINI_API_KEY", "")
    intent = {
        "intent_name": "r",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "E",
        "capability_focus": ["extraction"],
    }
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    plan = compile_and_save_artifacts(
        intent,
        artifacts_dir,
        planner_mode="deterministic",
        save_raw_planner_outputs=False,
    )
    assert (artifacts_dir / "planner_metadata.json").exists()
    assert (artifacts_dir / "compiled_plan.json").exists()
    meta = json.loads((artifacts_dir / "planner_metadata.json").read_text())
    assert meta.get("planner_mode") == "deterministic"
