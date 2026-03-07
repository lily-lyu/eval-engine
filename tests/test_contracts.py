"""
Contract tests for eval-engine: lock verifier execution model, oracle shape,
evidence structure, diagnoser clustering, QA logic, and run_record semantics.
Run from project root: pytest tests/test_contracts.py -v
"""
import random
from datetime import datetime, timezone

import pytest

from eval_engine.agents.a2_verifier import build_verification_plan, verify
from eval_engine.agents.batch_planner import compile_batch_plan
from eval_engine.agents.a3_diagnoser import diagnose, _cluster_key, _evidence_code
from eval_engine.agents.a6_data_producer import produce_data_requests
from eval_engine.core.failure_codes import (
    EXACT_MATCH_FAILED,
    EVAL_METHOD_UNSUPPORTED,
    TRAJECTORY_CHECK_FAILED,
)
from eval_engine.core.schema import validate_or_raise
from eval_engine.core.timeutil import now_iso
from eval_engine.eval_methods.trajectory_check import (
    TOOL_BINDING_MISMATCH,
    TOOL_SEQUENCE_MISSING,
    TOOL_TRACE_NOT_LIST,
)


# ---- build_verification_plan() ----

def test_build_verification_plan_returns_right_plan_for_exact_match():
    item = {"item_id": "item_1", "task_type": "json_extract_email", "output_schema": {}}
    oracle = {
        "item_id": "item_1",
        "eval_method": "exact_match",
        "expected": {"email": "a@b.co"},
        "method_justification": "x",
        "evidence_requirements": None,
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
    }
    plan = build_verification_plan(item, oracle)
    assert plan["eval_method"] == "exact_match"
    assert plan["expected"] == {"email": "a@b.co"}
    assert plan["oracle"] is oracle


def test_build_verification_plan_returns_right_plan_for_programmatic_check():
    item = {"item_id": "item_2", "task_type": "json_math_add", "output_schema": {}}
    oracle = {
        "item_id": "item_2",
        "eval_method": "programmatic_check",
        "checker_name": "math_add_v1",
        "expected": None,
        "method_justification": "x",
        "evidence_requirements": None,
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
        "failure_taxonomy": ["PROGRAMMATIC_CHECK_FAILED"],
    }
    plan = build_verification_plan(item, oracle)
    assert plan["eval_method"] == "programmatic_check"
    assert plan["checker_name"] == "math_add_v1"
    assert plan["failure_taxonomy"] == ["PROGRAMMATIC_CHECK_FAILED"]


def test_build_verification_plan_returns_right_plan_for_trajectory_check():
    item = {"item_id": "item_3", "task_type": "trajectory_email_then_answer", "output_schema": {}}
    oracle = {
        "item_id": "item_3",
        "eval_method": "trajectory_check",
        "expected": {"required_first": ["search_contacts"], "bindings": []},
        "method_justification": "x",
        "evidence_requirements": {},
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
    }
    plan = build_verification_plan(item, oracle)
    assert plan["eval_method"] == "trajectory_check"
    assert plan["expected"]["required_first"] == ["search_contacts"]


def test_build_verification_plan_includes_evidence_requirements_and_failure_taxonomy():
    oracle = {
        "item_id": "item_x",
        "eval_method": "exact_match",
        "expected": {},
        "method_justification": "x",
        "evidence_requirements": {"require_codes": True},
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
        "failure_taxonomy": ["EXACT_MATCH_FAILED"],
    }
    plan = build_verification_plan({"item_id": "item_x"}, oracle)
    assert plan.get("evidence_requirements") == {"require_codes": True}
    assert plan.get("failure_taxonomy") == ["EXACT_MATCH_FAILED"]


# ---- unknown checker_name -> UNKNOWN_CHECKER ----

def test_unknown_checker_name_produces_unknown_checker():
    item = {
        "item_id": "item_unknown_checker",
        "task_type": "json_math_add",
        "output_schema": {"type": "object", "properties": {"answer": {"type": "integer"}}, "required": ["answer"]},
    }
    oracle = {
        "item_id": "item_unknown_checker",
        "eval_method": "programmatic_check",
        "checker_name": "nonexistent_checker_xyz",
        "expected": None,
        "method_justification": "x",
        "evidence_requirements": None,
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
    }
    raw_ref = {"sha256": "a" * 64, "uri": "file:///x", "mime": "application/json", "bytes": 0}
    result = verify(item, oracle, '{"answer": 42}', model_version="v1", seed=42, raw_output_ref=raw_ref)
    assert result["verdict"] == "fail"
    assert result["error_type"] == EVAL_METHOD_UNSUPPORTED
    assert len(result["evidence"]) == 1
    assert result["evidence"][0].get("code") == "UNKNOWN_CHECKER"
    assert "nonexistent_checker_xyz" in result["evidence"][0].get("message", "")


