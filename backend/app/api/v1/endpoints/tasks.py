import asyncio

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.celery_cancel import clear_cancel_flag, set_cancel_flag
from app.services.task_service import create_task, get_task_by_id
from app.tasks.celery_app import celery_app
from app.tasks.tasks import get_celery_task_status
from shared.schemas.task import CeleryTaskStatus, TaskCreate, TaskOut

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/", response_model=TaskOut)
async def create_patent_task(task: TaskCreate, db: AsyncSession = Depends(get_db)):
    """Создать задачу на обработку патента."""
    try:
        result = await create_task(db, task.dict())
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{task_id}", response_model=TaskOut)
async def get_task_status(task_id: int, db: AsyncSession = Depends(get_db)):
    """Получить статус задачи по ID."""
    task = await get_task_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return task


@router.get("/celery/{task_id}/status", response_model=CeleryTaskStatus)
async def get_celery_task_status_endpoint(
    task_id: str = Path(..., description="Celery task UUID")
):
    """
    Получить статус задачи Celery по task_id.

    Возвращает текущий статус задачи (PENDING, STARTED, RETRY, FAILURE, SUCCESS)
    и результат выполнения если задача завершена.
    """
    task_info = await asyncio.to_thread(get_celery_task_status, task_id)

    if task_info is None:
        raise HTTPException(status_code=404, detail="Задача Celery не найдена")

    # Преобразуем результат в формат CeleryTaskStatus
    result = task_info.get("result")

    response = CeleryTaskStatus(
        task_id=task_id,
        status=task_info.get("status", "UNKNOWN"),
        state=task_info.get("state"),
        result=result if isinstance(result, dict) else None,
        progress=result.get("progress") if isinstance(result, dict) else None,
        query=result.get("query") if isinstance(result, dict) else None,
        source=result.get("source") if isinstance(result, dict) else None,
        current=result.get("current") if isinstance(result, dict) else None,
        total=result.get("total") if isinstance(result, dict) else None,
        saved_count=result.get("saved_count") if isinstance(result, dict) else None,
        embedded_count=result.get("embedded_count") if isinstance(result, dict) else None,
        errors=result.get("errors") if isinstance(result, dict) else None,
        name=task_info.get("name"),
        args=task_info.get("args"),
        kwargs=task_info.get("kwargs"),
    )

    return response


@router.post("/celery/{task_id}/revoke")
async def revoke_celery_task(
    task_id: str = Path(..., description="Celery task UUID"),
    terminate: bool = False,
):
    """
    Отменить задачу Celery по task_id.

    Примечание: на Windows с pool=solo завершение запущенной задачи
    через terminate может остановить весь воркер, поэтому по умолчанию terminate=False.
    """
    current_state = await asyncio.to_thread(lambda: AsyncResult(task_id, app=celery_app).state)

    if current_state in {"SUCCESS", "FAILURE", "REVOKED"}:
        return {
            "task_id": task_id,
            "status": current_state,
            "message": "Task already finished",
        }

    await asyncio.to_thread(set_cancel_flag, task_id)
    await asyncio.to_thread(celery_app.control.revoke, task_id, terminate=terminate)

    return {
        "task_id": task_id,
        "status": "REVOKED",
        "previous_state": current_state,
        "terminate": terminate,
    }


@router.delete("/celery/{task_id}")
async def delete_celery_task(
    task_id: str = Path(..., description="Celery task UUID"),
):
    """
    Удалить задачу Celery по task_id.

    Удаляет флаг отмены из Redis (если существует).
    Примечание: это не удаляет задачу из истории Celery/Flower,
    только очищает флаг отмены для возможности повторного запуска.
    """
    try:
        await asyncio.to_thread(clear_cancel_flag, task_id)
        return {
            "task_id": task_id,
            "status": "deleted",
            "message": "Флаг отмены удалён из Redis",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при удалении: {str(e)}")
