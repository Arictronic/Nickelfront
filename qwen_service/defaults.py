"""Environment-derived defaults for the standalone Qwen service.

This module is intentionally runtime-light: it only reads environment variables
and exposes immutable default constants plus small builders.  FastAPI schemas,
service runtime and config payloads should import defaults from here instead of
redefining their own values.
"""

from __future__ import annotations

import os
from typing import Any

try:
    from .env_utils import env_bool, env_float, env_int
except ImportError:  # pragma: no cover - supports direct script imports
    from env_utils import env_bool, env_float, env_int


DEFAULT_HOST = os.getenv("QWEN_SERVICE_HOST", "127.0.0.1")
DEFAULT_PORT = env_int("QWEN_SERVICE_PORT", 8767, min_value=1, max_value=65535)
DEFAULT_MODEL = (os.getenv("QWEN_MODEL", "qwen3.6-plus") or "qwen3.6-plus").strip() or "qwen3.6-plus"
DEFAULT_USER_AGENT = (os.getenv("QWEN_USER_AGENT", "") or "").strip()
DEFAULT_THINKING_ENABLED = env_bool("QWEN_THINKING_ENABLED", True)
DEFAULT_SEARCH_ENABLED = env_bool("QWEN_SEARCH_ENABLED", True)
DEFAULT_AUTO_CONTINUE_ENABLED = env_bool("QWEN_AUTO_CONTINUE_ENABLED", True)
DEFAULT_MAX_CONTINUES = env_int("QWEN_MAX_CONTINUES", 5, min_value=1, max_value=20)
DEFAULT_STREAM_RETRIES = env_int("QWEN_STREAM_RETRIES", 2, min_value=0, max_value=10)
DEFAULT_HISTORY_RECOVERY_ATTEMPTS = env_int("QWEN_HISTORY_RECOVERY_ATTEMPTS", 3, min_value=1, max_value=60)
DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC = env_float(
    "QWEN_HISTORY_RECOVERY_INTERVAL_SEC",
    1.0,
    min_value=0.2,
    max_value=30.0,
)
DEFAULT_MAX_ACTIVE_SESSIONS = env_int("QWEN_MAX_ACTIVE_SESSIONS", 50, min_value=1, max_value=500)
DEFAULT_PROVIDER_MAX_CONCURRENT_REQUESTS = env_int(
    "QWEN_PROVIDER_MAX_CONCURRENT_REQUESTS",
    10,
    min_value=1,
    max_value=50,
)
DEFAULT_PROVIDER_SLOT_TIMEOUT_SEC = env_float(
    "QWEN_PROVIDER_SLOT_TIMEOUT_SEC",
    300.0,
    min_value=1.0,
    max_value=1800.0,
)
DEFAULT_PROVIDER_START_THROTTLE_ENABLED = env_bool("QWEN_PROVIDER_START_THROTTLE_ENABLED", False)
DEFAULT_PROVIDER_START_INTERVAL_SEC = env_float(
    "QWEN_PROVIDER_START_INTERVAL_SEC",
    0.50,
    min_value=0.0,
    max_value=10.0,
)
DEFAULT_PROVIDER_START_JITTER_SEC = env_float(
    "QWEN_PROVIDER_START_JITTER_SEC",
    0.25,
    min_value=0.0,
    max_value=10.0,
)
DEFAULT_PROVIDER_RETRY_JITTER_ENABLED = env_bool(
    "QWEN_PROVIDER_RETRY_JITTER_ENABLED",
    DEFAULT_PROVIDER_START_THROTTLE_ENABLED,
)
DEFAULT_PROVIDER_RETRY_JITTER_MIN_SEC = env_float(
    "QWEN_PROVIDER_RETRY_JITTER_MIN_SEC",
    0.25,
    min_value=0.0,
    max_value=30.0,
)
DEFAULT_PROVIDER_RETRY_JITTER_MAX_SEC = env_float(
    "QWEN_PROVIDER_RETRY_JITTER_MAX_SEC",
    1.25,
    min_value=0.0,
    max_value=30.0,
)
DEFAULT_AUTH_STATUS_CACHE_TTL_SEC = env_float(
    "QWEN_AUTH_STATUS_CACHE_TTL_SEC",
    60.0,
    min_value=5.0,
    max_value=600.0,
)
DEFAULT_FILE_UPLOAD_MODE = (os.getenv("QWEN_FILE_UPLOAD_MODE", "auto") or "auto").strip().lower() or "auto"
DEFAULT_FILE_UPLOAD_MAX_SIZE_MB = env_int("QWEN_FILE_UPLOAD_MAX_SIZE_MB", 20, min_value=1, max_value=100)
DEFAULT_FILE_UPLOAD_MAX_FILES = env_int("QWEN_FILE_UPLOAD_MAX_FILES", 5, min_value=1, max_value=5)
DEFAULT_FILE_METADATA_CACHE_PATH = (
    os.getenv("QWEN_FILE_METADATA_CACHE_PATH", "runtime/qwen_uploaded_files.json") or "runtime/qwen_uploaded_files.json"
).strip()
DEFAULT_FILE_METADATA_CACHE_MAX_ENTRIES = env_int("QWEN_FILE_METADATA_CACHE_MAX_ENTRIES", 500, min_value=10, max_value=5000)
DEFAULT_FILE_METADATA_CACHE_MAX_AGE_DAYS = env_int("QWEN_FILE_METADATA_CACHE_MAX_AGE_DAYS", 7, min_value=1, max_value=3650)
DEFAULT_SESSION_REGISTRY_CACHE_PATH = (
    os.getenv("QWEN_SESSION_REGISTRY_CACHE_PATH", "runtime/qwen_sessions.json") or "runtime/qwen_sessions.json"
).strip()
DEFAULT_SESSION_REGISTRY_CACHE_MAX_ENTRIES = env_int(
    "QWEN_SESSION_REGISTRY_CACHE_MAX_ENTRIES", 500, min_value=10, max_value=5000
)
DEFAULT_SESSION_REGISTRY_CACHE_MAX_AGE_DAYS = env_int(
    "QWEN_SESSION_REGISTRY_CACHE_MAX_AGE_DAYS", 30, min_value=1, max_value=3650
)
DEFAULT_EVENT_JOURNAL_PATH = (
    os.getenv("QWEN_EVENT_JOURNAL_PATH", "runtime/qwen_events.json") or "runtime/qwen_events.json"
).strip()
DEFAULT_EVENT_JOURNAL_MAX_ENTRIES = env_int(
    "QWEN_EVENT_JOURNAL_MAX_ENTRIES", 500, min_value=10, max_value=5000
)
DEFAULT_SESSION_SOURCE = (os.getenv("QWEN_SESSION_SOURCE", "har") or "har").strip().lower() or "har"
DEFAULT_PLAYWRIGHT_ENABLED = env_bool("QWEN_PLAYWRIGHT_ENABLED", False)
DEFAULT_BROWSER_LOGIN_AUTOMATION = env_bool("QWEN_BROWSER_LOGIN_AUTOMATION", False)
DEFAULT_BROWSER_PROFILE_DIR = (
    os.getenv("QWEN_BROWSER_PROFILE_DIR", "qwen_service/.browser/qwen") or "qwen_service/.browser/qwen"
).strip()
DEFAULT_BROWSER_HEADLESS = env_bool("QWEN_BROWSER_HEADLESS", False)
DEFAULT_BROWSER_CHANNEL = (os.getenv("QWEN_BROWSER_CHANNEL", "chrome") or "chrome").strip()
DEFAULT_BROWSER_REFRESH_TIMEOUT_SEC = env_float(
    "QWEN_BROWSER_REFRESH_TIMEOUT_SEC",
    120.0,
    min_value=10.0,
    max_value=600.0,
)
DEFAULT_CDP_URL = (os.getenv("QWEN_CDP_URL", "http://127.0.0.1:9222") or "http://127.0.0.1:9222").strip()
DEFAULT_HAR_DIR = (os.getenv("QWEN_HAR_DIR", "qwen_service/har") or "qwen_service/har").strip()
DEFAULT_FILE_API_EXTRA_HEADERS_JSON = (os.getenv("QWEN_FILE_API_EXTRA_HEADERS_JSON", "") or "").strip()
DEFAULT_FILE_STS_PAYLOAD_TEMPLATE_JSON = (os.getenv("QWEN_FILE_STS_PAYLOAD_TEMPLATE_JSON", "") or "").strip()
DEFAULT_FILE_STS_URL = (os.getenv("QWEN_FILE_STS_URL", "") or "").strip()
DEFAULT_FILE_PARSE_PAYLOAD_TEMPLATE_JSON = (os.getenv("QWEN_FILE_PARSE_PAYLOAD_TEMPLATE_JSON", "") or "").strip()
DEFAULT_FILE_PARSE_URL = (os.getenv("QWEN_FILE_PARSE_URL", "") or "").strip()
DEFAULT_FILE_PARSE_STATUS_PAYLOAD_TEMPLATE_JSON = (
    os.getenv("QWEN_FILE_PARSE_STATUS_PAYLOAD_TEMPLATE_JSON", "") or ""
).strip()
DEFAULT_FILE_PARSE_STATUS_URL = (os.getenv("QWEN_FILE_PARSE_STATUS_URL", "") or "").strip()
DEFAULT_OSS_PUT_HEADERS_TEMPLATE_JSON = (os.getenv("QWEN_OSS_PUT_HEADERS_TEMPLATE_JSON", "") or "").strip()
DEFAULT_OSS_PUT_MODE = (os.getenv("QWEN_OSS_PUT_MODE", "minimal") or "minimal").strip().lower() or "minimal"
if DEFAULT_OSS_PUT_MODE not in {"minimal", "browser_like", "har"}:
    DEFAULT_OSS_PUT_MODE = "minimal"

