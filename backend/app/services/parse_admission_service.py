"""Redis-backed admission control for root parser Celery tasks.

The parser limit must be enforced before a task becomes Celery ``active``.
Celery inspect sees active/reserved/scheduled tasks only after workers touch
messages, while a burst of HTTP requests can enqueue several root parse jobs
into Redis broker in the meantime. This module keeps a small Redis slot
registry for accepted root parse jobs and releases the slot from the root task
``finally`` block.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

from loguru import logger
from redis import Redis

from app.core.config import settings

ROOT_PARSE_TASK_NAMES = {
    "app.tasks.parse_tasks.parse_papers_task",
    "app.tasks.parse_tasks.parse_multiple_queries_task",
    "app.tasks.parse_tasks.parse_all_sources_task",
}

_KEY_PREFIX = "nickelfront:parse:admission"
_SLOTS_KEY = f"{_KEY_PREFIX}:slots"
_LOCK_KEY = f"{_KEY_PREFIX}:lock"
_TASK_KEY_PREFIX = f"{_KEY_PREFIX}:task"
_DEFAULT_SLOT_TTL_SECONDS = 6 * 60 * 60
_LOCK_TTL_SECONDS = 5


@dataclass(frozen=True)
class ParseAdmissionSlot:
    task_id: str
    task_name: str
    source: str
    query: str
    created_at_ms: int
    expires_at_ms: int
    occupied: int
    max_parallel: int
    reserved: bool = True


class ParseAdmissionError(RuntimeError):
    """Base admission-control error."""


class ParseAdmissionUnavailableError(ParseAdmissionError):
    """Raised when Redis is unavailable and safe admission is impossible."""


class ParseAdmissionLimitError(ParseAdmissionError):
    """Raised when the configured parse slot limit is already occupied."""

    def __init__(self, *, occupied: int, max_parallel: int):
        super().__init__(f"Достигнут лимит parse-задач: {occupied}/{max_parallel}")
        self.occupied = occupied
        self.max_parallel = max_parallel


def _slot_ttl_seconds() -> int:
    raw = os.getenv("NICKELFRONT_PARSE_ADMISSION_SLOT_TTL_SECONDS")
    try:
        value = int(str(raw).strip()) if raw is not None else _DEFAULT_SLOT_TTL_SECONDS
    except (TypeError, ValueError):
        value = _DEFAULT_SLOT_TTL_SECONDS
    return max(300, min(value, 24 * 60 * 60))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _task_key(task_id: str) -> str:
    return f"{_TASK_KEY_PREFIX}:{task_id}"


def _redis_client() -> Redis:
    return Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=1.5,
        socket_timeout=1.5,
    )


def _cleanup_expired_slots(client: Redis, now_ms: int | None = None) -> None:
    current_ms = now_ms or _now_ms()
    expired_ids = client.zrangebyscore(_SLOTS_KEY, "-inf", current_ms)
    if not expired_ids:
        return
    pipe = client.pipeline(transaction=False)
    for task_id in expired_ids:
        pipe.delete(_task_key(str(task_id)))
    pipe.zrem(_SLOTS_KEY, *expired_ids)
    pipe.execute()


def _extract_inspected_task_id(item: dict[str, Any]) -> str | None:
    request = item.get("request") if isinstance(item.get("request"), dict) else {}
    value = item.get("id") or request.get("id")
    return str(value).strip() if value else None


def _extract_inspected_task_name(item: dict[str, Any]) -> str:
    request = item.get("request") if isinstance(item.get("request"), dict) else {}
    return str(
        item.get("name")
        or item.get("type")
        or request.get("name")
        or request.get("type")
        or ""
    ).strip()


def _count_inspected_root_parse_tasks(exclude_task_ids: set[str] | None = None) -> int:
    """Best-effort count of active/reserved/scheduled root parse tasks.

    This is a safety net for tasks started before the Redis admission registry
    existed or for manually enqueued root parse jobs. It intentionally ignores
    downstream content/Qwen tasks.
    """
    exclude_task_ids = exclude_task_ids or set()
    try:
        from app.tasks.celery_app import celery_app

        inspector = celery_app.control.inspect(timeout=1.0)
        groups = [
            inspector.active() or {},
            inspector.reserved() or {},
            inspector.scheduled() or {},
        ]
    except Exception as exc:
        logger.debug("Parse admission Celery inspect fallback unavailable: {}", exc)
        return 0

    task_ids: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            continue
        for entries in group.values():
            for item in entries or []:
                if not isinstance(item, dict):
                    continue
                task_name = _extract_inspected_task_name(item)
                if task_name not in ROOT_PARSE_TASK_NAMES:
                    continue
                task_id = _extract_inspected_task_id(item)
                if task_id and task_id not in exclude_task_ids:
                    task_ids.add(task_id)
    return len(task_ids)


def _acquire_lock(client: Redis) -> str:
    token = uuid.uuid4().hex
    try:
        acquired = client.set(_LOCK_KEY, token, nx=True, ex=_LOCK_TTL_SECONDS)
    except Exception as exc:
        raise ParseAdmissionUnavailableError(f"Redis admission lock недоступен: {exc}") from exc
    if not acquired:
        raise ParseAdmissionUnavailableError("Контроль очереди парсинга занят, повторите запуск через несколько секунд")
    return token


def _release_lock(client: Redis, token: str) -> None:
    try:
        if client.get(_LOCK_KEY) == token:
            client.delete(_LOCK_KEY)
    except Exception:
        logger.debug("Failed to release parse admission lock", exc_info=True)


def reserve_parse_slot(
    *,
    max_parallel: int,
    task_name: str,
    source: str,
    query: str,
) -> ParseAdmissionSlot:
    """Reserve a slot and return the task_id that must be used in apply_async.

    The reservation is made before publishing the Celery message, so queued
    broker messages are counted immediately. Use ``release_parse_slot`` if
    publishing fails.
    """
    max_parallel = int(max_parallel or 0)
    task_id = uuid.uuid4().hex
    now_ms = _now_ms()
    ttl_seconds = _slot_ttl_seconds()
    expires_at_ms = now_ms + ttl_seconds * 1000

    if max_parallel <= 0:
        return ParseAdmissionSlot(
            task_id=task_id,
            task_name=task_name,
            source=source,
            query=query,
            created_at_ms=now_ms,
            expires_at_ms=expires_at_ms,
            occupied=0,
            max_parallel=max_parallel,
            reserved=False,
        )

    client = _redis_client()
    token = _acquire_lock(client)
    try:
        _cleanup_expired_slots(client, now_ms)
        slot_ids = {str(item) for item in client.zrange(_SLOTS_KEY, 0, -1)}
        inspected_count = _count_inspected_root_parse_tasks(exclude_task_ids=slot_ids)
        occupied = len(slot_ids) + inspected_count
        if occupied >= max_parallel:
            raise ParseAdmissionLimitError(occupied=occupied, max_parallel=max_parallel)

        slot_payload = {
            "task_id": task_id,
            "task_name": task_name,
            "source": str(source or ""),
            "query": str(query or "")[:500],
            "status": "queued",
            "created_at_ms": str(now_ms),
            "expires_at_ms": str(expires_at_ms),
            "ttl_seconds": str(ttl_seconds),
        }
        pipe = client.pipeline(transaction=True)
        pipe.hset(_task_key(task_id), mapping=slot_payload)
        pipe.expire(_task_key(task_id), ttl_seconds + 300)
        pipe.zadd(_SLOTS_KEY, {task_id: expires_at_ms})
        pipe.execute()

        return ParseAdmissionSlot(
            task_id=task_id,
            task_name=task_name,
            source=source,
            query=query,
            created_at_ms=now_ms,
            expires_at_ms=expires_at_ms,
            occupied=occupied + 1,
            max_parallel=max_parallel,
            reserved=True,
        )
    except ParseAdmissionError:
        raise
    except Exception as exc:
        raise ParseAdmissionUnavailableError(f"Redis admission registry недоступен: {exc}") from exc
    finally:
        _release_lock(client, token)


def refresh_parse_slot(task_id: str | None, *, ttl_seconds: int | None = None) -> bool:
    """Extend a root parse admission slot while the root task is still alive.

    This prevents a very long parse-all/root parse task from losing its Redis
    admission reservation before the task reaches its ``finally`` block. Safe to
    call for task ids that are not registered parse slots.
    """
    normalized = str(task_id or "").strip()
    if not normalized:
        return False

    ttl_value = max(300, min(int(ttl_seconds or _slot_ttl_seconds()), 24 * 60 * 60))
    now_ms = _now_ms()
    expires_at_ms = now_ms + ttl_value * 1000

    try:
        client = _redis_client()
        key = _task_key(normalized)
        if not client.exists(key):
            return False
        pipe = client.pipeline(transaction=False)
        pipe.hset(
            key,
            mapping={
                "status": "running",
                "last_seen_at_ms": str(now_ms),
                "expires_at_ms": str(expires_at_ms),
                "ttl_seconds": str(ttl_value),
            },
        )
        pipe.expire(key, ttl_value + 300)
        pipe.zadd(_SLOTS_KEY, {normalized: expires_at_ms})
        pipe.execute()
        return True
    except Exception as exc:
        logger.debug("Failed to refresh parse admission slot {}: {}", normalized, exc)
        return False


def release_parse_slot(task_id: str | None) -> bool:
    """Release a root parse slot. Safe to call for non-parse task IDs."""
    normalized = str(task_id or "").strip()
    if not normalized:
        return False
    try:
        client = _redis_client()
        pipe = client.pipeline(transaction=False)
        pipe.zrem(_SLOTS_KEY, normalized)
        pipe.delete(_task_key(normalized))
        result = pipe.execute()
        return bool(result and (result[0] or result[1]))
    except Exception as exc:
        logger.debug("Failed to release parse admission slot {}: {}", normalized, exc)
        return False


def clear_parse_admission_slots() -> int:
    """Clear all parser admission slots, used when admin purges Celery queues."""
    try:
        client = _redis_client()
        slot_ids = [str(item) for item in client.zrange(_SLOTS_KEY, 0, -1)]
        pipe = client.pipeline(transaction=False)
        for task_id in slot_ids:
            pipe.delete(_task_key(task_id))
        pipe.delete(_SLOTS_KEY)
        pipe.execute()
        return len(slot_ids)
    except Exception as exc:
        logger.debug("Failed to clear parse admission slots: {}", exc)
        return 0


def get_parse_admission_snapshot(max_parallel: int | None = None) -> dict[str, Any]:
    """Small diagnostic payload for API responses/dashboard logs."""
    max_value = int(max_parallel or 0)
    try:
        client = _redis_client()
        now_ms = _now_ms()
        _cleanup_expired_slots(client, now_ms)
        slot_ids = [str(item) for item in client.zrange(_SLOTS_KEY, 0, -1)]
        slots: list[dict[str, Any]] = []
        for task_id in slot_ids[:50]:
            raw = client.hgetall(_task_key(task_id)) or {}
            slots.append(
                {
                    "task_id": task_id,
                    "task_name": raw.get("task_name"),
                    "source": raw.get("source"),
                    "query": raw.get("query"),
                    "status": raw.get("status") or "queued",
                    "created_at_ms": _to_int(raw.get("created_at_ms")),
                    "expires_at_ms": _to_int(raw.get("expires_at_ms")),
                }
            )
        inspected_count = _count_inspected_root_parse_tasks(exclude_task_ids=set(slot_ids))
        occupied = len(slot_ids) + inspected_count
        return {
            "status": "ok",
            "max_parallel": max_value,
            "occupied": occupied,
            "available": max(0, max_value - occupied) if max_value > 0 else None,
            "redis_slots_count": len(slot_ids),
            "inspected_root_tasks_count": inspected_count,
            "slots": slots,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "max_parallel": max_value,
            "occupied": None,
            "available": None,
            "error": str(exc)[:500],
            "slots": [],
        }


def _to_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
