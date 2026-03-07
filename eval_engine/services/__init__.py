"""
Service layer: business logic callable from CLI, MCP, web backend, tests.
All services return typed dicts or Pydantic-like response objects; no print/sys.exit.
"""
from .artifact_service import (
    generate_data_requests,
    get_artifact_content,
    get_artifact_content_by_run,
    get_artifact_path,
    get_item_result,
    get_run_summary,
    list_all_runs,
    list_failure_clusters,
    list_recent_runs,
    list_run_files,
)
from .run_index_service import get_repo_root, get_runs_dir, list_runs
from .diagnosis_service import diagnose_failures, get_run_diagnosis
from .job_service import cancel_job, get_job_status, list_jobs
from .regression_service import RegressionRequest, RegressionResponse, run_regression_service
from .replay_service import replay_item
from .run_service import RunBatchRequest, RunBatchResponse, run_batch_service

__all__ = [
    "run_batch_service",
    "RunBatchRequest",
    "RunBatchResponse",
    "run_regression_service",
    "RegressionRequest",
    "RegressionResponse",
    "replay_item",
    "list_all_runs",
    "list_recent_runs",
    "list_runs",
    "list_run_files",
    "get_repo_root",
    "get_runs_dir",
    "get_run_summary",
    "get_item_result",
    "get_artifact_content",
    "get_artifact_content_by_run",
    "list_failure_clusters",
    "generate_data_requests",
    "get_artifact_path",
    "diagnose_failures",
    "get_run_diagnosis",
    "get_job_status",
    "list_jobs",
    "cancel_job",
]
