"""Celery tasks for article content pipeline: PDF, text extraction, embeddings.

The old ``process_paper_content_task`` used to do everything in one long task.
It is kept as a backward-compatible entry point, but now it only launches a
chain of small tasks. Qwen-specific stages live in ``app.tasks.qwen_tasks`` and
are routed to the controlled ``qwen`` queue.
"""

from __future__ import annotations

import asyncio
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
    fetch_additional_full_text,
    resolve_pdf_url,
    save_pdf_locally,
)
from app.services.paper_service import PaperService
from app.services.paper_content_part_service import PaperContentPartService
from app.services.system_settings_service import (
    get_pdf_markdown_settings_safe,
    get_postprocess_settings_safe,
)
from app.services.vector_service import get_vector_service
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app


PIPELINE_VERSION = "content-pipeline-v2"


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


def enqueue_paper_content_pipeline(paper_id: int, root_task_id: str | None = None):
    """Start the article post-processing pipeline for one paper.

    Big text/PDF payloads are never passed through Celery results. Every stage
    receives a small dict with ``paper_id`` and reads/writes article data in DB.
    """
    content_queue = settings.CONTENT_QUEUE_NAME
    qwen_queue = settings.QWEN_QUEUE_NAME

    workflow = chain(
        download_pdf_task.s(paper_id, root_task_id).set(queue=content_queue),
        extract_pdf_text_task.s().set(queue=content_queue),
        celery_app.signature("app.tasks.qwen.markdown").set(queue=qwen_queue),
        celery_app.signature("app.tasks.qwen.ru_analysis").set(queue=qwen_queue),
        celery_app.signature("app.tasks.qwen.keywords").set(queue=qwen_queue),
        build_embedding_task.s().set(queue=content_queue),
        finalize_paper_processing_task.s().set(queue=content_queue),
    )
    return workflow.apply_async()


@celery_app.task(bind=True)
def process_paper_content_task(self, paper_id: int) -> dict[str, Any]:
    """Backward-compatible entry point used by parser endpoints/tasks.

    It no longer performs PDF/Qwen work directly. It only marks the paper as
    queued and launches the real stage-by-stage pipeline.
    """
    task_id = _task_id(self)
    try:
        result = enqueue_paper_content_pipeline(paper_id, root_task_id=task_id)
        logger.info(
            "Content pipeline queued: paper_id={}, root_task_id={}, chain_result_id={}",
            paper_id,
            task_id,
            getattr(result, "id", None),
        )
        return {
            "status": "queued",
            "paper_id": paper_id,
            "root_task_id": task_id,
            "chain_result_id": getattr(result, "id", None),
            "pipeline": PIPELINE_VERSION,
        }
    except Exception as exc:
        logger.exception("Failed to queue content pipeline for paper {}: {}", paper_id, exc)
        raise


@celery_app.task(bind=True, acks_late=True)
def download_pdf_task(self, paper_id: int, root_task_id: str | None = None) -> dict[str, Any]:
    task_id = _task_id(self)
    try:
        return run_async(_download_pdf_async(self, paper_id, root_task_id=root_task_id, task_id=task_id))
    except Exception as exc:
        logger.exception("PDF download task failed for paper {}: {}", paper_id, exc)
        raise


