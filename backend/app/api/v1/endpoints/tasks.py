import asyncio
import time
from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin_user
from app.db.session import get_db
from app.services.celery_cancel import clear_cancel_flag, set_cancel_flag
from app.services.parse_job_history import list_parse_jobs, remove_parse_job, update_parse_job
from app.services.parse_admission_service import clear_parse_admission_slots, release_parse_slot
from app.services import task_lifecycle_status as lifecycle
from app.services.alloy_analysis_service import (
    build_alloy_analysis_prompt,
    get_alloy_analysis_prompt,
    list_saved_alloy_analysis_results,
    save_alloy_analysis_prompt,
)
from app.services.task_service import create_task, get_task_by_id
from shared.schemas.auth import UserResponse
from shared.schemas.task import CeleryTaskStatus, TaskCreate, TaskOut

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get_celery_app():
    from app.tasks.celery_app import celery_app

    return celery_app


def _get_celery_task_status_func():
    from app.tasks.tasks import get_celery_task_status

    return get_celery_task_status


def _get_alloy_tasks():
    from app.tasks.alloy_analysis_tasks import analyze_papers_alloys_task, extract_alloys_task

    return analyze_papers_alloys_task, extract_alloys_task


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
    celery_app = _get_celery_app()
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


def _result_payload_from_task_info(task_info: dict | None) -> dict | None:
    if not isinstance(task_info, dict):
        return None
    result = task_info.get("result")
    if not isinstance(result, dict) and isinstance(task_info.get("info"), dict):
        result = task_info.get("info")
    return result if isinstance(result, dict) else None




def _compact_child_payload(payload: dict | None) -> dict | None:
    return lifecycle.compact_child_payload(payload)


def _result_is_partial(result: dict | None) -> bool:
    return lifecycle.result_is_partial(result)


def _related_statuses(task_info: dict | None) -> list[dict]:
    return lifecycle.related_statuses(task_info)


def _downstream_is_active(task_info: dict | None, *, stale_after_ms: int | None = None) -> bool:
    return lifecycle.downstream_is_active(task_info, stale_after_ms=stale_after_ms)


def _downstream_has_failure(task_info: dict | None) -> bool:
    return lifecycle.downstream_has_failure(task_info)


def _parse_job_status_from_celery(
    celery_status: str | None,
    result: dict | None = None,
    task_info: dict | None = None,
    *,
    stale_after_ms: int | None = None,
) -> str:
    return lifecycle.parse_job_status_from_celery(celery_status, result, task_info, stale_after_ms=stale_after_ms)


def _job_has_downstream_lifecycle(job: dict | None) -> bool:
    celery = job.get("celeryStatus") if isinstance(job, dict) and isinstance(job.get("celeryStatus"), dict) else {}
    return any(
        celery.get(key)
        for key in ("related_child_statuses", "related_task_ids", "stage_task_ids", "stage_tasks", "child_task_ids")
    ) or bool(isinstance(job, dict) and (job.get("contentQueuedCount") or 0))


def _should_sync_parse_job(job: dict | None) -> bool:
    if not isinstance(job, dict):
        return False
    status = str(job.get("status") or "in_progress")
    if status == "in_progress":
        return True
    if status not in {"completed", "partial"}:
        return False
    if not _job_has_downstream_lifecycle(job):
        return False
    now_ms = int(time.time() * 1000)
    try:
        started_ms = int(job.get("startedAt") or now_ms)
    except (TypeError, ValueError):
        started_ms = now_ms
    return now_ms - started_ms <= 24 * 60 * 60 * 1000


