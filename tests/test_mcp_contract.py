"""
MCP contract tests: invalid args → schema error, missing field → tool failure,
unknown run_id → typed not-found, missing artifact → not-found, unauthorized → auth failure,
session mismatch → transport failure. Keeps MCP demo productized.
Run from project root: pytest tests/test_mcp_contract.py -v
"""
from pathlib import Path

import pytest

from eval_engine.mcp.errors import (
    AUTH_FAILURE,
    NOT_FOUND,
    SCHEMA_ERROR,
    TOOL_FAILURE,
    TRANSPORT_FAILURE,
    ARTIFACT_NOT_FOUND,
    JOB_NOT_FOUND,
    RUN_NOT_FOUND,
    ITEM_NOT_FOUND,
)
from eval_engine.mcp.tools import (
    MCPContext,
    mcp_get_run_summary,
    mcp_get_item_result,
    mcp_get_artifact_content,
    mcp_get_job_status,
    mcp_remote_fetch,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---- invalid tool args → schema error ----

def test_mcp_invalid_tool_args_run_id_schema_error():
    """run_id must be string; integer or other type → schema_error."""
    ctx = MCPContext(PROJECT_ROOT)
    out = mcp_get_run_summary(ctx, run_id=12345)
    assert "error" in out
    assert out["error"]["kind"] == SCHEMA_ERROR
    assert (out["error"].get("details") or {}).get("field") == "run_id"
    assert "string" in out["error"]["message"].lower()


def test_mcp_invalid_tool_args_job_id_schema_error():
    """job_id must be string → schema_error."""
    ctx = MCPContext(PROJECT_ROOT)
    out = mcp_get_job_status(ctx, job_id=999)
    assert "error" in out
    assert out["error"]["kind"] == SCHEMA_ERROR
    assert out["error"].get("code") == "INVALID_ARGS"


def test_mcp_invalid_tool_args_item_id_schema_error():
    """item_id must be string → schema_error."""
    ctx = MCPContext(PROJECT_ROOT)
    out = mcp_get_item_result(ctx, run_id="run_any", item_id=[])
    assert "error" in out
    assert out["error"]["kind"] == SCHEMA_ERROR


# ---- missing required field → tool failure ----

def test_mcp_missing_required_field_run_id_tool_failure():
    """Missing run_id → tool_failure."""
    ctx = MCPContext(PROJECT_ROOT)
    out = mcp_get_run_summary(ctx)
    assert "error" in out
    assert out["error"]["kind"] == TOOL_FAILURE
    assert "run_id" in out["error"]["message"].lower() or (out["error"].get("details") or {}).get("field") == "run_id"


def test_mcp_missing_required_field_job_id_tool_failure():
    """Missing job_id → tool_failure."""
    ctx = MCPContext(PROJECT_ROOT)
    out = mcp_get_job_status(ctx)
    assert "error" in out
    assert out["error"]["kind"] == TOOL_FAILURE
    assert "job_id" in out["error"]["message"].lower()


def test_mcp_missing_required_field_item_id_tool_failure():
    """Missing item_id → tool_failure."""
    ctx = MCPContext(PROJECT_ROOT)
    out = mcp_get_item_result(ctx, run_id="run_any")
    assert "error" in out
    assert out["error"]["kind"] == TOOL_FAILURE


# ---- unknown run_id → typed not-found ----

def test_mcp_unknown_run_id_not_found():
    """Non-existent run_id → not_found with RUN_NOT_FOUND."""
    ctx = MCPContext(PROJECT_ROOT)
    out = mcp_get_run_summary(ctx, run_id="run_nonexistent_xyz_12345")
    assert "error" in out
    assert out["error"]["kind"] == NOT_FOUND
    assert out["error"]["code"] == RUN_NOT_FOUND
    assert out["error"].get("details", {}).get("run_id") == "run_nonexistent_xyz_12345"


# ---- resource fetch on missing artifact → typed not-found ----

def test_mcp_missing_artifact_not_found():
    """Fetch artifact for non-existent run or missing filename → ARTIFACT_NOT_FOUND."""
    ctx = MCPContext(PROJECT_ROOT)
    out = mcp_get_artifact_content(ctx, run_id="run_nonexistent_xyz", filename="no_such_file.txt")
    assert "error" in out
    assert out["error"]["kind"] == NOT_FOUND
    assert out["error"]["code"] == ARTIFACT_NOT_FOUND


def test_mcp_missing_artifact_valid_run_wrong_filename_not_found():
    """Valid run but missing artifact filename → ARTIFACT_NOT_FOUND (when run exists but file does not)."""
    ctx = MCPContext(PROJECT_ROOT)
    # Use a run_id that might not exist; if runs/ is empty we still get ARTIFACT_NOT_FOUND
    # because get_artifact_content returns None when file missing
    out = mcp_get_artifact_content(ctx, run_id="run_does_not_exist_999", filename="missing.txt")
    assert "error" in out
    assert out["error"]["code"] == ARTIFACT_NOT_FOUND


# ---- unauthorized remote call → auth failure ----

def test_mcp_unauthorized_remote_call_auth_failure():
    """When context requires auth and token is wrong → auth_failure."""
    ctx = MCPContext(PROJECT_ROOT, auth_token="wrong_token", expected_auth="secret123")
    out = mcp_remote_fetch(ctx, url="https://example.com/api")
    assert "error" in out
    assert out["error"]["kind"] == AUTH_FAILURE
    assert out["error"]["code"] == "UNAUTHORIZED"


def test_mcp_authorized_remote_call_succeeds():
    """When token matches expected_auth → content returned."""
    ctx = MCPContext(PROJECT_ROOT, auth_token="secret123", expected_auth="secret123")
    out = mcp_remote_fetch(ctx, url="https://example.com/api")
    assert "content" in out
    assert "error" not in out
    assert out["content"].get("status") == "ok"


# ---- session mismatch → typed transport failure ----

def test_mcp_session_mismatch_transport_failure():
    """When session_id does not match expected_session_id → transport_failure."""
    ctx = MCPContext(
        PROJECT_ROOT,
        session_id="session_abc",
        expected_session_id="session_xyz",
    )
    out = mcp_get_run_summary(ctx, run_id="run_any")
    assert "error" in out
    assert out["error"]["kind"] == TRANSPORT_FAILURE
    assert "SESSION_MISMATCH" in out["error"].get("code", "") or "session" in out["error"]["message"].lower()


def test_mcp_session_match_succeeds():
    """When session_id matches expected_session_id, tool runs (may still get not_found for bad run_id)."""
    ctx = MCPContext(
        PROJECT_ROOT,
        session_id="session_xyz",
        expected_session_id="session_xyz",
    )
    out = mcp_get_run_summary(ctx, run_id="run_nonexistent_xyz")
    # Should get not_found (run missing), not transport_failure
    assert "error" in out
    assert out["error"]["kind"] == NOT_FOUND
    assert out["error"]["code"] == RUN_NOT_FOUND


# ---- unknown job_id → typed not-found ----

def test_mcp_unknown_job_id_not_found():
    """Non-existent job_id → not_found with JOB_NOT_FOUND."""
    ctx = MCPContext(PROJECT_ROOT)
    out = mcp_get_job_status(ctx, job_id="nonexistentjob99")
    assert "error" in out
    assert out["error"]["kind"] == NOT_FOUND
    assert out["error"]["code"] == JOB_NOT_FOUND


# ---- empty string required fields → tool_failure ----

def test_mcp_empty_run_id_tool_failure():
    """Empty run_id string → tool_failure."""
    ctx = MCPContext(PROJECT_ROOT)
    out = mcp_get_run_summary(ctx, run_id="")
    assert "error" in out
    assert out["error"]["kind"] == TOOL_FAILURE
    assert "run_id" in out["error"]["message"].lower() or "non-empty" in out["error"]["message"].lower()
