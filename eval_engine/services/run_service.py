"""
Run batch service: execute a full batch from spec; returns structured response.
Creates a job and updates status/progress for async status API.
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional

from ..agents.a0_orchestrator import run_batch
from ..core.job_store import create_job, update_job


class RunBatchRequest:
    """Request to run a batch. All fields for orchestration; no CLI-specific args."""

    def __init__(
        self,
        project_root: Path,
        spec: Dict[str, Any],
        quota: int = 20,
        sut_name: str = "mock",
        model_version: str = "mock-1",
        sut_url: str = "",
        sut_timeout: int = 30,
    ):
        self.project_root = Path(project_root)
        self.spec = spec
        self.quota = quota
        self.sut_name = sut_name
        self.model_version = model_version
        self.sut_url = sut_url
        self.sut_timeout = sut_timeout


class RunBatchResponse:
    """Structured response from run_batch_service."""

    def __init__(
        self,
        run_id: str,
        run_dir: Path,
        paths: Dict[str, str],
        metrics: Dict[str, Any],
        run_record: Optional[Dict[str, Any]] = None,
        job_id: Optional[str] = None,
    ):
        self.run_id = run_id
        self.run_dir = Path(run_dir)
        self.paths = paths
        self.metrics = metrics
        self.run_record = run_record or {}
        self.job_id = job_id

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "paths": self.paths,
            "metrics": self.metrics,
            "run_record": self.run_record,
        }
        if self.job_id is not None:
            out["job_id"] = self.job_id
        return out


def run_batch_service(request: RunBatchRequest) -> RunBatchResponse:
    """
    Run a batch end-to-end. Creates a job and updates status/progress so
    get_job_status(job_id) can be polled. Returns typed response; no print or sys.exit.
    """
    project_root = request.project_root
    job_id = create_job(project_root)

    def progress_callback(event: str, **kwargs: Any) -> None:
        if event == "started":
            update_job(project_root, job_id, run_id=kwargs.get("run_id", ""), status="running")
        elif event == "progress":
            update_job(
                project_root,
                job_id,
                current_stage=kwargs.get("stage"),
                current_item=kwargs.get("item_id"),
                progress_pct=kwargs.get("progress_pct"),
            )

    try:
        run_dir = run_batch(
            project_root=project_root,
            spec=request.spec,
            quota=request.quota,
            sut_name=request.sut_name,
            model_version=request.model_version,
            sut_url=request.sut_url,
            sut_timeout=request.sut_timeout,
            progress_callback=progress_callback,
        )
        update_job(project_root, job_id, status="completed", progress_pct=100.0, current_stage="END", current_item=None)
    except Exception as e:
        update_job(
            project_root,
            job_id,
            status="failed",
            error_message=str(e),
        )
        raise

    run_id = run_dir.name
    run_record_path = run_dir / "run_record.json"
    run_record: Dict[str, Any] = {}
    if run_record_path.exists():
        run_record = json.loads(run_record_path.read_text(encoding="utf-8"))
    paths = run_record.get("paths", {})
    metrics = run_record.get("metrics", {})
    return RunBatchResponse(
        run_id=run_id,
        run_dir=run_dir,
        paths=paths,
        metrics=metrics,
        run_record=run_record,
        job_id=job_id,
    )
