"""Public status/health payload builders for Qwen service."""

from __future__ import annotations

from typing import Any


def session_capability_flags(config: dict[str, Any]) -> dict[str, Any]:
    """Return non-secret browser/file session capability flags."""
    return {
        "has_token": bool(config.get("token")),
        "has_qwen_cookie": bool(config.get("cookie")),
        "has_qwen_bx_ua": bool(config.get("bx_ua")),
        "has_qwen_bx_umidtoken": bool(config.get("bx_umidtoken")),
        "has_qwen_bx_v": bool(config.get("bx_v")),
        "has_qwen_user_agent": bool(config.get("user_agent")),
        "qwen_user_agent_len": len(str(config.get("user_agent") or "")),
        "has_file_api_extra_headers": bool(config.get("file_api_extra_headers_json")),
        "has_file_sts_payload_template": bool(config.get("file_sts_payload_template_json")),
        "has_file_sts_url": bool(config.get("file_sts_url")),
        "has_file_parse_payload_template": bool(config.get("file_parse_payload_template_json")),
        "has_file_parse_url": bool(config.get("file_parse_url")),
        "has_file_parse_status_payload_template": bool(config.get("file_parse_status_payload_template_json")),
        "has_file_parse_status_url": bool(config.get("file_parse_status_url")),
        "has_oss_put_headers_template": bool(config.get("oss_put_headers_template_json")),
        "has_file_browser_session": bool(
            config.get("cookie") and config.get("bx_ua") and config.get("bx_umidtoken") and config.get("bx_v")
        ),
        "has_api_key": bool(config.get("api_key")),
        "auth_required": bool(config.get("api_key")) or not bool(config.get("allow_unauth_without_api_key")),
        "allow_unauth_without_api_key": bool(config.get("allow_unauth_without_api_key")),
    }


def provider_status_payload(
    *,
    active_sessions: int,
    max_active_sessions: int,
    provider_max_concurrent_requests: int,
    provider_start_throttle_enabled: bool,
    provider_start_interval_sec: float,
    provider_start_jitter_sec: float,
    provider_retry_jitter_enabled: bool,
    provider_retry_jitter_bounds: tuple[float, float],
    provider_active_requests: int = 0,
    provider_active_operations: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "active_sessions": active_sessions,
        "max_active_sessions": max_active_sessions,
        "provider_max_concurrent_requests": provider_max_concurrent_requests,
        "provider_active_requests": int(provider_active_requests or 0),
        "provider_active_operations": dict(provider_active_operations or {}),
        "provider_busy": int(provider_active_requests or 0) > 0,
        "provider_start_throttle_enabled": provider_start_throttle_enabled,
        "provider_start_interval_sec": provider_start_interval_sec,
        "provider_start_jitter_sec": provider_start_jitter_sec,
        "provider_retry_jitter_enabled": provider_retry_jitter_enabled,
        "provider_retry_jitter_min_sec": provider_retry_jitter_bounds[0],
        "provider_retry_jitter_max_sec": provider_retry_jitter_bounds[1],
    }


def health_payload(
    *,
    config: dict[str, Any],
    defaults: dict[str, Any],
    available: bool,
    active_sessions: int,
    max_active_sessions: int,
    provider_max_concurrent_requests: int,
    provider_start_throttle_enabled: bool,
    provider_start_interval_sec: float,
    provider_start_jitter_sec: float,
    provider_retry_jitter_enabled: bool,
    provider_retry_jitter_bounds: tuple[float, float],
    provider_active_requests: int = 0,
    provider_active_operations: dict[str, int] | None = None,
    auth_checked_at: float | None = None,
    auth_valid_known: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "ok" if available else "error",
        "service_alive": True,
        "model": config.get("model", defaults["model"]),
        "available": available,
        "token_configured": bool(config.get("token")),
        "auth_checked_at": auth_checked_at,
        "auth_valid_known": auth_valid_known,
        "oss_put_mode": config.get("oss_put_mode", defaults["oss_put_mode"]),
        "file_upload_mode": config.get("file_upload_mode", defaults["file_upload_mode"]),
        "file_upload_max_size_mb": int(config.get("file_upload_max_size_mb") or defaults["file_upload_max_size_mb"]),
        "file_upload_max_files": int(config.get("file_upload_max_files") or defaults["file_upload_max_files"]),
        "session_source": config.get("session_source", defaults["session_source"]),
        "playwright_enabled": bool(config.get("playwright_enabled", defaults["playwright_enabled"])),
        "browser_login_automation": bool(
            config.get("browser_login_automation", defaults["browser_login_automation"])
        ),
        "cdp_url": config.get("cdp_url", defaults["cdp_url"]),
    }
    payload.update(session_capability_flags(config))
    payload.update(
        provider_status_payload(
            active_sessions=active_sessions,
            max_active_sessions=max_active_sessions,
            provider_max_concurrent_requests=provider_max_concurrent_requests,
            provider_start_throttle_enabled=provider_start_throttle_enabled,
            provider_start_interval_sec=provider_start_interval_sec,
            provider_start_jitter_sec=provider_start_jitter_sec,
            provider_retry_jitter_enabled=provider_retry_jitter_enabled,
            provider_retry_jitter_bounds=provider_retry_jitter_bounds,
            provider_active_requests=provider_active_requests,
            provider_active_operations=provider_active_operations,
        )
    )
    return payload
