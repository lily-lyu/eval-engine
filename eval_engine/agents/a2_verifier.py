import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.failure_codes import (
    EXACT_MATCH_FAILED,
    MODEL_OUTPUT_NOT_JSON,
    MODEL_OUTPUT_SCHEMA_VIOLATION,
    PROGRAMMATIC_CHECK_FAILED,
    TRAJECTORY_CHECK_FAILED,
    RUBRIC_JUDGE_FAILED,
    EVAL_METHOD_UNSUPPORTED,
)
from ..core.timeutil import now_iso
from ..eval_methods.schema_check import run_schema_check
from ..eval_methods.exact_match import run_exact_match
from ..eval_methods.trajectory_check import run_trajectory_check
from ..eval_methods.rubric_judge import run_rubric_judge
from ..tasks.registry import CHECKER_REGISTRY
from ..core.storage import write_json


def build_verification_plan(item: Dict[str, Any], oracle: Dict[str, Any]) -> Dict[str, Any]:
    """Build a normalized verification plan from item + oracle for registry-driven execution."""
    return {
        "eval_method": oracle["eval_method"],
        "checker_name": oracle.get("checker_name"),
        "expected": oracle.get("expected"),
        "checker_config": oracle.get("checker_config"),
        "failure_taxonomy": oracle.get("failure_taxonomy") or [],
        "evidence_requirements": oracle.get("evidence_requirements"),
        "oracle": oracle,
    }


def _result(
    item_id: str,
    verdict: str,
    score: float,
    error_type: str,
    evidence: List[Dict[str, Any]],
    raw_output_ref: Dict[str, Any],
    model_version: str,
    seed: int,
    task_type: str,
    eval_method: str,
) -> Dict[str, Any]:
    """Standardized eval_result shape."""
    return {
        "item_id": item_id,
        "verdict": verdict,
        "score": score,
        "error_type": error_type,
        "evidence": evidence,
        "raw_output_ref": dict(raw_output_ref),
        "model_version": model_version,
        "seed": seed,
        "created_at": now_iso(),
        "task_type": task_type,
        "eval_method": eval_method,
    }


def verify(
    item: Dict[str, Any],
    oracle: Dict[str, Any],
    raw_output: str,
    model_version: str,
    seed: int,
    raw_output_ref: Dict[str, Any],
    tool_trace: Optional[list] = None,
    artifacts_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    eval_method = oracle["eval_method"]
    output_schema = item["output_schema"]

    ok_schema, msg_schema, parsed = run_schema_check(output_schema, raw_output)
    task_type = item.get("task_type", "")
    raw_ref = {"sha256": raw_output_ref["sha256"], "uri": raw_output_ref["uri"], "mime": raw_output_ref["mime"], "bytes": raw_output_ref["bytes"]}

    if not ok_schema:
        return _result(
            item["item_id"], "fail", 0.0,
            MODEL_OUTPUT_SCHEMA_VIOLATION if parsed is not None else MODEL_OUTPUT_NOT_JSON,
            [{"kind": "schema_check", "message": msg_schema}],
            raw_ref, model_version, seed, task_type, eval_method,
        )

    plan = build_verification_plan(item, oracle)
    eval_method = plan["eval_method"]

    if eval_method == "schema_check":
        return _result(
            item["item_id"], "pass", 1.0, "",
            [{"kind": "schema_check", "message": "schema_check passed"}],
            raw_ref, model_version, seed, task_type, eval_method,
        )

    checker_name = plan.get("checker_name") or "math_add_v1"
    if eval_method == "programmatic_check":
        checker_fn = CHECKER_REGISTRY.get(checker_name)
        if not checker_fn:
            return _result(
                item["item_id"], "fail", 0.0, EVAL_METHOD_UNSUPPORTED,
                [{"kind": "router", "code": "UNKNOWN_CHECKER", "message": f"unknown checker_name={checker_name}"}],
                raw_ref, model_version, seed, task_type, eval_method,
            )
        out = checker_fn(item["input"], parsed, plan)
        if len(out) == 2:
            ok, msg = out
            evidence_code = "PROGRAMMATIC_CHECK_FAILED" if not ok else ""
            details = {}
        else:
            ok, msg, evidence_code, details = out
        evidence = []
        if ok:
            evidence.append({"kind": "programmatic_check", "message": msg})
        else:
            ev = {
                "kind": "programmatic_check",
                "code": evidence_code or "PROGRAMMATIC_CHECK_FAILED",
                "message": msg,
                "dimension": "structured_extraction" if item.get("task_type") == "json_extract_structured" else "programmatic",
            }
            if details.get("expected") is not None:
                ev["expected"] = details.get("expected")
            if details.get("observed") is not None:
                ev["observed"] = details.get("observed")
            if details.get("field") is not None:
                ev["locator"] = {"field": details.get("field")}
            evidence.append(ev)
        return _result(
            item["item_id"], "pass" if ok else "fail", 1.0 if ok else 0.0,
            "" if ok else PROGRAMMATIC_CHECK_FAILED,
            evidence, raw_ref, model_version, seed, task_type, eval_method,
        )

    if eval_method == "exact_match":
        ok, msg = run_exact_match(parsed, plan["expected"])
        evidence = [{"kind": "exact_match", "message": msg}]
        if not ok:
            evidence[0]["code"] = "EXACT_MATCH_FAILED"
        return _result(
            item["item_id"], "pass" if ok else "fail", 1.0 if ok else 0.0,
            "" if ok else EXACT_MATCH_FAILED,
            evidence, raw_ref, model_version, seed, task_type, eval_method,
        )

    if eval_method == "trajectory_check":
        ok, msg, evidence_list = run_trajectory_check(plan["expected"], tool_trace, parsed_output=parsed)
        return _result(
            item["item_id"], "pass" if ok else "fail", 1.0 if ok else 0.0,
            "" if ok else TRAJECTORY_CHECK_FAILED,
            evidence_list[:10], raw_ref, model_version, seed, task_type, eval_method,
        )

    if eval_method == "rubric_judge":
        passed, score, evidence_list, judge_outputs = run_rubric_judge(
            plan["oracle"], parsed, item, raw_prompt=item.get("prompt", ""), judge_fn=None
        )
        if artifacts_dir is not None:
            for i, jo in enumerate(judge_outputs):
                write_json(artifacts_dir / f"{item['item_id']}_judge_{i+1}.json", jo)
        return _result(
            item["item_id"], "pass" if passed else "fail", score,
            "" if passed else RUBRIC_JUDGE_FAILED,
            evidence_list[:10], raw_ref, model_version, seed, task_type, eval_method,
        )

    return _result(
        item["item_id"], "fail", 0.0, EVAL_METHOD_UNSUPPORTED,
        [{"kind": "router", "code": "UNSUPPORTED_EVAL_METHOD", "message": f"unsupported eval_method={eval_method}"}],
        raw_ref, model_version, seed, task_type, eval_method,
    )