# Security/CORS defaults for the local standalone service.  Mutable endpoints
# must not silently become unauthenticated when QWEN_API_KEY is missing; allow
# that only through an explicit developer override.
DEFAULT_ALLOW_UNAUTH_WITHOUT_API_KEY = env_bool("QWEN_ALLOW_UNAUTH_WITHOUT_API_KEY", False)
DEFAULT_CORS_ORIGINS = (
    os.getenv(
        "QWEN_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8001,http://127.0.0.1:8001",
    )
    or ""
).strip()


def runtime_config_defaults() -> dict[str, Any]:
    """Return default values used by runtime config and public schemas."""
    return {
        "model": DEFAULT_MODEL,
        "thinking_enabled": DEFAULT_THINKING_ENABLED,
        "search_enabled": DEFAULT_SEARCH_ENABLED,
        "auto_continue_enabled": DEFAULT_AUTO_CONTINUE_ENABLED,
        "max_continues": DEFAULT_MAX_CONTINUES,
        "stream_retries": DEFAULT_STREAM_RETRIES,
        "history_recovery_attempts": DEFAULT_HISTORY_RECOVERY_ATTEMPTS,
        "history_recovery_interval_sec": DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC,
        "file_upload_mode": DEFAULT_FILE_UPLOAD_MODE,
        "file_upload_max_size_mb": DEFAULT_FILE_UPLOAD_MAX_SIZE_MB,
        "file_upload_max_files": DEFAULT_FILE_UPLOAD_MAX_FILES,
        "file_metadata_cache_path": DEFAULT_FILE_METADATA_CACHE_PATH,
        "file_metadata_cache_max_entries": DEFAULT_FILE_METADATA_CACHE_MAX_ENTRIES,
        "file_metadata_cache_max_age_days": DEFAULT_FILE_METADATA_CACHE_MAX_AGE_DAYS,
        "session_registry_cache_path": DEFAULT_SESSION_REGISTRY_CACHE_PATH,
        "session_registry_cache_max_entries": DEFAULT_SESSION_REGISTRY_CACHE_MAX_ENTRIES,
        "session_registry_cache_max_age_days": DEFAULT_SESSION_REGISTRY_CACHE_MAX_AGE_DAYS,
        "event_journal_path": DEFAULT_EVENT_JOURNAL_PATH,
        "event_journal_max_entries": DEFAULT_EVENT_JOURNAL_MAX_ENTRIES,
        "session_source": DEFAULT_SESSION_SOURCE,
        "playwright_enabled": DEFAULT_PLAYWRIGHT_ENABLED,
        "browser_login_automation": DEFAULT_BROWSER_LOGIN_AUTOMATION,
        "browser_profile_dir": DEFAULT_BROWSER_PROFILE_DIR,
        "browser_headless": DEFAULT_BROWSER_HEADLESS,
        "browser_channel": DEFAULT_BROWSER_CHANNEL,
        "browser_refresh_timeout_sec": DEFAULT_BROWSER_REFRESH_TIMEOUT_SEC,
        "cdp_url": DEFAULT_CDP_URL,
        "oss_put_mode": DEFAULT_OSS_PUT_MODE,
        "allow_unauth_without_api_key": DEFAULT_ALLOW_UNAUTH_WITHOUT_API_KEY,
        "cors_origins": DEFAULT_CORS_ORIGINS,
    }


