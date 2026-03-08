import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import MAX_LLM_RETRIES_PER_STAGE
from ..core.failure_codes import (
    EXACT_MATCH_FAILED,
    MODEL_OUTPUT_NOT_JSON,
    MODEL_OUTPUT_SCHEMA_VIOLATION,
    PROGRAMMATIC_CHECK_FAILED,
    TRAJECTORY_CHECK_FAILED,
    RUBRIC_JUDGE_FAILED,
    JUDGE_SYSTEM_ERROR,
    EVAL_METHOD_UNSUPPORTED,
)
from ..core.timeutil import now_iso
from ..eval_methods.schema_check import run_schema_check
from ..eval_methods.exact_match import run_exact_match
from ..eval_methods.trajectory_check import run_trajectory_check
from ..eval_methods.rubric_judge import run_rubric_judge
from ..llm.structured import generate_and_validate_pydantic
from ..llm.worker_schemas import A2JudgeOutput
from ..tasks.registry import CHECKER_REGISTRY
from ..core.storage import write_json

logger = logging.getLogger(__name__)
_PROMPT_DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts"


def _ladder_entry(method: str, ran: bool, passed: bool, reason: str = "") -> Dict[str, Any]:
    return {"method": method, "ran": ran, "passed": passed, "reason": reason}


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
    verification_ladder: Optional[List[Dict[str, Any]]] = None,
    judge_artifacts_ref: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Standardized eval_result shape."""
    out = {
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
    if verification_ladder is not None:
        out["verification_ladder"] = verification_ladder
    if judge_artifacts_ref is not None:
        out["judge_artifacts_ref"] = judge_artifacts_ref
    return out


def _run_schema_precheck(
    output_schema: Dict[str, Any], raw_output: str
) -> Tuple[bool, str, Any, Dict[str, Any]]:
    """Run schema check; return (ok, message, parsed, ladder_entry)."""
    ok, msg, parsed = run_schema_check(output_schema, raw_output)
    entry = _ladder_entry(
        "schema_check",
        ran=True,
        passed=ok,
        reason=msg or "",
    )
    return ok, msg, parsed, entry


def _finalize_fail(
    item_id: str,
    error_type: str,
    evidence: List[Dict[str, Any]],
    raw_ref: Dict[str, Any],
    model_version: str,
    seed: int,
    task_type: str,
    eval_method: str,
    ladder: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return _result(
        item_id, "fail", 0.0, error_type, evidence,
        raw_ref, model_version, seed, task_type, eval_method,
        verification_ladder=ladder,
    )


def _verify_schema(
    item_id: str,
    raw_ref: Dict[str, Any],
    model_version: str,
    seed: int,
    task_type: str,
    eval_method: str,
) -> Dict[str, Any]:
    ladder = [_ladder_entry("schema_check", ran=True, passed=True, reason="schema_check passed")]
    return _result(
        item_id, "pass", 1.0, "",
        [{"kind": "schema_check", "message": "schema_check passed"}],
        raw_ref, model_version, seed, task_type, eval_method,
        verification_ladder=ladder,
    )


def _verify_programmatic(
    item: Dict[str, Any],
    plan: Dict[str, Any],
    parsed: Any,
    raw_ref: Dict[str, Any],
    model_version: str,
    seed: int,
    task_type: str,
    eval_method: str,
) -> Dict[str, Any]:
    checker_name = plan.get("checker_name") or "math_add_v1"
    checker_fn = CHECKER_REGISTRY.get(checker_name)
    if not checker_fn:
        ladder = [_ladder_entry("programmatic_check", ran=True, passed=False, reason=f"unknown checker_name={checker_name}")]
        return _result(
            item["item_id"], "fail", 0.0, EVAL_METHOD_UNSUPPORTED,
            [{"kind": "router", "code": "UNKNOWN_CHECKER", "message": f"unknown checker_name={checker_name}"}],
            raw_ref, model_version, seed, task_type, eval_method,
            verification_ladder=ladder,
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
    ladder = [_ladder_entry("programmatic_check", ran=True, passed=ok, reason=msg or "")]
    return _result(
        item["item_id"], "pass" if ok else "fail", 1.0 if ok else 0.0,
        "" if ok else PROGRAMMATIC_CHECK_FAILED,
        evidence, raw_ref, model_version, seed, task_type, eval_method,
        verification_ladder=ladder,
    )


def _verify_exact(
    item_id: str,
    plan: Dict[str, Any],
    parsed: Any,
    raw_ref: Dict[str, Any],
    model_version: str,
    seed: int,
    task_type: str,
    eval_method: str,
) -> Dict[str, Any]:
    ok, msg = run_exact_match(parsed, plan["expected"])
    evidence = [{"kind": "exact_match", "message": msg}]
    if not ok:
        evidence[0]["code"] = "EXACT_MATCH_FAILED"
    ladder = [_ladder_entry("exact_match", ran=True, passed=ok, reason=msg or "")]
    return _result(
        item_id, "pass" if ok else "fail", 1.0 if ok else 0.0,
        "" if ok else EXACT_MATCH_FAILED,
        evidence, raw_ref, model_version, seed, task_type, eval_method,
        verification_ladder=ladder,
    )


def _verify_trajectory(
    item_id: str,
    plan: Dict[str, Any],
    tool_trace: Optional[list],
    parsed: Any,
    raw_ref: Dict[str, Any],
    model_version: str,
    seed: int,
    task_type: str,
    eval_method: str,
) -> Dict[str, Any]:
    ok, msg, evidence_list = run_trajectory_check(plan["expected"], tool_trace, parsed_output=parsed)
    ladder = [_ladder_entry("trajectory_check", ran=True, passed=ok, reason=msg or "")]
    return _result(
        item_id, "pass" if ok else "fail", 1.0 if ok else 0.0,
        "" if ok else TRAJECTORY_CHECK_FAILED,
        evidence_list[:10], raw_ref, model_version, seed, task_type, eval_method,
        verification_ladder=ladder,
    )


def _run_llm_rubric_judge(
    item: Dict[str, Any],
    plan: Dict[str, Any],
    parsed: Any,
    raw_ref: Dict[str, Any],
    model_version: str,
    seed: int,
    task_type: str,
    eval_method: str,
    run_config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Run rubric judge via LLM (schema-first). Uses generate_and_validate_pydantic with A2JudgeOutput.
    On validation failure after retries, returns a graceful failure eval_result (fail, JUDGE_SYSTEM_ERROR).
    """
    oracle = plan.get("oracle") or {}
    rubric_schema = oracle.get("rubric_schema_version") or "v1"
    evidence_requirements = oracle.get("evidence_requirements") or {}
    template = (_PROMPT_DIR / "a2_judge.md").read_text(encoding="utf-8")
    payload = {
        "rubric_schema": rubric_schema,
        "evidence_requirements": evidence_requirements,
        "model_output": parsed,
    }
    prompt = template + "\n\n## Input\n\n```json\n" + json.dumps(payload, indent=2) + "\n```\n\nOutput only the JSON object with the five keys."
    max_retries = int(run_config.get("max_llm_retries_per_stage", MAX_LLM_RETRIES_PER_STAGE))
    try:
        llm_out = generate_and_validate_pydantic(prompt, A2JudgeOutput, max_retries=max_retries)
    except Exception as e:
        logger.warning("A2 LLM rubric judge failed after retries, returning graceful failure: %s", e)
        ladder = [_ladder_entry("rubric_judge", ran=True, passed=False, reason="LLM judge schema validation failed")]
        return _result(
            item["item_id"],
            "fail",
            0.0,
            JUDGE_SYSTEM_ERROR,
            [{"kind": "rubric_judge", "code": "JUDGE_SYSTEM_ERROR", "message": "LLM judge failed to return valid schema after retries."}],
            raw_ref,
            model_version,
            seed,
            task_type,
            eval_method,
            verification_ladder=ladder,
        )
    verdict_lower = "pass" if llm_out.verdict == "PASS" else "fail"
    error_type = "" if llm_out.verdict == "PASS" else (llm_out.error_type or (JUDGE_SYSTEM_ERROR if llm_out.verdict == "ERROR" else RUBRIC_JUDGE_FAILED))
    evidence_list = [{"kind": "rubric_judge", "message": s} for s in (llm_out.evidence or [])]
    if not evidence_list and llm_out.verdict != "PASS":
        evidence_list = [{"kind": "rubric_judge", "message": f"verdict={llm_out.verdict} score={llm_out.score}"}]
    reason = f"verdict={llm_out.verdict} score={llm_out.score} confidence={llm_out.confidence}"
    ladder = [_ladder_entry("rubric_judge", ran=True, passed=(llm_out.verdict == "PASS"), reason=reason[:500])]
    return _result(
        item["item_id"],
        verdict_lower,
        float(llm_out.score),
        error_type,
        evidence_list[:10],
        raw_ref,
        model_version,
        seed,
        task_type,
        eval_method,
        verification_ladder=ladder,
    )


