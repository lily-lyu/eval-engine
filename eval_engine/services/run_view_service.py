"""
Run view service: frontend-friendly parsed outputs for events and eval results (no raw text blobs).
Stage metrics are aggregated from the full event log so pipeline counts are correct for large runs.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from eval_engine.services.run_index_service import get_run_dir, read_jsonl

RUN_LEVEL_STAGES = frozenset({"INIT", "PLAN", "DIAGNOSE", "DATA_REQUESTS", "PACKAGE", "END"})

STAGE_META: list[dict[str, str]] = [
    {"agent": "A0", "stage": "INIT", "label": "Initialize"},
    {"agent": "A0", "stage": "PLAN", "label": "Plan batch"},
    {"agent": "A1", "stage": "GENERATE_ITEM", "label": "Generate item"},
    {"agent": "A1b", "stage": "BUILD_ORACLE", "label": "Build oracle"},
    {"agent": "A4", "stage": "QA_GATE", "label": "QA gate"},
    {"agent": "SUT", "stage": "RUN_MODEL", "label": "Run model"},
    {"agent": "A2", "stage": "VERIFY", "label": "Verify"},
    {"agent": "A3", "stage": "DIAGNOSE", "label": "Diagnose"},
    {"agent": "A6", "stage": "DATA_REQUESTS", "label": "Data requests"},
    {"agent": "A5", "stage": "PACKAGE", "label": "Package"},
]


def _normalize_limit(limit: int | None, default: int = 200, max_limit: int = 2000) -> int:
    if limit is None:
        return default
    if limit < 1:
        return default
    return min(limit, max_limit)


def get_run_events(run_id: str, limit: int = 200) -> dict[str, Any]:
    run_dir = get_run_dir(run_id)
    if not run_dir.exists():
        return {
            "error": {
                "kind": "not_found",
                "code": "RUN_NOT_FOUND",
                "message": f"Run not found: {run_id}",
                "details": {"run_id": run_id},
            }
        }

    path = run_dir / "events.jsonl"
    if not path.exists():
        return {
            "error": {
                "kind": "not_found",
                "code": "EVENTS_NOT_FOUND",
                "message": f"events.jsonl not found for run {run_id}",
                "details": {"run_id": run_id},
            }
        }

    rows = read_jsonl(path)
    limit = _normalize_limit(limit)
    return {
        "content": {
            "run_id": run_id,
            "events": rows[:limit],
            "total": len(rows),
        }
    }


def get_eval_results(run_id: str, limit: int = 200) -> dict[str, Any]:
    run_dir = get_run_dir(run_id)
    if not run_dir.exists():
        return {
            "error": {
                "kind": "not_found",
                "code": "RUN_NOT_FOUND",
                "message": f"Run not found: {run_id}",
                "details": {"run_id": run_id},
            }
        }

    path = run_dir / "eval_results.jsonl"
    if not path.exists():
        return {
            "error": {
                "kind": "not_found",
                "code": "EVAL_RESULTS_NOT_FOUND",
                "message": f"eval_results.jsonl not found for run {run_id}",
                "details": {"run_id": run_id},
            }
        }

    rows = read_jsonl(path)
    limit = _normalize_limit(limit)
    return {
        "content": {
            "run_id": run_id,
            "results": rows[:limit],
            "total": len(rows),
        }
    }


def _safe_ts(ts: str) -> float | None:
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp() * 1000
    except (ValueError, TypeError):
        return None


def _most_common(codes: list[str]) -> str | None:
    if not codes:
        return None
    counted = Counter(c for c in codes if c)
    return counted.most_common(1)[0][0] if counted else None


def get_run_stage_metrics(run_id: str) -> dict[str, Any]:
    """
    Aggregate stage metrics from the full events.jsonl and eval_results.jsonl.
    Used for pipeline health so counts are correct for large runs (no truncation).
    Returns content.stages (list of StageRow-like dicts) or error.
    """
    run_dir = get_run_dir(run_id)
    if not run_dir.exists():
        return {
            "error": {
                "kind": "not_found",
                "code": "RUN_NOT_FOUND",
                "message": f"Run not found: {run_id}",
                "details": {"run_id": run_id},
            }
        }

    events_path = run_dir / "events.jsonl"
    if not events_path.exists():
        return {
            "error": {
                "kind": "not_found",
                "code": "EVENTS_NOT_FOUND",
                "message": f"events.jsonl not found for run {run_id}",
                "details": {"run_id": run_id},
            }
        }

    events = read_jsonl(events_path)
    results: list[dict[str, Any]] = []
    results_path = run_dir / "eval_results.jsonl"
    if results_path.exists():
        results = read_jsonl(results_path)

    sorted_events = sorted(events, key=lambda e: _safe_ts(e.get("ts") or "") or 0)

    start_timestamps_by_stage: dict[str, list[float]] = {}
    duration_by_stage: dict[str, list[float]] = {}
    ok_count: dict[str, int] = {}
    fail_count: dict[str, int] = {}
    failure_codes_by_stage: dict[str, list[str]] = {}

    for ev in sorted_events:
        ts = _safe_ts(ev.get("ts") or "")
        stage = ev.get("stage") or ""
        status = ev.get("status") or ""

        if status == "start" and ts is not None:
            start_timestamps_by_stage.setdefault(stage, []).append(ts)

        if status in ("ok", "fail") and ts is not None:
            starts = start_timestamps_by_stage.get(stage)
            if starts:
                started = starts.pop(0)
                duration_by_stage.setdefault(stage, []).append(ts - started)
            if status == "ok":
                ok_count[stage] = ok_count.get(stage, 0) + 1
            else:
                fail_count[stage] = fail_count.get(stage, 0) + 1
                fc = ev.get("failure_code") or ""
                if fc:
                    failure_codes_by_stage.setdefault(stage, []).append(fc)

    has_data_requests = any(ev.get("stage") == "DATA_REQUESTS" for ev in events)

    stages_out: list[dict[str, Any]] = []
    for meta in STAGE_META:
        stage = meta["stage"]
        if stage == "DATA_REQUESTS" and not has_data_requests:
            continue

        start_count = sum(1 for e in events if e.get("stage") == stage and e.get("status") == "start")
        ok = ok_count.get(stage, 0)
        fail = fail_count.get(stage, 0)

        input_count = start_count
        if stage in RUN_LEVEL_STAGES and input_count == 0 and (ok > 0 or fail > 0):
            input_count = 1

        durations = duration_by_stage.get(stage) or []
        avg_latency_ms = (sum(durations) / len(durations)) if durations else None

        top_failure = _most_common(failure_codes_by_stage.get(stage) or [])
        if stage == "VERIFY" and not top_failure and results:
            error_types = [r.get("error_type") or "" for r in results if r.get("error_type")]
            top_failure = _most_common(error_types)

        stages_out.append({
            "agent": meta["agent"],
            "stage": stage,
            "label": meta["label"],
            "inputCount": input_count,
            "okCount": ok,
            "failCount": fail,
            "avgLatencyMs": avg_latency_ms,
            "topFailureCode": top_failure,
        })

    return {
        "content": {
            "run_id": run_id,
            "stages": stages_out,
        }
    }
