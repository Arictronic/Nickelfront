"""API endpoints для мониторинга Celery."""

import asyncio
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_admin_user
from app.core.config import settings

router = APIRouter(prefix="/monitoring", tags=["monitoring"], dependencies=[Depends(require_admin_user)])



FLOWER_HOST = settings.get_flower_url()
FLOWER_TIMEOUT = httpx.Timeout(connect=0.8, read=6.0, write=2.0, pool=1.0)
FLOWER_HTTP_OK_FOR_REACHABILITY = {200, 301, 302, 307, 308, 401, 403, 404}
WORKER_CACHE_TTL_SECONDS = 60
WORKER_STALE_AFTER_SECONDS = 15
_WORKER_CACHE: dict[str, dict[str, Any]] = {}


def _get_celery_app():
    from app.tasks.celery_app import celery_app

    return celery_app


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
        celery_app = _get_celery_app()
        inspector = celery_app.control.inspect(timeout=2.0)
        ping = inspector.ping() or {}
        return list(ping.keys())
    except Exception:
        return []


def _inspect_active_tasks_fallback() -> int:
    try:
        celery_app = _get_celery_app()
        inspector = celery_app.control.inspect(timeout=2.0)
        active = inspector.active() or {}
        return sum(len(v or []) for v in active.values())
    except Exception:
        return 0


def _inspect_active_queues_fallback() -> dict[str, list[str]]:
    try:
        celery_app = _get_celery_app()
        inspector = celery_app.control.inspect(timeout=2.0)
        active_queues = inspector.active_queues() or {}
        result: dict[str, list[str]] = {}
        for worker_name, queues in active_queues.items():
            names: list[str] = []
            for queue in queues or []:
                if isinstance(queue, dict):
                    queue_name = queue.get("name")
                    if queue_name:
                        names.append(str(queue_name))
            result[str(worker_name)] = names
        return result
    except Exception:
        return {}


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
        if age_seconds >= WORKER_STALE_AFTER_SECONDS:
            cached_worker["status"] = "stale"
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


