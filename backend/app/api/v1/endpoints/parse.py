"""API endpoints для парсинга научных статей."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from loguru import logger

from app.db.session import get_db
from app.services.paper_service import PaperService
from app.tasks.parse_tasks import (
    parse_papers_task,
    parse_multiple_queries_task,
    parse_all_sources_task,
    DEFAULT_SEARCH_QUERIES,
)
from parser.arxiv import ARXIV_SEARCH_QUERIES
from shared.schemas.paper import Paper, PaperSearchRequest, PaperSearchResponse

router = APIRouter(prefix="/papers", tags=["papers"])


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

    return PaperSearchResponse(
        papers=papers,
        total=len(papers),
        query=request.query,
        sources=request.sources,
    )


@router.get("", response_model=list[Paper])
async def get_papers(
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source: Optional[str] = Query(None, description="Фильтр по источнику (CORE, arXiv)"),
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
    source: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Получить общее количество статей."""
    paper_service = PaperService(db)
    
    if source:
        from sqlalchemy import select, func
        from app.db.models.paper import Paper as PaperModel
        result = await db.execute(select(func.count()).where(PaperModel.source == source))
        count = result.scalar() or 0
    else:
        count = await paper_service.get_total_count()
    
    return {"total": count}


@router.post("/parse")
async def start_parsing(
    query: str = Query(..., description="Поисковый запрос"),
    limit: int = Query(default=50, ge=1, le=100, description="Макс. количество результатов"),
    source: str = Query(default="CORE", description="Источник (CORE или arXiv)"),
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


@router.delete("/id/{paper_id}")
async def delete_paper(paper_id: int, db: AsyncSession = Depends(get_db)):
    """Удалить статью."""
    paper_service = PaperService(db)
    deleted = await paper_service.delete_paper(paper_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    return {"message": "Статья удалена"}
