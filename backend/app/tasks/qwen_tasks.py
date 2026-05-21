"""Shared Qwen Celery gateway tasks.

All non-interactive background Qwen consumers should go through this queue:
parser translations, PDF/content enrichment, RAG background calls, alloy analysis.
The queue can be served by up to QWEN_QUEUE_WORKERS workers, matching the Qwen API
parallel session limit for one API key.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from app.core.config import settings
from app.services.qwen_client import QwenServiceClient
from app.tasks.celery_app import celery_app


def _qwen_queue_rate_limit() -> str | None:
    """Return Celery rate_limit for Qwen gateway tasks.

    For parallel Qwen workers the hard limiter should be the number of qwen worker
    processes, not an accidental 300/h throttle. Set QWEN_QUEUE_TASK_RATE_LIMIT to
    off/none/0/empty to disable Celery rate limiting.
    """
    raw = settings.QWEN_QUEUE_TASK_RATE_LIMIT
    if raw is None:
        return None
    value = str(raw).strip()
    if not value or value.lower() in {"0", "off", "none", "false", "no", "unlimited"}:
        return None
    return value


@celery_app.task(
    bind=True,
    name="app.tasks.qwen.send_message",
    rate_limit=_qwen_queue_rate_limit(),
    acks_late=True,
    soft_time_limit=int(max(60, settings.QWEN_QUEUE_TIMEOUT + 30)),
    time_limit=int(max(90, settings.QWEN_QUEUE_TIMEOUT + 90)),
)
def qwen_send_message_task(
    self,
    message: str,
    session_id: str | None = None,
    thinking_enabled: bool = True,
    search_enabled: bool = False,
    file_ids: list[str] | None = None,
    auto_continue: bool | None = None,
    timeout: float = 120.0,
    purpose: str = "background",
) -> dict[str, Any]:
    """Send one message to qwen_service from the controlled Qwen queue."""
    task_id = getattr(getattr(self, "request", None), "id", None)
    logger.info(
        "Qwen queue task started: task_id={}, purpose={}, session={}, thinking={}, search={}",
        task_id,
        purpose,
        (session_id[-6:] if session_id else "new"),
        thinking_enabled,
        search_enabled,
    )

    client = QwenServiceClient(queue_enabled=False, timeout=timeout)
    result = client.send_message(
        message=message,
        session_id=session_id,
        thinking_enabled=thinking_enabled,
        search_enabled=search_enabled,
        file_ids=file_ids or [],
        auto_continue=auto_continue,
        timeout=timeout,
    )

    # qwen_service returns the original prompt in the `message` field. For PDF/page
    # processing this can be tens of thousands of characters and then Celery stores it
    # in Redis result backend and prints part of it in `Task ... succeeded` logs. The
    # caller only needs the generated response/thinking/session ids, so keep only a
    # small diagnostic preview instead of the full prompt.
    if isinstance(result, dict):
        original_prompt = result.pop("message", None)
        if isinstance(original_prompt, str):
            result["prompt_preview"] = original_prompt[:240]
            result["prompt_length"] = len(original_prompt)

    result.setdefault("task_id", task_id)
    result.setdefault("purpose", purpose)
    return result
