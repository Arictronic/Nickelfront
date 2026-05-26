"""Скрипт для запуска backend API с правильными путями и быстрым dev-start."""
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import uvicorn
from app.core.config import settings


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return default


if __name__ == "__main__":



    reload_enabled = _env_bool("NICKELFRONT_BACKEND_RELOAD", False)

    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=reload_enabled,


        reload_dirs=[
            str(BACKEND_DIR),
            str(ROOT_DIR / "shared"),
            str(ROOT_DIR / "parser_alpha"),
        ] if reload_enabled else None,
        reload_excludes=[
            "*.log",
            "logs/*",
            "logs/**/*",
            "chroma_db/*",
            "chroma_db/**/*",
            "reports/*",
            "reports/**/*",
            "frontend/node_modules/*",
            "frontend/node_modules/**/*",
            "parser_alpha/data/*",
            "parser_alpha/data/**/*",
            "__pycache__/*",
            "__pycache__/**/*",
        ] if reload_enabled else None,
    )
