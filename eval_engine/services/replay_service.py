"""
Replay service: re-verify a single item from a run, optionally with overrides.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..agents.a2_verifier import verify
from ..core.storage import read_jsonl, save_artifact_text


def _run_dir(project_root: Path, run_id: str) -> Path:
    return project_root / "runs" / run_id


def _find_item_oracle(
    run_dir: Path, item_id: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    items = read_jsonl(run_dir / "released_items.jsonl")
    oracles = read_jsonl(run_dir / "released_oracles.jsonl")
    item = next((r for r in items if r.get("item_id") == item_id), None)
    if not item:
        return None, None
    # Oracles are in same order as items in this run
    idx = next(i for i, r in enumerate(items) if r.get("item_id") == item_id)
    oracle = oracles[idx] if idx < len(oracles) else None
    return item, oracle


def replay_item(
    project_root: Path,
    run_id: str,
    item_id: str,
    overrides: Optional[Dict[str, Any]] = None,
    model_version: str = "replay",
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Re-verify one item from a run. Loads item and oracle from run artifacts;
    raw_output and tool_trace can be overridden (e.g. for what-if checks).
    Returns eval_result dict; raises FileNotFoundError/ValueError if run or item missing.
    """
    run_dir = _run_dir(project_root, run_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run not found: {run_dir}")
    item, oracle = _find_item_oracle(run_dir, item_id)
    if not item or not oracle:
        raise ValueError(f"Item {item_id} not found in run {run_id}")

    artifacts_dir = run_dir / "artifacts"
    overrides = overrides or {}

    raw_output = overrides.get("raw_output")
    tool_trace = overrides.get("tool_trace")
    if raw_output is None:
        raw_path = artifacts_dir / f"{item_id}_raw.txt"
        if not raw_path.exists():
            raise FileNotFoundError(f"Raw output not found: {raw_path}")
        raw_output = raw_path.read_text(encoding="utf-8")
    if isinstance(raw_output, dict):
        raw_output = json.dumps(raw_output, ensure_ascii=False)
    if tool_trace is None:
        tt_path = artifacts_dir / f"{item_id}_tool_trace.json"
        if tt_path.exists():
            tool_trace = json.loads(tt_path.read_text(encoding="utf-8"))

    raw_ref = save_artifact_text(
        artifacts_dir, f"{item_id}_replay_raw.txt", raw_output, mime="text/plain"
    )
    er = verify(
        item,
        oracle,
        raw_output,
        model_version=model_version,
        seed=seed,
        raw_output_ref=raw_ref,
        tool_trace=tool_trace,
        artifacts_dir=artifacts_dir,
    )
    return er