# ---- unknown eval_method -> UNSUPPORTED_EVAL_METHOD ----

def test_unknown_eval_method_produces_unsupported_eval_method():
    item = {
        "item_id": "item_unsupported",
        "task_type": "json_math_add",
        "output_schema": {"type": "object", "properties": {"answer": {"type": "integer"}}, "required": ["answer"]},
    }
    oracle = {
        "item_id": "item_unsupported",
        "eval_method": "unit_test",
        "expected": None,
        "method_justification": "x",
        "evidence_requirements": None,
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
    }
    raw_ref = {"sha256": "a" * 64, "uri": "file:///x", "mime": "application/json", "bytes": 0}
    result = verify(item, oracle, '{"answer": 42}', model_version="v1", seed=42, raw_output_ref=raw_ref)
    assert result["verdict"] == "fail"
    assert result["error_type"] == EVAL_METHOD_UNSUPPORTED
    assert len(result["evidence"]) == 1
    assert result["evidence"][0].get("code") == "UNSUPPORTED_EVAL_METHOD"
    assert "unit_test" in result["evidence"][0].get("message", "")


# ---- exact-match failures -> EXACT_MATCH_FAILED ----

def test_exact_match_failure_emits_exact_match_failed():
    item = {
        "item_id": "item_em",
        "task_type": "json_extract_email",
        "output_schema": {"type": "object", "properties": {"email": {"type": "string"}}, "required": ["email"]},
    }
    oracle = {
        "item_id": "item_em",
        "eval_method": "exact_match",
        "expected": {"email": "correct@example.com"},
        "method_justification": "x",
        "evidence_requirements": None,
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
    }
    raw_ref = {"sha256": "b" * 64, "uri": "file:///y", "mime": "application/json", "bytes": 0}
    result = verify(item, oracle, '{"email": "wrong@example.com"}', model_version="v1", seed=42, raw_output_ref=raw_ref)
    assert result["verdict"] == "fail"
    assert result["error_type"] == EXACT_MATCH_FAILED
    assert len(result["evidence"]) == 1
    assert result["evidence"][0].get("code") == "EXACT_MATCH_FAILED"


# ---- trajectory failures -> structured evidence codes ----

def test_trajectory_failure_emits_structured_evidence_codes():
    item = {
        "item_id": "item_traj",
        "task_type": "trajectory_email_then_answer",
        "output_schema": {"type": "object", "properties": {"email": {"type": "string"}}, "required": ["email"]},
    }
    oracle = {
        "item_id": "item_traj",
        "eval_method": "trajectory_check",
        "expected": {"required_first": ["search_contacts"]},
        "method_justification": "x",
        "evidence_requirements": {},
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
    }
    raw_ref = {"sha256": "c" * 64, "uri": "file:///z", "mime": "application/json", "bytes": 0}
    # tool_trace not a list -> TOOL_TRACE_NOT_LIST
    result = verify(
        item, oracle, '{"email": "a@b.co"}',
        model_version="v1", seed=42, raw_output_ref=raw_ref,
        tool_trace="not a list",
    )
    assert result["verdict"] == "fail"
    assert result["error_type"] == TRAJECTORY_CHECK_FAILED
    assert len(result["evidence"]) >= 1
    assert result["evidence"][0].get("code") == TOOL_TRACE_NOT_LIST