def _verify_rubric(
    item: Dict[str, Any],
    plan: Dict[str, Any],
    parsed: Any,
    raw_ref: Dict[str, Any],
    model_version: str,
    seed: int,
    task_type: str,
    eval_method: str,
    artifacts_dir: Optional[Path],
) -> Dict[str, Any]:
    passed, score, evidence_list, judge_outputs = run_rubric_judge(
        plan["oracle"], parsed, item, raw_prompt=item.get("prompt", ""), judge_fn=None
    )
    judge_artifacts_ref: Optional[Dict[str, Any]] = None
    if artifacts_dir is not None and judge_outputs:
        item_id = item["item_id"]
        write_json(artifacts_dir / f"{item_id}_judge1.json", judge_outputs[0])
        write_json(artifacts_dir / f"{item_id}_judge2.json", judge_outputs[1])
        ref: Dict[str, Any] = {
            "uri": str(artifacts_dir),
            "judge_1": f"{item_id}_judge1.json",
            "judge_2": f"{item_id}_judge2.json",
        }
        if len(judge_outputs) > 2:
            write_json(artifacts_dir / f"{item_id}_arbiter.json", judge_outputs[2])
            ref["arbiter"] = f"{item_id}_arbiter.json"
        judge_artifacts_ref = ref
    reason = "pass" if passed else (evidence_list[0].get("message", "fail") if evidence_list else "fail")
    ladder = [_ladder_entry("rubric_judge", ran=True, passed=passed, reason=reason[:500])]
    return _result(
        item["item_id"], "pass" if passed else "fail", score,
        "" if passed else RUBRIC_JUDGE_FAILED,
        evidence_list[:10], raw_ref, model_version, seed, task_type, eval_method,
        verification_ladder=ladder,
        judge_artifacts_ref=judge_artifacts_ref,
    )


