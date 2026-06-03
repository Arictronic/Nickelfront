"""Pydantic request/response models for the standalone Qwen service.

This module intentionally keeps the FastAPI schema classes away from
``service.py`` so the service module can focus on runtime orchestration.
Defaults match the legacy environment-based defaults that used to live next
to the route handlers.
"""

try:
    from .defaults import (
        DEFAULT_AUTO_CONTINUE_ENABLED,
        DEFAULT_MAX_CONTINUES,
        DEFAULT_MODEL,
        DEFAULT_FILE_METADATA_CACHE_MAX_AGE_DAYS,
        DEFAULT_SESSION_REGISTRY_CACHE_MAX_AGE_DAYS,
        DEFAULT_SEARCH_ENABLED,
        DEFAULT_THINKING_ENABLED,
    )
except ImportError:  # pragma: no cover - supports direct script imports
    from defaults import (
        DEFAULT_AUTO_CONTINUE_ENABLED,
        DEFAULT_MAX_CONTINUES,
        DEFAULT_MODEL,
        DEFAULT_FILE_METADATA_CACHE_MAX_AGE_DAYS,
        DEFAULT_SESSION_REGISTRY_CACHE_MAX_AGE_DAYS,
        DEFAULT_SEARCH_ENABLED,
        DEFAULT_THINKING_ENABLED,
    )

from pydantic import BaseModel, Field, field_validator


class ChatSession(BaseModel):
    session_id: str
    title: str = "Новый чат"


class CreateSessionRequest(BaseModel):
    title: str | None = None


class SendMessageRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    thinking_enabled: bool = DEFAULT_THINKING_ENABLED
    search_enabled: bool = DEFAULT_SEARCH_ENABLED
    file_ids: list[str] = Field(default_factory=list)
    auto_continue: bool | None = None

    @field_validator("session_id", "message", mode="before")
    @classmethod
    def _strip_required_text(cls, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("field must not be empty")
        return text

    @field_validator("file_ids", mode="before")
    @classmethod
    def _normalize_file_ids(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("file_ids must be a list")
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            fid = str(item or "").strip()
            if not fid or fid in seen:
                continue
            seen.add(fid)
            normalized.append(fid)
        return normalized


class FileMessageRequest(BaseModel):
    file_path: str = ""
    file_paths: list[str] = Field(default_factory=list)
    message: str = ""
    session_id: str | None = None
    thinking_enabled: bool = DEFAULT_THINKING_ENABLED
    search_enabled: bool = DEFAULT_SEARCH_ENABLED
    auto_continue: bool | None = None
    session_prompt: str = ""

    @field_validator("file_path", "message", "session_prompt", mode="before")
    @classmethod
    def _strip_optional_text(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("session_id", mode="before")
    @classmethod
    def _strip_optional_session_id(cls, value: object) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("file_paths", mode="before")
    @classmethod
    def _normalize_file_paths(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("file_paths must be a list")
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            path = str(item or "").strip()
            key = path.lower()
            if not path or key in seen:
                continue
            seen.add(key)
            normalized.append(path)
        return normalized


class ContinueMessageRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    message_id: int = Field(..., ge=1)
    thinking_enabled: bool = DEFAULT_THINKING_ENABLED

    @field_validator("session_id", mode="before")
    @classmethod
    def _strip_session_id(cls, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("session_id must not be empty")
        return text


class ModelConfig(BaseModel):
    model: str = DEFAULT_MODEL
    thinking_enabled: bool = DEFAULT_THINKING_ENABLED
    search_enabled: bool = DEFAULT_SEARCH_ENABLED
    auto_continue_enabled: bool = DEFAULT_AUTO_CONTINUE_ENABLED
    max_continues: int = DEFAULT_MAX_CONTINUES


class RuntimeConfigUpdate(BaseModel):
    model: str | None = None
    thinking_enabled: bool | None = None
    search_enabled: bool | None = None
    file_upload_mode: str | None = None
    session_source: str | None = None
    playwright_enabled: bool | None = None
    browser_login_automation: bool | None = None
    browser_profile_dir: str | None = None
    browser_headless: bool | None = None
    browser_channel: str | None = None
    browser_refresh_timeout_sec: float | None = None
    cdp_url: str | None = None
    har_dir: str | None = None
    auto_continue_enabled: bool | None = None
    max_continues: int | None = None
    stream_retries: int | None = None
    history_recovery_attempts: int | None = None
    history_recovery_interval_sec: float | None = None
    file_metadata_cache_max_age_days: int | None = None
    session_registry_cache_max_age_days: int | None = None
    provider_start_throttle_enabled: bool | None = None
    provider_start_interval_sec: float | None = None
    provider_start_jitter_sec: float | None = None
    provider_retry_jitter_enabled: bool | None = None
    provider_retry_jitter_min_sec: float | None = None
    provider_retry_jitter_max_sec: float | None = None


class CacheMaintenanceRequest(BaseModel):
    """Provider-safe maintenance request for local qwen_service runtime caches."""

    dry_run: bool = True
    prune_file_metadata: bool = True
    prune_session_registry: bool = True
    file_max_age_days: int | None = Field(DEFAULT_FILE_METADATA_CACHE_MAX_AGE_DAYS, ge=1, le=3650)
    session_max_age_days: int | None = Field(DEFAULT_SESSION_REGISTRY_CACHE_MAX_AGE_DAYS, ge=1, le=3650)
    clear_file_metadata: bool = False
    clear_session_registry: bool = False



class TokenConfig(BaseModel):
    token: str


class QwenSessionHeadersConfig(BaseModel):
    token: str | None = None
    cookie: str | None = None
    bx_ua: str | None = None
    bx_umidtoken: str | None = None
    bx_v: str | None = None
    user_agent: str | None = None
    file_api_extra_headers_json: str | None = None
    file_sts_payload_template_json: str | None = None
    file_sts_url: str | None = None
    file_parse_payload_template_json: str | None = None
    file_parse_url: str | None = None
    file_parse_status_payload_template_json: str | None = None
    file_parse_status_url: str | None = None
    oss_put_headers_template_json: str | None = None
    source: str | None = "manual"
    clear_missing: bool = False


class HarFileImportRequest(BaseModel):
    filename: str | None = None


class APIKeyConfig(BaseModel):
    api_key: str = Field(..., min_length=8)

    @field_validator("api_key", mode="before")
    @classmethod
    def _strip_api_key(cls, value: object) -> str:
        text = str(value or "").strip()
        if len(text) < 8:
            raise ValueError("api_key must contain at least 8 characters")
        return text
