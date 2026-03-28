"""Общие схемы данных."""

from .task import TaskCreate, TaskOut
from .paper import (
    Paper,
    PaperCreate,
    PaperSearchRequest,
    PaperSearchResponse,
    QwenMessageRequest,
    QwenMessageResponse,
    QwenSessionCreateRequest,
    QwenSessionCreateResponse,
    QwenSessionListResponse,
    QwenSessionInfo,
    QwenRenameRequest,
    QwenRenameResponse,
    QwenDeleteResponse,
    QwenConfigResponse,
    QwenConfigUpdateRequest,
    QwenHealthResponse,
)

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
