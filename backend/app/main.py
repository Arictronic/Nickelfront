"""
РўРѕС‡РєР° РІС…РѕРґР° FastAPI РїСЂРёР»РѕР¶РµРЅРёСЏ.

Р—Р°РїСѓСЃРєР°РµС‚ REST API СЃРµСЂРІРµСЂ РґР»СЏ РїР»Р°С‚С„РѕСЂРјС‹ Р°РЅР°Р»РёР·Р° РїР°С‚РµРЅС‚РѕРІ Рё РЅР°СѓС‡РЅС‹С… СЃС‚Р°С‚РµР№.
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

# Р”РѕР±Р°РІР»СЏРµРј РєРѕСЂРЅРµРІСѓСЋ РґРёСЂРµРєС‚РѕСЂРёСЋ РїСЂРѕРµРєС‚Р° РІ sys.path
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
from app.core.logging import setup_logging

setup_logging(service_name="backend_api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    РњРµРЅРµРґР¶РµСЂ Р¶РёР·РЅРµРЅРЅРѕРіРѕ С†РёРєР»Р° РїСЂРёР»РѕР¶РµРЅРёСЏ.

    Р’С‹РїРѕР»РЅСЏРµС‚ РёРЅРёС†РёР°Р»РёР·Р°С†РёСЋ РїСЂРё Р·Р°РїСѓСЃРєРµ Рё РѕС‡РёСЃС‚РєСѓ РїСЂРё РѕСЃС‚Р°РЅРѕРІРєРµ РїСЂРёР»РѕР¶РµРЅРёСЏ.
    """
    # === РЅРёС†РёР°Р»РёР·Р°С†РёСЏ РїСЂРё Р·Р°РїСѓСЃРєРµ ===
    logger.info("=" * 60)
    logger.info("Р—Р°РїСѓСЃРє РїР»Р°С‚С„РѕСЂРјС‹ Nickelfront")
    logger.info("=" * 60)

    # Р›РѕРіРёСЂРѕРІР°РЅРёРµ РєРѕРЅС„РёРіСѓСЂР°С†РёРё
    logger.info(f"РҐРѕСЃС‚: {settings.API_HOST}:{settings.API_PORT}")
    logger.info(f"Р РµР¶РёРј РѕС‚Р»Р°РґРєРё: {settings.DEBUG}")
    logger.info(f"Database URL: {settings.DATABASE_URL[:50]}...")
    logger.info(f"Redis URL: {settings.REDIS_URL}")
    logger.info(f"CORS origins: {settings.get_cors_origins()}")

    # Р’РµРєС‚РѕСЂРЅС‹Р№ РїРѕРёСЃРє
    logger.info(f"ChromaDB path: {settings.CHROMA_DB_PATH}")
    logger.info(f"Embedding model: {settings.EMBEDDING_MODEL}")
    logger.info(f"Embedding dim: {settings.EMBEDDING_DIM}")

    # LLM
    if settings.QWEN_TOKEN:
        logger.info(f"Qwen РјРѕРґРµР»СЊ: {settings.QWEN_MODEL}")
        if settings.QWEN_USE_STANDALONE:
            logger.info(f"Qwen Service: http://{settings.QWEN_SERVICE_HOST}:{settings.QWEN_SERVICE_PORT}")
        else:
            logger.info("Qwen: РІСЃС‚СЂРѕРµРЅРЅР°СЏ РёРЅС‚РµРіСЂР°С†РёСЏ")
    else:
        logger.warning("Qwen С‚РѕРєРµРЅ РЅРµ СѓСЃС‚Р°РЅРѕРІР»РµРЅ. Р“РµРЅРµСЂР°С†РёСЏ РѕС‚РІРµС‚РѕРІ Р±СѓРґРµС‚ РЅРµРґРѕСЃС‚СѓРїРЅР°.")
        logger.warning("РЈСЃС‚Р°РЅРѕРІРёС‚Рµ QWEN_TOKEN РІ .env С„Р°Р№Р»Рµ.")

    # РЎРѕР·РґР°РЅРёРµ РґРёСЂРµРєС‚РѕСЂРёР№
    log_dir = Path(settings.LOG_FILE).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Р”РёСЂРµРєС‚РѕСЂРёСЏ РґР»СЏ Р»РѕРіРѕРІ: {log_dir}")

    logger.info("РРЅРёС†РёР°Р»РёР·Р°С†РёСЏ Р·Р°РІРµСЂС€РµРЅР°")
    logger.info("=" * 60)

    yield

    # === РћС‡РёСЃС‚РєР° РїСЂРё РѕСЃС‚Р°РЅРѕРІРєРµ ===
    logger.info("РћСЃС‚Р°РЅРѕРІРєР° РїР»Р°С‚С„РѕСЂРјС‹ Nickelfront...")
    logger.info("РџР»Р°С‚С„РѕСЂРјР° РѕСЃС‚Р°РЅРѕРІР»РµРЅР°")


