"""API endpoints для мониторинга Celery."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional, List
from datetime import datetime
import httpx

from app.db.session import AsyncSessionLocal
from app.core.config import settings
from app.tasks.celery_app import celery_app

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


# Flower API base URL
FLOWER_HOST = settings.get_flower_url()


def _inspect_workers_fallback() -> list[str]:
    try:
        inspector = celery_app.control.inspect()
        ping = inspector.ping() or {}
        return list(ping.keys())
    except Exception:
        return []


def _inspect_active_tasks_fallback() -> int:
    try:
        inspector = celery_app.control.inspect()
        active = inspector.active() or {}
        return sum(len(v or []) for v in active.values())
    except Exception:
        return 0


def _safe_dict_values(data):
    if isinstance(data, dict):
        return data.values()
    return []


def _inspect_workers_details_fallback() -> list[dict]:
    try:
        inspector = celery_app.control.inspect()
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


def _inspect_tasks_details_fallback(limit: int = 100, state: Optional[str] = None) -> list[dict]:
    try:
        inspector = celery_app.control.inspect()
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
    Получить статус Celery кластера.
    
    Returns:
        Информация о воркерах и очередях
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            flower_reachable = False
            # Получаем информацию о воркерах из Flower API
            try:
                response = await client.get(f"{FLOWER_HOST}/api/workers")
                if response.status_code == 200:
                    workers_data = response.json()
                    flower_reachable = True
                else:
                    workers_data = {}
                    if response.status_code in {401, 403}:
                        flower_reachable = True
            except Exception:
                workers_data = {}
            
            # Получаем информацию об очередях
            try:
                response = await client.get(f"{FLOWER_HOST}/api/broker/queues")
                if response.status_code == 200:
                    queues_data = response.json()
                    flower_reachable = True
                else:
                    queues_data = {}
                    if response.status_code in {401, 403}:
                        flower_reachable = True
            except Exception:
                queues_data = {}
            
            # Получаем информацию о задачах
            try:
                response = await client.get(f"{FLOWER_HOST}/api/tasks")
                if response.status_code == 200:
                    tasks_data = response.json()
                    flower_reachable = True
                else:
                    tasks_data = {}
                    if response.status_code in {401, 403}:
                        flower_reachable = True
            except Exception:
                tasks_data = {}
        
        # Агрегируем статистику
        workers_count = len(workers_data) if isinstance(workers_data, dict) else 0
        if workers_count == 0:
            workers_count = len(_inspect_workers_fallback())
        active_workers = sum(
            1
            for w in _safe_dict_values(workers_data)
            if isinstance(w, dict)
            and (
                w.get("active", 0) > 0
                or str(w.get("status", "")).lower() == "online"
            )
        )
        
        # Статистика задач
        total_tasks = len(tasks_data) if isinstance(tasks_data, dict) else 0
        active_tasks = sum(
            1
            for t in _safe_dict_values(tasks_data)
            if isinstance(t, dict) and str(t.get("state", "")).lower() == "started"
        )
        if active_tasks == 0:
            active_tasks = _inspect_active_tasks_fallback()
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
        # Если Flower недоступен, возвращаем базовый статус
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
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{FLOWER_HOST}/api/workers")
            
            workers_data = response.json() if response.status_code == 200 else {}
            
            # Форматируем ответ
            workers = []
            for name, info in (workers_data.items() if isinstance(workers_data, dict) else {}):
                workers.append({
                    "name": name,
                    "status": info.get("status", "unknown"),
                    "active_tasks": info.get("active", 0),
                    "processed_tasks": info.get("processed", 0),
                    "queues": info.get("queues", []),
                    "pool": info.get("pool", {}),
                    "timestamp": info.get("timestamp"),
                })

            if len(workers) == 0:
                workers = _inspect_workers_details_fallback()
            
            return {
                "workers": workers,
                "total": len(workers),
                "generated_at": datetime.now().isoformat(),
            }
            
    except httpx.RequestError:
        workers = _inspect_workers_details_fallback()
        return {
            "workers": workers,
            "total": len(workers),
            "generated_at": datetime.now().isoformat(),
        }
    except Exception as e:
        workers = _inspect_workers_details_fallback()
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
    state: Optional[str] = None,
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
        async with httpx.AsyncClient(timeout=5.0) as client:
            params = {"limit": limit}
            if state:
                params["state"] = state
            
            response = await client.get(f"{FLOWER_HOST}/api/tasks", params=params)
            
            tasks_data = response.json() if response.status_code == 200 else {}
            
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
                tasks = _inspect_tasks_details_fallback(limit=limit, state=state)
            
            return {
                "tasks": tasks[:limit],
                "total": len(tasks),
                "limit": limit,
                "generated_at": datetime.now().isoformat(),
            }
            
    except httpx.RequestError:
        tasks = _inspect_tasks_details_fallback(limit=limit, state=state)
        return {
            "tasks": tasks[:limit],
            "total": len(tasks),
            "limit": limit,
            "generated_at": datetime.now().isoformat(),
        }
    except Exception as e:
        tasks = _inspect_tasks_details_fallback(limit=limit, state=state)
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
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{FLOWER_HOST}/api/broker/queues")
            
            if response.status_code != 200:
                # Если API очередей недоступно, возвращаем базовую информацию
                return {
                    "queues": [
                        {"name": "celery", "messages": 0, "consumers": 1},
                    ],
                    "total": 1,
                    "generated_at": datetime.now().isoformat(),
                }
            
            queues_data = response.json()
            
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
            "daily-parse-all-sources": "Ежедневный полный парсинг всех источников (CORE + arXiv)",
            "weekly-parse-all-sources": "Еженедельный полный парсинг всех источников (CORE + arXiv)",
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
