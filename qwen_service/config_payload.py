"""Public runtime config payload and update helpers for Qwen service."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

try:
    from .status_payload import provider_status_payload, session_capability_flags
except ImportError:
    from status_payload import provider_status_payload, session_capability_flags


def public_config_payload(
    *,
    config: dict[str, Any],
    defaults: dict[str, Any],
    har_dir: str,
    active_sessions: int,
    max_active_sessions: int,
    provider_max_concurrent_requests: int,
    provider_start_throttle_enabled: bool,
    provider_start_interval_sec: float,
    provider_start_jitter_sec: float,
    provider_retry_jitter_enabled: bool,
    provider_retry_jitter_bounds: tuple[float, float],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": config.get("model", defaults["model"]),
        "thinking_enabled": config.get("thinking_enabled", defaults["thinking_enabled"]),
        "search_enabled": config.get("search_enabled", defaults["search_enabled"]),
        "auto_continue_enabled": config.get("auto_continue_enabled", defaults["auto_continue_enabled"]),
        "max_continues": config.get("max_continues", defaults["max_continues"]),
        "stream_retries": config.get("stream_retries", defaults["stream_retries"]),
        "history_recovery_attempts": config.get("history_recovery_attempts", defaults["history_recovery_attempts"]),
        "history_recovery_interval_sec": config.get(
            "history_recovery_interval_sec", defaults["history_recovery_interval_sec"]
        ),
        "oss_put_mode": config.get("oss_put_mode", defaults["oss_put_mode"]),
        "file_upload_mode": config.get("file_upload_mode", defaults["file_upload_mode"]),
        "file_upload_max_size_mb": int(config.get("file_upload_max_size_mb") or defaults["file_upload_max_size_mb"]),
        "file_upload_max_files": int(config.get("file_upload_max_files") or defaults["file_upload_max_files"]),
        "file_metadata_cache_max_age_days": int(config.get("file_metadata_cache_max_age_days") or defaults.get("file_metadata_cache_max_age_days", 7)),
        "session_registry_cache_max_age_days": int(config.get("session_registry_cache_max_age_days") or defaults.get("session_registry_cache_max_age_days", 30)),
        "event_journal_path": config.get("event_journal_path", defaults.get("event_journal_path")),
        "event_journal_max_entries": int(config.get("event_journal_max_entries") or defaults.get("event_journal_max_entries", 500)),
        "session_source": config.get("session_source", defaults["session_source"]),
        "playwright_enabled": bool(config.get("playwright_enabled", defaults["playwright_enabled"])),
        "browser_login_automation": bool(
            config.get("browser_login_automation", defaults["browser_login_automation"])
        ),
        "browser_profile_dir": config.get("browser_profile_dir", defaults["browser_profile_dir"]),
        "browser_headless": bool(config.get("browser_headless", defaults["browser_headless"])),
        "browser_channel": config.get("browser_channel", defaults["browser_channel"]),
        "browser_refresh_timeout_sec": config.get(
            "browser_refresh_timeout_sec", defaults["browser_refresh_timeout_sec"]
        ),
        "cdp_url": config.get("cdp_url", defaults["cdp_url"]),
        "har_dir": har_dir,
        "auth_required": bool(config.get("api_key")) or not bool(config.get("allow_unauth_without_api_key")),
        "allow_unauth_without_api_key": bool(config.get("allow_unauth_without_api_key")),
        "cors_origins": config.get("cors_origins", defaults.get("cors_origins")),
    }
    payload.update(session_capability_flags(config))
    payload.update(
        provider_status_payload(
            active_sessions=active_sessions,
            max_active_sessions=max_active_sessions,
            provider_max_concurrent_requests=provider_max_concurrent_requests,
            provider_start_throttle_enabled=provider_start_throttle_enabled,
            provider_start_interval_sec=provider_start_interval_sec,
            provider_start_jitter_sec=provider_start_jitter_sec,
            provider_retry_jitter_enabled=provider_retry_jitter_enabled,
            provider_retry_jitter_bounds=provider_retry_jitter_bounds,
        )
    )
    return payload


def apply_runtime_config_update(
    update: Any,
    *,
    config: dict[str, Any],
    defaults: dict[str, Any],
    ensure_har_dir: Callable[[], Any],
    save_config: Callable[[dict[str, Any]], None],
    sync_env_from_config: Callable[[], None],
    set_model_for_all_clients: Callable[[str], None],
    public_payload_factory: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Apply partial runtime config without resetting omitted fields to defaults."""
    if update.model is not None:
        model = str(update.model or "").strip()
        if model:
            config["model"] = model
    if update.thinking_enabled is not None:
        config["thinking_enabled"] = bool(update.thinking_enabled)
    if update.search_enabled is not None:
        config["search_enabled"] = bool(update.search_enabled)
    if update.file_upload_mode is not None:
        mode = str(update.file_upload_mode or "auto").strip().lower()
        if mode not in {"api", "auto", "browser"}:
            mode = "auto"
        config["file_upload_mode"] = mode
    if update.session_source is not None:
        source = str(update.session_source or "har").strip().lower()
        if source not in {"env", "har", "manual", "cdp", "playwright"}:
            source = "har"
        config["session_source"] = source
    if update.playwright_enabled is not None:
        config["playwright_enabled"] = bool(update.playwright_enabled)
    if update.browser_login_automation is not None:
        config["browser_login_automation"] = bool(update.browser_login_automation)
    if update.browser_profile_dir is not None:
        profile_dir = str(update.browser_profile_dir or "").strip()
        if profile_dir:
            config["browser_profile_dir"] = profile_dir
    if update.browser_headless is not None:
        config["browser_headless"] = bool(update.browser_headless)
    if update.browser_channel is not None:
        config["browser_channel"] = str(update.browser_channel or "").strip() or defaults["browser_channel"]
    if update.browser_refresh_timeout_sec is not None:
        config["browser_refresh_timeout_sec"] = max(10.0, min(600.0, float(update.browser_refresh_timeout_sec)))
    if update.cdp_url is not None:
        cdp_url = str(update.cdp_url or "").strip()
        if cdp_url:
            config["cdp_url"] = cdp_url
    if update.har_dir is not None:
        har_dir = str(update.har_dir or "").strip()
        if har_dir:
            config["har_dir"] = har_dir
            ensure_har_dir()
    if update.auto_continue_enabled is not None:
        config["auto_continue_enabled"] = bool(update.auto_continue_enabled)
    if update.max_continues is not None:
        config["max_continues"] = max(1, min(20, int(update.max_continues)))
    if update.stream_retries is not None:
        config["stream_retries"] = max(0, min(10, int(update.stream_retries)))
    if update.history_recovery_attempts is not None:
        config["history_recovery_attempts"] = max(1, min(60, int(update.history_recovery_attempts)))
    if update.history_recovery_interval_sec is not None:
        config["history_recovery_interval_sec"] = max(0.2, min(30.0, float(update.history_recovery_interval_sec)))
    if getattr(update, "file_metadata_cache_max_age_days", None) is not None:
        config["file_metadata_cache_max_age_days"] = max(1, min(3650, int(update.file_metadata_cache_max_age_days)))
    if getattr(update, "session_registry_cache_max_age_days", None) is not None:
        config["session_registry_cache_max_age_days"] = max(1, min(3650, int(update.session_registry_cache_max_age_days)))
    if update.provider_start_throttle_enabled is not None:
        config["provider_start_throttle_enabled"] = bool(update.provider_start_throttle_enabled)
    if update.provider_start_interval_sec is not None:
        config["provider_start_interval_sec"] = max(0.0, min(10.0, float(update.provider_start_interval_sec)))
    if update.provider_start_jitter_sec is not None:
        config["provider_start_jitter_sec"] = max(0.0, min(10.0, float(update.provider_start_jitter_sec)))
    if update.provider_retry_jitter_enabled is not None:
        config["provider_retry_jitter_enabled"] = bool(update.provider_retry_jitter_enabled)
    if update.provider_retry_jitter_min_sec is not None:
        config["provider_retry_jitter_min_sec"] = max(0.0, min(30.0, float(update.provider_retry_jitter_min_sec)))
    if update.provider_retry_jitter_max_sec is not None:
        config["provider_retry_jitter_max_sec"] = max(0.0, min(30.0, float(update.provider_retry_jitter_max_sec)))

    save_config(config)
    sync_env_from_config()
    if update.model is not None:
        set_model_for_all_clients(str(config.get("model", defaults["model"])))
    return public_payload_factory()
