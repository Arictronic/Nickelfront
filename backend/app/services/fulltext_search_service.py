"""
Сервис полнотекстового поиска.

Использует возможности PostgreSQL для полнотекстового поиска:
- tsvector - индексированный текст
- tsquery - поисковый запрос
- GIN индексы - быстрый поиск
- Ранжирование по релевантности
"""

from typing import Optional, List
from sqlalchemy import select, func, text, String
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models.paper import Paper as PaperModel


class FullTextSearchService:
    """Сервис полнотекстового поиска."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
        source: Optional[str] = None,
        search_mode: str = "plain",  # plain, phrase, websearch
    ) -> tuple[List[PaperModel], int]:
        """
        Полнотекстовый поиск статей.
        
        Args:
            query: Поисковый запрос
            limit: Максимум результатов
            offset: Смещение
            source: Фильтр по источнику
            search_mode: Режим поиска (plain, phrase, websearch)
            
        Returns:
            (список статей, общее количество)
        """
        # Создаём tsquery из поискового запроса
        if search_mode == "phrase":
            # Поиск точной фразы
            tsquery = func.plainto_tsquery("english", func.quote_literal(query))
        elif search_mode == "websearch":
            # Веб-поиск с поддержкой AND, OR, NOT
            tsquery = func.websearch_to_tsquery("english", query)
        else:
            # Обычный поиск (AND между словами)
            tsquery = func.plainto_tsquery("english", query)
        
        # Базовый запрос с поиском
        search_query = select(
            PaperModel,
            func.ts_rank(PaperModel.search_vector, tsquery).label("rank")
        ).where(
            PaperModel.search_vector.op("@@")(tsquery)
        )
        
        # Фильтр по источнику
        if source and source != "all":
            search_query = search_query.where(PaperModel.source == source)
        
        # Подсчёт общего количества
        count_query = select(func.count()).select_from(
            search_query.subquery()
        )
        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0
        
        # Сортировка по релевантности и пагинация
        search_query = search_query.order_by(
            text("rank DESC"),
            PaperModel.publication_date.desc()
        ).limit(limit).offset(offset)
        
        result = await self.db.execute(search_query)
        rows = result.all()
        papers = [row[0] for row in rows]
        
        return papers, total
    
    async def search_with_highlight(
        self,
        query: str,
        paper: PaperModel,
        max_length: int = 200,
    ) -> dict:
        """
        Поиск с подсветкой совпадений.
        
        Args:
            query: Поисковый запрос
            paper: Статья
            max_length: Максимальная длина сниппета
            
        Returns:
            Dict с подсвеченными полями
        """
        tsquery = func.plainto_tsquery("english", query)
        
        # Создаём сниппеты с подсветкой
        title_snippet = func.ts_headline(
            "english",
            PaperModel.title,
            tsquery,
            "StartSel=<mark>, StopSel=</mark>, MaxWords=10, MinWords=5"
        )
        
        abstract_snippet = func.ts_headline(
            "english",
            PaperModel.abstract,
            tsquery,
            "StartSel=<mark>, StopSel=</mark>, MaxWords=30, MinWords=15"
        )
        
        # Выполняем запрос
        snippet_query = select(
            title_snippet.label("title_highlight"),
            abstract_snippet.label("abstract_highlight")
        ).where(
            PaperModel.id == paper.id
        )
        
        result = await self.db.execute(snippet_query)
        row = result.first()
        
        return {
            "title_highlight": row.title_highlight if row else paper.title,
            "abstract_highlight": row.abstract_highlight if row else paper.abstract,
        }
    
    async def suggest(
        self,
        prefix: str,
        limit: int = 10,
    ) -> List[str]:
        """
        Автодополнение поисковых запросов.
        
        Args:
            prefix: Префикс запроса
            limit: Максимум подсказок
            
        Returns:
            Список подсказок
        """
        # Используем trgm индекс для поиска по префиксу
        suggest_query = select(
            func.distinct(PaperModel.title).label("suggestion")
        ).where(
            PaperModel.title.ilike(f"{prefix}%")
        ).order_by(
            PaperModel.title
        ).limit(limit)
        
        result = await self.db.execute(suggest_query)
        suggestions = [row.suggestion for row in result.all()]
        
        return suggestions
    
    async def search_keywords(
        self,
        keywords: List[str],
        match_all: bool = True,
        limit: int = 20,
    ) -> List[PaperModel]:
        """
        Поиск по ключевым словам.
        
        Args:
            keywords: Список ключевых слов
            match_all: True = все слова должны совпасть (AND)
                      False = любое слово (OR)
            limit: Максимум результатов
            
        Returns:
            Список статей
        """
        # Создаём условия для каждого ключевого слова
        conditions = []
        for keyword in keywords:
            conditions.append(
                PaperModel.keywords.cast(String).ilike(f"%{keyword}%")
            )
        
        # Комбинируем условия
        if match_all:
            # AND - все ключевые слова должны совпасть
            from sqlalchemy import and_
            filter_condition = and_(*conditions)
        else:
            # OR - любое ключевое слово
            from sqlalchemy import or_
            filter_condition = or_(*conditions)
        
        # Выполняем поиск
        search_query = select(PaperModel).where(
            filter_condition
        ).order_by(
            PaperModel.publication_date.desc()
        ).limit(limit)
        
        result = await self.db.execute(search_query)
        papers = result.scalars().all()
        
        return papers
    
    async def get_search_stats(self, query: str) -> dict:
        """
        Получить статистику поискового запроса.
        
        Args:
            query: Поисковый запрос
            
        Returns:
            Dict со статистикой
        """
        tsquery = func.plainto_tsquery("english", query)
        
        # Статистика
        stats_query = select(
            func.count().label("total"),
            func.avg(func.ts_rank(PaperModel.search_vector, tsquery)).label("avg_rank"),
            func.max(func.ts_rank(PaperModel.search_vector, tsquery)).label("max_rank"),
        ).where(
            PaperModel.search_vector.op("@@")(tsquery)
        )
        
        result = await self.db.execute(stats_query)
        row = result.first()
        
        return {
            "total_matches": row.total if row else 0,
            "avg_relevance": float(row.avg_rank) if row and row.avg_rank else 0,
            "max_relevance": float(row.max_rank) if row and row.max_rank else 0,
        }


async def fulltext_search(
    db: AsyncSession,
    query: str,
    limit: int = 20,
    offset: int = 0,
    source: Optional[str] = None,
) -> tuple[List[PaperModel], int]:
    """
    Функция для быстрого доступа к полнотекстовому поиску.
    
    Args:
        db: Сессия БД
        query: Поисковый запрос
        limit: Максимум результатов
        offset: Смещение
        source: Фильтр по источнику
        
    Returns:
        (список статей, общее количество)
    """
    service = FullTextSearchService(db)
    return await service.search(query, limit, offset, source)
