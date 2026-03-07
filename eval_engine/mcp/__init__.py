"""
MCP-facing layer: typed errors and tool handlers for productized contract behavior.
"""
from .errors import (
    AUTH_FAILURE,
    NOT_FOUND,
    SCHEMA_ERROR,
    TOOL_FAILURE,
    TRANSPORT_FAILURE,
    RUN_NOT_FOUND,
    ARTIFACT_NOT_FOUND,
    ITEM_NOT_FOUND,
    JOB_NOT_FOUND,
    MCPServerError,
    auth_failure,
    not_found,
    schema_error,
    tool_failure,
    transport_failure,
)
from .tools import (
    MCPContext,
    mcp_get_run_summary,
    mcp_get_item_result,
    mcp_get_artifact_content,
    mcp_get_job_status,
    mcp_remote_fetch,
)

__all__ = [
    "SCHEMA_ERROR",
    "TOOL_FAILURE",
    "NOT_FOUND",
    "AUTH_FAILURE",
    "TRANSPORT_FAILURE",
    "RUN_NOT_FOUND",
    "ARTIFACT_NOT_FOUND",
    "ITEM_NOT_FOUND",
    "JOB_NOT_FOUND",
    "MCPServerError",
    "schema_error",
    "tool_failure",
    "not_found",
    "auth_failure",
    "transport_failure",
    "MCPContext",
    "mcp_get_run_summary",
    "mcp_get_item_result",
    "mcp_get_artifact_content",
    "mcp_get_job_status",
    "mcp_remote_fetch",
]
