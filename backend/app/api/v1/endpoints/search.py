"""API endpoints для полнотекстового поиска."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from app.db.session import get_db
from app.services.paper_service import PaperService
from app.services.fulltext_search_service import FullTextSearchService
from shared.schemas.paper import Paper, PaperSearchRequest, PaperSearchResponse

router = APIRouter(prefix="/search", tags=["search"])


@router.post("/fulltext", response_model=PaperSearchResponse)
async def fulltext_search(
    query: str = Query(..., description="Поисковый запрос"),
    limit: int = Query(default=20, ge=1, le=100, description="Максимум результатов"),
    offset: int = Query(default=0, ge=0, description="Смещение"),
    source: Optional[str] = Query(None, description="Фильтр по источнику"),
    search_mode: str = Query(default="websearch", description="Режим поиска: plain, phrase, websearch"),
    db: AsyncSession = Depends(get_db),
):
    """
    Полнотекстовый поиск статей с использованием PostgreSQL FTS.
    
    Поддерживаемые режимы:
    - **plain**: Обычный поиск (слова соединяются AND)
    - **phrase**: Поиск точной фразы
    - **websearch**: Расширенный поиск с поддержкой AND, OR, NOT
    
    Примеры сложных запросов (websearch):
    - `nickel AND superalloy` - оба слова должны быть
    - `nickel OR cobalt` - любое из слов
    - `nickel NOT iron` - nickel без iron
    - `"high temperature"` - точная фраза в кавычках
    """
    try:
        service = FullTextSearchService(db)
        papers, total = await service.search(
            query=query,
            limit=limit,
            offset=offset,
            source=source,
            search_mode=search_mode,
        )
        
        return PaperSearchResponse(
            papers=papers,
            total=total,
            query=query,
            sources=[source] if source else ["all"],
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка поиска: {str(e)}")


@router.get("/suggest")
async def search_suggestions(
    prefix: str = Query(..., min_length=2, description="Префикс для автодополнения"),
    limit: int = Query(default=10, ge=1, le=20, description="Максимум подсказок"),
    db: AsyncSession = Depends(get_db),
):
    """
    Автодополнение поисковых запросов.
    
    Возвращает список заголовков, начинающихся с указанного префикса.
    """
    try:
        service = FullTextSearchService(db)
        suggestions = await service.suggest(prefix=prefix, limit=limit)
        
        return {
            "suggestions": suggestions,
            "prefix": prefix,
            "count": len(suggestions),
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения подсказок: {str(e)}")


@router.post("/keywords")
async def search_by_keywords(
    keywords: List[str] = Query(..., description="Ключевые слова для поиска"),
    match_all: bool = Query(default=True, description="True=AND (все слова), False=OR (любое)"),
    limit: int = Query(default=20, ge=1, le=100, description="Максимум результатов"),
    db: AsyncSession = Depends(get_db),
):
    """
    Поиск статей по ключевым словам.
    
    - **match_all=True**: Все ключевые слова должны присутствовать (AND)
    - **match_all=False**: Достаточно любого ключевого слова (OR)
    """
    try:
        service = FullTextSearchService(db)
        papers = await service.search_keywords(
            keywords=keywords,
            match_all=match_all,
            limit=limit,
        )
        
        return {
            "papers": papers,
            "total": len(papers),
            "keywords": keywords,
            "match_all": match_all,
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка поиска: {str(e)}")


@router.get("/stats")
async def get_search_stats(
    query: str = Query(..., description="Поисковый запрос"),
    db: AsyncSession = Depends(get_db),
):
    """
    Получить статистику поискового запроса.
    
    Возвращает:
    - Общее количество совпадений
    - Среднюю релевантность
    - Максимальную релевантность
    """
    try:
        service = FullTextSearchService(db)
        stats = await service.get_search_stats(query=query)
        
        return stats
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения статистики: {str(e)}")


@router.get("/highlight/{paper_id}")
async def get_search_highlight(
    paper_id: int,
    query: str = Query(..., description="Поисковый запрос для подсветки"),
    db: AsyncSession = Depends(get_db),
):
    """
    Получить текст с подсветкой совпадений.
    
    Возвращает заголовок и аннотацию с тегами <mark> вокруг совпадений.
    """
    try:
        # Получаем статью
        paper_service = PaperService(db)
        paper = await paper_service.get_by_id(paper_id)
        
        if not paper:
            raise HTTPException(status_code=404, detail="Статья не найдена")
        
        # Получаем подсветку
        service = FullTextSearchService(db)
        highlight = await service.search_with_highlight(
            query=query,
            paper=paper,
        )
        
        return {
            "paper_id": paper_id,
            "title": highlight.get("title_highlight", paper.title),
            "abstract": highlight.get("abstract_highlight", paper.abstract),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")
