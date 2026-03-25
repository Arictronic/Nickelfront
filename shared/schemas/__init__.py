"""Общие схемы данных."""

from .task import TaskCreate, TaskOut
from .paper import Paper, PaperCreate, PaperSearchRequest, PaperSearchResponse

__all__ = [
    "TaskCreate",
    "TaskOut",
    "Paper",
    "PaperCreate",
    "PaperSearchRequest",
    "PaperSearchResponse",
]
