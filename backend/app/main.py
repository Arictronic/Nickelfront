import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

# Добавляем корневую директорию проекта в sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.api.v1.endpoints import tasks as tasks_router
from app.api.v1.endpoints import parse as parse_router
from app.api.v1.endpoints import auth as auth_router
from app.api.v1.endpoints import vector as vector_router
from app.api.v1.endpoints import analytics as analytics_router
from app.api.v1.endpoints import reports as reports_router
from app.api.v1.endpoints import monitoring as monitoring_router
from app.api.v1.endpoints import search as search_router
from app.core.logging import setup_logging
from app.core.config import settings

setup_logging()

app = FastAPI(
    title="Nickelfront API",
    description="Платформа для парсинга и анализа патентов",
    version="1.0.0"
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

# Подключаем роутеры
app.include_router(tasks_router.router, prefix="/api/v1")
app.include_router(parse_router.router, prefix="/api/v1")
app.include_router(auth_router.router, prefix="/api/v1")
app.include_router(vector_router.router, prefix="/api/v1")
app.include_router(analytics_router.router, prefix="/api/v1")
app.include_router(reports_router.router, prefix="/api/v1")
app.include_router(monitoring_router.router, prefix="/api/v1")
app.include_router(search_router.router, prefix="/api/v1")


@app.on_event("startup")
async def startup_event():
    logger.info("Приложение запущено")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Приложение останавливается")


@app.get("/health")
async def health_check():
    return {"status": "ok"}
