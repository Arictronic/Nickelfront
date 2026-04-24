"""Per-source runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from parsers_pkg.sources import SourceMetadata


@dataclass(frozen=True)
class SourceRuntimeConfig:
    source: str
    enabled: bool
    timeout: float
    max_retries: int
    retry_base_delay: float
    retry_backoff_base: float
    retry_jitter_max: float
    browser_enabled: bool
    require_api_key: bool
    headless: bool
    headers_profile: str


def _env_key(source: str, suffix: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", source).upper().strip("_")
    return f"SRC_{normalized}_{suffix}"


def _get_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
        return parsed if parsed >= 1 else default
    except ValueError:
        return default


def load_source_runtime_config(source: str) -> SourceRuntimeConfig:
    return _load_source_runtime_config(source=source, source_meta=None)


def _load_source_runtime_config(source: str, source_meta: SourceMetadata | None) -> SourceRuntimeConfig:
    defaults = source_meta.runtime_defaults if source_meta is not None else None

    timeout = _get_float_env(_env_key(source, "TIMEOUT"), defaults.timeout if defaults else 30.0)
    max_retries = _get_int_env(_env_key(source, "MAX_RETRIES"), defaults.max_retries if defaults else 3)
    retry_base_delay = _get_float_env(
        _env_key(source, "RETRY_BASE_DELAY"),
        defaults.retry_base_delay if defaults else 1.5,
    )
    retry_backoff_base = _get_float_env(
        _env_key(source, "RETRY_BACKOFF_BASE"),
        defaults.retry_backoff_base if defaults else 2.0,
    )
    retry_jitter_max = _get_float_env(
        _env_key(source, "RETRY_JITTER_MAX"),
        defaults.retry_jitter_max if defaults else 0.7,
    )

    return SourceRuntimeConfig(
        source=source,
        enabled=_get_bool_env(_env_key(source, "ENABLED"), defaults.enabled if defaults else True),
        timeout=timeout if timeout > 0 else 30.0,
        max_retries=max_retries,
        retry_base_delay=retry_base_delay if retry_base_delay > 0 else 1.5,
        retry_backoff_base=retry_backoff_base if retry_backoff_base > 1 else 2.0,
        retry_jitter_max=retry_jitter_max if retry_jitter_max >= 0 else 0.7,
        browser_enabled=_get_bool_env(
            _env_key(source, "BROWSER_ENABLED"),
            defaults.browser_enabled if defaults else True,
        ),
        require_api_key=_get_bool_env(
            _env_key(source, "REQUIRE_API_KEY"),
            defaults.require_api_key if defaults else False,
        ),
        headless=_get_bool_env(_env_key(source, "HEADLESS"), defaults.headless if defaults else True),
        headers_profile=os.getenv(
            _env_key(source, "HEADERS_PROFILE"),
            defaults.headers_profile if defaults else "default",
        ),
    )


def load_source_runtime_config_with_metadata(source: str, source_meta: SourceMetadata) -> SourceRuntimeConfig:
    return _load_source_runtime_config(source=source, source_meta=source_meta)