def test_trajectory_binding_mismatch_emits_code():
    item = {
        "item_id": "item_bind",
        "task_type": "trajectory_email_then_answer",
        "output_schema": {"type": "object", "properties": {"email": {"type": "string"}}, "required": ["email"]},
    }
    oracle = {
        "item_id": "item_bind",
        "eval_method": "trajectory_check",
        "expected": {
            "bindings": [
                {"tool": "search_contacts", "tool_path": "$.results[0].email", "output_path": "$.email"},
            ],
        },
        "method_justification": "x",
        "evidence_requirements": {},
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
    }
    raw_ref = {"sha256": "d" * 64, "uri": "file:///w", "mime": "application/json", "bytes": 0}
    tool_trace = [
        {"name": "search_contacts", "args": {}, "result": {"results": [{"email": "tool@example.com"}]}},
    ]
    # output says different email -> TOOL_BINDING_MISMATCH
    result = verify(
        item, oracle, '{"email": "wrong@example.com"}',
        model_version="v1", seed=42, raw_output_ref=raw_ref,
        tool_trace=tool_trace,
    )
    assert result["verdict"] == "fail"
    assert result["error_type"] == TRAJECTORY_CHECK_FAILED
    codes = [e.get("code") for e in result["evidence"] if e.get("code")]
    assert TOOL_BINDING_MISMATCH in codes


# ---- diagnoser clusters by (error_type, evidence_code, task_type, eval_method) ----

def test_diagnoser_clusters_by_error_type_evidence_code_task_type_eval_method():
    eval_results = [
        {
            "item_id": "i1",
            "verdict": "fail",
            "error_type": "EXACT_MATCH_FAILED",
            "evidence": [{"kind": "exact_match", "code": "EXACT_MATCH_FAILED", "message": "m1"}],
            "task_type": "json_extract_email",
            "eval_method": "exact_match",
        },
        {
            "item_id": "i2",
            "verdict": "fail",
            "error_type": "EXACT_MATCH_FAILED",
            "evidence": [{"kind": "exact_match", "code": "EXACT_MATCH_FAILED", "message": "m2"}],
            "task_type": "json_extract_email",
            "eval_method": "exact_match",
        },
        {
            "item_id": "i3",
            "verdict": "fail",
            "error_type": "TRAJECTORY_CHECK_FAILED",
            "evidence": [{"kind": "trajectory_check", "code": TOOL_BINDING_MISMATCH, "message": "m3"}],
            "task_type": "trajectory_email_then_answer",
            "eval_method": "trajectory_check",
        },
    ]
    clusters, plans = diagnose(eval_results)
    failure_plans = [p for p in plans if p["cluster_id"] != "PASS"]
    failure_clusters = [c for c in clusters if c["cluster_id"] != "PASS"]
    assert len(failure_plans) == 2
    assert len(failure_clusters) == 2
    cluster_ids = {p["cluster_id"] for p in failure_plans}
    assert "EXACT_MATCH_FAILED/EXACT_MATCH_FAILED|json_extract_email|exact_match" in cluster_ids
    assert f"TRAJECTORY_CHECK_FAILED/{TOOL_BINDING_MISMATCH}|trajectory_email_then_answer|trajectory_check" in cluster_ids
    # Analytical cluster shape: cluster_id, error_type, item_ids, count, hypothesis, owner, recommended_actions
    for c in failure_clusters:
        assert "item_ids" in c
        assert "hypothesis" in c
        assert "owner" in c
        assert "recommended_actions" in c
        assert isinstance(c["recommended_actions"], list)
    # Operational shape: root_cause_hypothesis, recommended_owner, priority, estimated_blast_radius, top_examples, next_action
    for p in failure_plans:
        assert "root_cause_hypothesis" in p
        assert "recommended_owner" in p
        assert p["recommended_owner"] in ("data", "model", "tooling", "product", "eval")
        assert "priority" in p
        assert "estimated_blast_radius" in p
        assert "top_examples" in p
        assert "next_action" in p
        assert isinstance(p["top_examples"], list)
        assert all("item_id" in e for e in p["top_examples"])
    # Heuristics: EXACT_MATCH → model, TOOL_BINDING_* → model
    exact_plan = next(p for p in failure_plans if "EXACT_MATCH" in p["cluster_id"])
    assert exact_plan["recommended_owner"] == "model"
    traj_plan = next(p for p in failure_plans if TOOL_BINDING_MISMATCH in p["cluster_id"])
    assert traj_plan["recommended_owner"] == "model"


def test_diagnoser_evidence_code_fallback_empty_when_no_code():
    record = {"error_type": "FAIL", "evidence": [{"kind": "legacy", "message": "no code"}], "task_type": "t", "eval_method": "em"}
    assert _evidence_code(record) == ""
    key = _cluster_key(record)
    assert key == ("FAIL", "", "t", "em")


