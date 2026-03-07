import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from ..core.failure_codes import DUPLICATE_ITEM, SUT_HTTP_ERROR
from ..core.schema import validate_or_raise
from ..core.run_index import add_run as index_add_run
from ..core.storage import append_jsonl, ensure_dir, save_artifact_text, write_json
from ..core.timeutil import now_iso
from ..core.versioning import compute_tool_snapshot_hash

# QA failures that are "stat-gate" / data issues: regenerate without burning retry budget
STAT_GATE_FAILURE_CODES = frozenset({DUPLICATE_ITEM})
MAX_PRECHECK_REGENS = 25  # max regenerations for stat-gate failures before aborting this slot

from .a1_item_generator import generate_item_from_target
from .a1b_oracle_builder import build_oracle
from .a4_qa_gate import qa_check
from .a2_verifier import verify
from .a3_diagnoser import diagnose
from .a5_packager import package_run
from .a6_data_producer import produce_data_requests
from .batch_planner import compile_batch_plan, plan_to_target_list


def _percentile(sorted_values: List[float], p: float) -> float:
    """Linear interpolation percentile. sorted_values must be non-empty and sorted."""
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    idx = (p / 100.0) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    if lo == hi:
        return float(sorted_values[lo])
    return sorted_values[lo] + (idx - lo) * (sorted_values[hi] - sorted_values[lo])


def _event(run_id: str, stage: str, status: str, item_id: str = "", failure_code: str = "", message: str = "", ref: Dict[str, Any] | None = None) -> Dict[str, Any]:
    e = {
        "ts": now_iso(),
        "run_id": run_id,
        "stage": stage,
        "status": status,
        "item_id": item_id,
        "failure_code": failure_code,
        "message": message
    }
    if ref is not None:
        e["ref"] = ref
    return e


