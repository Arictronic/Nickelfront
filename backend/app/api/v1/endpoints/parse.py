"""API endpoints для парсинга научных статей."""

import asyncio
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from loguru import logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.services.paper_content_service import save_pdf_locally
from app.services.paper_service import PaperService
from app.tasks.content_tasks import process_paper_content_task
from app.tasks.parse_tasks import (
    DEFAULT_SEARCH_QUERIES,
    parse_all_sources_task,
    parse_multiple_queries_task,
    parse_papers_task,
)
from parsers_pkg.arxiv import ARXIV_SEARCH_QUERIES
from shared.schemas.auth import UserResponse
from shared.schemas.paper import Paper, PaperSearchRequest, PaperSearchResponse

router = APIRouter(prefix="/papers", tags=["papers"])

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


@router.post("/search", response_model=PaperSearchResponse)
async def search_papers(
    request: PaperSearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Поиск статей в локальной базе данных."""
    paper_service = PaperService(db)
    papers = await paper_service.search(query=request.query, limit=request.limit)

    if request.sources:
        papers = [p for p in papers if p.source in request.sources]
    if request.full_text_only:
        papers = [p for p in papers if p.full_text and p.full_text.strip()]

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
    source: str | None = Query(None, description="Фильтр по источнику (CORE, arXiv)"),
    db: AsyncSession = Depends(get_db),
):
    """Получить список всех статей."""
    paper_service = PaperService(db)
    papers = await paper_service.get_all(limit=limit, offset=offset)

    if source:
        papers = [p for p in papers if p.source == source]

    return papers


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
    limit: int = Query(default=50, ge=1, le=100, description="Макс. количество результатов"),
    source: str = Query(default="CORE", description="Источник (CORE или arXiv)"),
    _current_user: UserResponse = Depends(get_current_user),
):
    """
    Запустить парсинг статей.

    Источники:
    - **CORE** (core.ac.uk)
    - **arXiv** (arxiv.org)
    """
    if source not in ["CORE", "arXiv"]:
        raise HTTPException(status_code=400, detail="Неподдерживаемый источник. Доступны: CORE, arXiv")

    task = parse_papers_task.delay(query=query, limit=limit, source=source)
    logger.info(f"Запущен парсинг: source={source}, query={query}, task_id={task.id}")

    return {
        "message": "Парсинг запущен",
        "task_id": task.id,
        "source": source,
        "query": query,
        "limit": limit,
    }


@router.post("/parse-all")
async def start_parsing_all(
    limit_per_query: int = Query(default=50, ge=1, le=100),
    source: str = Query(default="all", description="Источник (CORE, arXiv, all)"),
    _current_user: UserResponse = Depends(get_current_user),
):
    """
    Запустить парсинг по всем стандартным запросам.

    Источники:
    - **CORE**: nickel-based alloys, superalloys, etc.
    - **arXiv**: nickel-based alloys, superalloys, inconel, etc.
    - **all**: оба источника
    """
    if source not in ["CORE", "arXiv", "all"]:
        raise HTTPException(status_code=400, detail="Неподдерживаемый источник. Доступны: CORE, arXiv, all")

    if source == "all":
        task = parse_all_sources_task.delay(limit_per_query=limit_per_query)
        source_list = ["CORE", "arXiv"]
    elif source == "arXiv":
        task = parse_multiple_queries_task.delay(
            queries=ARXIV_SEARCH_QUERIES,
            limit_per_query=limit_per_query,
            source="arXiv",
        )
        source_list = ["arXiv"]
    else:
        task = parse_multiple_queries_task.delay(
            queries=DEFAULT_SEARCH_QUERIES,
            limit_per_query=limit_per_query,
            source="CORE",
        )
        source_list = ["CORE"]

    logger.info(f"Запущен массовый парсинг: sources={source_list}, task_id={task.id}")

    return {
        "message": "Массовый парсинг запущен",
        "task_id": task.id,
        "sources": source_list,
        "limit_per_query": limit_per_query,
    }


@router.get("/id/{paper_id}", response_model=Paper)
async def get_paper(paper_id: int, db: AsyncSession = Depends(get_db)):
    """Получить статью по ID."""
    paper_service = PaperService(db)
    paper = await paper_service.get_by_id(paper_id)

    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    return paper


@router.get("/id/{paper_id}/pdf")
async def get_paper_pdf(paper_id: int, db: AsyncSession = Depends(get_db)):
    """Получить PDF статьи: локальный файл или редирект на внешний URL."""
    paper = await PaperService(db).get_by_id(paper_id)
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
                raise HTTPException(status_code=404, detail="PDF РїСѓСЃС‚РѕР№")

            content_type = (remote.headers.get("content-type") or "").lower()
            if "pdf" not in content_type and not pdf_bytes.startswith(b"%PDF"):
                raise HTTPException(status_code=404, detail="РЈРґР°Р»РµРЅРЅС‹Р№ РёСЃС‚РѕС‡РЅРёРє РІРµСЂРЅСѓР» РЅРµ-PDF")

            try:
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
            raise HTTPException(status_code=502, detail="РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РіСЂСѓР·РёС‚СЊ PDF")

    raise HTTPException(status_code=404, detail="PDF не найден")


@router.post("/id/{paper_id}/reprocess")
async def reprocess_paper_content(
    paper_id: int,
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Поставить статью в очередь на повторную PDF+AI обработку."""
    paper_service = PaperService(db)
    paper = await paper_service.get_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    task = process_paper_content_task.delay(paper_id)
    await paper_service.update_paper(
        paper_id,
        processing_status="queued_for_content_processing",
        content_task_id=task.id,
        processing_error=None,
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
    papers = await paper_service.get_all(limit=limit, offset=0)
    if source:
        papers = [p for p in papers if p.source == source]

    queued = 0
    task_ids: list[str] = []
    for paper in papers:
        task = process_paper_content_task.delay(paper.id)
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
async def delete_paper(paper_id: int, db: AsyncSession = Depends(get_db)):
    """Удалить статью."""
    paper_service = PaperService(db)
    deleted = await paper_service.delete_paper(paper_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    return {"message": "Статья удалена"}
