"""Admin API for global technical settings."""

from __future__ import annotations

import os
import time
from threading import RLock
from typing import Any

from anyio import to_thread
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin_user
from app.db.session import get_db
from app.services.qwen_client import QwenServiceClient
from app.services.qwen_test_runner import run_qwen_service_test
from app.services.system_settings_service import SystemSettingsService, get_settings_schema
from shared.schemas.auth import UserResponse
from shared.schemas.system_settings import (
    SystemSettingsResponse,
    SystemSettingsSectionResponse,
    SystemSettingsSectionUpdate,
)

router = APIRouter(prefix="/admin/settings", tags=["admin-settings"])





_QWEN_TOKEN_STATUS_CACHE_TTL_SEC = float(
    os.getenv("QWEN_BACKEND_TOKEN_STATUS_CACHE_TTL_SEC", "60") or 60
)
_QWEN_TOKEN_STATUS_CACHE_LOCK = RLock()
_QWEN_TOKEN_STATUS_CACHE: dict[str, Any] | None = None
_QWEN_TOKEN_STATUS_CACHE_EXPIRES_AT = 0.0


def _clear_qwen_token_status_cache() -> None:
    global _QWEN_TOKEN_STATUS_CACHE, _QWEN_TOKEN_STATUS_CACHE_EXPIRES_AT
    with _QWEN_TOKEN_STATUS_CACHE_LOCK:
        _QWEN_TOKEN_STATUS_CACHE = None
        _QWEN_TOKEN_STATUS_CACHE_EXPIRES_AT = 0.0


class QwenTestRunRequest(BaseModel):
    chat_count: int = Field(default=5, ge=1, le=50)
    message: str = Field(default="Напиши короткий ответ: OK", min_length=1, max_length=4000)


