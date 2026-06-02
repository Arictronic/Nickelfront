"""
Точка входа FastAPI приложения.

Запускает REST API сервер для платформы анализа патентов и научных статей.
"""


import asyncio
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
import redis.asyncio as redis
from sqlalchemy import text


BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.api.v1.endpoints import (
    admin_settings as admin_settings_router,
)
from app.api.v1.endpoints import (
    analytics as analytics_router,
)
from app.api.v1.endpoints import (
    auth as auth_router,
)
from app.api.v1.endpoints import (
    dashboard as dashboard_router,
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
    analysis as analysis_router,
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
from app.core.logging import setup_logging
from app.db.session import async_session_maker

setup_logging(service_name="backend_api")


def _redact_url(value: str | None) -> str:
    """Скрыть пароль/токен в URL перед записью в логи."""
    if not value:
        return ""
    try:
        parts = urlsplit(value)
        netloc = parts.netloc
        if "@" in netloc:
            credentials, host = netloc.rsplit("@", 1)
            if ":" in credentials:
                username, _ = credentials.split(":", 1)
                netloc = f"{username}:***@{host}"
            else:
                netloc = f"***@{host}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return "***"


async def _verify_database_schema_ready() -> None:
    """Fail fast when backend points to a database without core tables.

    This catches the dangerous state where Alembic was run against one
    connection but the API starts with another DATABASE_URL. Without this guard
    the first login request fails later with a noisy UndefinedTableError.
    """
    required_tables = (
        "papers",
        "users",
        "refresh_tokens",
        "patent_tasks",
        "paper_content_parts",
        "system_settings",
    )
    missing: list[str] = []

    async with async_session_maker() as session:
        for table_name in required_tables:
            result = await session.execute(
                text("SELECT to_regclass(:table_name)"),
                {"table_name": table_name},
            )
            if result.scalar_one_or_none() is None:
                missing.append(table_name)

        version_result = await session.execute(
            text("SELECT to_regclass('alembic_version')")
        )
        has_alembic_version = version_result.scalar_one_or_none() is not None

    if missing or not has_alembic_version:
        details = []
        if not has_alembic_version:
            details.append("alembic_version")
        details.extend(missing)
        raise RuntimeError(
            "Database schema is not ready for Nickelfront. Missing table(s): "
            + ", ".join(details)
            + ". Run: .venv\\Scripts\\python.exe backend\\apply_migrations.py. "
            + f"DATABASE_URL={_redact_url(settings.DATABASE_URL)}"
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Менеджер жизненного цикла приложения.

    Выполняет инициализацию при запуске и очистку при остановке приложения.
    """

    logger.info("=" * 60)
    logger.info("Запуск платформы Nickelfront")
    logger.info("=" * 60)


    logger.info(f"Хост: {settings.API_HOST}:{settings.API_PORT}")
    logger.info(f"Режим отладки: {settings.DEBUG}")
    logger.info(f"Database URL: {_redact_url(settings.DATABASE_URL)}")
    logger.info(f"Redis URL: {_redact_url(settings.REDIS_URL)}")
    logger.info(f"CORS origins: {settings.get_cors_origins()}")

    await _verify_database_schema_ready()
    logger.info("Database schema check: OK")

    logger.info(f"ChromaDB path: {settings.CHROMA_DB_PATH}")
    logger.info(f"Embedding model: {settings.EMBEDDING_MODEL}")
    logger.info(f"Embedding dim: {settings.EMBEDDING_DIM}")


    if settings.QWEN_TOKEN:
        logger.info(f"Qwen модель: {settings.QWEN_MODEL}")
        if settings.QWEN_USE_STANDALONE:
            logger.info(f"Qwen Service: http://{settings.QWEN_SERVICE_HOST}:{settings.QWEN_SERVICE_PORT}")
        else:
            logger.info("Qwen: встроенная интеграция")
    else:
        logger.warning("Qwen токен не установлен. Генерация ответов будет недоступна.")
        logger.warning("Установите QWEN_TOKEN в .env файле.")


    log_dir = Path(settings.LOG_FILE).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Директория для логов: {log_dir}")

    logger.info("Инициализация завершена")
    logger.info("=" * 60)

    yield


    logger.info("Остановка платформы Nickelfront...")
    logger.info("Платформа остановлена")



app = FastAPI(
    title="Nickelfront API",
    description="""
## Возможности платформы

Платформа для парсинга и анализа научных статей и патентов в области материаловедения.

### Основные функции

* **Парсинг статей** - автоматический парсинг из arXiv, CORE, OpenAlex, Crossref, EuropePMC, CyberLeninka, eLibrary, Rospatent, FreePatent, GooglePatents, PATENTSCOPE
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



app.include_router(admin_settings_router.router, prefix="/api/v1")
app.include_router(tasks_router.router, prefix="/api/v1")
app.include_router(parse_router.router, prefix="/api/v1")
app.include_router(auth_router.router, prefix="/api/v1")
app.include_router(dashboard_router.router, prefix="/api/v1")
app.include_router(vector_router.router, prefix="/api/v1")
app.include_router(analytics_router.router, prefix="/api/v1")
app.include_router(reports_router.router, prefix="/api/v1")
app.include_router(monitoring_router.router, prefix="/api/v1")
app.include_router(search_router.router, prefix="/api/v1")
app.include_router(qwen_router.router, prefix="/api/v1")
app.include_router(rag_router.router, prefix="/api/v1")
app.include_router(analysis_router.router, prefix="/api/v1")


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
    """Проверка состояния API, PostgreSQL, Redis и настроек внешних сервисов."""
    logger.info("Health check request")

    database_status = "disconnected"
    redis_status = "disconnected"

    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
        database_status = "connected"
    except Exception as exc:
        logger.warning(f"Health check database failed: {exc}")

    redis_client = None
    try:
        redis_client = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        await redis_client.ping()
        redis_status = "connected"
    except Exception as exc:
        logger.warning(f"Health check Redis failed: {exc}")
    finally:
        if redis_client is not None:
            await redis_client.aclose()

    overall_status = "ok" if database_status == "connected" and redis_status == "connected" else "degraded"

    return {
        "status": overall_status,
        "version": "1.0.0",
        "services": {
            "database": database_status,
            "redis": redis_status,
            "embedding": {
                "available": True,
                "model": settings.EMBEDDING_MODEL,
                "dim": settings.EMBEDDING_DIM,
                "lazy_loaded": True,
            },
            "vector_search": {
                "available": True,
                "documents": None,
                "lazy_loaded": True,
            },
            "qwen": {
                "available": bool(settings.QWEN_TOKEN),
                "model": settings.QWEN_MODEL,
                "standalone": settings.QWEN_USE_STANDALONE,
            },
        },
    }
