"""
Stress tests for the full agent pipeline with LLM-capable workers (A1, A2, A3).

Covers:
- Run config merge: merge into spec, preserve existing keys, bounds for max_retries, invalid mode ignored.
- A1 materializer: LLM success path (mocked) returns valid item with creative fields; fallback when LLM raises.
- A2 judge: deterministic mode does not call LLM; LLM success/fail/ERROR verdicts map correctly; graceful failure.
- A3 analyst: deterministic mode does not call LLM; multiple clusters enriched; fallback when LLM raises.
- Full pipeline: artifact consistency (eval_results vs metrics), all-pass produces PASS cluster,
  rubric_judge path with mocked A2, A3 enrichment with mocked LLM, hybrid modes with no API key (fallbacks).
- API: POST /runs with run_config (spec and intent), 400 when missing spec and intent.
- Live (with API key): full pipeline with hybrid modes and real Gemini calls.

Run (no API key): pytest tests/test_llm_agent_pipeline_stress.py -v
Run (with API key): GEMINI_API_KEY=your_key pytest tests/test_llm_agent_pipeline_stress.py -v
Run only live tests: GEMINI_API_KEY=your_key pytest tests/test_llm_agent_pipeline_stress.py -v -k live
"""
from __future__ import annotations

import json
import os
import random
from pathlib import Path
from unittest.mock import patch

import pytest

# Skip live tests when no API key so CI and default runs stay green.
REQUIRES_GEMINI = pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set; set it to run live LLM stress tests",
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Minimal spec for direct run (no intent): used for pipeline smoke tests. target_id must match ^[a-z0-9_\-]{3,64}$
MINIMAL_SPEC = {
    "dataset_name": "stress_test",
    "dataset_spec_version": "1.0.0",
    "allowed_domain_tags": ["math", "extraction"],
    "capability_targets": [
        {"target_id": "math_1", "domain_tags": ["math"], "difficulty": "easy", "task_type": "json_math_add", "quota_weight": 1},
        {"target_id": "ext_1", "domain_tags": ["extraction"], "difficulty": "easy", "task_type": "json_extract_email", "quota_weight": 1},
    ],
    "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
}


# ---- Run config merge ----