def verify(
    item: Dict[str, Any],
    oracle: Dict[str, Any],
    raw_output: str,
    model_version: str,
    seed: int,
    raw_output_ref: Dict[str, Any],
    tool_trace: Optional[list] = None,
    artifacts_dir: Optional[Path] = None,
    run_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run verification for one item. When eval_method is rubric_judge and run_config
    has judge_mode in ('hybrid', 'llm_materialized'), uses LLM judge; otherwise
    uses deterministic/stub path. Pass run_config=spec.get('run_config') from the
    orchestrator to enable the LLM rubric judge.
    """
    output_schema = item["output_schema"]
    raw_ref = {
        "sha256": raw_output_ref["sha256"],
        "uri": raw_output_ref["uri"],
        "mime": raw_output_ref["mime"],
        "bytes": raw_output_ref["bytes"],
    }

    ok_schema, msg_schema, parsed, schema_entry = _run_schema_precheck(output_schema, raw_output)
    ladder: List[Dict[str, Any]] = [schema_entry]

    if not ok_schema:
        error_type = MODEL_OUTPUT_SCHEMA_VIOLATION if parsed is not None else MODEL_OUTPUT_NOT_JSON
        return _finalize_fail(
            item["item_id"], error_type,
            [{"kind": "schema_check", "message": msg_schema}],
            raw_ref, model_version, seed, item.get("task_type", ""), oracle["eval_method"],
            ladder=ladder,
        )

    plan = build_verification_plan(item, oracle)
    method = plan["eval_method"]

    if method == "schema_check":
        res = _verify_schema(
            item["item_id"], raw_ref, model_version, seed, item.get("task_type", ""), method,
        )
        return {**res, "verification_ladder": ladder}

    if method == "programmatic_check":
        res = _verify_programmatic(item, plan, parsed, raw_ref, model_version, seed, item.get("task_type", ""), method)
        return {**res, "verification_ladder": ladder + res.get("verification_ladder", [])}

    if method == "exact_match":
        res = _verify_exact(item["item_id"], plan, parsed, raw_ref, model_version, seed, item.get("task_type", ""), method)
        return {**res, "verification_ladder": ladder + res.get("verification_ladder", [])}

    if method == "trajectory_check":
        res = _verify_trajectory(
            item["item_id"], plan, tool_trace, parsed, raw_ref, model_version, seed,
            item.get("task_type", ""), method,
        )
        return {**res, "verification_ladder": ladder + res.get("verification_ladder", [])}

    if method == "rubric_judge":
        judge_mode = (run_config or {}).get("judge_mode") or "deterministic"
        judge_mode = judge_mode.strip().lower() if isinstance(judge_mode, str) else "deterministic"
        if judge_mode in ("hybrid", "llm_materialized"):
            res = _run_llm_rubric_judge(
                item, plan, parsed, raw_ref, model_version, seed,
                item.get("task_type", ""), method, run_config or {},
            )
        else:
            res = _verify_rubric(item, plan, parsed, raw_ref, model_version, seed, item.get("task_type", ""), method, artifacts_dir)
        return {**res, "verification_ladder": ladder + res.get("verification_ladder", [])}

    # unit_test and any other method: not implemented; deterministic-first, no half-real methods
    ladder.append(_ladder_entry(method, ran=False, passed=False, reason="unsupported or not implemented; deterministic methods only"))
    return _result(
        item["item_id"], "fail", 0.0, EVAL_METHOD_UNSUPPORTED,
        [{"kind": "router", "code": "UNSUPPORTED_EVAL_METHOD", "message": f"unsupported eval_method={method}"}],
        raw_ref, model_version, seed, item.get("task_type", ""), method,
        verification_ladder=ladder,
    )
