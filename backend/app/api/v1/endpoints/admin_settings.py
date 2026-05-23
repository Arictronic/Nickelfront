"""Admin API for global technical settings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin_user
from app.db.session import get_db
from app.services.system_settings_service import SETTINGS_SCHEMA, SystemSettingsService
from shared.schemas.auth import UserResponse
from shared.schemas.system_settings import (
    SystemSettingsResponse,
    SystemSettingsSectionResponse,
    SystemSettingsSectionUpdate,
)

router = APIRouter(prefix="/admin/settings", tags=["admin-settings"])


@router.get("", response_model=SystemSettingsResponse)
async def get_system_settings(
    _current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return all global technical settings and UI schema."""
    service = SystemSettingsService(db)
    return {"settings": await service.get_all(), "schema": SETTINGS_SCHEMA}


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
