"""
Break suite: frozen set of (item, oracle) + injected outputs that deliberately
trigger each engine pathway (wrong checker, unsupported method, schema failure,
exact-match failure, trajectory failures, rubric/leak QA failures).
Run via: run_break_suite(suite_path) or pytest tests/test_break_suite.py
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .agents.a2_verifier import verify
from .agents.a4_qa_gate import qa_check
from .core.schema import validate_or_raise
from .core.storage import save_artifact_text


# Minimal spec for QA gate (allowed_domain_tags, capability_targets)
BREAK_SUITE_SPEC: Dict[str, Any] = {
    "dataset_name": "break_suite",
    "dataset_spec_version": "1.0.0",
    "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    "allowed_domain_tags": ["math", "extraction", "classification", "trajectory", "rubric"],
    "capability_targets": [
        {"target_id": "math", "domain_tags": ["math"], "difficulty": "easy", "task_type": "json_math_add", "quota_weight": 1},
        {"target_id": "email", "domain_tags": ["extraction"], "difficulty": "easy", "task_type": "json_extract_email", "quota_weight": 1},
        {"target_id": "sentiment", "domain_tags": ["classification"], "difficulty": "easy", "task_type": "json_classify_sentiment", "quota_weight": 1},
        {"target_id": "traj", "domain_tags": ["trajectory"], "difficulty": "easy", "task_type": "trajectory_email_then_answer", "quota_weight": 1},
        {"target_id": "rubric", "domain_tags": ["rubric"], "difficulty": "easy", "task_type": "json_classify_sentiment", "quota_weight": 1},
        {"target_id": "structured", "domain_tags": ["extraction"], "difficulty": "easy", "task_type": "json_extract_structured", "quota_weight": 1},
        {"target_id": "canonical", "domain_tags": ["classification"], "difficulty": "easy", "task_type": "json_classify_canonical", "quota_weight": 1},
    ],
}


def load_break_suite(suite_path: Path, validate: bool = False) -> List[Dict[str, Any]]:
    """
    Load break suite JSONL. Each line: JSON with scenario_id, item, oracle,
    and either (raw_output, tool_trace?, expected_error_type, expected_evidence_code?)
    for verifier scenarios, or expected_qa_failure_code for QA scenarios.
    """
    rows = []
    for line in suite_path.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if "item" not in row or "oracle" not in row or "scenario_id" not in row:
            raise ValueError(f"Break suite row must have scenario_id, item, oracle: {list(row.keys())}")
        if validate:
            validate_or_raise("item.schema.json", row["item"])
            validate_or_raise("oracle.schema.json", row["oracle"])
        rows.append(row)
    return rows


def _make_raw_ref(artifacts_dir: Path, item_id: str, raw_output: str) -> Dict[str, Any]:
    ref = save_artifact_text(artifacts_dir, f"{item_id}_raw.txt", raw_output, mime="text/plain")
    return {"sha256": ref["sha256"], "uri": ref["uri"], "mime": ref["mime"], "bytes": ref["bytes"]}


def run_break_suite(
    suite_path: Path,
    artifacts_dir: Optional[Path] = None,
    model_version: str = "break-suite",
    seed: int = 42,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Run the break suite: for each row, either run QA check (if expected_qa_failure_code)
    or verify with injected raw_output/tool_trace (if expected_error_type).
    Returns (results, errors). results are dicts with scenario_id, passed, result/er/report; errors are failure messages.
    """
    rows = load_break_suite(suite_path)
    artifacts_dir = artifacts_dir or Path(".")
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    seen_hashes: set = set()
    results: List[Dict[str, Any]] = []
    errors: List[str] = []

    for row in rows:
        scenario_id = row["scenario_id"]
        item = row["item"]
        oracle = row["oracle"]

        if "expected_qa_failure_code" in row:
            report = qa_check(BREAK_SUITE_SPEC, item, oracle, seen_hashes)
            if not report["passed"] and report.get("failure_code") == row["expected_qa_failure_code"]:
                results.append({"scenario_id": scenario_id, "passed": True, "report": report})
            else:
                errors.append(
                    f"{scenario_id}: expected QA failure {row['expected_qa_failure_code']}, "
                    f"got passed={report['passed']} failure_code={report.get('failure_code')}"
                )
                results.append({"scenario_id": scenario_id, "passed": False, "report": report})
            continue

        raw_output = row.get("raw_output")
        if raw_output is None:
            errors.append(f"{scenario_id}: verifier scenario missing raw_output")
            results.append({"scenario_id": scenario_id, "passed": False})
            continue

        raw_ref = _make_raw_ref(artifacts_dir, item["item_id"], raw_output)
        tool_trace = row.get("tool_trace")
        er = verify(
            item, oracle, raw_output,
            model_version=model_version, seed=seed, raw_output_ref=raw_ref,
            tool_trace=tool_trace, artifacts_dir=artifacts_dir,
        )
        expected_verdict = row.get("expected_verdict")
        if expected_verdict == "pass":
            if er.get("verdict") == "pass":
                results.append({"scenario_id": scenario_id, "passed": True, "eval_result": er})
            else:
                errors.append(f"{scenario_id}: expected_verdict=pass but got verdict={er.get('verdict')}")
                results.append({"scenario_id": scenario_id, "passed": False, "eval_result": er})
        else:
            # expected_verdict == "fail" or not set: require fail and optional error_type/evidence_code
            expected_et = row.get("expected_error_type")
            expected_code = row.get("expected_evidence_code")
            ok_verdict = er.get("verdict") == "fail" if expected_verdict == "fail" else True
            ok_et = expected_et is None or er.get("error_type") == expected_et
            ok_code = expected_code is None or any(
                e.get("code") == expected_code for e in er.get("evidence", [])
            )
            if ok_verdict and ok_et and ok_code:
                results.append({"scenario_id": scenario_id, "passed": True, "eval_result": er})
            else:
                errors.append(
                    f"{scenario_id}: expected error_type={expected_et} evidence_code={expected_code}, "
                    f"got verdict={er.get('verdict')} error_type={er.get('error_type')} evidence={er.get('evidence')}"
                )
                results.append({"scenario_id": scenario_id, "passed": False, "eval_result": er})

    return results, errors


def write_break_suite_jsonl(output_path: Path) -> None:
    """Generate the frozen break_suite.jsonl from break_suite_data."""
    from .break_suite_data import build_break_suite_rows
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row in build_break_suite_rows():
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
