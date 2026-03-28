"""API endpoints для векторного поиска."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.embedding_service import get_embedding_service
from app.services.paper_service import PaperService
from app.services.vector_service import get_vector_service
from shared.schemas.paper import (
    VectorClearRequest,
    VectorClearResponse,
    VectorRebuildResponse,
    VectorSearchRequest,
    VectorSearchResponse,
    VectorSearchResultItem,
    VectorStats,
    VectorStatsResponse,
)

router = APIRouter(prefix="/vector", tags=["vector-search"])


@router.post("/search", response_model=VectorSearchResponse)
async def vector_search(
    request: VectorSearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Векторный семантический поиск статей.

    Использует эмбеддинги для поиска статей по смыслу, а не по ключевым словам.

    **search_type:**
    - **vector** - чистый векторный поиск по ChromaDB
    - **semantic** - векторный поиск с фильтрацией по метаданным
    - **hybrid** - комбинация векторного и текстового поиска

    **Фильтры:**
    - source - фильтр по источнику (CORE, arXiv)
    - date_from/date_to - фильтр по дате публикации
    """
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=400, detail="Пустой поисковый запрос")

    embedding_service = get_embedding_service()
    vector_service = get_vector_service()

    # Проверяем доступность сервисов
    embedding_available = await asyncio.to_thread(lambda: embedding_service.model is not None)
    if not embedding_available:
        logger.warning("Модель эмбеддингов недоступна, используем текстовый поиск")
        # Fallback на текстовый поиск
        paper_service = PaperService(db)
        papers = await paper_service.search(query=request.query, limit=request.limit)

        return VectorSearchResponse(
            results=[
                VectorSearchResultItem(paper=p, similarity=0.0)
                for p in papers
            ],
            total=len(papers),
            query=request.query,
            search_type="text_fallback",
        )

    # Генерируем эмбеддинг для запроса
    query_embedding = await asyncio.to_thread(embedding_service.get_embedding, request.query)

    if not query_embedding:
        raise HTTPException(status_code=500, detail="Ошибка генерации эмбеддинга")

    # Выполняем векторный поиск
    if request.search_type == "hybrid":
        # Гибридный поиск: векторный + текстовый
        vector_results = await asyncio.to_thread(
            vector_service.search,
            query_embedding=query_embedding,
            limit=request.limit,
            source=request.source,
            date_from=request.date_from,
            date_to=request.date_to,
        )

        # Получаем текстовые результаты для сравнения
        paper_service = PaperService(db)
        text_papers = await paper_service.search(query=request.query, limit=request.limit)

        # Объединяем результаты (приоритет векторным)
        seen_ids = set()
        results = []

        for vr in vector_results:
            if vr.paper_id not in seen_ids:
                seen_ids.add(vr.paper_id)
                # Получаем полную информацию о статье
                paper = await paper_service.get_by_id(vr.paper_id)
                if paper:
                    results.append(VectorSearchResultItem(
                        paper=paper,
                        similarity=vr.similarity,
                    ))

        # Добавляем текстовые результаты, которых нет в векторных
        for p in text_papers:
            if p.id not in seen_ids and len(results) < request.limit:
                seen_ids.add(p.id)
                results.append(VectorSearchResultItem(
                    paper=p,
                    similarity=0.5,  # Приоритет ниже векторных
                ))

        return VectorSearchResponse(
            results=results[:request.limit],
            total=len(results),
            query=request.query,
            search_type="hybrid",
        )

    else:
        # Чистый векторный поиск (vector или semantic)
        vector_results = await asyncio.to_thread(
            vector_service.search,
            query_embedding=query_embedding,
            limit=request.limit,
            source=request.source if request.search_type == "semantic" else None,
            date_from=request.date_from if request.search_type == "semantic" else None,
            date_to=request.date_to if request.search_type == "semantic" else None,
        )

        # Получаем полные данные о статьях
        results = []
        for vr in vector_results:
            paper = await PaperService(db).get_by_id(vr.paper_id)
            if paper:
                results.append(VectorSearchResultItem(
                    paper=paper,
                    similarity=vr.similarity,
                ))

        return VectorSearchResponse(
            results=results,
            total=len(results),
            query=request.query,
            search_type=request.search_type,
        )


