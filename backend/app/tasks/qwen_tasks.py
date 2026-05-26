"""Shared Qwen Celery gateway tasks and article Qwen stages.

The queue can be served by up to QWEN_QUEUE_WORKERS workers.  Background callers
should either enqueue one raw Qwen message through ``app.tasks.qwen.send_message``
or use the article-stage tasks below: markdown, RU analysis, keywords.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from app.core.config import settings
from app.db.session import async_session_maker
from app.services.paper_content_service import (
    create_qwen_session_for_paper,
    generate_ai_enrichment_ru,
    generate_article_keywords,
    normalize_pdf_text_part,
    PDF_MARKDOWN_PROMPT_VERSION,
)
from app.services.paper_service import PaperService
from app.services.paper_content_part_service import (
    PaperContentPartService,
    get_qwen_projection_text_for_part,
    should_qwen_markdown_content_type,
)
from app.services.system_settings_service import (
    get_pdf_markdown_settings_safe,
    get_postprocess_settings_safe,
    get_qwen_settings_safe,
)
from app.services.qwen_client import QwenServiceClient
from app.services.qwen_token_tools import is_qwen_auth_expired_message
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app


def _page_markdown_heading(page_start: int | None, page_end: int | None) -> str:
    if not page_start or not page_end:
        return "### Страница"
    if page_start == page_end:
        return f"### Страница {page_start}"
    return f"### Страницы {page_start}-{page_end}"


def _qwen_input_text_for_part(part: Any) -> str:
    """Return sanitized block-aware text for Qwen markdown normalization."""
    return get_qwen_projection_text_for_part(part)


def _fresh_markdown_input_available(previous: dict[str, Any]) -> bool:
    """Return whether this chain produced fresh text safe for Qwen markdown.

    Qwen must not read arbitrary existing ``paper_content_parts`` after a failed
    PDF/extraction stage. Abstract-only content is enough for RU analysis, but it
    is not a PDF markdown-normalization input.
    """
    if not isinstance(previous, dict):
        return False
    if previous.get("markdown_input_available") is True:
        return True
    return bool(previous.get("fresh_content_available")) and str(previous.get("text_source") or "") in {"pdf", "fallback_fulltext"}


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
        return str(previous.get("root_task_id") or previous.get("content_task_id") or fallback or "") or None
    return fallback


def _merge_previous(previous: Any, **updates: Any) -> dict[str, Any]:
    if isinstance(previous, dict):
        payload = dict(previous)
    else:
        payload = {"paper_id": _paper_id_from_previous(previous)}
    payload.update(updates)
    return payload


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
        raise


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
        raise


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
    """Generate article keywords/entities through Qwen."""
    task_id = _task_id(self)
    try:
        return run_async(_qwen_keywords_async(self, previous, task_id=task_id))
    except Exception as exc:
        paper_id = _paper_id_from_previous(previous)
        logger.exception("Qwen keywords task failed for paper {}: {}", paper_id, exc)
        raise


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

        try:
            keywords = await asyncio.to_thread(
                generate_article_keywords,
                title=paper.title,
                authors=paper.authors or [],
                journal=paper.journal,
                doi=paper.doi,
                source=paper.source,
                source_id=paper.source_id,
                url=paper.url,
                abstract=paper.abstract,
                full_text=paper.full_text,
                existing_keywords=paper.keywords or [],
                summary_ru=paper.summary_ru,
                analysis_ru=paper.analysis_ru,
                translation_ru=paper.translation_ru,
                session_id=session_id,
                timeout_seconds=qwen_timeout,
            )
            if keywords:
                await paper_service.update_paper(paper_id, keywords=keywords)
            await _set_stage(paper_service, paper_id, "keywords_ready", task_id=task_id, error=None)
            return _merge_previous(
                previous,
                paper_id=paper_id,
                root_task_id=root_task_id,
                session_id=session_id,
                keywords_ready=True,
                keywords_count=len(keywords or []),
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


@celery_app.task(
    bind=True,
    name="app.tasks.qwen.regenerate_markdown_part",
    rate_limit=_qwen_queue_rate_limit(),
    acks_late=True,
    soft_time_limit=int(max(60, settings.QWEN_QUEUE_TIMEOUT + 30)),
    time_limit=int(max(90, settings.QWEN_QUEUE_TIMEOUT + 90)),
)
def regenerate_markdown_part_task(self, paper_id: int, part_id: int) -> dict[str, Any]:
    """Regenerate Markdown only for one stored PDF/content part."""
    task_id = _task_id(self)
    try:
        return run_async(_regenerate_markdown_part_async(self, paper_id, part_id, task_id=task_id))
    except Exception as exc:
        logger.exception("Qwen markdown part regeneration failed: paper_id={}, part_id={}, error={}", paper_id, part_id, exc)
        raise


async def _regenerate_markdown_part_async(
    self,
    paper_id: int,
    part_id: int,
    task_id: str | None = None,
) -> dict[str, Any]:
    _safe_update_state(
        self,
        task_id,
        "STARTED",
        {"paper_id": paper_id, "part_id": part_id, "stage": "regenerating_markdown_part", "stage_label": "Повторная оцифровка части"},
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

        if not should_qwen_markdown_content_type(getattr(part, "content_type", "body")):
            await part_service.set_part_ready_without_markdown(part)
            full_text = await part_service.assemble_markdown(paper_id)
            await paper_service.update_paper(
                paper_id,
                full_text=full_text,
                processing_status="markdown_ready",
                content_task_id=task_id,
                processing_error=None,
            )
            return {
                "status": "ok",
                "paper_id": paper_id,
                "part_id": part_id,
                "page_start": part.page_start,
                "page_end": part.page_end,
                "markdown_text_chars": 0,
                "regeneration_count": int(part.regeneration_count or 0),
                "markdown_skipped": True,
                "content_type": getattr(part, "content_type", "body"),
            }

        raw_text = _qwen_input_text_for_part(part)
        if not raw_text:
            await part_service.set_part_ready_without_markdown(part)
            full_text = await part_service.assemble_markdown(paper_id)
            await paper_service.update_paper(
                paper_id,
                full_text=full_text,
                processing_status="markdown_ready",
                content_task_id=task_id,
                processing_error=None,
            )
            return {"status": "ok", "paper_id": paper_id, "part_id": part_id, "markdown_skipped": True, "error": "empty_qwen_projection"}

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
            prompt_version=PDF_MARKDOWN_PROMPT_VERSION,
            increment_regeneration=True,
        )
        full_text = await part_service.assemble_markdown(paper_id)
        await paper_service.update_paper(
            paper_id,
            full_text=full_text,
            processing_status="markdown_ready",
            content_task_id=task_id,
            processing_error=None,
        )
        return {
            "status": "ok",
            "paper_id": paper_id,
            "part_id": part_id,
            "page_start": part.page_start,
            "page_end": part.page_end,
            "markdown_text_chars": len(markdown_text),
            "regeneration_count": int(part.regeneration_count or 0),
        }
