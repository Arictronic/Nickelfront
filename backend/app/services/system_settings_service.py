"""Service for global technical settings stored in DB."""

from __future__ import annotations

import copy
import os
from collections.abc import Mapping
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.system_setting import SystemSetting

PARSER_SOURCES = [
    "CORE",
    "arXiv",
    "OpenAlex",
    "Crossref",
    "EuropePMC",
    "CyberLeninka",
    "eLibrary",
    "Rospatent",
    "FreePatent",
    "PATENTSCOPE",
]

DEFAULT_SYSTEM_SETTINGS: dict[str, dict[str, Any]] = {
    "parser": {
        "enabled": True,
        "default_limit": 10,
        "max_limit": 100,
        "subprocess_timeout_seconds": 300,
        "retry_count": 1,
        "retry_delay_seconds": 5,
        "max_parallel_parse_jobs": 1,
        "enabled_sources": {source: True for source in PARSER_SOURCES},
        "source_limits": {source: 20 for source in PARSER_SOURCES},
        "postprocess": {
            "download_pdf": True,
            "extract_pdf_text": True,
            "qwen_markdown": True,
            "qwen_ru_analysis": True,
            "qwen_keywords": True,
            "embedding": True,
        },
    },
    "pdf_markdown": {
        "pages_per_request": settings.QWEN_MARKDOWN_PAGES_PER_REQUEST,
        "page_chars": settings.QWEN_MARKDOWN_PAGE_CHARS,
        "save_raw_parts": True,
        "save_markdown_parts": True,
        "normalize_math": True,
        "show_extraction_diagnostics": True,
        "parser_mode": "auto",
        "ocr_mode": "auto",
        "ai_mode": "off",
        "force_strategy": "",
        "extraction_mode": "auto",
        "ocr_engine": "auto",
        "ai_provider": "",
        "ai_model": "",
        "ai_endpoint": "",
        "ai_render_dpi": 220,
        "ai_page_image_format": "png",
        "ai_timeout_sec": 120,
        "detect_columns": True,
        "extract_tables": True,
        "remove_headers_footers": True,
        "merge_hyphenated_words": True,
        "mark_formula_candidates": True,
        "ocr_enabled": False,
        "ocr_dpi": 220,
        "ocr_languages": "eng+rus",
        "min_text_chars": 300,
        "max_page_chars": 60000,
    },
    "qwen": {
        "markdown_enabled": True,
        "ru_analysis_enabled": True,
        "keywords_enabled": True,
        "request_timeout_seconds": settings.QWEN_QUEUE_TIMEOUT,
        "model": settings.QWEN_MODEL,
        "token_configured": bool(settings.QWEN_TOKEN),
    },
}



def _setting_value(name: str, default: Any) -> Any:
    """Read a runtime setting without making Settings import fragile.

    Some worker-related values are primarily used by Windows .bat scripts. Older
    config.py versions may not declare them as pydantic fields, while .env still
    contains the keys. Admin settings must stay read-only and must not crash the
    whole backend/worker import because of a missing optional display field.
    """
    if hasattr(settings, name):
        return getattr(settings, name)

    raw = os.getenv(name)
    if raw is None:
        return default

    if isinstance(default, bool):
        return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
    if isinstance(default, int):
        try:
            return int(raw)
        except ValueError:
            return default
    if isinstance(default, float):
        try:
            return float(raw)
        except ValueError:
            return default
    return raw

def _runtime_schema() -> dict[str, Any]:
    return {
        "sections": [
            {"key": "parser", "title": "Парсер", "editable": True},
            {"key": "pdf_markdown", "title": "PDF / Markdown", "editable": True},
            {"key": "qwen", "title": "Qwen / AI", "editable": True},
            {"key": "workers", "title": "Очереди и воркеры", "editable": False},
            {"key": "system", "title": "Система", "editable": False},
        ],
        "available_sources": PARSER_SOURCES,
        "readonly": {
            "workers": {
                "celery_queue": "celery",
                "content_queue": settings.CONTENT_QUEUE_NAME,
                "qwen_queue": settings.QWEN_QUEUE_NAME,
                "redis_broker": settings.CELERY_BROKER_URL,
                "redis_result_backend": settings.CELERY_RESULT_BACKEND,
                "regular_workers": _setting_value("CELERY_WORKERS", 1),
                "content_workers": _setting_value("CONTENT_WORKERS", 1),
                "qwen_workers": _setting_value("QWEN_QUEUE_WORKERS", 1),
                "worker_pool": _setting_value("WORKER_POOL", "threads"),
                "content_pool": _setting_value("CONTENT_WORKER_POOL", "threads"),
                "qwen_pool": _setting_value("QWEN_WORKER_POOL", "threads"),
                "worker_concurrency": _setting_value("WORKER_CONCURRENCY", 5),
                "content_concurrency": _setting_value("CONTENT_WORKER_CONCURRENCY", 5),
                "qwen_concurrency": _setting_value("QWEN_WORKER_CONCURRENCY", 5),
                "requires_restart": True,
            },
            "system": {
                "debug": settings.DEBUG,
                "api_host": settings.API_HOST,
                "api_port": settings.API_PORT,
                "chroma_db_path": settings.CHROMA_DB_PATH,
                "embedding_model": settings.EMBEDDING_MODEL,
                "embedding_dim": settings.EMBEDDING_DIM,
                "qwen_service_url": f"http://{settings.QWEN_SERVICE_HOST}:{settings.QWEN_SERVICE_PORT}",
                "qwen_token_configured": bool(settings.QWEN_TOKEN),
                "secrets_note": "Секреты и токены не редактируются из UI и остаются только в .env.",
            },
        },
    }


