"""Celery tasks triggered from the operational dashboard.

These tasks intentionally do not run heavy work inside FastAPI requests.  The
HTTP layer only validates permissions and enqueues one of these jobs; the worker
then fans out smaller content/embedding/vector tasks where appropriate.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger
from sqlalchemy import String, and_, cast, exists, func, or_, select

from app.core.config import settings
from app.db.models.paper import Paper as PaperModel
from app.db.models.paper_content_part import PaperContentPart
from app.db.session import async_session_maker
from app.services.paper_service import PaperService
from app.services.vector_service import get_vector_service
from app.services.pdf_parser.compat import Document
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app
from app.tasks.content_tasks import build_embedding_task, process_paper_content_task

CONTENT_ERROR_STATUSES = {
    "failed",
    "pdf_download_failed",
    "markdown_failed",
    "keywords_failed",
    "qwen_auth_failed",
}
CONTENT_ACTIVE_STATUSES = {
    "queued_for_content_processing",
    "processing_content",
    "pdf_pending",
    "downloading_pdf",
    "extracting_pdf_text",
    "formatting_markdown",
    "digitizing_file",
    "analyzing_ru",
    "extracting_keywords",
    "indexing_vector",
}


def _task_id(task_self: Any) -> str | None:
    return getattr(getattr(task_self, "request", None), "id", None)


def _safe_update_state(task_self: Any, state: str, meta: dict[str, Any]) -> None:
    task_id = _task_id(task_self)
    if not task_id:
        return
    try:
        task_self.update_state(task_id=task_id, state=state, meta=meta)
    except Exception as exc:
        logger.warning("Failed to update dashboard action state: task_id={}, state={}, error={}", task_id, state, exc)


def _text_present_expr(column):
    return and_(column.isnot(None), func.length(func.trim(cast(column, String))) > 0)


def _json_present_expr(column):
    text_value = func.trim(cast(column, String))
    return and_(
        column.isnot(None),
        func.length(text_value) > 2,
        text_value.notin_(["[]", "{}", "null", "NULL", ""]),
    )


def _normalize_limit(value: Any, *, default: int = 100, maximum: int = 1000) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(maximum, parsed))


def _normalize_source(value: Any) -> str | None:
    source = str(value or "").strip()
    if not source or source == "all":
        return None
    return source


def _paper_projection(paper: PaperModel) -> dict[str, Any]:
    return {
        "paper_id": paper.id,
        "embedding": paper.embedding,
        "title": paper.title or f"Paper #{paper.id}",
        "source": paper.source or "unknown",
        "doi": paper.doi,
        "publication_date": paper.publication_date.isoformat() if paper.publication_date else None,
        "journal": paper.journal,
    }


async def _queue_content_candidates_async(
    task_self: Any,
    *,
    limit: int,
    pdf_mode: str | None,
    failed_only: bool,
    source: str | None,
) -> dict[str, Any]:
    task_id = _task_id(task_self)
    limit = _normalize_limit(limit, default=100, maximum=500)
    source = _normalize_source(source)
    pdf_mode = str(pdf_mode or "auto").strip().lower()
    if pdf_mode not in {"auto", "ai", "mypdf"}:
        pdf_mode = "auto"

    _safe_update_state(task_self, "STARTED", {"stage": "selecting_candidates", "limit": limit, "source": source or "all"})

    async with async_session_maker() as db:
        paper_service = PaperService(db)
        active_expr = PaperModel.processing_status.in_(sorted(CONTENT_ACTIVE_STATUSES))
        source_expr = PaperModel.source == source if source else True
        content_parts_expr = exists(
            select(PaperContentPart.id).where(
                and_(
                    PaperContentPart.paper_id == PaperModel.id,
                    or_(_text_present_expr(PaperContentPart.markdown_text), _text_present_expr(PaperContentPart.raw_text)),
                )
            )
        )
        full_text_expr = _text_present_expr(PaperModel.full_text)
        abstract_expr = _text_present_expr(PaperModel.abstract)
        processable_source_expr = or_(
            _text_present_expr(PaperModel.pdf_url),
            _text_present_expr(PaperModel.pdf_local_path),
            _text_present_expr(PaperModel.url),
            _text_present_expr(PaperModel.source_id),
            abstract_expr,
            full_text_expr,
            content_parts_expr,
        )
        missing_content_expr = and_(
            ~content_parts_expr,
            or_(~full_text_expr, PaperModel.processing_status.in_(["pending", "embedding_skipped"])),
        )

        if failed_only:
            candidate_expr = and_(
                or_(
                    PaperModel.processing_status.in_(sorted(CONTENT_ERROR_STATUSES)),
                    _text_present_expr(PaperModel.processing_error),
                ),
                processable_source_expr,
                ~active_expr,
            )
        else:
            candidate_expr = and_(missing_content_expr, processable_source_expr, ~active_expr)

        stmt = (
            select(PaperModel.id)
            .where(and_(candidate_expr, source_expr))
            .order_by(PaperModel.updated_at.asc().nullsfirst(), PaperModel.created_at.desc(), PaperModel.id.desc())
            .limit(limit)
        )
        paper_ids = [int(row[0]) for row in (await db.execute(stmt)).all()]

        queued = 0
        errors: list[str] = []
        for index, paper_id in enumerate(paper_ids, start=1):
            _safe_update_state(
                task_self,
                "PROGRESS",
                {"stage": "queueing_content", "current": index, "total": len(paper_ids), "queued": queued},
            )
            try:
                async_result = process_paper_content_task.apply_async(args=[paper_id, pdf_mode], queue=settings.CONTENT_QUEUE_NAME)
                child_task_id = str(getattr(async_result, "id", "") or task_id or "") or None
                await paper_service.update_paper(
                    paper_id,
                    processing_status="queued_for_content_processing",
                    content_task_id=child_task_id,
                    processing_error=None,
                )
                queued += 1
            except Exception as exc:
                logger.warning("Failed to queue content pipeline from dashboard: paper_id={}, error={}", paper_id, exc)
                errors.append(f"paper_id={paper_id}: {exc}")

    status = "completed" if not errors else "completed_with_errors"
    result = {
        "status": status,
        "stage": "content_queued",
        "total": len(paper_ids),
        "queued": queued,
        "errors": errors[:20],
        "source": source or "all",
        "pdf_mode": pdf_mode,
    }
    _safe_update_state(task_self, "SUCCESS", result)
    return result


@celery_app.task(bind=True, name="app.tasks.dashboard.process_pdf_backlog")
def process_pdf_backlog_task(
    self,
    limit: int = 100,
    pdf_mode: str | None = "auto",
    source: str | None = None,
) -> dict[str, Any]:
    """Queue documents that still need PDF/full-text/content processing."""
    return run_async(_queue_content_candidates_async(self, limit=limit, pdf_mode=pdf_mode, failed_only=False, source=source))


@celery_app.task(bind=True, name="app.tasks.dashboard.retry_failed_content")
def retry_failed_content_task(
    self,
    limit: int = 100,
    pdf_mode: str | None = "auto",
    source: str | None = None,
) -> dict[str, Any]:
    """Requeue papers whose content pipeline previously failed."""
    return run_async(_queue_content_candidates_async(self, limit=limit, pdf_mode=pdf_mode, failed_only=True, source=source))


async def _rebuild_embeddings_async(task_self: Any, *, limit: int | None = None, source: str | None = None) -> dict[str, Any]:
    task_id = _task_id(task_self)
    source = _normalize_source(source)
    _safe_update_state(task_self, "STARTED", {"stage": "selecting_embedding_candidates", "source": source or "all"})

    async with async_session_maker() as db:
        source_expr = PaperModel.source == source if source else True
        content_expr = or_(_text_present_expr(PaperModel.full_text), _text_present_expr(PaperModel.abstract))
        missing_embedding_expr = or_(PaperModel.embedding.is_(None), ~_json_present_expr(PaperModel.embedding))
        stmt = (
            select(PaperModel.id)
            .where(and_(source_expr, content_expr, missing_embedding_expr))
            .order_by(PaperModel.updated_at.asc().nullsfirst(), PaperModel.created_at.desc(), PaperModel.id.desc())
        )
        paper_ids = [int(row[0]) for row in (await db.execute(stmt)).all()]

    queued = 0
    errors: list[str] = []
    for index, paper_id in enumerate(paper_ids, start=1):
        _safe_update_state(
            task_self,
            "PROGRESS",
            {"stage": "queueing_embeddings", "current": index, "total": len(paper_ids), "queued": queued},
        )
        try:
            build_embedding_task.apply_async(
                args=[{"paper_id": paper_id, "root_task_id": task_id, "text_source": "dashboard_action"}],
                queue=settings.CONTENT_QUEUE_NAME,
            )
            queued += 1
        except Exception as exc:
            logger.warning("Failed to queue embedding rebuild from dashboard: paper_id={}, error={}", paper_id, exc)
            errors.append(f"paper_id={paper_id}: {exc}")

    result = {
        "status": "completed" if not errors else "completed_with_errors",
        "stage": "embeddings_queued",
        "total": len(paper_ids),
        "queued": queued,
        "errors": errors[:20],
        "source": source or "all",
        "unlimited": True,
    }
    _safe_update_state(task_self, "SUCCESS", result)
    return result


@celery_app.task(bind=True, name="app.tasks.dashboard.rebuild_embeddings")
def rebuild_embeddings_task(self, limit: int | None = None, source: str | None = None) -> dict[str, Any]:
    """Queue all missing DB embeddings for papers that already have usable text."""
    return run_async(_rebuild_embeddings_async(self, limit=limit, source=source))


def _count_vector_candidates_stmt(source: str | None = None):
    source_expr = PaperModel.source == source if source else True
    return select(func.count()).select_from(PaperModel).where(and_(source_expr, _json_present_expr(PaperModel.embedding)))


def _vector_candidates_stmt(source: str | None = None, *, last_id: int = 0, batch_size: int = 500):
    source_expr = PaperModel.source == source if source else True
    return (
        select(PaperModel)
        .where(and_(source_expr, PaperModel.id > last_id, _json_present_expr(PaperModel.embedding)))
        .order_by(PaperModel.id.asc())
        .limit(batch_size)
    )


async def _sync_vector_store_async(
    task_self: Any,
    *,
    source: str | None = None,
    clear_first: bool = False,
) -> dict[str, Any]:
    source = _normalize_source(source)
    action_stage = "rebuilding_vector" if clear_first else "syncing_vector"
    _safe_update_state(task_self, "STARTED", {"stage": "counting_vector_candidates", "source": source or "all", "unlimited": True})

    vector_service = get_vector_service()
    if clear_first:
        cleared = await asyncio.to_thread(vector_service.clear)
        if not cleared:
            result = {"status": "failed", "stage": "vector_clear_failed", "indexed": 0, "errors": ["Не удалось очистить векторный индекс"]}
            _safe_update_state(task_self, "FAILURE", result)
            return result

    total = 0
    indexed = 0
    errors = 0
    last_id = 0
    batch_size = 500

    async with async_session_maker() as db:
        total = int((await db.execute(_count_vector_candidates_stmt(source))).scalar_one() or 0)
        while True:
            rows = list((await db.execute(_vector_candidates_stmt(source, last_id=last_id, batch_size=batch_size))).scalars().all())
            if not rows:
                break
            last_id = int(rows[-1].id)
            documents = [_paper_projection(paper) for paper in rows]
            _safe_update_state(
                task_self,
                "PROGRESS",
                {"stage": action_stage, "current": indexed, "total": total, "batch": len(documents), "unlimited": True},
            )
            try:
                added, failed = await asyncio.to_thread(vector_service.add_documents_batch, documents)
                indexed += int(added or 0)
                errors += int(failed or 0)
            except Exception as exc:
                logger.warning("Failed to sync Vector batch from dashboard: last_id={}, error={}", last_id, exc)
                errors += len(documents)

    result = {
        "status": "completed" if not errors else "completed_with_errors",
        "stage": "vector_rebuilt" if clear_first else "vector_synced",
        "total": total,
        "indexed": indexed,
        "errors_count": errors,
        "source": source or "all",
        "cleared": clear_first,
        "unlimited": True,
    }
    _safe_update_state(task_self, "SUCCESS", result)
    return result


@celery_app.task(bind=True, name="app.tasks.dashboard.reindex_vector_store")
def reindex_vector_store_task(self, limit: int | None = None, source: str | None = None) -> dict[str, Any]:
    """Synchronize Vector index from all PostgreSQL embeddings without clearing it."""
    return run_async(_sync_vector_store_async(self, source=source, clear_first=False))


@celery_app.task(bind=True, name="app.tasks.dashboard.rebuild_vector_store_full")
def rebuild_vector_store_full_task(self, source: str | None = None) -> dict[str, Any]:
    """Clear and rebuild the Vector index from all PostgreSQL embeddings."""
    return run_async(_sync_vector_store_async(self, source=source, clear_first=True))


def _paper_part_text(part: PaperContentPart) -> str:
    return str(part.markdown_text or part.raw_text or "").strip()


def _rag_part_document(part: PaperContentPart, paper: PaperModel) -> Document | None:
    text = _paper_part_text(part)
    if not text:
        return None
    title = str(paper.title or f"Paper #{paper.id}").strip()
    metadata = {
        "paper_id": int(paper.id),
        "part_index": int(part.part_index or 0),
        "title": title[:500],
        "source": paper.source or "unknown",
        "doi": paper.doi,
        "journal": paper.journal,
        "page_start": int(part.page_start or 0),
        "page_end": int(part.page_end or 0),
        "content_type": part.content_type or "body",
        "section_title": part.section_title,
        "rag_source": "paper_content_parts",
    }
    return Document(page_content=f"{title}\n\n{text}", metadata={k: v for k, v in metadata.items() if v not in (None, "")})


def _rag_paper_document(paper: PaperModel) -> Document | None:
    chunks = [str(paper.title or "").strip()]
    if paper.abstract and str(paper.abstract).strip():
        chunks.append(str(paper.abstract).strip())
    if paper.full_text and str(paper.full_text).strip():
        chunks.append(str(paper.full_text).strip())
    text = "\n\n".join(chunk for chunk in chunks if chunk)
    if not text:
        return None
    metadata = {
        "paper_id": int(paper.id),
        "part_index": 0,
        "title": str(paper.title or f"Paper #{paper.id}")[:500],
        "source": paper.source or "unknown",
        "doi": paper.doi,
        "journal": paper.journal,
        "rag_source": "paper_full_text" if paper.full_text else "paper_abstract",
    }
    return Document(page_content=text, metadata={k: v for k, v in metadata.items() if v not in (None, "")})


async def _rebuild_rag_index_async(task_self: Any) -> dict[str, Any]:
    _safe_update_state(task_self, "STARTED", {"stage": "clearing_rag_index", "unlimited": True})
    from app.services.rag_vector_store import get_rag_vector_store

    rag_store = get_rag_vector_store()
    cleared = await asyncio.to_thread(rag_store.clear)
    if not cleared:
        result = {"status": "failed", "stage": "rag_clear_failed", "indexed": 0, "errors": ["Не удалось очистить RAG-индекс"]}
        _safe_update_state(task_self, "FAILURE", result)
        return result

    indexed = 0
    errors = 0
    total_parts = 0
    total_papers = 0
    batch_size = 64
    last_part_id = 0

    async with async_session_maker() as db:
        total_parts = int(
            (await db.execute(
                select(func.count())
                .select_from(PaperContentPart)
                .join(PaperModel, PaperModel.id == PaperContentPart.paper_id)
                .where(
                    and_(
                        PaperContentPart.include_in_embedding.is_(True),
                        or_(_text_present_expr(PaperContentPart.markdown_text), _text_present_expr(PaperContentPart.raw_text)),
                    )
                )
            )).scalar_one()
            or 0
        )
        while True:
            rows = (await db.execute(
                select(PaperContentPart, PaperModel)
                .join(PaperModel, PaperModel.id == PaperContentPart.paper_id)
                .where(
                    and_(
                        PaperContentPart.id > last_part_id,
                        PaperContentPart.include_in_embedding.is_(True),
                        or_(_text_present_expr(PaperContentPart.markdown_text), _text_present_expr(PaperContentPart.raw_text)),
                    )
                )
                .order_by(PaperContentPart.id.asc())
                .limit(batch_size)
            )).all()
            if not rows:
                break
            last_part_id = int(rows[-1][0].id)
            documents = [doc for part, paper in rows if (doc := _rag_part_document(part, paper)) is not None]
            _safe_update_state(
                task_self,
                "PROGRESS",
                {"stage": "indexing_rag_content_parts", "current": indexed, "total": total_parts, "batch": len(documents), "unlimited": True},
            )
            added_ids = await asyncio.to_thread(rag_store.add_documents, documents)
            indexed += len(added_ids)
            errors += max(0, len(documents) - len(added_ids))

        content_parts_exists = exists(
            select(PaperContentPart.id).where(
                and_(
                    PaperContentPart.paper_id == PaperModel.id,
                    PaperContentPart.include_in_embedding.is_(True),
                    or_(_text_present_expr(PaperContentPart.markdown_text), _text_present_expr(PaperContentPart.raw_text)),
                )
            )
        )
        fallback_expr = and_(
            ~content_parts_exists,
            or_(_text_present_expr(PaperModel.full_text), _text_present_expr(PaperModel.abstract)),
        )
        total_papers = int((await db.execute(select(func.count()).select_from(PaperModel).where(fallback_expr))).scalar_one() or 0)
        last_paper_id = 0
        processed_fallback = 0
        while True:
            papers = list((await db.execute(
                select(PaperModel)
                .where(and_(PaperModel.id > last_paper_id, fallback_expr))
                .order_by(PaperModel.id.asc())
                .limit(batch_size)
            )).scalars().all())
            if not papers:
                break
            last_paper_id = int(papers[-1].id)
            processed_fallback += len(papers)
            documents = [doc for paper in papers if (doc := _rag_paper_document(paper)) is not None]
            _safe_update_state(
                task_self,
                "PROGRESS",
                {"stage": "indexing_rag_paper_text", "current": processed_fallback, "total": total_papers, "batch": len(documents), "unlimited": True},
            )
            added_ids = await asyncio.to_thread(rag_store.add_documents, documents)
            indexed += len(added_ids)
            errors += max(0, len(documents) - len(added_ids))

    result = {
        "status": "completed" if not errors else "completed_with_errors",
        "stage": "rag_index_rebuilt",
        "content_parts_total": total_parts,
        "fallback_papers_total": total_papers,
        "indexed": indexed,
        "errors_count": errors,
        "unlimited": True,
    }
    _safe_update_state(task_self, "SUCCESS", result)
    return result


@celery_app.task(bind=True, name="app.tasks.dashboard.rebuild_rag_index")
def rebuild_rag_index_task(self) -> dict[str, Any]:
    """Clear and rebuild RAG/Chroma from all content-ready papers."""
    return run_async(_rebuild_rag_index_async(self))