def test_diagnoser_heuristics_unknown_checker_unsupported_eval_to_eval():
    eval_results = [
        {"item_id": "u1", "verdict": "fail", "error_type": "EVAL_METHOD_UNSUPPORTED", "evidence": [{"code": "UNKNOWN_CHECKER", "message": "x"}], "task_type": "json_math_add", "eval_method": "programmatic_check"},
        {"item_id": "u2", "verdict": "fail", "error_type": "EVAL_METHOD_UNSUPPORTED", "evidence": [{"code": "UNSUPPORTED_EVAL_METHOD", "message": "y"}], "task_type": "json_extract_email", "eval_method": "unit_test"},
    ]
    clusters, plans = diagnose(eval_results)
    failure_plans = [p for p in plans if p["cluster_id"] != "PASS"]
    assert len(failure_plans) >= 1
    for p in failure_plans:
        if "UNKNOWN_CHECKER" in p["cluster_id"] or "UNSUPPORTED_EVAL_METHOD" in p["cluster_id"]:
            assert p["recommended_owner"] == "eval"


def test_diagnoser_heuristics_tool_args_to_tooling():
    from eval_engine.eval_methods.trajectory_check import TOOL_ARGS_SCHEMA_FAILED
    eval_results = [
        {"item_id": "a1", "verdict": "fail", "error_type": "TRAJECTORY_CHECK_FAILED", "evidence": [{"code": TOOL_ARGS_SCHEMA_FAILED, "message": "arg_schema failed"}], "task_type": "trajectory_email_then_answer", "eval_method": "trajectory_check"},
    ]
    clusters, plans = diagnose(eval_results)
    failure_plans = [p for p in plans if p["cluster_id"] != "PASS"]
    assert len(failure_plans) == 1
    assert failure_plans[0]["recommended_owner"] == "tooling"


def test_diagnoser_action_plans_validate_against_schema():
    eval_results = [
        {"item_id": "v1", "verdict": "fail", "error_type": "EXACT_MATCH_FAILED", "evidence": [{"code": "EXACT_MATCH_FAILED"}], "task_type": "json_extract_email", "eval_method": "exact_match"},
    ]
    clusters, plans = diagnose(eval_results)
    for c in clusters:
        validate_or_raise("failure_cluster.schema.json", c)
    for ap in plans:
        validate_or_raise("action_plan.schema.json", ap)


# ---- old-style evidence without code still works (fallback in a6_data_producer) ----

def test_old_style_evidence_without_code_still_works_through_fallback():
    # TRAJECTORY_CHECK_FAILED but evidence has no "code", only message with "bindings mismatch"
    eval_results = [
        {
            "item_id": "i_old",
            "verdict": "fail",
            "error_type": "TRAJECTORY_CHECK_FAILED",
            "evidence": [{"kind": "trajectory_check", "message": "bindings mismatch: tool$.x=1 != output$.y=2"}],
            "task_type": "trajectory_email_then_answer",
            "eval_method": "trajectory_check",
        },
    ]
    clusters, _ = diagnose(eval_results)
    requests = produce_data_requests(clusters, eval_results)
    assert len(requests) >= 1
    # Fallback should map to TOOL_RESULT_IGNORED_OR_HALLUCINATION-style request
    issue_types = [r["issue_type"] for r in requests]
    assert "TOOL_RESULT_IGNORED_OR_HALLUCINATION" in issue_types


def test_old_style_evidence_arg_schema_fallback():
    eval_results = [
        {
            "item_id": "i_old2",
            "verdict": "fail",
            "error_type": "TRAJECTORY_CHECK_FAILED",
            "evidence": [{"kind": "trajectory_check", "message": "arg_schema failed for search_contacts: something"}],
            "task_type": "trajectory_email_then_answer",
            "eval_method": "trajectory_check",
        },
    ]
    clusters, _ = diagnose(eval_results)
    requests = produce_data_requests(clusters, eval_results)
    assert len(requests) >= 1
    assert any(r["issue_type"] == "TOOL_ARGS_BAD" for r in requests)


# ---- compile_batch_plan() deterministic under fixed seed ----

def test_compile_batch_plan_deterministic_under_fixed_seed():
    spec = {
        "dataset_name": "test",
        "dataset_spec_version": "1.0.0",
        "defaults": {"seed": 12345},
        "capability_targets": [
            {"target_id": "T1", "domain_tags": ["a"], "difficulty": "easy", "task_type": "json_math_add", "quota_weight": 2, "min_count": 1, "max_count": 10},
            {"target_id": "T2", "domain_tags": ["b"], "difficulty": "easy", "task_type": "json_extract_email", "quota_weight": 1, "min_count": 0, "max_count": 10},
        ],
    }
    quota = 10
    rng1 = random.Random(42)
    rng2 = random.Random(42)
    plan1 = compile_batch_plan(spec, quota, rng1)
    plan2 = compile_batch_plan(spec, quota, rng2)
    assert plan1 == plan2
    total = sum(e["count"] for e in plan1)
    assert total == quota


