"""Client-side helper for the shared Qwen Celery gateway."""

from __future__ import annotations

from typing import Any

from celery import Celery
from celery.result import AsyncResult
from loguru import logger

from app.core.config import settings


def _make_celery_client() -> Celery:
    return Celery(
        "qwen_gateway_client",
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
    )


def send_qwen_message_via_queue(
    *,
    message: str,
    session_id: str | None = None,
    thinking_enabled: bool = True,
    search_enabled: bool = False,
    file_ids: list[str] | None = None,
    auto_continue: bool | None = None,
    timeout: float = 120.0,
    purpose: str = "background",
) -> dict[str, Any]:
    """Queue a Qwen request and wait for the controlled Qwen worker result.

    This may be called from regular Celery parser/content/alloy workers. Celery normally
    warns against result.get() inside tasks, so disable_sync_subtasks=False is explicit:
    we intentionally use this as a bounded gateway to the Qwen slot pool.
    """
    client = _make_celery_client()
    wait_timeout = max(float(timeout), float(settings.QWEN_QUEUE_TIMEOUT))
    task: AsyncResult = client.send_task(
        "app.tasks.qwen.send_message",
        kwargs={
            "message": message,
            "session_id": session_id,
            "thinking_enabled": thinking_enabled,
            "search_enabled": search_enabled,
            "file_ids": file_ids or [],
            "auto_continue": auto_continue,
            "timeout": timeout,
            "purpose": purpose,
        },
        queue=settings.QWEN_QUEUE_NAME,
    )
    logger.info(
        "Qwen request queued: task_id={}, queue={}, purpose={}, session={}",
        task.id,
        settings.QWEN_QUEUE_NAME,
        purpose,
        (session_id[-6:] if session_id else "new"),
    )

    try:
        result = task.get(timeout=wait_timeout, propagate=True, disable_sync_subtasks=False)
    except Exception as exc:
        logger.exception("Qwen queued request failed: task_id={}, purpose={}", task.id, purpose)
        return {
            "error": f"Qwen queued request failed: {exc}",
            "response": "",
            "thinking": "",
            "task_id": task.id,
            "purpose": purpose,
        }

    if not isinstance(result, dict):
        return {
            "error": "Qwen queued request returned invalid payload",
            "response": "",
            "thinking": "",
            "task_id": task.id,
            "purpose": purpose,
        }
    result.setdefault("task_id", task.id)
    result.setdefault("purpose", purpose)
    result.setdefault("queued", True)
    return result
