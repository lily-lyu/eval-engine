"""
MCP-facing typed errors. All tool responses use these so clients get
consistent schema_error / tool_failure / not_found / auth_failure / transport_failure.
"""
from dataclasses import dataclass
from typing import Any, Dict, Optional

# Error kinds for contract tests and MCP protocol mapping
SCHEMA_ERROR = "schema_error"
TOOL_FAILURE = "tool_failure"
NOT_FOUND = "not_found"
AUTH_FAILURE = "auth_failure"
TRANSPORT_FAILURE = "transport_failure"

# Codes for not_found (and optional detail)
RUN_NOT_FOUND = "RUN_NOT_FOUND"
ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
ITEM_NOT_FOUND = "ITEM_NOT_FOUND"
JOB_NOT_FOUND = "JOB_NOT_FOUND"


@dataclass(frozen=True)
class MCPServerError:
    """Typed error for MCP tool responses."""

    kind: str  # schema_error | tool_failure | not_found | auth_failure | transport_failure
    code: str  # e.g. RUN_NOT_FOUND, ARTIFACT_NOT_FOUND
    message: str
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "kind": self.kind,
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            out["details"] = self.details
        return out


def schema_error(message: str, details: Optional[Dict[str, Any]] = None) -> MCPServerError:
    return MCPServerError(kind=SCHEMA_ERROR, code="INVALID_ARGS", message=message, details=details)


def tool_failure(message: str, details: Optional[Dict[str, Any]] = None) -> MCPServerError:
    return MCPServerError(kind=TOOL_FAILURE, code="VALIDATION_FAILED", message=message, details=details)


def not_found(code: str, message: str, details: Optional[Dict[str, Any]] = None) -> MCPServerError:
    return MCPServerError(kind=NOT_FOUND, code=code, message=message, details=details)


def auth_failure(message: str = "Unauthorized", details: Optional[Dict[str, Any]] = None) -> MCPServerError:
    return MCPServerError(kind=AUTH_FAILURE, code="UNAUTHORIZED", message=message, details=details)


def transport_failure(message: str, details: Optional[Dict[str, Any]] = None) -> MCPServerError:
    return MCPServerError(kind=TRANSPORT_FAILURE, code="SESSION_MISMATCH", message=message, details=details)