def test_compile_batch_plan_different_seed_may_differ():
    spec = {
        "dataset_name": "test",
        "dataset_spec_version": "1.0.0",
        "defaults": {"seed": 1},
        "capability_targets": [
            {"target_id": "T1", "domain_tags": ["a"], "difficulty": "easy", "task_type": "json_math_add", "quota_weight": 1, "min_count": 0, "max_count": 5},
            {"target_id": "T2", "domain_tags": ["b"], "difficulty": "easy", "task_type": "json_extract_email", "quota_weight": 1, "min_count": 0, "max_count": 5},
        ],
    }
    quota = 4
    plan_a = compile_batch_plan(spec, quota, random.Random(1))
    plan_b = compile_batch_plan(spec, quota, random.Random(2))
    # With same min/max and quota, allocation may still be deterministic by weight; just check we get valid plans
    assert sum(e["count"] for e in plan_a) == quota
    assert sum(e["count"] for e in plan_b) == quota


# ---- run_record captures started_at, ended_at, model_versions, latency_p50/p90 ----

def _make_run_record(
    run_id: str,
    started_at: str,
    ended_at: str,
    model_versions: list,
    latency_p50: int | None = None,
    latency_p90: int | None = None,
) -> dict:
    """Build run_record as the orchestrator does (contract shape)."""
    metrics = {
        "items_total": 5,
        "qa_passed": 5,
        "eval_passed": 3,
        "failures_total": 2,
        "attempted_total": 5,
        "qa_failed_total": 0,
        "item_abort_total": 0,
    }
    if latency_p50 is not None:
        metrics["latency_ms_p50"] = latency_p50
    if latency_p90 is not None:
        metrics["latency_ms_p90"] = latency_p90
    return {
        "run_id": run_id,
        "dataset_name": "test_dataset",
        "dataset_spec_version": "1.0.0",
        "model_version": model_versions[0] if len(model_versions) == 1 else "mixed",
        "model_versions": sorted(model_versions),
        "tool_snapshot_hash": "a" * 64,
        "seed": 42,
        "started_at": started_at,
        "ended_at": ended_at,
        "paths": {
            "run_dir": "/runs/run_1",
            "events_jsonl": "/runs/run_1/events.jsonl",
            "artifacts_dir": "/runs/run_1/artifacts",
        },
        "metrics": metrics,
    }


def test_run_record_captures_started_at_ended_at_model_versions_latency():
    started_at = "2026-03-06T10:00:00+00:00"
    ended_at = "2026-03-06T10:05:00+00:00"
    model_versions = ["model-v1", "model-v2"]
    run_record = _make_run_record(
        run_id="run_1_0_42_20260306T100000Z_abc123",
        started_at=started_at,
        ended_at=ended_at,
        model_versions=model_versions,
        latency_p50=120,
        latency_p90=350,
    )
    validate_or_raise("run_record.schema.json", run_record)
    assert run_record["started_at"] == started_at
    assert run_record["ended_at"] == ended_at
    assert run_record["model_versions"] == ["model-v1", "model-v2"]
    assert run_record["metrics"]["latency_ms_p50"] == 120
    assert run_record["metrics"]["latency_ms_p90"] == 350


def test_structured_extraction_checker_pass():
    """Prove structured_extraction_v1 is in the registry and passes when fields match (with normalization)."""
    item = {
        "item_id": "item_extract_1",
        "task_type": "json_extract_structured",
        "input": {"text": "Contact Alice at alice42@example.com for support."},
        "output_schema": {"type": "object", "required": ["email", "name"], "properties": {"email": {"type": "string"}, "name": {"type": "string"}}},
    }
    oracle = {
        "item_id": "item_extract_1",
        "eval_method": "programmatic_check",
        "checker_name": "structured_extraction_v1",
        "expected": {"email": "alice42@example.com", "name": "Alice"},
        "method_justification": "x",
        "evidence_requirements": None,
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
        "checker_config": {"field_normalize": {"email": "strip_lower", "name": "strip"}},
    }
    raw_ref = {"sha256": "e" * 64, "uri": "file:///e", "mime": "application/json", "bytes": 0}
    result = verify(
        item, oracle,
        '{"email": "  ALICE42@EXAMPLE.COM  ", "name": "  Alice  "}',
        model_version="v1", seed=42, raw_output_ref=raw_ref,
    )
    assert result["verdict"] == "pass"
    assert result["error_type"] == ""


