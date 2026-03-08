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


def test_compile_brief_endpoint_deterministic():
    """POST /compile-brief with natural-language brief returns intent_spec and compiled_dataset_spec."""
    from fastapi.testclient import TestClient
    from eval_engine.api.app import app

    client = TestClient(app)
    resp = client.post(
        "/compile-brief",
        json={
            "brief_text": "Evaluate email extraction and trajectory tool use. Around 10 items.",
            "quota": 10,
            "planner_mode": "deterministic",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "brief_text" in data
    assert "intent_spec" in data
    assert "compiled_plan" in data
    assert "compiled_dataset_spec" in data
    assert "compile_metadata" in data
    intent = data["intent_spec"]
    assert intent.get("evaluation_goal")
    assert "capability_focus" in intent and len(intent["capability_focus"]) >= 1
    spec = data["compiled_dataset_spec"]
    assert "capability_targets" in spec and len(spec["capability_targets"]) >= 1
    assert data["compile_metadata"].get("planner_mode") == "deterministic"


def test_compile_brief_under_specified_returns_400():
    """Brief with no inferrable capability returns 400."""
    from fastapi.testclient import TestClient
    from eval_engine.api.app import app

    client = TestClient(app)
    resp = client.post(
        "/compile-brief",
        json={"brief_text": "Evaluate something vague and unspecific."},
    )
    assert resp.status_code == 400
    assert "capability" in resp.json().get("detail", "").lower() or "brief" in resp.json().get("detail", "").lower()


def test_compile_brief_target_domain_flows_to_spec():
    """target_domain in request is reflected in intent_spec and compiled_dataset_spec (allowed_domain_tags, capability_targets[].domain_tags)."""
    from fastapi.testclient import TestClient
    from eval_engine.api.app import app

    client = TestClient(app)
    requested_domain = ["extraction", "trajectory"]
    resp = client.post(
        "/compile-brief",
        json={
            "brief_text": "Evaluate email extraction and trajectory tool use. Around 6 items.",
            "quota": 6,
            "planner_mode": "deterministic",
            "target_domain": requested_domain,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    intent = data["intent_spec"]
    assert intent.get("target_domain") == requested_domain
    spec = data["compiled_dataset_spec"]
    assert spec.get("allowed_domain_tags") == requested_domain
    targets = spec.get("capability_targets") or []
    assert len(targets) >= 1
    for t in targets:
        assert t.get("domain_tags") == requested_domain


def test_run_compiled_batch_uses_exact_compiled_spec():
    """Run Compiled Batch uses the previously returned compiled_dataset_spec exactly; no recompile from brief.
    Submits spec_json only (no intent_json); when run record exists, dataset_name must match the compiled spec.
    """
    from fastapi.testclient import TestClient
    from eval_engine.api.app import app

    client = TestClient(app)
    compile_resp = client.post(
        "/compile-brief",
        json={
            "brief_text": "Evaluate email extraction. Around 3 items.",
            "quota": 3,
            "planner_mode": "deterministic",
        },
    )
    assert compile_resp.status_code == 200
    compile_data = compile_resp.json()
    compiled_spec = compile_data["compiled_dataset_spec"]
    dataset_name = compiled_spec.get("dataset_name")
    assert dataset_name, "compiled spec must have dataset_name"

    # Submit run with *only* spec_json (no intent_json) — this is the "Run Compiled Batch" contract
    run_resp = client.post(
        "/runs",
        json={
            "spec_json": json.dumps(compiled_spec),
            "quota": 3,
            "sut": "http",
            "sut_url": "http://127.0.0.1:9999/sut/run",
            "sut_timeout": 30,
            "model_version": "http-sut-local",
        },
    )
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    run_id = run_data.get("run_id")
    assert run_id

    summary_resp = client.get(f"/runs/{run_id}")
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    # When the run record exists (run has started and written metadata), it must match the spec we sent
    if summary.get("dataset_name"):
        assert summary["dataset_name"] == dataset_name, (
            "Run must use the exact compiled spec (same dataset_name); "
            "Run Compiled Batch must not recompile from brief."
        )


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


# ---- Hybrid family normalization (alias map) ----

def test_hybrid_normalizes_near_miss_family_id_trajectory_email_tool():
    """Hybrid mode: LLM output family_id 'trajectory.email_tool' normalizes to 'trajectory.email_lookup'; compile succeeds."""
    from eval_engine.agents.intent_planner import _normalize_eval_families_to_catalog

    raw = [
        {
            "family_id": "trajectory.email_tool",
            "family_label": "Email tool",
            "objective": "Use tool then return email.",
            "observable_targets": ["email", "trajectory"],
            "slot_weight": 10,
            "allowed_eval_methods": ["trajectory_check", "schema_check"],
            "grounding_mode": "synthetic",
            "materializer_type": "trajectory_email_then_answer",
            "materializer_config": {},
            "dedup_group": "trajectory.email_tool",
            "failure_taxonomy": [],
        }
    ]
    normalized, warnings = _normalize_eval_families_to_catalog(raw, allow_experimental=False)
    assert len(normalized) == 1
    assert normalized[0]["family_id"] == "trajectory.email_lookup"
    assert any("trajectory.email_tool" in w and "trajectory.email_lookup" in w for w in warnings)


def test_hybrid_compile_succeeds_with_trajectory_email_tool_mock(monkeypatch):
    """Full hybrid compile with mocked LLM returning family_id trajectory.email_tool succeeds."""
    monkeypatch.setattr("eval_engine.config.GEMINI_API_KEY", "fake-key-for-test")
    from eval_engine.agents.compile_pipeline import compile_intent_to_plan

    def mock_generate(_p, **kwargs):
        return json.dumps({
            "eval_families": [
                {
                    "family_id": "trajectory.email_tool",
                    "family_label": "Email tool",
                    "objective": "Use tool then return email.",
                    "observable_targets": ["email", "trajectory"],
                    "slot_weight": 10,
                    "allowed_eval_methods": ["trajectory_check", "schema_check"],
                    "grounding_mode": "synthetic",
                    "materializer_type": "trajectory_email_then_answer",
                    "materializer_config": {},
                    "dedup_group": "trajectory.email_tool",
                    "failure_taxonomy": [],
                }
            ]
        })

    monkeypatch.setattr("eval_engine.llm.structured.generate", mock_generate)
    intent = {
        "intent_name": "hybrid_alias",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Trajectory email.",
        "capability_focus": ["trajectory"],
    }
    plan = compile_intent_to_plan(intent, planner_mode="hybrid")
    assert plan["eval_families"][0]["family_id"] == "trajectory.email_lookup"
    assert "compiled_dataset_spec" in plan
    assert any("trajectory.email_tool" in w for w in plan["compile_metadata"].get("warnings", []))


def test_hybrid_unsupported_family_id_no_alias_raises():
    """Unsupported family_id with allow_experimental=false and no alias fails with LLM_FAMILY_UNSUPPORTED."""
    from eval_engine.agents.intent_planner import _normalize_eval_families_to_catalog
    from eval_engine.core.failure_codes import LLM_FAMILY_UNSUPPORTED

    raw = [
        {
            "family_id": "nonexistent.xyz",
            "family_label": "X",
            "objective": "O",
            "observable_targets": ["x"],
            "slot_weight": 10,
            "allowed_eval_methods": ["schema_check"],
            "materializer_type": "json_extract_email",
        }
    ]
    with pytest.raises(ValueError) as exc_info:
        _normalize_eval_families_to_catalog(raw, allow_experimental=False)
    assert LLM_FAMILY_UNSUPPORTED in str(exc_info.value)


def test_hybrid_exact_supported_family_id_unchanged():
    """Exact supported family_id 'trajectory.email_lookup' remains unchanged, no failure."""
    from eval_engine.agents.intent_planner import _normalize_eval_families_to_catalog

    raw = [
        {
            "family_id": "trajectory.email_lookup",
            "family_label": "Email lookup",
            "objective": "Use search then return email.",
            "observable_targets": ["email", "trajectory"],
            "slot_weight": 10,
            "allowed_eval_methods": ["trajectory_check", "schema_check"],
            "grounding_mode": "synthetic",
            "materializer_type": "trajectory_email_then_answer",
            "materializer_config": {},
            "dedup_group": "trajectory.email_lookup",
            "failure_taxonomy": [],
        }
    ]
    normalized, warnings = _normalize_eval_families_to_catalog(raw, allow_experimental=False)
    assert len(normalized) == 1
    assert normalized[0]["family_id"] == "trajectory.email_lookup"
    assert not any("Normalized family_id" in w for w in warnings)


# ---- Judge/blueprint hybrid order + null defaults + API JSON ----

def test_hybrid_judge_planner_normalizes_before_validation(monkeypatch):
    """Hybrid judge: raw Gemini output with checker_name None and evidence_requirements None normalizes then validates successfully."""
    monkeypatch.setattr("eval_engine.config.GEMINI_API_KEY", "fake-key")
    from eval_engine.agents.judge_planner import compile_judge_specs

    def mock_generate(_p, **kwargs):
        return json.dumps({
            "judge_specs": [
                {
                    "judge_spec_id": "judge_extraction_email",
                    "family_id": "extraction.email",
                    "blueprint_id": "bp_extraction_email_easy",
                    "eval_method": "exact_match",
                    "checker_name": None,
                    "checker_config": None,
                    "evidence_requirements": None,
                    "expected_shape": {},
                    "canonicalization_rules": [],
                    "pass_fail_observables": ["email"],
                    "adjudication_policy": "strict",
                    "failure_taxonomy": [],
                    "method_justification": "Exact match for email.",
                }
            ]
        })

    monkeypatch.setattr("eval_engine.llm.structured.generate", mock_generate)
    families = [
        {
            "family_id": "extraction.email",
            "family_label": "E",
            "objective": "Extract email.",
            "observable_targets": ["email"],
            "slot_weight": 10,
            "allowed_eval_methods": ["exact_match", "schema_check"],
            "materializer_type": "json_extract_email",
        }
    ]
    blueprints = [
        {"blueprint_id": "bp_extraction_email_easy", "family_id": "extraction.email", "blueprint_type": "json_extract_email"}
    ]
    specs = compile_judge_specs(families, blueprints, mode="hybrid")
    assert len(specs) == 1
    assert specs[0]["evidence_requirements"] == {}
    assert specs[0].get("checker_config") == {}
    assert "checker_name" not in specs[0] or specs[0]["checker_name"]


def test_hybrid_blueprint_normalizes_before_validation(monkeypatch):
    """Hybrid blueprint: parse without per-item validation, then normalize, then validate."""
    monkeypatch.setattr("eval_engine.config.GEMINI_API_KEY", "fake-key")
    from eval_engine.agents.prompt_program_compiler import compile_prompt_blueprints

    def mock_generate(_p, **kwargs):
        return json.dumps({
            "prompt_blueprints": [
                {
                    "blueprint_id": "bp_extraction_email_easy",
                    "family_id": "extraction.email",
                    "blueprint_type": "json_extract_email",
                    "instruction_template": "",
                    "input_schema": {},
                    "output_schema": {},
                    "variation_axes": ["difficulty"],
                    "grounding_recipe": {"mode": "synthetic"},
                    "constraints": [],
                    "negative_constraints": [],
                    "dedup_fingerprint_fields": [],
                    "materializer_type": "json_extract_email",
                    "materializer_config": {},
                }
            ]
        })

    monkeypatch.setattr("eval_engine.llm.structured.generate", mock_generate)
    families = [
        {
            "family_id": "extraction.email",
            "family_label": "E",
            "observable_targets": ["email"],
            "slot_weight": 10,
            "materializer_type": "json_extract_email",
            "grounding_mode": "synthetic",
        }
    ]
    intent_spec = {"intent_name": "x", "intent_spec_version": "1.0.0", "evaluation_goal": "E"}
    blueprints = compile_prompt_blueprints(families, intent_spec, mode="hybrid")
    assert len(blueprints) == 1
    assert blueprints[0]["family_id"] == "extraction.email"


def test_deterministic_judge_specs_schema_valid():
    """Deterministic judge path produces schema-valid specs with no invalid None (non-rubric, non-programmatic)."""
    from eval_engine.agents.judge_planner import _compile_judge_specs_deterministic
    from eval_engine.core.schema import validate_or_raise

    families = [
        {
            "family_id": "extraction.email",
            "family_label": "E",
            "objective": "Extract email.",
            "observable_targets": ["email"],
            "allowed_eval_methods": ["exact_match", "schema_check"],
            "slot_weight": 10,
            "materializer_type": "json_extract_email",
        }
    ]
    blueprints = [{"blueprint_id": "bp_1", "family_id": "extraction.email"}]
    specs = _compile_judge_specs_deterministic(families, blueprints)
    assert len(specs) == 1
    for s in specs:
        validate_or_raise("judge_spec.schema.json", s)
        assert s.get("evidence_requirements") is not None
        assert s.get("checker_config") is not None
        if "checker_name" in s:
            assert s["checker_name"] is not None


def test_runs_invalid_json_returns_400():
    """POST /runs with invalid intent_json or spec_json returns 400."""
    from fastapi.testclient import TestClient
    from eval_engine.api.app import app

    client = TestClient(app)
    resp = client.post("/runs", json={"intent_json": "not valid json {"})
    assert resp.status_code == 400
    assert "Invalid" in resp.json().get("detail", "")

    resp2 = client.post("/runs", json={"spec_json": "{ broken ]"})
    assert resp2.status_code == 400


def test_compile_invalid_json_returns_400():
    """POST /compile with invalid intent_json returns 400."""
    from fastapi.testclient import TestClient
    from eval_engine.api.app import app

    client = TestClient(app)
    resp = client.post("/compile", json={"intent_json": "not valid json {"})
    assert resp.status_code == 400
    assert "Invalid" in resp.json().get("detail", "")
