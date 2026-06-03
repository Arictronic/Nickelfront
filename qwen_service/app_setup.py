"""FastAPI application setup helpers for qwen_service."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


_DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8001,http://127.0.0.1:8001"


def _configured_cors_origins() -> list[str]:
    raw = (os.getenv("QWEN_CORS_ORIGINS", _DEFAULT_CORS_ORIGINS) or "").strip()
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or _DEFAULT_CORS_ORIGINS.split(",")


def create_qwen_app() -> FastAPI:
    """Create the standalone Qwen service FastAPI application."""
    app = FastAPI(title="Qwen Service", description="Мини-сервис для работы с Qwen API", version="1.0.0")
    origins = _configured_cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )
    return app