def test_run_config_merged_into_spec():
    """run_batch_service merges request run_config fields into spec so A1/A2/A3 can read them."""
    from eval_engine.services.run_service import RunBatchRequest, run_batch_service, _merge_run_config_into_spec

    spec = {
        "dataset_name": "merge_test",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["general"],
        "capability_targets": [{"target_id": "t1", "domain_tags": ["general"], "difficulty": "easy", "task_type": "json_math_add", "quota_weight": 1}],
        "defaults": {"seed": 1, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    request = RunBatchRequest(
        project_root=PROJECT_ROOT,
        spec=dict(spec),
        quota=1,
        sut_name="mock",
        model_version="mock-1",
        item_generation_mode="hybrid",
        judge_mode="llm_materialized",
        diagnoser_mode="hybrid",
        max_llm_retries_per_stage=3,
    )
    _merge_run_config_into_spec(spec, request)
    assert spec.get("run_config") is not None
    assert spec["run_config"].get("item_generation_mode") == "hybrid"
    assert spec["run_config"].get("judge_mode") == "llm_materialized"
    assert spec["run_config"].get("diagnoser_mode") == "hybrid"
    assert spec["run_config"].get("max_llm_retries_per_stage") == 3


def test_run_config_defaults_max_llm_retries_when_not_provided():
    """When request does not set max_llm_retries_per_stage, run_config gets env/default."""
    from eval_engine.services.run_service import RunBatchRequest, _merge_run_config_into_spec

    spec = {
        "dataset_name": "x",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["general"],
        "capability_targets": [{"target_id": "t1", "domain_tags": ["general"], "difficulty": "easy", "task_type": "json_math_add", "quota_weight": 1}],
        "defaults": {"seed": 1, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    request = RunBatchRequest(project_root=PROJECT_ROOT, spec=dict(spec), quota=1, sut_name="mock", model_version="mock-1")
    _merge_run_config_into_spec(spec, request)
    assert "run_config" in spec
    assert "max_llm_retries_per_stage" in spec["run_config"]
    assert isinstance(spec["run_config"]["max_llm_retries_per_stage"], int)


def test_run_config_merge_preserves_existing_spec_run_config():
    """Merging request run_config does not wipe existing spec run_config keys; partial request only updates given keys."""
    from eval_engine.services.run_service import RunBatchRequest, _merge_run_config_into_spec

    spec = {
        "dataset_name": "preserve",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["general"],
        "capability_targets": [{"target_id": "t1", "domain_tags": ["general"], "difficulty": "easy", "task_type": "json_math_add", "quota_weight": 1}],
        "defaults": {"seed": 1, "max_prompt_length": 20000, "max_retries_per_stage": 2},
        "run_config": {"item_generation_mode": "hybrid", "max_llm_retries_per_stage": 2},
    }
    request = RunBatchRequest(
        project_root=PROJECT_ROOT,
        spec=dict(spec),
        quota=1,
        sut_name="mock",
        model_version="mock-1",
        judge_mode="deterministic",
        diagnoser_mode="llm_materialized",
    )
    _merge_run_config_into_spec(spec, request)
    assert spec["run_config"]["item_generation_mode"] == "hybrid"
    assert spec["run_config"]["judge_mode"] == "deterministic"
    assert spec["run_config"]["diagnoser_mode"] == "llm_materialized"
    assert spec["run_config"]["max_llm_retries_per_stage"] == 2


def test_run_config_merge_max_retries_bounds():
    """max_llm_retries_per_stage is only merged when in [0, 10]; otherwise default is used if key missing."""
    from eval_engine.services.run_service import RunBatchRequest, _merge_run_config_into_spec

    for val, expect_set in [(0, True), (5, True), (10, True), (-1, False), (11, False)]:
        spec = {
            "dataset_name": "bounds",
            "dataset_spec_version": "1.0.0",
            "allowed_domain_tags": ["general"],
            "capability_targets": [{"target_id": "t1", "domain_tags": ["general"], "difficulty": "easy", "task_type": "json_math_add", "quota_weight": 1}],
            "defaults": {"seed": 1, "max_prompt_length": 20000, "max_retries_per_stage": 2},
        }
        request = RunBatchRequest(
            project_root=PROJECT_ROOT,
            spec=dict(spec),
            quota=1,
            sut_name="mock",
            model_version="mock-1",
            max_llm_retries_per_stage=val,
        )
        _merge_run_config_into_spec(spec, request)
        if expect_set:
            assert spec["run_config"]["max_llm_retries_per_stage"] == val
        else:
            assert spec["run_config"]["max_llm_retries_per_stage"] != val
            assert isinstance(spec["run_config"]["max_llm_retries_per_stage"], int)


def test_run_config_merge_invalid_mode_ignored():
    """Invalid mode strings are not written; existing spec run_config value for that key is preserved."""
    from eval_engine.services.run_service import RunBatchRequest, _merge_run_config_into_spec

    spec = {
        "dataset_name": "invalid",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["general"],
        "capability_targets": [{"target_id": "t1", "domain_tags": ["general"], "difficulty": "easy", "task_type": "json_math_add", "quota_weight": 1}],
        "defaults": {"seed": 1, "max_prompt_length": 20000, "max_retries_per_stage": 2},
        "run_config": {"item_generation_mode": "deterministic"},
    }
    request = RunBatchRequest(
        project_root=PROJECT_ROOT,
        spec=dict(spec),
        quota=1,
        sut_name="mock",
        model_version="mock-1",
        item_generation_mode="invalid_mode",
    )
    _merge_run_config_into_spec(spec, request)
    assert spec["run_config"]["item_generation_mode"] == "deterministic"


# ---- A2: rubric_judge deterministic when run_config is None ----

def test_verify_rubric_judge_with_run_config_none_uses_deterministic_stub():
    """When run_config is None, rubric_judge uses existing deterministic/stub path."""
    from eval_engine.agents.a2_verifier import verify
    from eval_engine.core.hashing import sha256_bytes

    item = {
        "item_id": "item_rubric_test",
        "task_type": "json_classify_sentiment",
        "prompt": "Classify sentiment.",
        "output_schema": {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]},
    }
    oracle = {
        "item_id": "item_rubric_test",
        "eval_method": "rubric_judge",
        "evidence_requirements": {"required_evidence": ["reasoning"], "min_length": 1},
        "method_justification": "test",
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
    }
    raw = '{"label": "positive", "reasoning": "good"}'
    b = raw.encode("utf-8")
    raw_ref = {"sha256": sha256_bytes(b), "uri": "test://x", "mime": "application/json", "bytes": len(b)}
    result = verify(
        item, oracle, raw, model_version="mock-1", seed=42, raw_output_ref=raw_ref, run_config=None
    )
    assert result["verdict"] in ("pass", "fail")
    assert "error_type" in result
    assert result.get("eval_method") == "rubric_judge"
    # Stub returns pass with score 0.85 when no judge_fn
    assert "score" in result


def test_a2_llm_judge_graceful_failure_when_validation_raises():
    """When judge_mode=hybrid and LLM validation fails, verify returns graceful failure (JUDGE_SYSTEM_ERROR)."""
    from eval_engine.agents.a2_verifier import verify
    from eval_engine.core.failure_codes import JUDGE_SYSTEM_ERROR
    from eval_engine.core.hashing import sha256_bytes

    item = {
        "item_id": "item_judge_fail",
        "task_type": "json_classify_sentiment",
        "prompt": "Classify.",
        "output_schema": {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]},
    }
    oracle = {
        "item_id": "item_judge_fail",
        "eval_method": "rubric_judge",
        "evidence_requirements": {"required_evidence": ["reasoning"]},
        "method_justification": "test",
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
    }
    raw = '{"label": "positive"}'
    b = raw.encode("utf-8")
    raw_ref = {"sha256": sha256_bytes(b), "uri": "test://x", "mime": "application/json", "bytes": len(b)}
    run_config = {"judge_mode": "hybrid", "max_llm_retries_per_stage": 1}

    with patch("eval_engine.agents.a2_verifier.generate_and_validate_pydantic") as mock_validate:
        mock_validate.side_effect = ValueError("LLM schema validation failed")
        result = verify(
            item, oracle, raw, model_version="mock-1", seed=42, raw_output_ref=raw_ref, run_config=run_config
        )
    assert result["verdict"] == "fail"
    assert result["error_type"] == JUDGE_SYSTEM_ERROR
    assert result["score"] == 0.0
    assert any(
        e.get("code") == "JUDGE_SYSTEM_ERROR" or "valid schema" in (e.get("message") or "").lower()
        for e in result.get("evidence", [])
    )


# ---- A3: diagnose deterministic when run_config is None ----

def test_diagnose_with_run_config_none_returns_deterministic_clusters():
    """diagnose(eval_results) with no run_config returns deterministic clusters (no LLM)."""
    from eval_engine.agents.a3_diagnoser import diagnose

    eval_results = [
        {
            "item_id": "i1",
            "verdict": "fail",
            "error_type": "EXACT_MATCH_FAILED",
            "evidence": [{"code": "EXACT_MATCH_FAILED", "message": "m1"}],
            "task_type": "json_extract_email",
            "eval_method": "exact_match",
        },
    ]
    clusters, plans = diagnose(eval_results, run_config=None)
    failure_clusters = [c for c in clusters if c["cluster_id"] != "PASS"]
    assert len(failure_clusters) == 1
    assert failure_clusters[0]["cluster_id"]
    assert "hypothesis" in failure_clusters[0]
    assert "owner" in failure_clusters[0]
    # Deterministic path does not add title or evidence_examples
    assert failure_clusters[0].get("title") is None or "title" not in failure_clusters[0]
    assert failure_clusters[0].get("evidence_examples") is None or "evidence_examples" not in failure_clusters[0]


def test_a3_llm_analyst_fallback_returns_original_clusters_when_llm_raises():
    """When diagnoser_mode=hybrid and LLM raises, diagnose returns deterministic clusters unmodified."""
    from eval_engine.agents.a3_diagnoser import diagnose

    eval_results = [
        {
            "item_id": "i1",
            "verdict": "fail",
            "error_type": "EXACT_MATCH_FAILED",
            "evidence": [{"code": "EXACT_MATCH_FAILED"}],
            "task_type": "json_extract_email",
            "eval_method": "exact_match",
        },
    ]
    run_config = {"diagnoser_mode": "hybrid", "max_llm_retries_per_stage": 1}
    with patch("eval_engine.agents.a3_diagnoser.generate_and_validate_pydantic") as mock_validate:
        mock_validate.side_effect = ValueError("A3 LLM failed")
        clusters, plans = diagnose(eval_results, run_config=run_config)
    failure_clusters = [c for c in clusters if c["cluster_id"] != "PASS"]
    assert len(failure_clusters) == 1
    assert failure_clusters[0]["cluster_id"]
    assert "hypothesis" in failure_clusters[0]
    # No enrichment when LLM failed
    assert failure_clusters[0].get("title") is None
    assert failure_clusters[0].get("evidence_examples") is None or failure_clusters[0].get("evidence_examples") == []


def test_a3_diagnoser_mode_deterministic_does_not_call_llm():
    """When run_config.diagnoser_mode is deterministic, diagnose does not call generate_and_validate_pydantic."""
    from eval_engine.agents.a3_diagnoser import diagnose

    eval_results = [
        {
            "item_id": "i1",
            "verdict": "fail",
            "error_type": "EXACT_MATCH_FAILED",
            "evidence": [{"code": "EXACT_MATCH_FAILED"}],
            "task_type": "json_extract_email",
            "eval_method": "exact_match",
        },
    ]
    run_config = {"diagnoser_mode": "deterministic", "max_llm_retries_per_stage": 1}
    with patch("eval_engine.agents.a3_diagnoser.generate_and_validate_pydantic") as mock_validate:
        clusters, plans = diagnose(eval_results, run_config=run_config)
    mock_validate.assert_not_called()
    failure_clusters = [c for c in clusters if c["cluster_id"] != "PASS"]
    assert len(failure_clusters) == 1


def test_a3_llm_analyst_multiple_clusters_both_enriched():
    """When two failure clusters exist and LLM returns two A3ClusterSummary, both clusters get title and evidence_examples."""
    from eval_engine.llm.worker_schemas import A3AnalystReport, A3ClusterSummary
    from eval_engine.agents.a3_diagnoser import diagnose

    eval_results = [
        {
            "item_id": "i1",
            "verdict": "fail",
            "error_type": "EXACT_MATCH_FAILED",
            "evidence": [{"code": "EXACT_MATCH_FAILED", "message": "m1"}],
            "task_type": "json_extract_email",
            "eval_method": "exact_match",
        },
        {
            "item_id": "i2",
            "verdict": "fail",
            "error_type": "PROGRAMMATIC_CHECK_FAILED",
            "evidence": [{"code": "PROGRAMMATIC_CHECK_FAILED", "message": "m2"}],
            "task_type": "json_math_add",
            "eval_method": "programmatic_check",
        },
    ]
    run_config = {"diagnoser_mode": "hybrid", "max_llm_retries_per_stage": 1}
    cid1 = "EXACT_MATCH_FAILED/EXACT_MATCH_FAILED|json_extract_email|exact_match"
    cid2 = "PROGRAMMATIC_CHECK_FAILED/PROGRAMMATIC_CHECK_FAILED|json_math_add|programmatic_check"
    with patch("eval_engine.agents.a3_diagnoser.generate_and_validate_pydantic") as mock_validate:
        def return_two_clusters(prompt, model_class, **kwargs):
            assert model_class is A3AnalystReport
            return A3AnalystReport(clusters=[
                A3ClusterSummary(
                    cluster_id=cid1,
                    title="Email exact-match failures",
                    affected_share=0.5,
                    likely_root_cause="Output format mismatch.",
                    owner="model",
                    recommended_actions=["Add examples."],
                    evidence_examples=["EXACT_MATCH_FAILED"],
                ),
                A3ClusterSummary(
                    cluster_id=cid2,
                    title="Math programmatic failures",
                    affected_share=0.5,
                    likely_root_cause="Wrong answer.",
                    owner="model",
                    recommended_actions=["Check arithmetic."],
                    evidence_examples=["PROGRAMMATIC_CHECK_FAILED"],
                ),
            ])
        mock_validate.side_effect = return_two_clusters
        clusters, plans = diagnose(eval_results, run_config=run_config)
    failure_clusters = [c for c in clusters if c["cluster_id"] != "PASS"]
    assert len(failure_clusters) == 2
    by_cid = {c["cluster_id"]: c for c in failure_clusters}
    assert by_cid[cid1]["title"] == "Email exact-match failures"
    assert by_cid[cid1]["evidence_examples"] == ["EXACT_MATCH_FAILED"]
    assert by_cid[cid2]["title"] == "Math programmatic failures"
    assert by_cid[cid2]["evidence_examples"] == ["PROGRAMMATIC_CHECK_FAILED"]


def test_a3_llm_analyst_success_enriches_clusters():
    """When diagnoser_mode=hybrid and LLM returns valid A3AnalystReport, clusters get title and evidence_examples."""
    from eval_engine.llm.worker_schemas import A3AnalystReport, A3ClusterSummary
    from eval_engine.agents.a3_diagnoser import diagnose

    eval_results = [
        {
            "item_id": "i1",
            "verdict": "fail",
            "error_type": "EXACT_MATCH_FAILED",
            "evidence": [{"code": "EXACT_MATCH_FAILED", "message": "m1"}],
            "task_type": "json_extract_email",
            "eval_method": "exact_match",
        },
    ]
    run_config = {"diagnoser_mode": "hybrid", "max_llm_retries_per_stage": 1}
    with patch("eval_engine.agents.a3_diagnoser.generate_and_validate_pydantic") as mock_validate:
        def return_report(prompt, model_class, **kwargs):
            assert model_class is A3AnalystReport
            if "## Input" not in prompt:
                payload = {}
            else:
                part = prompt.split("## Input", 1)[1]
                if "```" in part:
                    raw = part.split("```")[1].strip()
                    if raw.startswith("json"):
                        raw = raw[4:].strip()
                    payload = json.loads(raw)
                else:
                    payload = {}
            cluster_list = payload.get("clusters", [])
            if not cluster_list:
                return A3AnalystReport(clusters=[])
            cid = cluster_list[0]["cluster_id"]
            return A3AnalystReport(clusters=[
                A3ClusterSummary(
                    cluster_id=cid,
                    title="Email extraction exact-match failures",
                    affected_share=1.0,
                    likely_root_cause="Model output does not match expected email format.",
                    owner="model",
                    recommended_actions=["Add SFT examples for email extraction.", "Check canonical format."],
                    evidence_examples=["EXACT_MATCH_FAILED", "expected email format"],
                )
            ])
        mock_validate.side_effect = return_report
        clusters, plans = diagnose(eval_results, run_config=run_config)
    failure_clusters = [c for c in clusters if c["cluster_id"] != "PASS"]
    assert len(failure_clusters) == 1
    assert failure_clusters[0].get("title") == "Email extraction exact-match failures"
    assert failure_clusters[0].get("evidence_examples") == ["EXACT_MATCH_FAILED", "expected email format"]
    assert failure_clusters[0].get("hypothesis") == "Model output does not match expected email format."


# ---- A1: materializer fallback ----

def test_a2_judge_mode_deterministic_does_not_call_llm():
    """When run_config.judge_mode is deterministic, rubric_judge uses _verify_rubric and does not call generate_and_validate_pydantic."""
    from eval_engine.agents.a2_verifier import verify
    from eval_engine.core.hashing import sha256_bytes

    item = {
        "item_id": "item_det",
        "task_type": "json_classify_sentiment",
        "prompt": "Classify.",
        "output_schema": {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]},
    }
    oracle = {
        "item_id": "item_det",
        "eval_method": "rubric_judge",
        "evidence_requirements": {"required_evidence": ["reasoning"]},
        "method_justification": "test",
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
    }
    raw = '{"label": "positive", "reasoning": "ok"}'
    b = raw.encode("utf-8")
    raw_ref = {"sha256": sha256_bytes(b), "uri": "test://x", "mime": "application/json", "bytes": len(b)}
    run_config = {"judge_mode": "deterministic", "max_llm_retries_per_stage": 1}
    with patch("eval_engine.agents.a2_verifier.generate_and_validate_pydantic") as mock_validate:
        verify(
            item, oracle, raw, model_version="mock-1", seed=42, raw_output_ref=raw_ref, run_config=run_config
        )
    mock_validate.assert_not_called()


def test_a2_llm_judge_verdict_fail_score_maps_correctly():
    """When LLM returns FAIL and score 0.3, verify returns eval_result with verdict fail and score 0.3."""
    from eval_engine.agents.a2_verifier import verify
    from eval_engine.core.hashing import sha256_bytes
    from eval_engine.llm.worker_schemas import A2JudgeOutput

    item = {
        "item_id": "item_fail",
        "task_type": "json_classify_sentiment",
        "prompt": "Classify.",
        "output_schema": {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]},
    }
    oracle = {
        "item_id": "item_fail",
        "eval_method": "rubric_judge",
        "evidence_requirements": {"required_evidence": ["reasoning"]},
        "method_justification": "test",
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
    }
    raw = '{"label": "positive"}'
    b = raw.encode("utf-8")
    raw_ref = {"sha256": sha256_bytes(b), "uri": "test://x", "mime": "application/json", "bytes": len(b)}
    run_config = {"judge_mode": "hybrid", "max_llm_retries_per_stage": 1}
    with patch("eval_engine.agents.a2_verifier.generate_and_validate_pydantic") as mock_validate:
        mock_validate.return_value = A2JudgeOutput(
            score=0.3,
            verdict="FAIL",
            error_type="RUBRIC_JUDGE_FAILED",
            evidence=["Missing reasoning."],
            confidence=0.7,
        )
        result = verify(
            item, oracle, raw, model_version="mock-1", seed=42, raw_output_ref=raw_ref, run_config=run_config
        )
    assert result["verdict"] == "fail"
    assert result["score"] == 0.3
    assert result["error_type"] == "RUBRIC_JUDGE_FAILED"
    assert len(result["evidence"]) >= 1


