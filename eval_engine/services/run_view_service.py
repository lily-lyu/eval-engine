"""
Run view service: frontend-friendly parsed outputs for events and eval results (no raw text blobs).
"""
from __future__ import annotations

from typing import Any

from eval_engine.services.run_index_service import get_run_dir, read_jsonl


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
