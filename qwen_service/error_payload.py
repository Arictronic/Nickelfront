"""HTTP error normalization for standalone qwen_service.

Provider exceptions often arrive as plain strings from the unofficial Qwen web
API. Keep the mapping in one small module so routes do not leak every provider
failure as HTTP 500 and backend/frontend can handle stable error codes.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


_AUTH_MARKERS = (
    "qwen_token_expired",
    "token has expired",
    "please log in again",
    "token expired",
    "login again",
    "not logged in",
    "unauthorized",
    "authentication failed",
    "auth failed",
)

_RATE_LIMIT_MARKERS = (
    "qwen_rate_limited",
    "too many requests",
    "rate limit",
    "429",
    "частот",
)

_TIMEOUT_MARKERS = (
    "queue timeout",
    "read timed out",
    "readtimeout",
    "timeout",
    "timed out",
)

_BAD_REQUEST_MARKERS = (
    "qwen_no_files",
    "qwen_too_many_files",
    "qwen_file_too_large",
    "file does not exist",
    "missing full file_info",
    "cannot continue qwen response without session_id",
    "at least one file path is required",
)

_CONFLICT_MARKERS = (
    "chat is in progress",
    "request ended",
    "already ended",
    "still in progress",
)

_UNAVAILABLE_MARKERS = (
    "qwen api не инициализирован",
    "qwen api is not initialized",
    "connection refused",
    "connection aborted",
    "connection error",
    "remote disconnected",
    "service unavailable",
)


def _message_of(exc: BaseException | str | None) -> str:
    if exc is None:
        return ""
    return str(exc).strip()


def classify_provider_error(exc: BaseException | str | None) -> tuple[int, str, str]:
    """Return ``(status_code, error_code, message)`` for provider/runtime errors."""
    message = _message_of(exc) or "Qwen provider request failed"
    lowered = message.lower()
    exc_name = exc.__class__.__name__.lower() if isinstance(exc, BaseException) else ""

    if any(marker in lowered for marker in _AUTH_MARKERS):
        if "expired" in lowered or "login again" in lowered or "not logged in" in lowered:
            return 401, "qwen_token_expired", message
        return 401, "qwen_auth_failed", message

    if any(marker in lowered for marker in _RATE_LIMIT_MARKERS):
        return 429, "qwen_rate_limited", message

    if any(marker in lowered for marker in _BAD_REQUEST_MARKERS):
        if "qwen_file_too_large" in lowered or "file size" in lowered:
            return 413, "qwen_file_too_large", message
        if "missing full file_info" in lowered:
            return 400, "qwen_file_metadata_missing", message
        if "cannot continue" in lowered:
            return 400, "qwen_invalid_continue_request", message
        return 400, "qwen_bad_request", message

    if any(marker in lowered for marker in _CONFLICT_MARKERS) or "chatinprogress" in exc_name or "requestended" in exc_name:
        return 409, "qwen_chat_state_conflict", message

    if any(marker in lowered for marker in _TIMEOUT_MARKERS) or "timeout" in exc_name:
        if "queue timeout" in lowered:
            return 503, "qwen_provider_slot_timeout", message
        return 504, "qwen_provider_timeout", message

    if any(marker in lowered for marker in _UNAVAILABLE_MARKERS) or "connection" in exc_name:
        return 503, "qwen_service_unavailable", message

    if "internalstream" in exc_name or "internal stream" in lowered:
        return 502, "qwen_provider_stream_error", message

    return 502, "qwen_provider_error", message


def provider_error_detail(
    exc: BaseException | str | None,
    *,
    operation: str | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    status_code, code, message = classify_provider_error(exc)
    detail: dict[str, Any] = {
        "error": code,
        "error_code": code,
        "message": message,
        "status_code": status_code,
    }
    if operation:
        detail["operation"] = operation
    if extra:
        detail.update(extra)
    return status_code, detail


def raise_provider_http_error(
    exc: BaseException | str | None,
    *,
    operation: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Raise FastAPI HTTPException with a stable detail envelope."""
    status_code, detail = provider_error_detail(exc, operation=operation, extra=extra)
    if isinstance(exc, BaseException):
        raise HTTPException(status_code=status_code, detail=detail) from exc
    raise HTTPException(status_code=status_code, detail=detail)
