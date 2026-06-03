"""Authentication/status helpers for the standalone Qwen service.

This module intentionally contains no FastAPI routes and no Qwen transport
implementation.  The runtime service passes concrete callbacks/state into these
helpers so qwen_service.service can stay focused on orchestration and routes.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextvars import ContextVar
from threading import RLock
from typing import Any

QWEN_TOKEN_EXPIRED_MARKERS = (
    "token has expired",
    "please log in again",
    "token expired",
    "login again",
    "not logged in",
    "unauthorized",
)


def service_token_valid(credentials_token: str | None, api_key: str | None) -> bool:
    """Return True when service API key auth should allow the request."""
    configured_key = str(api_key or "")
    if not configured_key:
        return True
    return str(credentials_token or "") == configured_key


def is_qwen_token_expired_error(message: str | None) -> bool:
    """Detect Qwen provider auth expiry messages across API variants."""
    value = str(message or "").lower()
    return any(marker in value for marker in QWEN_TOKEN_EXPIRED_MARKERS)


def auth_status_payload(
    *,
    config: dict[str, Any],
    status: str,
    valid: bool,
    default_model: str,
    active_session_count: Callable[[], int],
    max_active_sessions: Callable[[], int],
    provider_concurrency: Callable[[], int],
    provider_start_throttle_enabled: Callable[[], bool],
    provider_start_interval_sec: Callable[[], float],
    provider_start_jitter_sec: Callable[[], float],
    provider_retry_jitter_enabled: Callable[[], bool],
    provider_retry_jitter_bounds: Callable[[], tuple[float, float]],
    expired: bool = False,
    message: str = "",
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the shared auth status payload used by health/auth endpoints."""
    retry_min, retry_max = provider_retry_jitter_bounds()
    return {
        "status": status,
        "valid": valid,
        "expired": expired,
        "token_configured": bool(config.get("token")),
        "has_api_key": bool(config.get("api_key")),
        "model": config.get("model", default_model),
        "message": message,
        "user": user or None,
        "checked_by": "provider_user_api",
        "active_sessions": active_session_count(),
        "max_active_sessions": max_active_sessions(),
        "provider_max_concurrent_requests": provider_concurrency(),
        "provider_start_throttle_enabled": provider_start_throttle_enabled(),
        "provider_start_interval_sec": provider_start_interval_sec(),
        "provider_start_jitter_sec": provider_start_jitter_sec(),
        "provider_retry_jitter_enabled": provider_retry_jitter_enabled(),
        "provider_retry_jitter_min_sec": retry_min,
        "provider_retry_jitter_max_sec": retry_max,
    }


def _payload_builder(
    *,
    config: dict[str, Any],
    default_model: str,
    active_session_count: Callable[[], int],
    max_active_sessions: Callable[[], int],
    provider_concurrency: Callable[[], int],
    provider_start_throttle_enabled: Callable[[], bool],
    provider_start_interval_sec: Callable[[], float],
    provider_start_jitter_sec: Callable[[], float],
    provider_retry_jitter_enabled: Callable[[], bool],
    provider_retry_jitter_bounds: Callable[[], tuple[float, float]],
) -> Callable[..., dict[str, Any]]:
    def build(**kwargs: Any) -> dict[str, Any]:
        return auth_status_payload(
            config=config,
            default_model=default_model,
            active_session_count=active_session_count,
            max_active_sessions=max_active_sessions,
            provider_concurrency=provider_concurrency,
            provider_start_throttle_enabled=provider_start_throttle_enabled,
            provider_start_interval_sec=provider_start_interval_sec,
            provider_start_jitter_sec=provider_start_jitter_sec,
            provider_retry_jitter_enabled=provider_retry_jitter_enabled,
            provider_retry_jitter_bounds=provider_retry_jitter_bounds,
            **kwargs,
        )

    return build


async def check_qwen_auth_status(
    *,
    config: dict[str, Any],
    auth_status_cache: dict[str, Any],
    default_model: str,
    cache_ttl_sec: float,
    force: bool,
    new_qwen_api: Callable[[], Any | None],
    run_in_threadpool: Callable[[Callable[[], Any]], Any],
    run_with_provider_slot: Callable[[str, Callable[[], Any]], Any],
    rate_limited_error: Callable[[str | None], bool],
    active_session_count: Callable[[], int],
    max_active_sessions: Callable[[], int],
    provider_concurrency: Callable[[], int],
    provider_start_throttle_enabled: Callable[[], bool],
    provider_start_interval_sec: Callable[[], float],
    provider_start_jitter_sec: Callable[[], float],
    provider_retry_jitter_enabled: Callable[[], bool],
    provider_retry_jitter_bounds: Callable[[], tuple[float, float]],
) -> dict[str, Any]:
    """Check Qwen token validity via provider user API with cache support."""
    build_payload = _payload_builder(
        config=config,
        default_model=default_model,
        active_session_count=active_session_count,
        max_active_sessions=max_active_sessions,
        provider_concurrency=provider_concurrency,
        provider_start_throttle_enabled=provider_start_throttle_enabled,
        provider_start_interval_sec=provider_start_interval_sec,
        provider_start_jitter_sec=provider_start_jitter_sec,
        provider_retry_jitter_enabled=provider_retry_jitter_enabled,
        provider_retry_jitter_bounds=provider_retry_jitter_bounds,
    )

    if not str(config.get("token") or "").strip():
        return build_payload(status="missing", valid=False, message="QWEN_TOKEN не задан.")

    cached = auth_status_cache.get("value")
    checked_at = float(auth_status_cache.get("checked_at") or 0.0)
    cache_age = time.monotonic() - checked_at
    if not force and isinstance(cached, dict) and cache_age <= cache_ttl_sec:
        payload = dict(cached)
        payload["cached"] = True
        payload["cache_age_sec"] = round(cache_age, 1)
        return payload

    client = new_qwen_api()
    if client is None:
        return build_payload(status="missing", valid=False, message="Qwen API не инициализирован: токен отсутствует.")

    try:
        info = await run_in_threadpool(lambda: run_with_provider_slot("auth_status", client.get_user_info))
        user = {}
        if isinstance(info, dict):
            user = {
                "id": info.get("id") or info.get("user_id"),
                "name": info.get("name") or info.get("nickname") or info.get("username"),
                "email": info.get("email"),
            }
            user = {key: value for key, value in user.items() if value}
        payload = build_payload(status="valid", valid=True, message="Текущий Qwen токен действителен.", user=user)
    except ValueError as exc:
        payload = build_payload(
            status="unknown",
            valid=False,
            message=(
                "Qwen /api/user вернул не-JSON ответ. Токен не помечен как истёк; "
                "для точной проверки нажмите 'Проверить действующий токен'. "
                f"Детали: {exc}"
            ),
        )
        payload["checked_by"] = "provider_user_api"
    except Exception as exc:
        message = str(exc)
        if is_qwen_token_expired_error(message):
            payload = build_payload(status="expired", valid=False, expired=True, message="Qwen токен истёк. Обновите QWEN_TOKEN через HAR.")
        elif rate_limited_error(message):
            payload = build_payload(
                status="rate_limited",
                valid=True,
                message="Текущий Qwen токен принят, но провайдер ограничил частоту запросов.",
            )
            payload["rate_limited"] = True
        else:
            payload = build_payload(status="unknown", valid=False, message=message or "Не удалось достоверно проверить Qwen токен.")

    auth_status_cache["value"] = payload
    auth_status_cache["checked_at"] = time.monotonic()
    return payload


