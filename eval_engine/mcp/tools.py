"""
MCP tool handlers: validate args, check context (auth/session), call services,
return standardized content or typed error for productized contract behavior.
"""
from pathlib import Path
from typing import Any, Dict, Optional

from .errors import (
    ARTIFACT_NOT_FOUND,
    JOB_NOT_FOUND,
    ITEM_NOT_FOUND,
    RUN_NOT_FOUND,
    MCPServerError,
    auth_failure,
    not_found,
    schema_error,
    tool_failure,
    transport_failure,
)
from ..services import (
    get_artifact_content as svc_get_artifact_content,
    get_job_status as svc_get_job_status,
    get_run_summary as svc_get_run_summary,
    get_item_result as svc_get_item_result,
)


# Result: either content dict (for MCP response) or error
MCPResult = Dict[str, Any]  # {"content": ...} or {"error": {...}}


class MCPContext:
    """
    Context for MCP tool calls: project_root plus optional auth/session.
    For contract tests, set expected_auth / expected_session_id to trigger
    auth_failure or transport_failure when they don't match.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        auth_token: Optional[str] = None,
        session_id: Optional[str] = None,
        expected_auth: Optional[str] = None,
        expected_session_id: Optional[str] = None,
    ):
        self.project_root = Path(project_root)
        self.auth_token = auth_token
        self.session_id = session_id
        self.expected_auth = expected_auth
        self.expected_session_id = expected_session_id

    def check_remote_auth(self) -> Optional[Dict[str, Any]]:
        """If expected_auth is set and token doesn't match, return auth_failure response."""
        if self.expected_auth is None:
            return None
        if self.auth_token != self.expected_auth:
            return {"error": auth_failure(message="Unauthorized remote call").to_dict()}
        return None

    def check_session(self) -> Optional[Dict[str, Any]]:
        """If expected_session_id is set and session_id doesn't match, return transport_failure response."""
        if self.expected_session_id is None or self.session_id is None:
            return None
        if self.session_id != self.expected_session_id:
            return {"error": transport_failure(message="Session mismatch").to_dict()}
        return None


def _require_string(value: Any, field_name: str) -> Optional[MCPServerError]:
    if value is None:
        return tool_failure(message=f"Missing required field: {field_name}", details={"field": field_name})
    if not isinstance(value, str):
        return schema_error(
            message=f"Invalid type for {field_name}: expected string",
            details={"field": field_name, "expected": "string"},
        )
    return None


def _require_int(value: Any, field_name: str) -> Optional[MCPServerError]:
    if value is None:
        return tool_failure(message=f"Missing required field: {field_name}", details={"field": field_name})
    if not isinstance(value, int):
        return schema_error(
            message=f"Invalid type for {field_name}: expected integer",
            details={"field": field_name, "expected": "integer"},
        )
    return None


def mcp_get_run_summary(ctx: MCPContext, run_id: Any = None, **kwargs: Any) -> MCPResult:
    """Get run summary. Invalid args → schema_error; missing run_id → tool_failure; unknown run → not_found."""
    err = ctx.check_session()
    if err:
        return err
    if run_id is None:
        return {"error": tool_failure(message="Missing required field: run_id", details={"field": "run_id"}).to_dict()}
    e = _require_string(run_id, "run_id")
    if e:
        return {"error": e.to_dict()}
    run_id = str(run_id).strip()
    if not run_id:
        return {"error": tool_failure(message="run_id must be non-empty", details={"field": "run_id"}).to_dict()}
    summary = svc_get_run_summary(ctx.project_root, run_id, from_index_only=True)
    if not summary:
        summary = svc_get_run_summary(ctx.project_root, run_id, from_index_only=False)
    if not summary:
        return {"error": not_found(RUN_NOT_FOUND, f"Run not found: {run_id}", details={"run_id": run_id}).to_dict()}
    return {"content": summary}