def initial_runtime_config() -> dict[str, Any]:
    """Build mutable runtime config from environment-derived defaults and secrets."""
    return {
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "token": (os.getenv("QWEN_TOKEN", "") or "").strip(),
        "cookie": (os.getenv("QWEN_COOKIE", "") or "").strip(),
        "bx_ua": (os.getenv("QWEN_BX_UA", "") or "").strip(),
        "bx_umidtoken": (os.getenv("QWEN_BX_UMIDTOKEN", "") or "").strip(),
        "bx_v": (os.getenv("QWEN_BX_V", "") or "").strip(),
        "api_key": (os.getenv("QWEN_API_KEY", "") or "").strip(),
        "model": DEFAULT_MODEL,
        "user_agent": DEFAULT_USER_AGENT,
        "file_upload_mode": DEFAULT_FILE_UPLOAD_MODE if DEFAULT_FILE_UPLOAD_MODE in {"api", "auto", "browser"} else "auto",
        "file_upload_max_size_mb": DEFAULT_FILE_UPLOAD_MAX_SIZE_MB,
        "file_upload_max_files": DEFAULT_FILE_UPLOAD_MAX_FILES,
        "file_metadata_cache_path": DEFAULT_FILE_METADATA_CACHE_PATH,
        "file_metadata_cache_max_entries": DEFAULT_FILE_METADATA_CACHE_MAX_ENTRIES,
        "file_metadata_cache_max_age_days": DEFAULT_FILE_METADATA_CACHE_MAX_AGE_DAYS,
        "session_registry_cache_path": DEFAULT_SESSION_REGISTRY_CACHE_PATH,
        "session_registry_cache_max_entries": DEFAULT_SESSION_REGISTRY_CACHE_MAX_ENTRIES,
        "session_registry_cache_max_age_days": DEFAULT_SESSION_REGISTRY_CACHE_MAX_AGE_DAYS,
        "event_journal_path": DEFAULT_EVENT_JOURNAL_PATH,
        "event_journal_max_entries": DEFAULT_EVENT_JOURNAL_MAX_ENTRIES,
        "session_source": DEFAULT_SESSION_SOURCE if DEFAULT_SESSION_SOURCE in {"env", "har", "manual", "cdp", "playwright"} else "har",
        "playwright_enabled": DEFAULT_PLAYWRIGHT_ENABLED,
        "browser_login_automation": DEFAULT_BROWSER_LOGIN_AUTOMATION,
        "browser_profile_dir": DEFAULT_BROWSER_PROFILE_DIR,
        "browser_headless": DEFAULT_BROWSER_HEADLESS,
        "browser_channel": DEFAULT_BROWSER_CHANNEL,
        "browser_refresh_timeout_sec": DEFAULT_BROWSER_REFRESH_TIMEOUT_SEC,
        "cdp_url": DEFAULT_CDP_URL,
        "har_dir": DEFAULT_HAR_DIR,
        "file_api_extra_headers_json": DEFAULT_FILE_API_EXTRA_HEADERS_JSON,
        "file_sts_payload_template_json": DEFAULT_FILE_STS_PAYLOAD_TEMPLATE_JSON,
        "file_sts_url": DEFAULT_FILE_STS_URL,
        "file_parse_payload_template_json": DEFAULT_FILE_PARSE_PAYLOAD_TEMPLATE_JSON,
        "file_parse_url": DEFAULT_FILE_PARSE_URL,
        "file_parse_status_payload_template_json": DEFAULT_FILE_PARSE_STATUS_PAYLOAD_TEMPLATE_JSON,
        "file_parse_status_url": DEFAULT_FILE_PARSE_STATUS_URL,
        "oss_put_headers_template_json": DEFAULT_OSS_PUT_HEADERS_TEMPLATE_JSON,
        "oss_put_mode": DEFAULT_OSS_PUT_MODE,
        "allow_unauth_without_api_key": DEFAULT_ALLOW_UNAUTH_WITHOUT_API_KEY,
        "cors_origins": DEFAULT_CORS_ORIGINS,
        "thinking_enabled": DEFAULT_THINKING_ENABLED,
        "search_enabled": DEFAULT_SEARCH_ENABLED,
        "auto_continue_enabled": DEFAULT_AUTO_CONTINUE_ENABLED,
        "max_continues": DEFAULT_MAX_CONTINUES,
        "stream_retries": DEFAULT_STREAM_RETRIES,
        "history_recovery_attempts": DEFAULT_HISTORY_RECOVERY_ATTEMPTS,
        "history_recovery_interval_sec": DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC,
        "max_active_sessions": DEFAULT_MAX_ACTIVE_SESSIONS,
        "provider_max_concurrent_requests": DEFAULT_PROVIDER_MAX_CONCURRENT_REQUESTS,
        "provider_start_throttle_enabled": DEFAULT_PROVIDER_START_THROTTLE_ENABLED,
        "provider_start_interval_sec": DEFAULT_PROVIDER_START_INTERVAL_SEC,
        "provider_start_jitter_sec": DEFAULT_PROVIDER_START_JITTER_SEC,
        "provider_retry_jitter_enabled": DEFAULT_PROVIDER_RETRY_JITTER_ENABLED,
        "provider_retry_jitter_min_sec": DEFAULT_PROVIDER_RETRY_JITTER_MIN_SEC,
        "provider_retry_jitter_max_sec": DEFAULT_PROVIDER_RETRY_JITTER_MAX_SEC,
    }
