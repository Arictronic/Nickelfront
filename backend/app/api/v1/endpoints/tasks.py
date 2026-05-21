import asyncio
from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin_user
from app.db.session import get_db
from app.services.celery_cancel import clear_cancel_flag, set_cancel_flag
from app.services.parse_job_history import list_parse_jobs, remove_parse_job
from app.services.alloy_analysis_service import (
    build_alloy_analysis_prompt,
    get_alloy_analysis_prompt,
    list_saved_alloy_analysis_results,
    save_alloy_analysis_prompt,
)
from app.services.task_service import create_task, get_task_by_id
from app.tasks.alloy_analysis_tasks import analyze_papers_alloys_task, extract_alloys_task
from app.tasks.celery_app import celery_app
from app.tasks.tasks import get_celery_task_status
from shared.schemas.auth import UserResponse
from shared.schemas.task import CeleryTaskStatus, TaskCreate, TaskOut

router = APIRouter(prefix="/tasks", tags=["tasks"])


class AlloyAnalysisRequest(BaseModel):
    document_id: str = Field(default="unknown", max_length=200)
    text: str = Field(..., min_length=1, max_length=45000)


class AlloyBatchAnalysisRequest(BaseModel):
    id_spec: str | None = Field(default=None, max_length=1000)
    sources: list[str] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=1000)


class AlloyPromptUpdateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=30000)




def _get_result_value(result: dict | None, *keys: str):
    if not isinstance(result, dict):
        return None
    for key in keys:
        value = result.get(key)
        if value is not None:
            return value
    return None

def _extract_inspected_task_id(item: dict) -> str | None:
    request = item.get("request") if isinstance(item.get("request"), dict) else {}
    task_id = item.get("id") or request.get("id")
    return str(task_id) if task_id else None


def _inspect_revoke_candidates() -> list[str]:
    inspector = celery_app.control.inspect(timeout=2.0)
    inspected_groups = [
        inspector.active() or {},
        inspector.reserved() or {},
        inspector.scheduled() or {},
    ]

    task_ids: set[str] = set()
    for group in inspected_groups:
        if not isinstance(group, dict):
            continue
        for entries in group.values():
            for item in entries or []:
                if not isinstance(item, dict):
                    continue
                task_id = _extract_inspected_task_id(item)
                if task_id:
                    task_ids.add(task_id)

    return sorted(task_ids)



@router.post("/", response_model=TaskOut)
async def create_patent_task(
    task: TaskCreate,
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Создать задачу на обработку патента."""
    try:
        result = await create_task(db, task.dict())
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/parse-jobs")
async def get_shared_parse_jobs(
    limit: int = 50,
    _current_user: UserResponse = Depends(get_current_user),
):
    return {"jobs": await asyncio.to_thread(list_parse_jobs, limit)}


@router.delete("/parse-jobs/{job_id}")
async def delete_shared_parse_job(
    job_id: str,
    _current_user: UserResponse = Depends(get_current_user),
):
    removed = await asyncio.to_thread(remove_parse_job, job_id)
    return {"job_id": job_id, "deleted": removed}


@router.get("/{task_id}", response_model=TaskOut)
async def get_task_status(
    task_id: int,
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить статус задачи по ID."""
    task = await get_task_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return task


@router.get("/celery/{task_id}/status", response_model=CeleryTaskStatus)
async def get_celery_task_status_endpoint(
    task_id: str = Path(..., description="Celery task UUID"),
    _current_user: UserResponse = Depends(get_current_user),
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
    if not isinstance(result, dict) and isinstance(task_info.get("info"), dict):
        result = task_info.get("info")

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
        saved_count=_get_result_value(result, "saved_count", "total_saved"),
        embedded_count=_get_result_value(result, "embedded_count"),
        content_queued_count=_get_result_value(result, "content_queued_count", "total_content_queued"),
        content_skipped_count=_get_result_value(result, "content_skipped_count", "total_content_skipped"),
        total_saved=_get_result_value(result, "total_saved", "saved_count"),
        total_content_queued=_get_result_value(result, "total_content_queued", "content_queued_count"),
        total_content_skipped=_get_result_value(result, "total_content_skipped", "content_skipped_count"),
        errors=result.get("errors") if isinstance(result, dict) else None,
        name=task_info.get("name"),
        args=task_info.get("args"),
        kwargs=task_info.get("kwargs"),
    )

    return response


@router.post("/celery/alloy-analysis")
async def create_alloy_analysis_task(
    request: AlloyAnalysisRequest,
    _current_user: UserResponse = Depends(get_current_user),
):
    prompt = build_alloy_analysis_prompt(request.document_id, request.text)
    if len(prompt) > 50000:
        raise HTTPException(
            status_code=413,
            detail="Text is too long for Qwen: maximum 50000 characters including the prompt",
        )

    task = extract_alloys_task.delay(request.document_id, request.text)
    return {
        "task_id": task.id,
        "status": "queued",
        "document_id": request.document_id,
    }


@router.post("/celery/alloy-analysis/batch")
async def create_alloy_batch_analysis_task(
    request: AlloyBatchAnalysisRequest,
    _current_user: UserResponse = Depends(get_current_user),
):
    task = analyze_papers_alloys_task.delay(
        request.id_spec,
        request.sources,
        request.limit,
    )
    return {
        "task_id": task.id,
        "status": "queued",
        "id_spec": request.id_spec,
        "sources": request.sources,
        "limit": request.limit,
    }


@router.get("/celery/alloy-analysis/results")
async def get_alloy_analysis_results(
    limit: int = 200,
    _current_user: UserResponse = Depends(get_current_user),
):
    return {
        "results": await asyncio.to_thread(list_saved_alloy_analysis_results, limit),
    }


@router.get("/celery/alloy-analysis/prompt")
async def get_alloy_prompt(
    _current_user: UserResponse = Depends(get_current_user),
):
    prompt = await asyncio.to_thread(get_alloy_analysis_prompt)
    return {"prompt": prompt}


@router.put("/celery/alloy-analysis/prompt")
async def update_alloy_prompt(
    request: AlloyPromptUpdateRequest,
    _current_user: UserResponse = Depends(get_current_user),
):
    prompt = await asyncio.to_thread(save_alloy_analysis_prompt, request.prompt)
    return {"prompt": prompt, "status": "saved"}


@router.post("/celery/queues/stop")
async def stop_celery_queues(
    terminate: bool = False,
    _admin=Depends(require_admin_user),
):
    """
    Emergency stop for Celery queues.

    Revokes active/reserved/scheduled tasks and purges waiting messages from the broker.
    By default terminate=False to avoid killing the worker process on Windows/solo pools.
    """
    try:
        task_ids = await asyncio.to_thread(_inspect_revoke_candidates)

        for task_id in task_ids:
            await asyncio.to_thread(set_cancel_flag, task_id)
            await asyncio.to_thread(celery_app.control.revoke, task_id, terminate=terminate)

        purged = await asyncio.to_thread(celery_app.control.purge)

        return {
            "status": "stopped",
            "revoked": len(task_ids),
            "task_ids": task_ids,
            "purged": int(purged or 0),
            "terminate": terminate,
            "message": "Celery queues stopped: active tasks revoked and waiting messages purged",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка остановки очередей: {str(e)}")


@router.post("/celery/{task_id}/revoke")
async def revoke_celery_task(
    task_id: str = Path(..., description="Celery task UUID"),
    terminate: bool = False,
    _current_user: UserResponse = Depends(get_current_user),
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
    _current_user: UserResponse = Depends(get_current_user),
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
