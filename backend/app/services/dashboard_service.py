"""Operational dashboard aggregation and health checks.

The dashboard must not guess critical state from the browser.  This service keeps
DB metrics, parser-job history and service health checks in one backend place so
`/dashboard` can stay a UI composition layer.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import redis.asyncio as redis
from loguru import logger
from sqlalchemy import String, and_, case, cast, exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.paper import Paper as PaperModel
from app.db.models.paper_content_part import PaperContentPart
from app.services.parse_job_history import add_parse_job, list_parse_jobs, update_parse_job
from app.services.system_settings_service import SystemSettingsService

PAPER_SOURCES = (
    "CORE",
    "arXiv",
    "OpenAlex",
    "Crossref",
    "EuropePMC",
    "CyberLeninka",
    "eLibrary",
    "Rospatent",
    "FreePatent",
    "GooglePatents",
    "PATENTSCOPE",
)

API_SOURCES = {"CORE", "arXiv", "OpenAlex", "Crossref", "EuropePMC"}
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled", "expired"}
ERROR_STATUSES = {
    "failed",
    "pdf_download_failed",
    "markdown_failed",
    "keywords_failed",
    "qwen_auth_failed",
}
CONTENT_QUEUE_STATUSES = {
    "queued_for_content_processing",
    "processing_content",
    "pdf_pending",
    "downloading_pdf",
    "extracting_pdf_text",
    "formatting_markdown",
    "digitizing_file",
    "analyzing_ru",
    "extracting_keywords",
    "indexing_vector",
}
READY_CONTENT_STATUSES = {"ready", "ready_with_fallback"}

OVERVIEW_CACHE_TTL_SECONDS = 20
_OVERVIEW_CACHE: dict[tuple[int], tuple[float, dict[str, Any]]] = {}

DASHBOARD_ACTIONS: dict[str, dict[str, str]] = {
    "process_pdf_backlog": {
        "title": "Поставить очередь PDF/контента",
        "task": "app.tasks.dashboard.process_pdf_backlog",
        "source": "dashboard",
        "query": "обработка очереди PDF/контента",
    },
    "retry_failed_content": {
        "title": "Повторить задачи контента с ошибками",
        "task": "app.tasks.dashboard.retry_failed_content",
        "source": "dashboard",
        "query": "повтор ошибок обработки контента",
    },
    "rebuild_embeddings": {
        "title": "Пересобрать недостающие эмбеддинги",
        "task": "app.tasks.dashboard.rebuild_embeddings",
        "source": "dashboard",
        "query": "пересборка недостающих эмбеддингов",
    },
    "reindex_vector_store": {
        "title": "Синхронизировать Vector index",
        "task": "app.tasks.dashboard.reindex_vector_store",
        "source": "dashboard",
        "query": "синхронизация Vector index со всеми эмбеддингами из PostgreSQL",
    },
    "rebuild_vector_store_full": {
        "title": "Полностью пересобрать Vector index",
        "task": "app.tasks.dashboard.rebuild_vector_store_full",
        "source": "dashboard",
        "query": "полная пересборка Vector index из PostgreSQL",
    },
    "rebuild_rag_index": {
        "title": "Полностью пересобрать RAG/Chroma",
        "task": "app.tasks.dashboard.rebuild_rag_index",
        "source": "dashboard",
        "query": "полная пересборка RAG/Chroma из контента статей",
    },
    "rerun_source": {
        "title": "Запустить источник заново",
        "task": "app.tasks.parse_tasks.parse_papers_task",
        "source": "all",
        "query": "повторный запуск источника",
    },
}


def invalidate_dashboard_overview_cache() -> None:
    _OVERVIEW_CACHE.clear()







def _text_present_expr(column):
    return and_(column.isnot(None), func.length(func.trim(cast(column, String))) > 0)


def _json_present_expr(column):
    text_value = func.trim(cast(column, String))
    return and_(
        column.isnot(None),
        func.length(text_value) > 2,
        text_value.notin_(["[]", "{}", "null", "NULL", ""]),
    )


def _count_if(expr):
    return func.coalesce(func.sum(case((expr, 1), else_=0)), 0)


def _percent(part: int | float, total: int | float) -> float:
    if total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, float(part) / float(total) * 100)), 1)


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        if value in (None, ""):
            return fallback
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return fallback
        parsed = float(value)
        return parsed if parsed == parsed else fallback
    except (TypeError, ValueError):
        return fallback


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_present(mapping: dict[str, Any] | None, *keys: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None



def _is_placeholder_job_id(task_id: Any) -> bool:
    raw = str(task_id or "").strip().lower()
    return raw.startswith(("test-", "test_", "mock-", "mock_", "demo-", "demo_", "sample-", "sample_"))

def _ts_ms_to_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, str) and "T" in value:
        return value
    timestamp = _safe_float(value, 0.0)
    if timestamp <= 0:
        return None

    if timestamp > 10_000_000_000:
        timestamp = timestamp / 1000.0
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    except Exception:
        return None


def _local_day_bounds(timezone_offset_minutes: int) -> tuple[datetime, datetime]:

    offset = timedelta(minutes=timezone_offset_minutes)
    now_local = datetime.now(timezone.utc) + offset
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local - offset, end_local - offset







def _job_meta(job: dict[str, Any]) -> dict[str, Any]:
    celery_status = _as_dict(job.get("celeryStatus"))
    progress = _as_dict(celery_status.get("progress"))
    result = _as_dict(celery_status.get("result"))
    info = _as_dict(celery_status.get("info"))
    return {**progress, **info, **result, **celery_status}


def _result_payload_from_task_info(task_info: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(task_info, dict):
        return None
    result = task_info.get("result")
    if not isinstance(result, dict) and isinstance(task_info.get("info"), dict):
        result = task_info.get("info")
    return result if isinstance(result, dict) else None


def _parse_job_status_from_celery(celery_status: str | None) -> str:
    if celery_status == "SUCCESS":
        return "completed"
    if celery_status == "FAILURE":
        return "failed"
    if celery_status == "REVOKED":
        return "cancelled"
    return "in_progress"


def _job_status(job: dict[str, Any]) -> str:
    status = str(job.get("status") or "").strip()
    celery = _as_dict(job.get("celeryStatus"))
    celery_status = str(celery.get("status") or "").strip()
    if celery_status in {"SUCCESS", "FAILURE", "REVOKED"}:
        return _parse_job_status_from_celery(celery_status)
    if status in {"in_progress", *TERMINAL_JOB_STATUSES}:
        return status
    return "in_progress"


def _job_error(job: dict[str, Any]) -> str | None:
    meta = _job_meta(job)
    for key in ("error", "exc_message", "traceback"):
        value = meta.get(key)
        if value:
            return str(value)[:600]
    errors = meta.get("errors")
    if isinstance(errors, list) and errors:
        return str(errors[0])[:600]
    return None


def _job_counter(job: dict[str, Any], *keys: str) -> int:
    meta = _job_meta(job)
    for key in keys:
        if key in job and job.get(key) is not None:
            return max(0, _safe_int(job.get(key), 0))
        if key in meta and meta.get(key) is not None:
            return max(0, _safe_int(meta.get(key), 0))
    return 0


def _job_progress_percent(job: dict[str, Any]) -> int:
    status = _job_status(job)
    if status == "completed":
        return 100
    if status in {"failed", "cancelled", "expired"}:
        return 0

    meta = _job_meta(job)
    explicit = _first_present(meta, "percent", "progress_percent")
    if explicit is not None:
        return int(_percent(_safe_float(explicit), 100))

    current = _safe_float(_first_present(meta, "current"), 0.0)
    total = _safe_float(_first_present(meta, "total"), 0.0)
    if total > 0:
        return int(_percent(current, total))

    current_query = _safe_float(_first_present(meta, "current_query"), 0.0)
    total_queries = _safe_float(_first_present(meta, "total_queries"), 0.0)
    if total_queries > 0:
        return int(_percent(current_query, total_queries))

    current_source = _safe_float(_first_present(meta, "current_source"), 0.0)
    total_sources = _safe_float(_first_present(meta, "total_sources"), 0.0)
    if total_sources > 0:
        return int(_percent(current_source, total_sources))

    saved = _job_counter(job, "savedCount", "saved_count", "total_saved")
    if saved > 0:
        return min(95, 10 + saved * 5)
    return 8


def _build_parse_job_patch(task_id: str, task_info: dict[str, Any] | None) -> dict[str, Any]:
    result = _result_payload_from_task_info(task_info)
    celery_status = str((task_info or {}).get("status") or "UNKNOWN")
    now_ms = int(time.time() * 1000)

    def result_value(*keys: str) -> Any:
        return _first_present(result, *keys)

    celery_payload = {
        "task_id": task_id,
        "status": celery_status,
        "state": (task_info or {}).get("state"),
        "result": result,
        "progress": result.get("progress") if isinstance(result, dict) else None,
        "query": result.get("query") if isinstance(result, dict) else None,
        "source": result.get("source") if isinstance(result, dict) else None,
        "current": result_value("current"),
        "total": result_value("total"),
        "saved_count": result_value("saved_count", "total_saved"),
        "updated_count": result_value("updated_count", "total_updated"),
        "duplicate_count": result_value("duplicate_count", "total_duplicates"),
        "embedded_count": result_value("embedded_count"),
        "content_queued_count": result_value("content_queued_count", "total_content_queued"),
        "content_skipped_count": result_value("content_skipped_count", "total_content_skipped"),
        "errors": result.get("errors") if isinstance(result, dict) else None,
        "name": (task_info or {}).get("name"),
        "args": (task_info or {}).get("args"),
        "kwargs": (task_info or {}).get("kwargs"),
    }
    patch: dict[str, Any] = {
        "status": _parse_job_status_from_celery(celery_status),
        "lastPolledAt": now_ms,
        "celeryStatus": celery_payload,
    }

    counter_map = {
        "savedCount": ("saved_count", "total_saved"),
        "updatedCount": ("updated_count", "total_updated"),
        "duplicateCount": ("duplicate_count", "total_duplicates"),
        "contentQueuedCount": ("content_queued_count", "total_content_queued"),
        "contentSkippedCount": ("content_skipped_count", "total_content_skipped"),
    }
    for field, keys in counter_map.items():
        value = result_value(*keys)
        if value is not None:
            patch[field] = value

    if patch["status"] != "in_progress" or any(field in patch for field in counter_map):
        patch["lastCountChangeAt"] = now_ms
    return patch


async def _sync_job_from_celery(job: dict[str, Any]) -> dict[str, Any]:
    task_id = str(job.get("jobId") or "")
    if not task_id or _job_status(job) != "in_progress":
        return job
    try:
        from app.tasks.tasks import get_celery_task_status

        task_info = await asyncio.to_thread(get_celery_task_status, task_id)
        if not task_info:
            return job
        patch = _build_parse_job_patch(task_id, task_info)
        synced = await asyncio.to_thread(update_parse_job, task_id, patch)
        return synced or {**job, **patch}
    except Exception as exc:
        logger.warning("Dashboard failed to sync parse job {} from Celery: {}", task_id, exc)
        return job


def _normalize_dashboard_job(job: dict[str, Any]) -> dict[str, Any]:
    meta = _job_meta(job)
    started_at = _safe_int(job.get("startedAt"), int(time.time() * 1000))
    last_update = _safe_int(job.get("lastCountChangeAt"), started_at)
    now_ms = int(time.time() * 1000)
    finished_at = last_update if _job_status(job) in TERMINAL_JOB_STATUSES else None
    duration_sec = max(0, int(((finished_at or now_ms) - started_at) / 1000))
    return {
        "job_id": str(job.get("jobId") or ""),
        "source": str(job.get("source") or meta.get("source") or "all"),
        "query": str(job.get("query") or meta.get("query") or ""),
        "status": _job_status(job),
        "celery_status": _as_dict(job.get("celeryStatus")),
        "progress_percent": _job_progress_percent(job),
        "saved": _job_counter(job, "savedCount", "saved_count", "total_saved"),
        "updated": _job_counter(job, "updatedCount", "updated_count", "total_updated"),
        "duplicates": _job_counter(job, "duplicateCount", "duplicate_count", "total_duplicates"),
        "content_queued": _job_counter(job, "contentQueuedCount", "content_queued_count", "total_content_queued"),
        "content_skipped": _job_counter(job, "contentSkippedCount", "content_skipped_count", "total_content_skipped"),
        "current": _safe_int(_first_present(meta, "current"), 0),
        "total": _safe_int(_first_present(meta, "total"), 0),
        "stage": str(_first_present(meta, "stage_label", "stage", "type") or ""),
        "started_at": _ts_ms_to_iso(started_at),
        "finished_at": _ts_ms_to_iso(finished_at),
        "duration_sec": duration_sec,
        "error": _job_error(job),

        "jobId": str(job.get("jobId") or ""),
        "startedAt": started_at,
        "initialCount": _safe_int(job.get("initialCount"), 0),
        "lastObservedCount": _safe_int(job.get("lastObservedCount"), _safe_int(job.get("initialCount"), 0)),
        "lastCountChangeAt": last_update,
        "savedCount": _job_counter(job, "savedCount", "saved_count", "total_saved"),
        "updatedCount": _job_counter(job, "updatedCount", "updated_count", "total_updated"),
        "duplicateCount": _job_counter(job, "duplicateCount", "duplicate_count", "total_duplicates"),
        "contentQueuedCount": _job_counter(job, "contentQueuedCount", "content_queued_count", "total_content_queued"),
        "contentSkippedCount": _job_counter(job, "contentSkippedCount", "content_skipped_count", "total_content_skipped"),
        "lastPolledAt": _safe_int(job.get("lastPolledAt"), 0) or None,
    }


async def get_dashboard_jobs(limit: int = 20) -> dict[str, Any]:
    """Return parse jobs normalized for the dashboard cards."""
    raw_jobs = await asyncio.to_thread(list_parse_jobs, max(limit * 3, limit))
    raw_jobs = [job for job in raw_jobs if not _is_placeholder_job_id(job.get("jobId"))]
    synced_jobs = await asyncio.gather(*[_sync_job_from_celery(job) for job in raw_jobs[:limit]]) if raw_jobs else []
    normalized = [_normalize_dashboard_job(job) for job in synced_jobs]
    return {
        "jobs": normalized[:limit],
        "summary": {
            "active": sum(1 for job in normalized if job["status"] == "in_progress"),
            "queued": sum(_safe_int(job.get("content_queued"), 0) for job in normalized),
            "failed_recent": sum(1 for job in normalized[:20] if job["status"] == "failed"),
        },
    }







async def _check_database_status(db: AsyncSession) -> dict[str, Any]:
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "online", "label": "PostgreSQL"}
    except Exception as exc:
        logger.warning("Dashboard PostgreSQL health check failed: {}", exc)
        return {"status": "offline", "label": "PostgreSQL", "error": str(exc)[:300]}


async def _check_redis_status() -> dict[str, Any]:
    client = None
    try:
        client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=1.2, socket_timeout=1.2)
        await client.ping()
        info = await client.info(section="memory")
        return {
            "status": "online",
            "label": "Redis",
            "memory": info.get("used_memory_human") if isinstance(info, dict) else None,
        }
    except Exception as exc:
        logger.warning("Dashboard Redis health check failed: {}", exc)
        return {"status": "offline", "label": "Redis", "error": str(exc)[:300]}
    finally:
        if client is not None:
            await client.aclose()


def _inspect_celery() -> dict[str, Any]:
    try:
        from app.tasks.celery_app import celery_app

        inspector = celery_app.control.inspect(timeout=1.0)
        stats = inspector.stats() or {}
        active = inspector.active() or {}
        reserved = inspector.reserved() or {}
        scheduled = inspector.scheduled() or {}
        worker_count = len(stats)
        active_count = sum(len(items or []) for items in active.values())
        reserved_count = sum(len(items or []) for items in reserved.values())
        scheduled_count = sum(len(items or []) for items in scheduled.values())
        queued_count = reserved_count + scheduled_count
        queues: dict[str, int] = {}
        for worker_name, entries in reserved.items():
            queues[f"{worker_name}:reserved"] = len(entries or [])
        for worker_name, entries in scheduled.items():
            queues[f"{worker_name}:scheduled"] = len(entries or [])
        if worker_count > 0:
            status = "online"
            reason = None
        else:




            status = "warning"
            reason = "worker не ответил на inspect; возможно занят или не запущен"
        return {
            "status": status,
            "label": "Celery",
            "workers": worker_count,
            "active": active_count,
            "queued": queued_count,
            "reserved": reserved_count,
            "scheduled": scheduled_count,
            "queues": queues,
            "reason": reason,
        }
    except Exception as exc:
        logger.warning("Dashboard Celery inspect failed: {}", exc)
        return {"status": "unknown", "label": "Celery", "workers": 0, "active": 0, "queued": 0, "error": str(exc)[:300]}


async def _check_qwen_status() -> dict[str, Any]:
    try:
        from app.services.qwen_service import get_qwen_service

        health = await asyncio.wait_for(asyncio.to_thread(get_qwen_service().health_status), timeout=4.0)
        available = bool(health.get("available"))
        has_token = health.get("has_token")
        token_present = bool(settings.QWEN_TOKEN or settings.QWEN_API_KEY)
        status = "online" if available else ("warning" if token_present or has_token is False else "offline")
        return {
            "status": status,
            "label": "Qwen",
            "model": health.get("model") or settings.QWEN_MODEL,
            "base_url": health.get("base_url"),
            "available": available,
            "has_token": has_token if has_token is not None else token_present,
            "reason": health.get("reason"),
        }
    except asyncio.TimeoutError:
        return {"status": "offline", "label": "Qwen", "model": settings.QWEN_MODEL, "reason": "Qwen health timeout"}
    except Exception as exc:
        logger.warning("Dashboard Qwen health check failed: {}", exc)
        return {"status": "unknown", "label": "Qwen", "model": settings.QWEN_MODEL, "reason": str(exc)[:300]}


async def _check_vector_status(total_papers: int) -> dict[str, Any]:
    try:
        from app.services.vector_service import get_vector_service

        stats = await asyncio.wait_for(asyncio.to_thread(get_vector_service().get_stats), timeout=4.0)
        count = _safe_int(stats.get("count"), 0)
        available = bool(stats.get("available"))



        status = "online" if available else "offline"
        return {
            "status": status,
            "label": "Vector",
            "count": count,
            "indexed": count,
            "collection": stats.get("collection"),
            "path": stats.get("persist_directory"),
            "available": available,
        }
    except asyncio.TimeoutError:
        return {"status": "offline", "label": "Vector", "count": 0, "indexed": 0, "reason": "Vector stats timeout"}
    except Exception as exc:
        logger.warning("Dashboard vector health check failed: {}", exc)
        return {"status": "unknown", "label": "Vector", "count": 0, "indexed": 0, "reason": str(exc)[:300]}


async def _check_rag_status(total_papers: int) -> dict[str, Any]:
    try:
        from app.services.rag_vector_store import get_rag_vector_store

        stats = await asyncio.wait_for(asyncio.to_thread(get_rag_vector_store().get_stats), timeout=4.0)
        count = _safe_int(stats.get("total_documents"), 0)
        path = stats.get("persist_directory") or settings.CHROMA_DB_PATH
        path_exists = Path(settings.resolve_path(str(path))).exists() if path else False


        status = "online"
        return {
            "status": status,
            "label": "RAG/Chroma",
            "count": count,
            "indexed": count,
            "collection": stats.get("collection_name"),
            "path": path,
        }
    except asyncio.TimeoutError:
        return {"status": "offline", "label": "RAG/Chroma", "count": 0, "indexed": 0, "reason": "RAG stats timeout"}
    except Exception as exc:
        logger.warning("Dashboard RAG health check failed: {}", exc)
        return {"status": "unknown", "label": "RAG/Chroma", "count": 0, "indexed": 0, "reason": str(exc)[:300]}


async def _build_services(db: AsyncSession, total_papers: int) -> dict[str, dict[str, Any]]:
    database, redis_status, celery, qwen, vector, rag = await asyncio.gather(
        _check_database_status(db),
        _check_redis_status(),
        asyncio.to_thread(_inspect_celery),
        _check_qwen_status(),
        _check_vector_status(total_papers),
        _check_rag_status(total_papers),
    )
    return {
        "backend": {"status": "online", "label": "FastAPI"},
        "database": database,
        "redis": redis_status,
        "celery": celery,
        "qwen": qwen,
        "vector": vector,
        "rag": rag,
    }


async def _get_vector_indexed_paper_ids() -> set[int]:
    try:
        from app.services.vector_service import get_vector_service

        return await asyncio.wait_for(asyncio.to_thread(get_vector_service().get_indexed_paper_ids), timeout=8.0)
    except Exception as exc:
        logger.warning("Dashboard could not read Vector indexed paper ids: {}", exc)
        return set()


async def _get_rag_indexed_paper_ids() -> set[int]:
    try:
        from app.services.rag_vector_store import get_rag_vector_store

        return await asyncio.wait_for(asyncio.to_thread(get_rag_vector_store().get_indexed_paper_ids), timeout=8.0)
    except Exception as exc:
        logger.warning("Dashboard could not read RAG indexed paper ids: {}", exc)
        return set()


async def _select_paper_ids(db: AsyncSession, expr) -> set[int]:
    rows = (await db.execute(select(PaperModel.id).where(expr))).scalars().all()
    return {int(value) for value in rows if value is not None}







def _source_success_rate(source: str, jobs: list[dict[str, Any]]) -> dict[str, Any]:
    source_jobs = [job for job in jobs if str(job.get("source") or "") == source]
    terminal = [job for job in source_jobs if _job_status(job) in TERMINAL_JOB_STATUSES]
    if not terminal:
        return {"success_rate": None, "error_rate": None, "last_duration_sec": None}
    success = sum(1 for job in terminal if _job_status(job) == "completed")
    failed = sum(1 for job in terminal if _job_status(job) == "failed")
    latest = terminal[0]
    started_at = _safe_int(latest.get("startedAt"), 0)
    finished_at = _safe_int(latest.get("lastCountChangeAt"), started_at)
    duration = int(max(0, finished_at - started_at) / 1000) if started_at else None
    return {
        "success_rate": round(success / len(terminal) * 100, 1),
        "error_rate": round(failed / len(terminal) * 100, 1),
        "last_duration_sec": duration,
    }


def _build_diagnostics(
    *,
    total: int,
    counts: dict[str, int],
    services: dict[str, Any],
    jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []

    def add(level: str, title: str, message: str, action_label: str | None = None, action_to: str | None = None):
        diagnostics.append(
            {
                "level": level,
                "title": title,
                "message": message,
                "action_label": action_label,
                "action_to": action_to,
            }
        )

    if services.get("database", {}).get("status") == "offline":
        add("error", "PostgreSQL недоступен", "Dashboard не сможет достоверно считать метрики базы.", "Настройки", "/settings")
    if services.get("redis", {}).get("status") == "offline":
        add("error", "Redis недоступен", "Очереди Celery и постановка новых задач могут не работать.", "Мониторинг", "/celery")
    if services.get("celery", {}).get("status") in {"offline", "unknown"}:
        add("warning", "Celery worker не подтверждён", "Запущенные задачи могут не обновлять прогресс на главной.", "Статус задач", "/jobs")
    if services.get("qwen", {}).get("status") != "online":
        reason = services.get("qwen", {}).get("reason") or "AI-анализ PDF и русские выводы могут быть недоступны."
        add("warning", "Qwen не готов", str(reason), "Настройки", "/settings")
    if services.get("rag", {}).get("status") in {"offline", "unknown"}:
        add("warning", "RAG/Chroma не подтверждён", "Вопросы по базе и RAG-проекции могут работать неполно.", "RAG", "/rag")
    elif total and counts.get("rag_ready", 0) < total * 0.5:
        add("info", "Низкая готовность RAG", f"К RAG готово примерно {counts.get('rag_ready', 0)} из {total} документов.", "Векторный поиск", "/search")

    missing_full_text = max(0, total - counts.get("with_full_text", 0))
    if total and missing_full_text:
        level = "warning" if _percent(missing_full_text, total) >= 25 else "info"
        add(level, "Неполное покрытие полного текста", f"{missing_full_text} документов пока без полного текста.", "Полнотекстовый поиск", "/search/fulltext")

    missing_embeddings = max(0, total - counts.get("with_embeddings", 0))
    if total and missing_embeddings:
        level = "warning" if _percent(missing_embeddings, total) >= 25 else "info"
        add(level, "Не все документы имеют эмбеддинги", f"{missing_embeddings} документов без эмбеддингов в БД.", "Векторный поиск", "/search")

    if counts.get("processing_errors", 0) > 0:
        add("error", "Есть ошибки обработки контента", f"Документов с ошибками обработки: {counts['processing_errors']}.", "База статей", "/database")

    if counts.get("content_queued", 0) > 0:
        add("info", "Есть очередь обработки контента", f"Ожидают или выполняют обработку PDF/контента: {counts['content_queued']}.", "Статус задач", "/jobs")

    failed_jobs = [job for job in jobs if _job_status(job) == "failed"]
    if failed_jobs:
        latest = failed_jobs[0]
        add(
            "error",
            f"Последняя ошибка парсинга: {latest.get('source') or 'source'}",
            _job_error(latest) or f"Задача {latest.get('jobId')} завершилась ошибкой.",
            "Подробнее",
            "/jobs",
        )

    if not diagnostics:
        add("success", "Критичных проблем не найдено", "Основные сервисы и данные выглядят готовыми к работе.")

    return diagnostics[:10]


async def _build_dashboard_overview(db: AsyncSession, timezone_offset_minutes: int = 0) -> dict[str, Any]:
    """Aggregated operational snapshot for the redesigned dashboard."""
    day_start_utc, day_end_utc = _local_day_bounds(timezone_offset_minutes)

    full_text_expr = _text_present_expr(PaperModel.full_text)
    abstract_expr = _text_present_expr(PaperModel.abstract)
    pdf_expr = or_(_text_present_expr(PaperModel.pdf_url), _text_present_expr(PaperModel.pdf_local_path))
    embedding_expr = _json_present_expr(PaperModel.embedding)
    qwen_ready_expr = or_(
        _text_present_expr(PaperModel.summary_ru),
        _text_present_expr(PaperModel.analysis_ru),
        _text_present_expr(PaperModel.translation_ru),
    )
    content_parts_expr = exists(
        select(PaperContentPart.id).where(
            and_(
                PaperContentPart.paper_id == PaperModel.id,
                PaperContentPart.include_in_embedding.is_(True),
                or_(_text_present_expr(PaperContentPart.markdown_text), _text_present_expr(PaperContentPart.raw_text)),
            )
        )
    )
    metadata_ready_expr = and_(
        _text_present_expr(PaperModel.title),
        or_(abstract_expr, _json_present_expr(PaperModel.keywords)),
        _json_present_expr(PaperModel.authors),
    )
    processing_error_expr = or_(
        _text_present_expr(PaperModel.processing_error),
        PaperModel.processing_status.in_(sorted(ERROR_STATUSES)),
    )
    content_queued_expr = PaperModel.processing_status.in_(sorted(CONTENT_QUEUE_STATUSES))
    content_ready_expr = or_(PaperModel.processing_status.in_(sorted(READY_CONTENT_STATUSES)), content_parts_expr)
    rag_candidate_expr = and_(or_(full_text_expr, content_parts_expr), embedding_expr)

    summary_query = select(
        func.count().label("total"),
        _count_if(and_(PaperModel.created_at >= day_start_utc, PaperModel.created_at < day_end_utc)).label("today"),
        _count_if(abstract_expr).label("with_abstract"),
        _count_if(full_text_expr).label("with_full_text"),
        _count_if(pdf_expr).label("with_pdf"),
        _count_if(embedding_expr).label("with_embeddings"),
        _count_if(metadata_ready_expr).label("metadata_ready"),
        _count_if(qwen_ready_expr).label("qwen_ready"),
        _count_if(content_parts_expr).label("with_content_parts"),
        _count_if(content_ready_expr).label("content_ready"),
        _count_if(rag_candidate_expr).label("rag_candidates"),
        _count_if(processing_error_expr).label("processing_errors"),
        _count_if(content_queued_expr).label("content_queued"),
    )
    summary_row = (await db.execute(summary_query)).one()

    total = int(summary_row.total or 0)
    counts = {
        "total_papers": total,
        "today_papers": int(summary_row.today or 0),
        "with_abstract": int(summary_row.with_abstract or 0),
        "with_full_text": int(summary_row.with_full_text or 0),
        "with_pdf": int(summary_row.with_pdf or 0),
        "with_embeddings": int(summary_row.with_embeddings or 0),
        "metadata_ready": int(summary_row.metadata_ready or 0),
        "qwen_ready": int(summary_row.qwen_ready or 0),
        "with_content_parts": int(summary_row.with_content_parts or 0),
        "content_ready": int(summary_row.content_ready or 0),
        "rag_candidates": int(summary_row.rag_candidates or 0),
        "processing_errors": int(summary_row.processing_errors or 0),
        "content_queued": int(summary_row.content_queued or 0),
    }

    services = await _build_services(db, total)




    vector_indexed_ids, rag_indexed_ids = await asyncio.gather(
        _get_vector_indexed_paper_ids(),
        _get_rag_indexed_paper_ids(),
    )
    embedding_ids = await _select_paper_ids(db, embedding_expr) if vector_indexed_ids else set()
    rag_candidate_ids = await _select_paper_ids(db, rag_candidate_expr) if rag_indexed_ids else set()

    counts["vector_indexed"] = len(embedding_ids & vector_indexed_ids)
    counts["rag_ready"] = len(rag_candidate_ids & rag_indexed_ids)
    counts["rag_indexed"] = len(rag_indexed_ids)
    counts["vector_index_records"] = len(vector_indexed_ids)

    parser_settings = await SystemSettingsService(db).get_parser_settings()
    enabled_sources = parser_settings.get("enabled_sources") or {}
    source_limits = parser_settings.get("source_limits") or {}
    max_limit = _safe_int(parser_settings.get("max_limit"), 100)

    source_query = select(
        PaperModel.source.label("source"),
        func.count().label("count"),
        _count_if(and_(PaperModel.created_at >= day_start_utc, PaperModel.created_at < day_end_utc)).label("today"),
        _count_if(full_text_expr).label("with_full_text"),
        _count_if(embedding_expr).label("with_embeddings"),
        _count_if(processing_error_expr).label("errors"),
    ).group_by(PaperModel.source)
    source_rows = (await db.execute(source_query)).all()
    source_stats = {
        str(row.source): {
            "papers_count": int(row.count or 0),
            "added_today": int(row.today or 0),
            "with_full_text": int(row.with_full_text or 0),
            "with_embeddings": int(row.with_embeddings or 0),
            "errors": int(row.errors or 0),
        }
        for row in source_rows
    }

    raw_jobs = await asyncio.to_thread(list_parse_jobs, 50)
    raw_jobs = [job for job in raw_jobs if not _is_placeholder_job_id(job.get("jobId"))]
    latest_job_by_source: dict[str, dict[str, Any]] = {}
    for job in raw_jobs:
        source = str(job.get("source") or "").strip()
        if not source or source == "all" or source in latest_job_by_source:
            continue
        latest_job_by_source[source] = job

    sources = []
    for source in PAPER_SOURCES:
        stats = source_stats.get(source, {})
        latest_job = latest_job_by_source.get(source)
        rate = _source_success_rate(source, raw_jobs)
        sources.append(
            {
                "name": source,
                "kind": "API" if source in API_SOURCES else "HTML",
                "enabled": bool(enabled_sources.get(source, True)),
                "limit": _safe_int(source_limits.get(source), max_limit),
                "papers_count": stats.get("papers_count", 0),
                "added_today": stats.get("added_today", 0),
                "with_full_text": stats.get("with_full_text", 0),
                "with_embeddings": stats.get("with_embeddings", 0),
                "errors": stats.get("errors", 0),
                "success_rate": rate["success_rate"],
                "error_rate": rate["error_rate"],
                "last_duration_sec": rate["last_duration_sec"],
                "last_status": _job_status(latest_job) if latest_job else None,
                "last_error": _job_error(latest_job) if latest_job else None,
                "last_run_at": latest_job.get("startedAt") if latest_job else None,
            }
        )

    jobs_payload = await get_dashboard_jobs(limit=20)
    normalized_jobs = jobs_payload["jobs"]
    diagnostics = _build_diagnostics(total=total, counts=counts, services=services, jobs=raw_jobs)

    quality_percent = round(
        (
            _percent(counts["metadata_ready"], total)
            + _percent(counts["with_full_text"], total)
            + _percent(counts["with_embeddings"], total)
            + _percent(counts["vector_indexed"], counts["with_embeddings"])
            + _percent(counts["rag_ready"], counts["rag_candidates"])
        )
        / 5,
        1,
    ) if total else 0.0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "pipeline": {
            "metadata_percent": _percent(counts["metadata_ready"], total),
            "abstract_percent": _percent(counts["with_abstract"], total),
            "full_text_percent": _percent(counts["with_full_text"], total),
            "pdf_percent": _percent(counts["with_pdf"], total),
            "content_parts_percent": _percent(counts["with_content_parts"], total),
            "content_ready_percent": _percent(counts["content_ready"], total),
            "embedding_percent": _percent(counts["with_embeddings"], total),
            "vector_percent": _percent(counts["vector_indexed"], counts["with_embeddings"]),
            "rag_percent": _percent(counts["rag_ready"], counts["rag_candidates"]),
            "qwen_percent": _percent(counts["qwen_ready"], total),
            "quality_percent": quality_percent,
        },
        "services": services,
        "jobs": {
            "active": jobs_payload["summary"]["active"],
            "queued": _safe_int(services.get("celery", {}).get("queued"), 0) + counts["content_queued"],
            "failed_recent": jobs_payload["summary"]["failed_recent"],
        },
        "sources": sources,
        "diagnostics": diagnostics,
        "recommended_actions": _build_recommended_actions(counts=counts, services=services),
        "recent_jobs": normalized_jobs[:8],
    }


def _build_recommended_actions(*, counts: dict[str, int], services: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    def add(
        kind: str,
        title: str,
        description: str,
        action_label: str,
        action_to: str,
        action_name: str | None = None,
        action_payload: dict[str, Any] | None = None,
    ):
        actions.append(
            {
                "kind": kind,
                "title": title,
                "description": description,
                "action_label": action_label,
                "action_to": action_to,
                "action_name": action_name,
                "action_payload": action_payload or {},
            }
        )

    if services.get("redis", {}).get("status") == "offline":
        add("error", "Запустить Redis", "Без Redis очереди парсинга, обработки контента и Celery будут нестабильны.", "Инструкция", "/celery")
    if services.get("celery", {}).get("status") in {"offline", "unknown"}:
        add("warning", "Запустить worker", "Главная видит очередь, но не подтверждает активный Celery worker.", "Worker status", "/jobs")
    if counts.get("content_queued", 0) > 0:
        add("info", "Проверить обработку контента", f"В очереди или обработке: {counts['content_queued']} документов.", "Открыть задачи", "/jobs")

    missing_full_text = max(0, counts.get("total_papers", 0) - counts.get("with_full_text", 0))
    if missing_full_text > 0:
        add(
            "info",
            "Добрать полный текст",
            f"Без полного текста: {missing_full_text} документов.",
            "Поставить в очередь",
            "/jobs",
            "process_pdf_backlog",
            {"limit": min(100, missing_full_text), "pdf_mode": "auto"},
        )

    missing_embeddings = max(0, counts.get("total_papers", 0) - counts.get("with_embeddings", 0))
    if missing_embeddings > 0:
        add(
            "warning",
            "Пересобрать эмбеддинги",
            f"Без эмбеддингов в БД: {missing_embeddings} документов.",
            "Запустить",
            "/jobs",
            "rebuild_embeddings",
            {},
        )

    if counts.get("processing_errors", 0) > 0:
        add(
            "error",
            "Повторить ошибки обработки",
            f"Ошибок обработки контента: {counts['processing_errors']}.",
            "Повторить",
            "/jobs",
            "retry_failed_content",
            {"limit": min(100, counts["processing_errors"]), "pdf_mode": "auto"},
        )

    indexed_gap = max(0, counts.get("with_embeddings", 0) - counts.get("vector_indexed", 0))
    if indexed_gap > 0:
        add(
            "warning",
            "Vector index отстаёт",
            f"В БД есть эмбеддинги, но в Vector index не подтверждено {indexed_gap} документов.",
            "Синхронизировать",
            "/jobs",
            "reindex_vector_store",
            {},
        )

    rag_gap = max(0, counts.get("rag_candidates", 0) - counts.get("rag_ready", 0))
    if rag_gap > 0:
        add(
            "warning",
            "RAG/Chroma отстаёт",
            f"Есть контент и эмбеддинги, но в RAG/Chroma не подтверждено {rag_gap} документов.",
            "Пересобрать RAG",
            "/jobs",
            "rebuild_rag_index",
            {},
        )

    return actions[:5]


async def get_dashboard_overview(
    db: AsyncSession,
    timezone_offset_minutes: int = 0,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return cached dashboard overview unless an explicit refresh was requested."""
    cache_key = (int(timezone_offset_minutes),)
    now = time.monotonic()
    if not force_refresh:
        cached = _OVERVIEW_CACHE.get(cache_key)
        if cached and now - cached[0] <= OVERVIEW_CACHE_TTL_SECONDS:
            return cached[1]

    overview = await _build_dashboard_overview(db=db, timezone_offset_minutes=timezone_offset_minutes)
    _OVERVIEW_CACHE[cache_key] = (now, overview)
    return overview


