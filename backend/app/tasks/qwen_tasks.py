"""Shared Qwen Celery gateway tasks and document Qwen stages.

The queue can be served by up to QWEN_QUEUE_WORKERS workers.  Background callers
should either enqueue one raw Qwen message through ``app.tasks.qwen.send_message``
or use the document-stage tasks below: markdown, RU analysis, keywords.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from sqlalchemy import select

from loguru import logger

from app.core.config import settings
from app.db.models.paper_content_part_translation import PaperContentPartTranslation
from app.db.session import async_session_maker
from app.services.paper_content_service import (
    create_qwen_session_for_paper,
    generate_ai_enrichment_ru,
    generate_document_keywords,
    normalize_pdf_text_part,
    PDF_MARKDOWN_PROMPT_VERSION,
)
from app.services.paper_service import PaperService
from app.services.paper_content_part_service import (
    PaperContentPartService,
    should_qwen_markdown_content_type,
)
from app.services.system_settings_service import (
    get_pdf_markdown_settings_safe,
    get_postprocess_settings_safe,
    get_qwen_settings_safe,
)
from app.services.qwen_client import QwenServiceClient
from app.services.qwen_token_tools import is_qwen_auth_expired_message
from app.services.qwen_document.cleaning import (
    clean_qwen_markdown_response as _clean_qwen_markdown_response,
)
from app.services.qwen_document.context import (
    count_pdf_pages_for_ai_ocr as _count_pdf_pages_for_ai_ocr,
    fresh_markdown_input_available as _fresh_markdown_input_available,
    mark_ai_fields_stale as _mark_ai_fields_stale,
    merge_language_codes as _merge_language_codes,
    merge_previous as _merge_previous,
    merge_quality_flags as _merge_quality_flags,
    page_markdown_heading as _page_markdown_heading,
    paper_id_from_previous as _paper_id_from_previous,
    qwen_input_text_for_part as _qwen_input_text_for_part,
    root_task_id as _root_task_id,
)
from app.services.qwen_document.keywords import (
    keywords_raw_source_from_parts as _keywords_raw_source_from_parts,
)
from app.services.qwen_document.prompts import (
    ARTICLE_MARKDOWN_IMAGE_REGENERATION_PROMPT_VERSION,
    build_article_translation_prompt as _build_article_translation_prompt,
)
from app.services.qwen_document.regeneration import (
    extract_part_pdf_pages_as_text as _extract_part_pdf_pages_as_text,
    normalize_regeneration_mode as _normalize_regeneration_mode,
    regenerate_part_markdown_from_page_images as _regenerate_part_markdown_from_page_images,
)
from app.services.qwen_document.stage_failures import (
    short_error as _short_error,
    stage_errors_from_previous as _stage_errors_from_previous,
    append_stage_error as _append_stage_error,
    stage_failure_payload as _stage_failure_payload,
)
from app.services.qwen_document.translation import (
    ARTICLE_TRANSLATION_MAX_ATTEMPTS,
    ARTICLE_TRANSLATION_PROMPT_VERSION,
    extract_qwen_error_response as _extract_qwen_error_response,
    format_translation_final_error as _format_translation_final_error,
    format_translation_retry_error as _format_translation_retry_error,
    is_retryable_translation_quality_error as _is_retryable_translation_quality_error,
    is_transient_article_translation_error as _is_transient_article_translation_error,
    markdown_translation_source_quality as _markdown_translation_source_quality,
    translation_language_name as _translation_language_name,
    translation_output_quality_error as _translation_output_quality_error,
    translation_retry_delay_seconds as _translation_retry_delay_seconds,
)
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app


async def _upsert_part_translation(
    db,
    *,
    paper_id: int,
    part_id: int,
    language_code: str,
    language_name: str | None,
    source_language_code: str | None,
    translated_markdown_text: str | None = None,
    status: str = "pending",
    error: str | None = None,
    qwen_model: str | None = None,
    qwen_prompt_version: str | None = None,
    source_chars: int = 0,
) -> PaperContentPartTranslation:
    result = await db.execute(
        select(PaperContentPartTranslation).where(
            PaperContentPartTranslation.part_id == part_id,
            PaperContentPartTranslation.language_code == language_code,
        )
    )
    row = result.scalar_one_or_none()
    text = (translated_markdown_text or "").strip() if translated_markdown_text is not None else None
    if not row:
        row = PaperContentPartTranslation(
            paper_id=paper_id,
            part_id=part_id,
            language_code=language_code,
            language_name=language_name,
            source_language_code=source_language_code,
        )
        db.add(row)
    row.language_name = language_name
    row.source_language_code = source_language_code
    row.status = status
    row.error = (error or None)[:4000] if error else None
    row.qwen_model = qwen_model
    row.qwen_prompt_version = qwen_prompt_version
    row.source_chars = int(source_chars or 0)
    if text is not None:
        row.translated_markdown_text = text
        row.translated_chars = len(text)
    elif status != "ready":
        row.translated_chars = int(row.translated_chars or 0)
    await db.commit()
    await db.refresh(row)
    return row



def _mark_regenerated_part_quality(part: Any, *, mode: str, raw_text: str | None = None) -> None:
    metadata = dict(getattr(part, "extraction_metadata", None) or {})
    text_ok = bool(str(raw_text if raw_text is not None else getattr(part, "raw_text", "") or "").strip())
    if mode in {"image", "ai"}:
        part.extraction_quality_score = 1.0 if text_ok else 0.0
        part.extraction_method = "ai_page_image_regenerate"
    elif mode == "mypdf":
        part.extraction_quality_score = 0.8 if text_ok else 0.0
        part.extraction_method = "mypdf_text_layer_regenerate"
    elif mode == "auto" and part.extraction_quality_score is None:
        part.extraction_quality_score = 1.0 if text_ok else 0.0
    elif part.extraction_quality_score is None:

        part.extraction_quality_score = 1.0 if text_ok else 0.0
    metadata["regeneration_mode"] = mode
    metadata["regeneration_quality"] = {
        "mode": "ai" if mode in {"image", "ai"} else mode,
        "pages_total": max(1, int((getattr(part, "page_end", None) or getattr(part, "page_start", None) or 1)) - int((getattr(part, "page_start", None) or 1)) + 1),
        "pages_success": 1 if text_ok else 0,
        "pages_failed": 0 if text_ok else 1,
    }
    part.extraction_metadata = metadata


def _qwen_queue_rate_limit() -> str | None:
    """Return Celery rate_limit for Qwen gateway tasks.

    For parallel Qwen workers the hard limiter should be the number of qwen worker
    processes, not an accidental 300/h throttle. Set QWEN_QUEUE_TASK_RATE_LIMIT to
    off/none/0/empty to disable Celery rate limiting.
    """
    raw = settings.QWEN_QUEUE_TASK_RATE_LIMIT
    if raw is None:
        return None
    value = str(raw).strip()
    if not value or value.lower() in {"0", "off", "none", "false", "no", "unlimited"}:
        return None
    return value


def _task_id(task_self: Any) -> str | None:
    return getattr(getattr(task_self, "request", None), "id", None)


def _safe_update_state(task_self: Any, task_id: str | None, state: str, meta: dict[str, Any]) -> None:
    """Update Celery state without relying on thread-local request context."""
    if not task_id:
        return
    try:
        task_self.update_state(task_id=task_id, state=state, meta=meta)
    except Exception as exc:
        logger.warning("Failed to update Qwen task state: task_id={}, state={}, error={}", task_id, state, exc)


async def _get_postprocess_settings(db=None) -> dict[str, bool]:
    return await get_postprocess_settings_safe(db)


async def _get_qwen_settings(db=None) -> dict[str, Any]:
    return await get_qwen_settings_safe(db)


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


async def _mark_qwen_stage_failed_async(
    paper_id: int | None,
    *,
    stage_status: str,
    task_id: str | None,
    error: BaseException | str | None,
) -> None:
    if not paper_id:
        return
    async with async_session_maker() as db:
        paper_service = PaperService(db)
        paper = await paper_service.get_by_id(int(paper_id))
        if not paper:
            return
        await _set_stage(paper_service, int(paper_id), stage_status, task_id=task_id, error=_short_error(error))


async def _handle_qwen_stage_failure_async(
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
    try:
        await _mark_qwen_stage_failed_async(
            resolved_paper_id,
            stage_status=stage_status,
            task_id=task_id,
            error=exc,
        )
    except Exception as status_exc:
        logger.warning(
            "Failed to mark Qwen stage as failed: paper_id={}, stage={}, error={}",
            resolved_paper_id,
            stage,
            status_exc,
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


@celery_app.task(
    bind=True,
    name="app.tasks.qwen.send_message",
    rate_limit=_qwen_queue_rate_limit(),
    acks_late=True,
    soft_time_limit=int(max(60, settings.QWEN_QUEUE_TIMEOUT + 30)),
    time_limit=int(max(90, settings.QWEN_QUEUE_TIMEOUT + 90)),
)
def qwen_send_message_task(
    self,
    message: str,
    session_id: str | None = None,
    thinking_enabled: bool = True,
    search_enabled: bool = False,
    file_ids: list[str] | None = None,
    auto_continue: bool | None = None,
    timeout: float = 120.0,
    purpose: str = "background",
) -> dict[str, Any]:
    """Send one message to qwen_service from the controlled Qwen queue."""
    task_id = _task_id(self)
    logger.info(
        "Qwen queue task started: task_id={}, purpose={}, session={}, thinking={}, search={}",
        task_id,
        purpose,
        (session_id[-6:] if session_id else "new"),
        thinking_enabled,
        search_enabled,
    )

    client = QwenServiceClient(queue_enabled=False, timeout=timeout)
    result = client.send_message(
        message=message,
        session_id=session_id,
        thinking_enabled=thinking_enabled,
        search_enabled=search_enabled,
        file_ids=file_ids or [],
        auto_continue=auto_continue,
        timeout=timeout,
    )






    if isinstance(result, dict):
        original_prompt = result.pop("message", None)
        if isinstance(original_prompt, str):
            result["prompt_preview"] = original_prompt[:240]
            result["prompt_length"] = len(original_prompt)

    result.setdefault("task_id", task_id)
    result.setdefault("purpose", purpose)
    return result



@celery_app.task(
    bind=True,
    name="app.tasks.qwen.ai_ocr_document",
    rate_limit=_qwen_queue_rate_limit(),
    acks_late=True,
    soft_time_limit=3300,
    time_limit=3600,
)
def qwen_ai_ocr_document_task(
    self,
    pdf_path: str,
    options: dict[str, Any] | None = None,
    timeout: float = 3600.0,
    purpose: str = "ai-page-ocr-document",
) -> dict[str, Any]:
    """Run AI page OCR for one PDF in the Qwen worker queue.

    One task processes the whole document so a single Qwen chat session can be
    reused: first the instruction prompt, then page image + short OCR command for
    every page. The returned payload is plain page text wrapped by backend code.
    """
    task_id = _task_id(self)
    path = Path(str(pdf_path or ""))
    opts = dict(options or {})
    logger.info(
        "Qwen AI OCR document task started: task_id={}, pdf_path={}, purpose={}",
        task_id,
        path,
        purpose,
    )

    if not path.exists() or not path.is_file():
        return {
            "status": "error",
            "error": "pdf_file_not_found",
            "pdf_path": str(path),
            "pages": [],
            "task_id": task_id,
            "purpose": purpose,
        }

    try:
        pdf_bytes = path.read_bytes()
    except Exception as exc:
        return {
            "status": "error",
            "error": f"pdf_read_failed:{type(exc).__name__}:{exc}",
            "pdf_path": str(path),
            "pages": [],
            "task_id": task_id,
            "purpose": purpose,
        }

    try:
        from app.services.pdf_parser.ai import AIPageRecognitionService
    except Exception as exc:
        return {
            "status": "error",
            "error": f"ai_service_import_failed:{type(exc).__name__}:{exc}",
            "pdf_path": str(path),
            "pages": [],
            "task_id": task_id,
            "purpose": purpose,
        }

    page_count = _count_pdf_pages_for_ai_ocr(pdf_bytes)
    if page_count <= 0:
        return {
            "status": "error",
            "error": "pdf_page_count_unavailable",
            "pdf_path": str(path),
            "pages": [],
            "task_id": task_id,
            "purpose": purpose,
        }

    opts.update(
        {
            "parser_mode": "ai",
            "force_strategy": "ai",
            "extraction_strategy": "ai",
            "selected_strategy": "ai",
            "ai_mode": "force",
            "ai_enabled": True,
            "ai_provider": str(opts.get("ai_provider") or "qwen"),
            "ai_timeout_sec": int(float(timeout or opts.get("ai_timeout_sec") or 120)),
        }
    )

    service = AIPageRecognitionService()
    service.reset_document_session()
    pages: list[dict[str, Any]] = []
    warnings: list[str] = []
    used_count = 0
    failed_count = 0

    for page_number in range(1, page_count + 1):
        try:
            result = service.recognize_page(
                file_bytes=pdf_bytes,
                page_number=page_number,
                opts=opts,
            )
        except Exception as exc:
            logger.exception("Qwen AI OCR page failed: task_id={}, page={}", task_id, page_number)
            text = ""
            metadata = {
                "parser_mode": "ai",
                "selected_strategy": "ai",
                "force_strategy": "ai",
                "ai_mode": "force",
                "ai_enabled": True,
                "ai_used": False,
                "ai_status": "provider_error",
                "ai_reason": f"ai_page_exception:{type(exc).__name__}",
                "ai_error": str(exc),
                "ai_external_call_performed": False,
            }
            failed_count += 1
        else:
            text = str(result.text or "")
            metadata = dict(result.metadata or {})
            metadata.update(
                {
                    "parser_mode": "ai",
                    "selected_strategy": "ai",
                    "force_strategy": "ai",
                    "extraction_strategy": "ai",
                    "ai_mode": "force",
                    "ai_enabled": True,
                    "ai_used": bool(text.strip()),
                    "ai_status": result.status,
                    "ai_reason": result.reason,
                    "ai_confidence": float(result.confidence or 0.0),
                    "ai_warnings": list(result.warnings or []),
                }
            )
            if text.strip():
                used_count += 1
            else:
                failed_count += 1
            warnings.extend(str(item) for item in (result.warnings or []) if item)

        pages.append(
            {
                "page_number": page_number,
                "text": text,
                "source": "ai",
                "method": "ai_page_image",
                "content_type": "body",
                "quality_score": 1.0 if text.strip() else 0.0,
                "metadata": metadata,
            }
        )
        try:
            self.update_state(
                task_id=task_id,
                state="PROGRESS",
                meta={
                    "stage": "ai_ocr_document",
                    "page": page_number,
                    "page_count": page_count,
                    "ai_used_page_count": used_count,
                    "ai_failed_page_count": failed_count,
                },
            )
        except Exception:
            pass

    full_text = "\n\n".join(str(page.get("text") or "") for page in pages if str(page.get("text") or "").strip()).strip()
    return {
        "status": "ok" if full_text else "empty",
        "pdf_path": str(path),
        "page_count": page_count,
        "pages": pages,
        "text_chars": len(full_text),
        "ai_used_page_count": used_count,
        "ai_failed_page_count": failed_count,
        "ai_session_id": service.session_id or "",
        "warnings": sorted(set(warnings)),
        "task_id": task_id,
        "purpose": purpose,
    }


@celery_app.task(
    bind=True,
    name="app.tasks.qwen.markdown",
    rate_limit=_qwen_queue_rate_limit(),
    acks_late=True,
    soft_time_limit=int(max(60, settings.QWEN_QUEUE_TIMEOUT + 30)),
    time_limit=int(max(90, settings.QWEN_QUEUE_TIMEOUT + 90)),
)
def qwen_markdown_task(self, previous: dict[str, Any]) -> dict[str, Any]:
    """Format extracted article text into readable Markdown through Qwen."""
    task_id = _task_id(self)
    try:
        return run_async(_qwen_markdown_async(self, previous, task_id=task_id))
    except Exception as exc:
        paper_id = _paper_id_from_previous(previous)
        logger.exception("Qwen markdown task failed for paper {}: {}", paper_id, exc)
        return run_async(
            _handle_qwen_stage_failure_async(
                previous,
                stage="qwen_markdown",
                stage_status="markdown_failed",
                task_id=task_id,
                exc=exc,
                paper_id=paper_id,
                markdown_ready=False,
                markdown_error=_short_error(exc),
            )
        )


async def _qwen_markdown_async(
    self,
    previous: dict[str, Any],
    task_id: str | None = None,
) -> dict[str, Any]:
    paper_id = _paper_id_from_previous(previous)
    root_task_id = _root_task_id(previous, fallback=task_id)
    task_id = task_id or root_task_id
    if not paper_id:
        return _merge_previous(previous, status="error", error="missing_paper_id")

    _safe_update_state(
        self,
        task_id,
        "STARTED",
        {"paper_id": paper_id, "stage": "digitizing_file", "stage_label": "Оцифровка файла", "current": 0, "total": 0, "percent": 50},
    )

    async with async_session_maker() as db:
        paper_service = PaperService(db)
        part_service = PaperContentPartService(db)
        paper = await paper_service.get_by_id(paper_id)
        if not paper:
            return _merge_previous(previous, status="error", error="paper_not_found")


        postprocess = await _get_postprocess_settings(db)
        qwen_settings = await _get_qwen_settings(db)
        pdf_markdown_settings = await _get_pdf_markdown_settings(db)
        if not postprocess.get("qwen_markdown", True) or not qwen_settings.get("markdown_enabled", True):
            await _set_stage(paper_service, paper_id, "markdown_skipped", task_id=task_id, error="qwen_markdown_disabled")
            return _merge_previous(previous, paper_id=paper_id, root_task_id=root_task_id, markdown_ready=False, markdown_skipped=True)

        save_markdown_parts = bool(pdf_markdown_settings.get("save_markdown_parts", True))
        page_char_limit = int(pdf_markdown_settings.get("page_chars") or settings.QWEN_MARKDOWN_PAGE_CHARS)
        normalize_math = bool(pdf_markdown_settings.get("normalize_math", True))
        qwen_timeout = float(qwen_settings.get("request_timeout_seconds") or settings.QWEN_QUEUE_TIMEOUT)

        if not _fresh_markdown_input_available(previous):
            text_source = str(previous.get("text_source") or "none") if isinstance(previous, dict) else "none"
            await _set_stage(paper_service, paper_id, "markdown_skipped", task_id=task_id, error=f"no_fresh_markdown_input:{text_source}")
            return _merge_previous(
                previous,
                paper_id=paper_id,
                root_task_id=root_task_id,
                markdown_ready=False,
                markdown_skipped=True,
                markdown_skip_reason=f"no_fresh_markdown_input:{text_source}",
            )

        content_text = (paper.full_text or "").strip()
        parts = await part_service.list_parts(paper_id)
        if not previous.get("fresh_parts_created") and content_text:



            if parts:
                await part_service.clear_parts(paper_id)
            parts = await part_service.ensure_parts_from_text(paper_id, content_text, source=str(previous.get("text_source") or "legacy_full_text"))

        if not parts:
            await _set_stage(paper_service, paper_id, "markdown_skipped", task_id=task_id, error="no_content_parts")
            return _merge_previous(previous, paper_id=paper_id, root_task_id=root_task_id, markdown_ready=False, markdown_skipped=True, markdown_skip_reason="no_content_parts")

        await _set_stage(paper_service, paper_id, "digitizing_file", task_id=task_id, error=None)
        session_id = await asyncio.to_thread(create_qwen_session_for_paper, paper_id, paper.title)
        total_parts = len(parts)
        markdown_ready_count = 0
        markdown_failed_count = 0
        markdown_skipped_count = 0
        qwen_eligible_count = 0
        generated_blocks: list[str] = []

        for index, part in enumerate(parts, start=1):




            if not should_qwen_markdown_content_type(getattr(part, "content_type", "body")):
                markdown_skipped_count += 1
                await part_service.set_part_ready_without_markdown(part)
                continue

            raw_text = _qwen_input_text_for_part(part)
            if not raw_text:
                markdown_skipped_count += 1
                await part_service.set_part_ready_without_markdown(part)
                continue

            qwen_eligible_count += 1

            await part_service.set_part_processing(part)
            status = f"digitizing_file:{index - 1}/{total_parts}"
            await paper_service.update_paper(
                paper_id,
                processing_status=status,
                content_task_id=task_id,
                processing_error=None,
            )
            _safe_update_state(
                self,
                task_id,
                "PROGRESS",
                {
                    "paper_id": paper_id,
                    "stage": "digitizing_file",
                    "stage_label": "Оцифровка файла",
                    "current": index - 1,
                    "total": total_parts,
                    "percent": 50 + round(((index - 1) / max(1, total_parts)) * 20),
                    "page_start": part.page_start,
                    "page_end": part.page_end,
                },
            )

            try:
                markdown_text = await asyncio.to_thread(
                    normalize_pdf_text_part,
                    paper_id,
                    paper.title,
                    raw_text,
                    part.page_start,
                    part.page_end,
                    session_id,
                    include_full_instruction=(index == 1),
                    page_char_limit=page_char_limit,
                    timeout_seconds=qwen_timeout,
                    normalize_math=normalize_math,
                )
            except Exception as markdown_exc:
                error_text = str(markdown_exc)
                logger.warning(
                    "Qwen markdown normalization failed for paper {} part {} pages {}-{}: {}",
                    paper_id,
                    part.id,
                    part.page_start,
                    part.page_end,
                    markdown_exc,
                )
                if is_qwen_auth_expired_message(error_text):
                    await part_service.set_part_failed(part, "qwen_token_expired")
                    await paper_service.update_paper(
                        paper_id,
                        processing_status="qwen_auth_failed",
                        content_task_id=task_id,
                        processing_error="Токен Qwen истёк. Обновите QWEN_TOKEN.",
                    )
                    return _merge_previous(
                        previous,
                        paper_id=paper_id,
                        root_task_id=root_task_id,
                        markdown_ready=False,
                        markdown_error="qwen_token_expired",
                    )
                markdown_failed_count += 1
                await part_service.set_part_failed(part, error_text)
                continue

            if markdown_text:
                generated_blocks.append(f"{_page_markdown_heading(part.page_start, part.page_end)}\n\n{markdown_text}".strip())
                if save_markdown_parts:
                    await part_service.set_part_markdown(
                        part,
                        markdown_text,
                        qwen_model=str(qwen_settings.get("model") or settings.QWEN_MODEL),
                        prompt_version=PDF_MARKDOWN_PROMPT_VERSION,
                        increment_regeneration=False,
                    )
                else:
                    await part_service.set_part_ready_without_markdown(part)
                markdown_ready_count += 1
            else:
                markdown_failed_count += 1
                await part_service.set_part_failed(part, "qwen_markdown_empty")

            current_markdown = await part_service.assemble_markdown(paper_id) if save_markdown_parts else "\n\n".join(generated_blocks).strip()
            await paper_service.update_paper(
                paper_id,
                full_text=current_markdown or content_text,
                processing_status=f"digitizing_file:{index}/{total_parts}",
                content_task_id=task_id,
                processing_error=None,
            )
            _safe_update_state(
                self,
                task_id,
                "PROGRESS",
                {
                    "paper_id": paper_id,
                    "stage": "digitizing_file",
                    "stage_label": "Оцифровка файла",
                    "current": index,
                    "total": total_parts,
                    "percent": 50 + round((index / max(1, total_parts)) * 20),
                    "page_start": part.page_start,
                    "page_end": part.page_end,
                },
            )

        final_markdown = await part_service.assemble_markdown(paper_id) if save_markdown_parts else "\n\n".join(generated_blocks).strip()
        if final_markdown and markdown_ready_count > 0:
            await paper_service.update_paper(paper_id, full_text=final_markdown)
            stage = "markdown_partial" if markdown_failed_count else "markdown_ready"
            error = f"qwen_markdown_partial_failed_parts:{markdown_failed_count}" if markdown_failed_count else None
            await _set_stage(paper_service, paper_id, stage, task_id=task_id, error=error)
            return _merge_previous(
                previous,
                paper_id=paper_id,
                root_task_id=root_task_id,
                session_id=session_id,
                markdown_ready=True,
                markdown_partial=bool(markdown_failed_count),
                markdown_parts_ready=markdown_ready_count,
                markdown_parts_failed=markdown_failed_count,
                markdown_parts_skipped=markdown_skipped_count,
                markdown_parts_eligible=qwen_eligible_count,
                markdown_parts_total=total_parts,
            )

        if final_markdown and qwen_eligible_count == 0:


            await paper_service.update_paper(paper_id, full_text=final_markdown)
            await _set_stage(paper_service, paper_id, "markdown_ready_without_qwen", task_id=task_id, error=None)
            return _merge_previous(
                previous,
                paper_id=paper_id,
                root_task_id=root_task_id,
                session_id=session_id,
                markdown_ready=True,
                markdown_without_qwen=True,
                markdown_parts_ready=markdown_ready_count,
                markdown_parts_failed=markdown_failed_count,
                markdown_parts_skipped=markdown_skipped_count,
                markdown_parts_eligible=qwen_eligible_count,
                markdown_parts_total=total_parts,
            )

        error = "qwen_markdown_empty" if qwen_eligible_count else "no_qwen_eligible_parts"
        stage = "markdown_failed" if qwen_eligible_count else "markdown_skipped"
        await _set_stage(paper_service, paper_id, stage, task_id=task_id, error=error)
        return _merge_previous(
            previous,
            paper_id=paper_id,
            root_task_id=root_task_id,
            session_id=session_id,
            markdown_ready=False,
            markdown_error=error,
            markdown_parts_ready=markdown_ready_count,
            markdown_parts_failed=markdown_failed_count,
            markdown_parts_skipped=markdown_skipped_count,
            markdown_parts_eligible=qwen_eligible_count,
            markdown_parts_total=total_parts,
        )


@celery_app.task(
    bind=True,
    name="app.tasks.qwen.ru_analysis",
    rate_limit=_qwen_queue_rate_limit(),
    acks_late=True,
    soft_time_limit=int(max(60, settings.QWEN_QUEUE_TIMEOUT + 30)),
    time_limit=int(max(90, settings.QWEN_QUEUE_TIMEOUT + 90)),
)
def qwen_ru_analysis_task(self, previous: dict[str, Any]) -> dict[str, Any]:
    """Generate Russian summary/analysis/translation for one article."""
    task_id = _task_id(self)
    try:
        return run_async(_qwen_ru_analysis_async(self, previous, task_id=task_id))
    except Exception as exc:
        paper_id = _paper_id_from_previous(previous)
        logger.exception("Qwen RU analysis task failed for paper {}: {}", paper_id, exc)
        return run_async(
            _handle_qwen_stage_failure_async(
                previous,
                stage="qwen_ru_analysis",
                stage_status="ru_analysis_failed",
                task_id=task_id,
                exc=exc,
                paper_id=paper_id,
                ru_analysis_ready=False,
                qwen_used_fallback=True,
                qwen_fallback_reason=_short_error(exc),
            )
        )


async def _qwen_ru_analysis_async(
    self,
    previous: dict[str, Any],
    task_id: str | None = None,
) -> dict[str, Any]:
    paper_id = _paper_id_from_previous(previous)
    root_task_id = _root_task_id(previous, fallback=task_id)
    task_id = task_id or root_task_id
    if not paper_id:
        return _merge_previous(previous, status="error", error="missing_paper_id")

    _safe_update_state(self, task_id, "STARTED", {"paper_id": paper_id, "stage": "analyzing_ru"})

    async with async_session_maker() as db:
        paper_service = PaperService(db)
        paper = await paper_service.get_by_id(paper_id)
        if not paper:
            return _merge_previous(previous, status="error", error="paper_not_found")


        postprocess = await _get_postprocess_settings(db)
        qwen_settings = await _get_qwen_settings(db)
        if not postprocess.get("qwen_ru_analysis", True) or not qwen_settings.get("ru_analysis_enabled", True):
            await _set_stage(paper_service, paper_id, "ru_analysis_skipped", task_id=task_id, error="qwen_ru_analysis_disabled")
            return _merge_previous(previous, paper_id=paper_id, root_task_id=root_task_id, ru_analysis_ready=False, qwen_analysis_skipped=True)

        qwen_timeout = float(qwen_settings.get("request_timeout_seconds") or settings.QWEN_QUEUE_TIMEOUT)
        content_text = (paper.full_text or paper.abstract or "").strip()
        await _set_stage(paper_service, paper_id, "analyzing_ru", task_id=task_id, error=None)
        session_id = previous.get("session_id") if isinstance(previous, dict) else None
        if not session_id:
            session_id = await asyncio.to_thread(create_qwen_session_for_paper, paper_id, paper.title)

        enrichment = await asyncio.to_thread(
            generate_ai_enrichment_ru,
            paper.title,
            paper.abstract or "",
            content_text,
            session_id,
            timeout_seconds=qwen_timeout,
        )
        fallback_reason = enrichment.fallback_reason if enrichment.used_fallback else None
        await paper_service.update_paper(
            paper_id,
            summary_ru=enrichment.summary_ru,
            analysis_ru=enrichment.analysis_ru,
            translation_ru=enrichment.translation_ru,
            processing_error=fallback_reason,
            quality_flags=_merge_quality_flags(
                getattr(paper, "quality_flags", None),
                remove={"ai_fields_stale_after_text_update"},
            ),
        )
        await _set_stage(
            paper_service,
            paper_id,
            "ru_analysis_ready" if not enrichment.used_fallback else "ru_analysis_fallback",
            task_id=task_id,
            error=fallback_reason,
        )
        return _merge_previous(
            previous,
            paper_id=paper_id,
            root_task_id=root_task_id,
            session_id=session_id,
            ru_analysis_ready=not enrichment.used_fallback,
            qwen_used_fallback=enrichment.used_fallback,
            qwen_fallback_reason=fallback_reason,
        )


@celery_app.task(
    bind=True,
    name="app.tasks.qwen.keywords",
    rate_limit=_qwen_queue_rate_limit(),
    acks_late=True,
    soft_time_limit=int(max(60, settings.QWEN_QUEUE_TIMEOUT + 30)),
    time_limit=int(max(90, settings.QWEN_QUEUE_TIMEOUT + 90)),
)
def qwen_keywords_task(self, previous: dict[str, Any]) -> dict[str, Any]:
    """Extract validated document keywords through Qwen."""
    task_id = _task_id(self)
    try:
        return run_async(_qwen_keywords_async(self, previous, task_id=task_id))
    except Exception as exc:
        paper_id = _paper_id_from_previous(previous)
        logger.exception("Qwen keywords task failed for paper {}: {}", paper_id, exc)
        return run_async(
            _handle_qwen_stage_failure_async(
                previous,
                stage="qwen_keywords",
                stage_status="keywords_failed",
                task_id=task_id,
                exc=exc,
                paper_id=paper_id,
                keywords_ready=False,
                keywords_error=_short_error(exc),
            )
        )


async def _qwen_keywords_async(
    self,
    previous: dict[str, Any],
    task_id: str | None = None,
) -> dict[str, Any]:
    paper_id = _paper_id_from_previous(previous)
    root_task_id = _root_task_id(previous, fallback=task_id)
    task_id = task_id or root_task_id
    if not paper_id:
        return _merge_previous(previous, status="error", error="missing_paper_id")

    _safe_update_state(self, task_id, "STARTED", {"paper_id": paper_id, "stage": "extracting_keywords"})

    async with async_session_maker() as db:
        paper_service = PaperService(db)
        paper = await paper_service.get_by_id(paper_id)
        if not paper:
            return _merge_previous(previous, status="error", error="paper_not_found")


        postprocess = await _get_postprocess_settings(db)
        qwen_settings = await _get_qwen_settings(db)
        if not postprocess.get("qwen_keywords", True) or not qwen_settings.get("keywords_enabled", True):
            await _set_stage(paper_service, paper_id, "keywords_skipped", task_id=task_id, error="qwen_keywords_disabled")
            return _merge_previous(previous, paper_id=paper_id, root_task_id=root_task_id, keywords_ready=False, qwen_keywords_skipped=True)

        await _set_stage(paper_service, paper_id, "extracting_keywords", task_id=task_id, error=None)
        session_id = previous.get("session_id") if isinstance(previous, dict) else None
        if not session_id:
            session_id = await asyncio.to_thread(create_qwen_session_for_paper, paper_id, paper.title)
        qwen_timeout = float(qwen_settings.get("request_timeout_seconds") or settings.QWEN_QUEUE_TIMEOUT)
        part_service = PaperContentPartService(db)
        raw_source_text = _keywords_raw_source_from_parts(await part_service.list_parts(paper_id))

        try:
            keyword_result = await asyncio.to_thread(
                generate_document_keywords,
                title=paper.title,
                abstract=paper.abstract,
                full_text=paper.full_text,
                raw_text=raw_source_text,
                existing_keywords=paper.keywords or [],
                session_id=session_id,
                timeout_seconds=qwen_timeout,
            )

            language_code = keyword_result.language_code or "unknown"
            language_payload: dict[str, Any] = {}
            if language_code and (language_code != "unknown" or not getattr(paper, "language_code", None)):
                language_payload = {
                    "language_code": language_code,
                    "language_name": keyword_result.language_name or "Не определён",
                    "language_confidence": keyword_result.language_confidence,
                    "language_source": keyword_result.language_source or "qwen_keywords",
                }

            await paper_service.update_paper(
                paper_id,
                keywords=keyword_result.keywords,
                **language_payload,
                quality_flags=_merge_quality_flags(
                    getattr(paper, "quality_flags", None),
                    remove={"keywords_stale_after_text_update"},
                ),
            )

            await _set_stage(paper_service, paper_id, "keywords_ready", task_id=task_id, error=None)
            return _merge_previous(
                previous,
                paper_id=paper_id,
                root_task_id=root_task_id,
                session_id=keyword_result.session_id or session_id,
                keywords_ready=True,
                keywords_count=len(keyword_result.keywords or []),
                keywords_generated_count=keyword_result.generated_count,
                keywords_validated_count=keyword_result.validated_count,
                keywords_rejected_count=keyword_result.rejected_count,
                keyword_source_chars=keyword_result.source_chars,
                keyword_source_mode=keyword_result.source_mode,
                language_code=keyword_result.language_code,
                language_name=keyword_result.language_name,
                language_confidence=keyword_result.language_confidence,
                language_source=keyword_result.language_source,
            )
        except Exception as keyword_exc:
            logger.warning("Keyword generation failed for paper {}: {}", paper_id, keyword_exc)
            await _set_stage(paper_service, paper_id, "keywords_failed", task_id=task_id, error=str(keyword_exc))
            return _merge_previous(
                previous,
                paper_id=paper_id,
                root_task_id=root_task_id,
                session_id=session_id,
                keywords_ready=False,
                keywords_error=str(keyword_exc),
            )


async def _mark_article_translation_failed(paper_id: int, task_id: str | None, error: str) -> None:
    async with async_session_maker() as db:
        paper_service = PaperService(db)
        await paper_service.update_paper(
            int(paper_id),
            translation_status="translation_failed",
            translation_task_id=task_id,
            translation_error=(error or "translation_failed")[:4000],
        )



@celery_app.task(
    bind=True,
    name="app.tasks.qwen.translate_markdown_parts",
    rate_limit=_qwen_queue_rate_limit(),
    acks_late=True,
    soft_time_limit=int(max(120, settings.QWEN_QUEUE_TIMEOUT * 2)),
    time_limit=int(max(180, settings.QWEN_QUEUE_TIMEOUT * 2 + 90)),
)
def translate_markdown_parts_task(
    self,
    paper_id: int,
    target_language_code: str = "ru",
    target_language_name: str | None = "Русский",
    force: bool = False,
) -> dict[str, Any]:
    """Translate saved Qwen Markdown parts into a separate language layer."""
    task_id = _task_id(self)
    try:
        return run_async(
            _translate_markdown_parts_async(
                self,
                int(paper_id),
                target_language_code=target_language_code,
                target_language_name=target_language_name,
                force=bool(force),
                task_id=task_id,
            )
        )
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        logger.exception("Qwen article translation failed for paper {}: {}", paper_id, error_text)
        try:
            run_async(_mark_article_translation_failed(int(paper_id), task_id, error_text))
        except Exception as status_exc:
            logger.warning("Failed to mark article translation as failed: paper_id={}, error={}", paper_id, status_exc)
        raise


async def _translate_markdown_parts_async(
    self,
    paper_id: int,
    *,
    target_language_code: str = "ru",
    target_language_name: str | None = "Русский",
    force: bool = False,
    task_id: str | None = None,
) -> dict[str, Any]:
    task_id = task_id or _task_id(self)
    language_code = (target_language_code or "ru").strip().lower()
    language_name = _translation_language_name(language_code, target_language_name)

    _safe_update_state(
        self,
        task_id,
        "STARTED",
        {"paper_id": paper_id, "stage": "translating_article", "stage_label": "Перевод текста статьи", "current": 0, "total": 0, "percent": 0},
    )

    async with async_session_maker() as db:
        paper_service = PaperService(db)
        part_service = PaperContentPartService(db)
        paper = await paper_service.get_by_id(paper_id)
        if not paper:
            return {"ok": False, "paper_id": paper_id, "error": "paper_not_found"}

        parts = await part_service.list_parts(paper_id)
        eligible_parts = [
            part
            for part in parts
            if str(getattr(part, "markdown_text", None) or "").strip()
            or (str(getattr(part, "source", "") or "") == "legacy_full_text" and str(getattr(part, "raw_text", None) or "").strip())
        ]
        if not eligible_parts:
            await paper_service.update_paper(
                paper_id,
                translation_status="translation_failed",
                translation_task_id=task_id,
                translation_error="Нет сохранённого Markdown-текста для перевода. Сначала выполните оцифровку файла через Qwen.",
            )
            return {"ok": False, "paper_id": paper_id, "error": "no_markdown_parts"}

        total = len(eligible_parts)
        ready_count = 0
        failed_count = 0
        skipped_count = 0
        source_language_code = str(getattr(paper, "language_code", None) or "").strip().lower() or None
        await paper_service.update_paper(
            paper_id,
            available_language_codes=_merge_language_codes(getattr(paper, "available_language_codes", None), source_language_code),
            translation_status=f"translating_article:0/{total}",
            translation_task_id=task_id,
            translation_error=None,
        )

        qwen_settings = await _get_qwen_settings(db)
        qwen_timeout = float(qwen_settings.get("request_timeout_seconds") or settings.QWEN_QUEUE_TIMEOUT)
        client = QwenServiceClient(queue_enabled=False, timeout=qwen_timeout)

        temp_dir = Path(settings.resolve_path("logs/run/tmp/qwen_article_translations"))
        temp_dir.mkdir(parents=True, exist_ok=True)

        for index, part in enumerate(eligible_parts, start=1):
            existing = None
            for item in getattr(part, "translations", []) or []:
                if str(getattr(item, "language_code", "") or "").strip().lower() == language_code:
                    existing = item
                    break
            if existing and getattr(existing, "status", None) == "ready" and getattr(existing, "translated_markdown_text", None) and not force:
                ready_count += 1
                skipped_count += 1
                continue

            source_markdown = str(part.markdown_text or (part.raw_text if str(getattr(part, "source", "") or "") == "legacy_full_text" else "") or "").strip()
            await _upsert_part_translation(
                db,
                paper_id=paper_id,
                part_id=part.id,
                language_code=language_code,
                language_name=language_name,
                source_language_code=source_language_code,
                status="processing",
                qwen_model=str(qwen_settings.get("model") or settings.QWEN_MODEL),
                qwen_prompt_version=ARTICLE_TRANSLATION_PROMPT_VERSION,
                source_chars=len(source_markdown),
            )
            await paper_service.update_paper(
                paper_id,
                translation_status=f"translating_article:{index - 1}/{total}",
                translation_task_id=task_id,
                translation_error=None,
            )
            _safe_update_state(
                self,
                task_id,
                "PROGRESS",
                {
                    "paper_id": paper_id,
                    "stage": "translating_article",
                    "stage_label": "Перевод текста статьи",
                    "current": index - 1,
                    "total": total,
                    "percent": round(((index - 1) / max(1, total)) * 100),
                    "language_code": language_code,
                    "page_start": part.page_start,
                    "page_end": part.page_end,
                },
            )

            source_quality = _markdown_translation_source_quality(source_markdown)
            if not source_quality.get("ok"):
                source_error = str(source_quality.get("error") or "source_markdown_invalid")
                fallback_notice = (
                    "Исходный Markdown повреждён, пробую повторно восстановить страницу по фото: "
                    f"{source_error}"
                )[:4000]
                await _upsert_part_translation(
                    db,
                    paper_id=paper_id,
                    part_id=part.id,
                    language_code=language_code,
                    language_name=language_name,
                    source_language_code=source_language_code,
                    status="processing",
                    error=fallback_notice,
                    qwen_model=str(qwen_settings.get("model") or settings.QWEN_MODEL),
                    qwen_prompt_version=ARTICLE_TRANSLATION_PROMPT_VERSION,
                    source_chars=len(source_markdown),
                )
                await paper_service.update_paper(
                    paper_id,
                    translation_status=f"translating_article:{index - 1}/{total}",
                    translation_task_id=task_id,
                    translation_error=fallback_notice,
                )
                _safe_update_state(
                    self,
                    task_id,
                    "PROGRESS",
                    {
                        "paper_id": paper_id,
                        "stage": "translating_article_regenerate_markdown",
                        "stage_label": "Повторная обработка страницы по фото",
                        "current": index - 1,
                        "total": total,
                        "percent": round(((index - 1) / max(1, total)) * 100),
                        "language_code": language_code,
                        "page_start": part.page_start,
                        "page_end": part.page_end,
                        "source_quality_error": source_error,
                    },
                )
                try:
                    regenerated_markdown, regeneration_meta = await _regenerate_part_markdown_from_page_images(
                        client=client,
                        paper=paper,
                        part=part,
                        qwen_settings=qwen_settings,
                        qwen_timeout=qwen_timeout,
                        temp_dir=temp_dir,
                    )
                except Exception as exc:
                    regenerated_markdown = ""
                    regeneration_meta = {"error": f"image_regeneration_failed:{type(exc).__name__}:{exc}"}
                    logger.warning(
                        "Article translation image fallback failed: paper_id={}, part_id={}, error={}",
                        paper_id,
                        part.id,
                        regeneration_meta["error"],
                    )

                regenerated_quality = _markdown_translation_source_quality(regenerated_markdown)
                if not regenerated_markdown or not regenerated_quality.get("ok"):
                    failed_count += 1
                    final_source_error = str(
                        regeneration_meta.get("error")
                        or regenerated_quality.get("error")
                        or source_error
                        or "source_markdown_invalid"
                    )[:4000]
                    await _upsert_part_translation(
                        db,
                        paper_id=paper_id,
                        part_id=part.id,
                        language_code=language_code,
                        language_name=language_name,
                        source_language_code=source_language_code,
                        status="failed",
                        error="Исходный Markdown повреждён, повторная обработка по фото не восстановила страницу: " + final_source_error,
                        qwen_model=str(qwen_settings.get("model") or settings.QWEN_MODEL),
                        qwen_prompt_version=ARTICLE_TRANSLATION_PROMPT_VERSION,
                        source_chars=len(source_markdown),
                    )
                    await paper_service.update_paper(
                        paper_id,
                        translation_status=f"translating_article:{index}/{total}",
                        translation_task_id=task_id,
                        translation_error="Исходный Markdown повреждён, повторная обработка по фото не восстановила страницу: " + final_source_error,
                    )
                    continue

                metadata = dict(getattr(part, "extraction_metadata", None) or {})
                metadata["translation_markdown_fallback"] = {
                    **regeneration_meta,
                    "source_quality_error": source_error,
                    "regenerated_quality_warnings": regenerated_quality.get("warnings") or [],
                }
                part.markdown_text = regenerated_markdown.strip()
                part.markdown_text_chars = len(part.markdown_text)
                part.status = "ready"
                part.error = None
                part.qwen_model = str(qwen_settings.get("model") or settings.QWEN_MODEL)
                part.qwen_prompt_version = ARTICLE_MARKDOWN_IMAGE_REGENERATION_PROMPT_VERSION
                part.extraction_method = "ai_page_image_translation_fallback"
                part.extraction_quality_score = 1.0
                part.extraction_metadata = metadata
                part.regeneration_count = int(getattr(part, "regeneration_count", 0) or 0) + 1
                await db.commit()
                await db.refresh(part)
                source_markdown = part.markdown_text
                try:
                    assembled_markdown = await part_service.assemble_markdown(paper_id)
                    if assembled_markdown:
                        stale_updates = _mark_ai_fields_stale(paper)
                        await paper_service.update_paper(
                            paper_id,
                            full_text=assembled_markdown,
                            **stale_updates,
                        )
                    else:
                        stale_updates = _mark_ai_fields_stale(paper)
                        if stale_updates:
                            await paper_service.update_paper(paper_id, **stale_updates)
                except Exception:
                    logger.debug("Failed to refresh paper.full_text after translation fallback markdown regeneration", exc_info=True)

            prompt = _build_article_translation_prompt(
                target_language_code=language_code,
                target_language_name=language_name,
                paper_title=paper.title,
                page_start=part.page_start,
                page_end=part.page_end,
            )

            result: dict[str, Any] | None = None
            response_text = ""
            translated_candidate = ""
            error_text = ""
            max_attempts = max(1, ARTICLE_TRANSLATION_MAX_ATTEMPTS)
            for attempt in range(1, max_attempts + 1):
                if attempt > 1:
                    retry_error = _format_translation_retry_error(error_text, attempt, max_attempts)
                    await _upsert_part_translation(
                        db,
                        paper_id=paper_id,
                        part_id=part.id,
                        language_code=language_code,
                        language_name=language_name,
                        source_language_code=source_language_code,
                        status="processing",
                        error=retry_error,
                        qwen_model=str(qwen_settings.get("model") or settings.QWEN_MODEL),
                        qwen_prompt_version=ARTICLE_TRANSLATION_PROMPT_VERSION,
                        source_chars=len(source_markdown),
                    )
                    await paper_service.update_paper(
                        paper_id,
                        translation_status=f"translating_article:{index - 1}/{total}",
                        translation_task_id=task_id,
                        translation_error=retry_error,
                    )
                    _safe_update_state(
                        self,
                        task_id,
                        "PROGRESS",
                        {
                            "paper_id": paper_id,
                            "stage": "translating_article",
                            "stage_label": "Перевод текста статьи: повторная попытка",
                            "current": index - 1,
                            "total": total,
                            "percent": round(((index - 1) / max(1, total)) * 100),
                            "language_code": language_code,
                            "page_start": part.page_start,
                            "page_end": part.page_end,
                            "retry_attempt": attempt,
                            "retry_total": max_attempts,
                            "error": error_text,
                        },
                    )
                    await asyncio.sleep(_translation_retry_delay_seconds(attempt - 1))

                file_path = temp_dir / f"paper_{paper_id}_part_{part.id}_{language_code}_try_{attempt}.md"
                file_path.write_text(source_markdown, encoding="utf-8")
                try:
                    attempt_session_id = await asyncio.to_thread(
                        create_qwen_session_for_paper,
                        paper_id,
                        f"{paper.title} — {language_name} — part {part.id} try {attempt}",
                    )
                    raw_result = await asyncio.to_thread(
                        client.upload_file_and_send_message,
                        file_path=str(file_path),
                        message=prompt,
                        session_id=attempt_session_id,
                        thinking_enabled=False,
                        search_enabled=False,
                        auto_continue=True,
                        timeout=qwen_timeout,
                        session_prompt="",
                    )
                except Exception as exc:
                    raw_result = {"error": f"{type(exc).__name__}: {exc}", "response": ""}
                finally:
                    try:
                        file_path.unlink(missing_ok=True)
                    except Exception:
                        logger.debug("Failed to delete temporary translation file {}", file_path, exc_info=True)

                result = raw_result if isinstance(raw_result, dict) else {"error": "invalid_qwen_response", "response": ""}
                error_text = str(result.get("error") or result.get("message") or "").strip()
                response_text = str(result.get("response") or "").strip()
                response_error = _extract_qwen_error_response(response_text)
                if response_error:
                    error_text = error_text or response_error
                    response_text = ""
                if response_text:
                    translated_candidate = _clean_qwen_markdown_response(response_text)
                    quality_error = _translation_output_quality_error(source_markdown, translated_candidate)
                    if not quality_error:
                        break
                    error_text = quality_error
                    response_text = ""
                    translated_candidate = ""

                if is_qwen_auth_expired_message(error_text):
                    break
                retryable = _is_transient_article_translation_error(error_text) or _is_retryable_translation_quality_error(error_text)
                if attempt >= max_attempts or not retryable:
                    break
                logger.warning(
                    "Qwen translation attempt will be retried: paper_id={}, part_id={}, attempt={}/{}, error={}",
                    paper_id,
                    part.id,
                    attempt + 1,
                    max_attempts,
                    error_text,
                )

            if error_text and not response_text:
                if is_qwen_auth_expired_message(error_text):
                    await _upsert_part_translation(
                        db,
                        paper_id=paper_id,
                        part_id=part.id,
                        language_code=language_code,
                        language_name=language_name,
                        source_language_code=source_language_code,
                        status="failed",
                        error="qwen_token_expired",
                        qwen_model=str(qwen_settings.get("model") or settings.QWEN_MODEL),
                        qwen_prompt_version=ARTICLE_TRANSLATION_PROMPT_VERSION,
                        source_chars=len(source_markdown),
                    )
                    await paper_service.update_paper(
                        paper_id,
                        translation_status="translation_failed",
                        translation_task_id=task_id,
                        translation_error="Токен Qwen истёк. Обновите QWEN_TOKEN.",
                    )
                    return {"ok": False, "paper_id": paper_id, "error": "qwen_token_expired"}
                failed_count += 1
                final_part_error = (
                    _format_translation_final_error(error_text, max_attempts)
                    if (_is_transient_article_translation_error(error_text) or _is_retryable_translation_quality_error(error_text))
                    else (error_text or "empty_qwen_response")
                )
                await _upsert_part_translation(
                    db,
                    paper_id=paper_id,
                    part_id=part.id,
                    language_code=language_code,
                    language_name=language_name,
                    source_language_code=source_language_code,
                    status="failed",
                    error=final_part_error,
                    qwen_model=str(qwen_settings.get("model") or settings.QWEN_MODEL),
                    qwen_prompt_version=ARTICLE_TRANSLATION_PROMPT_VERSION,
                    source_chars=len(source_markdown),
                )
                await paper_service.update_paper(
                    paper_id,
                    translation_status=f"translating_article:{index}/{total}",
                    translation_task_id=task_id,
                    translation_error=final_part_error,
                )
                continue

            translated = translated_candidate or _clean_qwen_markdown_response(response_text)
            if not translated:
                failed_count += 1
                await _upsert_part_translation(
                    db,
                    paper_id=paper_id,
                    part_id=part.id,
                    language_code=language_code,
                    language_name=language_name,
                    source_language_code=source_language_code,
                    status="failed",
                    error="empty_translation",
                    qwen_model=str(qwen_settings.get("model") or settings.QWEN_MODEL),
                    qwen_prompt_version=ARTICLE_TRANSLATION_PROMPT_VERSION,
                    source_chars=len(source_markdown),
                )
                continue

            await _upsert_part_translation(
                db,
                paper_id=paper_id,
                part_id=part.id,
                language_code=language_code,
                language_name=language_name,
                source_language_code=source_language_code,
                translated_markdown_text=translated,
                status="ready",
                qwen_model=str(qwen_settings.get("model") or settings.QWEN_MODEL),
                qwen_prompt_version=ARTICLE_TRANSLATION_PROMPT_VERSION,
                source_chars=len(source_markdown),
            )
            ready_count += 1
            fresh_paper = await paper_service.get_by_id(paper_id)
            await paper_service.update_paper(
                paper_id,
                available_language_codes=_merge_language_codes(
                    getattr(fresh_paper, "available_language_codes", None),
                    source_language_code,
                    language_code,
                ),
                translation_status=f"translating_article:{index}/{total}",
                translation_task_id=task_id,
                translation_error=None,
            )
            _safe_update_state(
                self,
                task_id,
                "PROGRESS",
                {
                    "paper_id": paper_id,
                    "stage": "translating_article",
                    "stage_label": "Перевод текста статьи",
                    "current": index,
                    "total": total,
                    "percent": round((index / max(1, total)) * 100),
                    "language_code": language_code,
                    "page_start": part.page_start,
                    "page_end": part.page_end,
                },
            )

        final_status = "translation_ready" if ready_count == total else "translation_partial" if ready_count > 0 else "translation_failed"
        final_error = None if final_status == "translation_ready" else f"ready={ready_count}, failed={failed_count}, skipped={skipped_count}, total={total}"
        fresh_paper = await paper_service.get_by_id(paper_id)
        await paper_service.update_paper(
            paper_id,
            available_language_codes=_merge_language_codes(
                getattr(fresh_paper, "available_language_codes", None),
                source_language_code,
                language_code if ready_count else None,
            ),
            translation_status=final_status,
            translation_task_id=task_id,
            translation_error=final_error,
        )
        return {
            "ok": ready_count > 0,
            "paper_id": paper_id,
            "language_code": language_code,
            "language_name": language_name,
            "ready": ready_count,
            "failed": failed_count,
            "skipped": skipped_count,
            "total": total,
            "status": final_status,
        }


@celery_app.task(
    bind=True,
    name="app.tasks.qwen.regenerate_markdown_part",
    rate_limit=_qwen_queue_rate_limit(),
    acks_late=True,
    soft_time_limit=int(max(60, settings.QWEN_QUEUE_TIMEOUT + 30)),
    time_limit=int(max(90, settings.QWEN_QUEUE_TIMEOUT + 90)),
)
def regenerate_markdown_part_task(self, paper_id: int, part_id: int, mode: str = "text") -> dict[str, Any]:
    """Regenerate Markdown only for one stored PDF/content part."""
    task_id = _task_id(self)
    mode = _normalize_regeneration_mode(mode)
    try:
        return run_async(_regenerate_markdown_part_async(self, paper_id, part_id, mode=mode, task_id=task_id))
    except Exception as exc:
        logger.exception("Qwen markdown part regeneration failed: paper_id={}, part_id={}, mode={}, error={}", paper_id, part_id, mode, exc)
        raise


async def _regenerate_markdown_part_async(
    self,
    paper_id: int,
    part_id: int,
    mode: str = "text",
    task_id: str | None = None,
) -> dict[str, Any]:
    mode = _normalize_regeneration_mode(mode)
    _safe_update_state(
        self,
        task_id,
        "STARTED",
        {
            "paper_id": paper_id,
            "part_id": part_id,
            "mode": mode,
            "stage": "regenerating_markdown_part",
            "stage_label": "Повторная оцифровка части" if mode == "text" else "Повторное извлечение текста страницы" if mode in {"auto", "mypdf"} else "Повторная оцифровка части по фото",
        },
    )

    async with async_session_maker() as db:
        paper_service = PaperService(db)
        part_service = PaperContentPartService(db)
        paper = await paper_service.get_by_id(paper_id)
        if not paper:
            return {"status": "error", "paper_id": paper_id, "part_id": part_id, "error": "paper_not_found"}

        part = await part_service.get_part(paper_id, part_id)
        if not part:
            return {"status": "error", "paper_id": paper_id, "part_id": part_id, "error": "part_not_found"}

        qwen_settings = await _get_qwen_settings(db)
        pdf_markdown_settings = await _get_pdf_markdown_settings(db)
        if not qwen_settings.get("markdown_enabled", True):
            await part_service.set_part_failed(part, "qwen_markdown_disabled")
            await paper_service.update_paper(paper_id, processing_status="markdown_skipped", content_task_id=task_id, processing_error="qwen_markdown_disabled")
            return {"status": "error", "paper_id": paper_id, "part_id": part_id, "error": "qwen_markdown_disabled"}
        page_char_limit = int(pdf_markdown_settings.get("page_chars") or settings.QWEN_MARKDOWN_PAGE_CHARS)
        normalize_math = bool(pdf_markdown_settings.get("normalize_math", True))
        qwen_timeout = float(qwen_settings.get("request_timeout_seconds") or settings.QWEN_QUEUE_TIMEOUT)

        if mode == "text" and not should_qwen_markdown_content_type(getattr(part, "content_type", "body")):
            await part_service.set_part_ready_without_markdown(part)
            full_text = await part_service.assemble_markdown(paper_id)
            await paper_service.update_paper(
                paper_id,
                full_text=full_text,
                processing_status="page_regenerated",
                content_task_id=task_id,
                processing_error=None,
                **_mark_ai_fields_stale(paper),
            )
            return {
                "status": "ok",
                "paper_id": paper_id,
                "part_id": part_id,
                "mode": mode,
                "page_start": part.page_start,
                "page_end": part.page_end,
                "markdown_text_chars": 0,
                "regeneration_count": int(part.regeneration_count or 0),
                "markdown_skipped": True,
                "content_type": getattr(part, "content_type", "body"),
            }

        if mode in {"image", "ai", "auto", "mypdf"}:
            try:
                raw_text, regeneration_metadata = await asyncio.to_thread(
                    _extract_part_pdf_pages_as_text,
                    pdf_path=str(getattr(paper, "pdf_local_path", "") or ""),
                    paper_id=paper_id,
                    part_id=part_id,
                    page_start=int(part.page_start or 1),
                    page_end=int(part.page_end or part.page_start or 1),
                    mode=mode,
                    pdf_markdown_settings=pdf_markdown_settings,
                    qwen_settings=qwen_settings,
                    timeout=qwen_timeout,
                )
            except Exception as exc:
                error_text = str(exc)
                await part_service.set_part_failed(part, error_text)
                await paper_service.update_paper(paper_id, processing_status="markdown_failed", content_task_id=task_id, processing_error=error_text)
                return {"status": "error", "paper_id": paper_id, "part_id": part_id, "mode": mode, "error": error_text}

            if raw_text:
                metadata = dict(getattr(part, "extraction_metadata", None) or {})
                warnings = set(str(item) for item in (getattr(part, "extraction_warnings", None) or []) if item)
                warnings.update(str(item) for item in regeneration_metadata.get("warnings", []) if item)
                metadata["pdf_page_regeneration"] = regeneration_metadata
                part.raw_text = raw_text
                part.raw_text_chars = len(raw_text)
                if regeneration_metadata.get("method"):
                    part.extraction_method = str(regeneration_metadata.get("method"))
                if regeneration_metadata.get("quality_score") is not None:
                    try:
                        part.extraction_quality_score = float(regeneration_metadata.get("quality_score"))
                    except (TypeError, ValueError):
                        pass
                part.extraction_warnings = sorted(warnings)
                part.extraction_metadata = metadata
                _mark_regenerated_part_quality(part, mode=mode, raw_text=raw_text)
                await db.commit()
                await db.refresh(part)
        else:
            raw_text = _qwen_input_text_for_part(part)
        if not raw_text:
            await part_service.set_part_ready_without_markdown(part)
            full_text = await part_service.assemble_markdown(paper_id)
            await paper_service.update_paper(
                paper_id,
                full_text=full_text,
                processing_status="page_regenerated",
                content_task_id=task_id,
                processing_error=None,
                **_mark_ai_fields_stale(paper),
            )
            return {"status": "ok", "paper_id": paper_id, "part_id": part_id, "mode": mode, "markdown_skipped": True, "error": "empty_qwen_projection"}

        await part_service.set_part_processing(part)
        total_parts = len(await part_service.list_parts(paper_id)) or max(1, part.part_index)
        await paper_service.update_paper(
            paper_id,
            processing_status=f"digitizing_file:{max(0, part.part_index - 1)}/{total_parts}",
            content_task_id=task_id,
            processing_error=None,
        )

        session_id = await asyncio.to_thread(create_qwen_session_for_paper, paper_id, paper.title)
        try:
            markdown_text = await asyncio.to_thread(
                normalize_pdf_text_part,
                paper_id,
                paper.title,
                raw_text,
                part.page_start,
                part.page_end,
                session_id,
                include_full_instruction=True,
                page_char_limit=page_char_limit,
                timeout_seconds=qwen_timeout,
                normalize_math=normalize_math,
            )
        except Exception as exc:
            error_text = str(exc)
            if is_qwen_auth_expired_message(error_text):
                await part_service.set_part_failed(part, "qwen_token_expired")
                await paper_service.update_paper(
                    paper_id,
                    processing_status="qwen_auth_failed",
                    content_task_id=task_id,
                    processing_error="Токен Qwen истёк. Обновите QWEN_TOKEN.",
                )
                return {"status": "error", "paper_id": paper_id, "part_id": part_id, "error": "qwen_token_expired"}
            await part_service.set_part_failed(part, error_text)
            await paper_service.update_paper(paper_id, processing_status="markdown_failed", content_task_id=task_id, processing_error=error_text)
            return {"status": "error", "paper_id": paper_id, "part_id": part_id, "error": error_text}

        if not markdown_text:
            await part_service.set_part_failed(part, "qwen_markdown_empty")
            await paper_service.update_paper(paper_id, processing_status="markdown_failed", content_task_id=task_id, processing_error="qwen_markdown_empty")
            return {"status": "error", "paper_id": paper_id, "part_id": part_id, "error": "qwen_markdown_empty"}

        await part_service.set_part_markdown(
            part,
            markdown_text,
            qwen_model=str(qwen_settings.get("model") or settings.QWEN_MODEL),
            prompt_version=f"{PDF_MARKDOWN_PROMPT_VERSION}:{mode}",
            increment_regeneration=True,
        )
        full_text = await part_service.assemble_markdown(paper_id)
        _mark_regenerated_part_quality(part, mode=mode, raw_text=raw_text)
        await db.commit()
        await paper_service.update_paper(
            paper_id,
            full_text=full_text,
            processing_status="page_regenerated",
            content_task_id=task_id,
            processing_error=None,
            **_mark_ai_fields_stale(paper),
        )
        return {
            "status": "ok",
            "paper_id": paper_id,
            "part_id": part_id,
            "mode": mode,
            "page_start": part.page_start,
            "page_end": part.page_end,
            "markdown_text_chars": len(markdown_text),
            "regeneration_count": int(part.regeneration_count or 0),
            "image_regeneration": regeneration_metadata if mode in {"image", "ai"} else None,
        }
