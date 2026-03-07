"""
Artifact service: read run summary, item result, failure clusters, data requests from a run.
Uses durable run index when available for fast run listing and summary.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.run_index import get_all_runs as index_get_all_runs
from ..core.run_index import get_recent_runs as index_get_recent_runs
from ..core.run_index import get_run_summary as index_get_run_summary
from ..core.storage import read_jsonl


def _run_dir(project_root: Path, run_id: str) -> Path:
    return project_root / "runs" / run_id


def list_all_runs(project_root: Path) -> List[Dict[str, Any]]:
    """
    List all runs from the durable index (fast). Returns list of run summary dicts.
    """
    return index_get_all_runs(Path(project_root))


def list_recent_runs(project_root: Path, limit: int = 50) -> List[Dict[str, Any]]:
    """
    List recent runs from the durable index (by ended_at desc). Returns list of run summary dicts.
    """
    return index_get_recent_runs(Path(project_root), limit=limit)


def get_run_summary(
    project_root: Path, run_id: str, from_index_only: bool = False
) -> Dict[str, Any]:
    """
    Get run summary: from index when available (fast), else from run_summary.json.
    If from_index_only=True, returns only index data (no file read).
    Returns dict; empty dict if run or file missing.
    """
    project_root = Path(project_root)
    summary = index_get_run_summary(project_root, run_id)
    if summary is not None:
        return summary
    if from_index_only:
        return {}
    run_dir = _run_dir(project_root, run_id)
    path = run_dir / "run_summary.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def get_item_result(project_root: Path, run_id: str, item_id: str) -> Dict[str, Any]:
    """
    Get eval_result for one item from the run. Returns dict; empty dict if not found.
    """
    run_dir = _run_dir(project_root, run_id)
    path = run_dir / "eval_results.jsonl"
    if not path.exists():
        return {}
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("item_id") == item_id:
            return rec
    return {}


def list_failure_clusters(project_root: Path, run_id: str) -> Dict[str, Any]:
    """
    Load action_plans (failure clusters) from the run.
    Returns dict with key "clusters" (list of action plan dicts).
    """
    run_dir = _run_dir(project_root, run_id)
    path = run_dir / "action_plans.jsonl"
    clusters = read_jsonl(path)
    return {"clusters": clusters, "run_id": run_id}


def generate_data_requests(project_root: Path, run_id: str) -> Dict[str, Any]:
    """
    Load eval_results from run and produce data_requests (same as batch diagnosis pipeline).
    Returns dict with "data_requests" list.
    """
    from ..agents.a6_data_producer import produce_data_requests

    run_dir = _run_dir(project_root, run_id)
    path = run_dir / "eval_results.jsonl"
    if not path.exists():
        return {"data_requests": [], "run_id": run_id}
    eval_results = read_jsonl(path)
    requests = produce_data_requests(eval_results)
    return {"data_requests": requests, "run_id": run_id}


# Run-root files that are allowed to be read via get_artifact_content (basename only)
RUN_ROOT_ALLOWLIST = frozenset({
    "eval_results.jsonl",
    "run_summary.json",
    "run_record.json",
    "action_plans.jsonl",
    "released_items.jsonl",
    "released_oracles.jsonl",
    "data_requests.jsonl",
    "events.jsonl",
})
RUN_ROOT_FILES = RUN_ROOT_ALLOWLIST  # alias for run_index_service–based API


def get_artifact_path(
    project_root: Path, run_id: str, filename: str
) -> Optional[Path]:
    """
    Resolve path to one artifact or run-root file.
    - If filename is in RUN_ROOT_ALLOWLIST (e.g. eval_results.jsonl), looks in run_dir.
    - Otherwise looks in run_dir/artifacts/ (e.g. {item_id}_raw.txt).
    Returns None if run or file missing.
    """
    run_dir = _run_dir(project_root, run_id)
    if not run_dir.exists():
        return None
    if filename in RUN_ROOT_ALLOWLIST:
        path = run_dir / filename
    else:
        path = run_dir / "artifacts" / filename
    if not path.exists():
        return None
    return path


def get_artifact_content(
    project_root: Path, run_id: str, filename: str, encoding: str = "utf-8"
) -> Optional[str]:
    """
    Read one artifact or run-root file as text.
    filename: for run-level files use eval_results.jsonl, run_summary.json, etc.;
    for evidence artifacts use the basename under artifacts/ (e.g. item1_raw.txt).
    Returns None if run or file missing.
    """
    path = get_artifact_path(project_root, run_id, filename)
    if path is None:
        return None
    return path.read_text(encoding=encoding)


# ---- Run-id–only API (uses run_index_service.get_run_dir; for MCP) ----

def _artifact_path_by_run(run_id: str, filename: str) -> Path:
    """Resolve artifact path by run_id (uses EVAL_ENGINE_ROOT). Raises FileNotFoundError if missing."""
    from .run_index_service import get_run_dir
    run_dir = get_run_dir(run_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run not found: {run_id}")
    if filename in RUN_ROOT_FILES:
        candidate = run_dir / filename
    else:
        candidate = run_dir / "artifacts" / filename
    if not candidate.exists():
        raise FileNotFoundError(f"Artifact not found: {filename} in run {run_id}")
    return candidate


def list_run_files(run_id: str) -> Dict[str, Any]:
    """List root files and artifact files for a run. Returns {content: {...}} or {error: {...}}."""
    from .run_index_service import get_run_dir
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
    root_files = sorted([p.name for p in run_dir.iterdir() if p.is_file()])
    artifacts_dir = run_dir / "artifacts"
    artifact_files = sorted([p.name for p in artifacts_dir.iterdir() if p.is_file()]) if artifacts_dir.exists() else []
    return {
        "content": {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "root_files": root_files,
            "artifact_files": artifact_files,
        }
    }


def get_artifact_content_by_run(run_id: str, filename: str, encoding: str = "utf-8") -> Dict[str, Any]:
    """Read one artifact by run_id (uses EVAL_ENGINE_ROOT). Returns {content: {...}} or {error: {...}}."""
    try:
        path = _artifact_path_by_run(run_id, filename)
    except FileNotFoundError as e:
        return {
            "error": {
                "kind": "not_found",
                "code": "ARTIFACT_NOT_FOUND",
                "message": str(e),
                "details": {"run_id": run_id, "filename": filename},
            }
        }
    text = path.read_text(encoding=encoding)
    payload: Dict[str, Any] = {
        "filename": path.name,
        "path": str(path),
        "text": text,
        "content_type": "text/plain",
        "bytes": path.stat().st_size,
    }
    if path.suffix == ".json":
        payload["content_type"] = "application/json"
        payload["parsed_json"] = json.loads(text)
    elif path.suffix == ".jsonl":
        payload["content_type"] = "application/jsonl"
        payload["parsed_jsonl"] = [json.loads(line) for line in text.splitlines() if line.strip()]
    return {"content": payload}