def _uniq_strings(values: list[Any] | tuple[Any, ...] | set[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _split_queue_names(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        parts = value
    else:
        parts = str(value).replace(";", ",").split(",")
    return _uniq_strings([str(part).strip() for part in parts if str(part).strip()])


def _expected_queue_names() -> list[str]:
    names: list[str] = []
    names.extend(_split_queue_names(getattr(settings, "WORKER_QUEUES", "celery")))
    names.extend(_split_queue_names(getattr(settings, "CONTENT_QUEUE_NAME", "content")))
    if bool(getattr(settings, "QWEN_QUEUE_ENABLED", True)):
        names.extend(_split_queue_names(getattr(settings, "QWEN_QUEUE_NAME", "qwen")))
    return _uniq_strings(names or ["celery"])


def _task_time_sort_value(value: Any) -> float:
    if value is None:
        return 0.0

    if isinstance(value, (int, float)):
        raw = float(value)
        return raw / 1000.0 if raw > 10_000_000_000 else raw

    text = str(value).strip()
    if not text:
        return 0.0

    try:
        raw = float(text)
        return raw / 1000.0 if raw > 10_000_000_000 else raw
    except ValueError:
        pass

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _task_sort_key(task: dict[str, Any]) -> float:
    return max(
        _task_time_sort_value(task.get("received")),
        _task_time_sort_value(task.get("started")),
        _task_time_sort_value(task.get("succeeded")),
        _task_time_sort_value(task.get("failed")),
    )


def _merge_worker_records(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    """Merge Flower and Celery inspect worker payloads without losing queues.

    Flower can temporarily miss a worker while Celery inspect still sees it, and
    Flower's /api/workers payload can omit active_queues. The UI needs a stable
    view, so we merge by worker name and keep the richest values.
    """
    merged = dict(primary)

    primary_status = str(primary.get("status") or "").lower()
    secondary_status = str(secondary.get("status") or "").lower()
    if primary_status not in {"online", "busy"} and secondary_status in {"online", "busy"}:
        merged["status"] = secondary.get("status")

    merged["active_tasks"] = max(
        int(primary.get("active_tasks") or 0),
        int(secondary.get("active_tasks") or 0),
    )
    merged["processed_tasks"] = max(
        int(primary.get("processed_tasks") or 0),
        int(secondary.get("processed_tasks") or 0),
    )

    merged["queues"] = _uniq_strings(
        list(primary.get("queues") or []) + list(secondary.get("queues") or [])
    )

    primary_pool = primary.get("pool") if isinstance(primary.get("pool"), dict) else {}
    secondary_pool = secondary.get("pool") if isinstance(secondary.get("pool"), dict) else {}
    merged["pool"] = primary_pool or secondary_pool

    if not merged.get("timestamp") and secondary.get("timestamp"):
        merged["timestamp"] = secondary.get("timestamp")

    return merged


def _merge_worker_lists(*worker_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for workers in worker_lists:
        for worker in workers or []:
            if not isinstance(worker, dict):
                continue
            name = str(worker.get("name") or "").strip()
            if not name:
                continue
            if name in merged:
                merged[name] = _merge_worker_records(merged[name], worker)
            else:
                merged[name] = dict(worker)
    return sorted(merged.values(), key=lambda item: str(item.get("name") or ""))


def _queue_consumer_counts_from_active_queues(active_queues: dict[str, list[str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for queue_names in active_queues.values():
        for queue_name in queue_names or []:
            name = str(queue_name or "").strip()
            if not name:
                continue
            counts[name] = counts.get(name, 0) + 1
    return counts


def _normalize_queue_record(name: str, info: Any) -> dict[str, Any]:
    payload = info if isinstance(info, dict) else {}
    return {
        "name": name,
        "messages": int(payload.get("messages") or 0),
        "consumers": int(payload.get("consumers") or 0),
        "unacked": int(payload.get("unacked") or 0),
    }


def _merge_queue_lists(*queue_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for queues in queue_lists:
        for queue in queues or []:
            if not isinstance(queue, dict):
                continue
            name = str(queue.get("name") or "").strip()
            if not name:
                continue
            if name not in merged:
                merged[name] = {
                    "name": name,
                    "messages": int(queue.get("messages") or 0),
                    "consumers": int(queue.get("consumers") or 0),
                    "unacked": int(queue.get("unacked") or 0),
                }
                continue
            merged[name]["messages"] = max(
                int(merged[name].get("messages") or 0),
                int(queue.get("messages") or 0),
            )
            merged[name]["consumers"] = max(
                int(merged[name].get("consumers") or 0),
                int(queue.get("consumers") or 0),
            )
            merged[name]["unacked"] = max(
                int(merged[name].get("unacked") or 0),
                int(queue.get("unacked") or 0),
            )
    return sorted(merged.values(), key=lambda item: str(item.get("name") or ""))


def _queue_payloads_from_inspect(active_queues: dict[str, list[str]]) -> list[dict[str, Any]]:
    return [
        {"name": name, "messages": 0, "consumers": consumers, "unacked": 0}
        for name, consumers in sorted(_queue_consumer_counts_from_active_queues(active_queues).items())
    ]


def _task_state_counts(tasks_data: Any) -> dict[str, int]:
    counts = {"total": 0, "active": 0, "successful": 0, "failed": 0}
    if not isinstance(tasks_data, dict):
        return counts

    counts["total"] = len(tasks_data)
    for info in tasks_data.values():
        if not isinstance(info, dict):
            continue
        state = str(info.get("state") or "").lower()
        if state in {"started", "running", "active"}:
            counts["active"] += 1
        elif state == "success":
            counts["successful"] += 1
        elif state == "failure":
            counts["failed"] += 1
    return counts


def _inspect_workers_details_fallback() -> list[dict]:
    try:
        celery_app = _get_celery_app()
        inspector = celery_app.control.inspect(timeout=2.0)
        ping = inspector.ping() or {}
        active = inspector.active() or {}
        stats = inspector.stats() or {}
        active_queues = inspector.active_queues() or {}

        workers = []
        for name in ping.keys():
            worker_stats = stats.get(name, {}) if isinstance(stats, dict) else {}
            total_map = (worker_stats.get("total") or {}) if isinstance(worker_stats, dict) else {}
            processed_tasks = sum(total_map.values()) if isinstance(total_map, dict) else 0
            queues = []
            for queue in active_queues.get(name, []) or []:
                if isinstance(queue, dict) and queue.get("name"):
                    queues.append(str(queue.get("name")))
            workers.append(
                {
                    "name": name,
                    "status": "online",
                    "active_tasks": len(active.get(name, []) or []),
                    "processed_tasks": processed_tasks,
                    "queues": queues,
                    "pool": worker_stats.get("pool", {}) if isinstance(worker_stats, dict) else {},
                    "timestamp": None,
                }
            )
        return workers
    except Exception:
        return []


def _inspect_tasks_details_fallback(limit: int = 100, state: str | None = None) -> list[dict]:
    try:
        celery_app = _get_celery_app()
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
            probe_ok, workers_result, tasks_result = await asyncio.gather(
                _flower_probe(client),
                _flower_get_json(client, "/api/workers", params={"refresh": 1}),
                _flower_get_json(client, "/api/tasks", params={"limit": 100}),
            )

        workers_data_raw, workers_reachable = workers_result
        tasks_data_raw, tasks_reachable = tasks_result
        flower_workers_api_available = isinstance(workers_data_raw, dict)
        flower_tasks_api_available = isinstance(tasks_data_raw, dict)
        flower_api_available = flower_workers_api_available or flower_tasks_api_available
        workers_data = workers_data_raw if isinstance(workers_data_raw, dict) else {}
        tasks_data = tasks_data_raw if isinstance(tasks_data_raw, dict) else {}
        flower_reachable = bool(probe_ok or workers_reachable or tasks_reachable)

        flower_workers = [
            _normalize_worker(name, info)
            for name, info in workers_data.items()
        ]
        inspect_workers = await asyncio.to_thread(_inspect_workers_details_fallback)
        workers = _merge_worker_lists(flower_workers, inspect_workers, _get_cached_workers())
        if workers:
            _cache_workers(workers)

        workers_count = len(workers)
        active_workers = sum(
            1
            for worker in workers
            if str(worker.get("status", "")).lower() in {"online", "busy"}
        )

        task_counts = _task_state_counts(tasks_data)
        inspect_active_tasks = await _inspect_active_tasks_quick()
        active_tasks = max(task_counts["active"], inspect_active_tasks)

        return {
            "status": "online" if workers_count > 0 else "offline",
            "workers": {
                "total": workers_count,
                "active": active_workers,
            },
            "tasks": {
                "total": task_counts["total"],
                "active": active_tasks,
                "successful": task_counts["successful"],
                "failed": task_counts["failed"],
            },
            "flower_available": flower_reachable,
            "flower_api_available": flower_api_available,
            "expected_queues": _expected_queue_names(),
            "flower_url": FLOWER_HOST,
            "generated_at": datetime.now().isoformat(),
        }

    except Exception as e:
        workers = await asyncio.to_thread(_inspect_workers_details_fallback)
        if workers:
            _cache_workers(workers)
            active_tasks = await _inspect_active_tasks_quick()
            return {
                "status": "online",
                "workers": {
                    "total": len(workers),
                    "active": sum(
                        1
                        for worker in workers
                        if str(worker.get("status", "")).lower() in {"online", "busy"}
                    ),
                },
                "tasks": {
                    "total": 0,
                    "active": active_tasks,
                    "successful": 0,
                    "failed": 0,
                },
                "flower_available": False,
                "flower_api_available": False,
                "expected_queues": _expected_queue_names(),
                "flower_url": FLOWER_HOST,
                "warning": str(e),
                "generated_at": datetime.now().isoformat(),
            }

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
            "flower_api_available": False,
            "expected_queues": _expected_queue_names(),
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
        flower_workers: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=FLOWER_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            workers_data, _ = await _flower_get_json(client, "/api/workers", params={"refresh": 1})
            if isinstance(workers_data, dict):
                flower_workers = [
                    _normalize_worker(name, info)
                    for name, info in workers_data.items()
                ]

        inspect_workers = await asyncio.to_thread(_inspect_workers_details_fallback)
        workers = _merge_worker_lists(flower_workers, inspect_workers, _get_cached_workers())
        if workers:
            _cache_workers(workers)

        return {
            "workers": workers,
            "total": len(workers),
            "generated_at": datetime.now().isoformat(),
        }

    except httpx.RequestError:
        workers = await asyncio.to_thread(_inspect_workers_details_fallback)
        workers = _merge_worker_lists(workers, _get_cached_workers())
        if workers:
            _cache_workers(workers)
        return {
            "workers": workers,
            "total": len(workers),
            "generated_at": datetime.now().isoformat(),
        }
    except Exception as e:
        workers = await asyncio.to_thread(_inspect_workers_details_fallback)
        workers = _merge_worker_lists(workers, _get_cached_workers())
        if workers:
            _cache_workers(workers)
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

            tasks_data_raw, _ = await _flower_get_json(client, "/api/tasks", params=params)
            flower_api_available = isinstance(tasks_data_raw, dict)
            tasks_data = tasks_data_raw if isinstance(tasks_data_raw, dict) else {}


            tasks = []
            for task_id, info in tasks_data.items():
                if not isinstance(info, dict):
                    continue
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


            tasks.sort(key=_task_sort_key, reverse=True)

            source = "flower"
            if len(tasks) == 0:
                tasks = await asyncio.to_thread(_inspect_tasks_details_fallback, limit, state)
                tasks.sort(key=_task_sort_key, reverse=True)
                source = "inspect"

            return {
                "tasks": tasks[:limit],
                "total": len(tasks),
                "limit": limit,
                "source": source,
                "flower_api_available": flower_api_available,
                "generated_at": datetime.now().isoformat(),
            }

    except httpx.RequestError:
        tasks = await asyncio.to_thread(_inspect_tasks_details_fallback, limit, state)
        tasks.sort(key=_task_sort_key, reverse=True)
        return {
            "tasks": tasks[:limit],
            "total": len(tasks),
            "limit": limit,
            "source": "inspect",
            "flower_api_available": False,
            "generated_at": datetime.now().isoformat(),
        }
    except Exception as e:
        tasks = await asyncio.to_thread(_inspect_tasks_details_fallback, limit, state)
        if tasks:
            tasks.sort(key=_task_sort_key, reverse=True)
            return {
                "tasks": tasks[:limit],
                "total": len(tasks),
                "limit": limit,
                "source": "inspect",
                "flower_api_available": False,
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
        flower_queues: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=FLOWER_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            queues_data, _ = await _flower_get_json(client, "/api/broker/queues")
            if isinstance(queues_data, dict):
                flower_queues = [
                    _normalize_queue_record(name, info)
                    for name, info in queues_data.items()
                ]

        active_queues = await asyncio.to_thread(_inspect_active_queues_fallback)
        inspect_queues = _queue_payloads_from_inspect(active_queues)
        queues = _merge_queue_lists(flower_queues, inspect_queues)

        return {
            "queues": queues,
            "total": len(queues),
            "expected_queues": _expected_queue_names(),
            "generated_at": datetime.now().isoformat(),
        }

    except httpx.RequestError:
        fallback_queues = await asyncio.to_thread(_inspect_active_queues_fallback)
        queues = _queue_payloads_from_inspect(fallback_queues)
        return {
            "queues": queues,
            "total": len(queues),
            "expected_queues": _expected_queue_names(),
            "generated_at": datetime.now().isoformat(),
        }
    except Exception as e:
        fallback_queues = await asyncio.to_thread(_inspect_active_queues_fallback)
        queues = _queue_payloads_from_inspect(fallback_queues)
        if queues:
            return {
                "queues": queues,
                "total": len(queues),
                "expected_queues": _expected_queue_names(),
                "generated_at": datetime.now().isoformat(),
            }
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/celery/scheduled-tasks")
async def get_scheduled_tasks_info():
    """
    Получить информацию о запланированных задачах (Celery Beat).

    Returns:
        Список периодических задач
    """
    try:

        celery_app = _get_celery_app()
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