def _build_parse_job_patch(task_id: str, task_info: dict | None, job: dict | None = None) -> dict:
    result = _result_payload_from_task_info(task_info)
    celery_status = str((task_info or {}).get("status") or "UNKNOWN")
    now_ms = int(time.time() * 1000)
    started_ms = int((job or {}).get("startedAt") or now_ms)
    last_change_ms = int((job or {}).get("lastCountChangeAt") or started_ms)
    stale_after_ms = max(0, now_ms - last_change_ms)

    patch = {
        "status": lifecycle.parse_job_status_from_celery(celery_status, result, task_info, stale_after_ms=stale_after_ms),
        "lastPolledAt": now_ms,
        "celeryStatus": {
            "task_id": task_id,
            "status": celery_status,
            "state": (task_info or {}).get("state"),
            "result": result,
            "progress": result.get("progress") if isinstance(result, dict) else None,
            "query": result.get("query") if isinstance(result, dict) else None,
            "source": result.get("source") if isinstance(result, dict) else None,
            "current": result.get("current") if isinstance(result, dict) else None,
            "total": result.get("total") if isinstance(result, dict) else None,
            "saved_count": _get_result_value(result, "saved_count", "total_saved"),
            "updated_count": _get_result_value(result, "updated_count", "total_updated"),
            "duplicate_count": _get_result_value(result, "duplicate_count", "total_duplicates"),
            "embedded_count": _get_result_value(result, "embedded_count"),
            "content_queued_count": _get_result_value(result, "content_queued_count", "total_content_queued"),
            "content_skipped_count": _get_result_value(result, "content_skipped_count", "total_content_skipped"),
            "total_saved": _get_result_value(result, "total_saved", "saved_count"),
            "total_updated": _get_result_value(result, "total_updated", "updated_count"),
            "total_duplicates": _get_result_value(result, "total_duplicates", "duplicate_count"),
            "total_content_queued": _get_result_value(result, "total_content_queued", "content_queued_count"),
            "total_content_skipped": _get_result_value(result, "total_content_skipped", "content_skipped_count"),
            "errors": result.get("errors") if isinstance(result, dict) else None,
            "pipeline_error": _get_result_value(result, "pipeline_error"),
            "failed_stage": _get_result_value(result, "failed_stage", "first_failed_stage"),
            "pipeline_error_message": _get_result_value(result, "pipeline_error_message", "error_message"),
            "stage_errors": result.get("stage_errors") if isinstance(result, dict) else None,
            "final_stage": _get_result_value(result, "final_stage"),
            "name": (task_info or {}).get("name"),
            "args": (task_info or {}).get("args"),
            "kwargs": (task_info or {}).get("kwargs"),
            "child_task_ids": (task_info or {}).get("child_task_ids"),
            "children": (task_info or {}).get("children"),
            "related_child_statuses": (task_info or {}).get("related_child_statuses"),
            "related_task_ids": (task_info or {}).get("related_task_ids"),
            "stage_task_ids": (task_info or {}).get("stage_task_ids"),
            "stage_tasks": (task_info or {}).get("stage_tasks"),
        },
        "relatedTaskIds": (task_info or {}).get("related_task_ids"),
    }

    saved_count = _get_result_value(result, "saved_count", "total_saved")
    updated_count = _get_result_value(result, "updated_count", "total_updated")
    duplicate_count = _get_result_value(result, "duplicate_count", "total_duplicates")
    content_queued_count = _get_result_value(result, "content_queued_count", "total_content_queued")
    content_skipped_count = _get_result_value(result, "content_skipped_count", "total_content_skipped")

    if saved_count is not None:
        patch["savedCount"] = saved_count
    if updated_count is not None:
        patch["updatedCount"] = updated_count
    if duplicate_count is not None:
        patch["duplicateCount"] = duplicate_count
    if content_queued_count is not None:
        patch["contentQueuedCount"] = content_queued_count
    if content_skipped_count is not None:
        patch["contentSkippedCount"] = content_skipped_count
    if patch["status"] != "in_progress" or any(key in patch for key in ("savedCount", "updatedCount", "duplicateCount", "contentQueuedCount")):
        patch["lastCountChangeAt"] = now_ms

    return patch



def _merge_related_task_ids(task_info: dict | None, extra_ids: set[str]) -> dict | None:
    if not isinstance(task_info, dict):
        return task_info
    current = task_info.get("related_task_ids")
    ids = {str(item).strip() for item in current or [] if str(item or "").strip()}
    ids.update(extra_ids)
    if ids:
        task_info["related_task_ids"] = sorted(ids)[:500]
    return task_info