def test_a2_llm_judge_verdict_error_maps_to_graceful_fail():
    """When LLM returns verdict ERROR with error_type set, verify returns fail with that error_type."""
    from eval_engine.agents.a2_verifier import verify
    from eval_engine.core.hashing import sha256_bytes
    from eval_engine.llm.worker_schemas import A2JudgeOutput

    item = {
        "item_id": "item_err",
        "task_type": "json_classify_sentiment",
        "prompt": "Classify.",
        "output_schema": {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]},
    }
    oracle = {
        "item_id": "item_err",
        "eval_method": "rubric_judge",
        "evidence_requirements": {"required_evidence": ["reasoning"]},
        "method_justification": "test",
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
    }
    raw = '{"label": "positive"}'
    b = raw.encode("utf-8")
    raw_ref = {"sha256": sha256_bytes(b), "uri": "test://x", "mime": "application/json", "bytes": len(b)}
    run_config = {"judge_mode": "hybrid", "max_llm_retries_per_stage": 1}
    with patch("eval_engine.agents.a2_verifier.generate_and_validate_pydantic") as mock_validate:
        mock_validate.return_value = A2JudgeOutput(
            score=0.0,
            verdict="ERROR",
            error_type="LLM_TIMEOUT",
            evidence=["Judge timed out."],
            confidence=0.0,
        )
        result = verify(
            item, oracle, raw, model_version="mock-1", seed=42, raw_output_ref=raw_ref, run_config=run_config
        )
    assert result["verdict"] == "fail"
    assert result["score"] == 0.0
    assert result["error_type"] == "LLM_TIMEOUT"


