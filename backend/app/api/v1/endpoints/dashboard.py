"""Dashboard overview endpoints for the operational Nickelfront home page."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin_user
from app.db.session import get_db
from app.services.dashboard_service import (
    DashboardActionConflictError,
    DashboardActionUnavailableError,
    get_dashboard_jobs,
    get_dashboard_overview,
    trigger_dashboard_action,
)
from shared.schemas.auth import UserResponse

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class DashboardActionRequest(BaseModel):
    """Safe, bounded payload for admin dashboard actions."""

    limit: int | None = Field(default=None, ge=1, le=5000)
    source: str | None = Field(default=None, max_length=50)
    query: str | None = Field(default=None, max_length=500)
    pdf_mode: str | None = Field(default="auto", max_length=20)


@router.get("/overview")
async def dashboard_overview(
    timezone_offset_minutes: int = Query(default=0, ge=-840, le=840),
    force_refresh: bool = Query(default=False),
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated operational snapshot for the redesigned dashboard."""
    return await get_dashboard_overview(
        db=db,
        timezone_offset_minutes=timezone_offset_minutes,
        force_refresh=force_refresh,
    )


@router.get("/jobs")
async def dashboard_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    _current_user: UserResponse = Depends(get_current_user),
):
    """Parse jobs normalized for dashboard cards and counters."""
    return await get_dashboard_jobs(limit=limit)


@router.post("/actions/{action}", status_code=status.HTTP_202_ACCEPTED)
async def dashboard_action(
    action: str,
    payload: DashboardActionRequest | None = None,
    _current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Queue a heavy dashboard action. Admin-only by design."""
    try:
        return await trigger_dashboard_action(
            action,
            (payload or DashboardActionRequest()).model_dump(exclude_none=True),
            db=db,
        )
    except DashboardActionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DashboardActionUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
