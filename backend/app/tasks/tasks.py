import re
import time
from typing import Any

from celery.result import AsyncResult
from loguru import logger
from sqlalchemy import select

from app.db.models.task import PatentTask
from app.db.session import async_session_maker

from .async_runner import run_async
from .celery_app import celery_app


_TASK_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9:_-]{15,}$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _looks_like_task_id(value: Any) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    if raw.lower().startswith(("test-", "test_", "mock-", "mock_", "demo-", "demo_")):
        return False
    return bool(_UUID_RE.match(raw) or (_TASK_ID_RE.match(raw) and any(ch in raw for ch in "-_:")))


def _collect_task_ids_from_payload(value: Any, result: set[str] | None = None, depth: int = 0) -> set[str]:
    if result is None:
        result = set()
    if depth > 10 or value is None:
        return result
    if isinstance(value, str):
        if _looks_like_task_id(value):
            result.add(value.strip())
        return result
    if isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_task_ids_from_payload(item, result, depth + 1)
        return result
    if isinstance(value, dict):
        for key, item in value.items():
            if re.search(r"task|celery|child|children|chain|group|chord|workflow|qwen|content|pdf|embedding|markdown|keyword|result|meta|progress|id", str(key), re.I) or isinstance(item, (dict, list, tuple, set)):
                _collect_task_ids_from_payload(item, result, depth + 1)
    return result


def _collect_async_result_children(async_result: AsyncResult, task_ids: set[str], children: list[dict[str, Any]], depth: int = 0) -> None:
    if depth > 4:
        return
    try:
        raw_children = list(async_result.children or [])
    except Exception:
        raw_children = []
    for child in raw_children:
        child_id = str(getattr(child, "id", "") or "").strip()
        if not child_id:
            continue
        task_ids.add(child_id)
        child_summary = {
            "task_id": child_id,
            "status": getattr(child, "status", None),
            "state": getattr(child, "state", None),
        }
        children.append(child_summary)
        try:
            child_info = getattr(child, "info", None)
            if isinstance(child_info, dict):
                _collect_task_ids_from_payload(child_info, task_ids)
        except Exception:
            pass
        _collect_async_result_children(child, task_ids, children, depth + 1)


def get_celery_task_status(task_id: str) -> dict[str, Any] | None:
    """
    Получить статус задачи Celery по task_id.

    Args:
        task_id: UUID задачи Celery

    Returns:
        Dict со статусом задачи или None если задача не найдена
    """
    try:
        result = AsyncResult(task_id, app=celery_app)

        task_info = {
            "task_id": task_id,
            "status": result.status,
            "state": result.state,
            "ready": result.ready(),
            "successful": result.successful() if result.ready() else None,
        }


        if result.ready():
            try:
                task_info["result"] = result.get(timeout=1)
            except Exception as e:
                task_info["error"] = str(e)


        if result.info and isinstance(result.info, dict):
            task_info["info"] = result.info

        related_task_ids: set[str] = {str(task_id)}
        child_summaries: list[dict[str, Any]] = []
        _collect_task_ids_from_payload(task_info.get("result"), related_task_ids)
        _collect_task_ids_from_payload(task_info.get("info"), related_task_ids)
        for payload in (task_info.get("result"), task_info.get("info")):
            if not isinstance(payload, dict):
                continue
            if isinstance(payload.get("stage_task_ids"), dict) and "stage_task_ids" not in task_info:
                task_info["stage_task_ids"] = payload.get("stage_task_ids")
            if isinstance(payload.get("stage_tasks"), list) and "stage_tasks" not in task_info:
                task_info["stage_tasks"] = payload.get("stage_tasks")
        _collect_async_result_children(result, related_task_ids, child_summaries)
        task_info["child_task_ids"] = [item["task_id"] for item in child_summaries if item.get("task_id")][:300]
        task_info["children"] = child_summaries[:100]
        task_info["related_task_ids"] = sorted(related_task_ids)[:500]

        return task_info

    except Exception as e:
        logger.error(f"Ошибка получения статуса задачи {task_id}: {e}")
        return None


@celery_app.task(bind=True)
def process_patent(self, task_id: int, patent_number: str, options: dict):
    """Фоновая обработка патента."""
    try:

        run_async(update_task_status(task_id, "processing"))


        time.sleep(10)


        result = {
            "patent": patent_number,
            "analysis": "some result",
            "status": "completed"
        }


        run_async(update_task_status(task_id, "completed", result))

        return result

    except Exception as e:
        logger.error(f"Ошибка обработки патента {patent_number}: {e}")

        run_async(update_task_status(task_id, "failed", {"error": str(e)}))
        raise


async def update_task_status(task_id: int, status: str, result: dict = None):
    """Обновить статус задачи в БД."""
    async with async_session_maker() as session:
        stmt = select(PatentTask).where(PatentTask.id == task_id)
        result_stmt = await session.execute(stmt)
        task = result_stmt.scalar_one_or_none()

        if task:
            task.status = status
            if result is not None:
                task.result = result
            await session.commit()
            logger.info(f"Задача {task_id} обновлена: статус={status}")
