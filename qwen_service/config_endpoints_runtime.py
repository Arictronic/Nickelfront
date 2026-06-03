"""Runtime handlers for Qwen service auth/config/model endpoints.

The public FastAPI routes still live in service.py.  This module keeps their
business logic out of the route file while preserving the exact endpoint
signatures and response shapes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials

try:  # package import
    from .defaults import (
        DEFAULT_AUTO_CONTINUE_ENABLED,
        DEFAULT_BROWSER_CHANNEL,
        DEFAULT_BROWSER_HEADLESS,
        DEFAULT_BROWSER_LOGIN_AUTOMATION,
        DEFAULT_BROWSER_PROFILE_DIR,
        DEFAULT_BROWSER_REFRESH_TIMEOUT_SEC,
        DEFAULT_CDP_URL,
        DEFAULT_MODEL,
        DEFAULT_PLAYWRIGHT_ENABLED,
        DEFAULT_SESSION_SOURCE,
    )
    from .har_token_scanner import extract_latest_qwen_session_from_har_bytes, mask_token
    from .playwright_session import refresh_qwen_browser_session, refresh_qwen_cdp_session
    from .runtime_state import QwenRuntimeState
    from .schemas import APIKeyConfig, HarFileImportRequest, ModelConfig, QwenSessionHeadersConfig, RuntimeConfigUpdate, TokenConfig
except ImportError:  # pragma: no cover - supports direct script imports
    from defaults import (
        DEFAULT_AUTO_CONTINUE_ENABLED,
        DEFAULT_BROWSER_CHANNEL,
        DEFAULT_BROWSER_HEADLESS,
        DEFAULT_BROWSER_LOGIN_AUTOMATION,
        DEFAULT_BROWSER_PROFILE_DIR,
        DEFAULT_BROWSER_REFRESH_TIMEOUT_SEC,
        DEFAULT_CDP_URL,
        DEFAULT_MODEL,
        DEFAULT_PLAYWRIGHT_ENABLED,
        DEFAULT_SESSION_SOURCE,
    )
    from har_token_scanner import extract_latest_qwen_session_from_har_bytes, mask_token
    from playwright_session import refresh_qwen_browser_session, refresh_qwen_cdp_session
    from runtime_state import QwenRuntimeState
    from schemas import APIKeyConfig, HarFileImportRequest, ModelConfig, QwenSessionHeadersConfig, RuntimeConfigUpdate, TokenConfig

RequireToken = Callable[[HTTPAuthorizationCredentials | None], None]
AuthStatusBuilder = Callable[..., dict[str, Any]]
CheckAuthStatus = Callable[..., Awaitable[dict[str, Any]]]
ApplySessionValues = Callable[[dict[str, Any]], dict[str, Any]]


async def auth_status_payload(
    *,
    force: bool,
    credentials: HTTPAuthorizationCredentials | None,
    require_service_token: RequireToken,
    check_qwen_auth_status: CheckAuthStatus,
) -> dict[str, Any]:
    """Return current Qwen token status without exposing secrets."""
    require_service_token(credentials)
    return await check_qwen_auth_status(force=force)


async def auth_check_payload(
    *,
    state: QwenRuntimeState,
    credentials: HTTPAuthorizationCredentials | None,
    require_service_token: RequireToken,
    active_token_smoke_check_sync: Callable[[], dict[str, Any]],
    monotonic: Callable[[], float],
) -> dict[str, Any]:
    """Smoke-check the active in-memory Qwen token with a minimal request."""
    require_service_token(credentials)
    payload = await run_in_threadpool(active_token_smoke_check_sync)
    state.auth_status_cache["value"] = payload
    state.auth_status_cache["checked_at"] = monotonic()
    return payload


def get_config_payload(*, public_config_payload: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    return public_config_payload()


def update_config_payload(
    *,
    state: QwenRuntimeState,
    update: RuntimeConfigUpdate,
    credentials: HTTPAuthorizationCredentials | None,
    require_service_token: RequireToken,
    apply_runtime_config_update: Callable[[RuntimeConfigUpdate], dict[str, Any]],
) -> dict[str, Any]:
    require_service_token(credentials)
    with state.request_lock:
        updated = apply_runtime_config_update(update)
    return {"status": "ok", **updated}


def get_auto_continue_config_payload(*, state: QwenRuntimeState) -> dict[str, Any]:
    config = state.config
    return {
        "enabled": config.get("auto_continue_enabled", DEFAULT_AUTO_CONTINUE_ENABLED),
        "max_continues": config.get("max_continues"),
    }


def set_auto_continue_config_payload(
    *,
    state: QwenRuntimeState,
    enabled: bool,
    max_continues: int | None,
    credentials: HTTPAuthorizationCredentials | None,
    require_service_token: RequireToken,
    apply_runtime_config_update: Callable[[RuntimeConfigUpdate], dict[str, Any]],
) -> dict[str, Any]:
    require_service_token(credentials)
    update = RuntimeConfigUpdate(auto_continue_enabled=enabled, max_continues=max_continues)
    with state.request_lock:
        updated = apply_runtime_config_update(update)
    return {"status": "ok", "enabled": updated["auto_continue_enabled"], "max_continues": updated["max_continues"]}


def set_token_payload(
    *,
    state: QwenRuntimeState,
    token_config: TokenConfig,
    credentials: HTTPAuthorizationCredentials | None,
    require_service_token: RequireToken,
    save_config: Callable[[dict[str, Any]], None],
    reset_runtime_state_locked: Callable[[], None],
) -> dict[str, Any]:
    require_service_token(credentials)
    token = (token_config.token or "").strip()
    with state.request_lock:
        state.config["token"] = token
        save_config(state.config)
        reset_runtime_state_locked()
    return {"status": "ok", "message": "Токен установлен" if token else "Токен очищен", "available": bool(state.control_qwen_api)}


async def set_token_from_har_upload_payload(
    *,
    state: QwenRuntimeState,
    har_file: UploadFile,
    validate: bool,
    require_file_api: bool,
    credentials: HTTPAuthorizationCredentials | None,
    require_service_token: RequireToken,
    apply_session_values_locked: Callable[..., dict[str, Any]],
    check_qwen_auth_status: CheckAuthStatus,
    auth_status_payload_builder: AuthStatusBuilder,
) -> dict[str, Any]:
    require_service_token(credentials)

    filename = har_file.filename or ""
    if filename and not filename.lower().endswith(".har"):
        raise HTTPException(status_code=400, detail="Загрузите HAR-файл с расширением .har")

    content = await har_file.read()
    if len(content) > 120 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="HAR-файл слишком большой: максимум 120 МБ")

    try:
        session_values, meta = extract_latest_qwen_session_from_har_bytes(content, require_file_api=require_file_api)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with state.request_lock:
        public = apply_session_values_locked(session_values, source="har", clear_missing=False)

    auth_status = await check_qwen_auth_status() if validate else auth_status_payload_builder(
        status="updated",
        valid=False,
        message="Токен/session установлены из HAR, проверка не выполнялась.",
    )
    return {
        "status": "ok",
        "updated": True,
        "token_preview": mask_token(state.config.get("token")),
        **public,
        "token_source": meta,
        "qwen_status": auth_status,
        "message": "Qwen token/session обновлены из HAR." if auth_status.get("valid") else "Token/session извлечены и установлены, но проверка токена не прошла.",
    }


def get_har_dir_info_payload(
    *,
    credentials: HTTPAuthorizationCredentials | None,
    require_service_token: RequireToken,
    ensure_har_dir: Callable[[], Path],
) -> dict[str, Any]:
    require_service_token(credentials)
    har_dir = ensure_har_dir()
    files = []
    for har_path in sorted(har_dir.glob("*.har"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = har_path.stat()
        files.append({"filename": har_path.name, "size_bytes": stat.st_size, "modified_at": stat.st_mtime})
    return {
        "status": "ok",
        "har_dir": str(har_dir),
        "has_har_files": bool(files),
        "latest": files[0] if files else None,
        "files": files[:20],
        "message": "Положите HAR-файл с запросами /api/v2/files/* в qwen_service/har и вызовите POST /config/token/update-from-har-file.",
    }


async def set_token_from_local_har_file_payload(
    *,
    state: QwenRuntimeState,
    import_request: HarFileImportRequest | None,
    validate: bool,
    require_file_api: bool,
    credentials: HTTPAuthorizationCredentials | None,
    require_service_token: RequireToken,
    load_har_from_service_dir: Callable[[str | None], tuple[Path, bytes]],
    apply_session_values_locked: Callable[..., dict[str, Any]],
    check_qwen_auth_status: CheckAuthStatus,
    auth_status_payload_builder: AuthStatusBuilder,
) -> dict[str, Any]:
    require_service_token(credentials)
    filename = import_request.filename if import_request else None
    har_path, content = load_har_from_service_dir(filename)
    try:
        session_values, meta = extract_latest_qwen_session_from_har_bytes(content, require_file_api=require_file_api)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with state.request_lock:
        public = apply_session_values_locked(session_values, source="har", clear_missing=False)

    auth_status = await check_qwen_auth_status() if validate else auth_status_payload_builder(
        status="updated",
        valid=False,
        message="Токен/session установлены из HAR-файла из qwen_service/har, проверка не выполнялась.",
    )
    return {
        "status": "ok",
        "updated": True,
        "har_dir": str(har_path.parent),
        "har_filename": har_path.name,
        "token_preview": mask_token(state.config.get("token")),
        **public,
        "token_source": meta,
        "qwen_status": auth_status,
        "message": "Qwen token/session обновлены из локального HAR-файла." if auth_status.get("valid") else "Token/session извлечены из HAR-файла и установлены, но проверка токена не прошла.",
    }


async def update_session_headers_payload(
    *,
    state: QwenRuntimeState,
    session_config: QwenSessionHeadersConfig,
    validate: bool,
    credentials: HTTPAuthorizationCredentials | None,
    require_service_token: RequireToken,
    apply_session_values_locked: Callable[..., dict[str, Any]],
    safe_session_source: Callable[[str | None, str], str],
    check_qwen_auth_status: CheckAuthStatus,
) -> dict[str, Any]:
    require_service_token(credentials)
    values = {
        "token": session_config.token,
        "cookie": session_config.cookie,
        "bx_ua": session_config.bx_ua,
        "bx_umidtoken": session_config.bx_umidtoken,
        "bx_v": session_config.bx_v,
        "user_agent": session_config.user_agent,
        "file_api_extra_headers_json": session_config.file_api_extra_headers_json,
        "file_sts_payload_template_json": session_config.file_sts_payload_template_json,
        "file_sts_url": session_config.file_sts_url,
        "file_parse_payload_template_json": session_config.file_parse_payload_template_json,
        "file_parse_url": session_config.file_parse_url,
        "file_parse_status_payload_template_json": session_config.file_parse_status_payload_template_json,
        "file_parse_status_url": session_config.file_parse_status_url,
        "oss_put_headers_template_json": session_config.oss_put_headers_template_json,
    }
    if not session_config.clear_missing and not any(str(value or "").strip() for value in values.values()):
        raise HTTPException(status_code=400, detail="Передайте хотя бы одно поле: token/cookie/bx_ua/bx_umidtoken/bx_v/user_agent/file templates/oss_put_headers_template_json")

    with state.request_lock:
        public = apply_session_values_locked(
            values,
            source=safe_session_source(session_config.source, "manual"),
            clear_missing=bool(session_config.clear_missing),
        )
    auth_status = await check_qwen_auth_status() if validate else None
    return {"status": "ok", "updated": True, **public, "qwen_status": auth_status, "message": "Qwen browser-session headers обновлены вручную."}


async def refresh_session_from_cdp_payload(
    *,
    state: QwenRuntimeState,
    validate: bool,
    credentials: HTTPAuthorizationCredentials | None,
    require_service_token: RequireToken,
    apply_session_values_locked: Callable[..., dict[str, Any]],
    check_qwen_auth_status: CheckAuthStatus,
) -> dict[str, Any]:
    require_service_token(credentials)
    config = state.config
    if not bool(config.get("playwright_enabled", DEFAULT_PLAYWRIGHT_ENABLED)):
        raise HTTPException(status_code=400, detail="QWEN_PLAYWRIGHT_ENABLED=false; CDP capture requires Playwright client library")
    try:
        result = await run_in_threadpool(
            refresh_qwen_cdp_session,
            cdp_url=str(config.get("cdp_url", DEFAULT_CDP_URL) or DEFAULT_CDP_URL),
            timeout_sec=float(config.get("browser_refresh_timeout_sec", DEFAULT_BROWSER_REFRESH_TIMEOUT_SEC)),
        )
    except Exception as exc:
        logging.exception("Qwen CDP session refresh failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    values = result.get("values") if isinstance(result, dict) else {}
    if not isinstance(values, dict):
        values = {}
    with state.request_lock:
        public = apply_session_values_locked(values, source="cdp", clear_missing=False)
    auth_status = await check_qwen_auth_status() if validate else None
    return {
        "status": "ok" if result.get("ok") else "partial",
        "updated": True,
        "source": "cdp",
        **public,
        "qwen_status": auth_status,
        "message": result.get("message") or "Qwen CDP session refresh completed.",
    }


async def refresh_session_from_browser_payload(
    *,
    state: QwenRuntimeState,
    validate: bool,
    credentials: HTTPAuthorizationCredentials | None,
    require_service_token: RequireToken,
    apply_session_values_locked: Callable[..., dict[str, Any]],
    safe_session_source: Callable[[str | None, str], str],
    check_qwen_auth_status: CheckAuthStatus,
) -> dict[str, Any]:
    require_service_token(credentials)
    config = state.config
    source = safe_session_source(str(config.get("session_source", DEFAULT_SESSION_SOURCE)), "har")
    if source == "cdp":
        return await refresh_session_from_cdp_payload(
            state=state,
            validate=validate,
            credentials=credentials,
            require_service_token=require_service_token,
            apply_session_values_locked=apply_session_values_locked,
            check_qwen_auth_status=check_qwen_auth_status,
        )
    if source != "playwright" or not bool(config.get("browser_login_automation", DEFAULT_BROWSER_LOGIN_AUTOMATION)):
        raise HTTPException(
            status_code=400,
            detail=(
                "qwen_browser_login_automation_disabled: login in a normal Chrome/Edge and use "
                "POST /config/token/update-from-har, POST /config/session/update, or "
                "set QWEN_SESSION_SOURCE=cdp and call /config/session/refresh-cdp"
            ),
        )
    if not bool(config.get("playwright_enabled", DEFAULT_PLAYWRIGHT_ENABLED)):
        raise HTTPException(status_code=400, detail="QWEN_PLAYWRIGHT_ENABLED=false")
    try:
        result = await run_in_threadpool(
            refresh_qwen_browser_session,
            profile_dir=str(config.get("browser_profile_dir", DEFAULT_BROWSER_PROFILE_DIR)),
            headless=bool(config.get("browser_headless", DEFAULT_BROWSER_HEADLESS)),
            channel=str(config.get("browser_channel", DEFAULT_BROWSER_CHANNEL) or DEFAULT_BROWSER_CHANNEL),
            timeout_sec=float(config.get("browser_refresh_timeout_sec", DEFAULT_BROWSER_REFRESH_TIMEOUT_SEC)),
        )
    except Exception as exc:
        logging.exception("Qwen browser session refresh failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    values = result.get("values") if isinstance(result, dict) else {}
    if not isinstance(values, dict):
        values = {}
    with state.request_lock:
        public = apply_session_values_locked(values, source="playwright", clear_missing=False)
    auth_status = await check_qwen_auth_status() if validate else None
    return {
        "status": "ok" if result.get("ok") else "partial",
        "updated": True,
        "source": "playwright",
        **public,
        "qwen_status": auth_status,
        "message": result.get("message") or "Qwen browser session refresh completed.",
    }


def set_api_key_payload(
    *,
    state: QwenRuntimeState,
    api_key_config: APIKeyConfig,
    credentials: HTTPAuthorizationCredentials | None,
    require_service_token: RequireToken,
    save_config: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    require_service_token(credentials)
    state.config["api_key"] = (api_key_config.api_key or "").strip()
    save_config(state.config)
    return {"status": "ok", "message": "API ключ установлен"}


def get_model_payload(*, state: QwenRuntimeState) -> dict[str, Any]:
    return {"model": state.config.get("model", DEFAULT_MODEL)}


def set_model_payload(
    *,
    state: QwenRuntimeState,
    model_config: ModelConfig,
    credentials: HTTPAuthorizationCredentials | None,
    require_service_token: RequireToken,
    apply_runtime_config_update: Callable[[RuntimeConfigUpdate], dict[str, Any]],
) -> dict[str, Any]:
    require_service_token(credentials)
    update = RuntimeConfigUpdate(
        model=model_config.model,
        thinking_enabled=model_config.thinking_enabled,
        search_enabled=model_config.search_enabled,
        auto_continue_enabled=model_config.auto_continue_enabled,
        max_continues=model_config.max_continues,
    )
    with state.request_lock:
        updated = apply_runtime_config_update(update)
    return {"status": "ok", "model": updated["model"]}


async def list_models_payload(
    *,
    credentials: HTTPAuthorizationCredentials | None,
    verify_token: Callable[[HTTPAuthorizationCredentials | None], bool],
    qwen_api: Any,
    run_qwen_locked: Callable[..., Awaitable[Any]],
) -> dict[str, Any]:
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")
    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")
    try:
        models = await run_qwen_locked(qwen_api.fetch_models)
        return {"models": models}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
