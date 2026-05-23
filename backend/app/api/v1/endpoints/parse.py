"""API endpoints для парсинга научных статей."""

import asyncio
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.api.v1.endpoints.error_helpers import format_paper_db_error
from app.db.models.paper import Paper as PaperModel
from app.db.session import get_db
from app.services.parse_job_history import add_parse_job
from app.services.system_settings_service import SystemSettingsService
from app.services.paper_service import PaperService
from app.services.paper_content_part_service import PaperContentPartService
from shared.schemas.auth import UserResponse
from shared.schemas.paper import (
    Paper,
    PaperContentPart,
    PaperContentPartRegenerateResponse,
    PaperSearchRequest,
    PaperSearchResponse,
)

router = APIRouter(prefix="/papers", tags=["papers"])


def _get_parse_task_module():
    """Lazy import Celery parser tasks only when a parse endpoint is used."""
    from app.tasks import parse_tasks

    return parse_tasks


def _get_content_task():
    """Lazy import content task only when PDF post-processing is queued."""
    from app.tasks.content_tasks import process_paper_content_task

    return process_paper_content_task


def _get_regenerate_markdown_part_task():
    """Lazy import Qwen part-regeneration task."""
    from app.tasks.qwen_tasks import regenerate_markdown_part_task

    return regenerate_markdown_part_task


def _get_save_pdf_locally():
    """Lazy import PDF helper to avoid PDFParser initialization during API startup."""
    from app.services.paper_content_service import save_pdf_locally

    return save_pdf_locally

_PAPERS_COUNT_TTL_SECONDS = 5.0
_papers_count_cache: dict[str, tuple[int, float]] = {}
_PDF_PROXY_TIMEOUT = httpx.Timeout(connect=4.0, read=45.0, write=10.0, pool=4.0)

def _count_cache_key(source: str | None) -> str:
    return source or "__all__"


def _get_cached_count(source: str | None) -> tuple[int, bool] | None:
    key = _count_cache_key(source)
    cached = _papers_count_cache.get(key)
    if not cached:
        return None
    total, ts = cached
    is_stale = (time.monotonic() - ts) > _PAPERS_COUNT_TTL_SECONDS
    return total, is_stale


def _set_cached_count(source: str | None, total: int) -> None:
    _papers_count_cache[_count_cache_key(source)] = (total, time.monotonic())


def _is_source_enabled(parser_settings: dict, source: str) -> bool:
    enabled_sources = parser_settings.get("enabled_sources") or {}
    return bool(enabled_sources.get(source, True))


def _effective_parse_limit(requested_limit: int | None, parser_settings: dict, source: str) -> int:
    default_limit = int(parser_settings.get("default_limit") or 10)
    max_limit = int(parser_settings.get("max_limit") or 100)
    source_limits = parser_settings.get("source_limits") or {}
    source_limit = int(source_limits.get(source) or max_limit)
    requested = int(requested_limit or default_limit)
    return max(1, min(requested, max_limit, source_limit))


async def _get_parser_settings(db: AsyncSession) -> dict:
    return await SystemSettingsService(db).get_parser_settings()


async def _count_papers_for_source(db: AsyncSession, source: str | None) -> int:
    stmt = select(func.count()).select_from(PaperModel)
    if source and source != "all":
        stmt = stmt.where(PaperModel.source == source)
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


def _record_parse_job(
    *,
    task_id: str,
    query: str,
    source: str,
    initial_count: int,
) -> None:
    started_at = int(time.time() * 1000)
    add_parse_job(
        {
            "jobId": task_id,
            "startedAt": started_at,
            "query": query,
            "source": source,
            "initialCount": initial_count,
            "lastObservedCount": initial_count,
            "lastCountChangeAt": started_at,
            "status": "in_progress",
        }
    )


