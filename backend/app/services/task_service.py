from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models.task import PatentTask
from app.tasks.tasks import process_patent


async def create_task(db: AsyncSession, task_data: dict) -> PatentTask:
    """Создать задачу в БД и отправить в Celery."""
    # 1. Создаём запись в БД
    db_task = PatentTask(
        patent_number=task_data["patent_number"],
        status="pending",
        input_data=task_data.get("options", {}),
    )
    db.add(db_task)
    await db.commit()
    await db.refresh(db_task)

    # 2. Отправляем в Celery
    process_patent.delay(db_task.id, task_data["patent_number"], task_data.get("options", {}))

    return db_task


async def get_task_by_id(db: AsyncSession, task_id: int) -> Optional[PatentTask]:
    """Получить задачу по ID."""
    result = await db.execute(select(PatentTask).where(PatentTask.id == task_id))
    return result.scalar_one_or_none()


async def update_task_status(
    db: AsyncSession,
    task_id: int,
    status: str,
    result: Optional[Dict[str, Any]] = None
) -> Optional[PatentTask]:
    """Обновить статус задачи."""
    task = await get_task_by_id(db, task_id)
    if not task:
        return None

    task.status = status
    if result is not None:
        task.result = result

    await db.commit()
    await db.refresh(task)
    return task
