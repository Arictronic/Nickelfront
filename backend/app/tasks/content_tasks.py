"""Celery tasks for article post-processing: PDF, RU analysis, vector indexing."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from app.db.session import async_session_maker
from app.services.embedding_service import get_embedding_service
from app.services.paper_content_service import (
    create_qwen_session_for_paper,
    download_pdf_bytes,
    extract_pdf_text,
    fetch_additional_full_text,
    generate_ai_enrichment_ru,
    normalize_pdf_text_markdown,
    resolve_pdf_url,
    save_pdf_locally,
)
from app.services.paper_service import PaperService
from app.services.vector_service import get_vector_service
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app


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


@celery_app.task(bind=True)
def process_paper_content_task(self, paper_id: int) -> dict[str, Any]:
    try:
        return run_async(_process_paper_content_async(self, paper_id))
    except Exception as exc:
        logger.exception("Ошибка post-processing статьи {}: {}", paper_id, exc)
        raise


async def _process_paper_content_async(self, paper_id: int) -> dict[str, Any]:
    task_id = getattr(getattr(self, "request", None), "id", None)
    self.update_state(state="STARTED", meta={"paper_id": paper_id, "stage": "started"})

    try:
        async with async_session_maker() as db:
            paper_service = PaperService(db)
            paper = await paper_service.get_by_id(paper_id)
            if not paper:
                return {"status": "error", "paper_id": paper_id, "error": "paper_not_found"}

            await _set_stage(paper_service, paper_id, "pdf_pending", task_id=task_id, error=None)

            pdf_url = resolve_pdf_url(paper.source, paper.source_id, paper.url)
            if pdf_url and pdf_url != paper.pdf_url:
                await paper_service.update_paper(paper_id, pdf_url=pdf_url)

            self.update_state(state="STARTED", meta={"paper_id": paper_id, "stage": "downloading_pdf"})
            pdf_bytes = await asyncio.to_thread(download_pdf_bytes, pdf_url) if pdf_url else None

            extracted_text = ""
            pdf_local_path = None
            if pdf_bytes:
                await _set_stage(paper_service, paper_id, "pdf_downloaded", task_id=task_id)
                pdf_local_path = await asyncio.to_thread(save_pdf_locally, paper_id, pdf_bytes)
                extracted_text = await asyncio.to_thread(extract_pdf_text, pdf_bytes)

            if pdf_local_path:
                await paper_service.update_paper(paper_id, pdf_local_path=pdf_local_path)

            if extracted_text:
                await _set_stage(paper_service, paper_id, "pdf_parsed", task_id=task_id)
                await paper_service.update_paper(paper_id, full_text=extracted_text)
            else:
                fallback_text = await asyncio.to_thread(
                    fetch_additional_full_text,
                    paper.source,
                    paper.source_id,
                    paper.url,
                    paper.abstract or "",
                )
                if fallback_text:
                    await _set_stage(paper_service, paper_id, "fulltext_fallback_parsed", task_id=task_id)
                    await paper_service.update_paper(paper_id, full_text=fallback_text)

            # Reload updated paper to use freshest content.
            paper = await paper_service.get_by_id(paper_id)
            content_text = (paper.full_text or paper.abstract or "").strip()
            session_id = await asyncio.to_thread(
                create_qwen_session_for_paper,
                paper_id,
                paper.title,
            )

            if pdf_bytes and content_text:
                await _set_stage(paper_service, paper_id, "formatting_markdown", task_id=task_id)
                loop = asyncio.get_running_loop()

                def _on_page_markdown(_page_idx: int, current_markdown: str) -> None:
                    future = asyncio.run_coroutine_threadsafe(
                        paper_service.update_paper(paper_id, full_text=current_markdown),
                        loop,
                    )
                    future.result(timeout=30)

                markdown_text = await asyncio.to_thread(
                    normalize_pdf_text_markdown,
                    paper_id,
                    paper.title,
                    content_text,
                    session_id,
                    _on_page_markdown,
                )
                if markdown_text:
                    await paper_service.update_paper(paper_id, full_text=markdown_text)
                    content_text = markdown_text

            await _set_stage(paper_service, paper_id, "analyzing_ru", task_id=task_id)
            enrichment = await asyncio.to_thread(
                generate_ai_enrichment_ru,
                paper.title,
                paper.abstract or "",
                content_text,
                session_id,
            )

            fallback_reason = enrichment.fallback_reason if enrichment.used_fallback else None
            await paper_service.update_paper(
                paper_id,
                summary_ru=enrichment.summary_ru,
                analysis_ru=enrichment.analysis_ru,
                translation_ru=enrichment.translation_ru,
                processing_error=fallback_reason,
            )

            await _set_stage(paper_service, paper_id, "indexing_vector", task_id=task_id)
            embedding_service = get_embedding_service()
            vector_service = get_vector_service()

            embedding_available = await asyncio.to_thread(lambda: embedding_service.model is not None)
            embedded = False
            if embedding_available and content_text:
                embedding_text = await asyncio.to_thread(
                    lambda: " | ".join(
                        part
                        for part in [
                            f"Title: {paper.title}" if paper.title else "",
                            f"Abstract: {paper.abstract}" if paper.abstract else "",
                            (
                                f"Keywords: {', '.join(paper.keywords or [])}"
                                if (paper.keywords and len(paper.keywords) > 0)
                                else ""
                            ),
                            f"Content: {content_text[:12000]}" if content_text else "",
                        ]
                        if part
                    )
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

            final_stage = "ready_with_fallback" if enrichment.used_fallback else "ready"
            await _set_stage(
                paper_service,
                paper_id,
                final_stage,
                task_id=task_id,
                error=fallback_reason,
            )
            self.update_state(state="SUCCESS", meta={"paper_id": paper_id, "stage": final_stage})

            return {
                "status": "ok",
                "paper_id": paper_id,
                "pdf_url": pdf_url,
                "pdf_local_path": pdf_local_path,
                "text_length": len(content_text),
                "embedded": embedded,
            }
    except Exception as exc:
        async with async_session_maker() as db:
            paper_service = PaperService(db)
            await _set_stage(
                paper_service,
                paper_id,
                "failed",
                task_id=task_id,
                error=str(exc),
            )
        raise
