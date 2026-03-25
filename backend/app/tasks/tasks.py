from .celery_app import celery_app
from app.db.session import AsyncSessionLocal
from app.db.models.task import PatentTask
from sqlalchemy import select
import time
from loguru import logger


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
    async with AsyncSessionLocal() as session:
        stmt = select(PatentTask).where(PatentTask.id == task_id)
        result_stmt = await session.execute(stmt)
        task = result_stmt.scalar_one_or_none()
        
        if task:
            task.status = status
            if result is not None:
                task.result = result
            await session.commit()
            logger.info(f"Задача {task_id} обновлена: статус={status}")