async def _download_pdf_async(
    self,
    paper_id: int,
    root_task_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    task_id = task_id or root_task_id
    _safe_update_state(self, task_id, "STARTED", {"paper_id": paper_id, "stage": "downloading_pdf"})

    async with async_session_maker() as db:
        paper_service = PaperService(db)
        paper = await paper_service.get_by_id(paper_id)
        if not paper:
            return {"status": "error", "paper_id": paper_id, "error": "paper_not_found", "root_task_id": root_task_id}

        postprocess = await _get_postprocess_settings(db)
        if not postprocess.get("download_pdf", True):
            await _set_stage(paper_service, paper_id, "pdf_download_skipped", task_id=task_id, error="download_pdf_disabled")
            return {
                "status": "ok",
                "paper_id": paper_id,
                "root_task_id": root_task_id,
                "pdf_downloaded": False,
                "pdf_skipped": True,
                "pipeline": PIPELINE_VERSION,
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
                "root_task_id": root_task_id,
                "pdf_downloaded": False,
                "pdf_url": pdf_url,
                "pipeline": PIPELINE_VERSION,
            }

        pdf_local_path = await asyncio.to_thread(save_pdf_locally, paper_id, pdf_bytes)
        await paper_service.update_paper(paper_id, pdf_local_path=pdf_local_path)
        await _set_stage(paper_service, paper_id, "pdf_downloaded", task_id=task_id, error=None)

        return {
            "status": "ok",
            "paper_id": paper_id,
            "root_task_id": root_task_id,
            "pdf_downloaded": True,
            "pdf_local_path": pdf_local_path,
            "pdf_url": pdf_url,
            "pipeline": PIPELINE_VERSION,
        }


@celery_app.task(bind=True, acks_late=True)
def extract_pdf_text_task(self, previous: dict[str, Any]) -> dict[str, Any]:
    task_id = _task_id(self)
    try:
        return run_async(_extract_pdf_text_async(self, previous, task_id=task_id))
    except Exception as exc:
        paper_id = _paper_id_from_previous(previous)
        logger.exception("PDF text extraction task failed for paper {}: {}", paper_id, exc)
        raise


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
                text_available=bool((paper.full_text or paper.abstract or "").strip()),
                text_source="existing_or_abstract",
                text_skipped=True,
            )

        pdf_markdown = await _get_pdf_markdown_settings(db)
        save_raw_parts = bool(pdf_markdown.get("save_raw_parts", True))
        pages_per_part = max(1, int(pdf_markdown.get("pages_per_request") or settings.QWEN_MARKDOWN_PAGES_PER_REQUEST or 1))

        extracted_page_items: list[dict[str, Any]] = []
        extracted_pages: list[str] = []
        extracted_text = ""
        pdf_local_path = (paper.pdf_local_path or "").strip()
        if pdf_local_path and Path(pdf_local_path).exists():
            await _set_stage(paper_service, paper_id, "extracting_pdf_text", task_id=task_id, error=None)
            pdf_bytes = await asyncio.to_thread(Path(pdf_local_path).read_bytes)
            extraction_options = {
                "extraction_mode": pdf_markdown.get("extraction_mode", "auto"),
                "detect_columns": pdf_markdown.get("detect_columns", True),
                "extract_tables": pdf_markdown.get("extract_tables", True),
                "remove_headers_footers": pdf_markdown.get("remove_headers_footers", True),
                "merge_hyphenated_words": pdf_markdown.get("merge_hyphenated_words", True),
                "normalize_math": pdf_markdown.get("normalize_math", True),
                "mark_formula_candidates": pdf_markdown.get("mark_formula_candidates", True),
                "ocr_enabled": pdf_markdown.get("ocr_enabled", False),
                "ocr_dpi": pdf_markdown.get("ocr_dpi", 220),
                "ocr_languages": pdf_markdown.get("ocr_languages", "eng+rus"),
                "min_text_chars": pdf_markdown.get("min_text_chars", 300),
                "max_page_chars": pdf_markdown.get("max_page_chars", 60000),
            }
            extracted_page_items = await asyncio.to_thread(extract_pdf_page_items, pdf_bytes, extraction_options)
            extracted_pages = [str(item.get("text") or "") for item in extracted_page_items]
            extracted_text = "\n\n".join(page for page in extracted_pages if page and page.strip()).strip()

        if extracted_text:
            if save_raw_parts:
                part_service = PaperContentPartService(db)
                await part_service.replace_raw_parts(paper_id, extracted_page_items or extracted_pages or [extracted_text], source="pdf", pages_per_part=pages_per_part)
            await paper_service.update_paper(paper_id, full_text=extracted_text)
            await _set_stage(paper_service, paper_id, "pdf_parsed", task_id=task_id, error=None)
            return _merge_previous(
                previous,
                status="ok",
                paper_id=paper_id,
                root_task_id=root_task_id,
                text_available=True,
                text_source="pdf",
                content_parts_count=len(extracted_pages or [extracted_text]),
            )

        fallback_text = await asyncio.to_thread(
            fetch_additional_full_text,
            paper.source,
            paper.source_id,
            paper.url,
            paper.abstract or "",
        )
        if fallback_text:
            if save_raw_parts:
                part_service = PaperContentPartService(db)
                await part_service.replace_raw_parts(paper_id, [fallback_text], source="fallback_fulltext", pages_per_part=1)
            await paper_service.update_paper(paper_id, full_text=fallback_text)
            await _set_stage(paper_service, paper_id, "fulltext_fallback_parsed", task_id=task_id, error=None)
            return _merge_previous(
                previous,
                status="ok",
                paper_id=paper_id,
                root_task_id=root_task_id,
                text_available=True,
                text_source="fallback_fulltext",
                content_parts_count=1,
            )

        await _set_stage(paper_service, paper_id, "fulltext_unavailable", task_id=task_id, error=None)
        return _merge_previous(
            previous,
            status="ok",
            paper_id=paper_id,
            root_task_id=root_task_id,
            text_available=bool((paper.abstract or "").strip()),
            text_source="abstract" if (paper.abstract or "").strip() else "none",
        )


@celery_app.task(bind=True, acks_late=True)
def build_embedding_task(self, previous: dict[str, Any]) -> dict[str, Any]:
    task_id = _task_id(self)
    try:
        return run_async(_build_embedding_async(self, previous, task_id=task_id))
    except Exception as exc:
        paper_id = _paper_id_from_previous(previous)
        logger.exception("Embedding task failed for paper {}: {}", paper_id, exc)
        raise


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

        content_text = (paper.full_text or paper.abstract or "").strip()
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
        raise


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

        had_qwen_fallback = bool((paper.processing_error or "").strip())
        has_ai = bool((paper.summary_ru or "").strip() or (paper.analysis_ru or "").strip())
        has_text = bool((paper.full_text or paper.abstract or "").strip())

        if not has_text:
            final_stage = "failed"
            error = paper.processing_error or "no_text_available"
        elif had_qwen_fallback or not has_ai:
            final_stage = "ready_with_fallback"
            error = paper.processing_error
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
