"""
Durable run index (SQLite). Source of truth remains JSONL/filesystem;
this index enables fast listing and run summary without reading large files.
"""
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


INDEX_DB_NAME = ".index.db"


def _runs_dir(project_root: Path) -> Path:
    runs_dir = os.getenv("EVAL_ENGINE_RUNS_DIR")
    return Path(runs_dir) if runs_dir else Path(project_root) / "runs"


def _index_path(project_root: Path) -> Path:
    return _runs_dir(project_root) / INDEX_DB_NAME


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            run_dir TEXT NOT NULL,
            started_at TEXT,
            ended_at TEXT,
            dataset_name TEXT,
            dataset_spec_version TEXT,
            model_version TEXT,
            model_versions TEXT,
            pass_rate REAL,
            failures_total INTEGER,
            items_total INTEGER,
            eval_passed INTEGER,
            artifacts_dir TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_runs_ended_at ON runs(ended_at DESC)"
    )
    conn.commit()


def add_run(project_root: Path, run_record: Dict[str, Any]) -> None:
    """
    Register a run in the index. Call after run_record.json is written.
    Keeps index in sync with filesystem; JSONL/files remain source of truth.
    """
    project_root = Path(project_root)
    paths = run_record.get("paths") or {}
    metrics = run_record.get("metrics") or {}
    run_dir = paths.get("run_dir") or ""
    artifacts_dir = paths.get("artifacts_dir") or ""
    items_total = metrics.get("items_total", 0) or 0
    eval_passed = metrics.get("eval_passed", 0) or 0
    failures_total = metrics.get("failures_total", 0) or 0
    pass_rate = (eval_passed / items_total) if items_total else 0.0
    model_versions = run_record.get("model_versions") or []
    if isinstance(model_versions, list):
        model_versions = json.dumps(model_versions)

    index_file = _index_path(project_root)
    index_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(index_file))
    try:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO runs (
                run_id, run_dir, started_at, ended_at, dataset_name,
                dataset_spec_version, model_version, model_versions,
                pass_rate, failures_total, items_total, eval_passed, artifacts_dir
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_record.get("run_id", ""),
                run_dir,
                run_record.get("started_at"),
                run_record.get("ended_at"),
                run_record.get("dataset_name"),
                run_record.get("dataset_spec_version"),
                run_record.get("model_version"),
                model_versions if isinstance(model_versions, str) else json.dumps(model_versions),
                pass_rate,
                failures_total,
                items_total,
                eval_passed,
                artifacts_dir,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _row_to_summary(row: tuple, keys: List[str]) -> Dict[str, Any]:
    d: Dict[str, Any] = {}
    for i, k in enumerate(keys):
        if i >= len(row):
            break
        v = row[i]
        if k == "model_versions" and v is not None:
            try:
                v = json.loads(v)
            except Exception:
                v = []
        d[k] = v
    return d


def get_run_summary(project_root: Path, run_id: str) -> Optional[Dict[str, Any]]:
    """
    Return run summary from index (fast). Returns None if run not in index.
    """
    project_root = Path(project_root)
    index_file = _index_path(project_root)
    if not index_file.exists():
        return None
    conn = sqlite3.connect(str(index_file))
    try:
        keys = [
            "run_id", "run_dir", "started_at", "ended_at", "dataset_name",
            "dataset_spec_version", "model_version", "model_versions",
            "pass_rate", "failures_total", "items_total", "eval_passed", "artifacts_dir",
        ]
        row = conn.execute(
            "SELECT run_id, run_dir, started_at, ended_at, dataset_name, "
            "dataset_spec_version, model_version, model_versions, "
            "pass_rate, failures_total, items_total, eval_passed, artifacts_dir "
            "FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_summary(row, keys)
    finally:
        conn.close()


def get_run_dir(project_root: Path, run_id: str) -> Optional[Path]:
    """Return run_dir path for a run from index, or None."""
    summary = get_run_summary(project_root, run_id)
    if not summary or not summary.get("run_dir"):
        return None
    return Path(summary["run_dir"])


def get_all_runs(project_root: Path) -> List[Dict[str, Any]]:
    """Return all runs from index, ordered by ended_at descending."""
    return _runs_query(project_root, limit=None)


def get_recent_runs(project_root: Path, limit: int = 50) -> List[Dict[str, Any]]:
    """Return recent runs from index (by ended_at desc)."""
    return _runs_query(project_root, limit=limit)


def backfill_from_fs(project_root: Path) -> int:
    """
    Scan runs/ for run_record.json and add each to the index. Use once to index
    existing runs. Returns number of runs indexed.
    """
    project_root = Path(project_root)
    runs_dir = _runs_dir(project_root)
    if not runs_dir.exists():
        return 0
    count = 0
    for path in runs_dir.iterdir():
        if path.is_dir() and not path.name.startswith("."):
            record_file = path / "run_record.json"
            if record_file.exists():
                try:
                    run_record = json.loads(record_file.read_text(encoding="utf-8"))
                    add_run(project_root, run_record)
                    count += 1
                except Exception:
                    pass
    return count


def _runs_query(project_root: Path, limit: Optional[int]) -> List[Dict[str, Any]]:
    project_root = Path(project_root)
    index_file = _index_path(project_root)
    if not index_file.exists():
        return []
    conn = sqlite3.connect(str(index_file))
    try:
        keys = [
            "run_id", "run_dir", "started_at", "ended_at", "dataset_name",
            "dataset_spec_version", "model_version", "model_versions",
            "pass_rate", "failures_total", "items_total", "eval_passed", "artifacts_dir",
        ]
        sql = (
            "SELECT run_id, run_dir, started_at, ended_at, dataset_name, "
            "dataset_spec_version, model_version, model_versions, "
            "pass_rate, failures_total, items_total, eval_passed, artifacts_dir "
            "FROM runs ORDER BY ended_at DESC"
        )
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        rows = conn.execute(sql).fetchall()
        return [_row_to_summary(r, keys) for r in rows]
    finally:
        conn.close()
