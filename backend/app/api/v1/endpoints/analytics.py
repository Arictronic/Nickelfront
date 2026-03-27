"""API endpoints для аналитики и метрик."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from datetime import datetime, timedelta

from app.db.session import get_db
from app.db.models.paper import Paper as PaperModel

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/metrics/summary")
async def get_analytics_summary(
    source: Optional[str] = Query(None, description="Фильтр по источнику"),
    db: AsyncSession = Depends(get_db),
):
    """
    Получить сводную статистику.
    
    Returns:
        Dict с основными метриками
    """
    try:
        # Базовые запросы
        base_query = select(PaperModel)
        if source and source != "all":
            base_query = base_query.where(PaperModel.source == source)
        
        # Общее количество
        count_query = select(func.count()).select_from(PaperModel)
        if source and source != "all":
            count_query = count_query.where(PaperModel.source == source)
        
        total_count_result = await db.execute(count_query)
        total_count = total_count_result.scalar() or 0
        
        # Количество по источникам
        source_query = select(
            PaperModel.source,
            func.count().label("count")
        ).group_by(PaperModel.source)
        
        source_result = await db.execute(source_query)
        sources = {row.source: row.count for row in source_result}
        
        # Количество с эмбеддингами
        embedding_query = select(func.count()).where(
            PaperModel.embedding.isnot(None)
        )
        if source and source != "all":
            embedding_query = embedding_query.where(PaperModel.source == source)
        
        embedding_result = await db.execute(embedding_query)
        with_embedding = embedding_result.scalar() or 0
        
        # Средняя полнота данных
        papers_query = base_query.limit(1000)
        papers_result = await db.execute(papers_query)
        papers = papers_result.scalars().all()
        
        # Вычисляем метрики
        quality_scores = []
        for paper in papers:
            score = 0
            if paper.abstract: score += 20
            if paper.full_text: score += 30
            if paper.keywords: score += 20
            if paper.doi: score += 15
            if paper.authors: score += 15
            quality_scores.append(min(100, score))
        
        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0
        
        return {
            "total_papers": total_count,
            "papers_by_source": sources,
            "papers_with_embedding": with_embedding,
            "embedding_coverage": round((with_embedding / total_count * 100) if total_count > 0 else 0, 2),
            "avg_quality_score": round(avg_quality, 2),
            "generated_at": datetime.now().isoformat(),
        }
        
    except HTTPException:
        raise
    except HTTPException:
        raise
    except HTTPException:
        raise
    except HTTPException:
        raise
    except HTTPException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/trend")
async def get_publications_trend(
    group_by: str = Query(default="month", description="Группировка: day, week, month, year"),
    limit: int = Query(default=12, description="Максимум периодов"),
    source: Optional[str] = Query(None, description="Фильтр по источнику"),
    db: AsyncSession = Depends(get_db),
):
    """
    Получить тренд публикаций.
    
    Returns:
        Список периодов с количеством публикаций
    """
    try:
        bind = db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""

        # В зависимости от group_by используем разные функции
        if dialect_name == "sqlite":
            if group_by == "year":
                date_trunc = func.strftime("%Y-01-01", PaperModel.publication_date)
            elif group_by == "month":
                date_trunc = func.strftime("%Y-%m-01", PaperModel.publication_date)
            elif group_by == "week":
                date_trunc = func.strftime("%Y-%W-1", PaperModel.publication_date)
            elif group_by == "day":
                date_trunc = func.strftime("%Y-%m-%d", PaperModel.publication_date)
            else:
                date_trunc = func.strftime("%Y-%m-01", PaperModel.publication_date)
        else:
            if group_by == "year":
                date_trunc = func.date_trunc("year", PaperModel.publication_date)
            elif group_by == "month":
                date_trunc = func.date_trunc("month", PaperModel.publication_date)
            elif group_by == "week":
                date_trunc = func.date_trunc("week", PaperModel.publication_date)
            elif group_by == "day":
                date_trunc = func.date_trunc("day", PaperModel.publication_date)
            else:
                date_trunc = func.date_trunc("month", PaperModel.publication_date)
        
        query = select(
            date_trunc.label("period"),
            func.count().label("count")
        ).where(
            PaperModel.publication_date.isnot(None)
        )
        
        if source and source != "all":
            query = query.where(PaperModel.source == source)
        
        query = query.group_by("period").order_by("period").limit(limit)
        
        result = await db.execute(query)
        rows = result.all()
        
        trend = [
            {
                "period": row.period.strftime("%Y-%m-%d") if hasattr(row.period, "strftime") else str(row.period),
                "count": row.count,
            }
            for row in rows
        ]
        
        return {
            "trend": trend,
            "group_by": group_by,
            "generated_at": datetime.now().isoformat(),
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/top")
async def get_top_items(
    item_type: str = Query(..., description="Тип: journals, authors, keywords"),
    limit: int = Query(default=10, description="Максимум элементов"),
    source: Optional[str] = Query(None, description="Фильтр по источнику"),
    db: AsyncSession = Depends(get_db),
):
    """
    Получить топ элементов.
    
    Args:
        item_type: journals, authors, keywords
        
    Returns:
        Список элементов с количеством
    """
    try:
        query = select(PaperModel)
        
        if source and source != "all":
            query = query.where(PaperModel.source == source)
        
        query = query.limit(2000)  # Ограничение для обработки
        
        result = await db.execute(query)
        papers = result.scalars().all()
        
        from collections import Counter
        
        if item_type == "journals":
            items = [p.journal for p in papers if p.journal]
            counter = Counter(items)
        elif item_type == "authors":
            items = []
            for p in papers:
                if p.authors and isinstance(p.authors, list):
                    items.extend(p.authors)
            counter = Counter(items)
        elif item_type == "keywords":
            items = []
            for p in papers:
                if p.keywords and isinstance(p.keywords, list):
                    items.extend(p.keywords)
            counter = Counter(items)
        else:
            raise HTTPException(status_code=400, detail=f"Неизвестный тип: {item_type}")
        
        top_items = [
            {"name": name, "count": count}
            for name, count in counter.most_common(limit)
        ]
        
        return {
            "item_type": item_type,
            "items": top_items,
            "generated_at": datetime.now().isoformat(),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/source-distribution")
async def get_source_distribution(
    db: AsyncSession = Depends(get_db),
):
    """
    Получить распределение по источникам.
    
    Returns:
        Dict с распределением
    """
    try:
        query = select(
            PaperModel.source,
            func.count().label("count")
        ).group_by(PaperModel.source)
        
        result = await db.execute(query)
        rows = result.all()
        
        distribution = {
            row.source: {
                "count": row.count,
                "percent": 0  # Будет вычислено ниже
            }
            for row in rows
        }
        
        total = sum(d["count"] for d in distribution.values())
        if total > 0:
            for source in distribution:
                distribution[source]["percent"] = round(
                    distribution[source]["count"] / total * 100, 2
                )
        
        return {
            "distribution": distribution,
            "total": total,
            "generated_at": datetime.now().isoformat(),
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/quality-report")
async def get_quality_report(
    source: Optional[str] = Query(None, description="Фильтр по источнику"),
    db: AsyncSession = Depends(get_db),
):
    """
    Получить отчёт о качестве данных.
    
    Returns:
        Dict с метриками качества
    """
    try:
        query = select(PaperModel)
        
        if source and source != "all":
            query = query.where(PaperModel.source == source)
        
        query = query.limit(2000)
        
        result = await db.execute(query)
        papers = result.scalars().all()
        
        if not papers:
            empty_completeness = {
                "with_abstract": {"count": 0, "percent": 0},
                "with_full_text": {"count": 0, "percent": 0},
                "with_keywords": {"count": 0, "percent": 0},
                "with_doi": {"count": 0, "percent": 0},
                "with_authors": {"count": 0, "percent": 0},
                "with_embedding": {"count": 0, "percent": 0},
            }
            return {
                "total": 0,
                "completeness": empty_completeness,
                "averages": {
                    "avg_abstract_length": 0,
                    "avg_keywords_count": 0,
                },
                "quality_score": {
                    "avg": 0,
                    "min": 0,
                    "max": 0,
                },
                "generated_at": datetime.now().isoformat(),
            }
        
        # Метрики качества
        total = len(papers)
        
        with_abstract = sum(1 for p in papers if p.abstract and len(p.abstract) > 0)
        with_full_text = sum(1 for p in papers if p.full_text and len(p.full_text) > 0)
        with_keywords = sum(1 for p in papers if p.keywords and len(p.keywords) > 0)
        with_doi = sum(1 for p in papers if p.doi and len(p.doi) > 0)
        with_authors = sum(1 for p in papers if p.authors and len(p.authors) > 0)
        with_embedding = sum(1 for p in papers if p.embedding and len(p.embedding) > 0)
        
        # Средние значения
        avg_abstract_len = sum(len(p.abstract) for p in papers if p.abstract) / max(1, with_abstract)
        avg_keywords = sum(len(p.keywords) for p in papers if p.keywords) / max(1, with_keywords)
        
        # Оценка качества
        quality_scores = []
        for paper in papers:
            score = 0
            if paper.abstract: score += 20
            if paper.full_text: score += 30
            if paper.keywords: score += 20
            if paper.doi: score += 15
            if paper.authors: score += 15
            quality_scores.append(min(100, score))
        
        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0
        
        return {
            "total": total,
            "completeness": {
                "with_abstract": {"count": with_abstract, "percent": round(with_abstract / total * 100, 2)},
                "with_full_text": {"count": with_full_text, "percent": round(with_full_text / total * 100, 2)},
                "with_keywords": {"count": with_keywords, "percent": round(with_keywords / total * 100, 2)},
                "with_doi": {"count": with_doi, "percent": round(with_doi / total * 100, 2)},
                "with_authors": {"count": with_authors, "percent": round(with_authors / total * 100, 2)},
                "with_embedding": {"count": with_embedding, "percent": round(with_embedding / total * 100, 2)},
            },
            "averages": {
                "avg_abstract_length": round(avg_abstract_len, 2),
                "avg_keywords_count": round(avg_keywords, 2),
            },
            "quality_score": {
                "avg": round(avg_quality, 2),
                "min": min(quality_scores) if quality_scores else 0,
                "max": max(quality_scores) if quality_scores else 100,
            },
            "generated_at": datetime.now().isoformat(),
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
