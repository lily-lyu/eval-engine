"""
Diagnosis service: cluster failures and produce action plans from eval_results.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from ..agents.a3_diagnoser import diagnose
from ..core.storage import read_jsonl

from .run_index_service import get_run_dir as get_run_dir_by_id, read_jsonl as read_jsonl_from_path


DEFAULT_OWNER_BY_ERROR = {
    "EXACT_MATCH_FAILED": "data/eval",
    "SCHEMA_CHECK_FAILED": "model",
    "PROGRAMMATIC_CHECK_FAILED": "model",
    "TRAJECTORY_CHECK_FAILED": "agent/tooling",
    "TOOL_ARGS_BAD": "agent/tooling",
    "TOOL_RESULT_IGNORED_OR_HALLUCINATION": "agent/product",
    "SCHEMA_INVALID": "data/eval",
    "SUT_HTTP_ERROR": "model/sut",
    "DUPLICATE_ITEM": "data/eval",
    "DISTRIBUTION_MISMATCH": "data/eval",
}

DEFAULT_ACTION_BY_ERROR = {
    "EXACT_MATCH_FAILED": "Add more direct-answer supervision and near-miss negatives for exact field/value copying.",
    "SCHEMA_CHECK_FAILED": "Add schema-constrained decoding examples and validation retries.",
    "PROGRAMMATIC_CHECK_FAILED": "Collect targeted numeric/logic failure examples and re-run programmatic checks.",
    "TRAJECTORY_CHECK_FAILED": "Add more tool-use supervision and tighten trajectory requirements.",
    "TOOL_ARGS_BAD": "Collect tool-call examples with correct argument schema and negative counterexamples.",
    "TOOL_RESULT_IGNORED_OR_HALLUCINATION": "Collect examples that bind tool results into the final answer correctly.",
    "SCHEMA_INVALID": "Fix item/oracle JSON to match schema; check schema file and $ref resolution.",
    "SUT_HTTP_ERROR": "Check SUT availability and request format; fix schema or endpoint.",
    "DUPLICATE_ITEM": "Regenerate item with different input or surface form.",
    "DISTRIBUTION_MISMATCH": "Batch slot overfilled; skip or rebalance quota.",
}


def _normalize_cluster_row(
    error_type: str,
    count: int,
    sample_item_ids: List[str],
    owner: str,
    recommended_action: str,
) -> Dict[str, Any]:
    """Return a cluster row with the exact shape expected by the UI."""
    return {
        "error_type": str(error_type),
        "count": int(count),
        "sample_item_ids": list(sample_item_ids)[:10],
        "owner": str(owner),
        "recommended_action": str(recommended_action),
    }


def _run_dir(project_root: Path, run_id: str) -> Path:
    return project_root / "runs" / run_id


def diagnose_failures(eval_results: List[Dict[str, Any]]) -> tuple:
    """
    Cluster failures and return (clusters, action_plans). Same as batch pipeline diagnosis; no I/O.
    """
    return diagnose(eval_results)


def get_run_diagnosis(project_root: Path, run_id: str) -> Dict[str, Any]:
    """
    Load eval_results from run, run diagnosis, return clusters and action plans.
    Returns dict with "clusters", "action_plans", and "run_id".
    """
    run_dir = _run_dir(project_root, run_id)
    path = run_dir / "eval_results.jsonl"
    if not path.exists():
        return {"clusters": [], "action_plans": [], "run_id": run_id}
    eval_results = read_jsonl(path)
    clusters, action_plans = diagnose(eval_results)
    return {"clusters": clusters, "action_plans": action_plans, "run_id": run_id}


def _clusters_from_events(run_dir: Path, run_id: str) -> List[Dict[str, Any]]:
    """Build cluster rows from QA_GATE fail events when eval_results.jsonl is missing (e.g. blocked run)."""
    events_path = run_dir / "events.jsonl"
    if not events_path.exists():
        return []
    events = read_jsonl_from_path(events_path)
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ev in events:
        if ev.get("stage") != "QA_GATE" or ev.get("status") != "fail":
            continue
        error_type = ev.get("failure_code") or "UNKNOWN_FAILURE"
        grouped[error_type].append(ev)
    clusters = []
    for error_type, items in grouped.items():
        sample_item_ids = [e.get("item_id", "") for e in items if e.get("item_id")][:10]
        clusters.append(
            _normalize_cluster_row(
                error_type=error_type,
                count=len(items),
                sample_item_ids=sample_item_ids,
                owner=DEFAULT_OWNER_BY_ERROR.get(error_type, "eval/platform"),
                recommended_action=DEFAULT_ACTION_BY_ERROR.get(
                    error_type,
                    "Inspect evidence, collect targeted data, and rerun regression.",
                ),
            )
        )
    clusters.sort(key=lambda x: x["count"], reverse=True)
    return clusters


def list_failure_clusters(run_id: str) -> Dict[str, Any]:
    """
    List failure clusters for a run by error_type (run_id-only API for MCP).
    Returns content with run_id, clusters (error_type, count, sample_item_ids, owner, recommended_action), or error.
    When eval_results.jsonl is missing (e.g. QA-blocked run), clusters are built from QA_GATE fail events.
    """
    run_dir = get_run_dir_by_id(run_id)
    if not run_dir.exists():
        return {
            "error": {
                "kind": "not_found",
                "code": "RUN_NOT_FOUND",
                "message": f"Run not found: {run_id}",
                "details": {"run_id": run_id},
            }
        }

    eval_results_path = run_dir / "eval_results.jsonl"
    clusters: List[Dict[str, Any]] = []

    if eval_results_path.exists():
        rows = read_jsonl_from_path(eval_results_path)
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            verdict = row.get("verdict", "")
            if verdict == "pass":
                continue
            error_type = row.get("error_type") or "UNKNOWN_FAILURE"
            grouped[error_type].append(row)
        for error_type, items in grouped.items():
            clusters.append(
                _normalize_cluster_row(
                    error_type=error_type,
                    count=len(items),
                    sample_item_ids=[r.get("item_id", "") for r in items[:10]],
                    owner=DEFAULT_OWNER_BY_ERROR.get(error_type, "eval/platform"),
                    recommended_action=DEFAULT_ACTION_BY_ERROR.get(
                        error_type,
                        "Inspect evidence, collect targeted data, and rerun regression.",
                    ),
                )
            )
        clusters.sort(key=lambda x: x["count"], reverse=True)
    else:
        clusters = _clusters_from_events(run_dir, run_id)

    return {
        "content": {
            "run_id": run_id,
            "clusters": clusters,
            "clusters_count": len(clusters),
        }
    }
