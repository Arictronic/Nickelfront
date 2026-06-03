"""API endpoints для Qwen чата."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user, require_admin_user
from app.services.qwen_client import get_qwen_client
from shared.schemas.auth import UserResponse
from shared.schemas.paper import (
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

router = APIRouter(prefix="/qwen", tags=["qwen-chat"])


def _qwen_unavailable_message(health: dict) -> str:
    reason = str(health.get("reason") or "").strip()
    base_url = str(health.get("base_url") or "").strip()
    details = f" Причина: {reason}." if reason else ""
    where = f" URL: {base_url}." if base_url else ""
    return f"Qwen сервис недоступен.{details}{where}"


def _qwen_error_status_code(result: dict) -> int:
    raw_code = result.get("status_code")
    if isinstance(raw_code, int) and 400 <= raw_code < 600:
        return raw_code

    code = str(result.get("error_code") or result.get("error") or "").lower()
    if "token" in code or "auth" in code or "unauthorized" in code:
        return 401
    if "rate" in code or "too_many" in code:
        return 429
    if "timeout" in code:
        return 504
    if "empty" in code or "validation" in code:
        return 422
    return 503


def _raise_qwen_result_error(result: dict) -> None:
    if not result.get("error"):
        return
    detail = {
        "error": result.get("error_code") or result.get("error"),
        "message": result.get("message") or result.get("detail") or result.get("error"),
        "session_id": result.get("session_id") or "",
        "status": result.get("status", "error"),
    }
    raise HTTPException(status_code=_qwen_error_status_code(result), detail=detail)


@router.get("/health", response_model=QwenHealthResponse)
async def health_check():
    """
    Проверка здоровья Qwen сервиса.

    Returns:
        Информация о статусе и доступности сервиса.
    """
    qwen_client = get_qwen_client()
    health = await asyncio.to_thread(qwen_client.health_status)

    return QwenHealthResponse(**health)


@router.get("/readiness")
async def get_readiness(
    _admin: UserResponse = Depends(require_admin_user),
):
    """Получить локальную диагностику готовности qwen_service без вызова внешнего Qwen."""
    qwen_client = get_qwen_client()
    return await asyncio.to_thread(qwen_client.get_readiness)


@router.post("/cache-maintenance")
async def run_cache_maintenance(
    dry_run: bool = True,
    prune_file_metadata: bool = True,
    prune_session_registry: bool = True,
    file_max_age_days: int | None = None,
    session_max_age_days: int | None = None,
    clear_file_metadata: bool = False,
    clear_session_registry: bool = False,
    _admin: UserResponse = Depends(require_admin_user),
):
    """Очистить/проверить локальные runtime-кэши qwen_service без вызова внешнего Qwen."""
    qwen_client = get_qwen_client()
    return await asyncio.to_thread(
        qwen_client.run_cache_maintenance,
        dry_run=dry_run,
        prune_file_metadata=prune_file_metadata,
        prune_session_registry=prune_session_registry,
        file_max_age_days=file_max_age_days,
        session_max_age_days=session_max_age_days,
        clear_file_metadata=clear_file_metadata,
        clear_session_registry=clear_session_registry,
    )


@router.get("/events")
async def get_qwen_events(
    limit: int = 50,
    event: str | None = None,
    status: str | None = None,
    _admin: UserResponse = Depends(require_admin_user),
):
    """Получить локальный журнал событий qwen_service без вызова внешнего Qwen."""
    qwen_client = get_qwen_client()
    return await asyncio.to_thread(qwen_client.get_event_journal, limit=limit, event=event, status=status)


@router.post("/events/clear")
async def clear_qwen_events(
    _admin: UserResponse = Depends(require_admin_user),
):
    """Очистить локальный журнал событий qwen_service."""
    qwen_client = get_qwen_client()
    return await asyncio.to_thread(qwen_client.clear_event_journal)


@router.get("/config", response_model=QwenConfigResponse)
async def get_config(
    _current_user: UserResponse = Depends(get_current_user),
):
    """
    Получить текущую конфигурацию Qwen сервиса.

    Returns:
        Конфигурация сервиса.
    """
    qwen_client = get_qwen_client()
    config = await asyncio.to_thread(qwen_client.get_config)

    return QwenConfigResponse(**config)


@router.get("/stats")
async def get_stats(
    _current_user: UserResponse = Depends(get_current_user),
):
    """
    Получить статистику Qwen сервиса.

    Возвращает информацию о загруженности сервиса и количестве запросов.

    **Важно:** Сервис использует один поток. При частых запросах
    применяется rate limiting для защиты от спама.

    Returns:
        Статистика сервиса.
    """
    qwen_client = get_qwen_client()
    return await asyncio.to_thread(qwen_client.get_stats)


@router.post("/config", response_model=QwenConfigResponse)
async def update_config(
    config_update: QwenConfigUpdateRequest,
    _admin: UserResponse = Depends(require_admin_user),
):
    """
    Обновить конфигурацию Qwen сервиса.

    **Параметры:**
    - **model** - модель (qwen-coder, qwen-plus, qwen-max)
    - **thinking_enabled** - режим мышления
    - **search_enabled** - поиск в интернете
    - **auto_continue_enabled** - авто-продолжение
    - **max_continues** - макс. количество продолжений (1-20)
    """
    qwen_client = get_qwen_client()

    updated = await asyncio.to_thread(
        qwen_client.update_config,
        model=config_update.model,
        thinking_enabled=config_update.thinking_enabled,
        search_enabled=config_update.search_enabled,
        auto_continue_enabled=config_update.auto_continue_enabled,
        max_continues=config_update.max_continues,
        stream_retries=config_update.stream_retries,
        history_recovery_attempts=config_update.history_recovery_attempts,
        history_recovery_interval_sec=config_update.history_recovery_interval_sec,
        file_metadata_cache_max_age_days=config_update.file_metadata_cache_max_age_days,
        session_registry_cache_max_age_days=config_update.session_registry_cache_max_age_days,
    )

    return QwenConfigResponse(**updated)


@router.post("/sessions", response_model=QwenSessionCreateResponse)
async def create_session(
    request: QwenSessionCreateRequest | None = None,
    _current_user: UserResponse = Depends(require_admin_user),
):
    """
    Создать новую сессию чата.

    Args:
        request: Запрос с опциональным заголовком.

    Returns:
        Информация о созданной сессии.
    """
    qwen_client = get_qwen_client()
    health = await asyncio.to_thread(qwen_client.health_status)

    if not health.get("available"):
        raise HTTPException(
            status_code=503,
            detail=_qwen_unavailable_message(health),
        )

    session_id = await asyncio.to_thread(qwen_client.create_session, request.title if request else None)

    if not session_id:
        raise HTTPException(
            status_code=500,
            detail="Не удалось создать сессию"
        )

    title = request.title if request else "Новый чат"


    return QwenSessionCreateResponse(
        session_id=session_id,
        title=title,
    )


@router.get("/sessions", response_model=QwenSessionListResponse)
async def list_sessions(
    _current_user: UserResponse = Depends(get_current_user),
):
    """
    Получить список всех сессий.

    Returns:
        Список сессий.
    """
    qwen_client = get_qwen_client()

    if not await asyncio.to_thread(qwen_client.is_available):
        return QwenSessionListResponse(sessions=[])

    sessions_data = await asyncio.to_thread(qwen_client.list_sessions)

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
async def get_session(
    session_id: str,
    _current_user: UserResponse = Depends(get_current_user),
):
    """
    Получить информацию о сессии.

    Args:
        session_id: ID сессии.

    Returns:
        Информация о сессии с историей сообщений.
    """
    qwen_client = get_qwen_client()

    if not await asyncio.to_thread(qwen_client.is_available):
        raise HTTPException(
            status_code=503,
            detail="Qwen сервис недоступен",
        )

    session_info = await asyncio.to_thread(qwen_client.get_session_info, session_id)

    if not session_info:
        raise HTTPException(
            status_code=404,
            detail=f"Сессия {session_id} не найдена"
        )

    return session_info


@router.delete("/sessions/{session_id}", response_model=QwenDeleteResponse)
async def delete_session(
    session_id: str,
    _current_user: UserResponse = Depends(require_admin_user),
):
    """
    Удалить сессию.

    Args:
        session_id: ID сессии.

    Returns:
        Результат удаления.
    """
    qwen_client = get_qwen_client()

    if not await asyncio.to_thread(qwen_client.is_available):
        raise HTTPException(
            status_code=503,
            detail="Qwen сервис недоступен",
        )

    success = await asyncio.to_thread(qwen_client.delete_session, session_id)

    return QwenDeleteResponse(
        status="ok" if success else "error",
        deleted=success,
    )


@router.post("/sessions/{session_id}/rename", response_model=QwenRenameResponse)
async def rename_session(
    session_id: str,
    request: QwenRenameRequest,
    _current_user: UserResponse = Depends(require_admin_user),
):
    """
    Переименовать сессию.

    Args:
        session_id: ID сессии.
        request: Новый заголовок.

    Returns:
        Результат переименования.
    """
    qwen_client = get_qwen_client()

    if not await asyncio.to_thread(qwen_client.is_available):
        raise HTTPException(
            status_code=503,
            detail="Qwen сервис недоступен",
        )

    success = await asyncio.to_thread(qwen_client.rename_session, session_id, request.title)

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
async def send_message(
    request: QwenMessageRequest,
    _current_user: UserResponse = Depends(require_admin_user),
):
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
    qwen_client = get_qwen_client()
    health = await asyncio.to_thread(qwen_client.health_status)

    if not health.get("available"):
        raise HTTPException(
            status_code=503,
            detail={
                "error": "qwen_service_unavailable",
                "message": _qwen_unavailable_message(health),
                "health": health,
            },
        )

    result = await asyncio.to_thread(
        qwen_client.send_message,
        message=request.message,
        session_id=request.session_id,
        thinking_enabled=request.thinking_enabled,
        search_enabled=request.search_enabled,
        file_ids=request.file_ids,
        auto_continue=request.auto_continue,
    )

    _raise_qwen_result_error(result)

    return QwenMessageResponse(
        status=result.get("status", "ok"),
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
        task_id=result.get("task_id"),
        queued=result.get("queued"),
        error_code=result.get("error_code"),
        status_code=result.get("status_code"),
        error=result.get("error"),
    )
