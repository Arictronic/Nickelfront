"""System endpoint and startup helpers for qwen_service.service.

This module keeps small, non-transport runtime concerns outside the FastAPI
route file: health payload assembly, user-info payload, and startup logging.
It does not know about HAR/token refresh, upload protocol or Qwen transport
internals.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException

try:
    from .defaults import (
        DEFAULT_AUTO_CONTINUE_ENABLED,
        DEFAULT_HOST,
        DEFAULT_MAX_ACTIVE_SESSIONS,
        DEFAULT_MAX_CONTINUES,
        DEFAULT_MODEL,
        DEFAULT_PORT,
        DEFAULT_PROVIDER_MAX_CONCURRENT_REQUESTS,
        DEFAULT_PROVIDER_RETRY_JITTER_ENABLED,
        DEFAULT_PROVIDER_RETRY_JITTER_MAX_SEC,
        DEFAULT_PROVIDER_RETRY_JITTER_MIN_SEC,
        DEFAULT_PROVIDER_START_INTERVAL_SEC,
        DEFAULT_PROVIDER_START_JITTER_SEC,
        DEFAULT_PROVIDER_START_THROTTLE_ENABLED,
        DEFAULT_SEARCH_ENABLED,
        DEFAULT_THINKING_ENABLED,
        runtime_config_defaults,
    )
    from .provider_runtime import (
        current_max_active_sessions,
        current_provider_concurrency,
        current_provider_retry_jitter_bounds,
        current_provider_retry_jitter_enabled,
        current_provider_start_interval_sec,
        current_provider_start_jitter_sec,
        current_provider_start_throttle_enabled,
    )
    from .runtime_state import QwenRuntimeState
    from .status_payload import health_payload
except ImportError:
    from defaults import (
        DEFAULT_AUTO_CONTINUE_ENABLED,
        DEFAULT_HOST,
        DEFAULT_MAX_ACTIVE_SESSIONS,
        DEFAULT_MAX_CONTINUES,
        DEFAULT_MODEL,
        DEFAULT_PORT,
        DEFAULT_PROVIDER_MAX_CONCURRENT_REQUESTS,
        DEFAULT_PROVIDER_RETRY_JITTER_ENABLED,
        DEFAULT_PROVIDER_RETRY_JITTER_MAX_SEC,
        DEFAULT_PROVIDER_RETRY_JITTER_MIN_SEC,
        DEFAULT_PROVIDER_START_INTERVAL_SEC,
        DEFAULT_PROVIDER_START_JITTER_SEC,
        DEFAULT_PROVIDER_START_THROTTLE_ENABLED,
        DEFAULT_SEARCH_ENABLED,
        DEFAULT_THINKING_ENABLED,
        runtime_config_defaults,
    )
    from provider_runtime import (
        current_max_active_sessions,
        current_provider_concurrency,
        current_provider_retry_jitter_bounds,
        current_provider_retry_jitter_enabled,
        current_provider_start_interval_sec,
        current_provider_start_jitter_sec,
        current_provider_start_throttle_enabled,
    )
    from runtime_state import QwenRuntimeState
    from status_payload import health_payload

LoggerLike = Any


def health_check_payload_from_state(
    state: QwenRuntimeState,
    *,
    ensure_control_client: Callable[[], Any | None],
) -> dict[str, Any]:
    """Build the public /health payload from runtime state."""
    control_client = ensure_control_client()
    available = bool(control_client and state.config.get("token"))
    config = state.config
    auth_cache = state.auth_status_cache or {}
    auth_payload = auth_cache.get("value") if isinstance(auth_cache.get("value"), dict) else None
    auth_valid_known = bool(auth_payload.get("valid")) if auth_payload is not None else None
    auth_checked_at = auth_cache.get("checked_at") or None
    activity = state.provider_activity_snapshot() if hasattr(state, "provider_activity_snapshot") else {}
    return health_payload(
        config=config,
        defaults=runtime_config_defaults(),
        available=available,
        active_sessions=state.active_session_count(),
        max_active_sessions=current_max_active_sessions(config, DEFAULT_MAX_ACTIVE_SESSIONS),
        provider_max_concurrent_requests=current_provider_concurrency(config, DEFAULT_PROVIDER_MAX_CONCURRENT_REQUESTS),
        provider_start_throttle_enabled=current_provider_start_throttle_enabled(
            config, DEFAULT_PROVIDER_START_THROTTLE_ENABLED
        ),
        provider_start_interval_sec=current_provider_start_interval_sec(config, DEFAULT_PROVIDER_START_INTERVAL_SEC),
        provider_start_jitter_sec=current_provider_start_jitter_sec(config, DEFAULT_PROVIDER_START_JITTER_SEC),
        provider_retry_jitter_enabled=current_provider_retry_jitter_enabled(config, DEFAULT_PROVIDER_RETRY_JITTER_ENABLED),
        provider_retry_jitter_bounds=current_provider_retry_jitter_bounds(
            config,
            default_min_sec=DEFAULT_PROVIDER_RETRY_JITTER_MIN_SEC,
            default_max_sec=DEFAULT_PROVIDER_RETRY_JITTER_MAX_SEC,
        ),
        provider_active_requests=int(activity.get("provider_active_requests") or 0),
        provider_active_operations=dict(activity.get("provider_active_operations") or {}),
        auth_checked_at=auth_checked_at,
        auth_valid_known=auth_valid_known,
    )


async def user_info_payload(
    *,
    qwen_api: Any,
    run_qwen_locked: Callable[..., Awaitable[Any]],
) -> dict[str, Any]:
    """Fetch current Qwen user info through the locked control client."""
    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")
    try:
        user_info = await run_qwen_locked(qwen_api.get_user_info)
        return {"user_info": user_info}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def startup_host_port(config: dict[str, Any]) -> tuple[str, int]:
    """Return configured host/port with service defaults."""
    return str(config.get("host", DEFAULT_HOST) or DEFAULT_HOST), int(config.get("port", DEFAULT_PORT) or DEFAULT_PORT)


def log_startup_config(config: dict[str, Any], *, logger: LoggerLike) -> None:
    """Log non-secret startup configuration for local diagnostics."""
    host, port = startup_host_port(config)
    logger.info("Starting Qwen Service on %s:%s", host, port)
    logger.info("Default model: %s", config.get("model", DEFAULT_MODEL))
    logger.info("Thinking enabled: %s", config.get("thinking_enabled", DEFAULT_THINKING_ENABLED))
    logger.info("Web search enabled: %s", config.get("search_enabled", DEFAULT_SEARCH_ENABLED))
    logger.info(
        "Auto-continue: %s (max %s)",
        config.get("auto_continue_enabled", DEFAULT_AUTO_CONTINUE_ENABLED),
        config.get("max_continues", DEFAULT_MAX_CONTINUES),
    )
    if not config.get("token"):
        logger.warning("WARNING: Qwen token is not set!")
        logger.warning("Run POST /config/token to set the token")
    if not config.get("api_key"):
        if config.get("allow_unauth_without_api_key"):
            logger.warning("WARNING: QWEN_API_KEY is empty; unauthenticated mode is explicitly enabled")
        else:
            logger.warning("WARNING: QWEN_API_KEY is empty; protected endpoints will return 401")