SETTINGS_SCHEMA: dict[str, Any] = _runtime_schema()


def get_settings_schema() -> dict[str, Any]:
    """Return runtime schema/read-only values refreshed from current env settings."""
    return _runtime_schema()


def deep_merge(default: Any, override: Any) -> Any:
    """Merge user settings over defaults while preserving only known nested keys."""
    if isinstance(default, dict) and isinstance(override, Mapping):
        merged = {key: copy.deepcopy(value) for key, value in default.items()}
        for key, value in override.items():
            if key in merged:
                merged[key] = deep_merge(merged[key], value)
        return merged
    return copy.deepcopy(override if override is not None else default)


def _to_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "да"}
    if value is None:
        return default
    return bool(value)


def sanitize_section(section: str, value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and clamp editable settings before saving/using."""
    if section not in DEFAULT_SYSTEM_SETTINGS:
        raise ValueError(f"Unknown settings section: {section}")

    merged = deep_merge(DEFAULT_SYSTEM_SETTINGS[section], value)

    if section == "parser":
        merged["enabled"] = _to_bool(merged.get("enabled"), True)
        merged["default_limit"] = _to_int(merged.get("default_limit"), 10, minimum=1, maximum=500)
        merged["max_limit"] = _to_int(merged.get("max_limit"), 100, minimum=1, maximum=5000)
        if merged["default_limit"] > merged["max_limit"]:
            merged["default_limit"] = merged["max_limit"]
        merged["subprocess_timeout_seconds"] = _to_int(
            merged.get("subprocess_timeout_seconds"), 300, minimum=30, maximum=7200
        )
        merged["retry_count"] = _to_int(merged.get("retry_count"), 1, minimum=0, maximum=10)
        merged["retry_delay_seconds"] = _to_int(merged.get("retry_delay_seconds"), 5, minimum=0, maximum=600)
        merged["max_parallel_parse_jobs"] = _to_int(
            merged.get("max_parallel_parse_jobs"), 1, minimum=1, maximum=20
        )

        enabled_sources = merged.get("enabled_sources") or {}
        merged["enabled_sources"] = {
            source: _to_bool(enabled_sources.get(source), True) for source in PARSER_SOURCES
        }
        source_limits = merged.get("source_limits") or {}
        merged["source_limits"] = {
            source: _to_int(source_limits.get(source), merged["default_limit"], minimum=1, maximum=merged["max_limit"])
            for source in PARSER_SOURCES
        }
        postprocess = merged.get("postprocess") or {}
        merged["postprocess"] = {
            "download_pdf": _to_bool(postprocess.get("download_pdf"), True),
            "extract_pdf_text": _to_bool(postprocess.get("extract_pdf_text"), True),
            "qwen_markdown": _to_bool(postprocess.get("qwen_markdown"), True),
            "qwen_ru_analysis": _to_bool(postprocess.get("qwen_ru_analysis"), True),
            "qwen_keywords": _to_bool(postprocess.get("qwen_keywords"), True),
            "embedding": _to_bool(postprocess.get("embedding"), True),
        }

    elif section == "pdf_markdown":
        merged["pages_per_request"] = _to_int(merged.get("pages_per_request"), 1, minimum=1, maximum=10)
        merged["page_chars"] = _to_int(merged.get("page_chars"), 14000, minimum=1000, maximum=60000)
        merged["save_raw_parts"] = _to_bool(merged.get("save_raw_parts"), True)
        merged["save_markdown_parts"] = _to_bool(merged.get("save_markdown_parts"), True)
        merged["normalize_math"] = _to_bool(merged.get("normalize_math"), True)
        merged["show_extraction_diagnostics"] = _to_bool(
            merged.get("show_extraction_diagnostics"), True
        )
        parser_mode = str(merged.get("parser_mode") or "auto").strip().lower()
        merged["parser_mode"] = parser_mode if parser_mode in {"auto", "ai"} else "auto"

        ocr_mode = str(merged.get("ocr_mode") or "auto").strip().lower()
        merged["ocr_mode"] = ocr_mode if ocr_mode in {"auto", "force", "off"} else "auto"

        ai_mode = str(merged.get("ai_mode") or ("force" if merged["parser_mode"] == "ai" else "off")).strip().lower()
        merged["ai_mode"] = ai_mode if ai_mode in {"off", "auto", "force"} else ("force" if merged["parser_mode"] == "ai" else "off")

        force_strategy = str(merged.get("force_strategy") or "").strip().lower()
        merged["force_strategy"] = force_strategy if force_strategy in {"", "simple", "layout", "columns", "ocr", "ai"} else ""

        mode = str(merged.get("extraction_mode") or "auto").strip().lower()
        merged["extraction_mode"] = mode if mode in {"auto", "layout", "columns", "simple", "ocr", "ai"} else "auto"
        if merged["extraction_mode"] in {"layout", "columns", "simple", "ocr", "ai"} and not merged["force_strategy"]:
            merged["force_strategy"] = merged["extraction_mode"]
        if merged["force_strategy"] == "ai":
            merged["parser_mode"] = "ai"
            merged["ai_mode"] = "force"
        if merged["force_strategy"] == "ocr":
            merged["ocr_mode"] = "force"

        merged["ocr_engine"] = str(merged.get("ocr_engine") or "auto").strip().lower() or "auto"
        merged["ai_provider"] = str(merged.get("ai_provider") or "").strip()
        merged["ai_model"] = str(merged.get("ai_model") or "").strip()
        merged["ai_endpoint"] = str(merged.get("ai_endpoint") or "").strip()
        merged["ai_render_dpi"] = _to_int(merged.get("ai_render_dpi"), 220, minimum=120, maximum=500)
        image_format = str(merged.get("ai_page_image_format") or "png").strip().lower()
        merged["ai_page_image_format"] = image_format if image_format in {"png", "jpeg", "jpg", "webp"} else "png"
        merged["ai_timeout_sec"] = _to_int(merged.get("ai_timeout_sec"), 120, minimum=5, maximum=1800)

        merged["detect_columns"] = _to_bool(merged.get("detect_columns"), True)
        merged["extract_tables"] = _to_bool(merged.get("extract_tables"), True)
        merged["remove_headers_footers"] = _to_bool(merged.get("remove_headers_footers"), True)
        merged["merge_hyphenated_words"] = _to_bool(merged.get("merge_hyphenated_words"), True)
        merged["mark_formula_candidates"] = _to_bool(merged.get("mark_formula_candidates"), True)
        merged["ocr_enabled"] = merged["ocr_mode"] != "off"
        merged["ocr_dpi"] = _to_int(merged.get("ocr_dpi"), 220, minimum=120, maximum=400)
        merged["ocr_languages"] = str(merged.get("ocr_languages") or "eng+rus").strip() or "eng+rus"
        merged["min_text_chars"] = _to_int(merged.get("min_text_chars"), 300, minimum=0, maximum=10000)
        merged["max_page_chars"] = _to_int(merged.get("max_page_chars"), 60000, minimum=5000, maximum=250000)

    elif section == "qwen":
        merged["markdown_enabled"] = _to_bool(merged.get("markdown_enabled"), True)
        merged["ru_analysis_enabled"] = _to_bool(merged.get("ru_analysis_enabled"), True)
        merged["keywords_enabled"] = _to_bool(merged.get("keywords_enabled"), True)
        merged["request_timeout_seconds"] = _to_int(
            merged.get("request_timeout_seconds"), int(settings.QWEN_QUEUE_TIMEOUT), minimum=30, maximum=1800
        )
        merged["model"] = str(merged.get("model") or settings.QWEN_MODEL).strip() or settings.QWEN_MODEL

        merged["token_configured"] = bool(settings.QWEN_TOKEN)

    return merged


class SystemSettingsService:
    """CRUD helper for global settings."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> dict[str, Any]:
        result = await self.db.execute(select(SystemSetting))
        rows = result.scalars().all()
        stored: dict[str, dict[str, Any]] = {}
        for row in rows:
            stored.setdefault(row.section, {})[row.key] = row.value_json

        data: dict[str, Any] = {}
        for section, defaults in DEFAULT_SYSTEM_SETTINGS.items():
            section_override = stored.get(section, {}).get("config")
            data[section] = sanitize_section(section, deep_merge(defaults, section_override or {}))
        return data

    async def get_section(self, section: str) -> dict[str, Any]:
        if section not in DEFAULT_SYSTEM_SETTINGS:
            raise ValueError(f"Unknown settings section: {section}")
        result = await self.db.execute(
            select(SystemSetting).where(SystemSetting.section == section, SystemSetting.key == "config")
        )
        row = result.scalar_one_or_none()
        value = row.value_json if row is not None else {}
        return sanitize_section(section, value or {})

    async def update_section(
        self,
        section: str,
        value: Mapping[str, Any],
        *,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        sanitized = sanitize_section(section, value)
        result = await self.db.execute(
            select(SystemSetting).where(SystemSetting.section == section, SystemSetting.key == "config")
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = SystemSetting(
                section=section,
                key="config",
                value_json=sanitized,
                value_type="json",
                title=section,
                description=f"Global {section} settings",
                is_public=False,
                requires_restart=False,
                updated_by=updated_by,
            )
            self.db.add(row)
        else:
            row.value_json = sanitized
            row.updated_by = updated_by
        await self.db.commit()
        await self.db.refresh(row)
        return sanitized

    async def reset_section(self, section: str, *, updated_by: str | None = None) -> dict[str, Any]:
        if section not in DEFAULT_SYSTEM_SETTINGS:
            raise ValueError(f"Unknown settings section: {section}")
        defaults = sanitize_section(section, DEFAULT_SYSTEM_SETTINGS[section])
        return await self.update_section(section, defaults, updated_by=updated_by)

    async def get_parser_settings(self) -> dict[str, Any]:
        return await self.get_section("parser")

    async def get_postprocess_settings(self) -> dict[str, bool]:
        parser = await self.get_parser_settings()
        return parser.get("postprocess") or DEFAULT_SYSTEM_SETTINGS["parser"]["postprocess"]

    async def get_pdf_markdown_settings(self) -> dict[str, Any]:
        return await self.get_section("pdf_markdown")

    async def get_qwen_settings(self) -> dict[str, Any]:
        return await self.get_section("qwen")


async def get_parser_settings_safe(db: AsyncSession | None = None) -> dict[str, Any]:
    """Load parser settings or return sanitized defaults on DB startup/errors."""
    if db is not None:
        try:
            return await SystemSettingsService(db).get_parser_settings()
        except Exception as exc:
            logger.warning("Failed to load parser settings, using defaults: {}", exc)
            return sanitize_section("parser", {})
    from app.db.session import async_session_maker

    try:
        async with async_session_maker() as session:
            return await SystemSettingsService(session).get_parser_settings()
    except Exception as exc:
        logger.warning("Failed to load parser settings, using defaults: {}", exc)
        return sanitize_section("parser", {})


async def get_postprocess_settings_safe(db: AsyncSession | None = None) -> dict[str, bool]:
    parser = await get_parser_settings_safe(db)
    return parser.get("postprocess") or sanitize_section("parser", {}).get("postprocess", {})


async def get_pdf_markdown_settings_safe(db: AsyncSession | None = None) -> dict[str, Any]:
    if db is not None:
        try:
            return await SystemSettingsService(db).get_pdf_markdown_settings()
        except Exception as exc:
            logger.warning("Failed to load PDF/Markdown settings, using defaults: {}", exc)
            return sanitize_section("pdf_markdown", {})
    from app.db.session import async_session_maker

    try:
        async with async_session_maker() as session:
            return await SystemSettingsService(session).get_pdf_markdown_settings()
    except Exception as exc:
        logger.warning("Failed to load PDF/Markdown settings, using defaults: {}", exc)
        return sanitize_section("pdf_markdown", {})


async def get_qwen_settings_safe(db: AsyncSession | None = None) -> dict[str, Any]:
    if db is not None:
        try:
            return await SystemSettingsService(db).get_qwen_settings()
        except Exception as exc:
            logger.warning("Failed to load Qwen settings, using defaults: {}", exc)
            return sanitize_section("qwen", {})
    from app.db.session import async_session_maker

    try:
        async with async_session_maker() as session:
            return await SystemSettingsService(session).get_qwen_settings()
    except Exception as exc:
        logger.warning("Failed to load Qwen settings, using defaults: {}", exc)
        return sanitize_section("qwen", {})
