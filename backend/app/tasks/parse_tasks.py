"""Celery задачи для парсинга научных статей.

Поддерживаемые источники:
- CORE (core.ac.uk)
- arXiv (arxiv.org)
"""

import asyncio

from loguru import logger

from app.db.session import async_session_maker
from app.services.celery_cancel import clear_cancel_flag, is_cancelled
from app.services.paper_content_service import resolve_pdf_url
from app.services.paper_service import PaperService
from app.tasks.content_tasks import process_paper_content_task
from parsers_pkg.arxiv import ARXIV_SEARCH_QUERIES
from parsers_pkg.arxiv.client import ArxivClient
from parsers_pkg.arxiv.parser import ArxivParser
from parsers_pkg.core.client import COREClient
from parsers_pkg.core.parser import COREParser
from shared.schemas.paper import PaperCreate

from .celery_app import celery_app

# Поисковые запросы по тематике никелевых сплавов
DEFAULT_SEARCH_QUERIES = [
    "nickel-based alloys",
    "superalloys",
    "heat resistant alloys",
    "nickel superalloys corrosion",
    "nickel alloys high temperature",
]


def _get_task_id(task) -> str | None:
    return getattr(getattr(task, "request", None), "id", None)


def _is_cancelled(task) -> bool:
    task_id = _get_task_id(task)
    return bool(task_id and is_cancelled(task_id))


def _mark_revoked(task, query: str, source: str, current: int = 0, total: int = 0) -> dict:
    task.update_state(
        state="REVOKED",
        meta={
            "query": query,
            "source": source,
            "current": current,
            "total": total,
            "status": "Отменено",
        },
    )
    return {
        "status": "revoked",
        "query": query,
        "source": source,
        "current": current,
        "total": total,
        "saved_count": 0,
        "embedded_count": 0,
        "content_queued_count": 0,
        "errors": ["cancelled"],
    }


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
        if _is_cancelled(self):
            return _mark_revoked(self, query=query, source=source, current=0, total=limit)

        # Обновляем статус STARTED
        self.update_state(
            state="STARTED",
            meta={
                "query": query,
                "source": source,
                "limit": limit,
                "current": 0,
                "total": limit,
                "status": "Инициализация..."
            }
        )
        return asyncio.run(_parse_async(self, query, limit, source))
    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")
        self.update_state(
            state="FAILURE",
            meta={
                "query": query,
                "source": source,
                "error": str(e),
                "current": 0,
                "total": limit,
            }
        )
        raise
    finally:
        task_id = _get_task_id(self)
        if task_id:
            clear_cancel_flag(task_id)


