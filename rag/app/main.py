"""
Точка входа FastAPI приложения.

Запускает REST API сервер для RAG-системы анализа патентов на суперсплавы.
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import settings

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Менеджер жизненного цикла приложения.

    Выполняет инициализацию при запуске и очистку при остановке приложения.
    """
    # === Инициализация при запуске ===
    logger.info("=" * 50)
    logger.info("Запуск RAG-системы для анализа патентов")
    logger.info("=" * 50)

    # Логирование конфигурации
    logger.info(f"Директория данных: {settings.data_dir}")
    logger.info(f"Директория БД: {settings.db_dir}")
    logger.info(f"Модель эмбеддингов: {settings.embedding_model_name}")
    logger.info(f"Модель LLM: {settings.llm_model_name}")
    logger.info(f"LLM API URL: {settings.llm_api_base_url}")

    # Проверка наличия API ключа
    if not settings.llm_api_key:
        logger.warning("API ключ LLM не установлен! Генерация ответов будет недоступна.")
        logger.warning("Установите LLM_API_KEY в .env файле или переменной окружения.")

    # Создание директорий
    settings._create_directories()
    logger.info("Директории для данных созданы/проверены")

    logger.info("Инициализация завершена")
    logger.info("=" * 50)

    yield

    # === Очистка при остановке ===
    logger.info("Остановка RAG-системы...")
    logger.info("RAG-система остановлена")


# Создание приложения FastAPI
app = FastAPI(
    title="RAG-система для анализа патентов на суперсплавы",
    description="""
## Возможности системы

Система Retrieval-Augmented Generation (RAG) для работы с патентными документами в области суперсплавов.

### Основные функции

* **Загрузка патентов** - загрузка PDF файлов патентов и автоматическое извлечение текста
* **Поиск по вопросам** - ответы на вопросы на основе содержимого патентов
* **Векторный поиск** - семантический поиск по базе патентов
* **Источники** - указание документов, на которых основан ответ

### Технологический стек

* **FastAPI** - REST API сервер
* **LangChain** - фреймворк для RAG
* **ChromaDB** - векторная база данных
* **sentence-transformers** - легковесные эмбеддинги (all-MiniLM-L6-v2)
* **pdfplumber** - извлечение текста из PDF

### Лимиты

* Максимальный размер файла: 50 МБ
* Поддерживаемый формат: PDF
    """,
    version="1.0.0",
    lifespan=lifespan,
)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене ограничить до конкретных доменов
    allow_credentials=True,
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
            "details": str(exc) if app.debug else None,
        },
    )


# Подключение маршрутов
app.include_router(router, prefix="/api/v1", tags=["RAG API"])


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
        "message": "RAG-система для анализа патентов на суперсплавы",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/v1/health",
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


def main():
    """
    Точка входа для запуска сервера через CLI.

    Запускает uvicorn сервер с настройками из конфигурации.
    """
    import uvicorn

    logger.info(f"Запуск сервера на {settings.host}:{settings.port}")

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,  # Автоперезагрузка при разработке
        log_level="info",
    )


if __name__ == "__main__":
    main()
