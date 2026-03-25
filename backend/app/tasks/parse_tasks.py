"""Celery задачи для парсинга научных статей.

Поддерживаемые источники:
- CORE (core.ac.uk)
- arXiv (arxiv.org)
"""

from .celery_app import celery_app
from app.db.session import AsyncSessionLocal
from app.services.paper_service import PaperService
from shared.schemas.paper import PaperCreate
from parser.core import COREClient, COREParser
from parser.arxiv import ArxivClient, ArxivParser, ARXIV_SEARCH_QUERIES
from loguru import logger
import asyncio


# Поисковые запросы по тематике никелевых сплавов
DEFAULT_SEARCH_QUERIES = [
    "nickel-based alloys",
    "superalloys",
    "heat resistant alloys",
    "nickel superalloys corrosion",
    "nickel alloys high temperature",
]


@celery_app.task(bind=True)
def parse_papers_task(
    self,
    query: str,
    limit: int = 50,
    source: str = "CORE",
):
    """
    Фоновая задача для парсинга статей.

    Args:
        query: Поисковый запрос
        limit: Макс. количество результатов
        source: Источник (CORE или arXiv)
    """
    try:
        return asyncio.run(_parse_async(query, limit, source))
    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")
        raise


async def _parse_async(
    query: str,
    limit: int = 50,
    source: str = "CORE",
) -> dict:
    """Асинхронная функция для парсинга статей."""
    
    # Выбираем клиент и парсер в зависимости от источника
    if source == "arXiv":
        client = ArxivClient(rate_limit=True)
        parser = ArxivParser()
    else:
        client = COREClient()
        parser = COREParser()

    stats = {
        "query": query,
        "source": source,
        "found_count": 0,
        "parsed_count": 0,
        "saved_count": 0,
        "errors": [],
    }

    try:
        # Поиск статей
        if source == "arXiv":
            search_results = await client.search(query=query, limit=limit)
        else:
            search_results = await client.search(query=query, limit=limit, full_text_only=False)
        
        stats["found_count"] = len(search_results)

        # Парсинг результатов
        papers = await parser.parse_search_results(search_results)
        stats["parsed_count"] = len(papers)

        # Сохранение в БД
        async with AsyncSessionLocal() as db:
            paper_service = PaperService(db)

            for paper in papers:
                try:
                    paper_create = PaperCreate(
                        title=paper.title,
                        authors=paper.authors,
                        publication_date=paper.publication_date,
                        journal=paper.journal,
                        doi=paper.doi,
                        abstract=paper.abstract,
                        full_text=paper.full_text,
                        keywords=paper.keywords,
                        source=paper.source,
                        source_id=paper.source_id,
                        url=paper.url,
                    )
                    await paper_service.create_paper(paper_create)
                    stats["saved_count"] += 1
                except Exception as e:
                    error_msg = f"Error saving paper '{paper.title[:50]}...': {e}"
                    logger.error(error_msg)
                    stats["errors"].append(error_msg)

            await db.commit()

        logger.info(
            f"Парсинг '{query}' ({source}): найдено={stats['found_count']}, "
            f"распарсено={stats['parsed_count']}, сохранено={stats['saved_count']}"
        )

        return stats

    finally:
        await client.close()


@celery_app.task(bind=True)
def parse_multiple_queries_task(
    self,
    queries: list[str] = None,
    limit_per_query: int = 50,
    source: str = "CORE",
):
    """
    Парсинг по нескольким поисковым запросам.

    Args:
        queries: Список запросов (по умолчанию DEFAULT_SEARCH_QUERIES)
        limit_per_query: Лимит на каждый запрос
        source: Источник (CORE или arXiv)
    """
    if queries is None:
        queries = DEFAULT_SEARCH_QUERIES if source == "CORE" else ARXIV_SEARCH_QUERIES

    results = []
    for query in queries:
        try:
            result = parse_papers_task(
                query=query,
                limit=limit_per_query,
                source=source,
            )
            results.append(result)
        except Exception as e:
            logger.error(f"Ошибка при парсинге запроса '{query}': {e}")
            results.append({"query": query, "error": str(e)})

    return {
        "total_queries": len(queries),
        "source": source,
        "results": results,
        "total_saved": sum(r.get("saved_count", 0) for r in results if "error" not in r),
    }


@celery_app.task(bind=True)
def parse_all_sources_task(
    self,
    limit_per_query: int = 50,
):
    """
    Парсинг по всем источникам (CORE + arXiv).

    Args:
        limit_per_query: Лимит на каждый запрос
    """
    logger.info("Запуск парсинга по всем источникам...")

    # Парсинг CORE
    core_result = parse_multiple_queries_task(
        queries=DEFAULT_SEARCH_QUERIES,
        limit_per_query=limit_per_query,
        source="CORE",
    )

    # Парсинг arXiv
    arxiv_result = parse_multiple_queries_task(
        queries=ARXIV_SEARCH_QUERIES,
        limit_per_query=limit_per_query,
        source="arXiv",
    )

    return {
        "core": core_result,
        "arxiv": arxiv_result,
        "total_saved": core_result["total_saved"] + arxiv_result["total_saved"],
    }
