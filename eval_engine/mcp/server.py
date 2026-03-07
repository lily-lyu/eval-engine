"""
MCP server using the official Python SDK (FastMCP). Exposes eval-engine tools
and resources. Run with: python -m eval_engine.mcp.server
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from eval_engine.services.run_index_service import (
    get_repo_root,
    get_run_summary as get_run_summary_service,
    get_item_result as get_item_result_service,
    list_runs as list_runs_service,
)
from eval_engine.services.artifact_service import (
    list_run_files as list_run_files_service,
    get_artifact_content_by_run as get_artifact_content_service,
)
from eval_engine.services.job_service import get_job_status as get_job_status_service
from eval_engine.services.run_service import RunBatchRequest, run_batch_service
from eval_engine.services.regression_service import RegressionRequest, run_regression_service
from eval_engine.services.demo_service import run_demo_failure as run_demo_failure_service
from eval_engine.services.diagnosis_service import list_failure_clusters as list_failure_clusters_service
from eval_engine.services.run_view_service import (
    get_run_events as get_run_events_service,
    get_eval_results as get_eval_results_service,
)

from eval_engine.mcp.resources import register_resources


# Server instructions: guidance for host LLMs (no vibe-based grading).
EVAL_ENGINE_INSTRUCTIONS = """
Prefer deterministic tools over generative tools. Use run_batch before requesting summaries; after a run completes, fetch eval://runs/{run_id}/summary for the run summary. Use replay_item only when evidence inspection suggests a reproducible failure. Never infer pass/fail without oracle-backed evidence; all verdicts must come from the eval pipeline (run_batch, get_run_summary, get_item_result, or replay), not from free-form judgment.
""".strip()

mcp = FastMCP(
    "eval-engine",
    json_response=True,
    instructions=EVAL_ENGINE_INSTRUCTIONS,
)


@mcp.tool()
def ping() -> dict[str, Any]:
    """Health check. Returns ok, server name, and repo_root from EVAL_ENGINE_ROOT."""
    return {
        "ok": True,
        "server": "eval-engine",
        "repo_root": str(get_repo_root()),
    }


@mcp.tool()
def list_runs(limit: int = 20) -> dict[str, Any]:
    """List recent runs (by mtime). Returns list of run summaries."""
    return {"content": list_runs_service(limit=limit)}


@mcp.tool()
def get_run_summary(run_id: str) -> dict[str, Any]:
    """Get run summary by run_id. Returns summary dict (from run_summary.json or run_record.json)."""
    summary = get_run_summary_service(run_id)
    if not summary:
        return {"error": {"kind": "not_found", "code": "RUN_NOT_FOUND", "message": f"Run not found: {run_id}", "details": {"run_id": run_id}}}
    return {"content": summary}


@mcp.tool()
def list_run_files(run_id: str) -> dict[str, Any]:
    """List root files and artifact files for a run. Returns content or error."""
    return list_run_files_service(run_id)


@mcp.tool()
def get_item_result(run_id: str, item_id: str) -> dict[str, Any]:
    """Get one item's eval result from a run. Returns result dict or error."""
    result = get_item_result_service(run_id, item_id)
    if not result:
        return {"error": {"kind": "not_found", "code": "ITEM_NOT_FOUND", "message": f"Item {item_id} not found in run {run_id}", "details": {"run_id": run_id, "item_id": item_id}}}
    return {"content": result}


@mcp.tool()
def get_artifact_content(run_id: str, filename: str) -> dict[str, Any]:
    """Fetch one artifact or run-root file (e.g. eval_results.jsonl, item_raw.txt). Returns content or error."""
    return get_artifact_content_service(run_id, filename)


@mcp.tool()
def get_job_status(job_id: str) -> dict[str, Any]:
    """Get job status (running / completed / failed / cancelled). Returns job dict or error."""
    job = get_job_status_service(get_repo_root(), job_id)
    if not job:
        return {"error": {"kind": "not_found", "code": "JOB_NOT_FOUND", "message": f"Job not found: {job_id}", "details": {"job_id": job_id}}}
    return {"content": job}


@mcp.tool()
def run_batch(
    spec_json: str,
    quota: int = 1,
    sut: str = "http",
    sut_url: str = "http://127.0.0.1:8000/run",
    sut_timeout: int = 30,
    model_version: str = "http-sut-local",
) -> dict[str, Any]:
    """Run a batch from a dataset spec. spec_json: JSON string of the dataset spec object. Returns run_id, run_dir, paths, metrics, job_id."""
    spec = json.loads(spec_json) if isinstance(spec_json, str) else spec_json
    request = RunBatchRequest(
        project_root=get_repo_root(),
        spec=spec,
        quota=quota,
        sut_name=sut,
        model_version=model_version,
        sut_url=sut_url or "",
        sut_timeout=sut_timeout,
    )
    response = run_batch_service(request)
    return response.to_dict()


@mcp.tool()
def run_regression(
    suite_path: str,
    sut_url: str,
    sut_timeout: int = 30,
    min_pass_rate: float = 0.95,
    artifacts_dir: str | None = None,
) -> dict[str, Any]:
    """Run golden regression suite against HTTP SUT. Returns passed_gate, pass_rate, results, failures."""
    request = RegressionRequest(
        suite_path=Path(suite_path),
        sut_url=sut_url,
        sut_timeout=sut_timeout,
        artifacts_dir=Path(artifacts_dir) if artifacts_dir else None,
        min_pass_rate=min_pass_rate,
    )
    response = run_regression_service(request)
    return response.to_dict()


@mcp.tool()
def run_demo_failure(case_name: str) -> dict[str, Any]:
    """Run a single guaranteed-failure demo batch. Supported cases: wrong_email, wrong_sentiment, wrong_math, traj_arg_bad, traj_binding_mismatch."""
    try:
        return run_demo_failure_service(case_name)
    except ValueError as e:
        return {"error": {"code": "UNKNOWN_DEMO_CASE", "message": str(e)}}


@mcp.tool(annotations={"readOnlyHint": True})
def list_failure_clusters(run_id: str) -> dict[str, Any]:
    """Summarize failures by error_type with count, sample_item_ids, owner, and recommended_action."""
    return list_failure_clusters_service(run_id)


@mcp.tool(annotations={"readOnlyHint": True})
def get_run_events(run_id: str, limit: int = 200) -> dict[str, Any]:
    """Return parsed events for a run (frontend-friendly; limit caps number of events)."""
    return get_run_events_service(run_id, limit=limit)


@mcp.tool(annotations={"readOnlyHint": True})
def get_eval_results(run_id: str, limit: int = 200) -> dict[str, Any]:
    """Return parsed eval results for a run (frontend-friendly; limit caps number of results)."""
    return get_eval_results_service(run_id, limit=limit)


register_resources(mcp)


def run(transport: str = "stdio") -> None:
    """Run the MCP server. transport: stdio | streamable-http | sse."""
    mcp.run(transport=transport)


if __name__ == "__main__":
    run(transport=os.environ.get("MCP_TRANSPORT", "stdio"))