def _action_limit(payload: dict[str, Any], *, default: int, maximum: int) -> int:
    try:
        raw = int(payload.get("limit") or default)
    except (TypeError, ValueError):
        raw = default
    return max(1, min(maximum, raw))


def _action_source(payload: dict[str, Any]) -> str | None:
    source = str(payload.get("source") or "").strip()
    if not source or source == "all":
        return None
    return source


def _action_pdf_mode(payload: dict[str, Any]) -> str:
    mode = str(payload.get("pdf_mode") or payload.get("pdfMode") or "auto").strip().lower()
    return mode if mode in {"auto", "ai", "mypdf"} else "auto"


async def trigger_dashboard_action(action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate and enqueue a heavy dashboard action through Celery."""
    payload = payload or {}
    action = str(action or "").strip()
    if action not in DASHBOARD_ACTIONS:
        raise ValueError(f"Unsupported dashboard action: {action}")

    invalidate_dashboard_overview_cache()
    spec = DASHBOARD_ACTIONS[action]

    if action == "process_pdf_backlog":
        from app.tasks.dashboard_actions import process_pdf_backlog_task

        args = [
            _action_limit(payload, default=100, maximum=500),
            _action_pdf_mode(payload),
            _action_source(payload),
        ]
        async_result = process_pdf_backlog_task.apply_async(args=args, queue=settings.CONTENT_QUEUE_NAME)
        source = _action_source(payload) or "dashboard"
        query = spec["query"]
    elif action == "retry_failed_content":
        from app.tasks.dashboard_actions import retry_failed_content_task

        args = [
            _action_limit(payload, default=100, maximum=500),
            _action_pdf_mode(payload),
            _action_source(payload),
        ]
        async_result = retry_failed_content_task.apply_async(args=args, queue=settings.CONTENT_QUEUE_NAME)
        source = _action_source(payload) or "dashboard"
        query = spec["query"]
    elif action == "rebuild_embeddings":
        from app.tasks.dashboard_actions import rebuild_embeddings_task


        args = [None, _action_source(payload)]
        async_result = rebuild_embeddings_task.apply_async(args=args, queue=settings.CONTENT_QUEUE_NAME)
        source = _action_source(payload) or "dashboard"
        query = spec["query"]
    elif action == "reindex_vector_store":
        from app.tasks.dashboard_actions import reindex_vector_store_task


        async_result = reindex_vector_store_task.apply_async(args=[None, _action_source(payload)], queue=settings.CONTENT_QUEUE_NAME)
        source = _action_source(payload) or "dashboard"
        query = spec["query"]
    elif action == "rebuild_vector_store_full":
        from app.tasks.dashboard_actions import rebuild_vector_store_full_task

        async_result = rebuild_vector_store_full_task.apply_async(args=[_action_source(payload)], queue=settings.CONTENT_QUEUE_NAME)
        source = _action_source(payload) or "dashboard"
        query = spec["query"]
    elif action == "rebuild_rag_index":
        from app.tasks.dashboard_actions import rebuild_rag_index_task

        async_result = rebuild_rag_index_task.apply_async(queue=settings.CONTENT_QUEUE_NAME)
        source = "dashboard"
        query = spec["query"]
    elif action == "rerun_source":
        from app.tasks.parse_tasks import parse_all_sources_task, parse_papers_task

        query = str(payload.get("query") or "nickel-based superalloys").strip()
        source_payload = str(payload.get("source") or "all").strip() or "all"
        limit = _action_limit(payload, default=25, maximum=100)
        pdf_mode = _action_pdf_mode(payload)
        if source_payload == "all":
            async_result = parse_all_sources_task.apply_async(
                kwargs={"limit_per_query": limit, "query": query, "pdf_mode": pdf_mode},
                queue="celery",
            )
        else:
            async_result = parse_papers_task.apply_async(
                args=[query, limit, source_payload, pdf_mode],
                queue="celery",
            )
        source = source_payload
    else:
        raise ValueError(f"Unsupported dashboard action: {action}")

    now_ms = int(time.time() * 1000)
    task_id = str(async_result.id)
    add_parse_job(
        {
            "jobId": task_id,
            "startedAt": now_ms,
            "query": query,
            "source": source,
            "initialCount": 0,
            "lastObservedCount": 0,
            "lastCountChangeAt": now_ms,
            "status": "in_progress",
            "celeryStatus": {
                "task_id": task_id,
                "status": "PENDING",
                "state": "PENDING",
                "name": spec["task"],
                "dashboard_action": action,
            },
        }
    )

    return {
        "action": action,
        "title": spec["title"],
        "task_id": task_id,
        "status": "queued",
        "source": source,
        "query": query,
    }
