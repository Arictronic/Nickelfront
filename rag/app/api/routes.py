"""
Модуль маршрутов API.

Содержит реализацию REST эндпоинтов для взаимодействия с RAG-системой.
"""

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.api.schemas import (
    AskRequest,
    AskResponse,
    ClearStoreResponse,
    ErrorResponse,
    HealthResponse,
    SourceDocument,
    StatsResponse,
    UploadResponse,
    VectorStoreStats,
)
from app.config import settings
from app.core.rag_chain import process_query, process_query_with_sources
from app.core.vector_store import vector_store_manager
from app.services.llm_service import llm_service
from app.services.parser_service import pdf_parser

logger = logging.getLogger(__name__)

# Создание роутера
router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Проверка статуса приложения",
    description="Возвращает текущий статус приложения и доступность сервисов.",
)
async def health_check() -> HealthResponse:
    """
    Эндпоинт для проверки здоровья приложения.

    Returns:
        HealthResponse: Статус приложения, версия, доступность LLM и количество документов.

    Example:
        GET /health
        {
            "status": "ok",
            "version": "1.0.0",
            "llm_available": true,
            "vector_store_documents": 150
        }
    """
    logger.info("Проверка здоровья приложения")

    # Получение статистики векторного хранилища
    stats = vector_store_manager.get_stats()

    return HealthResponse(
        status="ok",
        version="1.0.0",
        llm_available=llm_service.is_available(),
        vector_store_documents=stats["total_documents"],
    )


@router.post(
    "/ask",
    response_model=AskResponse,
    responses={
        200: {"description": "Успешный ответ на вопрос"},
        400: {"model": ErrorResponse, "description": "Некорректный запрос"},
        500: {"model": ErrorResponse, "description": "Ошибка обработки запроса"},
    },
    summary="Задать вопрос по патентам",
    description="Отправляет вопрос в RAG-систему и получает ответ на основе патентных документов.",
)
async def ask_question(request: AskRequest) -> AskResponse:
    """
    Обработка вопроса пользователя через RAG-систему.

    Args:
        request: Запрос с вопросом и опциями.

    Returns:
        AskResponse: Ответ с результатом и источниками.

    Raises:
        HTTPException: При ошибке обработки запроса.

    Example:
        POST /ask
        {
            "question": "Какой состав у сплава ХН77ТЮР?",
            "include_sources": true,
            "include_scores": false
        }
    """
    logger.info(f"Получен вопрос: {request.question[:100]}...")

    try:
        # Обработка запроса через RAG-цепь
        if request.include_sources:
            result = process_query_with_sources(
                question=request.question,
                include_scores=request.include_scores,
            )
        else:
            result = process_query(request.question)

        # Форматирование источников
        sources: list[SourceDocument] = []
        for doc in result.get("source_documents", []):
            source_doc = SourceDocument(
                index=doc.get("index", 0),
                content=doc.get("content", ""),
                metadata=doc.get("metadata", {}),
                relevance_score=doc.get("relevance_score"),
            )
            sources.append(source_doc)

        return AskResponse(
            answer=result.get("result", ""),
            question=result.get("query", request.question),
            sources=sources,
            documents_found=result.get("documents_found", len(sources)),
        )

    except RuntimeError as e:
        logger.error(f"Ошибка RAG-цепи: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обработки запроса: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Неожиданная ошибка при обработке вопроса: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}",
        )


