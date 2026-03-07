"""Run index service: list runs and read run summary/item result by run_id (uses EVAL_ENGINE_ROOT / EVAL_ENGINE_RUNS_DIR)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(os.getenv("EVAL_ENGINE_ROOT", str(DEFAULT_REPO_ROOT)))
RUNS_DIR = Path(os.getenv("EVAL_ENGINE_RUNS_DIR", str(REPO_ROOT / "runs")))


def get_repo_root() -> Path:
    return REPO_ROOT


def get_runs_dir() -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return RUNS_DIR


def get_run_dir(run_id: str) -> Path:
    return get_runs_dir() / run_id


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    run_dirs = [
        p for p in get_runs_dir().iterdir()
        if p.is_dir() and p.name.startswith("run_")
    ]
    run_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    out: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        if len(out) >= limit:
            break
        run_summary_path = run_dir / "run_summary.json"
        run_record_path = run_dir / "run_record.json"

        summary = read_json(run_summary_path) if run_summary_path.exists() else {}
        record = read_json(run_record_path) if run_record_path.exists() else {}

        has_real_metadata = bool(
            record.get("started_at")
            or record.get("dataset_name")
            or summary.get("dataset_name")
        )
        if not has_real_metadata:
            continue

        counts = summary.get("counts", {})
        metrics = record.get("metrics", {})
        items_total = counts.get("items_total", metrics.get("items_total", 0))
        if items_total == 0:
            continue

        eval_passed = counts.get("eval_passed", metrics.get("eval_passed", 0))
        out.append({
            "run_id": run_dir.name,
            "run_dir": str(run_dir),
            "dataset_name": record.get("dataset_name") or summary.get("dataset_name", ""),
            "dataset_spec_version": record.get("dataset_spec_version") or summary.get("dataset_spec_version", ""),
            "model_version": record.get("model_version", ""),
            "started_at": record.get("started_at"),
            "ended_at": record.get("ended_at"),
            "items_total": items_total,
            "eval_passed": eval_passed,
            "failures_total": metrics.get("failures_total", counts.get("eval_failed", 0)),
            "pass_rate": (eval_passed / items_total if items_total else 0.0),
        })

    return out


def get_run_summary(run_id: str) -> dict[str, Any]:
    """Get run summary by run_id (uses REPO_ROOT from env). Returns {} if run or file missing."""
    run_dir = get_run_dir(run_id)
    if not run_dir.exists():
        return {}
    summary_path = run_dir / "run_summary.json"
    record_path = run_dir / "run_record.json"
    if summary_path.exists():
        return read_json(summary_path)
    if record_path.exists():
        return read_json(record_path)
    return {}


def get_item_result(run_id: str, item_id: str) -> dict[str, Any]:
    """Get one item's eval result from a run. Returns {} if not found."""
    run_dir = get_run_dir(run_id)
    if not run_dir.exists():
        return {}
    path = run_dir / "eval_results.jsonl"
    if not path.exists():
        return {}
    for rec in read_jsonl(path):
        if rec.get("item_id") == item_id:
            return rec
    return {}