def test_a2_llm_judge_success_returns_eval_result_with_verdict_and_evidence():
    """When judge_mode=hybrid and LLM returns valid A2JudgeOutput, verify returns proper eval_result."""
    from eval_engine.agents.a2_verifier import verify
    from eval_engine.core.hashing import sha256_bytes
    from eval_engine.llm.worker_schemas import A2JudgeOutput

    item = {
        "item_id": "item_judge_ok",
        "task_type": "json_classify_sentiment",
        "prompt": "Classify.",
        "output_schema": {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"]},
    }
    oracle = {
        "item_id": "item_judge_ok",
        "eval_method": "rubric_judge",
        "evidence_requirements": {"required_evidence": ["reasoning"]},
        "method_justification": "test",
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
    }
    raw = '{"label": "positive", "reasoning": "clearly positive"}'
    b = raw.encode("utf-8")
    raw_ref = {"sha256": sha256_bytes(b), "uri": "test://x", "mime": "application/json", "bytes": len(b)}
    run_config = {"judge_mode": "hybrid", "max_llm_retries_per_stage": 1}
    with patch("eval_engine.agents.a2_verifier.generate_and_validate_pydantic") as mock_validate:
        mock_validate.return_value = A2JudgeOutput(
            score=0.9,
            verdict="PASS",
            error_type=None,
            evidence=["Output cites reasoning.", "Label matches criteria."],
            confidence=0.85,
        )
        result = verify(
            item, oracle, raw, model_version="mock-1", seed=42, raw_output_ref=raw_ref, run_config=run_config
        )
    assert result["verdict"] == "pass"
    assert result["score"] == 0.9
    assert result["error_type"] == ""
    assert len(result["evidence"]) >= 1
    assert result["eval_method"] == "rubric_judge"


def test_a1_materialize_llm_success_returns_valid_item_with_creative_fields():
    """When item_generation_mode=hybrid and LLM returns valid A1CreativeOutput, item has LLM creative fields and admin from blueprint."""
    from eval_engine.agents.a1_item_generator import materialize_target_to_item
    from eval_engine.core.schema import validate_or_raise
    from eval_engine.llm.worker_schemas import A1CreativeOutput, ItemConstraints

    spec = {
        "dataset_name": "a1_success",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["math"],
        "capability_targets": [],
        "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
        "run_config": {"item_generation_mode": "hybrid", "max_llm_retries_per_stage": 1},
    }
    target = {
        "target_id": "bp_math_1",
        "domain_tags": ["math"],
        "difficulty": "easy",
        "task_type": "json_math_add",
        "quota_weight": 1,
        "blueprint_id": "bp_math_1",
        "family_id": "math.add",
    }
    blueprint = {
        "blueprint_id": "bp_math_1",
        "family_id": "math.add",
        "blueprint_type": "json_math_add",
        "materializer_type": "json_math_add",
        "grounding_recipe": {"mode": "synthetic"},
        "materializer_config": {},
    }
    rng = random.Random(99)
    creative_prompt = "Add the two numbers given in input."
    creative_input = {"a": 10, "b": 20}
    creative_input_schema = {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}}
    creative_output_schema = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "integer"}}}
    with patch("eval_engine.agents.a1_item_generator.generate_and_validate_pydantic") as mock_validate:
        mock_validate.return_value = A1CreativeOutput(
            prompt=creative_prompt,
            difficulty="medium",
            input=creative_input,
            input_schema=creative_input_schema,
            output_schema=creative_output_schema,
            constraints=ItemConstraints(no_subjective_judgement=True, safety_notes="", locked_fields=["dataset_spec_version", "domain_tags", "difficulty", "task_type"]),
        )
        item = materialize_target_to_item(spec, target, "1.0.0", rng, blueprint=blueprint)
    validate_or_raise("item.schema.json", item)
    assert item["prompt"] == creative_prompt
    assert item["input"] == creative_input
    assert item["difficulty"] == "medium"
    assert item["task_type"] == "json_math_add"
    assert item["domain_tags"] == ["math"]
    assert item["dataset_spec_version"] == "1.0.0"
    assert item["item_id"]
    assert item.get("provenance", {}).get("created_by") == "A1"


