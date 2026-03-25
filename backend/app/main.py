from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.v1.endpoints import tasks as tasks_router
from app.api.v1.endpoints import parse as parse_router
from app.core.logging import setup_logging
from app.core.config import settings

setup_logging()

app = FastAPI(
    title="Nickelfront API",
    description="Платформа для парсинга и анализа патентов",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем роутеры
app.include_router(tasks_router.router, prefix="/api/v1")
app.include_router(parse_router.router, prefix="/api/v1")


@app.on_event("startup")
async def startup_event():
    logger.info("Приложение запущено")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Приложение останавливается")


@app.get("/health")
async def health_check():
    return {"status": "ok"}
