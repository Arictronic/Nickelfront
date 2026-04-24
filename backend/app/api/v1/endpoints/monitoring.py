"""API endpoints для мониторинга Celery."""

import asyncio
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.tasks.celery_app import celery_app

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


# Flower API base URL
FLOWER_HOST = settings.get_flower_url()
FLOWER_TIMEOUT = httpx.Timeout(connect=0.8, read=6.0, write=2.0, pool=1.0)
FLOWER_HTTP_OK_FOR_REACHABILITY = {200, 301, 302, 307, 308, 401, 403, 404}
WORKER_CACHE_TTL_SECONDS = 180
WORKER_BUSY_AFTER_SECONDS = 15
_WORKER_CACHE: dict[str, dict[str, Any]] = {}


def _flower_url(path: str) -> str:
    base = FLOWER_HOST.rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    return f"{base}{suffix}"


async def _flower_probe(client: httpx.AsyncClient) -> bool:
    try:
        response = await client.get(FLOWER_HOST)
    except httpx.RequestError:
        return False
    return response.status_code in FLOWER_HTTP_OK_FOR_REACHABILITY


async def _flower_get_json(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any] | None = None,
) -> tuple[Any, bool]:
    try:
        response = await client.get(_flower_url(path), params=params)
    except httpx.RequestError:
        return None, False

    reachable = response.status_code in FLOWER_HTTP_OK_FOR_REACHABILITY
    if response.status_code != 200:
        return None, reachable

    try:
        return response.json(), reachable
    except ValueError:
        return None, reachable


def _inspect_workers_fallback() -> list[str]:
    try:
        inspector = celery_app.control.inspect(timeout=2.0)
        ping = inspector.ping() or {}
        return list(ping.keys())
    except Exception:
        return []


def _inspect_active_tasks_fallback() -> int:
    try:
        inspector = celery_app.control.inspect(timeout=2.0)
        active = inspector.active() or {}
        return sum(len(v or []) for v in active.values())
    except Exception:
        return 0


async def _inspect_workers_count_quick() -> int:
    try:
        workers = await asyncio.wait_for(asyncio.to_thread(_inspect_workers_fallback), timeout=2.5)
        return len(workers)
    except Exception:
        return 0


async def _inspect_active_tasks_quick() -> int:
    try:
        return int(
            await asyncio.wait_for(asyncio.to_thread(_inspect_active_tasks_fallback), timeout=2.5)
        )
    except Exception:
        return 0


def _safe_dict_values(data):
    if isinstance(data, dict):
        return data.values()
    return []


def _is_worker_active(worker_info: Any) -> bool:
    if not isinstance(worker_info, dict):
        return False
    active_value = worker_info.get("active", 0)
    if isinstance(active_value, list):
        active_count = len(active_value)
    elif isinstance(active_value, (int, float)):
        active_count = int(active_value)
    else:
        active_count = 0
    status = str(worker_info.get("status", "")).lower()
    return active_count > 0 or status in {"online", "busy"}


def _cache_workers(workers: list[dict[str, Any]]) -> None:
    now = datetime.now()
    for worker in workers:
        name = worker.get("name")
        if not name:
            continue
        _WORKER_CACHE[str(name)] = {"worker": worker, "last_seen": now}


def _get_cached_workers() -> list[dict[str, Any]]:
    now = datetime.now()
    result: list[dict[str, Any]] = []
    expired: list[str] = []

    for name, payload in _WORKER_CACHE.items():
        last_seen = payload.get("last_seen")
        worker = payload.get("worker")
        if not isinstance(last_seen, datetime) or not isinstance(worker, dict):
            expired.append(name)
            continue

        age_seconds = int((now - last_seen).total_seconds())
        if age_seconds > WORKER_CACHE_TTL_SECONDS:
            expired.append(name)
            continue

        cached_worker = dict(worker)
        cached_worker["stale_seconds"] = age_seconds
        if age_seconds >= WORKER_BUSY_AFTER_SECONDS:
            cached_worker["status"] = "busy"
        result.append(cached_worker)

    for name in expired:
        _WORKER_CACHE.pop(name, None)

    return result