# РЎРѕР·РґР°РЅРёРµ РїСЂРёР»РѕР¶РµРЅРёСЏ FastAPI
app = FastAPI(
    title="Nickelfront API",
    description="""
## Р’РѕР·РјРѕР¶РЅРѕСЃС‚Рё РїР»Р°С‚С„РѕСЂРјС‹

РџР»Р°С‚С„РѕСЂРјР° РґР»СЏ РїР°СЂСЃРёРЅРіР° Рё Р°РЅР°Р»РёР·Р° РЅР°СѓС‡РЅС‹С… СЃС‚Р°С‚РµР№ Рё РїР°С‚РµРЅС‚РѕРІ РІ РѕР±Р»Р°СЃС‚Рё РјР°С‚РµСЂРёР°Р»РѕРІРµРґРµРЅРёСЏ.

### РћСЃРЅРѕРІРЅС‹Рµ С„СѓРЅРєС†РёРё

* **РџР°СЂСЃРёРЅРі СЃС‚Р°С‚РµР№** - Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРёР№ РїР°СЂСЃРёРЅРі РёР· arXiv, CORE, OpenAlex, Crossref, SemanticScholar, EuropePMC
* **Р’РµРєС‚РѕСЂРЅС‹Р№ РїРѕРёСЃРє** - СЃРµРјР°РЅС‚РёС‡РµСЃРєРёР№ РїРѕРёСЃРє РїРѕ Р±Р°Р·Рµ СЃС‚Р°С‚РµР№
* **РџРѕР»РЅРѕС‚РµРєСЃС‚РѕРІС‹Р№ РїРѕРёСЃРє** - РїРѕРёСЃРє РїРѕ РєР»СЋС‡РµРІС‹Рј СЃР»РѕРІР°Рј
* **РђРЅР°Р»РёС‚РёРєР°** - РјРµС‚СЂРёРєРё Рё РѕС‚С‡С‘С‚С‹ РїРѕ СЃС‚Р°С‚СЊСЏРј
* **Р­РєСЃРїРѕСЂС‚** - РІС‹РіСЂСѓР·РєР° РѕС‚С‡С‘С‚РѕРІ РІ PDF/DOCX
* **РњРѕРЅРёС‚РѕСЂРёРЅРі** - РѕС‚СЃР»РµР¶РёРІР°РЅРёРµ Celery Р·Р°РґР°С‡

### РўРµС…РЅРѕР»РѕРіРёС‡РµСЃРєРёР№ СЃС‚РµРє

* **FastAPI** - REST API СЃРµСЂРІРµСЂ
* **PostgreSQL** - РѕСЃРЅРѕРІРЅР°СЏ Р±Р°Р·Р° РґР°РЅРЅС‹С…
* **ChromaDB** - РІРµРєС‚РѕСЂРЅР°СЏ Р±Р°Р·Р° РґР°РЅРЅС‹С…
* **Celery** - С„РѕРЅРѕРІС‹Рµ Р·Р°РґР°С‡Рё
* **Redis** - Р±СЂРѕРєРµСЂ СЃРѕРѕР±С‰РµРЅРёР№
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
    Р“Р»РѕР±Р°Р»СЊРЅС‹Р№ РѕР±СЂР°Р±РѕС‚С‡РёРє РЅРµРѕР±СЂР°Р±РѕС‚Р°РЅРЅС‹С… РёСЃРєР»СЋС‡РµРЅРёР№.

    Р›РѕРіРёСЂСѓРµС‚ РѕС€РёР±РєСѓ Рё РІРѕР·РІСЂР°С‰Р°РµС‚ РїРѕР»СЊР·РѕРІР°С‚РµР»СЋ Р±РµР·РѕРїР°СЃРЅРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ.
    """
    logger.error(f"РќРµРѕР±СЂР°Р±РѕС‚Р°РЅРЅРѕРµ РёСЃРєР»СЋС‡РµРЅРёРµ: {exc}", exc_info=True)

    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "Р’РЅСѓС‚СЂРµРЅРЅСЏСЏ РѕС€РёР±РєР° СЃРµСЂРІРµСЂР°",
            "details": str(exc) if settings.DEBUG else None,
        },
    )