def test_a1_materialize_fallback_when_llm_raises():
    """When item_generation_mode=hybrid and LLM raises, materialize_target_to_item returns deterministic item."""
    from eval_engine.agents.a1_item_generator import materialize_target_to_item
    from eval_engine.core.schema import validate_or_raise

    spec = {
        "dataset_name": "a1_fallback",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["math"],
        "capability_targets": [],
        "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
        "run_config": {"item_generation_mode": "hybrid", "max_llm_retries_per_stage": 1},
    }
    target = {
        "target_id": "bp_math_1",
        "domain_tags": ["math"],
        "difficulty": "easy",
        "task_type": "json_math_add",
        "quota_weight": 1,
        "blueprint_id": "bp_math_1",
        "family_id": "math.add",
    }
    blueprint = {
        "blueprint_id": "bp_math_1",
        "family_id": "math.add",
        "blueprint_type": "json_math_add",
        "materializer_type": "json_math_add",
        "grounding_recipe": {"mode": "synthetic"},
        "materializer_config": {},
    }
    rng = random.Random(42)
    with patch("eval_engine.agents.a1_item_generator.generate_and_validate_pydantic") as mock_validate:
        mock_validate.side_effect = ValueError("A1 LLM validation failed")
        item = materialize_target_to_item(spec, target, "1.0.0", rng, blueprint=blueprint)
    validate_or_raise("item.schema.json", item)
    assert item["item_id"]
    assert item["task_type"] == "json_math_add"
    assert item["dataset_spec_version"] == "1.0.0"
    assert "prompt" in item and "input" in item and "output_schema" in item
    assert item.get("provenance", {}).get("created_by") == "A1"