@router.get("/stats", response_model=VectorStatsResponse)
async def vector_search_stats():
    """
    Получить статистику векторного поиска.

    Возвращает информацию о количестве документов в векторной базе,
    модели эмбеддингов и статусе сервисов.
    """
    vector_service = get_vector_service()
    vector_stats = await asyncio.to_thread(vector_service.get_stats)

    embedding_service = get_embedding_service()
    embedding_available = await asyncio.to_thread(lambda: embedding_service.model is not None)

    return VectorStatsResponse(
        vector_store=VectorStats(
            count=vector_stats.get("count", 0),
            available=vector_stats.get("available", False),
            collection=vector_stats.get("collection", "papers"),
            persist_directory=vector_stats.get("persist_directory", "./chroma_db"),
        ),
        embedding_model=embedding_service.MODEL_NAME if embedding_available else None,
        embedding_dim=embedding_service.EMBEDDING_DIM if embedding_available else None,
        embedding_available=embedding_available,
    )


@router.post("/rebuild", response_model=VectorRebuildResponse)
async def rebuild_vector_index(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=10000, ge=1, le=100000, description="Макс. количество статей"),
    batch_size: int = Query(default=32, ge=1, le=128, description="Размер пакета"),
):
    """
    Перестроить векторный индекс из текущих статей в БД.

    Генерирует эмбеддинги для всех статей и обновляет ChromaDB.

    **Параметры:**
    - **limit** - максимальное количество статей для обработки
    - **batch_size** - размер пакета для пакетного добавления
    """
    embedding_service = get_embedding_service()
    vector_service = get_vector_service()

    embedding_available = await asyncio.to_thread(lambda: embedding_service.model is not None)
    if not embedding_available:
        raise HTTPException(status_code=500, detail="Модель эмбеддингов недоступна")

    logger.info(f"Начало перестройки векторного индекса (limit={limit}, batch_size={batch_size})")

    # Получаем все статьи из БД
    paper_service = PaperService(db)
    all_papers = await paper_service.get_all(limit=limit, offset=0)

    if not all_papers:
        return VectorRebuildResponse(
            message="Нет статей для индексации",
            indexed=0,
            total=0,
        )

    # Генерируем тексты и эмбеддинги
    papers_with_embeddings = []
    for paper in all_papers:
        # Пропускаем если уже есть эмбеддинг
        if paper.embedding:
            papers_with_embeddings.append({
                "id": paper.id,
                "title": paper.title,
                "source": paper.source,
                "doi": paper.doi,
                "publication_date": paper.publication_date.isoformat() if paper.publication_date else None,
                "journal": paper.journal,
                "embedding": paper.embedding,
            })
            continue

        # Генерируем новый эмбеддинг
        text = await asyncio.to_thread(
            embedding_service.get_paper_embedding_text,
            title=paper.title,
            abstract=paper.abstract or "",
            keywords=paper.keywords or [],
        )

        if text:
            embedding = await asyncio.to_thread(embedding_service.get_embedding, text)
            if embedding:
                # Сохраняем эмбеддинг в БД
                await paper_service.update_paper(paper.id, embedding=embedding)
                papers_with_embeddings.append({
                    "id": paper.id,
                    "title": paper.title,
                    "source": paper.source,
                    "doi": paper.doi,
                    "publication_date": paper.publication_date.isoformat() if paper.publication_date else None,
                    "journal": paper.journal,
                    "embedding": embedding,
                })

    # Перестраиваем индекс в ChromaDB с пакетным добавлением
    indexed_count = await asyncio.to_thread(vector_service.rebuild_index, papers_with_embeddings)

    logger.info(f"Векторный индекс перестроен: {indexed_count} статей")

    return VectorRebuildResponse(
        message="Векторный индекс перестроен",
        indexed=indexed_count,
        total=len(all_papers),
    )


@router.post("/clear", response_model=VectorClearResponse)
async def clear_vector_index(
    request: VectorClearRequest,
):
    """
    Очистить векторный индекс.

    **Внимание:** Эта операция необратима! Все документы будут удалены.

    Для подтверждения очистки установите `confirm=true`.
    """
    if not request.confirm:
        raise HTTPException(
            status_code=400,
            detail="Для подтверждения очистки установите confirm=true"
        )

    logger.warning("Запрос на очистку векторного индекса")

    vector_service = get_vector_service()
    success = await asyncio.to_thread(vector_service.clear)

    if success:
        logger.info("Векторное хранилище успешно очищено")
        return VectorClearResponse(
            message="Векторное хранилище очищено",
            success=True,
        )
    else:
        logger.error("Ошибка при очистке векторного хранилища")
        raise HTTPException(
            status_code=500,
            detail="Не удалось очистить векторное хранилище",
        )
