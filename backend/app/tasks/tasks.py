import time
from typing import Any

from celery.result import AsyncResult
from loguru import logger
from sqlalchemy import select

from app.db.models.task import PatentTask
from app.db.session import async_session_maker

from .celery_app import celery_app


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

        # Если задача завершена, получаем результат
        if result.ready():
            try:
                task_info["result"] = result.get(timeout=1)
            except Exception as e:
                task_info["error"] = str(e)

        # Получаем метаданные задачи если доступны
        if result.info and isinstance(result.info, dict):
            task_info["info"] = result.info

        return task_info

    except Exception as e:
        logger.error(f"Ошибка получения статуса задачи {task_id}: {e}")
        return None


@celery_app.task(bind=True)
def process_patent(self, task_id: int, patent_number: str, options: dict):
    """Фоновая обработка патента."""
    try:
        # Обновляем статус на processing
        import asyncio
        asyncio.run(update_task_status(task_id, "processing"))

        # Имитация долгой работы (парсинг, ML анализ и т.д.)
        time.sleep(10)

        # Результат обработки
        result = {
            "patent": patent_number,
            "analysis": "some result",
            "status": "completed"
        }

        # Обновляем статус на completed
        asyncio.run(update_task_status(task_id, "completed", result))

        return result

    except Exception as e:
        logger.error(f"Ошибка обработки патента {patent_number}: {e}")
        # Обновляем статус на failed
        import asyncio
        asyncio.run(update_task_status(task_id, "failed", {"error": str(e)}))
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