@router.post(
    "/upload",
    response_model=UploadResponse,
    responses={
        200: {"description": "Файл успешно загружен и обработан"},
        400: {"model": ErrorResponse, "description": "Некорректный файл"},
        413: {"model": ErrorResponse, "description": "Файл слишком большой"},
        415: {"model": ErrorResponse, "description": "Неподдерживаемый тип файла"},
        500: {"model": ErrorResponse, "description": "Ошибка обработки файла"},
    },
    summary="Загрузить PDF патента",
    description="Загружает PDF файл патента, извлекает текст и сохраняет в векторную базу.",
)
async def upload_patent(
    file: UploadFile = File(..., description="PDF файл патента"),
) -> UploadResponse:
    """
    Загрузка и обработка PDF файла патента.

    Args:
        file: Загружаемый PDF файл.

    Returns:
        UploadResponse: Результат загрузки с количеством документов.

    Raises:
        HTTPException: При ошибке загрузки или обработки файла.

    Example:
        POST /upload
        Content-Type: multipart/form-data
        file: <patent.pdf>
    """
    logger.info(f"Получен файл для загрузки: {file.filename}")

    # Проверка типа файла
    if not file.filename.lower().endswith(".pdf"):
        logger.warning(f"Попытка загрузить файл не PDF: {file.filename}")
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Поддерживаются только PDF файлы",
        )

    # Проверка размера файла
    file_size = 0
    file_bytes = await file.read()
    file_size = len(file_bytes)

    if file_size > settings.max_file_size_bytes:
        logger.warning(
            f"Файл слишком большой: {file_size} байт (лимит: {settings.max_file_size_bytes})"
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Файл слишком большой. Максимум {settings.max_file_size_mb} МБ",
        )

    if file_size == 0:
        logger.warning("Получен пустой файл")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Файл пуст",
        )

    try:
        # Парсинг PDF в документы
        logger.info(f"Парсинг PDF: {file.filename} ({file_size} байт)")
        documents = pdf_parser.parse_bytes_to_documents(
            file_bytes=file_bytes,
            filename=file.filename,
            metadata={"file_size": file_size},
        )

        if not documents:
            logger.warning("PDF не содержит извлекаемого текста")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Не удалось извлечь текст из PDF. Возможно, файл содержит только изображения.",
            )

        # Добавление документов в векторное хранилище
        logger.info(f"Добавление {len(documents)} документов в векторную базу")
        vector_store_manager.add_documents(documents)

        logger.info(f"Файл успешно обработан: {file.filename}")

        return UploadResponse(
            message="Файл успешно загружен и обработан",
            filename=file.filename,
            documents_count=len(documents),
            file_size=file_size,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при обработке файла {file.filename}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка обработки файла: {str(e)}",
        )


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Статистика системы",
    description="Возвращает статистику векторного хранилища и используемых моделей.",
)
async def get_stats() -> StatsResponse:
    """
    Получение статистики системы.

    Returns:
        StatsResponse: Статистика векторного хранилища и моделей.

    Example:
        GET /stats
        {
            "vector_store": {
                "total_documents": 150,
                "collection_name": "patents_collection",
                "persist_directory": "./data/db"
            },
            "llm_model": "gpt-3.5-turbo",
            "embedding_model": "all-MiniLM-L6-v2"
        }
    """
    logger.info("Запрос статистики системы")

    stats = vector_store_manager.get_stats()

    return StatsResponse(
        vector_store=VectorStoreStats(
            total_documents=stats["total_documents"],
            collection_name=stats["collection_name"],
            persist_directory=stats["persist_directory"],
        ),
        llm_model=settings.llm_model_name,
        embedding_model=settings.embedding_model_name,
    )


@router.post(
    "/clear",
    response_model=ClearStoreResponse,
    summary="Очистить векторное хранилище",
    description="Удаляет все документы из векторной базы данных.",
)
async def clear_store() -> ClearStoreResponse:
    """
    Очистка векторного хранилища.

    Returns:
        ClearStoreResponse: Результат операции.

    Warning:
        Эта операция необратима! Все документы будут удалены.

    Example:
        POST /clear
        {
            "message": "Векторное хранилище очищено",
            "success": true
        }
    """
    logger.warning("Запрос на очистку векторного хранилища")

    success = vector_store_manager.clear()

    if success:
        logger.info("Векторное хранилище успешно очищено")
        return ClearStoreResponse(
            message="Векторное хранилище очищено",
            success=True,
        )
    else:
        logger.error("Ошибка при очистке векторного хранилища")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось очистить векторное хранилище",
        )


@router.get(
    "/models",
    summary="Информация о моделях",
    description="Возвращает информацию об используемых моделях LLM и эмбеддингов.",
)
async def get_models_info() -> dict:
    """
    Получение информации о моделях.

    Returns:
        dict: Информация о моделях и их настройках.
    """
    return {
        "llm": {
            "model": settings.llm_model_name,
            "base_url": settings.llm_api_base_url,
            "api_key_configured": bool(settings.llm_api_key),
        },
        "embeddings": {
            "model": settings.embedding_model_name,
            "device": settings.embedding_device,
        },
        "chunking": {
            "chunk_size": settings.max_chunk_size,
            "chunk_overlap": settings.chunk_overlap,
        },
        "search": {
            "default_k": settings.search_k,
        },
    }
