# shared/schemas/task.py

from typing import Optional, Dict, Any, Literal
from pydantic import BaseModel
from datetime import datetime


class TaskCreate(BaseModel):
    patent_number: str
    options: Dict[str, Any] = {}


class TaskOut(BaseModel):
    id: int
    patent_number: str
    status: str
    result: Optional[Dict[str, Any]] = None
    created_at: datetime


class CeleryTaskStatus(BaseModel):
    """Статус задачи Celery по task_id."""
    task_id: str
    status: Literal["PENDING", "STARTED", "RETRY", "FAILURE", "SUCCESS", "REVOKED"]
    state: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    progress: Optional[Dict[str, Any]] = None
    
    # Для задач парсинга
    query: Optional[str] = None
    source: Optional[str] = None
    current: Optional[int] = None
    total: Optional[int] = None
    saved_count: Optional[int] = None
    embedded_count: Optional[int] = None
    errors: Optional[list[str]] = None
    
    # Метаданные
    name: Optional[str] = None
    args: Optional[list] = None
    kwargs: Optional[Dict[str, Any]] = None
