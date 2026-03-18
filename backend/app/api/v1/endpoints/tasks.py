from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.task_service import create_task, get_task_by_id
from app.db.session import get_db
from shared.schemas.task import TaskCreate, TaskOut

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