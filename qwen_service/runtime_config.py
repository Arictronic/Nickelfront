"""Runtime config persistence helpers for the standalone Qwen service.

This module intentionally stays framework-free: it knows how to persist the
mutable Qwen runtime config into .env and how to mirror selected values into
``os.environ`` for already-created QwenAPI clients. It does not import FastAPI,
QwenAPI, or service runtime state.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dotenv import set_key





_PERSISTED_CONFIG_KEYS: tuple[tuple[str, str, Any, bool], ...] = (
    ("token", "QWEN_TOKEN", "", False),
    ("cookie", "QWEN_COOKIE", "", False),
    ("bx_ua", "QWEN_BX_UA", "", False),
    ("bx_umidtoken", "QWEN_BX_UMIDTOKEN", "", False),
    ("bx_v", "QWEN_BX_V", "", False),
    ("api_key", "QWEN_API_KEY", "", False),
    ("model", "QWEN_MODEL", "qwen3.6-plus", False),
    ("user_agent", "QWEN_USER_AGENT", "", False),
    ("file_upload_mode", "QWEN_FILE_UPLOAD_MODE", "auto", False),
    ("file_metadata_cache_path", "QWEN_FILE_METADATA_CACHE_PATH", "logs/runtime/qwen/qwen_uploaded_files.json", False),
    ("file_metadata_cache_max_entries", "QWEN_FILE_METADATA_CACHE_MAX_ENTRIES", 500, False),
    ("file_metadata_cache_max_age_days", "QWEN_FILE_METADATA_CACHE_MAX_AGE_DAYS", 7, False),
    ("session_registry_cache_path", "QWEN_SESSION_REGISTRY_CACHE_PATH", "logs/runtime/qwen/qwen_sessions.json", False),
    ("session_registry_cache_max_entries", "QWEN_SESSION_REGISTRY_CACHE_MAX_ENTRIES", 500, False),
    ("session_registry_cache_max_age_days", "QWEN_SESSION_REGISTRY_CACHE_MAX_AGE_DAYS", 30, False),
    ("session_source", "QWEN_SESSION_SOURCE", "har", False),
    ("playwright_enabled", "QWEN_PLAYWRIGHT_ENABLED", False, True),
    ("browser_login_automation", "QWEN_BROWSER_LOGIN_AUTOMATION", False, True),
    ("browser_profile_dir", "QWEN_BROWSER_PROFILE_DIR", "qwen_service/.browser/qwen", False),
    ("browser_headless", "QWEN_BROWSER_HEADLESS", False, True),
    ("browser_channel", "QWEN_BROWSER_CHANNEL", "chrome", False),
    ("browser_refresh_timeout_sec", "QWEN_BROWSER_REFRESH_TIMEOUT_SEC", 120.0, False),
    ("cdp_url", "QWEN_CDP_URL", "http://127.0.0.1:9222", False),
    ("har_dir", "QWEN_HAR_DIR", "qwen_service/har", False),
    ("file_api_extra_headers_json", "QWEN_FILE_API_EXTRA_HEADERS_JSON", "", False),
    ("file_sts_payload_template_json", "QWEN_FILE_STS_PAYLOAD_TEMPLATE_JSON", "", False),
    ("file_sts_url", "QWEN_FILE_STS_URL", "", False),
    ("file_parse_payload_template_json", "QWEN_FILE_PARSE_PAYLOAD_TEMPLATE_JSON", "", False),
    ("file_parse_url", "QWEN_FILE_PARSE_URL", "", False),
    ("file_parse_status_payload_template_json", "QWEN_FILE_PARSE_STATUS_PAYLOAD_TEMPLATE_JSON", "", False),
    ("file_parse_status_url", "QWEN_FILE_PARSE_STATUS_URL", "", False),
    ("oss_put_headers_template_json", "QWEN_OSS_PUT_HEADERS_TEMPLATE_JSON", "", False),
    ("oss_put_mode", "QWEN_OSS_PUT_MODE", "minimal", False),
    ("thinking_enabled", "QWEN_THINKING_ENABLED", True, True),
    ("search_enabled", "QWEN_SEARCH_ENABLED", True, True),
    ("auto_continue_enabled", "QWEN_AUTO_CONTINUE_ENABLED", True, True),
    ("max_continues", "QWEN_MAX_CONTINUES", 5, False),
    ("stream_retries", "QWEN_STREAM_RETRIES", 2, False),
    ("history_recovery_attempts", "QWEN_HISTORY_RECOVERY_ATTEMPTS", 3, False),
    ("history_recovery_interval_sec", "QWEN_HISTORY_RECOVERY_INTERVAL_SEC", 1.0, False),
    ("max_active_sessions", "QWEN_MAX_ACTIVE_SESSIONS", 50, False),
    ("provider_max_concurrent_requests", "QWEN_PROVIDER_MAX_CONCURRENT_REQUESTS", 10, False),
    ("provider_start_throttle_enabled", "QWEN_PROVIDER_START_THROTTLE_ENABLED", False, True),
    ("provider_start_interval_sec", "QWEN_PROVIDER_START_INTERVAL_SEC", 0.5, False),
    ("provider_start_jitter_sec", "QWEN_PROVIDER_START_JITTER_SEC", 0.25, False),
    ("provider_retry_jitter_enabled", "QWEN_PROVIDER_RETRY_JITTER_ENABLED", False, True),
    ("provider_retry_jitter_min_sec", "QWEN_PROVIDER_RETRY_JITTER_MIN_SEC", 0.25, False),
    ("provider_retry_jitter_max_sec", "QWEN_PROVIDER_RETRY_JITTER_MAX_SEC", 1.25, False),
)

_RUNTIME_ENV_SYNC_KEYS: tuple[tuple[str, str], ...] = (
    ("token", "QWEN_TOKEN"),
    ("cookie", "QWEN_COOKIE"),
    ("bx_ua", "QWEN_BX_UA"),
    ("bx_umidtoken", "QWEN_BX_UMIDTOKEN"),
    ("bx_v", "QWEN_BX_V"),
    ("user_agent", "QWEN_USER_AGENT"),
    ("file_upload_mode", "QWEN_FILE_UPLOAD_MODE"),
    ("file_metadata_cache_path", "QWEN_FILE_METADATA_CACHE_PATH"),
    ("file_metadata_cache_max_entries", "QWEN_FILE_METADATA_CACHE_MAX_ENTRIES"),
    ("file_metadata_cache_max_age_days", "QWEN_FILE_METADATA_CACHE_MAX_AGE_DAYS"),
    ("session_registry_cache_path", "QWEN_SESSION_REGISTRY_CACHE_PATH"),
    ("session_registry_cache_max_entries", "QWEN_SESSION_REGISTRY_CACHE_MAX_ENTRIES"),
    ("session_registry_cache_max_age_days", "QWEN_SESSION_REGISTRY_CACHE_MAX_AGE_DAYS"),
    ("session_source", "QWEN_SESSION_SOURCE"),
    ("playwright_enabled", "QWEN_PLAYWRIGHT_ENABLED"),
    ("browser_login_automation", "QWEN_BROWSER_LOGIN_AUTOMATION"),
    ("browser_profile_dir", "QWEN_BROWSER_PROFILE_DIR"),
    ("browser_headless", "QWEN_BROWSER_HEADLESS"),
    ("browser_channel", "QWEN_BROWSER_CHANNEL"),
    ("browser_refresh_timeout_sec", "QWEN_BROWSER_REFRESH_TIMEOUT_SEC"),
    ("cdp_url", "QWEN_CDP_URL"),
    ("har_dir", "QWEN_HAR_DIR"),
    ("file_api_extra_headers_json", "QWEN_FILE_API_EXTRA_HEADERS_JSON"),
    ("file_sts_payload_template_json", "QWEN_FILE_STS_PAYLOAD_TEMPLATE_JSON"),
    ("file_sts_url", "QWEN_FILE_STS_URL"),
    ("file_parse_payload_template_json", "QWEN_FILE_PARSE_PAYLOAD_TEMPLATE_JSON"),
    ("file_parse_url", "QWEN_FILE_PARSE_URL"),
    ("file_parse_status_payload_template_json", "QWEN_FILE_PARSE_STATUS_PAYLOAD_TEMPLATE_JSON"),
    ("file_parse_status_url", "QWEN_FILE_PARSE_STATUS_URL"),
    ("oss_put_headers_template_json", "QWEN_OSS_PUT_HEADERS_TEMPLATE_JSON"),
    ("oss_put_mode", "QWEN_OSS_PUT_MODE"),
)


def _format_env_value(value: Any, *, lower_bool: bool = False) -> str:
    if lower_bool:
        return str(bool(value)).lower()
    return str(value if value is not None else "")


def persist_runtime_config(current_config: Mapping[str, Any], *, env_path: str | Path) -> None:
    """Persist mutable runtime config values into the project .env file."""
    target = Path(env_path)
    if not target.exists():
        target.touch()

    target_str = str(target)
    for key, env_name, default, lower_bool in _PERSISTED_CONFIG_KEYS:
        value = current_config.get(key, default)
        set_key(target_str, env_name, _format_env_value(value, lower_bool=lower_bool))


def sync_runtime_env_from_config(current_config: Mapping[str, Any]) -> None:
    """Mirror runtime config into os.environ for already-created provider clients."""
    for key, env_name in _RUNTIME_ENV_SYNC_KEYS:
        os.environ[env_name] = str(current_config.get(key, "") or "")
