

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TaskCreate(BaseModel):
    patent_number: str
    options: dict[str, Any] = Field(default_factory=dict)


class TaskOut(BaseModel):
    id: int
    patent_number: str
    status: str
    result: dict[str, Any] | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CeleryTaskStatus(BaseModel):
    """Статус задачи Celery по task_id."""
    task_id: str
    status: Literal["PENDING", "RECEIVED", "STARTED", "PROGRESS", "RETRY", "FAILURE", "SUCCESS", "REVOKED", "UNKNOWN"]
    state: str | None = None
    result: dict[str, Any] | None = None
    progress: dict[str, Any] | None = None


    query: str | None = None
    source: str | None = None
    current: int | None = None
    total: int | None = None
    saved_count: int | None = None
    updated_count: int | None = None
    duplicate_count: int | None = None
    embedded_count: int | None = None
    content_queued_count: int | None = None
    content_skipped_count: int | None = None
    total_saved: int | None = None
    total_updated: int | None = None
    total_duplicates: int | None = None
    total_content_queued: int | None = None
    total_content_skipped: int | None = None
    errors: list[str] | None = None
    pipeline_error: bool | None = None
    failed_stage: str | None = None
    pipeline_error_message: str | None = None
    stage_errors: list[dict[str, Any]] | None = None
    final_stage: str | None = None


    name: str | None = None
    args: list | None = None
    kwargs: dict[str, Any] | None = None
    child_task_ids: list[str] | None = None
    children: list[dict[str, Any]] | None = None
    related_child_statuses: list[dict[str, Any]] | None = None
    related_task_ids: list[str] | None = None
    stage_task_ids: dict[str, str] | None = None
    stage_tasks: list[dict[str, Any]] | None = None
