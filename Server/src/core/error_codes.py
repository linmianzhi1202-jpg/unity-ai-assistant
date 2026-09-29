"""
Unified Error Code System for the Unified MCP for Unity system.
Provides standardized error codes, automatic retry hints, and error response formatting.
"""

from enum import IntEnum
from typing import Any

from pydantic import BaseModel


class UnifiedErrorCode(IntEnum):
    """Standardized error codes across the unified system."""

    # ═══ Connection Errors (1xxx) ═══
    CONNECTION_LOST = 1001
    CONNECTION_TIMEOUT = 1002
    NO_UNITY_INSTANCE = 1003
    MULTIPLE_INSTANCES = 1004
    DOMAIN_RELOADING = 1005

    # ═══ Authentication Errors (2xxx) ═══
    AUTH_REQUIRED = 2001
    AUTH_INVALID_KEY = 2002
    ACL_DENIED = 2003
    RATE_LIMITED = 2004

    # ═══ Tool Errors (3xxx) ═══
    TOOL_NOT_FOUND = 3001
    TOOL_DISABLED = 3002
    TOOL_EXECUTION_ERROR = 3003
    STALE_FILE = 3004
    BUSY_COMPILING = 3005
    TOOL_GROUP_DISABLED = 3006

    # ═══ Parameter Errors (4xxx) ═══
    PARAM_MISSING = 4001
    PARAM_INVALID = 4002
    PARAM_TYPE_ERROR = 4003

    # ═══ AI Generation Errors (5xxx) ═══
    AI_PROVIDER_ERROR = 5001
    AI_QUOTA_EXCEEDED = 5002
    AI_GENERATION_TIMEOUT = 5003
    AI_INVALID_RESPONSE = 5004
    AI_MODEL_NOT_AVAILABLE = 5005

    # ═══ Unity Internal Errors (6xxx) ═══
    UNITY_COMPILE_ERROR = 6001
    UNITY_RUNTIME_ERROR = 6002
    UNITY_ASSET_NOT_FOUND = 6003


# Human-readable error messages
_ERROR_MESSAGES: dict[UnifiedErrorCode, str] = {
    UnifiedErrorCode.CONNECTION_LOST: "Connection to Unity was lost",
    UnifiedErrorCode.CONNECTION_TIMEOUT: "Connection to Unity timed out",
    UnifiedErrorCode.NO_UNITY_INSTANCE: "No Unity Editor instance is available",
    UnifiedErrorCode.MULTIPLE_INSTANCES: "Multiple Unity instances found; specify one with set_unity_project_root",
    UnifiedErrorCode.DOMAIN_RELOADING: "Unity is currently reloading domains",
    UnifiedErrorCode.AUTH_REQUIRED: "API key is required for this operation",
    UnifiedErrorCode.AUTH_INVALID_KEY: "The provided API key is invalid",
    UnifiedErrorCode.ACL_DENIED: "Access denied by ACL policy",
    UnifiedErrorCode.RATE_LIMITED: "Rate limit exceeded for this tool",
    UnifiedErrorCode.TOOL_NOT_FOUND: "The requested tool was not found",
    UnifiedErrorCode.TOOL_DISABLED: "This tool is currently disabled",
    UnifiedErrorCode.TOOL_EXECUTION_ERROR: "An error occurred during tool execution",
    UnifiedErrorCode.STALE_FILE: "File has changed since last SHA calculation",
    UnifiedErrorCode.BUSY_COMPILING: "Unity is busy compiling scripts",
    UnifiedErrorCode.TOOL_GROUP_DISABLED: "This tool group is disabled in configuration",
    UnifiedErrorCode.PARAM_MISSING: "A required parameter is missing",
    UnifiedErrorCode.PARAM_INVALID: "A parameter value is invalid",
    UnifiedErrorCode.PARAM_TYPE_ERROR: "A parameter has an incorrect type",
    UnifiedErrorCode.AI_PROVIDER_ERROR: "AI service provider returned an error",
    UnifiedErrorCode.AI_QUOTA_EXCEEDED: "AI generation quota has been exceeded",
    UnifiedErrorCode.AI_GENERATION_TIMEOUT: "AI generation timed out",
    UnifiedErrorCode.AI_INVALID_RESPONSE: "AI service returned an invalid response",
    UnifiedErrorCode.AI_MODEL_NOT_AVAILABLE: "The requested AI model is not available",
    UnifiedErrorCode.UNITY_COMPILE_ERROR: "Unity reported a compilation error",
    UnifiedErrorCode.UNITY_RUNTIME_ERROR: "Unity reported a runtime error",
    UnifiedErrorCode.UNITY_ASSET_NOT_FOUND: "The requested asset was not found",
}

# Auto-retry configuration per error code
_RETRY_CONFIG: dict[UnifiedErrorCode, dict[str, Any]] = {
    UnifiedErrorCode.DOMAIN_RELOADING: {
        "max_retries": 40,
        "interval_ms": 250,
        "strategy": "fixed",
    },
    UnifiedErrorCode.CONNECTION_LOST: {
        "max_retries": 5,
        "interval_ms": 250,
        "strategy": "exponential",
        "max_interval_ms": 8000,
    },
    UnifiedErrorCode.BUSY_COMPILING: {
        "max_retries": 20,
        "interval_ms": 500,
        "strategy": "fixed",
    },
    UnifiedErrorCode.AI_GENERATION_TIMEOUT: {
        "max_retries": 1,
        "interval_ms": 0,
        "strategy": "timeout_doubled",
    },
}


class ErrorDetail(BaseModel):
    """Structured error detail for API responses."""
    code: int
    name: str
    message: str
    hint: str = ""           # "retry" | "auth" | "check_config" | ""
    retry_after_ms: int | None = None
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """Standard error response envelope."""
    success: bool = False
    error: ErrorDetail


def make_error(
    code: UnifiedErrorCode,
    message: str | None = None,
    hint: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a standardized error response.

    Args:
        code: The unified error code.
        message: Override the default message (optional).
        hint: Action hint for the client.
        details: Additional context about the error.

    Returns:
        Dict suitable for returning as MCP tool result.
    """
    error_detail = ErrorDetail(
        code=code.value,
        name=code.name,
        message=message or _ERROR_MESSAGES.get(code, "Unknown error"),
        hint=hint,
        retry_after_ms=_get_retry_after_ms(code),
        details=details,
    )
    return ErrorResponse(error=error_detail).model_dump()


def _get_retry_after_ms(code: UnifiedErrorCode) -> int | None:
    """Get the recommended retry interval for auto-retryable errors."""
    cfg = _RETRY_CONFIG.get(code)
    if cfg:
        return cfg["interval_ms"]
    return None


def get_retry_config(code: UnifiedErrorCode) -> dict[str, Any] | None:
    """Get the full retry configuration for an error code."""
    return _RETRY_CONFIG.get(code)


def is_retryable(code: UnifiedErrorCode) -> bool:
    """Check if an error code is eligible for automatic retry."""
    return code in _RETRY_CONFIG