@router.post("/search", response_model=PaperSearchResponse)
async def search_papers(
    request: PaperSearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Поиск статей в локальной базе данных."""
    paper_service = PaperService(db)
    try:
        papers = await paper_service.search(
            query=request.query,
            limit=request.limit,
            sources=request.sources,
            full_text_only=request.full_text_only,
        )
    except Exception as exc:
        logger.exception("Failed to search papers")
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    return PaperSearchResponse(
        papers=papers,
        total=len(papers),
        query=request.query,
        sources=request.sources or ["CORE"],
    )


@router.get("", response_model=list[Paper])
async def get_papers(
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source: str | None = Query(None, description="Фильтр по источнику"),
    db: AsyncSession = Depends(get_db),
):
    """Получить список всех статей."""
    paper_service = PaperService(db)
    try:
        return await paper_service.get_all(limit=limit, offset=offset, source=source)
    except Exception as exc:
        logger.exception("Failed to list papers")
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))


@router.get("/count")
async def get_papers_count(
    source: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Получить общее количество статей."""
    cached = _get_cached_count(source)
    if cached and not cached[1]:
        return {"total": cached[0], "cached": True, "stale": False}

    paper_service = PaperService(db)

    try:
        if source:
            from sqlalchemy import func, select

            from app.db.models.paper import Paper as PaperModel
            result = await db.execute(select(func.count()).where(PaperModel.source == source))
            count = result.scalar() or 0
        else:
            count = await paper_service.get_total_count()
    except (SQLAlchemyError, TimeoutError, OSError) as exc:
        if cached:
            logger.warning("papers/count timeout, returning stale cache: {}", exc)
            return {"total": cached[0], "cached": True, "stale": True}
        logger.error("papers/count failed without cache: {}", exc)
        raise HTTPException(status_code=503, detail="База данных временно недоступна")

    total = int(count)
    _set_cached_count(source, total)
    return {"total": total, "cached": False, "stale": False}


@router.post("/parse")
async def start_parsing(
    query: str = Query(..., description="Поисковый запрос"),
    limit: int | None = Query(default=None, ge=1, le=5000, description="Макс. количество результатов"),
    source: str = Query(default="CORE", description="Источник"),
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Запустить парсинг статей.

    Доступные источники берутся из parser_alpha реестра.
    """
    normalized_query = query.strip()
    if not normalized_query:
        raise HTTPException(status_code=400, detail="Поле query обязательно и не может быть пустым")

    parse_tasks = _get_parse_task_module()
    available_sources = parse_tasks.AVAILABLE_SOURCES
    if source not in available_sources:
        raise HTTPException(status_code=400, detail=f"Неподдерживаемый источник. Доступны: {', '.join(available_sources)}")

    parser_settings = await _get_parser_settings(db)
    if not parser_settings.get("enabled", True):
        raise HTTPException(status_code=409, detail="Парсинг временно отключён в технических настройках")
    if not _is_source_enabled(parser_settings, source):
        raise HTTPException(status_code=409, detail=f"Источник {source} отключён в технических настройках")
    effective_limit = _effective_parse_limit(limit, parser_settings, source)

    task = parse_tasks.parse_papers_task.apply_async(
        kwargs={"query": normalized_query, "limit": effective_limit, "source": source},
        queue="celery",
    )
    initial_count = await _count_papers_for_source(db, source)
    _record_parse_job(
        task_id=task.id,
        query=normalized_query,
        source=source,
        initial_count=initial_count,
    )
    logger.info(f"Запущен парсинг: source={source}, query={normalized_query}, task_id={task.id}")

    return {
        "message": "Парсинг запущен",
        "task_id": task.id,
        "source": source,
        "query": normalized_query,
        "limit": effective_limit,
    }


@router.post("/parse-all")
async def start_parsing_all(
    limit_per_query: int | None = Query(default=None, ge=1, le=5000),
    source: str = Query(default="all", description="Источник (или all)"),
    query: str = Query(..., description="Пользовательский запрос для всех источников"),
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Запустить парсинг по всем стандартным запросам.

    Источники: `AVAILABLE_SOURCES` и `all`.
    """
    parse_tasks = _get_parse_task_module()
    available_sources = parse_tasks.AVAILABLE_SOURCES
    parser_settings = await _get_parser_settings(db)
    if not parser_settings.get("enabled", True):
        raise HTTPException(status_code=409, detail="Парсинг временно отключён в технических настройках")

    enabled_sources = [s for s in available_sources if _is_source_enabled(parser_settings, s)]
    allowed_with_all = [*available_sources, "all"]
    if source not in allowed_with_all:
        raise HTTPException(status_code=400, detail=f"Неподдерживаемый источник. Доступны: {', '.join(allowed_with_all)}")
    if source != "all" and source not in enabled_sources:
        raise HTTPException(status_code=409, detail=f"Источник {source} отключён в технических настройках")
    if source == "all" and not enabled_sources:
        raise HTTPException(status_code=409, detail="Все источники отключены в технических настройках")

    normalized_query = query.strip()
    if not normalized_query:
        raise HTTPException(status_code=400, detail="Поле query обязательно и не может быть пустым")
    user_queries = [normalized_query]

    if source == "all":
        effective_limit = min(
            _effective_parse_limit(limit_per_query, parser_settings, src) for src in enabled_sources
        )
        task = parse_tasks.parse_all_sources_task.apply_async(
            kwargs={
                "limit_per_query": effective_limit,
                "queries": user_queries,
                "query": normalized_query or None,
                "sources": enabled_sources,
            },
            queue="celery",
        )
        source_list = enabled_sources
    elif source == "arXiv":
        task = parse_tasks.parse_multiple_queries_task.apply_async(
            kwargs={
                "queries": user_queries or parse_tasks.ARXIV_SEARCH_QUERIES,
                "limit_per_query": _effective_parse_limit(limit_per_query, parser_settings, "arXiv"),
                "source": "arXiv",
            },
            queue="celery",
        )
        source_list = ["arXiv"]
    elif source == "CORE":
        task = parse_tasks.parse_multiple_queries_task.apply_async(
            kwargs={
                "queries": user_queries or parse_tasks.DEFAULT_SEARCH_QUERIES,
                "limit_per_query": _effective_parse_limit(limit_per_query, parser_settings, "CORE"),
                "source": "CORE",
            },
            queue="celery",
        )
        source_list = ["CORE"]
    else:
        task = parse_tasks.parse_multiple_queries_task.apply_async(
            kwargs={
                "queries": user_queries or parse_tasks.DEFAULT_SEARCH_QUERIES,
                "limit_per_query": _effective_parse_limit(limit_per_query, parser_settings, source),
                "source": source,
            },
            queue="celery",
        )
        source_list = [source]

    logger.info(
        "Запущен массовый парсинг: sources={}, query='{}', limit_per_query={}, task_id={}",
        source_list,
        normalized_query or "<default_templates>",
        limit_per_query,
        task.id,
    )
    initial_count = await _count_papers_for_source(db, "all" if source == "all" else source_list[0])
    _record_parse_job(
        task_id=task.id,
        query=normalized_query,
        source="all" if source == "all" else source_list[0],
        initial_count=initial_count,
    )

    return {
        "message": "Массовый парсинг запущен",
        "task_id": task.id,
        "sources": source_list,
        "limit_per_query": effective_limit if source == "all" else _effective_parse_limit(limit_per_query, parser_settings, source),
        "query": normalized_query,
    }


@router.get("/id/{paper_id}", response_model=Paper)
async def get_paper(paper_id: int, db: AsyncSession = Depends(get_db)):
    """Получить статью по ID."""
    paper_service = PaperService(db)
    try:
        paper = await paper_service.get_by_id(paper_id)
    except Exception as exc:
        logger.exception("Failed to load paper {}", paper_id)
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    return paper


@router.get("/id/{paper_id}/content-parts", response_model=list[PaperContentPart])
async def get_paper_content_parts(paper_id: int, db: AsyncSession = Depends(get_db)):
    """Получить сохранённые части PDF/raw text + Qwen Markdown по статье."""
    paper = await PaperService(db).get_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return await PaperContentPartService(db).list_parts(paper_id)


@router.post("/id/{paper_id}/content-parts/{part_id}/regenerate", response_model=PaperContentPartRegenerateResponse)
async def regenerate_paper_content_part(
    paper_id: int,
    part_id: int,
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Перегенерировать Markdown только для одной сохранённой части."""
    paper = await PaperService(db).get_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    part_service = PaperContentPartService(db)
    part = await part_service.get_part(paper_id, part_id)
    if not part:
        raise HTTPException(status_code=404, detail="Часть статьи не найдена")
    if not (part.raw_text or "").strip():
        raise HTTPException(status_code=400, detail="У части нет сохранённого сырого PDF-текста")

    task = _get_regenerate_markdown_part_task().apply_async(
        args=[paper_id, part_id],
        queue=settings.QWEN_QUEUE_NAME,
    )
    total_parts = len(await part_service.list_parts(paper_id)) or max(1, part.part_index)
    await PaperService(db).update_paper(
        paper_id,
        processing_status=f"digitizing_file:{part.part_index}/{max(1, total_parts)}",
        content_task_id=task.id,
        processing_error=None,
    )
    return PaperContentPartRegenerateResponse(
        paper_id=paper_id,
        part_id=part_id,
        task_id=task.id,
        status="queued",
        page_start=part.page_start,
        page_end=part.page_end,
    )


@router.post("/id/{paper_id}/markdown-pages/regenerate", response_model=PaperContentPartRegenerateResponse)
async def regenerate_paper_markdown_pages(
    paper_id: int,
    page_start: int = Query(..., ge=1),
    page_end: int = Query(..., ge=1),
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Совместимый endpoint: найти часть по диапазону страниц и перегенерировать её."""
    if page_end < page_start:
        raise HTTPException(status_code=400, detail="page_end должен быть >= page_start")

    paper = await PaperService(db).get_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    part_service = PaperContentPartService(db)
    part = await part_service.get_part_by_pages(paper_id, page_start, page_end)
    if not part:
        raise HTTPException(status_code=404, detail="Часть с указанными страницами не найдена")

    task = _get_regenerate_markdown_part_task().apply_async(
        args=[paper_id, part.id],
        queue=settings.QWEN_QUEUE_NAME,
    )
    total_parts = len(await part_service.list_parts(paper_id)) or max(1, part.part_index)
    await PaperService(db).update_paper(
        paper_id,
        processing_status=f"digitizing_file:{part.part_index}/{max(1, total_parts)}",
        content_task_id=task.id,
        processing_error=None,
    )
    return PaperContentPartRegenerateResponse(
        paper_id=paper_id,
        part_id=part.id,
        task_id=task.id,
        status="queued",
        page_start=part.page_start,
        page_end=part.page_end,
    )


@router.get("/id/{paper_id}/pdf")
async def get_paper_pdf(paper_id: int, db: AsyncSession = Depends(get_db)):
    """Получить PDF статьи: локальный файл или редирект на внешний URL."""
    try:
        paper = await PaperService(db).get_by_id(paper_id)
    except Exception as exc:
        logger.exception("Failed to load paper PDF metadata {}", paper_id)
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    if paper.pdf_local_path:
        path = Path(paper.pdf_local_path)
        if path.exists() and path.is_file():
            return FileResponse(
                path=path,
                media_type="application/pdf",
                filename=f"paper_{paper_id}.pdf",
                content_disposition_type="inline",
            )

    if paper.pdf_url:
        try:
            async with httpx.AsyncClient(timeout=_PDF_PROXY_TIMEOUT, follow_redirects=True) as client:
                remote = await client.get(
                    paper.pdf_url,
                    headers={"Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.1"},
                )
                remote.raise_for_status()
                pdf_bytes = remote.content or b""

            if not pdf_bytes:
                raise HTTPException(status_code=404, detail="PDF пустой")

            content_type = (remote.headers.get("content-type") or "").lower()
            if "pdf" not in content_type and not pdf_bytes.startswith(b"%PDF"):
                raise HTTPException(status_code=404, detail="Удалённый ресурс не является PDF")

            try:
                save_pdf_locally = _get_save_pdf_locally()
                cached_path = await asyncio.to_thread(save_pdf_locally, paper_id, pdf_bytes)
                await PaperService(db).update_paper(paper_id, pdf_local_path=cached_path)
            except Exception as cache_exc:
                logger.warning("PDF cache save failed for paper {}: {}", paper_id, cache_exc)

            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename=\"paper_{paper_id}.pdf\"'},
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Failed to proxy PDF for paper {}: {}", paper_id, exc)
            raise HTTPException(status_code=502, detail="Не удалось получить PDF")

    raise HTTPException(status_code=404, detail="PDF не найден")


@router.post("/id/{paper_id}/reprocess")
async def reprocess_paper_content(
    paper_id: int,
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Поставить статью в очередь на повторную PDF+AI обработку."""
    paper_service = PaperService(db)
    try:
        paper = await paper_service.get_by_id(paper_id)
    except Exception as exc:
        logger.exception("Failed to load paper for reprocess {}", paper_id)
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    process_paper_content_task = _get_content_task()
    task = process_paper_content_task.apply_async(
        args=[paper_id],
        queue=settings.CONTENT_QUEUE_NAME,
    )
    await paper_service.update_paper(
        paper_id,
        processing_status="queued_for_content_processing",
        content_task_id=task.id,
        processing_error=None,
        full_text=None,
        summary_ru=None,
        analysis_ru=None,
        translation_ru=None,
        embedding=None,
    )
    return {"paper_id": paper_id, "task_id": task.id, "status": "queued"}


@router.post("/reprocess-all")
async def reprocess_all_papers(
    limit: int = Query(default=500, ge=1, le=5000),
    source: str | None = Query(default=None, description="Фильтр по источнику"),
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Поставить в очередь постобработку набора существующих статей."""
    paper_service = PaperService(db)
    try:
        papers = await paper_service.get_all(limit=limit, offset=0, source=source)
    except Exception as exc:
        logger.exception("Failed to load papers for reprocess-all")
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    process_paper_content_task = _get_content_task()
    queued = 0
    task_ids: list[str] = []
    for paper in papers:
        task = process_paper_content_task.apply_async(
            args=[paper.id],
            queue=settings.CONTENT_QUEUE_NAME,
        )
        await paper_service.update_paper(
            paper.id,
            processing_status="queued_for_content_processing",
            content_task_id=task.id,
            processing_error=None,
        )
        task_ids.append(task.id)
        queued += 1

    return {"queued": queued, "task_ids": task_ids}


@router.delete("/id/{paper_id}")
async def delete_paper(
    paper_id: int,
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Удалить статью."""
    paper_service = PaperService(db)
    try:
        deleted = await paper_service.delete_paper(paper_id)
    except Exception as exc:
        logger.exception("Failed to delete paper {}", paper_id)
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    if not deleted:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    return {"message": "Статья удалена"}