def mcp_get_item_result(
    ctx: MCPContext,
    run_id: Any = None,
    item_id: Any = None,
    **kwargs: Any,
) -> MCPResult:
    """Get one item result. Invalid/missing args → schema_error or tool_failure; unknown run/item → not_found."""
    err = ctx.check_session()
    if err:
        return err
    for name, val in [("run_id", run_id), ("item_id", item_id)]:
        e = _require_string(val, name)
        if e:
            return {"error": e.to_dict()}
    run_id = str(run_id).strip()
    item_id = str(item_id).strip()
    if not run_id:
        return {"error": tool_failure(message="run_id must be non-empty", details={"field": "run_id"}).to_dict()}
    if not item_id:
        return {"error": tool_failure(message="item_id must be non-empty", details={"field": "item_id"}).to_dict()}
    run_dir = ctx.project_root / "runs" / run_id
    if not run_dir.exists():
        return {"error": not_found(RUN_NOT_FOUND, f"Run not found: {run_id}", details={"run_id": run_id}).to_dict()}
    result = svc_get_item_result(ctx.project_root, run_id, item_id)
    if not result:
        return {"error": not_found(ITEM_NOT_FOUND, f"Item not found: {item_id} in run {run_id}", details={"run_id": run_id, "item_id": item_id}).to_dict()}
    return {"content": result}


def mcp_get_artifact_content(
    ctx: MCPContext,
    run_id: Any = None,
    filename: Any = None,
    **kwargs: Any,
) -> MCPResult:
    """Fetch one artifact by filename. Missing/invalid args → tool_failure or schema_error; missing artifact → not_found."""
    err = ctx.check_session()
    if err:
        return err
    for name, val in [("run_id", run_id), ("filename", filename)]:
        e = _require_string(val, name)
        if e:
            return {"error": e.to_dict()}
    run_id = str(run_id).strip()
    filename = str(filename).strip()
    if not run_id or not filename:
        return {"error": tool_failure(message="run_id and filename must be non-empty", details={}).to_dict()}
    content = svc_get_artifact_content(ctx.project_root, run_id, filename)
    if content is None:
        return {"error": not_found(ARTIFACT_NOT_FOUND, f"Artifact not found: {filename} in run {run_id}", details={"run_id": run_id, "filename": filename}).to_dict()}
    return {"content": {"text": content, "filename": filename}}


def mcp_get_job_status(ctx: MCPContext, job_id: Any = None, **kwargs: Any) -> MCPResult:
    """Get job status. Invalid args → schema_error; missing job_id → tool_failure; unknown job → not_found."""
    err = ctx.check_session()
    if err:
        return err
    if job_id is None:
        return {"error": tool_failure(message="Missing required field: job_id", details={"field": "job_id"}).to_dict()}
    e = _require_string(job_id, "job_id")
    if e:
        return {"error": e.to_dict()}
    job_id = str(job_id).strip()
    if not job_id:
        return {"error": tool_failure(message="job_id must be non-empty", details={"field": "job_id"}).to_dict()}
    job = svc_get_job_status(ctx.project_root, job_id)
    if not job:
        return {"error": not_found(JOB_NOT_FOUND, f"Job not found: {job_id}", details={"job_id": job_id}).to_dict()}
    return {"content": job}


def mcp_remote_fetch(
    ctx: MCPContext,
    url: Any = None,
    **kwargs: Any,
) -> MCPResult:
    """
    Simulated remote fetch: requires auth. Used for contract test "unauthorized remote call → auth_failure".
    If context.expected_auth is set, validates auth_token; otherwise always returns success (no-op).
    """
    auth_err = ctx.check_remote_auth()
    if auth_err:
        return auth_err
    err = ctx.check_session()
    if err:
        return err
    # Optional url for schema validation
    if url is not None and not isinstance(url, str):
        return {"error": schema_error(message="Invalid type for url: expected string", details={"field": "url"}).to_dict()}
    return {"content": {"status": "ok", "message": "Remote fetch authorized"}}
