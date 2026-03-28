"""API endpoints для Qwen чата."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from loguru import logger

from app.db.session import get_db
from app.services.qwen_service import get_qwen_service
from shared.schemas.paper import (
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

router = APIRouter(prefix="/qwen", tags=["qwen-chat"])


@router.get("/health", response_model=QwenHealthResponse)
async def health_check():
    """
    Проверка здоровья Qwen сервиса.

    Returns:
        Информация о статусе и доступности сервиса.
    """
    qwen_service = get_qwen_service()

    return QwenHealthResponse(
        status="ok" if qwen_service.is_available else "unavailable",
        model=qwen_service.model,
        available=qwen_service.is_available,
    )


@router.get("/config", response_model=QwenConfigResponse)
async def get_config():
    """
    Получить текущую конфигурацию Qwen сервиса.

    Returns:
        Конфигурация сервиса.
    """
    qwen_service = get_qwen_service()
    config = qwen_service.get_config()

    return QwenConfigResponse(**config)


@router.get("/stats")
async def get_stats():
    """
    Получить статистику Qwen сервиса.

    Возвращает информацию о загруженности сервиса и количестве запросов.

    **Важно:** Сервис использует один поток. При частых запросах
    применяется rate limiting для защиты от спама.

    Returns:
        Статистика сервиса.
    """
    qwen_service = get_qwen_service()
    stats = qwen_service.get_stats()

    return {
        **stats,
        "model": qwen_service.model,
        "is_available": qwen_service.is_available,
    }


@router.post("/config", response_model=QwenConfigResponse)
async def update_config(config_update: QwenConfigUpdateRequest):
    """
    Обновить конфигурацию Qwen сервиса.

    **Параметры:**
    - **model** - модель (qwen-coder, qwen-plus, qwen-max)
    - **thinking_enabled** - режим мышления
    - **search_enabled** - поиск в интернете
    - **auto_continue_enabled** - авто-продолжение
    - **max_continues** - макс. количество продолжений (1-20)
    """
    qwen_service = get_qwen_service()

    qwen_service.update_config(
        model=config_update.model,
        thinking_enabled=config_update.thinking_enabled,
        search_enabled=config_update.search_enabled,
        auto_continue_enabled=config_update.auto_continue_enabled,
        max_continues=config_update.max_continues,
    )

    return QwenConfigResponse(**qwen_service.get_config())


@router.post("/sessions", response_model=QwenSessionCreateResponse)
async def create_session(request: Optional[QwenSessionCreateRequest] = None):
    """
    Создать новую сессию чата.

    Args:
        request: Запрос с опциональным заголовком.

    Returns:
        Информация о созданной сессии.
    """
    qwen_service = get_qwen_service()

    if not qwen_service.is_available:
        raise HTTPException(
            status_code=503,
            detail="Qwen сервис недоступен. Проверьте настройку QWEN_TOKEN."
        )

    session_id = qwen_service.create_session()

    if not session_id:
        raise HTTPException(
            status_code=500,
            detail="Не удалось создать сессию"
        )

    title = request.title if request else "Новый чат"

    # Переименовываем сессию если указан заголовок
    if title != "Новый чат":
        qwen_service.rename_session(session_id, title)

    return QwenSessionCreateResponse(
        session_id=session_id,
        title=title,
    )


@router.get("/sessions", response_model=QwenSessionListResponse)
async def list_sessions():
    """
    Получить список всех сессий.

    Returns:
        Список сессий.
    """
    qwen_service = get_qwen_service()

    if not qwen_service.is_available:
        return QwenSessionListResponse(sessions=[])

    sessions_data = qwen_service.list_sessions()

    sessions = [
        QwenSessionInfo(
            session_id=s.get("id", s.get("session_id", "")),
            title=s.get("title", "Новый чат"),
            created_at=s.get("created_at"),
        )
        for s in sessions_data
    ]

    return QwenSessionListResponse(sessions=sessions)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """
    Получить информацию о сессии.

    Args:
        session_id: ID сессии.

    Returns:
        Информация о сессии с историей сообщений.
    """
    qwen_service = get_qwen_service()

    if not qwen_service.is_available:
        raise HTTPException(
            status_code=503,
            detail="Qwen сервис недоступен"
        )

    session_info = qwen_service.get_session_info(session_id)

    if not session_info:
        raise HTTPException(
            status_code=404,
            detail=f"Сессия {session_id} не найдена"
        )

    return session_info


@router.delete("/sessions/{session_id}", response_model=QwenDeleteResponse)
async def delete_session(session_id: str):
    """
    Удалить сессию.

    Args:
        session_id: ID сессии.

    Returns:
        Результат удаления.
    """
    qwen_service = get_qwen_service()

    if not qwen_service.is_available:
        raise HTTPException(
            status_code=503,
            detail="Qwen сервис недоступен"
        )

    success = qwen_service.delete_session(session_id)

    return QwenDeleteResponse(
        status="ok" if success else "error",
        deleted=success,
    )


@router.post("/sessions/{session_id}/rename", response_model=QwenRenameResponse)
async def rename_session(session_id: str, request: QwenRenameRequest):
    """
    Переименовать сессию.

    Args:
        session_id: ID сессии.
        request: Новый заголовок.

    Returns:
        Результат переименования.
    """
    qwen_service = get_qwen_service()

    if not qwen_service.is_available:
        raise HTTPException(
            status_code=503,
            detail="Qwen сервис недоступен"
        )

    success = qwen_service.rename_session(session_id, request.title)

    if not success:
        raise HTTPException(
            status_code=500,
            detail="Не удалось переименовать сессию"
        )

    return QwenRenameResponse(
        status="ok",
        title=request.title,
    )


@router.post("/messages", response_model=QwenMessageResponse)
async def send_message(request: QwenMessageRequest):
    """
    Отправить сообщение в Qwen чат.

    **Особенности:**
    - **Режим мышления** - анализ задачи перед ответом (thinking_enabled)
    - **Поиск в интернете** - поиск актуальной информации (search_enabled)
    - **Авто-продолжение** - автоматическое продолжение длинных ответов

    Args:
        request: Запрос с сообщением и параметрами.

    Returns:
        Ответ с текстом и метаданными.

    Example:
        POST /api/v1/qwen/messages
        {
            "message": "Напиши функцию Fibonacci на Python",
            "thinking_enabled": true,
            "search_enabled": false,
            "auto_continue": true
        }
    """
    qwen_service = get_qwen_service()

    if not qwen_service.is_available:
        return QwenMessageResponse(
            session_id="",
            message=request.message,
            response="",
            thinking="",
            thinking_enabled=request.thinking_enabled,
            search_enabled=request.search_enabled,
            error="Qwen сервис недоступен. Проверьте настройку QWEN_TOKEN.",
        )

    result = qwen_service.send_message(
        message=request.message,
        session_id=request.session_id,
        thinking_enabled=request.thinking_enabled,
        search_enabled=request.search_enabled,
        file_ids=request.file_ids,
        auto_continue=request.auto_continue,
    )

    return QwenMessageResponse(
        session_id=result.get("session_id", ""),
        message=request.message,
        response=result.get("response", ""),
        thinking=result.get("thinking", ""),
        thinking_enabled=result.get("thinking_enabled", request.thinking_enabled),
        search_enabled=result.get("search_enabled", request.search_enabled),
        message_id=result.get("message_id", 0),
        continue_count=result.get("continue_count", 0),
        can_continue=result.get("can_continue", False),
        auto_continue_performed=result.get("auto_continue_performed", False),
    )