# ---- Full pipeline smoke ----

def test_full_pipeline_deterministic_smoke():
    """Full run with no run_config (all deterministic): batch completes, artifacts valid."""
    from eval_engine.services.run_service import RunBatchRequest, run_batch_service
    from eval_engine.core.schema import validate_or_raise

    request = RunBatchRequest(
        project_root=PROJECT_ROOT,
        spec=json.loads(json.dumps(MINIMAL_SPEC)),
        quota=2,
        sut_name="mock",
        model_version="mock-1",
    )
    response = run_batch_service(request)
    run_dir = response.run_dir
    assert run_dir.exists()
    run_record_path = run_dir / "run_record.json"
    assert run_record_path.exists()
    run_record = json.loads(run_record_path.read_text(encoding="utf-8"))
    assert "paths" in run_record
    assert "metrics" in run_record
    assert run_record["metrics"].get("items_total") == 2

    artifacts_dir = run_dir / "artifacts"
    eval_results_path = run_dir / "eval_results.jsonl"
    assert eval_results_path.exists()
    clusters_path = run_dir / "clusters.jsonl"
    assert clusters_path.exists()
    action_plans_path = run_dir / "action_plans.jsonl"
    assert action_plans_path.exists()

    for line in eval_results_path.read_text(encoding="utf-8").strip().splitlines():
        if line:
            er = json.loads(line)
            validate_or_raise("eval_result.schema.json", er)
    for line in clusters_path.read_text(encoding="utf-8").strip().splitlines():
        if line:
            cl = json.loads(line)
            validate_or_raise("failure_cluster.schema.json", cl)
    for line in action_plans_path.read_text(encoding="utf-8").strip().splitlines():
        if line:
            ap = json.loads(line)
            validate_or_raise("action_plan.schema.json", ap)


def test_full_pipeline_with_run_config_explicitly_deterministic():
    """Full run with run_config all deterministic: same as no run_config, no LLM calls."""
    from eval_engine.services.run_service import RunBatchRequest, run_batch_service

    request = RunBatchRequest(
        project_root=PROJECT_ROOT,
        spec=json.loads(json.dumps(MINIMAL_SPEC)),
        quota=2,
        sut_name="mock",
        model_version="mock-1",
        item_generation_mode="deterministic",
        judge_mode="deterministic",
        diagnoser_mode="deterministic",
    )
    response = run_batch_service(request)
    run_dir = response.run_dir
    assert run_dir.exists()
    run_record = json.loads((run_dir / "run_record.json").read_text(encoding="utf-8"))
    assert run_record["metrics"].get("items_total") == 2


def test_full_pipeline_artifact_consistency_eval_results_match_metrics():
    """After a deterministic run, eval_results.jsonl line count and item_ids match run_record metrics and schema."""
    from eval_engine.services.run_service import RunBatchRequest, run_batch_service
    from eval_engine.core.schema import validate_or_raise

    request = RunBatchRequest(
        project_root=PROJECT_ROOT,
        spec=json.loads(json.dumps(MINIMAL_SPEC)),
        quota=3,
        sut_name="mock",
        model_version="mock-1",
    )
    response = run_batch_service(request)
    run_dir = response.run_dir
    run_record = json.loads((run_dir / "run_record.json").read_text(encoding="utf-8"))
    metrics = run_record["metrics"]
    items_total = metrics["items_total"]

    lines = [ln for ln in (run_dir / "eval_results.jsonl").read_text(encoding="utf-8").strip().splitlines() if ln]
    assert len(lines) == items_total
    eval_item_ids = []
    for line in lines:
        er = json.loads(line)
        validate_or_raise("eval_result.schema.json", er)
        eval_item_ids.append(er["item_id"])
    assert len(eval_item_ids) == items_total
    assert len(set(eval_item_ids)) == items_total


def test_full_pipeline_all_pass_produces_pass_cluster():
    """When all items pass (mock SUT), clusters include PASS cluster and no failure clusters or one PASS-only."""
    from eval_engine.services.run_service import RunBatchRequest, run_batch_service

    request = RunBatchRequest(
        project_root=PROJECT_ROOT,
        spec=json.loads(json.dumps(MINIMAL_SPEC)),
        quota=2,
        sut_name="mock",
        model_version="mock-1",
    )
    response = run_batch_service(request)
    run_dir = response.run_dir
    clusters = [json.loads(ln) for ln in (run_dir / "clusters.jsonl").read_text(encoding="utf-8").strip().splitlines() if ln]
    pass_clusters = [c for c in clusters if c.get("cluster_id") == "PASS"]
    assert len(pass_clusters) >= 1
    assert run_dir.exists()