async def _enrich_task_info_with_related_children(task_info: dict | None, max_children: int = 120) -> dict | None:
    """Load related content/Qwen stage statuses for parse-job details.

    The content wrapper returns stage_task_ids after it queues the Celery chain.
    We walk a few lightweight BFS rounds so root parse jobs can show real
    download/extract/Qwen/embedding/finalize statuses instead of only wrapper ids.
    """
    if not isinstance(task_info, dict):
        return task_info

    root_id = str(task_info.get("task_id") or "").strip()
    pending: list[str] = []
    seen: set[str] = {root_id} if root_id else set()
    discovered: set[str] = {str(item).strip() for item in task_info.get("related_task_ids") or [] if str(item or "").strip()}
    discovered.update(str(item).strip() for item in task_info.get("child_task_ids") or [] if str(item or "").strip())

    for item in sorted(discovered):
        if item and item not in seen:
            pending.append(item)
            seen.add(item)

    if not pending:
        return task_info

    get_celery_task_status = _get_celery_task_status_func()
    child_statuses: list[dict] = []

    while pending and len(child_statuses) < max_children:
        child_id = pending.pop(0)
        child_info = await asyncio.to_thread(get_celery_task_status, child_id)
        if not isinstance(child_info, dict):
            continue

        result_payload = child_info.get("result") if isinstance(child_info.get("result"), dict) else None
        info_payload = child_info.get("info") if isinstance(child_info.get("info"), dict) else None
        stage_task_ids = None
        stage_tasks = None
        for payload in (result_payload, info_payload):
            if not isinstance(payload, dict):
                continue
            if isinstance(payload.get("stage_task_ids"), dict):
                stage_task_ids = payload.get("stage_task_ids")
            if isinstance(payload.get("stage_tasks"), list):
                stage_tasks = payload.get("stage_tasks")

        child_statuses.append(
            {
                "task_id": child_id,
                "status": child_info.get("status"),
                "state": child_info.get("state"),
                "name": child_info.get("name"),
                "stage_task_ids": stage_task_ids,
                "stage_tasks": stage_tasks,
                "related_task_ids": child_info.get("related_task_ids"),
                "child_task_ids": child_info.get("child_task_ids"),
                "children": child_info.get("children"),
                "result": lifecycle.compact_child_payload(result_payload),
                "info": lifecycle.compact_child_payload(info_payload),
            }
        )

        for nested_id in child_info.get("related_task_ids") or []:
            nested_id = str(nested_id or "").strip()
            if nested_id and nested_id not in seen:
                discovered.add(nested_id)
                pending.append(nested_id)
                seen.add(nested_id)
        for nested_id in child_info.get("child_task_ids") or []:
            nested_id = str(nested_id or "").strip()
            if nested_id and nested_id not in seen:
                discovered.add(nested_id)
                pending.append(nested_id)
                seen.add(nested_id)
        for payload in (result_payload, info_payload):
            if not isinstance(payload, dict):
                continue
            for nested_id in (payload.get("stage_task_ids") or {}).values() if isinstance(payload.get("stage_task_ids"), dict) else []:
                nested_id = str(nested_id or "").strip()
                if nested_id and nested_id not in seen:
                    discovered.add(nested_id)
                    pending.append(nested_id)
                    seen.add(nested_id)

    if child_statuses:
        task_info["related_child_statuses"] = child_statuses[:max_children]
    task_info = _merge_related_task_ids(task_info, discovered)

    # Promote stage metadata to root task_info so frontend does not have to dig
    # into wrapper.result manually. Prefer the first wrapper payload with stages.
    for child in child_statuses:
        if not task_info.get("stage_task_ids") and isinstance(child.get("stage_task_ids"), dict):
            task_info["stage_task_ids"] = child.get("stage_task_ids")
        if not task_info.get("stage_tasks") and isinstance(child.get("stage_tasks"), list):
            task_info["stage_tasks"] = child.get("stage_tasks")

    return task_info