def _normalize_qwen_auth_status(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    status = str(data.get("status") or "unknown").strip().lower()
    expired = bool(data.get("expired") or status == "expired")
    token_configured = bool(data.get("token_configured") or data.get("has_token"))
    rate_limited = bool(data.get("rate_limited") or status == "rate_limited")


    valid = bool(data.get("valid") or status == "valid" or rate_limited)

    if expired:
        normalized_status = "expired"
        message = "Токен авторизации Qwen истёк. Обновите его через HAR."
    elif valid and rate_limited:
        normalized_status = "rate_limited"
        message = str(data.get("message") or "Текущий Qwen токен действителен, но провайдер временно ограничил частоту запросов.")
    elif valid:
        normalized_status = "valid"
        message = str(data.get("message") or "Текущий Qwen токен действителен.")
    elif not token_configured:
        normalized_status = "missing"
        message = "Qwen токен не задан."
    elif status in {"unknown", "unverified", "bad_response"}:
        normalized_status = status
        message = str(data.get("message") or "Не удалось достоверно проверить текущий Qwen токен. Это не означает, что он истёк.")
    else:
        normalized_status = status or "invalid"
        message = str(data.get("message") or "Текущий Qwen токен не прошёл проверку.")

    return {
        "status": normalized_status,
        "valid": valid,
        "expired": expired,
        "rate_limited": rate_limited,
        "token_configured": token_configured,
        "message": message,
        "model": data.get("model"),
        "user": data.get("user"),
        "checked_by": data.get("checked_by") or data.get("check") or data.get("source"),
        "service_available": data.get("service_available"),
        "active_sessions": data.get("active_sessions"),
        "max_active_sessions": data.get("max_active_sessions"),
        "provider_max_concurrent_requests": data.get("provider_max_concurrent_requests"),
    }


def _qwen_client() -> QwenServiceClient:
    return QwenServiceClient(queue_enabled=False, timeout=15.0)


def _get_qwen_token_status_sync() -> dict[str, Any]:
    global _QWEN_TOKEN_STATUS_CACHE, _QWEN_TOKEN_STATUS_CACHE_EXPIRES_AT

    now = time.monotonic()
    with _QWEN_TOKEN_STATUS_CACHE_LOCK:
        if _QWEN_TOKEN_STATUS_CACHE is not None and _QWEN_TOKEN_STATUS_CACHE_EXPIRES_AT > now:
            return dict(_QWEN_TOKEN_STATUS_CACHE)

    status = _normalize_qwen_auth_status(_qwen_client().get_auth_status(force=False))

    with _QWEN_TOKEN_STATUS_CACHE_LOCK:
        _QWEN_TOKEN_STATUS_CACHE = dict(status)
        _QWEN_TOKEN_STATUS_CACHE_EXPIRES_AT = time.monotonic() + max(
            1.0, _QWEN_TOKEN_STATUS_CACHE_TTL_SEC
        )

    return status


def _check_qwen_token_sync() -> dict[str, Any]:
    return _normalize_qwen_auth_status(_qwen_client().check_active_token())



@router.get("", response_model=SystemSettingsResponse)
async def get_system_settings(
    _current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return all global technical settings and UI schema."""
    service = SystemSettingsService(db)
    return {"settings": await service.get_all(), "schema": get_settings_schema()}


@router.get("/public-display")
async def get_public_display_settings(
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """Return non-sensitive display settings used by regular frontend pages."""
    service = SystemSettingsService(db)
    try:
        pdf_markdown = await service.get_section("pdf_markdown")
    except Exception:
        pdf_markdown = {}
    return {
        "show_extraction_diagnostics": bool(
            pdf_markdown.get("show_extraction_diagnostics", True)
        )
    }




@router.get("/qwen/token/status")
async def get_qwen_token_status(
    _current_user: UserResponse = Depends(get_current_user),
) -> dict[str, Any]:
    """Return non-secret Qwen token status for UI warnings."""
    return await to_thread.run_sync(_get_qwen_token_status_sync)


@router.post("/qwen/token/check")
async def check_qwen_token(
    _current_user: UserResponse = Depends(require_admin_user),
) -> dict[str, Any]:
    """Admin action: check current Qwen token validity."""
    _clear_qwen_token_status_cache()
    return await to_thread.run_sync(_check_qwen_token_sync)


@router.post("/qwen/test-run")
async def run_qwen_test(
    payload: QwenTestRunRequest,
    _current_user: UserResponse = Depends(require_admin_user),
) -> dict[str, Any]:
    """Admin action: run a direct Qwen Service smoke/parallellism test."""
    return await to_thread.run_sync(
        run_qwen_service_test,
        payload.chat_count,
        240.0,
        payload.message,
    )


@router.post("/qwen/token/update-from-har")
async def update_qwen_token_from_har(
    har_file: UploadFile = File(...),
    _current_user: UserResponse = Depends(require_admin_user),
) -> dict[str, Any]:
    """Extract the latest Qwen token from uploaded HAR and apply it to qwen_service.

    The HAR file is read in memory only and is not saved. The response never
    returns the token value, only a short masked preview and source metadata.
    """
    filename = har_file.filename or ""
    if filename and not filename.lower().endswith(".har"):
        raise HTTPException(status_code=400, detail="Загрузите HAR-файл с расширением .har")

    content = await har_file.read()
    if len(content) > 120 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="HAR-файл слишком большой: максимум 120 МБ")

    def _update_from_har_sync() -> tuple[dict[str, Any], dict[str, Any]]:
        client = _qwen_client()
        update_result = client.update_token_from_har_bytes(
            content,
            filename=filename or "qwen.har",
            validate=True,
        )
        if str(update_result.get("status") or "").lower() not in {"ok", "success"}:
            raise RuntimeError(str(update_result.get("message") or "qwen_service не смог извлечь или применить токен из HAR"))

        status = _normalize_qwen_auth_status(update_result.get("qwen_status") or client.check_active_token())
        return update_result, status

    try:
        update_result, status = await to_thread.run_sync(_update_from_har_sync)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _clear_qwen_token_status_cache()
    return {
        "updated": True,
        "token_preview": update_result.get("token_preview"),
        "token_source": update_result.get("token_source"),
        "qwen_status": status,
        "message": "Qwen токен обновлён из HAR." if status.get("valid") else "Токен извлечён и установлен, но проверка не прошла.",
    }

@router.get("/{section}", response_model=SystemSettingsSectionResponse)
async def get_system_settings_section(
    section: str,
    _current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return one settings section."""
    service = SystemSettingsService(db)
    try:
        value = await service.get_section(section)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"section": section, "value": value}


@router.patch("/{section}", response_model=SystemSettingsSectionResponse)
async def update_system_settings_section(
    section: str,
    payload: SystemSettingsSectionUpdate,
    current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update one editable settings section."""
    service = SystemSettingsService(db)
    try:
        value = await service.update_section(section, payload.value, updated_by=current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"section": section, "value": value}


@router.post("/{section}/reset", response_model=SystemSettingsSectionResponse)
async def reset_system_settings_section(
    section: str,
    current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Reset section to safe defaults."""
    service = SystemSettingsService(db)
    try:
        value = await service.reset_section(section, updated_by=current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"section": section, "value": value}
