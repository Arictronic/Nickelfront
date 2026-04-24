"""Общие схемы данных."""

from .paper import (
    Paper,
    PaperCreate,
    PaperSearchRequest,
    PaperSearchResponse,
    QwenConfigResponse,
    QwenConfigUpdateRequest,
    QwenDeleteResponse,
    QwenHealthResponse,
    QwenMessageRequest,
    QwenMessageResponse,
    QwenRenameRequest,
    QwenRenameResponse,
    QwenSessionCreateRequest,
    QwenSessionCreateResponse,
    QwenSessionInfo,
    QwenSessionListResponse,
)
from .task import TaskCreate, TaskOut

__all__ = [
    "TaskCreate",
    "TaskOut",
    "Paper",
    "PaperCreate",
    "PaperSearchRequest",
    "PaperSearchResponse",
    "QwenMessageRequest",
    "QwenMessageResponse",
    "QwenSessionCreateRequest",
    "QwenSessionCreateResponse",
    "QwenSessionListResponse",
    "QwenSessionInfo",
    "QwenRenameRequest",
    "QwenRenameResponse",
    "QwenDeleteResponse",
    "QwenConfigResponse",
    "QwenConfigUpdateRequest",
    "QwenHealthResponse",
]
