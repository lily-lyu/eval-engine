"""Tests for dual-judge + arbiter rubric_judge module."""
from eval_engine.eval_methods.rubric_judge import (
    RUBRIC_SCHEMA_VERSION,
    SCORE_DELTA_THRESHOLD,
    arbitrate,
    build_arbiter_prompt,
    build_judge_prompt,
    call_judge,
    compare_judgements,
    run_rubric_judge,
)


def test_build_judge_prompt_includes_evidence_requirements_and_schema_version():
    oracle = {
        "rubric_schema_version": "v1",
        "evidence_requirements": {"rules": ["label matches sentiment"], "observable": True},
    }
    item = {"task_type": "json_classify_sentiment", "prompt": "Classify."}
    parsed = {"label": "neutral"}
    prompt = build_judge_prompt(oracle, parsed, item, "Classify.")
    assert "rubric_schema_version" in prompt
    assert "evidence_requirements" in prompt or "rules" in prompt
    assert "json_classify_sentiment" in prompt
    assert "neutral" in prompt


def test_call_judge_returns_normalized_output_with_evidence():
    out = call_judge("test_model", "dummy prompt", judge_fn=None)
    assert out["verdict"] in ("pass", "fail")
    assert 0 <= out["score"] <= 1
    assert "reason" in out
    assert isinstance(out["evidence"], list)
    assert all("rule" in e and "observation" in e for e in out["evidence"])
    assert "model_version" in out


def test_compare_judgements_accept_mean_when_verdicts_match_and_delta_small():
    j1 = {"verdict": "pass", "score": 0.8, "evidence": [], "reason": "", "model_version": "m1"}
    j2 = {"verdict": "pass", "score": 0.85, "evidence": [], "reason": "", "model_version": "m2"}
    cmp = compare_judgements(j1, j2)
    assert cmp["verdicts_match"] is True
    assert cmp["score_delta"] == 0.05
    assert cmp["accept_mean"] is True


def test_compare_judgements_no_accept_mean_when_verdicts_differ():
    j1 = {"verdict": "pass", "score": 0.9, "evidence": [], "reason": "", "model_version": "m1"}
    j2 = {"verdict": "fail", "score": 0.3, "evidence": [], "reason": "", "model_version": "m2"}
    cmp = compare_judgements(j1, j2)
    assert cmp["verdicts_match"] is False
    assert cmp["accept_mean"] is False


def test_compare_judgements_no_accept_mean_when_delta_above_threshold():
    j1 = {"verdict": "pass", "score": 0.9, "evidence": [], "reason": "", "model_version": "m1"}
    j2 = {"verdict": "pass", "score": 0.5, "evidence": [], "reason": "", "model_version": "m2"}
    cmp = compare_judgements(j1, j2)
    assert cmp["verdicts_match"] is True
    assert cmp["score_delta"] >= SCORE_DELTA_THRESHOLD
    assert cmp["accept_mean"] is False


def test_arbitrate_returns_structured_evidence():
    j1 = {"verdict": "pass", "score": 0.9, "evidence": [{"rule": "r1", "observation": "ok"}], "reason": "", "model_version": "m1"}
    j2 = {"verdict": "fail", "score": 0.4, "evidence": [{"rule": "r1", "observation": "missing"}], "reason": "", "model_version": "m2"}
    oracle = {"evidence_requirements": {"rules": ["r1"]}, "rubric_schema_version": "v1"}
    item = {"task_type": "classify", "item_id": "t1"}
    parsed = {"label": "x"}
    out = arbitrate(j1, j2, oracle, item, parsed, arbiter_fn=None)
    assert "verdict" in out and "score" in out and "evidence" in out
    assert isinstance(out["evidence"], list)
    assert all("rule" in e and "observation" in e for e in out["evidence"])


def test_run_rubric_judge_public_api():
    oracle = {
        "evidence_requirements": {"rules": ["label present"]},
        "rubric_schema_version": "v1",
    }
    item = {"item_id": "i1", "task_type": "classify", "prompt": "Classify."}
    parsed = {"label": "neutral"}
    passed, score, evidence, judge_outputs = run_rubric_judge(
        oracle, parsed, item, raw_prompt="Classify.", judge_fn=None
    )
    assert isinstance(passed, bool)
    assert 0 <= score <= 1
    assert isinstance(evidence, list)
    assert len(judge_outputs) >= 2  # j1, j2; arbiter only if accept_mean is False
    assert judge_outputs[0].get("judge_index") == 1
    assert judge_outputs[1].get("judge_index") == 2
    assert judge_outputs[0].get("rubric_schema_version") == RUBRIC_SCHEMA_VERSION


def test_run_rubric_judge_fails_without_evidence_requirements():
    oracle = {"evidence_requirements": None, "rubric_schema_version": "v1"}
    item = {"item_id": "i1", "task_type": "classify", "prompt": "Classify."}
    parsed = {"label": "neutral"}
    passed, score, evidence, judge_outputs = run_rubric_judge(oracle, parsed, item, raw_prompt="Classify.")
    assert passed is False
    assert score == 0.0
    assert len(judge_outputs) == 0
    assert any("evidence_requirements" in e.get("message", "") for e in evidence)


def test_run_rubric_judge_arbiter_used_when_score_delta_large():
    """When both judges agree on verdict but score delta >= 0.15, arbiter is called."""
    call_count = [0]

    def stateful_judge(_m: str, _p: str):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"verdict": "pass", "score": 0.9, "reason": "ok", "evidence": [{"rule": "r1", "observation": "ok"}], "model_version": "j"}
        return {"verdict": "pass", "score": 0.5, "reason": "low", "evidence": [{"rule": "r1", "observation": "meh"}], "model_version": "j"}

    oracle = {"evidence_requirements": {"rules": ["r1"]}, "rubric_schema_version": "v1"}
    item = {"item_id": "i1", "task_type": "classify", "prompt": "Classify."}
    parsed = {"label": "neutral"}
    _, _, _, out = run_rubric_judge(oracle, parsed, item, raw_prompt="x", judge_fn=stateful_judge)
    # Score delta 0.4 >= 0.15 -> accept_mean False -> arbiter called
    assert len(out) == 3, "expected arbiter as third output when score delta >= threshold"
    assert "evidence" in out[2] and isinstance(out[2]["evidence"], list)


def test_build_arbiter_prompt_includes_both_judges_and_evidence_requirements():
    j1 = {"verdict": "pass", "score": 0.8, "reason": "r1", "evidence": [{"rule": "r1", "observation": "o1"}]}
    j2 = {"verdict": "fail", "score": 0.4, "reason": "r2", "evidence": [{"rule": "r1", "observation": "o2"}]}
    oracle = {"evidence_requirements": {"rules": ["r1"]}, "rubric_schema_version": "v1"}
    item = {"task_type": "classify"}
    parsed = {"label": "x"}
    prompt = build_arbiter_prompt(j1, j2, oracle, item, parsed)
    assert "Judge 1" in prompt and "Judge 2" in prompt
    assert "pass" in prompt and "fail" in prompt
    assert "evidence" in prompt or "rule-by-rule" in prompt