def _merge_with_cached_workers(workers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for worker in workers:
        name = worker.get("name")
        if name:
            merged[str(name)] = worker

    for cached in _get_cached_workers():
        name = cached.get("name")
        if name and str(name) not in merged:
            merged[str(name)] = cached

    return list(merged.values())


def _normalize_worker(name: str, info: Any) -> dict[str, Any]:
    if not isinstance(info, dict):
        return {
            "name": name,
            "status": "unknown",
            "active_tasks": 0,
            "processed_tasks": 0,
            "queues": [],
            "pool": {},
            "timestamp": None,
        }

    active_value = info.get("active", 0)
    if isinstance(active_value, list):
        active_tasks = len(active_value)
    elif isinstance(active_value, (int, float)):
        active_tasks = int(active_value)
    else:
        active_tasks = 0

    stats = info.get("stats", {}) if isinstance(info.get("stats"), dict) else {}
    total_map = stats.get("total", {}) if isinstance(stats.get("total"), dict) else {}
    if isinstance(info.get("processed"), (int, float)):
        processed_tasks = int(info.get("processed", 0))
    else:
        processed_tasks = sum(total_map.values())

    active_queues = info.get("active_queues", [])
    queues: list[str] = []
    if isinstance(active_queues, list):
        queues = [q.get("name", "celery") for q in active_queues if isinstance(q, dict)]

    return {
        "name": name,
        "status": "online",
        "active_tasks": active_tasks,
        "processed_tasks": processed_tasks,
        "queues": queues,
        "pool": stats.get("pool", {}) if isinstance(stats, dict) else {},
        "timestamp": info.get("timestamp"),
    }


def _inspect_workers_details_fallback() -> list[dict]:
    try:
        inspector = celery_app.control.inspect(timeout=2.0)
        ping = inspector.ping() or {}
        active = inspector.active() or {}
        stats = inspector.stats() or {}

        workers = []
        for name in ping.keys():
            worker_stats = stats.get(name, {}) if isinstance(stats, dict) else {}
            total_map = (worker_stats.get("total") or {}) if isinstance(worker_stats, dict) else {}
            processed_tasks = sum(total_map.values()) if isinstance(total_map, dict) else 0
            workers.append(
                {
                    "name": name,
                    "status": "online",
                    "active_tasks": len(active.get(name, []) or []),
                    "processed_tasks": processed_tasks,
                    "queues": ["celery"],
                    "pool": worker_stats.get("pool", {}) if isinstance(worker_stats, dict) else {},
                    "timestamp": None,
                }
            )
        return workers
    except Exception:
        return []


def _inspect_tasks_details_fallback(limit: int = 100, state: str | None = None) -> list[dict]:
    try:
        inspector = celery_app.control.inspect(timeout=2.0)
        active = inspector.active() or {}
        reserved = inspector.reserved() or {}
        scheduled = inspector.scheduled() or {}

        tasks: list[dict] = []

        def _append(entries, default_state: str, worker_name: str):
            for item in entries or []:
                task_id = item.get("id") or item.get("request", {}).get("id") or "unknown"
                task_name = item.get("name") or item.get("request", {}).get("name") or "unknown"
                task_state = str(item.get("state") or default_state).upper()
                if state and task_state != state.upper():
                    continue
                tasks.append(
                    {
                        "task_id": task_id,
                        "name": task_name,
                        "state": task_state,
                        "args": str(item.get("args") or item.get("request", {}).get("args") or ""),
                        "kwargs": item.get("kwargs") or item.get("request", {}).get("kwargs") or {},
                        "started": item.get("time_start"),
                        "received": item.get("time_start"),
                        "succeeded": None,
                        "failed": None,
                        "retries": item.get("retries", 0),
                        "worker": {"hostname": worker_name},
                    }
                )

        for worker_name, entries in active.items():
            _append(entries, "STARTED", worker_name)
        for worker_name, entries in reserved.items():
            _append(entries, "PENDING", worker_name)
        for worker_name, entries in scheduled.items():
            _append(entries, "PENDING", worker_name)

        return tasks[:limit]
    except Exception:
        return []


@router.get("/celery/status")
async def get_celery_status():
    """
    Get fast Celery cluster status.

    Returns:
        Summary for workers and tasks.
    """
    try:
        async with httpx.AsyncClient(timeout=FLOWER_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            probe_ok, workers_result = await asyncio.gather(
                _flower_probe(client),
                _flower_get_json(client, "/api/workers", params={"refresh": 1}),
            )

        workers_data, workers_reachable = workers_result
        tasks_data, tasks_reachable = {}, False
        workers_data = workers_data if isinstance(workers_data, dict) else {}
        tasks_data = tasks_data if isinstance(tasks_data, dict) else {}
        flower_reachable = bool(probe_ok or workers_reachable or tasks_reachable)

        workers_count = len(workers_data) if isinstance(workers_data, dict) else 0
        active_workers = sum(1 for w in _safe_dict_values(workers_data) if _is_worker_active(w))

        if workers_count == 0:
            workers_payload = await get_workers_info()
            fallback_workers = workers_payload.get("workers", [])
            workers_count = int(workers_payload.get("total", 0))
            active_workers = sum(
                1
                for worker in fallback_workers
                if isinstance(worker, dict)
                and str(worker.get("status", "")).lower() in {"online", "busy"}
            )
            if active_workers == 0 and workers_count > 0:
                active_workers = workers_count

        total_tasks = len(tasks_data) if isinstance(tasks_data, dict) else 0
        active_tasks = sum(
            1
            for t in _safe_dict_values(tasks_data)
            if isinstance(t, dict) and str(t.get("state", "")).lower() == "started"
        )
        if active_tasks == 0:
            active_tasks = await _inspect_active_tasks_quick()
        successful_tasks = sum(
            1
            for t in _safe_dict_values(tasks_data)
            if isinstance(t, dict) and str(t.get("state", "")).lower() == "success"
        )
        failed_tasks = sum(
            1
            for t in _safe_dict_values(tasks_data)
            if isinstance(t, dict) and str(t.get("state", "")).lower() == "failure"
        )

        return {
            "status": "online" if workers_count > 0 else "offline",
            "workers": {
                "total": workers_count,
                "active": active_workers,
            },
            "tasks": {
                "total": total_tasks,
                "active": active_tasks,
                "successful": successful_tasks,
                "failed": failed_tasks,
            },
            "flower_available": flower_reachable,
            "flower_url": FLOWER_HOST,
            "generated_at": datetime.now().isoformat(),
        }

    except Exception as e:
        return {
            "status": "offline",
            "workers": {
                "total": 0,
                "active": 0,
            },
            "tasks": {
                "total": 0,
                "active": 0,
                "successful": 0,
                "failed": 0,
            },
            "flower_available": False,
            "flower_url": FLOWER_HOST,
            "error": str(e),
            "generated_at": datetime.now().isoformat(),
        }


@router.get("/celery/workers")
async def get_workers_info():
    """
    Получить информацию о воркерах.

    Returns:
        Список воркеров с деталями
    """
    try:
        async with httpx.AsyncClient(timeout=FLOWER_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            workers_data, _ = await _flower_get_json(client, "/api/workers", params={"refresh": 1})
            workers_data = workers_data if isinstance(workers_data, dict) else {}

            # Форматируем ответ
            workers = []
            for name, info in (workers_data.items() if isinstance(workers_data, dict) else {}):
                workers.append(_normalize_worker(name, info))

            if len(workers) == 0:
                workers = await asyncio.to_thread(_inspect_workers_details_fallback)
            else:
                _cache_workers(workers)

            workers = _merge_with_cached_workers(workers)
            if workers:
                _cache_workers(workers)

            return {
                "workers": workers,
                "total": len(workers),
                "generated_at": datetime.now().isoformat(),
            }

    except httpx.RequestError:
        workers = await asyncio.to_thread(_inspect_workers_details_fallback)
        if workers:
            _cache_workers(workers)
        workers = _merge_with_cached_workers(workers)
        return {
            "workers": workers,
            "total": len(workers),
            "generated_at": datetime.now().isoformat(),
        }
    except Exception as e:
        workers = await asyncio.to_thread(_inspect_workers_details_fallback)
        if workers:
            _cache_workers(workers)
        workers = _merge_with_cached_workers(workers)
        if workers:
            return {
                "workers": workers,
                "total": len(workers),
                "generated_at": datetime.now().isoformat(),
            }
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/celery/tasks")
async def get_tasks_info(
    limit: int = 100,
    state: str | None = None,
):
    """
    Получить информацию о задачах.

    Args:
        limit: Максимум задач
        state: Фильтр по статусу (SUCCESS, FAILURE, STARTED, PENDING)

    Returns:
        Список задач
    """
    try:
        async with httpx.AsyncClient(timeout=FLOWER_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            params = {"limit": min(limit, 500)}
            if state:
                params["state"] = state

            tasks_data, _ = await _flower_get_json(client, "/api/tasks", params=params)
            tasks_data = tasks_data if isinstance(tasks_data, dict) else {}

            # Форматируем ответ
            tasks = []
            for task_id, info in (tasks_data.items() if isinstance(tasks_data, dict) else {}):
                tasks.append({
                    "task_id": task_id,
                    "name": info.get("name", "unknown"),
                    "state": info.get("state", "UNKNOWN"),
                    "args": info.get("args", ""),
                    "kwargs": info.get("kwargs", {}),
                    "started": info.get("started"),
                    "received": info.get("received"),
                    "succeeded": info.get("succeeded"),
                    "failed": info.get("failed"),
                    "retries": info.get("retries", 0),
                    "worker": info.get("worker", {}),
                })

            # Сортируем по времени получения
            tasks.sort(key=lambda t: t.get("received", ""), reverse=True)

            if len(tasks) == 0:
                tasks = await asyncio.to_thread(_inspect_tasks_details_fallback, limit, state)

            return {
                "tasks": tasks[:limit],
                "total": len(tasks),
                "limit": limit,
                "generated_at": datetime.now().isoformat(),
            }

    except httpx.RequestError:
        tasks = await asyncio.to_thread(_inspect_tasks_details_fallback, limit, state)
        return {
            "tasks": tasks[:limit],
            "total": len(tasks),
            "limit": limit,
            "generated_at": datetime.now().isoformat(),
        }
    except Exception as e:
        tasks = await asyncio.to_thread(_inspect_tasks_details_fallback, limit, state)
        if tasks:
            return {
                "tasks": tasks[:limit],
                "total": len(tasks),
                "limit": limit,
                "generated_at": datetime.now().isoformat(),
            }
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/celery/queues")
async def get_queues_info():
    """
    Получить информацию об очередях.

    Returns:
        Список очередей
    """
    try:
        async with httpx.AsyncClient(timeout=FLOWER_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            queues_data, _ = await _flower_get_json(client, "/api/broker/queues")

            if not isinstance(queues_data, dict):
                # Queue API unavailable: return minimal fallback payload
                return {
                    "queues": [
                        {"name": "celery", "messages": 0, "consumers": 1},
                    ],
                    "total": 1,
                    "generated_at": datetime.now().isoformat(),
                }

            # Форматируем ответ
            queues = []
            for name, info in (queues_data.items() if isinstance(queues_data, dict) else {}):
                queues.append({
                    "name": name,
                    "messages": info.get("messages", 0),
                    "consumers": info.get("consumers", 0),
                    "unacked": info.get("unacked", 0),
                })

            return {
                "queues": queues,
                "total": len(queues),
                "generated_at": datetime.now().isoformat(),
            }

    except httpx.RequestError:
        # Возвращаем базовую информацию при ошибке
        return {
            "queues": [
                {"name": "celery", "messages": 0, "consumers": 1},
            ],
            "total": 1,
            "generated_at": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/celery/scheduled-tasks")
async def get_scheduled_tasks_info():
    """
    Получить информацию о запланированных задачах (Celery Beat).

    Returns:
        Список периодических задач
    """
    try:
        # Получаем конфигурацию из celery_app
        beat_schedule = celery_app.conf.beat_schedule or {}
        descriptions = {
            "daily-parse-all-sources": "Ежедневный полный парсинг всех источников из parser_alpha",
            "weekly-parse-all-sources": "Еженедельный полный парсинг всех источников из parser_alpha",
            "hourly-parse-core": "Ежечасный парсинг CORE по базовым запросам",
        }

        scheduled_tasks = []
        for name, config in beat_schedule.items():
            scheduled_tasks.append({
                "name": name,
                "task": config.get("task", "unknown"),
                "schedule": str(config.get("schedule", "unknown")),
                "description": descriptions.get(name, "Периодическая задача Celery"),
                "kwargs": config.get("kwargs", {}),
                "options": config.get("options", {}),
            })

        return {
            "scheduled_tasks": scheduled_tasks,
            "total": len(scheduled_tasks),
            "generated_at": datetime.now().isoformat(),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
