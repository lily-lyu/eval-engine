"""
Job status API: get job state (running / finished / failed / cancelled) for web demo.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.job_store import cancel_job as store_cancel_job
from ..core.job_store import get_job as store_get_job
from ..core.job_store import list_jobs as store_list_jobs


def get_job_status(project_root: Path, job_id: str) -> Optional[Dict[str, Any]]:
    """
    Return current job state: job_id, run_id, status, progress_pct, current_stage,
    current_item, error_message, created_at, updated_at.
    Returns None if job not found.
    """
    return store_get_job(Path(project_root), job_id)


def list_jobs(project_root: Path, limit: int = 50) -> List[Dict[str, Any]]:
    """
    List jobs (e.g. for dashboard), ordered by updated_at descending.
    """
    return store_list_jobs(Path(project_root), limit=limit)


def cancel_job(project_root: Path, job_id: str) -> bool:
    """
    Set job to cancelled if it is queued or running. Returns True if updated.
    """
    return store_cancel_job(Path(project_root), job_id)
