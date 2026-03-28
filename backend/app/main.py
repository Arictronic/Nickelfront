"""
Точка входа FastAPI приложения.

Запускает REST API сервер для платформы анализа патентов и научных статей.
"""
# ruff: noqa: E402

import asyncio
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

# Добавляем корневую директорию проекта в sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.api.v1.endpoints import (
    analytics as analytics_router,
)
from app.api.v1.endpoints import (
    auth as auth_router,
)
from app.api.v1.endpoints import (
    monitoring as monitoring_router,
)
from app.api.v1.endpoints import (
    parse as parse_router,
)
from app.api.v1.endpoints import (
    qwen as qwen_router,
)
from app.api.v1.endpoints import (
    rag as rag_router,
)
from app.api.v1.endpoints import (
    reports as reports_router,
)
from app.api.v1.endpoints import (
    search as search_router,
)
from app.api.v1.endpoints import (
    tasks as tasks_router,
)
from app.api.v1.endpoints import (
    vector as vector_router,
)
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Менеджер жизненного цикла приложения.

    Выполняет инициализацию при запуске и очистку при остановке приложения.
    """
    # === Инициализация при запуске ===
    logger.info("=" * 60)
    logger.info("Запуск платформы Nickelfront")
    logger.info("=" * 60)

    # Логирование конфигурации
    logger.info(f"Хост: {settings.API_HOST}:{settings.API_PORT}")
    logger.info(f"Режим отладки: {settings.DEBUG}")
    logger.info(f"Database URL: {settings.DATABASE_URL[:50]}...")
    logger.info(f"Redis URL: {settings.REDIS_URL}")
    logger.info(f"CORS origins: {settings.get_cors_origins()}")

    # Векторный поиск
    logger.info(f"ChromaDB path: {settings.CHROMA_DB_PATH}")
    logger.info(f"Embedding model: {settings.EMBEDDING_MODEL}")
    logger.info(f"Embedding dim: {settings.EMBEDDING_DIM}")

    # LLM
    if settings.QWEN_TOKEN:
        logger.info(f"Qwen модель: {settings.QWEN_MODEL}")
        if settings.QWEN_USE_STANDALONE:
            logger.info(f"Qwen Service: http://{settings.QWEN_SERVICE_HOST}:{settings.QWEN_SERVICE_PORT}")
        else:
            logger.info("Qwen: встроенная интеграция")
    else:
        logger.warning("Qwen токен не установлен. Генерация ответов будет недоступна.")
        logger.warning("Установите QWEN_TOKEN в .env файле.")

    # Создание директорий
    log_dir = Path(settings.LOG_FILE).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Директория для логов: {log_dir}")

    logger.info("Инициализация завершена")
    logger.info("=" * 60)

    yield

    # === Очистка при остановке ===
    logger.info("Остановка платформы Nickelfront...")
    logger.info("Платформа остановлена")


# Создание приложения FastAPI
app = FastAPI(
    title="Nickelfront API",
    description="""
## Возможности платформы

Платформа для парсинга и анализа научных статей и патентов в области материаловедения.

### Основные функции

* **Парсинг статей** - автоматический парсинг из arXiv, CORE, ScienceDirect
* **Векторный поиск** - семантический поиск по базе статей
* **Полнотекстовый поиск** - поиск по ключевым словам
* **Аналитика** - метрики и отчёты по статьям
* **Экспорт** - выгрузка отчётов в PDF/DOCX
* **Мониторинг** - отслеживание Celery задач

### Технологический стек

* **FastAPI** - REST API сервер
* **PostgreSQL** - основная база данных
* **ChromaDB** - векторная база данных
* **Celery** - фоновые задачи
* **Redis** - брокер сообщений
    """,
    version="1.0.0",
    lifespan=lifespan,
)


# CORS middleware
cors_origins = settings.get_cors_origins()
allow_credentials = "*" not in cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Глобальный обработчик необработанных исключений.

    Логирует ошибку и возвращает пользователю безопасное сообщение.
    """
    logger.error(f"Необработанное исключение: {exc}", exc_info=True)

    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "Внутренняя ошибка сервера",
            "details": str(exc) if settings.DEBUG else None,
        },
    )


# Подключение роутеров
app.include_router(tasks_router.router, prefix="/api/v1")
app.include_router(parse_router.router, prefix="/api/v1")
app.include_router(auth_router.router, prefix="/api/v1")
app.include_router(vector_router.router, prefix="/api/v1")
app.include_router(analytics_router.router, prefix="/api/v1")
app.include_router(reports_router.router, prefix="/api/v1")
app.include_router(monitoring_router.router, prefix="/api/v1")
app.include_router(search_router.router, prefix="/api/v1")
app.include_router(qwen_router.router, prefix="/api/v1")
app.include_router(rag_router.router, prefix="/api/v1")


@app.get(
    "/",
    tags=["Root"],
    summary="Корневой эндпоинт",
    description="Возвращает приветственное сообщение и ссылку на документацию.",
)
async def root():
    """
    Корневой эндпоинт приложения.

    Returns:
        dict: Приветственное сообщение.
    """
    return {
        "message": "Nickelfront API - Платформа для анализа патентов и научных статей",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


@app.get(
    "/ping",
    tags=["Root"],
    summary="Проверка доступности",
    description="Простой эндпоинт для проверки доступности сервера.",
)
async def ping():
    """
    Простая проверка доступности сервера.

    Returns:
        dict: Сообщение pong.
    """
    return {"status": "pong"}


@app.get(
    "/health",
    tags=["Monitoring"],
    summary="Проверка статуса приложения",
    description="Возвращает текущий статус приложения и доступность сервисов.",
)
async def health_check():
    """
    Эндпоинт для проверки здоровья приложения.

    Returns:
        dict: Статус приложения, версия, доступность сервисов.
    """
    from app.services.embedding_service import get_embedding_service
    from app.services.vector_service import get_vector_service

    logger.info("Проверка здоровья приложения")

    # Проверка сервисов
    embedding_service = get_embedding_service()
    vector_service = get_vector_service()

    vector_stats = await asyncio.to_thread(vector_service.get_stats)
    embedding_available = await asyncio.to_thread(lambda: embedding_service.model is not None)

    return {
        "status": "ok",
        "version": "1.0.0",
        "services": {
            "database": "connected",  # TODO: добавить проверку БД
            "redis": "connected",  # TODO: добавить проверку Redis
            "embedding": {
                "available": embedding_available,
                "model": settings.EMBEDDING_MODEL,
                "dim": settings.EMBEDDING_DIM,
            },
            "vector_search": {
                "available": vector_stats.get("available", False),
                "documents": vector_stats.get("count", 0),
            },
            "qwen": {
                "available": bool(settings.QWEN_TOKEN),
                "model": settings.QWEN_MODEL,
                "standalone": settings.QWEN_USE_STANDALONE,
            },
        },
    }