def active_token_smoke_check_sync(
    *,
    config: dict[str, Any],
    default_model: str,
    new_qwen_api: Callable[[], Any | None],
    run_with_provider_slot: Callable[[str, Callable[[], Any]], Any],
    send_message_sync: Callable[..., Any],
    current_qwen_client: ContextVar[Any | None],
    registry_lock: RLock,
    active_sessions: dict[str, Any],
    drop_session_client: Callable[[str], None],
    rate_limited_error: Callable[[str | None], bool],
    active_session_count: Callable[[], int],
    max_active_sessions: Callable[[], int],
    provider_concurrency: Callable[[], int],
    provider_start_throttle_enabled: Callable[[], bool],
    provider_start_interval_sec: Callable[[], float],
    provider_start_jitter_sec: Callable[[], float],
    provider_retry_jitter_enabled: Callable[[], bool],
    provider_retry_jitter_bounds: Callable[[], tuple[float, float]],
) -> dict[str, Any]:
    """Perform active Qwen smoke check by creating a short test chat."""
    build_payload = _payload_builder(
        config=config,
        default_model=default_model,
        active_session_count=active_session_count,
        max_active_sessions=max_active_sessions,
        provider_concurrency=provider_concurrency,
        provider_start_throttle_enabled=provider_start_throttle_enabled,
        provider_start_interval_sec=provider_start_interval_sec,
        provider_start_jitter_sec=provider_start_jitter_sec,
        provider_retry_jitter_enabled=provider_retry_jitter_enabled,
        provider_retry_jitter_bounds=provider_retry_jitter_bounds,
    )

    if not str(config.get("token") or "").strip():
        return build_payload(status="missing", valid=False, message="QWEN_TOKEN не задан.")

    client = new_qwen_api()
    if client is None:
        return build_payload(status="missing", valid=False, message="Qwen API не инициализирован: токен отсутствует.")

    session_id = ""
    started = time.monotonic()
    try:
        session_id = run_with_provider_slot("auth_check_create_session", client.create_session)
        if not session_id:
            return build_payload(status="invalid", valid=False, message="Qwen не вернул id тестовой сессии.")

        client.session_id = session_id
        token = current_qwen_client.set(client)
        try:
            run_with_provider_slot(
                "auth_check_send_message",
                lambda: send_message_sync(
                    session_id=session_id,
                    message="Ответь только: OK",
                    thinking_enabled=False,
                    search_enabled=False,
                    ref_file_ids=None,
                    timeout=60,
                ),
            )
        finally:
            current_qwen_client.reset(token)

        payload = build_payload(status="valid", valid=True, message="Текущий Qwen токен действителен: тестовый чат успешно получил ответ.")
        payload["checked_by"] = "smoke_chat"
        payload["duration_sec"] = round(time.monotonic() - started, 2)
        return payload
    except Exception as exc:
        message = str(exc)
        if is_qwen_token_expired_error(message):
            payload = build_payload(status="expired", valid=False, expired=True, message="Qwen токен истёк. Обновите его через HAR.")
        elif rate_limited_error(message):
            payload = build_payload(
                status="rate_limited",
                valid=True,
                message="Текущий Qwen токен принят, но провайдер временно ограничил частоту запросов: Too many requests.",
            )
            payload["rate_limited"] = True
        else:
            payload = build_payload(status="invalid", valid=False, message=message or "Текущий Qwen токен не прошёл smoke-проверку.")
        payload["checked_by"] = "smoke_chat"
        payload["duration_sec"] = round(time.monotonic() - started, 2)
        return payload
    finally:
        if session_id:
            try:
                run_with_provider_slot("auth_check_delete_session", lambda: client.delete_session(session_id))
            except Exception as cleanup_exc:
                logging.warning("Smoke-check session cleanup failed for %s: %s", session_id[-8:], cleanup_exc)
            with registry_lock:
                active_sessions.pop(session_id, None)
            drop_session_client(session_id)
