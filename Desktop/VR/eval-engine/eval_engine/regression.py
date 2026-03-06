"""
Golden regression suite: run frozen items against SUT, enforce pass_rate and no critical failures.
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .agents.a2_verifier import verify
from .core.failure_codes import SUT_HTTP_ERROR
from .core.schema import validate_or_raise
from .core.storage import save_artifact_text
from .core.timeutil import now_iso
from .sut_http import run_sut_http


# Failure codes that should fail the regression gate (tool behavior + rubric are release-blocking when used)
CRITICAL_FAILURE_CODES = frozenset({
    "SUT_HTTP_ERROR",
    "SCHEMA_INVALID",
    "ORACLE_LEAK",
    "TRAJECTORY_CHECK_FAILED",
    "RUBRIC_JUDGE_FAILED",
})


def load_suite(suite_path: Path, validate: bool = True) -> List[Dict[str, Any]]:
    """Load golden suite: one JSON object per line with keys item, oracle. Fail closed: validate each row if validate=True."""
    rows = []
    for i, line in enumerate(suite_path.read_text(encoding="utf-8").strip().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if "item" not in row or "oracle" not in row:
            raise ValueError(f"Suite row {i}: must have 'item' and 'oracle' keys")
        if validate:
            validate_or_raise("item.schema.json", row["item"])
            validate_or_raise("oracle.schema.json", row["oracle"])
        rows.append(row)
    return rows


def run_sut_http_for_item(
    sut_url: str,
    item: Dict[str, Any],
    timeout_s: int,
) -> Tuple[int, str, Optional[List[Any]], Optional[int], str]:
    """Call HTTP SUT; return (status_code, raw_output, tool_trace, latency_ms, model_version)."""
    payload = {
        "item_id": item["item_id"],
        "prompt": item["prompt"],
        "input": item["input"],
        "output_schema": item["output_schema"],
        "task_type": item.get("task_type"),
    }
    try:
        status, raw_text = run_sut_http(sut_url, payload, timeout_s=timeout_s)
    except Exception as e:
        # Convert network failure into a synthetic non-200 response
        return 0, f"__SUT_HTTP_ERROR__ {e}", None, None, "sut-unreachable"
    if status != 200:
        return status, raw_text, None, None, ""
    try:
        resp = json.loads(raw_text)
        if isinstance(resp, dict) and "output" in resp:
            out = resp["output"]
            raw_output = json.dumps(out, ensure_ascii=False) if isinstance(out, dict) else str(out)
            tool_trace = resp.get("tool_trace")
            latency_ms = resp.get("latency_ms")
            model_version = resp.get("model_version") or ""
            return status, raw_output, tool_trace, latency_ms, model_version
    except Exception:
        pass
    return status, raw_text, None, None, ""


def run_regression(
    suite_path: Path,
    sut_url: str,
    sut_timeout: int = 30,
    artifacts_dir: Optional[Path] = None,
    model_version: str = "regression",
    seed: int = 42,
    min_pass_rate: float = 0.95,
    critical_failure_codes: Optional[Set[str]] = None,
) -> Tuple[bool, float, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Run suite against HTTP SUT. Returns (passed_gate, pass_rate, eval_results, failures).
    passed_gate is False if pass_rate < min_pass_rate or any critical failure_code appears.
    """
    critical = critical_failure_codes or CRITICAL_FAILURE_CODES
    rows = load_suite(suite_path)
    if not rows:
        return False, 0.0, [], []

    eval_results: List[Dict[str, Any]] = []
    artifacts_dir = artifacts_dir or Path(".")
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    for row in rows:
        item = row["item"]
        oracle = row["oracle"]
        status, raw_output, tool_trace, _, mv = run_sut_http_for_item(sut_url, item, sut_timeout)
        raw_ref = save_artifact_text(artifacts_dir, f"{item['item_id']}_raw.txt", raw_output, mime="text/plain")
        if status != 200:
            if status == 0:
                print(f"  [regression] SUT unreachable for item {item['item_id']}: {raw_output[:200]}")
            msg = f"status_code={status}" if status != 0 else "SUT unreachable (network/timeout error)"
            er = {
                "item_id": item["item_id"],
                "verdict": "fail",
                "score": 0.0,
                "error_type": SUT_HTTP_ERROR,
                "evidence": [{"kind": "sut_http", "message": msg}],
                "raw_output_ref": {"sha256": raw_ref["sha256"], "uri": raw_ref["uri"], "mime": raw_ref["mime"], "bytes": raw_ref["bytes"]},
                "model_version": model_version,
                "seed": seed,
                "created_at": now_iso(),
                "task_type": item.get("task_type", ""),
                "eval_method": oracle.get("eval_method", ""),
            }
        else:
            er = verify(
                item, oracle, raw_output,
                model_version=mv or model_version, seed=seed, raw_output_ref=raw_ref,
                tool_trace=tool_trace, artifacts_dir=artifacts_dir,
            )
            er["created_at"] = now_iso()
        validate_or_raise("eval_result.schema.json", er)
        eval_results.append(er)

    n = len(eval_results)
    passed = sum(1 for r in eval_results if r["verdict"] == "pass")
    pass_rate = passed / n if n else 0.0
    failure_codes = {r["error_type"] for r in eval_results if r.get("error_type")}
    critical_hit = bool(failure_codes & critical)
    passed_gate = pass_rate >= min_pass_rate and not critical_hit
    failures = [r for r in eval_results if r["verdict"] == "fail"]

    return passed_gate, pass_rate, eval_results, failures


def generate_golden_suite(
    spec_path: Path,
    output_path: Path,
    quota: int,
    seed: int = 42,
) -> None:
    """Generate frozen items+oracles and write to golden suite JSONL. Uses same planner as run_batch."""
    import random
    from .agents.batch_planner import compile_batch_plan, plan_to_target_list
    from .agents.a1_item_generator import generate_item_from_target
    from .agents.a1b_oracle_builder import build_oracle
    from .core.schema import validate_or_raise

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    validate_or_raise("dataset_spec.schema.json", spec)
    rng = random.Random(seed)
    dataset_spec_version = spec["dataset_spec_version"]

    batch_plan = compile_batch_plan(spec, quota, rng)
    targets = plan_to_target_list(batch_plan)

    seen: set = set()
    rows: List[Dict[str, Any]] = []

    for target in targets:
        item = generate_item_from_target(spec, target, dataset_spec_version, rng)
        oracle = build_oracle(item)
        key = (item["task_type"], item.get("prompt", "")[:200])
        if key in seen:
            continue
        seen.add(key)
        rows.append({"item": item, "oracle": oracle})

    while len(rows) < quota:
        refill_plan = compile_batch_plan(spec, quota - len(rows), rng)
        refill_targets = plan_to_target_list(refill_plan)
        if not refill_targets:
            break
        added_this_round = 0
        for target in refill_targets:
            item = generate_item_from_target(spec, target, dataset_spec_version, rng)
            oracle = build_oracle(item)
            key = (item["task_type"], item.get("prompt", "")[:200])
            if key in seen:
                continue
            seen.add(key)
            rows.append({"item": item, "oracle": oracle})
            added_this_round += 1
            if len(rows) >= quota:
                break
        if added_this_round == 0:
            break

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} items to {output_path}")


if __name__ == "__main__":
    pass
