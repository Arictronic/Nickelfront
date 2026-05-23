"""Service for global technical settings stored in DB."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

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

SETTINGS_SCHEMA: dict[str, Any] = {
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
            "content_workers": settings.CONTENT_WORKERS,
            "qwen_workers": settings.QWEN_QUEUE_WORKERS,
            "content_pool": settings.CONTENT_WORKER_POOL,
            "content_concurrency": settings.CONTENT_WORKER_CONCURRENCY,
            "requires_restart": True,
        },
        "system": {
            "debug": settings.DEBUG,
            "api_host": settings.API_HOST,
            "api_port": settings.API_PORT,
            "chroma_db_path": settings.CHROMA_DB_PATH,
            "embedding_model": settings.EMBEDDING_MODEL,
            "qwen_service_url": f"http://{settings.QWEN_SERVICE_HOST}:{settings.QWEN_SERVICE_PORT}",
            "secrets_note": "Секреты и токены не редактируются из UI и остаются только в .env.",
        },
    },
}


def deep_merge(default: Any, override: Any) -> Any:
    """Merge user settings over defaults while preserving unknown nested keys safely."""
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
    """Validate and clamp editable settings before saving."""
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

    elif section == "qwen":
        # Do not accept or expose tokens here.
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
        await self.db.flush()
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
