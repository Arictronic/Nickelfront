"""Stable Qwen result/error normalization helpers.

This module does not perform HTTP requests. It only maps qwen_service responses
and errors to compact backend-facing payloads used by clients, tasks and UI.
"""

from __future__ import annotations

from typing import Any

KNOWN_QWEN_PROVIDER_ERRORS = (
    "qwen_too_many_files",
    "qwen_file_too_large",
    "qwen_file_auth_failed",
    "qwen_file_sts_failed",
    "qwen_oss_put_failed",
    "qwen_oss_auth_failed",
    "qwen_oss_connect_timeout",
    "qwen_file_parse_failed",
    "qwen_file_parse_timeout",
    "qwen_file_parse_status_failed",
    "qwen_file_not_visible",
    "qwen_token_expired",
    "qwen_auth_failed",
    "qwen_rate_limited",
    "qwen_provider_slot_timeout",
    "qwen_provider_timeout",
    "qwen_file_metadata_missing",
    "qwen_upload_bad_request",
    "qwen_chat_state_conflict",
    "qwen_provider_stream_error",
    "qwen_provider_error",
)

TRANSIENT_QWEN_ERRORS = {
    "timeout",
    "rate_limited",
    "qwen_rate_limited",
    "qwen_file_parse_timeout",
    "qwen_oss_connect_timeout",
    "qwen_service_unavailable",
    "qwen_service_timeout",
    "qwen_provider_timeout",
    "qwen_provider_slot_timeout",
    "qwen_provider_stream_error",
}

AUTH_QWEN_ERRORS = {
    "auth_expired",
    "qwen_token_expired",
    "qwen_file_auth_failed",
    "qwen_oss_auth_failed",
    "qwen_auth_failed",
}


def classify_qwen_service_error(detail_text: str, *, status_code: int | None = None) -> str:
    """Map qwen_service HTTP details to stable backend-facing error codes."""
    lowered = (detail_text or "").lower()
    for code in KNOWN_QWEN_PROVIDER_ERRORS:
        if code in lowered:
            return code
    if status_code == 413:
        return "qwen_file_too_large"
    if status_code == 429:
        return "qwen_rate_limited"
    if status_code in {502, 503, 504} and "timeout" in lowered:
        return "qwen_provider_timeout"
    if status_code == 401 or "unauthorized" in lowered or "auth" in lowered:
        return "qwen_file_auth_failed"
    return "qwen_service_http_error"


def format_error_result(
    result: dict[str, Any] | None,
    *,
    fallback_error: str,
    fallback_message: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(result or {})
    if not payload.get("error"):
        payload["error"] = fallback_error
    if not payload.get("message"):
        payload["message"] = payload.get("detail") or fallback_message
    payload.setdefault("response", "")
    payload.setdefault("thinking", "")
    payload.setdefault("can_continue", False)
    if extra:
        for key, value in extra.items():
            payload.setdefault(key, value)
    return payload


def qwen_result_text(result: Any) -> str:
    if not isinstance(result, dict):
        return str(result or "").strip()
    for key in ("response", "text", "content", "message"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def qwen_error_text(result: Any, *, fallback: str = "") -> str:
    if isinstance(result, dict):
        for key in ("message", "detail", "error", "status"):
            value = result.get(key)
            if value:
                return str(value).strip()
    return str(fallback or "").strip()


def qwen_error_code(result: Any, *, error_type: str | None = None) -> str | None:
    if isinstance(result, dict):
        for key in ("error", "code", "status"):
            value = result.get(key)
            if value:
                return str(value).strip()
    return str(error_type or "").strip() or None


def is_qwen_auth_error(result: Any, *, error_type: str | None = None) -> bool:
    code = qwen_error_code(result, error_type=error_type)
    if code and code in AUTH_QWEN_ERRORS:
        return True
    text = qwen_error_text(result).lower()
    return "token" in text and ("expired" in text or "auth" in text or "login" in text)


def is_transient_qwen_error(result: Any, *, error_type: str | None = None) -> bool:
    code = qwen_error_code(result, error_type=error_type)
    if code and code in TRANSIENT_QWEN_ERRORS:
        return True
    text = qwen_error_text(result).lower()
    return any(marker in text for marker in ("timeout", "rate limit", "too many requests", "temporarily", "unavailable"))