def run_batch(
    project_root: Path,
    spec: Dict[str, Any],
    quota: int,
    sut_name: str,
    model_version: str,
    sut_url: str = "",
    sut_timeout: int = 30,
    progress_callback: Optional[Callable[..., None]] = None,
) -> Path:
    # Validate spec
    validate_or_raise("dataset_spec.schema.json", spec)

    seed = int(spec["defaults"]["seed"])
    rng = random.Random(seed)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"run_{spec['dataset_spec_version']}_{seed}_{ts}_{uuid4().hex[:6]}"
    runs_dir = Path(os.getenv("EVAL_ENGINE_RUNS_DIR", str(project_root / "runs")))
    run_dir = runs_dir / run_id
    artifacts_dir = run_dir / "artifacts"
    ensure_dir(run_dir)
    ensure_dir(artifacts_dir)

    tool_snapshot_hash = compute_tool_snapshot_hash(project_root)
    events_path = run_dir / "events.jsonl"

    append_jsonl(events_path, [_event(run_id, "INIT", "ok", message="run started")])
    if progress_callback:
        progress_callback("started", run_id=run_id)

    batch_plan = compile_batch_plan(spec, quota, rng)
    targets = plan_to_target_list(batch_plan)
    total_slots = len(targets)
    write_json(artifacts_dir / "batch_plan.json", {
        "quota": quota,
        "seed": seed,
        "plan": [{"target_id": e["target"]["target_id"], "count": e["count"], "task_type": e["target"]["task_type"], "difficulty": e["target"].get("difficulty"), "split": e["target"].get("split"), "risk_tier": e["target"].get("risk_tier")} for e in batch_plan],
        "total_slots": total_slots,
    })
    append_jsonl(events_path, [_event(run_id, "PLAN", "ok", message=f"batch_plan slots={total_slots}")])

    started_at = now_iso()
    seen_prompt_hashes: Set[str] = set()
    model_versions_seen: Set[str] = set()

    released_items: List[Dict[str, Any]] = []
    released_oracles: List[Dict[str, Any]] = []
    eval_results: List[Dict[str, Any]] = []

    max_retries = int(spec["defaults"]["max_retries_per_stage"])

    attempted_total = 0
    qa_failed_total = 0
    item_abort_total = 0
    latency_ms_list: List[Optional[int]] = []

    for idx, target in enumerate(targets):
        attempted_total += 1
        # A0 state machine per item: precheck loop (stat-gate regens) vs real retries (template/schema)
        attempt = 1  # current "real" attempt (only incremented on template/schema failures)
        precheck_regens = 0
        while True:
            append_jsonl(events_path, [_event(run_id, "GENERATE_ITEM", "start", message=f"attempt={attempt} precheck_regens={precheck_regens}")])
            item = generate_item_from_target(spec, target, spec["dataset_spec_version"], rng)
            if progress_callback:
                progress_pct = (idx + 1) / total_slots * 100.0 if total_slots else 0.0
                progress_callback("progress", stage="GENERATE_ITEM", item_id=item["item_id"], idx=idx + 1, total=total_slots, progress_pct=progress_pct)

            append_jsonl(events_path, [_event(run_id, "BUILD_ORACLE", "start", item_id=item["item_id"])])
            oracle = build_oracle(item)

            append_jsonl(events_path, [_event(run_id, "QA_GATE", "start", item_id=item["item_id"])])
            report = qa_check(spec, item, oracle, seen_prompt_hashes)

            # Always validate QA report schema
            validate_or_raise("qa_audit_report.schema.json", report)

            if not report["passed"]:
                qa_failed_total += 1
                append_jsonl(events_path, [_event(run_id, "QA_GATE", "fail", item_id=item["item_id"], failure_code=report["failure_code"], message=report["explanation"])])
                failure_code = report["failure_code"]

                if failure_code in STAT_GATE_FAILURE_CODES:
                    # Data/stat issue: regenerate without burning retry budget
                    precheck_regens += 1
                    if precheck_regens >= MAX_PRECHECK_REGENS:
                        item_abort_total += 1
                        append_jsonl(events_path, [_event(run_id, "ITEM_ABORT", "fail", item_id=item["item_id"], failure_code=failure_code, message="max precheck regens exceeded")])
                        break
                    continue
                # Real template/schema issue: counts as retry
                attempt += 1
                if attempt > max_retries:
                    item_abort_total += 1
                    append_jsonl(events_path, [_event(run_id, "ITEM_ABORT", "fail", item_id=item["item_id"], failure_code=failure_code, message="max retries exceeded")])
                    break
                continue

            append_jsonl(events_path, [_event(run_id, "QA_GATE", "ok", item_id=item["item_id"])])
            # RUN_MODEL (SUT)
            if progress_callback:
                progress_pct = (idx + 1) / total_slots * 100.0 if total_slots else 0.0
                progress_callback("progress", stage="RUN_MODEL", item_id=item["item_id"], idx=idx + 1, total=total_slots, progress_pct=progress_pct)
            append_jsonl(events_path, [_event(run_id, "RUN_MODEL", "start", item_id=item["item_id"], message=f"sut={sut_name}")])

            tool_trace: Optional[List[Any]] = None
            if sut_name in ("mock", "mock_fail"):
                raw_output = run_sut_mock(sut_name, item)
                item_model_version = model_version
                model_versions_seen.add(item_model_version)
                status_code = None
                latency_ms = None
            elif sut_name == "http":
                from ..sut_http import run_sut_http
                payload = {
                    "item_id": item["item_id"],
                    "prompt": item["prompt"],
                    "input": item["input"],
                    "output_schema": item["output_schema"],
                    "task_type": item["task_type"],
                }
                t0 = time.perf_counter()
                status_code, raw_output = run_sut_http(sut_url, payload, timeout_s=sut_timeout)
                latency_ms = int((time.perf_counter() - t0) * 1000)
                _ = save_artifact_text(artifacts_dir, f"{item['item_id']}_http_status.txt", str(status_code), mime="text/plain")

                if status_code != 200:
                    raw_ref = save_artifact_text(artifacts_dir, f"{item['item_id']}_raw.txt", raw_output, mime="text/plain")
                    append_jsonl(events_path, [_event(run_id, "RUN_MODEL", "fail", item_id=item["item_id"], failure_code=SUT_HTTP_ERROR, message=f"status_code={status_code} latency_ms={latency_ms}", ref={"raw_output_ref": raw_ref, "status_code": status_code, "latency_ms": latency_ms})])
                    er = {
                        "item_id": item["item_id"],
                        "verdict": "fail",
                        "score": 0.0,
                        "error_type": SUT_HTTP_ERROR,
                        "evidence": [
                            {"kind": "sut_http", "message": f"status_code={status_code} latency_ms={latency_ms}"}
                        ],
                        "raw_output_ref": {"sha256": raw_ref["sha256"], "uri": raw_ref["uri"], "mime": raw_ref["mime"], "bytes": raw_ref["bytes"]},
                        "model_version": model_version,
                        "seed": seed,
                        "created_at": now_iso(),
                    }
                    validate_or_raise("eval_result.schema.json", er)
                    model_versions_seen.add(model_version)
                    released_items.append(item)
                    released_oracles.append(oracle)
                    eval_results.append(er)
                    latency_ms_list.append(latency_ms if latency_ms is not None else None)
                    break
                # Envelope: validate against sut_response.schema.json then use
                try:
                    resp = json.loads(raw_output)
                    if isinstance(resp, dict) and "output" in resp and "model_version" in resp:
                        validate_or_raise("sut_response.schema.json", resp)
                        out = resp["output"]
                        raw_output = json.dumps(out, ensure_ascii=False) if isinstance(out, dict) else str(out)
                        item_model_version = resp.get("model_version") or "http-sut-unknown"
                        model_versions_seen.add(item_model_version)
                        if resp.get("latency_ms") is not None:
                            latency_ms = int(resp["latency_ms"])
                        tool_trace = resp.get("tool_trace")
                        if tool_trace is not None:
                            tt = json.dumps(tool_trace, ensure_ascii=False, indent=2)
                            save_artifact_text(artifacts_dir, f"{item['item_id']}_tool_trace.json", tt, mime="application/json")
                    else:
                        item_model_version = model_version
                except Exception:
                    item_model_version = model_version
                    tool_trace = None
            else:
                raise ValueError(f"Unknown sut_name={sut_name}")

            raw_ref = save_artifact_text(artifacts_dir, f"{item['item_id']}_raw.txt", raw_output, mime="text/plain")

            run_model_ref = {"raw_output_ref": raw_ref}
            if status_code is not None:
                run_model_ref["status_code"] = status_code
            if latency_ms is not None:
                run_model_ref["latency_ms"] = latency_ms
            append_jsonl(events_path, [_event(run_id, "RUN_MODEL", "ok", item_id=item["item_id"], ref=run_model_ref)])

            # VERIFY
            append_jsonl(events_path, [_event(run_id, "VERIFY", "start", item_id=item["item_id"], message=f"eval_method={oracle['eval_method']}")])
            er = verify(item, oracle, raw_output, model_version=item_model_version, seed=seed, raw_output_ref=raw_ref, tool_trace=tool_trace, artifacts_dir=artifacts_dir)
            validate_or_raise("eval_result.schema.json", er)

            append_jsonl(events_path, [_event(run_id, "VERIFY", "ok", item_id=item["item_id"], message=f"verdict={er['verdict']} error_type={er['error_type']}")])
            if progress_callback:
                progress_pct = (idx + 1) / total_slots * 100.0 if total_slots else 0.0
                progress_callback("progress", stage="VERIFY", item_id=item["item_id"], idx=idx + 1, total=total_slots, progress_pct=progress_pct)

            released_items.append(item)
            released_oracles.append(oracle)
            eval_results.append(er)
            latency_ms_list.append(latency_ms if latency_ms is not None else None)
            break

    # Run record: model_version(s) and latency summary from full run
    sorted_versions = sorted(model_versions_seen) if model_versions_seen else [model_version]
    run_model_version = sorted_versions[0] if len(sorted_versions) == 1 else "mixed"
    valid_latencies = sorted([x for x in latency_ms_list if x is not None])
    latency_p50 = int(round(_percentile(valid_latencies, 50))) if valid_latencies else None
    latency_p90 = int(round(_percentile(valid_latencies, 90))) if valid_latencies else None

    # DIAGNOSE
    append_jsonl(events_path, [_event(run_id, "DIAGNOSE", "start", message="batch diagnosis")])
    action_plans = diagnose(eval_results)
    append_jsonl(events_path, [_event(run_id, "DIAGNOSE", "ok", message=f"plans={len(action_plans)}")])

    # Data production backlog (提出数据生产策略)
    data_requests = produce_data_requests(eval_results)

    # PACKAGE
    append_jsonl(events_path, [_event(run_id, "PACKAGE", "start")])
    package_run(
        run_dir, spec, released_items, released_oracles, eval_results, action_plans,
        attempted_total=attempted_total,
        item_abort_total=item_abort_total,
        latency_ms_list=latency_ms_list,
        data_requests=data_requests,
    )
    append_jsonl(events_path, [_event(run_id, "PACKAGE", "ok", message="packaged")])

    run_record = {
        "run_id": run_id,
        "dataset_name": spec["dataset_name"],
        "dataset_spec_version": spec["dataset_spec_version"],
        "model_version": run_model_version,
        "model_versions": sorted_versions,
        "tool_snapshot_hash": tool_snapshot_hash,
        "seed": seed,
        "started_at": started_at,
        "ended_at": now_iso(),
        "paths": {
            "run_dir": str(run_dir),
            "events_jsonl": str(events_path),
            "artifacts_dir": str(artifacts_dir)
        },
        "metrics": {
            "items_total": len(released_items),
            "qa_passed": len(released_items),
            "eval_passed": sum(1 for r in eval_results if r["verdict"] == "pass"),
            "failures_total": sum(1 for r in eval_results if r["verdict"] == "fail"),
            "attempted_total": attempted_total,
            "qa_failed_total": qa_failed_total,
            "item_abort_total": item_abort_total,
            **({"latency_ms_p50": latency_p50} if latency_p50 is not None else {}),
            **({"latency_ms_p90": latency_p90} if latency_p90 is not None else {}),
        }
    }
    validate_or_raise("run_record.schema.json", run_record)
    write_json(run_dir / "run_record.json", run_record)
    project_root = run_dir.parent.parent
    index_add_run(project_root, run_record)

    append_jsonl(events_path, [_event(run_id, "END", "ok", message="run completed")])
    return run_dir


def run_sut_mock(sut_name: str, item: Dict[str, Any]) -> str:
    """
    MVP SUT: 'mock' returns correct JSON via task registry; 'mock_fail' breaks ~30% of cases.
    """
    import random as rr

    from ..tasks.registry import get_task_registry

    if sut_name == "mock_fail" and rr.random() < 0.3:
        return '{"oops": true}'

    registry = get_task_registry()
    task_type = item["task_type"]
    if task_type in registry:
        return registry[task_type].mock_sut(item)
    return "{}"