async def _parse_async(
    self,
    query: str,
    limit: int = 50,
    source: str = "CORE",
) -> dict:
    """Асинхронная функция для парсинга статей."""

    # Выбираем клиент и парсер в зависимости от источника
    if _is_cancelled(self):
        return _mark_revoked(self, query=query, source=source, current=0, total=limit)

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
        "embedded_count": 0,
        "content_queued_count": 0,
        "errors": [],
    }

    try:
        # Поиск статей
        self.update_state(
            state="STARTED",
            meta={
                "query": query,
                "source": source,
                "current": 0,
                "total": limit,
                "status": f"Поиск статей по запросу '{query}'..."
            }
        )

        if _is_cancelled(self):
            return _mark_revoked(self, query=query, source=source, current=0, total=limit)

        if source == "arXiv":
            search_results = await client.search(query=query, limit=limit)
        else:
            search_results = await client.search(query=query, limit=limit, full_text_only=False)

        stats["found_count"] = len(search_results)

        # Парсинг результатов
        self.update_state(
            state="STARTED",
            meta={
                "query": query,
                "source": source,
                "current": len(search_results),
                "total": limit,
                "status": f"Парсинг результатов ({len(search_results)} найдено)..."
            }
        )

        if _is_cancelled(self):
            return _mark_revoked(self, query=query, source=source, current=0, total=limit)

        papers = await parser.parse_search_results(search_results)
        stats["parsed_count"] = len(papers)

        # Сохранение в БД - создаём сессию внутри asyncio.run()
        async with async_session_maker() as db:
            paper_service = PaperService(db)

            for idx, paper in enumerate(papers):
                # Проверяем флаг отмены на каждой итерации
                if _is_cancelled(self):
                    return _mark_revoked(self, query=query, source=source, current=idx, total=len(papers))
                try:
                    # Обновляем прогресс и проверяем отмену каждые 5 статей
                    if idx % 5 == 0:
                        # Дополнительная проверка отмены перед обновлением статуса
                        if _is_cancelled(self):
                            return _mark_revoked(self, query=query, source=source, current=idx, total=len(papers))

                        self.update_state(
                            state="STARTED",
                            meta={
                                "query": query,
                                "source": source,
                                "current": idx,
                                "total": len(papers),
                                "saved_count": stats["saved_count"],
                                "content_queued_count": stats["content_queued_count"],
                                "status": f"Сохранение статей ({idx}/{len(papers)})..."
                            }
                        )

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
                    saved_paper = await paper_service.create_paper(paper_create)
                    stats["saved_count"] += 1

                    # Ставим отдельную задачу воркеру на PDF + AI + индексацию
                    if saved_paper.id:
                        try:
                            pdf_url = resolve_pdf_url(
                                source=saved_paper.source,
                                source_id=saved_paper.source_id,
                                url=saved_paper.url,
                            )
                            content_task = process_paper_content_task.delay(saved_paper.id)
                            await paper_service.update_paper(
                                saved_paper.id,
                                processing_status="queued_for_content_processing",
                                content_task_id=content_task.id,
                                pdf_url=pdf_url,
                                processing_error=None,
                            )
                            stats["content_queued_count"] += 1
                        except Exception as e:
                            logger.warning(
                                f"Не удалось поставить content-task для статьи {saved_paper.id}: {e}"
                            )

                except Exception as e:
                    error_msg = f"Error saving paper '{paper.title[:50]}...': {e}"
                    logger.error(error_msg)
                    stats["errors"].append(error_msg)

            await db.commit()

        # Финальный статус
        self.update_state(
            state="SUCCESS",
            meta={
                "query": query,
                "source": source,
                "current": len(papers),
                "total": len(papers),
                "saved_count": stats["saved_count"],
                "embedded_count": stats["embedded_count"],
                "content_queued_count": stats["content_queued_count"],
                "status": "Завершено"
            }
        )

        logger.info(
            f"Парсинг '{query}' ({source}): найдено={stats['found_count']}, "
            f"распарсено={stats['parsed_count']}, сохранено={stats['saved_count']}, "
            f"в очереди на AI/PDF={stats['content_queued_count']}"
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

    total_queries = len(queries)
    results = []
    total_saved = 0

    for idx, query in enumerate(queries):
        if _is_cancelled(self):
            return _mark_revoked(self, query=str(query), source=source, current=idx, total=total_queries)
        try:
            # Обновляем прогресс по текущему запросу
            self.update_state(
                state="STARTED",
                meta={
                    "type": "multiple_queries",
                    "source": source,
                    "current_query": idx + 1,
                    "total_queries": total_queries,
                    "current_query_text": query,
                    "total_saved": total_saved,
                    "status": f"Обработка запроса {idx + 1}/{total_queries}: '{query}'"
                }
            )

            result = parse_papers_task(
                query=query,
                limit=limit_per_query,
                source=source,
            )
            results.append(result)
            total_saved += result.get("saved_count", 0)

        except Exception as e:
            logger.error(f"Ошибка при парсинге запроса '{query}': {e}")
            results.append({"query": query, "error": str(e)})

    # Финальный статус
    self.update_state(
        state="SUCCESS",
        meta={
            "type": "multiple_queries",
            "source": source,
            "current_query": total_queries,
            "total_queries": total_queries,
            "total_saved": total_saved,
            "status": "Все запросы обработаны"
        }
    )

    return {
        "total_queries": total_queries,
        "source": source,
        "results": results,
        "total_saved": total_saved,
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
    if _is_cancelled(self):
        return _mark_revoked(self, query='all_sources', source='CORE', current=0, total=2)

    logger.info("Запуск парсинга по всем источникам...")

    total_sources = 2  # CORE + arXiv

    # Парсинг CORE
    self.update_state(
        state="STARTED",
        meta={
            "type": "all_sources",
            "current_source": 1,
            "total_sources": total_sources,
            "source": "CORE",
            "status": "Парсинг источника CORE..."
        }
    )

    core_result = parse_multiple_queries_task(
        queries=DEFAULT_SEARCH_QUERIES,
        limit_per_query=limit_per_query,
        source="CORE",
    )

    # Парсинг arXiv
    self.update_state(
        state="STARTED",
        meta={
            "type": "all_sources",
            "current_source": 2,
            "total_sources": total_sources,
            "source": "arXiv",
            "status": "Парсинг источника arXiv..."
        }
    )

    if _is_cancelled(self):
        return _mark_revoked(self, query='all_sources', source='arXiv', current=1, total=2)

    arxiv_result = parse_multiple_queries_task(
        queries=ARXIV_SEARCH_QUERIES,
        limit_per_query=limit_per_query,
        source="arXiv",
    )

    # Финальный статус
    self.update_state(
        state="SUCCESS",
        meta={
            "type": "all_sources",
            "current_source": total_sources,
            "total_sources": total_sources,
            "total_saved": core_result["total_saved"] + arxiv_result["total_saved"],
            "status": "Все источники обработаны"
        }
    )

    return {
        "core": core_result,
        "arxiv": arxiv_result,
        "total_saved": core_result["total_saved"] + arxiv_result["total_saved"],
    }