def test_structured_extraction_checker_fail():
    """Structured extraction fails when a field is wrong."""
    item = {
        "item_id": "item_extract_2",
        "task_type": "json_extract_structured",
        "input": {"text": "Contact Bob at bob@example.com."},
        "output_schema": {"type": "object", "required": ["email", "name"], "properties": {"email": {"type": "string"}, "name": {"type": "string"}}},
    }
    oracle = {
        "item_id": "item_extract_2",
        "eval_method": "programmatic_check",
        "checker_name": "structured_extraction_v1",
        "expected": {"email": "bob@example.com", "name": "Bob"},
        "method_justification": "x",
        "evidence_requirements": None,
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
    }
    raw_ref = {"sha256": "f" * 64, "uri": "file:///f", "mime": "application/json", "bytes": 0}
    result = verify(item, oracle, '{"email": "bob@example.com", "name": "Wrong"}', model_version="v1", seed=42, raw_output_ref=raw_ref)
    assert result["verdict"] == "fail"
    assert result["error_type"] == "PROGRAMMATIC_CHECK_FAILED"


def test_classification_canonical_checker_pass():
    """Prove classification_canonical_v1 is in the registry and passes with canonicalization."""
    item = {
        "item_id": "item_class_1",
        "task_type": "json_classify_canonical",
        "input": {"text": "I love this product."},
        "output_schema": {"type": "object", "required": ["label"], "properties": {"label": {"type": "string"}}},
    }
    oracle = {
        "item_id": "item_class_1",
        "eval_method": "programmatic_check",
        "checker_name": "classification_canonical_v1",
        "expected": {"label": "positive"},
        "method_justification": "x",
        "evidence_requirements": None,
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
        "checker_config": {"allowed_labels": ["positive", "neutral", "negative"]},
        "canonicalization_rules": [{"from": "Positive", "to": "positive"}, {"from": "Neutral", "to": "neutral"}, {"from": "Negative", "to": "negative"}],
    }
    raw_ref = {"sha256": "g" * 64, "uri": "file:///g", "mime": "application/json", "bytes": 0}
    result = verify(item, oracle, '{"label": "Positive"}', model_version="v1", seed=42, raw_output_ref=raw_ref)
    assert result["verdict"] == "pass"
    assert result["error_type"] == ""


def test_classification_canonical_checker_fail():
    """Classification canonical fails when label is wrong after canonicalization."""
    item = {
        "item_id": "item_class_2",
        "task_type": "json_classify_canonical",
        "input": {"text": "Neither good nor bad."},
        "output_schema": {"type": "object", "required": ["label"], "properties": {"label": {"type": "string"}}},
    }
    oracle = {
        "item_id": "item_class_2",
        "eval_method": "programmatic_check",
        "checker_name": "classification_canonical_v1",
        "expected": {"label": "neutral"},
        "method_justification": "x",
        "evidence_requirements": None,
        "leak_check": {"passed": True, "notes": ""},
        "created_at": "2026-01-01T00:00:00Z",
        "checker_config": {"allowed_labels": ["positive", "neutral", "negative"]},
    }
    raw_ref = {"sha256": "h" * 64, "uri": "file:///h", "mime": "application/json", "bytes": 0}
    result = verify(item, oracle, '{"label": "positive"}', model_version="v1", seed=42, raw_output_ref=raw_ref)
    assert result["verdict"] == "fail"
    assert result["error_type"] == "PROGRAMMATIC_CHECK_FAILED"


def test_run_record_valid_without_latency_when_no_http_calls():
    started_at = now_iso()
    ended_at = now_iso()
    run_record = _make_run_record(
        run_id="run_2_0_42_20260306T100000Z_def456",
        started_at=started_at,
        ended_at=ended_at,
        model_versions=["mock-1"],
        latency_p50=None,
        latency_p90=None,
    )
    validate_or_raise("run_record.schema.json", run_record)
    assert "latency_ms_p50" not in run_record["metrics"]
    assert "latency_ms_p90" not in run_record["metrics"]
