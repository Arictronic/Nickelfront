

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
    status: Literal["PENDING", "STARTED", "RETRY", "FAILURE", "SUCCESS", "REVOKED"]
    state: str | None = None
    result: dict[str, Any] | None = None
    progress: dict[str, Any] | None = None


    query: str | None = None
    source: str | None = None
    current: int | None = None
    total: int | None = None
    saved_count: int | None = None
    embedded_count: int | None = None
    errors: list[str] | None = None


    name: str | None = None
    args: list | None = None
    kwargs: dict[str, Any] | None = None
