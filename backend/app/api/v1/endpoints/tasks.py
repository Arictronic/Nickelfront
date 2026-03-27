from fastapi import APIRouter, HTTPException, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.task_service import create_task, get_task_by_id
from app.db.session import get_db
from app.tasks.tasks import get_celery_task_status
from shared.schemas.task import TaskCreate, TaskOut, CeleryTaskStatus
from typing import Optional

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
    task_info = get_celery_task_status(task_id)
    
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