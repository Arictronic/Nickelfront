"""Admin API for global technical settings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin_user
from app.db.session import get_db
from app.services.qwen_client import QwenServiceClient
from app.services.system_settings_service import SystemSettingsService, get_settings_schema
from shared.schemas.auth import UserResponse
from shared.schemas.system_settings import (
    SystemSettingsResponse,
    SystemSettingsSectionResponse,
    SystemSettingsSectionUpdate,
)

router = APIRouter(prefix="/admin/settings", tags=["admin-settings"])


def _normalize_qwen_auth_status(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    status = str(data.get("status") or "unknown").strip().lower()
    expired = bool(data.get("expired") or status == "expired")
    valid = bool(data.get("valid") or status == "valid")
    token_configured = bool(data.get("token_configured") or data.get("has_token"))

    if expired:
        message = "Токен авторизации нейросети QWEN истёк. Обновите токен в настройках."
    elif valid:
        message = "Qwen токен действителен."
    elif not token_configured:
        message = "Qwen токен не задан."
    else:
        message = str(data.get("message") or "Qwen токен не прошёл проверку.")

    return {
        "status": "expired" if expired else ("valid" if valid else status),
        "valid": valid,
        "expired": expired,
        "token_configured": token_configured,
        "message": message,
        "model": data.get("model"),
        "user": data.get("user"),
    }


def _qwen_client() -> QwenServiceClient:
    return QwenServiceClient(queue_enabled=False, timeout=15.0)



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
    return _normalize_qwen_auth_status(_qwen_client().get_auth_status())


@router.post("/qwen/token/check")
async def check_qwen_token(
    _current_user: UserResponse = Depends(require_admin_user),
) -> dict[str, Any]:
    """Admin action: check current Qwen token validity."""
    return _normalize_qwen_auth_status(_qwen_client().get_auth_status())


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

    client = _qwen_client()
    update_result = client.update_token_from_har_bytes(
        content,
        filename=filename or "qwen.har",
        validate=True,
    )
    if str(update_result.get("status") or "").lower() not in {"ok", "success"}:
        raise HTTPException(
            status_code=502,
            detail=str(update_result.get("message") or "qwen_service не смог извлечь или применить токен из HAR"),
        )

    status = _normalize_qwen_auth_status(update_result.get("qwen_status") or client.get_auth_status())
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
