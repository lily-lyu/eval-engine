"""
Break suite: assert that the frozen suite triggers each engine pathway.
Run: pytest tests/test_break_suite.py -v
"""
from pathlib import Path

import pytest

from eval_engine.break_suite import run_break_suite

# Path to frozen suite (repo root relative to tests/)
BREAK_SUITE_PATH = Path(__file__).resolve().parents[1] / "examples" / "break_suite.jsonl"

EXPECTED_SCENARIOS = [
    "wrong_checker_name",
    "unsupported_eval_method",
    "schema_invalid_output",
    "exact_match_wrong_answer",
    "trajectory_missing_first_tool",
    "trajectory_wrong_tool_args",
    "tool_binding_mismatch",
    "rubric_missing_evidence_requirements",
    "answer_leakage_into_prompt",
    "structured_extraction_pass",
    "structured_extraction_fail",
    "canonical_classification_pass",
    "canonical_classification_fail",
]


def test_break_suite_file_exists():
    assert BREAK_SUITE_PATH.exists(), f"Frozen break suite not found: {BREAK_SUITE_PATH}"


def test_break_suite_triggers_all_pathways():
    """Run the break suite and assert every scenario passes (pathway triggered)."""
    results, errors = run_break_suite(BREAK_SUITE_PATH)
    scenario_ids = {r["scenario_id"] for r in results}
    for sid in EXPECTED_SCENARIOS:
        assert sid in scenario_ids, f"Missing scenario in suite: {sid}"
    failed = [r["scenario_id"] for r in results if not r["passed"]]
    assert not failed, f"Break suite scenarios failed: {failed}. Errors: {errors}"
    assert not errors, f"Break suite reported errors: {errors}"


def test_break_suite_scenario_count():
    """Lock the number of break scenarios."""
    results, _ = run_break_suite(BREAK_SUITE_PATH)
    assert len(results) == len(EXPECTED_SCENARIOS)