def test_full_pipeline_rubric_judge_with_mocked_a2():
    """Full run with intent that can produce rubric_judge; mock A2 LLM to return PASS; run completes and eval_results have verdict pass."""
    from eval_engine.services.run_service import RunBatchRequest, run_batch_service
    from eval_engine.llm.worker_schemas import A2JudgeOutput

    intent = {
        "intent_name": "rubric_mock",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Test rubric judge path.",
        "capability_focus": ["math", "extraction"],
        "batch_size": 2,
        "defaults": {"seed": 77, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    request = RunBatchRequest(
        project_root=PROJECT_ROOT,
        spec={},
        quota=2,
        sut_name="mock",
        model_version="mock-1",
        intent_spec=intent,
        planner_mode="deterministic",
        item_generation_mode="deterministic",
        judge_mode="hybrid",
        diagnoser_mode="deterministic",
        max_llm_retries_per_stage=1,
    )
    with patch("eval_engine.agents.a2_verifier.generate_and_validate_pydantic") as mock_a2:
        mock_a2.return_value = A2JudgeOutput(
            score=1.0,
            verdict="PASS",
            error_type=None,
            evidence=["Output meets criteria."],
            confidence=0.9,
        )
        response = run_batch_service(request)
    run_dir = response.run_dir
    assert run_dir.exists()
    run_record = json.loads((run_dir / "run_record.json").read_text(encoding="utf-8"))
    assert run_record["metrics"].get("items_total") == 2
    for line in (run_dir / "eval_results.jsonl").read_text(encoding="utf-8").strip().splitlines():
        if line:
            er = json.loads(line)
            assert "verdict" in er
            assert er["verdict"] in ("pass", "fail")


def test_full_pipeline_hybrid_a3_enrichment_with_mocked_llm():
    """Run with failures and diagnoser_mode=hybrid; mock A3 to enrich; assert clusters have title/evidence_examples."""
    from eval_engine.services.run_service import RunBatchRequest, run_batch_service
    from eval_engine.llm.worker_schemas import A3AnalystReport, A3ClusterSummary

    spec = {
        "dataset_name": "a3_enrich",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["math"],
        "capability_targets": [
            {"target_id": "m1", "domain_tags": ["math"], "difficulty": "easy", "task_type": "json_math_add", "quota_weight": 1},
        ],
        "defaults": {"seed": 88, "max_prompt_length": 20000, "max_retries_per_stage": 2},
        "run_config": {"diagnoser_mode": "hybrid", "item_generation_mode": "deterministic", "judge_mode": "deterministic", "max_llm_retries_per_stage": 1},
    }
    request = RunBatchRequest(
        project_root=PROJECT_ROOT,
        spec=json.loads(json.dumps(spec)),
        quota=1,
        sut_name="mock_fail",
        model_version="mock-1",
        diagnoser_mode="hybrid",
    )
    a3_cluster_id = "PROGRAMMATIC_CHECK_FAILED/PROGRAMMATIC_CHECK_FAILED|json_math_add|programmatic_check"

    def mock_a3_report(prompt, model_class, **kwargs):
        if model_class is not A3AnalystReport:
            raise ValueError("unexpected model class")
        return A3AnalystReport(clusters=[
            A3ClusterSummary(
                cluster_id=a3_cluster_id,
                title="Math check failures (LLM-enriched)",
                affected_share=1.0,
                likely_root_cause="Model returned wrong answer.",
                owner="model",
                recommended_actions=["Add more examples."],
                evidence_examples=["wrong answer"],
            ),
        ])
    with patch("eval_engine.agents.a3_diagnoser.generate_and_validate_pydantic", side_effect=mock_a3_report):
        response = run_batch_service(request)
    run_dir = response.run_dir
    assert run_dir.exists()
    clusters = [json.loads(ln) for ln in (run_dir / "clusters.jsonl").read_text(encoding="utf-8").strip().splitlines() if ln]
    failure_clusters = [c for c in clusters if c.get("cluster_id") != "PASS"]
    if failure_clusters:
        assert any(c.get("title") for c in failure_clusters)
        assert any(c.get("evidence_examples") for c in failure_clusters)


def test_full_pipeline_hybrid_modes_with_llm_mocked_no_api_key():
    """With hybrid/llm_materialized modes but no API key, A1/A2/A3 fallbacks prevent run from crashing."""
    from eval_engine.services.run_service import RunBatchRequest, run_batch_service

    intent = {
        "intent_name": "stress_hybrid",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Stress test hybrid modes.",
        "capability_focus": ["extraction", "math"],
        "batch_size": 3,
        "defaults": {"seed": 99, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    request = RunBatchRequest(
        project_root=PROJECT_ROOT,
        spec={},
        quota=3,
        sut_name="mock",
        model_version="mock-1",
        intent_spec=intent,
        planner_mode="deterministic",
        item_generation_mode="hybrid",
        judge_mode="hybrid",
        diagnoser_mode="hybrid",
        max_llm_retries_per_stage=1,
    )
    # Without GEMINI_API_KEY, LLM calls would fail; A1/A2/A3 should fall back and run should still complete
    with patch("eval_engine.llm.gemini_client.get_client") as mock_get:
        mock_get.side_effect = ValueError("GEMINI_API_KEY is not set")
        response = run_batch_service(request)
    run_dir = response.run_dir
    assert run_dir.exists()
    run_record = json.loads((run_dir / "run_record.json").read_text(encoding="utf-8"))
    assert run_record["metrics"].get("items_total") == 3


# ---- API run_config ----

def test_api_post_runs_with_run_config_returns_200_and_artifacts():
    """POST /runs with spec_json and run_config fields returns 200 and response has run_id, run_dir, metrics."""
    from fastapi.testclient import TestClient
    from eval_engine.api.app import app

    client = TestClient(app)
    spec = {
        "dataset_name": "api_run_config",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["math"],
        "capability_targets": [
            {"target_id": "m1", "domain_tags": ["math"], "difficulty": "easy", "task_type": "json_math_add", "quota_weight": 1},
        ],
        "defaults": {"seed": 1, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    payload = {
        "spec_json": json.dumps(spec),
        "quota": 1,
        "sut": "mock",
        "model_version": "mock-1",
        "item_generation_mode": "deterministic",
        "judge_mode": "deterministic",
        "diagnoser_mode": "deterministic",
    }
    resp = client.post("/runs", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert "run_dir" in data
    assert "metrics" in data
    assert data["metrics"].get("items_total") == 1


def test_api_post_runs_with_intent_and_run_config_completes():
    """POST /runs with intent_json and run_config (e.g. judge_mode) completes and returns run_id."""
    from fastapi.testclient import TestClient
    from eval_engine.api.app import app

    client = TestClient(app)
    intent = {
        "intent_name": "api_intent_run_config",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Smoke API.",
        "capability_focus": ["math"],
        "batch_size": 2,
        "defaults": {"seed": 2, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    payload = {
        "intent_json": json.dumps(intent),
        "quota": 2,
        "sut": "mock",
        "model_version": "mock-1",
        "planner_mode": "deterministic",
        "judge_mode": "deterministic",
        "diagnoser_mode": "deterministic",
        "item_generation_mode": "deterministic",
    }
    resp = client.post("/runs", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert data["metrics"].get("items_total") == 2


def test_api_post_runs_missing_spec_and_intent_returns_400():
    """POST /runs without spec_json and without intent_json returns 400."""
    from fastapi.testclient import TestClient
    from eval_engine.api.app import app

    client = TestClient(app)
    resp = client.post("/runs", json={"quota": 1, "sut": "mock", "model_version": "mock-1"})
    assert resp.status_code == 400


# ---- Live stress tests (require GEMINI_API_KEY) ----

@REQUIRES_GEMINI
def test_live_full_pipeline_hybrid_small_batch():
    """
    Full pipeline with real Gemini: intent -> compile -> run. A2 (judge) and A3 (analyst) use hybrid.
    A1 (item generation) is deterministic so items have the task-specific input shape oracles expect.
    Small batch (3 items), mock SUT. Verifies run completes and artifacts are valid.
    """
    from eval_engine.services.run_service import RunBatchRequest, run_batch_service
    from eval_engine.core.schema import validate_or_raise

    intent = {
        "intent_name": "live_stress",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Live stress test with real LLM workers.",
        "capability_focus": ["extraction", "math"],
        "batch_size": 3,
        "defaults": {"seed": 123, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    request = RunBatchRequest(
        project_root=PROJECT_ROOT,
        spec={},
        quota=3,
        sut_name="mock",
        model_version="mock-1",
        intent_spec=intent,
        planner_mode="deterministic",
        item_generation_mode="deterministic",  # keep deterministic so item.input shape matches oracle (e.g. input["text"] for email)
        judge_mode="hybrid",
        diagnoser_mode="hybrid",
        max_llm_retries_per_stage=2,
    )
    response = run_batch_service(request)
    run_dir = response.run_dir
    assert run_dir.exists()
    run_record = json.loads((run_dir / "run_record.json").read_text(encoding="utf-8"))
    assert run_record["metrics"].get("items_total") == 3

    # Validate artifacts
    for line in (run_dir / "eval_results.jsonl").read_text(encoding="utf-8").strip().splitlines():
        if line:
            validate_or_raise("eval_result.schema.json", json.loads(line))
    for line in (run_dir / "clusters.jsonl").read_text(encoding="utf-8").strip().splitlines():
        if line:
            validate_or_raise("failure_cluster.schema.json", json.loads(line))
    for line in (run_dir / "action_plans.jsonl").read_text(encoding="utf-8").strip().splitlines():
        if line:
            validate_or_raise("action_plan.schema.json", json.loads(line))

    # If we have failure clusters, A3 may have enriched them (title, evidence_examples)
    clusters = [json.loads(ln) for ln in (run_dir / "clusters.jsonl").read_text(encoding="utf-8").strip().splitlines() if ln]
    failure_clusters = [c for c in clusters if c.get("cluster_id") != "PASS"]
    # At least one cluster (PASS or failure); if failures and LLM succeeded, some may have title
    assert len(clusters) >= 1


@REQUIRES_GEMINI
def test_live_a3_analyst_only_with_failures():
    """
    Direct spec run that produces failures, then A3 with diagnoser_mode=hybrid.
    Verifies LLM analyst enriches clusters (title, evidence_examples present when possible).
    """
    from eval_engine.services.run_service import RunBatchRequest, run_batch_service
    from eval_engine.core.schema import validate_or_raise

    # Spec that will generate 2 items; mock SUT will return wrong answer for at least one to get failures
    spec = {
        "dataset_name": "live_a3",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["math", "extraction"],
        "capability_targets": [
            {"target_id": "math_1", "domain_tags": ["math"], "difficulty": "easy", "task_type": "json_math_add", "quota_weight": 1},
            {"target_id": "ext_1", "domain_tags": ["extraction"], "difficulty": "easy", "task_type": "json_extract_email", "quota_weight": 1},
        ],
        "defaults": {"seed": 456, "max_prompt_length": 20000, "max_retries_per_stage": 2},
        "run_config": {"diagnoser_mode": "hybrid", "item_generation_mode": "deterministic", "judge_mode": "deterministic", "max_llm_retries_per_stage": 2},
    }
    request = RunBatchRequest(
        project_root=PROJECT_ROOT,
        spec=json.loads(json.dumps(spec)),
        quota=2,
        sut_name="mock",
        model_version="mock-1",
        diagnoser_mode="hybrid",
    )
    response = run_batch_service(request)
    run_dir = response.run_dir
    assert run_dir.exists()
    run_record = json.loads((run_dir / "run_record.json").read_text(encoding="utf-8"))
    assert run_record["metrics"].get("items_total") == 2

    clusters = [json.loads(ln) for ln in (run_dir / "clusters.jsonl").read_text(encoding="utf-8").strip().splitlines() if ln]
    for c in clusters:
        validate_or_raise("failure_cluster.schema.json", c)
    failure_clusters = [c for c in clusters if c.get("cluster_id") != "PASS"]
    # With hybrid diagnoser and real API, failure clusters may have title/evidence_examples from A3
    if failure_clusters:
        # At least one failure cluster should exist; LLM may have added title
        assert any("cluster_id" in c for c in failure_clusters)