async def _sync_parse_job_from_celery(task_id: str, task_info: dict | None, job: dict | None = None) -> dict | None:
    if task_info is None:
        return None
    patch = _build_parse_job_patch(task_id, task_info, job)
    return await asyncio.to_thread(update_parse_job, task_id, patch)



@router.post("/", response_model=TaskOut)
async def create_patent_task(
    task: TaskCreate,
    _current_user: UserResponse = Depends(require_admin_user),
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
    jobs = await asyncio.to_thread(list_parse_jobs, limit)
    get_celery_task_status = _get_celery_task_status_func()

    synced_jobs = []
    for job in jobs:
        task_id = str(job.get("jobId") or "")
        if not task_id or not _should_sync_parse_job(job):
            synced_jobs.append(job)
            continue

        task_info = await asyncio.to_thread(get_celery_task_status, task_id)
        task_info = await _enrich_task_info_with_related_children(task_info)
        synced = await _sync_parse_job_from_celery(task_id, task_info, job)
        synced_jobs.append(synced or job)

    return {"jobs": synced_jobs[:limit]}


@router.delete("/parse-jobs/{job_id}")
async def delete_shared_parse_job(
    job_id: str,
    _current_user: UserResponse = Depends(require_admin_user),
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
    get_celery_task_status = _get_celery_task_status_func()
    task_info = await asyncio.to_thread(get_celery_task_status, task_id)
    task_info = await _enrich_task_info_with_related_children(task_info)

    if task_info is None:
        raise HTTPException(status_code=404, detail="Задача Celery не найдена")


    result = _result_payload_from_task_info(task_info)
    await _sync_parse_job_from_celery(task_id, task_info)

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
        updated_count=_get_result_value(result, "updated_count", "total_updated"),
        duplicate_count=_get_result_value(result, "duplicate_count", "total_duplicates"),
        embedded_count=_get_result_value(result, "embedded_count"),
        content_queued_count=_get_result_value(result, "content_queued_count", "total_content_queued"),
        content_skipped_count=_get_result_value(result, "content_skipped_count", "total_content_skipped"),
        total_saved=_get_result_value(result, "total_saved", "saved_count"),
        total_updated=_get_result_value(result, "total_updated", "updated_count"),
        total_duplicates=_get_result_value(result, "total_duplicates", "duplicate_count"),
        total_content_queued=_get_result_value(result, "total_content_queued", "content_queued_count"),
        total_content_skipped=_get_result_value(result, "total_content_skipped", "content_skipped_count"),
        errors=result.get("errors") if isinstance(result, dict) else None,
        pipeline_error=bool(result.get("pipeline_error")) if isinstance(result, dict) and result.get("pipeline_error") is not None else None,
        failed_stage=_get_result_value(result, "failed_stage", "first_failed_stage"),
        pipeline_error_message=_get_result_value(result, "pipeline_error_message", "error_message"),
        stage_errors=result.get("stage_errors") if isinstance(result, dict) and isinstance(result.get("stage_errors"), list) else None,
        final_stage=_get_result_value(result, "final_stage"),
        name=task_info.get("name"),
        args=task_info.get("args"),
        kwargs=task_info.get("kwargs"),
        child_task_ids=task_info.get("child_task_ids"),
        children=task_info.get("children"),
        related_child_statuses=task_info.get("related_child_statuses"),
        related_task_ids=task_info.get("related_task_ids"),
        stage_task_ids=task_info.get("stage_task_ids"),
        stage_tasks=task_info.get("stage_tasks"),
    )

    return response


@router.post("/celery/alloy-analysis")
async def create_alloy_analysis_task(
    request: AlloyAnalysisRequest,
    _current_user: UserResponse = Depends(require_admin_user),
):
    prompt = build_alloy_analysis_prompt(request.document_id, request.text)
    if len(prompt) > 50000:
        raise HTTPException(
            status_code=413,
            detail="Text is too long for Qwen: maximum 50000 characters including the prompt",
        )

    _, extract_alloys_task = _get_alloy_tasks()
    task = extract_alloys_task.delay(request.document_id, request.text)
    return {
        "task_id": task.id,
        "status": "queued",
        "document_id": request.document_id,
    }


@router.post("/celery/alloy-analysis/batch")
async def create_alloy_batch_analysis_task(
    request: AlloyBatchAnalysisRequest,
    _current_user: UserResponse = Depends(require_admin_user),
):
    analyze_papers_alloys_task, _ = _get_alloy_tasks()
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
    _current_user: UserResponse = Depends(require_admin_user),
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
            await asyncio.to_thread(
                update_parse_job,
                task_id,
                {"status": "cancelled", "lastPolledAt": int(time.time() * 1000), "lastCountChangeAt": int(time.time() * 1000)},
            )
            await asyncio.to_thread(release_parse_slot, task_id)
            celery_app = _get_celery_app()
            await asyncio.to_thread(celery_app.control.revoke, task_id, terminate=terminate)

        celery_app = _get_celery_app()
        purged = await asyncio.to_thread(celery_app.control.purge)
        cleared_parse_slots = await asyncio.to_thread(clear_parse_admission_slots)

        return {
            "status": "queues_purged",
            "revoked": len(task_ids),
            "task_ids": task_ids,
            "purged": int(purged or 0),
            "cleared_parse_admission_slots": cleared_parse_slots,
            "terminate": terminate,
            "message": "Cancel requested for inspected tasks; waiting broker messages purged",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка остановки очередей: {str(e)}")


@router.post("/celery/{task_id}/revoke")
async def revoke_celery_task(
    task_id: str = Path(..., description="Celery task UUID"),
    terminate: bool = False,
    _current_user: UserResponse = Depends(require_admin_user),
):
    """
    Отменить задачу Celery по task_id.

    Примечание: на Windows с pool=solo завершение запущенной задачи
    через terminate может остановить весь воркер, поэтому по умолчанию terminate=False.
    """
    celery_app = _get_celery_app()
    current_state = await asyncio.to_thread(lambda: AsyncResult(task_id, app=celery_app).state)

    if current_state in {"SUCCESS", "FAILURE", "REVOKED"}:
        parse_slot_released = await asyncio.to_thread(release_parse_slot, task_id)
        return {
            "task_id": task_id,
            "status": current_state,
            "parse_slot_released": parse_slot_released,
            "message": "Task already finished",
        }

    await asyncio.to_thread(set_cancel_flag, task_id)
    now_ms = int(time.time() * 1000)
    await asyncio.to_thread(
        update_parse_job,
        task_id,
        {
            "status": "cancelled",
            "lastPolledAt": now_ms,
            "lastCountChangeAt": now_ms,
            "celeryStatus": {"task_id": task_id, "status": "REVOKED", "state": "REVOKED"},
        },
    )
    await asyncio.to_thread(celery_app.control.revoke, task_id, terminate=terminate)
    await asyncio.to_thread(release_parse_slot, task_id)

    return {
        "task_id": task_id,
        "status": "REVOKED",
        "previous_state": current_state,
        "terminate": terminate,
    }


@router.delete("/celery/{task_id}")
async def delete_celery_task(
    task_id: str = Path(..., description="Celery task UUID"),
    _current_user: UserResponse = Depends(require_admin_user),
):
    """
    Удалить задачу Celery по task_id.

    Удаляет флаг отмены из Redis (если существует).
    Примечание: это не удаляет задачу из истории Celery/Flower,
    только очищает флаг отмены для возможности повторного запуска.
    """
    try:
        await asyncio.to_thread(clear_cancel_flag, task_id)
        parse_slot_released = await asyncio.to_thread(release_parse_slot, task_id)
        return {
            "task_id": task_id,
            "status": "deleted",
            "parse_slot_released": parse_slot_released,
            "message": "Флаг отмены удалён из Redis",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при удалении: {str(e)}")
