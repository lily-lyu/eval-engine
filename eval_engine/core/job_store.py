"""
Persistent job state for async run status. Uses same SQLite DB as run index (runs/.index.db).
Status: queued | running | completed | failed | cancelled.
"""
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .timeutil import now_iso

# Same DB as run index so one file for runs + jobs
INDEX_DB_NAME = ".index.db"


def _db_path(project_root: Path) -> Path:
    runs_dir = os.getenv("EVAL_ENGINE_RUNS_DIR")
    base = Path(runs_dir) if runs_dir else Path(project_root) / "runs"
    return base / INDEX_DB_NAME


JOB_KEYS = [
    "job_id", "run_id", "status", "progress_pct", "current_stage", "current_item",
    "error_message", "created_at", "updated_at",
]

VALID_STATUSES = frozenset({"queued", "running", "completed", "failed", "cancelled"})


def _ensure_jobs_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            run_id TEXT,
            status TEXT NOT NULL,
            progress_pct REAL,
            current_stage TEXT,
            current_item TEXT,
            error_message TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_updated_at ON jobs(updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
    conn.commit()


def create_job(project_root: Path) -> str:
    """
    Create a new job with status=queued. Returns job_id.
    """
    project_root = Path(project_root)
    job_id = uuid4().hex[:12]
    now = now_iso()
    path = _db_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        _ensure_jobs_schema(conn)
        conn.execute(
            """
            INSERT INTO jobs (job_id, run_id, status, progress_pct, current_stage, current_item, error_message, created_at, updated_at)
            VALUES (?, ?, 'queued', 0, NULL, NULL, NULL, ?, ?)
            """,
            (job_id, "", now, now),
        )
        conn.commit()
        return job_id
    finally:
        conn.close()


def update_job(
    project_root: Path,
    job_id: str,
    *,
    run_id: Optional[str] = None,
    status: Optional[str] = None,
    progress_pct: Optional[float] = None,
    current_stage: Optional[str] = None,
    current_item: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Update job fields. Only provided kwargs are updated. status must be in VALID_STATUSES."""
    project_root = Path(project_root)
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {sorted(VALID_STATUSES)}")
    path = _db_path(project_root)
    if not path.exists():
        return
    now = now_iso()
    updates: List[str] = ["updated_at = ?"]
    params: List[Any] = [now]
    if run_id is not None:
        updates.append("run_id = ?")
        params.append(run_id)
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if progress_pct is not None:
        updates.append("progress_pct = ?")
        params.append(progress_pct)
    if current_stage is not None:
        updates.append("current_stage = ?")
        params.append(current_stage)
    if current_item is not None:
        updates.append("current_item = ?")
        params.append(current_item)
    if error_message is not None:
        updates.append("error_message = ?")
        params.append(error_message)
    params.append(job_id)
    conn = sqlite3.connect(str(path))
    try:
        _ensure_jobs_schema(conn)
        conn.execute(
            f"UPDATE jobs SET {', '.join(updates)} WHERE job_id = ?",
            params,
        )
        conn.commit()
    finally:
        conn.close()


def get_job(project_root: Path, job_id: str) -> Optional[Dict[str, Any]]:
    """Return job row as dict, or None if not found."""
    project_root = Path(project_root)
    path = _db_path(project_root)
    if not path.exists():
        return None
    conn = sqlite3.connect(str(path))
    try:
        _ensure_jobs_schema(conn)
        row = conn.execute(
            "SELECT job_id, run_id, status, progress_pct, current_stage, current_item, error_message, created_at, updated_at FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(zip(JOB_KEYS, row))
    finally:
        conn.close()


def list_jobs(project_root: Path, limit: int = 50) -> List[Dict[str, Any]]:
    """Return jobs ordered by updated_at descending."""
    project_root = Path(project_root)
    path = _db_path(project_root)
    if not path.exists():
        return []
    conn = sqlite3.connect(str(path))
    try:
        _ensure_jobs_schema(conn)
        rows = conn.execute(
            "SELECT job_id, run_id, status, progress_pct, current_stage, current_item, error_message, created_at, updated_at FROM jobs ORDER BY updated_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(zip(JOB_KEYS, r)) for r in rows]
    finally:
        conn.close()


def cancel_job(project_root: Path, job_id: str) -> bool:
    """Set job status to cancelled if it is still queued or running. Returns True if updated."""
    job = get_job(project_root, job_id)
    if not job or job.get("status") not in ("queued", "running"):
        return False
    update_job(project_root, job_id, status="cancelled")
    return True