# РџРѕРґРєР»СЋС‡РµРЅРёРµ СЂРѕСѓС‚РµСЂРѕРІ
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
    summary="РљРѕСЂРЅРµРІРѕР№ СЌРЅРґРїРѕРёРЅС‚",
    description="Р’РѕР·РІСЂР°С‰Р°РµС‚ РїСЂРёРІРµС‚СЃС‚РІРµРЅРЅРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ Рё СЃСЃС‹Р»РєСѓ РЅР° РґРѕРєСѓРјРµРЅС‚Р°С†РёСЋ.",
)
async def root():
    """
    РљРѕСЂРЅРµРІРѕР№ СЌРЅРґРїРѕРёРЅС‚ РїСЂРёР»РѕР¶РµРЅРёСЏ.

    Returns:
        dict: РџСЂРёРІРµС‚СЃС‚РІРµРЅРЅРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ.
    """
    return {
        "message": "Nickelfront API - РџР»Р°С‚С„РѕСЂРјР° РґР»СЏ Р°РЅР°Р»РёР·Р° РїР°С‚РµРЅС‚РѕРІ Рё РЅР°СѓС‡РЅС‹С… СЃС‚Р°С‚РµР№",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


@app.get(
    "/ping",
    tags=["Root"],
    summary="РџСЂРѕРІРµСЂРєР° РґРѕСЃС‚СѓРїРЅРѕСЃС‚Рё",
    description="РџСЂРѕСЃС‚РѕР№ СЌРЅРґРїРѕРёРЅС‚ РґР»СЏ РїСЂРѕРІРµСЂРєРё РґРѕСЃС‚СѓРїРЅРѕСЃС‚Рё СЃРµСЂРІРµСЂР°.",
)
async def ping():
    """
    РџСЂРѕСЃС‚Р°СЏ РїСЂРѕРІРµСЂРєР° РґРѕСЃС‚СѓРїРЅРѕСЃС‚Рё СЃРµСЂРІРµСЂР°.

    Returns:
        dict: РЎРѕРѕР±С‰РµРЅРёРµ pong.
    """
    return {"status": "pong"}


@app.get(
    "/health",
    tags=["Monitoring"],
    summary="РџСЂРѕРІРµСЂРєР° СЃС‚Р°С‚СѓСЃР° РїСЂРёР»РѕР¶РµРЅРёСЏ",
    description="Р’РѕР·РІСЂР°С‰Р°РµС‚ С‚РµРєСѓС‰РёР№ СЃС‚Р°С‚СѓСЃ РїСЂРёР»РѕР¶РµРЅРёСЏ Рё РґРѕСЃС‚СѓРїРЅРѕСЃС‚СЊ СЃРµСЂРІРёСЃРѕРІ.",
)
async def health_check():
    """
    Р­РЅРґРїРѕРёРЅС‚ РґР»СЏ РїСЂРѕРІРµСЂРєРё Р·РґРѕСЂРѕРІСЊСЏ РїСЂРёР»РѕР¶РµРЅРёСЏ.

    Returns:
        dict: РЎС‚Р°С‚СѓСЃ РїСЂРёР»РѕР¶РµРЅРёСЏ, РІРµСЂСЃРёСЏ, РґРѕСЃС‚СѓРїРЅРѕСЃС‚СЊ СЃРµСЂРІРёСЃРѕРІ.
    """
    logger.info("Health check request")

    return {
        "status": "ok",
        "version": "1.0.0",
        "services": {
            "database": "connected",  # TODO: add real DB check
            "redis": "connected",  # TODO: add real Redis check
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


