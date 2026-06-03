"""Celery tasks for article content pipeline: PDF, text extraction, embeddings.

The old ``process_paper_content_task`` used to do everything in one long task.
It is kept as a backward-compatible entry point, but now it only launches a
chain of small tasks. Qwen-specific stages live in ``app.tasks.qwen_tasks`` and
are routed to the controlled ``qwen`` queue.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from celery import chain
from loguru import logger

from app.core.config import settings
from app.db.session import async_session_maker
from app.services.embedding_service import get_embedding_service
from app.services.paper_content_service import (
    download_pdf_bytes,
    extract_pdf_page_items,
    extract_pdf_page_items_mypdf,
    fetch_additional_full_text,
    resolve_pdf_url,
    save_pdf_locally,
)
from app.services.paper_service import PaperService
from app.services.paper_content_part_service import PaperContentPartService
from app.services.qwen_queue_client import run_ai_ocr_document_via_queue
from app.services.system_settings_service import (
    get_pdf_markdown_settings_safe,
    get_postprocess_settings_safe,
)
from app.services.vector_service import get_vector_service
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app


PIPELINE_VERSION = "content-pipeline-v2"


CONTENT_PIPELINE_STAGES: tuple[tuple[str, str, str], ...] = (
    ("download_pdf", "app.tasks.content_tasks.download_pdf_task", "Скачивание PDF"),
    ("extract_pdf_text", "app.tasks.content_tasks.extract_pdf_text_task", "Извлечение текста PDF"),
    ("qwen_markdown", "app.tasks.qwen.markdown", "Qwen Markdown"),
    ("qwen_ru_analysis", "app.tasks.qwen.ru_analysis", "Русский анализ"),
    ("qwen_keywords", "app.tasks.qwen.keywords", "Ключевые слова"),
    ("build_embedding", "app.tasks.content_tasks.build_embedding_task", "Embedding / Chroma"),
    ("finalize", "app.tasks.content_tasks.finalize_paper_processing_task", "Финализация"),
)


def _new_task_id() -> str:
    return str(uuid.uuid4())


def _build_stage_task_ids() -> dict[str, str]:
    return {stage: _new_task_id() for stage, _task_name, _label in CONTENT_PIPELINE_STAGES}


def _stage_task_descriptors(stage_task_ids: dict[str, Any] | None) -> list[dict[str, Any]]:
    ids = {str(key): str(value) for key, value in (stage_task_ids or {}).items() if str(value or "").strip()}
    items: list[dict[str, Any]] = []
    for order, (stage, task_name, label) in enumerate(CONTENT_PIPELINE_STAGES, start=1):
        task_id = ids.get(stage)
        if task_id:
            items.append({"stage": stage, "label": label, "task_name": task_name, "task_id": task_id, "order": order})
    if ids.get("qwen_ai_ocr_document"):
        items.append({
            "stage": "qwen_ai_ocr_document",
            "label": "AI OCR документа через Qwen",
            "task_name": "app.tasks.qwen.ai_ocr_document",
            "task_id": ids["qwen_ai_ocr_document"],
            "order": 2.5,
        })
    return items


def _pipeline_related_task_ids(
    *,
    parse_root_task_id: str | None = None,
    content_root_task_id: str | None = None,
    chain_result_id: str | None = None,
    stage_task_ids: dict[str, Any] | None = None,
    extra: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    ids: list[str] = []
    for value in [parse_root_task_id, content_root_task_id, chain_result_id, *(extra or [])]:
        text = str(value or "").strip()
        if text and text not in ids:
            ids.append(text)
    for value in (stage_task_ids or {}).values():
        text = str(value or "").strip()
        if text and text not in ids:
            ids.append(text)
    return ids[:500]


def _pipeline_lifecycle_payload(
    *,
    parse_root_task_id: str | None = None,
    content_root_task_id: str | None = None,
    chain_result_id: str | None = None,
    stage_task_ids: dict[str, Any] | None = None,
    extra_related_task_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    clean_stage_ids = {
        str(key): str(value)
        for key, value in (stage_task_ids or {}).items()
        if str(key or "").strip() and str(value or "").strip()
    }
    payload = {
        "parse_root_task_id": parse_root_task_id,
        "root_task_id": content_root_task_id,
        "content_root_task_id": content_root_task_id,
        "content_wrapper_task_id": content_root_task_id,
        "chain_result_id": chain_result_id,
        "stage_task_ids": clean_stage_ids,
        "stage_tasks": _stage_task_descriptors(clean_stage_ids),
    }
    payload["related_task_ids"] = _pipeline_related_task_ids(
        parse_root_task_id=parse_root_task_id,
        content_root_task_id=content_root_task_id,
        chain_result_id=chain_result_id,
        stage_task_ids=clean_stage_ids,
        extra=extra_related_task_ids,
    )
    return payload


def _previous_stage_task_ids(previous: Any) -> dict[str, str]:
    if not isinstance(previous, dict):
        return {}
    raw = previous.get("stage_task_ids")
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items() if str(key or "").strip() and str(value or "").strip()}


def _previous_extra_related_task_ids(previous: Any) -> list[str]:
    if not isinstance(previous, dict):
        return []
    raw = previous.get("related_task_ids")
    if not isinstance(raw, list):
        return []
    output: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in output:
            output.append(text)
    return output


def _normalize_pdf_mode_override(value: Any) -> str | None:
    if value is None:
        return None
    mode = str(value).strip().lower()
    return mode if mode in {"auto", "ai", "mypdf"} else "auto"




def _text_is_available(value: Any) -> bool:
    return bool(str(value or "").strip())


def _merge_quality_flags(current: Any, *flags: str) -> list[str]:
    merged: list[str] = []
    for item in list(current or []) + [flag for flag in flags if flag]:
        text = str(item or "").strip()
        if text and text not in merged:
            merged.append(text)
    return merged


def _annotate_document_processing(
    page_items: list[dict[str, Any]],
    *,
    requested_mode: str | None,
    actual_mode: str,
    fallback_used: bool = False,
) -> list[dict[str, Any]]:
    """Persist document-level extraction summary into every page item.

    ``replace_raw_parts`` intentionally skips empty pages. Without this summary
    AI quality would be calculated only by saved non-empty rows and could become
    artificially 100%.
    """
    if not page_items:
        return page_items

    requested = (requested_mode or actual_mode or "auto").strip().lower()
    actual = (actual_mode or requested or "auto").strip().lower()
    total = len(page_items)
    success = 0
    scores: list[float] = []

    for item in page_items:
        text_ok = _text_is_available(item.get("text"))
        if actual == "mypdf":
            item["quality_score"] = 0.8
            success += 1 if text_ok else 0
            scores.append(0.8 if text_ok else 0.0)
        elif actual == "ai":
            item["quality_score"] = 1.0 if text_ok else 0.0
            success += 1 if text_ok else 0
            scores.append(1.0 if text_ok else 0.0)
        else:
            raw_score = item.get("quality_score")
            try:
                score = float(raw_score)
                if score > 1 and score <= 100:
                    score = score / 100
                score = max(0.0, min(1.0, score))
            except (TypeError, ValueError):
                score = 1.0 if text_ok else 0.0
            item["quality_score"] = score
            success += 1 if text_ok else 0
            scores.append(score)

        method = str(item.get("method") or "").strip().lower()
        if actual == "mypdf" and "mypdf" not in method:
            item["method"] = "mypdf_text_layer"
        elif actual == "ai" and "ai" not in method:
            item["method"] = "ai_page_image"
        elif actual == "auto" and not method:
            item["method"] = "auto_pdf_parser"

    failed = max(0, total - success)
    avg_score = round(sum(scores) / max(1, len(scores)), 4) if scores else None
    summary = {
        "mode": actual,
        "requested_mode": requested,
        "actual_mode": actual,
        "quality_score": 0.8 if actual == "mypdf" else avg_score,
        "pages_total": total,
        "pages_success": success,
        "pages_failed": failed,
        "fallback_used": bool(fallback_used),
        "basis": "document_extraction_summary",
    }

    for item in page_items:
        metadata = dict(item.get("metadata") or {})
        metadata["document_processing"] = summary
        item["metadata"] = metadata
    return page_items


def _stale_ai_update_kwargs(paper: Any) -> dict[str, Any]:
    """Clear stale AI-derived fields right after full text replacement.

    The following Qwen tasks will refill them. If a later stage fails or is
    disabled, UI will not show analysis/keywords from the previous text version.
    """
    return {
        "summary_ru": None,
        "analysis_ru": None,
        "translation_ru": None,
        "keywords": [],
        "quality_flags": _merge_quality_flags(
            getattr(paper, "quality_flags", None),
            "ai_fields_stale_after_text_update",
            "keywords_stale_after_text_update",
        ),
    }

def _task_id(task_self: Any) -> str | None:
    return getattr(getattr(task_self, "request", None), "id", None)


def _safe_update_state(task_self: Any, task_id: str | None, state: str, meta: dict[str, Any]) -> None:
    """Update Celery state without relying on thread-local request context.

    With Celery pool=threads, async stage code runs in the shared asyncio loop
    thread. There ``task_self.request.id`` may be unavailable, so the task id is
    captured by the synchronous task wrapper and passed explicitly.
    """
    if not task_id:
        return
    try:
        task_self.update_state(task_id=task_id, state=state, meta=meta)
    except Exception as exc:
        logger.warning("Failed to update Celery task state: task_id={}, state={}, error={}", task_id, state, exc)


def _paper_id_from_previous(previous: Any) -> int | None:
    if isinstance(previous, dict):
        value = previous.get("paper_id")
    else:
        value = previous
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _root_task_id(previous: Any, fallback: str | None = None) -> str | None:
    if isinstance(previous, dict):
        return str(previous.get("content_root_task_id") or previous.get("root_task_id") or previous.get("content_task_id") or fallback or "") or None
    return fallback


def _merge_previous(previous: Any, **updates: Any) -> dict[str, Any]:
    if isinstance(previous, dict):
        payload = dict(previous)
    else:
        payload = {"paper_id": _paper_id_from_previous(previous)}
    payload.update(updates)

    stage_task_ids = _previous_stage_task_ids(payload)
    if stage_task_ids:
        lifecycle = _pipeline_lifecycle_payload(
            parse_root_task_id=str(payload.get("parse_root_task_id") or "") or None,
            content_root_task_id=str(payload.get("content_root_task_id") or payload.get("root_task_id") or "") or None,
            chain_result_id=str(payload.get("chain_result_id") or "") or None,
            stage_task_ids=stage_task_ids,
            extra_related_task_ids=_previous_extra_related_task_ids(payload),
        )
        payload.update(lifecycle)
    return payload


async def _get_postprocess_settings(db=None) -> dict[str, bool]:
    return await get_postprocess_settings_safe(db)


async def _get_pdf_markdown_settings(db=None) -> dict[str, Any]:
    return await get_pdf_markdown_settings_safe(db)


async def _set_stage(
    paper_service: PaperService,
    paper_id: int,
    stage: str,
    task_id: str | None,
    error: str | None = None,
) -> None:
    await paper_service.update_paper(
        paper_id,
        processing_status=stage,
        content_task_id=task_id,
        processing_error=error,
    )


_PIPELINE_ERROR_MESSAGE_MAX = 1200
_PIPELINE_STAGE_ERRORS_MAX = 20


def _short_error(exc: BaseException | str | None) -> str:
    if exc is None:
        return "pipeline_stage_failed"
    if isinstance(exc, BaseException):
        text = f"{type(exc).__name__}: {exc}"
    else:
        text = str(exc)
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split()).strip()
    return (text or "pipeline_stage_failed")[:_PIPELINE_ERROR_MESSAGE_MAX]


def _stage_errors_from_previous(previous: Any) -> list[dict[str, Any]]:
    if not isinstance(previous, dict):
        return []
    raw = previous.get("stage_errors")
    if not isinstance(raw, list):
        return []
    output: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            stage = str(item.get("stage") or "").strip()
            message = str(item.get("error_message") or item.get("error") or "").strip()
            if not stage and not message:
                continue
            output.append(
                {
                    "stage": stage or "unknown",
                    "task_id": str(item.get("task_id") or "").strip() or None,
                    "error_type": str(item.get("error_type") or "").strip() or None,
                    "error_message": message[:_PIPELINE_ERROR_MESSAGE_MAX],
                    "retry_allowed": bool(item.get("retry_allowed", True)),
                    "fallback_used": bool(item.get("fallback_used", True)),
                }
            )
    return output[:_PIPELINE_STAGE_ERRORS_MAX]


def _append_stage_error(
    previous: Any,
    *,
    stage: str,
    task_id: str | None,
    exc: BaseException | str | None,
    retry_allowed: bool = True,
    fallback_used: bool = True,
) -> list[dict[str, Any]]:
    errors = _stage_errors_from_previous(previous)
    error_type = type(exc).__name__ if isinstance(exc, BaseException) else None
    errors.append(
        {
            "stage": stage,
            "task_id": task_id,
            "error_type": error_type,
            "error_message": _short_error(exc),
            "retry_allowed": bool(retry_allowed),
            "fallback_used": bool(fallback_used),
        }
    )
    return errors[-_PIPELINE_STAGE_ERRORS_MAX:]


def _stage_error_summary(previous: Any) -> str | None:
    errors = _stage_errors_from_previous(previous)
    if not errors:
        return None
    chunks: list[str] = []
    for item in errors[-5:]:
        stage = str(item.get("stage") or "unknown")
        message = str(item.get("error_message") or "pipeline_stage_failed")
        chunks.append(f"{stage}: {message}")
    return "; ".join(chunks)[:_PIPELINE_ERROR_MESSAGE_MAX]


def _stage_failure_payload(
    previous: Any,
    *,
    stage: str,
    task_id: str | None,
    exc: BaseException | str | None,
    paper_id: int | None = None,
    retry_allowed: bool = True,
    fallback_used: bool = True,
    **updates: Any,
) -> dict[str, Any]:
    error_text = _short_error(exc)
    previous_payload = previous if isinstance(previous, dict) else {}
    first_failed_stage = str(previous_payload.get("first_failed_stage") or "").strip() or stage
    return _merge_previous(
        previous,
        status="stage_failed",
        paper_id=paper_id or _paper_id_from_previous(previous),
        pipeline_error=True,
        first_failed_stage=first_failed_stage,
        failed_stage=stage,
        failed_task_id=task_id,
        error=error_text,
        pipeline_error_message=error_text,
        retry_allowed=bool(retry_allowed),
        fallback_used=bool(fallback_used),
        stage_errors=_append_stage_error(
            previous,
            stage=stage,
            task_id=task_id,
            exc=exc,
            retry_allowed=retry_allowed,
            fallback_used=fallback_used,
        ),
        **{f"{stage}_error": error_text},
        **updates,
    )


async def _mark_stage_failed_async(
    paper_id: int | None,
    *,
    stage_status: str,
    task_id: str | None,
    error: BaseException | str | None,
) -> dict[str, Any]:
    text_available = False
    text_source = "none"
    if not paper_id:
        return {"text_available": False, "text_source": "none"}

    async with async_session_maker() as db:
        paper_service = PaperService(db)
        paper = await paper_service.get_by_id(int(paper_id))
        if not paper:
            return {"text_available": False, "text_source": "none"}

        full_text_available = bool(str(getattr(paper, "full_text", None) or "").strip())
        abstract_available = bool(str(getattr(paper, "abstract", None) or "").strip())
        text_available = full_text_available or abstract_available
        text_source = "existing_full_text" if full_text_available else ("abstract" if abstract_available else "none")
        await _set_stage(paper_service, int(paper_id), stage_status, task_id=task_id, error=_short_error(error))
        return {"text_available": text_available, "text_source": text_source}


async def _handle_content_stage_failure_async(
    previous: Any,
    *,
    stage: str,
    stage_status: str,
    task_id: str | None,
    exc: BaseException | str | None,
    paper_id: int | None = None,
    retry_allowed: bool = True,
    fallback_used: bool = True,
    **updates: Any,
) -> dict[str, Any]:
    resolved_paper_id = paper_id or _paper_id_from_previous(previous)
    marker: dict[str, Any] = {}
    try:
        marker = await _mark_stage_failed_async(
            resolved_paper_id,
            stage_status=stage_status,
            task_id=task_id,
            error=exc,
        )
    except Exception as status_exc:
        logger.warning(
            "Failed to mark content stage as failed: paper_id={}, stage={}, error={}",
            resolved_paper_id,
            stage,
            status_exc,
        )

    if "text_available" not in updates:
        updates.update(
            _content_flags(
                text_available=bool(marker.get("text_available")),
                text_source=str(marker.get("text_source") or "none"),
                fresh_content_available=False,
            )
        )
    return _stage_failure_payload(
        previous,
        stage=stage,
        task_id=task_id,
        exc=exc,
        paper_id=resolved_paper_id,
        retry_allowed=retry_allowed,
        fallback_used=fallback_used,
        **updates,
    )


async def _finalize_failure_fallback_async(previous: Any, *, task_id: str | None, exc: BaseException | str | None) -> dict[str, Any]:
    paper_id = _paper_id_from_previous(previous)
    root_task_id = _root_task_id(previous, fallback=task_id)
    error_text = _short_error(exc)
    fallback_payload = _stage_failure_payload(
        previous,
        stage="finalize",
        task_id=task_id,
        exc=exc,
        paper_id=paper_id,
        retry_allowed=True,
        fallback_used=True,
        root_task_id=root_task_id,
        final_stage="failed",
        pipeline=PIPELINE_VERSION,
    )
    if not paper_id:
        return fallback_payload

    try:
        async with async_session_maker() as db:
            paper_service = PaperService(db)
            paper = await paper_service.get_by_id(int(paper_id))
            if not paper:
                return fallback_payload
            has_text = bool(str(getattr(paper, "full_text", None) or getattr(paper, "abstract", None) or "").strip())
            final_stage = "ready_with_fallback" if has_text else "failed"
            await _set_stage(paper_service, int(paper_id), final_stage, task_id=task_id, error=error_text)
            return _merge_previous(
                fallback_payload,
                status="done" if has_text else "error",
                paper_id=int(paper_id),
                root_task_id=root_task_id,
                final_stage=final_stage,
                pipeline=PIPELINE_VERSION,
            )
    except Exception as status_exc:
        logger.warning("Failed to run finalize fallback: paper_id={}, error={}", paper_id, status_exc)
        return fallback_payload


def _content_flags(
    *,
    text_available: bool = False,
    text_source: str = "none",
    fresh_content_available: bool = False,
    fresh_parts_created: bool = False,
    content_parts_count: int = 0,
) -> dict[str, Any]:
    """Small, explicit contract passed between content and Qwen stages."""
    return {
        "text_available": bool(text_available),
        "text_source": text_source,
        "fresh_content_available": bool(fresh_content_available),
        "fresh_parts_created": bool(fresh_parts_created),
        "content_parts_count": int(content_parts_count or 0),
        "markdown_input_available": bool(fresh_content_available and text_source in {"pdf", "fallback_fulltext"}),
    }


def enqueue_paper_content_pipeline(
    paper_id: int,
    root_task_id: str | None = None,
    pdf_mode: str | None = None,
    parse_root_task_id: str | None = None,
):
    """Start the article post-processing pipeline for one paper.

    Big text/PDF payloads are never passed through Celery results. Every stage
    receives a small dict with ``paper_id`` and reads/writes article data in DB.
    Stage task ids are generated before the chain starts so dashboard can show
    the real PDF/Qwen/embedding lifecycle instead of guessing from counters.
    """
    content_queue = settings.CONTENT_QUEUE_NAME
    qwen_queue = settings.QWEN_QUEUE_NAME
    pdf_mode = _normalize_pdf_mode_override(pdf_mode)
    stage_task_ids = _build_stage_task_ids()

    workflow = chain(
        download_pdf_task.s(paper_id, root_task_id, pdf_mode, parse_root_task_id, stage_task_ids).set(
            queue=content_queue,
            task_id=stage_task_ids["download_pdf"],
        ),
        extract_pdf_text_task.s().set(queue=content_queue, task_id=stage_task_ids["extract_pdf_text"]),
        celery_app.signature("app.tasks.qwen.markdown").set(queue=qwen_queue, task_id=stage_task_ids["qwen_markdown"]),
        celery_app.signature("app.tasks.qwen.ru_analysis").set(queue=qwen_queue, task_id=stage_task_ids["qwen_ru_analysis"]),
        celery_app.signature("app.tasks.qwen.keywords").set(queue=qwen_queue, task_id=stage_task_ids["qwen_keywords"]),
        build_embedding_task.s().set(queue=content_queue, task_id=stage_task_ids["build_embedding"]),
        finalize_paper_processing_task.s().set(queue=content_queue, task_id=stage_task_ids["finalize"]),
    )
    result = workflow.apply_async()
    setattr(result, "stage_task_ids", stage_task_ids)
    return result


@celery_app.task(bind=True)
def process_paper_content_task(
    self,
    paper_id: int,
    pdf_mode: str | None = None,
    parse_root_task_id: str | None = None,
) -> dict[str, Any]:
    """Backward-compatible entry point used by parser endpoints/tasks.

    It no longer performs PDF/Qwen work directly. It only marks the paper as
    queued and launches the real stage-by-stage pipeline.
    """
    task_id = _task_id(self)
    pdf_mode = _normalize_pdf_mode_override(pdf_mode)
    try:
        result = enqueue_paper_content_pipeline(
            paper_id,
            root_task_id=task_id,
            pdf_mode=pdf_mode,
            parse_root_task_id=parse_root_task_id,
        )
        chain_result_id = getattr(result, "id", None)
        stage_task_ids = getattr(result, "stage_task_ids", {}) or {}
        lifecycle = _pipeline_lifecycle_payload(
            parse_root_task_id=parse_root_task_id,
            content_root_task_id=task_id,
            chain_result_id=chain_result_id,
            stage_task_ids=stage_task_ids,
        )
        logger.info(
            "Content pipeline queued: paper_id={}, parse_root_task_id={}, root_task_id={}, chain_result_id={}, stages={}",
            paper_id,
            parse_root_task_id,
            task_id,
            chain_result_id,
            len(stage_task_ids),
        )
        return {
            "status": "queued",
            "paper_id": paper_id,
            **lifecycle,
            "pipeline": PIPELINE_VERSION,
            "pdf_mode": pdf_mode,
        }
    except Exception as exc:
        logger.exception("Failed to queue content pipeline for paper {}: {}", paper_id, exc)
        return run_async(
            _handle_content_stage_failure_async(
                {"paper_id": paper_id, "parse_root_task_id": parse_root_task_id, "content_root_task_id": task_id, "pdf_mode": pdf_mode},
                stage="content_queue",
                stage_status="content_queue_failed",
                task_id=task_id,
                exc=exc,
                paper_id=paper_id,
                queued=False,
                pipeline=PIPELINE_VERSION,
                pdf_mode=pdf_mode,
            )
        )


@celery_app.task(bind=True, acks_late=True)
def download_pdf_task(
    self,
    paper_id: int,
    root_task_id: str | None = None,
    pdf_mode: str | None = None,
    parse_root_task_id: str | None = None,
    stage_task_ids: dict[str, str] | None = None,
) -> dict[str, Any]:
    task_id = _task_id(self)
    try:
        return run_async(
            _download_pdf_async(
                self,
                paper_id,
                root_task_id=root_task_id,
                task_id=task_id,
                pdf_mode=pdf_mode,
                parse_root_task_id=parse_root_task_id,
                stage_task_ids=stage_task_ids,
            )
        )
    except Exception as exc:
        logger.exception("PDF download task failed for paper {}: {}", paper_id, exc)
        lifecycle = _pipeline_lifecycle_payload(
            parse_root_task_id=parse_root_task_id,
            content_root_task_id=root_task_id,
            stage_task_ids=stage_task_ids,
        )
        return run_async(
            _handle_content_stage_failure_async(
                {"paper_id": paper_id, **lifecycle, "pdf_mode": pdf_mode, "pipeline": PIPELINE_VERSION},
                stage="download_pdf",
                stage_status="pdf_download_failed",
                task_id=task_id,
                exc=exc,
                paper_id=paper_id,
                pdf_downloaded=False,
                pdf_url=None,
                pdf_local_path=None,
                pdf_mode=pdf_mode,
                pipeline=PIPELINE_VERSION,
            )
        )


async def _download_pdf_async(
    self,
    paper_id: int,
    root_task_id: str | None = None,
    task_id: str | None = None,
    pdf_mode: str | None = None,
    parse_root_task_id: str | None = None,
    stage_task_ids: dict[str, str] | None = None,
) -> dict[str, Any]:
    task_id = task_id or root_task_id
    pdf_mode = _normalize_pdf_mode_override(pdf_mode)
    lifecycle = _pipeline_lifecycle_payload(
        parse_root_task_id=parse_root_task_id,
        content_root_task_id=root_task_id,
        stage_task_ids=stage_task_ids,
    )
    _safe_update_state(self, task_id, "STARTED", {"paper_id": paper_id, "stage": "downloading_pdf", **lifecycle})

    async with async_session_maker() as db:
        paper_service = PaperService(db)
        paper = await paper_service.get_by_id(paper_id)
        if not paper:
            return {
                "status": "error",
                "paper_id": paper_id,
                "error": "paper_not_found",
                **lifecycle,
                "pdf_mode": pdf_mode,
            }


        postprocess = await _get_postprocess_settings(db)
        if not postprocess.get("download_pdf", True):
            await _set_stage(paper_service, paper_id, "pdf_download_skipped", task_id=task_id, error="download_pdf_disabled")
            return {
                "status": "ok",
                "paper_id": paper_id,
                **lifecycle,
                "pdf_mode": pdf_mode,
                "pdf_downloaded": False,
                "pdf_skipped": True,
                "pipeline": PIPELINE_VERSION,
                **_content_flags(
                    text_available=bool((paper.full_text or paper.abstract or "").strip()),
                    text_source="existing_or_abstract",
                    fresh_content_available=False,
                ),
            }

        await _set_stage(paper_service, paper_id, "pdf_pending", task_id=task_id, error=None)

        inferred_pdf_url = resolve_pdf_url(paper.source, paper.source_id, paper.url)
        pdf_url = (paper.pdf_url or inferred_pdf_url or "").strip() or None
        if pdf_url and pdf_url != paper.pdf_url:
            await paper_service.update_paper(paper_id, pdf_url=pdf_url)

        await _set_stage(paper_service, paper_id, "downloading_pdf", task_id=task_id, error=None)
        pdf_bytes = await asyncio.to_thread(download_pdf_bytes, pdf_url) if pdf_url else None

        if not pdf_bytes:
            if paper.pdf_url:
                pdf_url_text = paper.pdf_url or ""
                stale_epmc_pdf = "ebi.ac.uk/europepmc/webservices/rest/" in pdf_url_text and "fullTextPDF" in pdf_url_text
                uncertain_external_pdf = paper.source in {"EuropePMC", "OpenAlex", "Crossref"}
                if stale_epmc_pdf or uncertain_external_pdf:
                    await paper_service.update_paper(paper_id, pdf_url=None)

            await _set_stage(
                paper_service,
                paper_id,
                "pdf_download_failed" if pdf_url else "pdf_unavailable",
                task_id=task_id,
                error=None,
            )
            return {
                "status": "ok",
                "paper_id": paper_id,
                **lifecycle,
                "pdf_mode": pdf_mode,
                "pdf_downloaded": False,
                "pdf_url": pdf_url,
                "pdf_local_path": None,
                "pipeline": PIPELINE_VERSION,
                **_content_flags(
                    text_available=bool((paper.abstract or "").strip()),
                    text_source="abstract" if (paper.abstract or "").strip() else "none",
                    fresh_content_available=False,
                ),
            }

        pdf_local_path = await asyncio.to_thread(save_pdf_locally, paper_id, pdf_bytes)
        await paper_service.update_paper(paper_id, pdf_local_path=pdf_local_path)
        await _set_stage(paper_service, paper_id, "pdf_downloaded", task_id=task_id, error=None)

        return {
            "status": "ok",
            "paper_id": paper_id,
            **lifecycle,
            "pdf_mode": pdf_mode,
            "pdf_downloaded": True,
            "pdf_local_path": pdf_local_path,
            "pdf_url": pdf_url,
            "pipeline": PIPELINE_VERSION,
            **_content_flags(text_available=False, text_source="pdf_pending", fresh_content_available=False),
        }


@celery_app.task(bind=True, acks_late=True)
def extract_pdf_text_task(self, previous: dict[str, Any]) -> dict[str, Any]:
    task_id = _task_id(self)
    try:
        return run_async(_extract_pdf_text_async(self, previous, task_id=task_id))
    except Exception as exc:
        paper_id = _paper_id_from_previous(previous)
        logger.exception("PDF text extraction task failed for paper {}: {}", paper_id, exc)
        return run_async(
            _handle_content_stage_failure_async(
                previous,
                stage="extract_pdf_text",
                stage_status="pdf_text_failed",
                task_id=task_id,
                exc=exc,
                paper_id=paper_id,
                pdf_text_ready=False,
                extraction_ready=False,
            )
        )


async def _extract_pdf_text_async(
    self,
    previous: dict[str, Any],
    task_id: str | None = None,
) -> dict[str, Any]:
    paper_id = _paper_id_from_previous(previous)
    root_task_id = _root_task_id(previous, fallback=task_id)
    task_id = task_id or root_task_id
    if not paper_id:
        return _merge_previous(previous, status="error", error="missing_paper_id")

    _safe_update_state(self, task_id, "STARTED", {"paper_id": paper_id, "stage": "extracting_pdf_text"})

    async with async_session_maker() as db:
        paper_service = PaperService(db)
        paper = await paper_service.get_by_id(paper_id)
        if not paper:
            return _merge_previous(previous, status="error", error="paper_not_found")


        postprocess = await _get_postprocess_settings(db)
        if not postprocess.get("extract_pdf_text", True):
            await _set_stage(paper_service, paper_id, "pdf_text_skipped", task_id=task_id, error="extract_pdf_text_disabled")
            return _merge_previous(
                previous,
                status="ok",
                paper_id=paper_id,
                root_task_id=root_task_id,
                text_skipped=True,
                **_content_flags(
                    text_available=bool((paper.full_text or paper.abstract or "").strip()),
                    text_source="existing_or_abstract",
                    fresh_content_available=False,
                ),
            )

        pdf_markdown = await _get_pdf_markdown_settings(db)
        save_raw_parts = bool(pdf_markdown.get("save_raw_parts", True))
        pages_per_part = max(1, int(pdf_markdown.get("pages_per_request") or settings.QWEN_MARKDOWN_PAGES_PER_REQUEST or 1))

        extracted_page_items: list[dict[str, Any]] = []
        extracted_pages: list[str] = []
        extracted_text = ""
        requested_pdf_mode = _normalize_pdf_mode_override(previous.get("pdf_mode")) or "auto"
        actual_pdf_mode = "auto"
        pdf_fallback_used = False

        pdf_local_path = str(previous.get("pdf_local_path") or "").strip() if previous.get("pdf_downloaded") else ""
        if pdf_local_path and Path(pdf_local_path).exists():
            await _set_stage(paper_service, paper_id, "extracting_pdf_text", task_id=task_id, error=None)
            pdf_bytes = await asyncio.to_thread(Path(pdf_local_path).read_bytes)
            parser_mode = str(pdf_markdown.get("parser_mode") or "auto").strip().lower() or "auto"
            ocr_mode = str(pdf_markdown.get("ocr_mode") or "auto").strip().lower() or "auto"
            ai_mode = str(pdf_markdown.get("ai_mode") or ("force" if parser_mode == "ai" else "off")).strip().lower() or "off"
            force_strategy = str(pdf_markdown.get("force_strategy") or "").strip().lower()
            legacy_extraction_mode = str(pdf_markdown.get("extraction_mode") or "auto").strip().lower() or "auto"
            launch_pdf_mode = requested_pdf_mode
            if launch_pdf_mode == "ai":
                parser_mode = "ai"
                ai_mode = "force"
                force_strategy = "ai"
                legacy_extraction_mode = "ai"
            elif launch_pdf_mode == "mypdf":
                parser_mode = "mypdf"
                ai_mode = "off"
                force_strategy = "mypdf"
                legacy_extraction_mode = "mypdf"
                ocr_mode = "off"
            elif launch_pdf_mode == "auto":
                parser_mode = "auto"
                ai_mode = "off"
                force_strategy = ""
                legacy_extraction_mode = "auto"

            use_mypdf = (
                launch_pdf_mode == "mypdf"
                or parser_mode == "mypdf"
                or force_strategy == "mypdf"
                or legacy_extraction_mode == "mypdf"
            )

            extraction_options = {
                "parser_mode": parser_mode,
                "ocr_mode": ocr_mode,
                "ai_mode": ai_mode,
                "force_strategy": force_strategy,
                "extraction_mode": legacy_extraction_mode,
                "detect_columns": False if use_mypdf else pdf_markdown.get("detect_columns", True),
                "extract_tables": False if use_mypdf else pdf_markdown.get("extract_tables", True),
                "remove_headers_footers": pdf_markdown.get("remove_headers_footers", True),
                "merge_hyphenated_words": pdf_markdown.get("merge_hyphenated_words", True),
                "normalize_math": pdf_markdown.get("normalize_math", True),
                "mark_formula_candidates": False if use_mypdf else pdf_markdown.get("mark_formula_candidates", True),
                "ocr_enabled": False if use_mypdf else ocr_mode != "off",
                "ocr_force": ocr_mode == "force",
                "ocr_engine": pdf_markdown.get("ocr_engine", "auto"),
                "ocr_dpi": pdf_markdown.get("ocr_dpi", 220),
                "ocr_languages": pdf_markdown.get("ocr_languages", "eng+rus"),
                "ai_enabled": False if use_mypdf else parser_mode == "ai" or ai_mode in {"auto", "force"} or force_strategy == "ai",
                "ai_provider": pdf_markdown.get("ai_provider", ""),
                "ai_model": pdf_markdown.get("ai_model", ""),
                "ai_endpoint": pdf_markdown.get("ai_endpoint", ""),
                "ai_render_dpi": pdf_markdown.get("ai_render_dpi", 220),
                "ai_page_image_format": pdf_markdown.get("ai_page_image_format", "png"),
                "ai_timeout_sec": pdf_markdown.get("ai_timeout_sec", 120),
                "ai_fallback_to_auto": pdf_markdown.get("ai_fallback_to_auto", True),
                "ai_delete_temp_images": pdf_markdown.get("ai_delete_temp_images", True),
                "min_text_chars": pdf_markdown.get("min_text_chars", 300),
                "max_page_chars": pdf_markdown.get("max_page_chars", 60000),
            }
            ai_requested = parser_mode == "ai" or force_strategy == "ai" or ai_mode == "force"
            if use_mypdf:
                actual_pdf_mode = "mypdf"
                extracted_page_items = await asyncio.to_thread(extract_pdf_page_items_mypdf, pdf_bytes, extraction_options)
                extracted_pages = [str(item.get("text") or "") for item in extracted_page_items]
                extracted_text = "\n\n".join(page for page in extracted_pages if page and page.strip()).strip()
            elif ai_requested:
                actual_pdf_mode = "ai"
                ai_timeout = float(pdf_markdown.get("ai_document_timeout_sec") or 3600)
                ai_result = await asyncio.to_thread(
                    run_ai_ocr_document_via_queue,
                    pdf_path=pdf_local_path,
                    options=extraction_options,
                    timeout=max(300.0, ai_timeout),
                    purpose=f"paper-{paper_id}-ai-page-ocr",
                )
                ai_task_id = str(ai_result.get("task_id") or "").strip() if isinstance(ai_result, dict) else ""
                if ai_task_id:
                    stage_task_ids = _previous_stage_task_ids(previous)
                    stage_task_ids["qwen_ai_ocr_document"] = ai_task_id
                    previous = _merge_previous(previous, stage_task_ids=stage_task_ids)
                ai_pages = ai_result.get("pages") if isinstance(ai_result, dict) else []
                if isinstance(ai_pages, list) and ai_pages:
                    extracted_page_items = [item for item in ai_pages if isinstance(item, dict)]
                    extracted_pages = [str(item.get("text") or "") for item in extracted_page_items]
                    extracted_text = "\n\n".join(page for page in extracted_pages if page and page.strip()).strip()
                if not extracted_text and bool(extraction_options.get("ai_fallback_to_auto", True)):
                    logger.warning(
                        "AI OCR returned no text for paper {}; falling back to local auto parser. error={}",
                        paper_id,
                        ai_result.get("error") if isinstance(ai_result, dict) else "invalid_ai_result",
                    )
                    actual_pdf_mode = "auto"
                    pdf_fallback_used = True
                    fallback_options = dict(extraction_options)
                    fallback_options.update(
                        {
                            "parser_mode": "auto",
                            "force_strategy": "",
                            "extraction_mode": "auto",
                            "extraction_strategy": "auto",
                            "ai_mode": "off",
                            "ai_enabled": False,
                        }
                    )
                    extracted_page_items = await asyncio.to_thread(extract_pdf_page_items, pdf_bytes, fallback_options)
                    extracted_pages = [str(item.get("text") or "") for item in extracted_page_items]
                    extracted_text = "\n\n".join(page for page in extracted_pages if page and page.strip()).strip()
            else:
                actual_pdf_mode = "auto"
                extracted_page_items = await asyncio.to_thread(extract_pdf_page_items, pdf_bytes, extraction_options)
                extracted_pages = [str(item.get("text") or "") for item in extracted_page_items]
                extracted_text = "\n\n".join(page for page in extracted_pages if page and page.strip()).strip()

        if extracted_text:
            if extracted_page_items:
                extracted_page_items = _annotate_document_processing(
                    extracted_page_items,
                    requested_mode=requested_pdf_mode,
                    actual_mode=actual_pdf_mode,
                    fallback_used=pdf_fallback_used,
                )
            content_parts_count = len(extracted_pages or [extracted_text])
            if save_raw_parts:
                part_service = PaperContentPartService(db)
                stored_parts = await part_service.replace_raw_parts(paper_id, extracted_page_items or extracted_pages or [extracted_text], source="pdf", pages_per_part=pages_per_part)
                content_parts_count = len(stored_parts)
            await paper_service.update_paper(paper_id, full_text=extracted_text, **_stale_ai_update_kwargs(paper))
            await _set_stage(paper_service, paper_id, "pdf_parsed", task_id=task_id, error=None)
            return _merge_previous(
                previous,
                status="ok",
                paper_id=paper_id,
                root_task_id=root_task_id,
                **_content_flags(
                    text_available=True,
                    text_source="pdf",
                    fresh_content_available=True,
                    fresh_parts_created=bool(save_raw_parts and content_parts_count > 0),
                    content_parts_count=content_parts_count,
                ),
            )

        fallback_text = await asyncio.to_thread(
            fetch_additional_full_text,
            paper.source,
            paper.source_id,
            paper.url,
            paper.abstract or "",
        )
        if fallback_text:
            fallback_parts_count = 0
            if save_raw_parts:
                part_service = PaperContentPartService(db)
                stored_parts = await part_service.replace_raw_parts(paper_id, [fallback_text], source="fallback_fulltext", pages_per_part=1)
                fallback_parts_count = len(stored_parts)
            await paper_service.update_paper(paper_id, full_text=fallback_text, **_stale_ai_update_kwargs(paper))
            await _set_stage(paper_service, paper_id, "fulltext_fallback_parsed", task_id=task_id, error=None)
            return _merge_previous(
                previous,
                status="ok",
                paper_id=paper_id,
                root_task_id=root_task_id,
                **_content_flags(
                    text_available=True,
                    text_source="fallback_fulltext",
                    fresh_content_available=True,
                    fresh_parts_created=bool(fallback_parts_count),
                    content_parts_count=fallback_parts_count,
                ),
            )

        await _set_stage(paper_service, paper_id, "fulltext_unavailable", task_id=task_id, error=None)
        return _merge_previous(
            previous,
            status="ok",
            paper_id=paper_id,
            root_task_id=root_task_id,
            **_content_flags(
                text_available=bool((paper.abstract or "").strip()),
                text_source="abstract" if (paper.abstract or "").strip() else "none",
                fresh_content_available=False,
            ),
        )


@celery_app.task(bind=True, acks_late=True)
def build_embedding_task(self, previous: dict[str, Any]) -> dict[str, Any]:
    task_id = _task_id(self)
    try:
        return run_async(_build_embedding_async(self, previous, task_id=task_id))
    except Exception as exc:
        paper_id = _paper_id_from_previous(previous)
        logger.exception("Embedding task failed for paper {}: {}", paper_id, exc)
        return run_async(
            _handle_content_stage_failure_async(
                previous,
                stage="build_embedding",
                stage_status="embedding_failed",
                task_id=task_id,
                exc=exc,
                paper_id=paper_id,
                embedded=False,
                embedding_ready=False,
                embedding_error=_short_error(exc),
            )
        )


async def _build_embedding_async(
    self,
    previous: dict[str, Any],
    task_id: str | None = None,
) -> dict[str, Any]:
    paper_id = _paper_id_from_previous(previous)
    root_task_id = _root_task_id(previous, fallback=task_id)
    task_id = task_id or root_task_id
    if not paper_id:
        return _merge_previous(previous, status="error", error="missing_paper_id")

    _safe_update_state(self, task_id, "STARTED", {"paper_id": paper_id, "stage": "indexing_vector"})

    async with async_session_maker() as db:
        paper_service = PaperService(db)
        paper = await paper_service.get_by_id(paper_id)
        if not paper:
            return _merge_previous(previous, status="error", error="paper_not_found")


        postprocess = await _get_postprocess_settings(db)
        if not postprocess.get("embedding", True):
            await _set_stage(paper_service, paper_id, "embedding_skipped", task_id=task_id, error="embedding_disabled")
            return _merge_previous(previous, status="ok", paper_id=paper_id, root_task_id=root_task_id, embedded=False, embedding_skipped=True)

        await _set_stage(paper_service, paper_id, "indexing_vector", task_id=task_id, error=None)

        part_service = PaperContentPartService(db)
        embedding_source_text = await part_service.assemble_embedding_text(paper_id, max_chars=12000)
        content_text = (embedding_source_text or paper.full_text or paper.abstract or "").strip()
        embedded = False
        if content_text:
            embedding_service = get_embedding_service()
            vector_service = get_vector_service()
            embedding_available = await asyncio.to_thread(lambda: embedding_service.model is not None)
            if embedding_available:
                embedding_text = " | ".join(
                    part
                    for part in [
                        f"Title: {paper.title}" if paper.title else "",
                        f"Abstract: {paper.abstract}" if paper.abstract else "",
                        f"Keywords: {', '.join(paper.keywords or [])}" if paper.keywords else "",
                        f"Content: {content_text[:12000]}" if content_text else "",
                    ]
                    if part
                )
                if embedding_text:
                    embedding = await asyncio.to_thread(embedding_service.get_embedding, embedding_text)
                    if embedding:
                        await paper_service.update_paper(paper_id, embedding=embedding)
                        await asyncio.to_thread(
                            vector_service.add_paper,
                            paper_id=paper_id,
                            embedding=embedding,
                            title=paper.title,
                            source=paper.source,
                            doi=paper.doi,
                            publication_date=paper.publication_date.isoformat() if paper.publication_date else None,
                            journal=paper.journal,
                        )
                        embedded = True

        await _set_stage(
            paper_service,
            paper_id,
            "embedding_ready" if embedded else "embedding_skipped",
            task_id=task_id,
            error=None,
        )
        return _merge_previous(previous, status="ok", paper_id=paper_id, root_task_id=root_task_id, embedded=embedded)


@celery_app.task(bind=True, acks_late=True)
def finalize_paper_processing_task(self, previous: dict[str, Any]) -> dict[str, Any]:
    task_id = _task_id(self)
    try:
        return run_async(_finalize_paper_processing_async(self, previous, task_id=task_id))
    except Exception as exc:
        paper_id = _paper_id_from_previous(previous)
        logger.exception("Finalize content pipeline failed for paper {}: {}", paper_id, exc)
        return run_async(_finalize_failure_fallback_async(previous, task_id=task_id, exc=exc))


async def _finalize_paper_processing_async(
    self,
    previous: dict[str, Any],
    task_id: str | None = None,
) -> dict[str, Any]:
    paper_id = _paper_id_from_previous(previous)
    root_task_id = _root_task_id(previous, fallback=task_id)
    task_id = task_id or root_task_id
    if not paper_id:
        return _merge_previous(previous, status="error", error="missing_paper_id")

    async with async_session_maker() as db:
        paper_service = PaperService(db)
        paper = await paper_service.get_by_id(paper_id)
        if not paper:
            return _merge_previous(previous, status="error", error="paper_not_found")

        postprocess = await _get_postprocess_settings(db)
        previous_payload = previous if isinstance(previous, dict) else {}
        stage_error_summary = _stage_error_summary(previous_payload)
        known_stage_error = next(
            (
                str(previous_payload.get(key) or "").strip()
                for key in (
                    "markdown_error",
                    "qwen_markdown_error",
                    "ru_analysis_error",
                    "qwen_ru_analysis_error",
                    "qwen_fallback_reason",
                    "keywords_error",
                    "qwen_keywords_error",
                    "embedding_error",
                    "build_embedding_error",
                    "extract_pdf_text_error",
                    "download_pdf_error",
                )
                if str(previous_payload.get(key) or "").strip()
            ),
            None,
        )
        stage_error_summary = stage_error_summary or known_stage_error
        pipeline_error = bool(previous_payload.get("pipeline_error")) or bool(stage_error_summary)
        keywords_error = str(previous_payload.get("keywords_error") or "").strip()
        keywords_required = bool(postprocess.get("qwen_keywords", True)) and not bool(previous_payload.get("qwen_keywords_skipped"))
        keywords_failed = keywords_required and (
            bool(keywords_error)
            or previous_payload.get("keywords_ready") is False
        )

        had_qwen_fallback = bool((paper.processing_error or "").strip())
        has_ai = bool((paper.summary_ru or "").strip() or (paper.analysis_ru or "").strip())
        has_text = bool((paper.full_text or paper.abstract or "").strip())
        ru_analysis_required = bool(postprocess.get("qwen_ru_analysis", True)) and not bool(previous_payload.get("qwen_analysis_skipped"))

        if not has_text:
            final_stage = "failed"
            error = paper.processing_error or stage_error_summary or "no_text_available"
        elif keywords_failed:
            final_stage = "ready_with_fallback"
            error = keywords_error or stage_error_summary or "keywords_not_ready"
        elif pipeline_error:
            final_stage = "ready_with_fallback"
            error = paper.processing_error or stage_error_summary or "pipeline_stage_failed"
        elif had_qwen_fallback or (ru_analysis_required and not has_ai):
            final_stage = "ready_with_fallback"
            error = paper.processing_error or ("ru_analysis_not_ready" if ru_analysis_required and not has_ai else None)
        else:
            final_stage = "ready"
            error = None

        await _set_stage(paper_service, paper_id, final_stage, task_id=task_id, error=error)
        logger.info(
            "Content pipeline finished: paper_id={}, final_stage={}, embedded={}, qwen_markdown={}, qwen_analysis={}, qwen_keywords={}",
            paper_id,
            final_stage,
            previous.get("embedded") if isinstance(previous, dict) else None,
            previous.get("markdown_ready") if isinstance(previous, dict) else None,
            previous.get("ru_analysis_ready") if isinstance(previous, dict) else None,
            previous.get("keywords_ready") if isinstance(previous, dict) else None,
        )
        return _merge_previous(
            previous,
            status="done" if final_stage != "failed" else "error",
            paper_id=paper_id,
            root_task_id=root_task_id,
            final_stage=final_stage,
            pipeline=PIPELINE_VERSION,
        )
