"""Qwen Service: standalone REST API wrapper around Qwen provider client."""

import logging
import os
import sys
import time
from pathlib import Path
from threading import RLock
from collections.abc import Callable
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import File, HTTPException, Security, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials


PROJECT_ROOT = Path(__file__).resolve().parent.parent
QWEN_SERVICE_DIR = Path(__file__).resolve().parent
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path)
    logging.info(f".env загружен из: {env_path}")


try:
    from .qwen_api import (
        QwenAPI,
        QwenChatInProgressError,
        QwenInternalStreamError,
        QwenProviderError,
        QwenRequestEndedError,
        SendRequest,
        StreamCallbacks,
    )
    from .har_token_scanner import extract_latest_qwen_session_from_har_bytes, extract_latest_qwen_token_from_har_bytes, mask_token
    from .playwright_session import refresh_qwen_browser_session, refresh_qwen_cdp_session
except ImportError:
    from qwen_api import (
        QwenAPI,
        QwenChatInProgressError,
        QwenInternalStreamError,
        QwenProviderError,
        QwenRequestEndedError,
        SendRequest,
        StreamCallbacks,
    )
    from har_token_scanner import extract_latest_qwen_session_from_har_bytes, extract_latest_qwen_token_from_har_bytes, mask_token
    from playwright_session import refresh_qwen_browser_session, refresh_qwen_cdp_session

try:
    from requests.exceptions import ChunkedEncodingError, ConnectionError as RequestsConnectionError, ReadTimeout
except Exception:
    ChunkedEncodingError = Exception
    RequestsConnectionError = Exception
    ReadTimeout = Exception

try:
    from .auth_runtime import (
        active_token_smoke_check_sync as _auth_active_token_smoke_check_sync,
        auth_status_payload as _auth_status_payload_builder,
        check_qwen_auth_status as _auth_check_qwen_auth_status,
        is_qwen_token_expired_error as _auth_is_qwen_token_expired_error,
    )
    from .api_runtime import (
        QwenApiProxy as _ApiRuntimeQwenApiProxy,
        call_qwen_locked as _api_call_qwen_locked,
        ensure_control_qwen_api as _api_ensure_control_qwen_api,
        new_qwen_api as _api_new_qwen_api,
        run_qwen_locked as _api_run_qwen_locked,
    )
    from .app_setup import create_qwen_app
    from .security_runtime import (
        create_service_security as _security_create_service_security,
        require_service_token as _security_require_service_token,
        verify_service_token as _security_verify_service_token,
    )
    from .config_payload import (
        apply_runtime_config_update as _config_apply_runtime_config_update,
        public_config_payload as _config_public_payload,
    )
    from .diagnostics_runtime import build_readiness_payload as _diagnostics_build_readiness_payload
    from .cache_maintenance_runtime import build_cache_maintenance_payload as _cache_maintenance_payload
    from .event_journal_runtime import (
        build_event_journal_clear_payload as _event_journal_clear_payload,
        build_event_journal_payload as _event_journal_payload,
        event_status_from_payload as _event_status_from_payload,
        record_qwen_event as _record_qwen_event,
    )
    from .config_endpoints_runtime import (
        auth_check_payload as _config_endpoint_auth_check,
        auth_status_payload as _config_endpoint_auth_status,
        get_auto_continue_config_payload as _config_endpoint_get_auto_continue,
        get_config_payload as _config_endpoint_get_config,
        get_har_dir_info_payload as _config_endpoint_get_har_dir_info,
        get_model_payload as _config_endpoint_get_model,
        list_models_payload as _config_endpoint_list_models,
        refresh_session_from_browser_payload as _config_endpoint_refresh_session_from_browser,
        refresh_session_from_cdp_payload as _config_endpoint_refresh_session_from_cdp,
        set_api_key_payload as _config_endpoint_set_api_key,
        set_auto_continue_config_payload as _config_endpoint_set_auto_continue,
        set_model_payload as _config_endpoint_set_model,
        set_token_from_har_upload_payload as _config_endpoint_set_token_from_har_upload,
        set_token_from_local_har_file_payload as _config_endpoint_set_token_from_local_har_file,
        set_token_payload as _config_endpoint_set_token,
        update_config_payload as _config_endpoint_update_config,
        update_session_headers_payload as _config_endpoint_update_session_headers,
    )
    from .defaults import (
        DEFAULT_AUTH_STATUS_CACHE_TTL_SEC,
        DEFAULT_AUTO_CONTINUE_ENABLED,
        DEFAULT_BROWSER_CHANNEL,
        DEFAULT_BROWSER_HEADLESS,
        DEFAULT_BROWSER_LOGIN_AUTOMATION,
        DEFAULT_BROWSER_PROFILE_DIR,
        DEFAULT_BROWSER_REFRESH_TIMEOUT_SEC,
        DEFAULT_CDP_URL,
        DEFAULT_FILE_UPLOAD_MAX_FILES,
        DEFAULT_FILE_UPLOAD_MAX_SIZE_MB,
        DEFAULT_FILE_UPLOAD_MODE,
        DEFAULT_HAR_DIR,
        DEFAULT_HISTORY_RECOVERY_ATTEMPTS,
        DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC,
        DEFAULT_HOST,
        DEFAULT_MAX_ACTIVE_SESSIONS,
        DEFAULT_MAX_CONTINUES,
        DEFAULT_MODEL,
        DEFAULT_OSS_PUT_MODE,
        DEFAULT_PLAYWRIGHT_ENABLED,
        DEFAULT_PORT,
        DEFAULT_PROVIDER_MAX_CONCURRENT_REQUESTS,
        DEFAULT_PROVIDER_RETRY_JITTER_ENABLED,
        DEFAULT_PROVIDER_RETRY_JITTER_MAX_SEC,
        DEFAULT_PROVIDER_RETRY_JITTER_MIN_SEC,
        DEFAULT_PROVIDER_SLOT_TIMEOUT_SEC,
        DEFAULT_PROVIDER_START_INTERVAL_SEC,
        DEFAULT_PROVIDER_START_JITTER_SEC,
        DEFAULT_PROVIDER_START_THROTTLE_ENABLED,
        DEFAULT_SEARCH_ENABLED,
        DEFAULT_SESSION_SOURCE,
        DEFAULT_STREAM_RETRIES,
        DEFAULT_THINKING_ENABLED,
        DEFAULT_USER_AGENT,
        initial_runtime_config,
        runtime_config_defaults,
    )
    from .continuation import (
        can_auto_continue as _continuation_can_auto_continue,
        reset_continuation_tracker as _continuation_reset_tracker,
        should_auto_continue as _continuation_should_auto_continue,
        track_continuation as _continuation_track,
    )
    from .har_storage import (
        configured_har_dir as _har_configured_dir,
        ensure_har_dir as _har_ensure_dir,
        latest_har_file as _har_latest_file,
        load_har_from_service_dir as _har_load_from_service_dir,
        resolve_project_path as _har_resolve_project_path,
    )
    from .logging_config import setup_qwen_logging as _logging_setup_qwen_logging
    from .message_recovery import (
        extract_latest_assistant_parts as _message_extract_latest_assistant_parts,
        pick_fallback_model as _message_pick_fallback_model,
        recover_response_from_history as _message_recover_response_from_history,
    )
    from .message_stream_runtime import (
        continue_message_sync as _stream_continue_message_sync,
        send_message_sync as _stream_send_message_sync,
    )
    from .message_endpoints_runtime import (
        continue_message_payload_from_state as _message_endpoint_continue_message_payload,
        send_message_payload_from_state as _message_endpoint_send_message_payload,
    )
    from .provider_runtime import (
        current_max_active_sessions as _provider_current_max_active_sessions,
        current_provider_concurrency as _provider_current_concurrency,
        current_provider_retry_jitter_bounds as _provider_current_retry_jitter_bounds,
        current_provider_retry_jitter_enabled as _provider_current_retry_jitter_enabled,
        current_provider_start_interval_sec as _provider_current_start_interval_sec,
        current_provider_start_jitter_sec as _provider_current_start_jitter_sec,
        current_provider_start_throttle_enabled as _provider_current_start_throttle_enabled,
        provider_retry_backoff as _provider_retry_backoff_helper,
        rate_limited_error as _provider_rate_limited_error,
        run_with_provider_slot as _provider_run_with_slot,
        wait_provider_start_spacing as _provider_wait_start_spacing,
    )
    from .runtime_config import (
        persist_runtime_config as _runtime_persist_config,
        sync_runtime_env_from_config as _runtime_sync_env_from_config,
    )
    from .runtime_state import QwenRuntimeState
    from .schemas import (
        APIKeyConfig,
        CacheMaintenanceRequest,
        ChatSession,
        ContinueMessageRequest,
        CreateSessionRequest,
        FileMessageRequest,
        HarFileImportRequest,
        ModelConfig,
        QwenSessionHeadersConfig,
        RuntimeConfigUpdate,
        SendMessageRequest,
        TokenConfig,
    )
    from .session_endpoints_runtime import (
        create_session_payload_from_state as _session_endpoint_create_session,
        delete_session_payload_from_state as _session_endpoint_delete_session,
        get_session_payload_from_state as _session_endpoint_get_session,
        list_sessions_payload_from_state as _session_endpoint_list_sessions,
        rename_session_payload_from_state as _session_endpoint_rename_session,
    )
    from .system_runtime import (
        health_check_payload_from_state as _system_health_check_payload,
        log_startup_config as _system_log_startup_config,
        startup_host_port as _system_startup_host_port,
        user_info_payload as _system_user_info_payload,
    )
    from .file_runtime import (
        fetch_file_info_from_state as _file_runtime_fetch_file_info,
        upload_files_and_send_message_from_state as _file_runtime_upload_files_and_send_message,
        upload_files_payload_from_state as _file_runtime_upload_files_payload,
    )
    from .file_metadata_store import build_uploaded_file_metadata_store as _build_uploaded_file_metadata_store
    from .session_registry_store import build_qwen_session_registry_store as _build_qwen_session_registry_store
    from .event_journal_store import build_qwen_event_journal_store as _build_qwen_event_journal_store
    from .session_runtime import (
        active_session_count as _session_active_count,
        apply_session_values as _session_apply_values,
        drop_session_client as _session_drop_client,
        get_session_client as _session_get_client,
        get_session_lock as _session_get_lock,
        register_session_client as _session_register_client,
        safe_session_source as _session_safe_source,
        set_model_for_clients as _session_set_model_for_clients,
    )
    from .upload_validation import (
        file_max_size_bytes as _upload_file_max_size_bytes,
        max_files_per_message as _upload_max_files_per_message,
        normalize_request_file_paths as _upload_normalize_request_file_paths,
        prevalidate_upload_paths as _upload_prevalidate_upload_paths,
        raise_upload_http_error as _upload_raise_http_error,
    )
except ImportError:
    from auth_runtime import (
        active_token_smoke_check_sync as _auth_active_token_smoke_check_sync,
        auth_status_payload as _auth_status_payload_builder,
        check_qwen_auth_status as _auth_check_qwen_auth_status,
        is_qwen_token_expired_error as _auth_is_qwen_token_expired_error,
    )
    from api_runtime import (
        QwenApiProxy as _ApiRuntimeQwenApiProxy,
        call_qwen_locked as _api_call_qwen_locked,
        ensure_control_qwen_api as _api_ensure_control_qwen_api,
        new_qwen_api as _api_new_qwen_api,
        run_qwen_locked as _api_run_qwen_locked,
    )
    from app_setup import create_qwen_app
    from security_runtime import (
        create_service_security as _security_create_service_security,
        require_service_token as _security_require_service_token,
        verify_service_token as _security_verify_service_token,
    )
    from config_payload import (
        apply_runtime_config_update as _config_apply_runtime_config_update,
        public_config_payload as _config_public_payload,
    )
    from diagnostics_runtime import build_readiness_payload as _diagnostics_build_readiness_payload
    from cache_maintenance_runtime import build_cache_maintenance_payload as _cache_maintenance_payload
    from event_journal_runtime import (
        build_event_journal_clear_payload as _event_journal_clear_payload,
        build_event_journal_payload as _event_journal_payload,
        event_status_from_payload as _event_status_from_payload,
        record_qwen_event as _record_qwen_event,
    )
    from config_endpoints_runtime import (
        auth_check_payload as _config_endpoint_auth_check,
        auth_status_payload as _config_endpoint_auth_status,
        get_auto_continue_config_payload as _config_endpoint_get_auto_continue,
        get_config_payload as _config_endpoint_get_config,
        get_har_dir_info_payload as _config_endpoint_get_har_dir_info,
        get_model_payload as _config_endpoint_get_model,
        list_models_payload as _config_endpoint_list_models,
        refresh_session_from_browser_payload as _config_endpoint_refresh_session_from_browser,
        refresh_session_from_cdp_payload as _config_endpoint_refresh_session_from_cdp,
        set_api_key_payload as _config_endpoint_set_api_key,
        set_auto_continue_config_payload as _config_endpoint_set_auto_continue,
        set_model_payload as _config_endpoint_set_model,
        set_token_from_har_upload_payload as _config_endpoint_set_token_from_har_upload,
        set_token_from_local_har_file_payload as _config_endpoint_set_token_from_local_har_file,
        set_token_payload as _config_endpoint_set_token,
        update_config_payload as _config_endpoint_update_config,
        update_session_headers_payload as _config_endpoint_update_session_headers,
    )
    from defaults import (
        DEFAULT_AUTH_STATUS_CACHE_TTL_SEC,
        DEFAULT_AUTO_CONTINUE_ENABLED,
        DEFAULT_BROWSER_CHANNEL,
        DEFAULT_BROWSER_HEADLESS,
        DEFAULT_BROWSER_LOGIN_AUTOMATION,
        DEFAULT_BROWSER_PROFILE_DIR,
        DEFAULT_BROWSER_REFRESH_TIMEOUT_SEC,
        DEFAULT_CDP_URL,
        DEFAULT_FILE_UPLOAD_MAX_FILES,
        DEFAULT_FILE_UPLOAD_MAX_SIZE_MB,
        DEFAULT_FILE_UPLOAD_MODE,
        DEFAULT_HAR_DIR,
        DEFAULT_HISTORY_RECOVERY_ATTEMPTS,
        DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC,
        DEFAULT_HOST,
        DEFAULT_MAX_ACTIVE_SESSIONS,
        DEFAULT_MAX_CONTINUES,
        DEFAULT_MODEL,
        DEFAULT_OSS_PUT_MODE,
        DEFAULT_PLAYWRIGHT_ENABLED,
        DEFAULT_PORT,
        DEFAULT_PROVIDER_MAX_CONCURRENT_REQUESTS,
        DEFAULT_PROVIDER_RETRY_JITTER_ENABLED,
        DEFAULT_PROVIDER_RETRY_JITTER_MAX_SEC,
        DEFAULT_PROVIDER_RETRY_JITTER_MIN_SEC,
        DEFAULT_PROVIDER_SLOT_TIMEOUT_SEC,
        DEFAULT_PROVIDER_START_INTERVAL_SEC,
        DEFAULT_PROVIDER_START_JITTER_SEC,
        DEFAULT_PROVIDER_START_THROTTLE_ENABLED,
        DEFAULT_SEARCH_ENABLED,
        DEFAULT_SESSION_SOURCE,
        DEFAULT_STREAM_RETRIES,
        DEFAULT_THINKING_ENABLED,
        DEFAULT_USER_AGENT,
        initial_runtime_config,
        runtime_config_defaults,
    )
    from continuation import (
        can_auto_continue as _continuation_can_auto_continue,
        reset_continuation_tracker as _continuation_reset_tracker,
        should_auto_continue as _continuation_should_auto_continue,
        track_continuation as _continuation_track,
    )
    from har_storage import (
        configured_har_dir as _har_configured_dir,
        ensure_har_dir as _har_ensure_dir,
        latest_har_file as _har_latest_file,
        load_har_from_service_dir as _har_load_from_service_dir,
        resolve_project_path as _har_resolve_project_path,
    )
    from logging_config import setup_qwen_logging as _logging_setup_qwen_logging
    from message_recovery import (
        extract_latest_assistant_parts as _message_extract_latest_assistant_parts,
        pick_fallback_model as _message_pick_fallback_model,
        recover_response_from_history as _message_recover_response_from_history,
    )
    from message_stream_runtime import (
        continue_message_sync as _stream_continue_message_sync,
        send_message_sync as _stream_send_message_sync,
    )
    from message_endpoints_runtime import (
        continue_message_payload_from_state as _message_endpoint_continue_message_payload,
        send_message_payload_from_state as _message_endpoint_send_message_payload,
    )
    from provider_runtime import (
        current_max_active_sessions as _provider_current_max_active_sessions,
        current_provider_concurrency as _provider_current_concurrency,
        current_provider_retry_jitter_bounds as _provider_current_retry_jitter_bounds,
        current_provider_retry_jitter_enabled as _provider_current_retry_jitter_enabled,
        current_provider_start_interval_sec as _provider_current_start_interval_sec,
        current_provider_start_jitter_sec as _provider_current_start_jitter_sec,
        current_provider_start_throttle_enabled as _provider_current_start_throttle_enabled,
        provider_retry_backoff as _provider_retry_backoff_helper,
        rate_limited_error as _provider_rate_limited_error,
        run_with_provider_slot as _provider_run_with_slot,
        wait_provider_start_spacing as _provider_wait_start_spacing,
    )
    from runtime_config import (
        persist_runtime_config as _runtime_persist_config,
        sync_runtime_env_from_config as _runtime_sync_env_from_config,
    )
    from runtime_state import QwenRuntimeState
    from schemas import (
        APIKeyConfig,
        CacheMaintenanceRequest,
        ChatSession,
        ContinueMessageRequest,
        CreateSessionRequest,
        FileMessageRequest,
        HarFileImportRequest,
        ModelConfig,
        QwenSessionHeadersConfig,
        RuntimeConfigUpdate,
        SendMessageRequest,
        TokenConfig,
    )
    from session_endpoints_runtime import (
        create_session_payload_from_state as _session_endpoint_create_session,
        delete_session_payload_from_state as _session_endpoint_delete_session,
        get_session_payload_from_state as _session_endpoint_get_session,
        list_sessions_payload_from_state as _session_endpoint_list_sessions,
        rename_session_payload_from_state as _session_endpoint_rename_session,
    )
    from system_runtime import (
        health_check_payload_from_state as _system_health_check_payload,
        log_startup_config as _system_log_startup_config,
        startup_host_port as _system_startup_host_port,
        user_info_payload as _system_user_info_payload,
    )
    from file_runtime import (
        fetch_file_info_from_state as _file_runtime_fetch_file_info,
        upload_files_and_send_message_from_state as _file_runtime_upload_files_and_send_message,
        upload_files_payload_from_state as _file_runtime_upload_files_payload,
    )
    from file_metadata_store import build_uploaded_file_metadata_store as _build_uploaded_file_metadata_store
    from session_registry_store import build_qwen_session_registry_store as _build_qwen_session_registry_store
    from event_journal_store import build_qwen_event_journal_store as _build_qwen_event_journal_store
    from session_runtime import (
        active_session_count as _session_active_count,
        apply_session_values as _session_apply_values,
        drop_session_client as _session_drop_client,
        get_session_client as _session_get_client,
        get_session_lock as _session_get_lock,
        register_session_client as _session_register_client,
        safe_session_source as _session_safe_source,
        set_model_for_clients as _session_set_model_for_clients,
    )
    from upload_validation import (
        file_max_size_bytes as _upload_file_max_size_bytes,
        max_files_per_message as _upload_max_files_per_message,
        normalize_request_file_paths as _upload_normalize_request_file_paths,
        prevalidate_upload_paths as _upload_prevalidate_upload_paths,
        raise_upload_http_error as _upload_raise_http_error,
    )


runtime_state = QwenRuntimeState(
    config=initial_runtime_config(),
    project_root=PROJECT_ROOT,
    service_dir=QWEN_SERVICE_DIR,
    env_path=env_path,
    provider_default_concurrency=DEFAULT_PROVIDER_MAX_CONCURRENT_REQUESTS,
)
config = runtime_state.config


def _resolve_project_path(raw_path: str | None, *, default: str) -> Path:
    return _har_resolve_project_path(raw_path, project_root=PROJECT_ROOT, default=default)


def _configured_har_dir() -> Path:
    return _har_configured_dir(config, project_root=PROJECT_ROOT, default_har_dir=DEFAULT_HAR_DIR)


def _ensure_har_dir() -> Path:
    return _har_ensure_dir(config, project_root=PROJECT_ROOT, default_har_dir=DEFAULT_HAR_DIR)


def _latest_har_file(har_dir: Path) -> Path | None:
    return _har_latest_file(har_dir)


def _load_har_from_service_dir(filename: str | None = None) -> tuple[Path, bytes]:
    return _har_load_from_service_dir(
        filename,
        config=config,
        project_root=PROJECT_ROOT,
        default_har_dir=DEFAULT_HAR_DIR,
    )


def setup_qwen_logging() -> Path:
    """Configure qwen service logging to shared logs directory."""
    return _logging_setup_qwen_logging(PROJECT_ROOT, stdout=sys.stdout)


setup_qwen_logging()


def save_config(current_config: dict[str, Any]) -> None:
    """Persist runtime config into .env."""
    _runtime_persist_config(current_config, env_path=env_path)


def _sync_qwen_env_from_config() -> None:
    """Keep os.environ aligned with runtime config for existing QwenAPI objects."""
    _runtime_sync_env_from_config(config)


_sync_qwen_env_from_config()
qwen_token = str(config.get("token", "") or "").strip()
try:
    _ensure_har_dir()
except Exception as exc:
    logging.warning("Cannot create Qwen HAR directory %s: %s", config.get("har_dir", DEFAULT_HAR_DIR), exc)

try:
    runtime_state.uploaded_file_store = _build_uploaded_file_metadata_store(
        config,
        project_root=PROJECT_ROOT,
        logger=logging,
    )
    logging.info(
        "Qwen file metadata cache loaded: path=%s, entries=%s",
        runtime_state.uploaded_file_store.path,
        len(runtime_state.uploaded_file_store.all()),
    )
except Exception as exc:
    runtime_state.uploaded_file_store = None
    logging.warning("Cannot initialize Qwen file metadata cache: %s", exc)

try:
    runtime_state.session_registry_store = _build_qwen_session_registry_store(
        config,
        project_root=PROJECT_ROOT,
        logger=logging,
    )
    restored_sessions = runtime_state.load_persisted_sessions(
        max_sessions=_provider_current_max_active_sessions(config, DEFAULT_MAX_ACTIVE_SESSIONS)
    )
    logging.info(
        "Qwen session registry loaded: path=%s, entries=%s",
        runtime_state.session_registry_store.path,
        restored_sessions,
    )
except Exception as exc:
    runtime_state.session_registry_store = None
    logging.warning("Cannot initialize Qwen session registry cache: %s", exc)

try:
    runtime_state.event_journal_store = _build_qwen_event_journal_store(
        config,
        project_root=PROJECT_ROOT,
        logger=logging,
    )
    logging.info(
        "Qwen event journal loaded: path=%s, entries=%s",
        runtime_state.event_journal_store.path,
        runtime_state.event_journal_store.stats().get("entries"),
    )
    runtime_state.record_event(
        "service_start",
        status="ok",
        message="qwen_service runtime initialized",
        details={"model": config.get("model"), "has_token": bool(config.get("token"))},
    )
except Exception as exc:
    runtime_state.event_journal_store = None
    logging.warning("Cannot initialize Qwen event journal: %s", exc)





_session_qwen_clients = runtime_state.session_qwen_clients
_session_locks = runtime_state.session_locks
_qwen_registry_lock = runtime_state.registry_lock
qwen_request_lock = runtime_state.request_lock
_file_upload_and_send_lock = RLock()
_provider_request_semaphore = runtime_state.provider_request_semaphore
_provider_start_lock = runtime_state.provider_start_lock
_auth_status_cache = runtime_state.auth_status_cache
_current_qwen_client = runtime_state.current_qwen_client
active_sessions = runtime_state.active_sessions
auto_continue_tracker = runtime_state.auto_continue_tracker


def _new_qwen_api() -> QwenAPI | None:
    client = _api_new_qwen_api(
        config=config,
        qwen_api_cls=QwenAPI,
        default_user_agent=DEFAULT_USER_AGENT,
        default_model=DEFAULT_MODEL,
        logger_fn=lambda msg: logging.info(msg),
    )
    store = runtime_state.uploaded_file_store
    if client is not None and store is not None:
        try:
            store.hydrate_qwen_api(client)
        except Exception as exc:
            logging.warning("Cannot hydrate Qwen file metadata cache into provider client: %s", exc)
    return client


def _ensure_control_qwen_api() -> QwenAPI | None:
    runtime_state.control_qwen_api = _api_ensure_control_qwen_api(
        runtime_state.control_qwen_api,
        config=config,
        client_factory=_new_qwen_api,
    )
    return runtime_state.control_qwen_api


qwen_api = _ApiRuntimeQwenApiProxy(
    lambda: _current_qwen_client.get() or _ensure_control_qwen_api(),
    provider_error_cls=QwenProviderError,
)

if qwen_token:
    runtime_state.control_qwen_api = _new_qwen_api()
    logging.info("Qwen API initialized: token found")
else:
    logging.warning("Qwen token not found in .env!")


def _safe_session_source(source: str | None, default: str = "manual") -> str:
    return _session_safe_source(source, default)


def _reset_qwen_runtime_state_locked() -> None:
    """Reset provider clients after auth/session values changed.

    Caller must hold qwen_request_lock. This keeps token, Cookie and bx-* changes
    visible to all new QwenAPI instances without leaking secret values in logs.
    """
    _sync_qwen_env_from_config()
    with _qwen_registry_lock:
        runtime_state.clear_clients_and_sessions()
        runtime_state.control_qwen_api = _new_qwen_api() if config.get("token") else None


def _apply_session_values_locked(
    values: dict[str, Any],
    *,
    source: str = "manual",
    clear_missing: bool = False,
) -> dict[str, Any]:
    """Apply Qwen browser-session values to runtime config and .env.

    Caller must hold qwen_request_lock. Empty values are ignored by default so a
    partial manual/HAR/CDP update cannot accidentally wipe a working token. Pass
    clear_missing=true only when the caller intentionally wants to clear omitted
    fields.
    """
    return _session_apply_values(
        values,
        config=config,
        source=source,
        clear_missing=clear_missing,
        reset_runtime_state=_reset_qwen_runtime_state_locked,
        save_config=save_config,
        default_oss_put_mode=DEFAULT_OSS_PUT_MODE,
        default_session_source=DEFAULT_SESSION_SOURCE,
        logger=logging,
    )


def _get_session_lock(session_id: str) -> RLock:
    return _session_get_lock(
        session_id,
        registry_lock=_qwen_registry_lock,
        session_locks=_session_locks,
    )


def _get_session_qwen_api(session_id: str) -> QwenAPI:
    return _session_get_client(
        session_id,
        registry_lock=_qwen_registry_lock,
        session_clients=_session_qwen_clients,
        session_locks=_session_locks,
        client_factory=_new_qwen_api,
        provider_error_cls=QwenProviderError,
    )


def _register_session_qwen_api(session_id: str, client: QwenAPI) -> None:
    _session_register_client(
        session_id,
        client,
        registry_lock=_qwen_registry_lock,
        session_clients=_session_qwen_clients,
        session_locks=_session_locks,
    )


def _drop_session_qwen_api(session_id: str) -> None:
    _session_drop_client(
        session_id,
        registry_lock=_qwen_registry_lock,
        session_clients=_session_qwen_clients,
        session_locks=_session_locks,
        continuation_tracker=auto_continue_tracker,
    )


def _active_session_count() -> int:
    return _session_active_count(active_sessions, registry_lock=_qwen_registry_lock)


def _current_max_active_sessions() -> int:
    return _provider_current_max_active_sessions(config, DEFAULT_MAX_ACTIVE_SESSIONS)


def _current_provider_concurrency() -> int:
    return _provider_current_concurrency(config, DEFAULT_PROVIDER_MAX_CONCURRENT_REQUESTS)


def _current_provider_start_throttle_enabled() -> bool:
    return _provider_current_start_throttle_enabled(config, DEFAULT_PROVIDER_START_THROTTLE_ENABLED)


def _current_provider_start_interval_sec() -> float:
    return _provider_current_start_interval_sec(config, DEFAULT_PROVIDER_START_INTERVAL_SEC)


def _current_provider_start_jitter_sec() -> float:
    return _provider_current_start_jitter_sec(config, DEFAULT_PROVIDER_START_JITTER_SEC)


def _current_provider_retry_jitter_enabled() -> bool:
    return _provider_current_retry_jitter_enabled(config, DEFAULT_PROVIDER_RETRY_JITTER_ENABLED)


def _current_provider_retry_jitter_bounds() -> tuple[float, float]:
    return _provider_current_retry_jitter_bounds(
        config,
        default_min_sec=DEFAULT_PROVIDER_RETRY_JITTER_MIN_SEC,
        default_max_sec=DEFAULT_PROVIDER_RETRY_JITTER_MAX_SEC,
    )


def _wait_provider_start_spacing(operation: str) -> None:
    """Spread provider send start times without serializing active streams."""
    runtime_state.provider_next_start_at = _provider_wait_start_spacing(
        operation,
        config=config,
        default_enabled=DEFAULT_PROVIDER_START_THROTTLE_ENABLED,
        default_interval_sec=DEFAULT_PROVIDER_START_INTERVAL_SEC,
        default_jitter_sec=DEFAULT_PROVIDER_START_JITTER_SEC,
        start_lock=_provider_start_lock,
        next_start_at=runtime_state.provider_next_start_at,
        logger=logging,
    )


def _provider_retry_backoff(base: float) -> float:
    return _provider_retry_backoff_helper(
        base,
        config=config,
        default_enabled=DEFAULT_PROVIDER_RETRY_JITTER_ENABLED,
        default_min_sec=DEFAULT_PROVIDER_RETRY_JITTER_MIN_SEC,
        default_max_sec=DEFAULT_PROVIDER_RETRY_JITTER_MAX_SEC,
    )


def _run_with_provider_slot(operation: str, fn: Callable[[], Any]) -> Any:
    timeout = float(os.getenv("QWEN_PROVIDER_SLOT_TIMEOUT_SEC", str(DEFAULT_PROVIDER_SLOT_TIMEOUT_SEC)) or DEFAULT_PROVIDER_SLOT_TIMEOUT_SEC)
    runtime_state.begin_provider_request(operation)
    try:
        if operation not in {"send_message", "continue_message"}:
            _wait_provider_start_spacing(operation)
        return _provider_run_with_slot(
            operation,
            fn,
            semaphore=_provider_request_semaphore,
            timeout_sec=timeout,
            provider_error_cls=QwenProviderError,
        )
    finally:
        runtime_state.end_provider_request(operation)


def _rate_limited_error(message: str | None) -> bool:
    return _provider_rate_limited_error(message)


def _set_model_for_all_clients(model: str) -> None:
    _session_set_model_for_clients(
        model,
        registry_lock=_qwen_registry_lock,
        control_client=runtime_state.control_qwen_api,
        session_clients=_session_qwen_clients,
    )


def _call_qwen_locked(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return _api_call_qwen_locked(qwen_request_lock, fn, *args, **kwargs)


async def _run_qwen_locked(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await _api_run_qwen_locked(qwen_request_lock, fn, *args, **kwargs)



app = create_qwen_app()


security = _security_create_service_security()


def _allow_unauth_without_api_key() -> bool:
    return bool(config.get("allow_unauth_without_api_key"))


def verify_token(credentials: HTTPAuthorizationCredentials | None = Security(security)) -> bool:
    """Return whether the request matches the configured qwen_service API key."""
    return _security_verify_service_token(
        credentials,
        config.get("api_key", ""),
        allow_unauth_without_api_key=_allow_unauth_without_api_key(),
    )


def _require_service_token(credentials: HTTPAuthorizationCredentials | None) -> None:
    """Guard protected qwen_service endpoints with the configured API key."""
    _security_require_service_token(
        credentials,
        config.get("api_key", ""),
        allow_unauth_without_api_key=_allow_unauth_without_api_key(),
    )




def _is_qwen_token_expired_error(message: str | None) -> bool:
    return _auth_is_qwen_token_expired_error(message)


def _auth_status_payload(
    *,
    status: str,
    valid: bool,
    expired: bool = False,
    message: str = "",
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _auth_status_payload_builder(
        config=config,
        status=status,
        valid=valid,
        expired=expired,
        message=message,
        user=user,
        default_model=DEFAULT_MODEL,
        active_session_count=_active_session_count,
        max_active_sessions=_current_max_active_sessions,
        provider_concurrency=_current_provider_concurrency,
        provider_start_throttle_enabled=_current_provider_start_throttle_enabled,
        provider_start_interval_sec=_current_provider_start_interval_sec,
        provider_start_jitter_sec=_current_provider_start_jitter_sec,
        provider_retry_jitter_enabled=_current_provider_retry_jitter_enabled,
        provider_retry_jitter_bounds=_current_provider_retry_jitter_bounds,
    )


async def _check_qwen_auth_status(*, force: bool = False) -> dict[str, Any]:
    return await _auth_check_qwen_auth_status(
        config=config,
        auth_status_cache=_auth_status_cache,
        default_model=DEFAULT_MODEL,
        cache_ttl_sec=DEFAULT_AUTH_STATUS_CACHE_TTL_SEC,
        force=force,
        new_qwen_api=_new_qwen_api,
        run_in_threadpool=run_in_threadpool,
        run_with_provider_slot=_run_with_provider_slot,
        rate_limited_error=_rate_limited_error,
        active_session_count=_active_session_count,
        max_active_sessions=_current_max_active_sessions,
        provider_concurrency=_current_provider_concurrency,
        provider_start_throttle_enabled=_current_provider_start_throttle_enabled,
        provider_start_interval_sec=_current_provider_start_interval_sec,
        provider_start_jitter_sec=_current_provider_start_jitter_sec,
        provider_retry_jitter_enabled=_current_provider_retry_jitter_enabled,
        provider_retry_jitter_bounds=_current_provider_retry_jitter_bounds,
    )


def _active_token_smoke_check_sync() -> dict[str, Any]:
    return _auth_active_token_smoke_check_sync(
        config=config,
        default_model=DEFAULT_MODEL,
        new_qwen_api=_new_qwen_api,
        run_with_provider_slot=_run_with_provider_slot,
        send_message_sync=_send_message_sync,
        current_qwen_client=_current_qwen_client,
        registry_lock=_qwen_registry_lock,
        active_sessions=active_sessions,
        drop_session_client=_drop_session_qwen_api,
        rate_limited_error=_rate_limited_error,
        active_session_count=_active_session_count,
        max_active_sessions=_current_max_active_sessions,
        provider_concurrency=_current_provider_concurrency,
        provider_start_throttle_enabled=_current_provider_start_throttle_enabled,
        provider_start_interval_sec=_current_provider_start_interval_sec,
        provider_start_jitter_sec=_current_provider_start_jitter_sec,
        provider_retry_jitter_enabled=_current_provider_retry_jitter_enabled,
        provider_retry_jitter_bounds=_current_provider_retry_jitter_bounds,
    )


def _runtime_config_defaults() -> dict[str, Any]:
    return runtime_config_defaults()


def _public_config_payload() -> dict[str, Any]:
    payload = _config_public_payload(
        config=config,
        defaults=_runtime_config_defaults(),
        har_dir=str(_configured_har_dir()),
        active_sessions=_active_session_count(),
        max_active_sessions=_current_max_active_sessions(),
        provider_max_concurrent_requests=_current_provider_concurrency(),
        provider_start_throttle_enabled=_current_provider_start_throttle_enabled(),
        provider_start_interval_sec=_current_provider_start_interval_sec(),
        provider_start_jitter_sec=_current_provider_start_jitter_sec(),
        provider_retry_jitter_enabled=_current_provider_retry_jitter_enabled(),
        provider_retry_jitter_bounds=_current_provider_retry_jitter_bounds(),
    )
    store = runtime_state.uploaded_file_store
    payload["file_metadata_cache_enabled"] = store is not None
    if store is not None:
        payload["file_metadata_cache_path"] = str(store.path)
        payload["file_metadata_cache_entries"] = len(store.all())
        payload["file_metadata_cache_max_age_days"] = int(config.get("file_metadata_cache_max_age_days") or 7)
    session_store = runtime_state.session_registry_store
    payload["session_registry_cache_enabled"] = session_store is not None
    if session_store is not None:
        payload["session_registry_cache_path"] = str(session_store.path)
        payload["session_registry_cache_entries"] = len(session_store.all())
        payload["session_registry_cache_max_age_days"] = int(config.get("session_registry_cache_max_age_days") or 30)
    event_store = runtime_state.event_journal_store
    payload["event_journal_enabled"] = event_store is not None
    if event_store is not None:
        stats = event_store.stats()
        payload["event_journal_path"] = str(event_store.path)
        payload["event_journal_entries"] = stats.get("entries")
        payload["event_journal_max_entries"] = stats.get("max_entries")
    return payload


def _apply_runtime_config_update(update: "RuntimeConfigUpdate") -> dict[str, Any]:
    return _config_apply_runtime_config_update(
        update,
        config=config,
        defaults=_runtime_config_defaults(),
        ensure_har_dir=_ensure_har_dir,
        save_config=save_config,
        sync_env_from_config=_sync_qwen_env_from_config,
        set_model_for_all_clients=_set_model_for_all_clients,
        public_payload_factory=_public_config_payload,
    )




def _can_auto_continue(session_id: str) -> bool:
    return _continuation_can_auto_continue(
        config=config,
        tracker_store=auto_continue_tracker,
        session_id=session_id,
        default_enabled=DEFAULT_AUTO_CONTINUE_ENABLED,
        default_max_continues=DEFAULT_MAX_CONTINUES,
    )


def _track_continuation(session_id: str, message_id: int) -> None:
    _continuation_track(auto_continue_tracker, session_id, message_id)


def _reset_continuation_tracker(session_id: str) -> None:
    _continuation_reset_tracker(auto_continue_tracker, session_id)


def _should_auto_continue(response_text: str, can_continue_flag: bool) -> bool:
    return _continuation_should_auto_continue(response_text, can_continue_flag)


def _extract_latest_assistant_parts(
    session_id: str,
    min_message_id: int = 0,
) -> tuple[str, str, int]:
    return _message_extract_latest_assistant_parts(
        qwen_api=qwen_api,
        session_id=session_id,
        min_message_id=min_message_id,
    )


def _pick_fallback_model(current_model: str, *, tried_models: set[str] | None = None) -> str | None:
    return _message_pick_fallback_model(
        qwen_api=qwen_api,
        current_model=current_model,
        tried_models=tried_models,
        logger=logging,
    )


def _recover_response_from_history(
    session_id: str,
    min_message_id: int = 0,
    *,
    attempts_override: int | None = None,
    interval_override: float | None = None,
) -> tuple[str, str, int]:
    return _message_recover_response_from_history(
        qwen_api=qwen_api,
        config=config,
        default_attempts=DEFAULT_HISTORY_RECOVERY_ATTEMPTS,
        default_interval_sec=DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC,
        session_id=session_id,
        min_message_id=min_message_id,
        attempts_override=attempts_override,
        interval_override=interval_override,
        logger=logging,
        sleep_fn=time.sleep,
    )

def _send_message_sync(
    session_id: str,
    message: str,
    thinking_enabled: bool,
    search_enabled: bool,
    ref_file_ids: list[str] | None = None,
    timeout: int = 120,
) -> tuple[str, str, int, bool]:
    return _stream_send_message_sync(
        qwen_api=qwen_api,
        config=config,
        session_id=session_id,
        message=message,
        thinking_enabled=thinking_enabled,
        search_enabled=search_enabled,
        ref_file_ids=ref_file_ids,
        timeout=timeout,
        default_stream_retries=DEFAULT_STREAM_RETRIES,
        default_model=DEFAULT_MODEL,
        default_history_recovery_attempts=DEFAULT_HISTORY_RECOVERY_ATTEMPTS,
        default_history_recovery_interval_sec=DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC,
        wait_provider_start_spacing=_wait_provider_start_spacing,
        provider_retry_backoff=_provider_retry_backoff,
        recover_response_from_history=_recover_response_from_history,
        pick_fallback_model=_pick_fallback_model,
        save_config=save_config,
        set_model_for_all_clients=_set_model_for_all_clients,
    )


def _continue_message_sync(
    session_id: str,
    message_id: int,
    thinking_enabled: bool,
    timeout: int = 120,
) -> tuple[str, str, int, bool]:
    return _stream_continue_message_sync(
        qwen_api=qwen_api,
        config=config,
        session_id=session_id,
        message_id=message_id,
        thinking_enabled=thinking_enabled,
        timeout=timeout,
        default_stream_retries=DEFAULT_STREAM_RETRIES,
        default_history_recovery_attempts=DEFAULT_HISTORY_RECOVERY_ATTEMPTS,
        default_history_recovery_interval_sec=DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC,
        wait_provider_start_spacing=_wait_provider_start_spacing,
        provider_retry_backoff=_provider_retry_backoff,
        recover_response_from_history=_recover_response_from_history,
    )


@app.get("/health")
async def health_check():
    """Return compact Qwen service health/runtime status."""
    return _system_health_check_payload(
        runtime_state,
        ensure_control_client=_ensure_control_qwen_api,
    )




@app.get("/diagnostics/readiness")
async def diagnostics_readiness(credentials: HTTPAuthorizationCredentials | None = Security(security)):
    """Return local, provider-safe Qwen readiness diagnostics.

    This endpoint does not call the external Qwen provider. It only checks
    local config/runtime/cache/HAR state, so it is safe for admin pages and
    probe scripts before running expensive text/upload checks.
    """
    _require_service_token(credentials)
    host, port = _system_startup_host_port(config)
    payload = _diagnostics_build_readiness_payload(
        state=runtime_state,
        qwen_api=_ensure_control_qwen_api(),
        har_dir=_configured_har_dir(),
        service_base_url=f"http://{host}:{port}",
    )
    _record_qwen_event(
        runtime_state,
        "readiness",
        status=_event_status_from_payload(payload),
        message="readiness diagnostics finished",
        details={
            "check_count": payload.get("check_count"),
            "error_count": payload.get("error_count"),
            "warning_count": payload.get("warning_count"),
        },
    )
    return payload


@app.post("/diagnostics/cache-maintenance")
async def diagnostics_cache_maintenance(
    request: CacheMaintenanceRequest | None = None,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Inspect/prune local runtime caches without external Qwen provider calls.

    Default mode is dry-run. Set dry_run=false to actually remove stale local
    entries from logs/runtime/qwen/qwen_uploaded_files.json and logs/runtime/qwen/qwen_sessions.json.
    """
    _require_service_token(credentials)
    payload = _cache_maintenance_payload(
        state=runtime_state,
        request=request or CacheMaintenanceRequest(),
    )
    _record_qwen_event(
        runtime_state,
        "cache_maintenance",
        status=_event_status_from_payload(payload),
        message=str(payload.get("message") or "cache maintenance finished"),
        details={
            "dry_run": payload.get("dry_run"),
            "total_candidates": payload.get("total_candidates"),
            "total_removed": payload.get("total_removed"),
        },
    )
    return payload


@app.get("/diagnostics/events")
async def diagnostics_events(
    limit: int = 50,
    event: str | None = None,
    status: str | None = None,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Return recent local qwen_service operation events without external Qwen calls."""
    _require_service_token(credentials)
    return _event_journal_payload(state=runtime_state, limit=limit, event=event, status=status)


@app.post("/diagnostics/events/clear")
async def diagnostics_events_clear(credentials: HTTPAuthorizationCredentials | None = Security(security)):
    """Clear local qwen_service operation event journal."""
    _require_service_token(credentials)
    payload = _event_journal_clear_payload(state=runtime_state)
    _record_qwen_event(
        runtime_state,
        "event_journal_clear",
        status=_event_status_from_payload(payload),
        message=str(payload.get("message") or "event journal cleared"),
        details={"cleared": payload.get("cleared")},
    )
    return payload


@app.get("/auth/status")
async def auth_status(
    force: bool = False,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Return current Qwen token status without exposing the token."""
    return await _config_endpoint_auth_status(
        force=force,
        credentials=credentials,
        require_service_token=_require_service_token,
        check_qwen_auth_status=_check_qwen_auth_status,
    )


@app.post("/auth/check")
async def auth_check(credentials: HTTPAuthorizationCredentials | None = Security(security)):
    """Smoke-check the active in-memory Qwen token with a minimal chat request."""
    payload = await _config_endpoint_auth_check(
        state=runtime_state,
        credentials=credentials,
        require_service_token=_require_service_token,
        active_token_smoke_check_sync=_active_token_smoke_check_sync,
        monotonic=time.monotonic,
    )
    _record_qwen_event(
        runtime_state,
        "auth_check",
        status=_event_status_from_payload(payload),
        message=str(payload.get("message") or "auth check finished"),
        details={"checked_by": payload.get("checked_by"), "valid": payload.get("valid")},
    )
    return payload


@app.get("/config")
async def get_config():
    """Documentation updated."""
    return _config_endpoint_get_config(public_config_payload=_public_config_payload)


@app.post("/config")
async def update_config(
    update: RuntimeConfigUpdate,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Partial runtime config update used by backend QwenServiceClient.update_config()."""
    return _config_endpoint_update_config(
        state=runtime_state,
        update=update,
        credentials=credentials,
        require_service_token=_require_service_token,
        apply_runtime_config_update=_apply_runtime_config_update,
    )


@app.get("/config/auto_continue")
async def get_auto_continue_config():
    """Documentation updated."""
    return _config_endpoint_get_auto_continue(state=runtime_state)


@app.post("/config/auto_continue")
async def set_auto_continue_config(
    enabled: bool,
    max_continues: int | None = None,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    return _config_endpoint_set_auto_continue(
        state=runtime_state,
        enabled=enabled,
        max_continues=max_continues,
        credentials=credentials,
        require_service_token=_require_service_token,
        apply_runtime_config_update=_apply_runtime_config_update,
    )


@app.post("/config/token")
async def set_token(
    token_config: TokenConfig,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Set only the bearer token; browser-session headers are not touched."""
    return _config_endpoint_set_token(
        state=runtime_state,
        token_config=token_config,
        credentials=credentials,
        require_service_token=_require_service_token,
        save_config=save_config,
        reset_runtime_state_locked=_reset_qwen_runtime_state_locked,
    )


@app.post("/config/token/update-from-har")
async def set_token_from_har(
    har_file: UploadFile = File(...),
    validate: bool = True,
    require_file_api: bool = False,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Extract Qwen token + browser-session headers from uploaded HAR."""
    payload = await _config_endpoint_set_token_from_har_upload(
        state=runtime_state,
        har_file=har_file,
        validate=validate,
        require_file_api=require_file_api,
        credentials=credentials,
        require_service_token=_require_service_token,
        apply_session_values_locked=_apply_session_values_locked,
        check_qwen_auth_status=_check_qwen_auth_status,
        auth_status_payload_builder=_auth_status_payload,
    )
    _record_qwen_event(
        runtime_state,
        "token_update_from_har",
        status=_event_status_from_payload(payload),
        message=str(payload.get("message") or "HAR token/session import finished"),
        details={"validate": validate, "require_file_api": require_file_api, "updated": payload.get("updated")},
    )
    return payload


@app.get("/config/har")
async def get_har_dir_info(credentials: HTTPAuthorizationCredentials | None = Security(security)):
    """Return the local HAR import folder and visible .har files without secrets."""
    return _config_endpoint_get_har_dir_info(
        credentials=credentials,
        require_service_token=_require_service_token,
        ensure_har_dir=_ensure_har_dir,
    )


@app.post("/config/token/update-from-har-file")
async def set_token_from_local_har_file(
    import_request: HarFileImportRequest | None = None,
    validate: bool = True,
    require_file_api: bool = True,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Extract Qwen token + browser-session headers from qwen_service/har."""
    payload = await _config_endpoint_set_token_from_local_har_file(
        state=runtime_state,
        import_request=import_request,
        validate=validate,
        require_file_api=require_file_api,
        credentials=credentials,
        require_service_token=_require_service_token,
        load_har_from_service_dir=_load_har_from_service_dir,
        apply_session_values_locked=_apply_session_values_locked,
        check_qwen_auth_status=_check_qwen_auth_status,
        auth_status_payload_builder=_auth_status_payload,
    )
    _record_qwen_event(
        runtime_state,
        "token_update_from_local_har",
        status=_event_status_from_payload(payload),
        message=str(payload.get("message") or "local HAR token/session import finished"),
        details={"validate": validate, "require_file_api": require_file_api, "updated": payload.get("updated")},
    )
    return payload


@app.post("/config/session/update")
async def update_session_headers(
    session_config: QwenSessionHeadersConfig,
    validate: bool = False,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Manually set Qwen browser-session headers without Playwright login."""
    payload = await _config_endpoint_update_session_headers(
        state=runtime_state,
        session_config=session_config,
        validate=validate,
        credentials=credentials,
        require_service_token=_require_service_token,
        apply_session_values_locked=_apply_session_values_locked,
        safe_session_source=_safe_session_source,
        check_qwen_auth_status=_check_qwen_auth_status,
    )
    _record_qwen_event(
        runtime_state,
        "session_headers_update",
        status=_event_status_from_payload(payload),
        message=str(payload.get("message") or "session headers update finished"),
        details={"validate": validate, "source": getattr(session_config, "source", None)},
    )
    return payload


@app.post("/config/session/refresh-cdp")
async def refresh_session_from_cdp(
    validate: bool = False,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Capture Qwen session from an already-open normal Chrome via CDP."""
    return await _config_endpoint_refresh_session_from_cdp(
        state=runtime_state,
        validate=validate,
        credentials=credentials,
        require_service_token=_require_service_token,
        apply_session_values_locked=_apply_session_values_locked,
        check_qwen_auth_status=_check_qwen_auth_status,
    )


@app.post("/config/session/refresh-browser")
async def refresh_session_from_browser(
    validate: bool = False,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Compatibility endpoint for browser session refresh."""
    return await _config_endpoint_refresh_session_from_browser(
        state=runtime_state,
        validate=validate,
        credentials=credentials,
        require_service_token=_require_service_token,
        apply_session_values_locked=_apply_session_values_locked,
        safe_session_source=_safe_session_source,
        check_qwen_auth_status=_check_qwen_auth_status,
    )


@app.post("/config/api_key")
async def set_api_key(
    api_key_config: APIKeyConfig,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    return _config_endpoint_set_api_key(
        state=runtime_state,
        api_key_config=api_key_config,
        credentials=credentials,
        require_service_token=_require_service_token,
        save_config=save_config,
    )


@app.get("/config/model")
async def get_model():
    """Documentation updated."""
    return _config_endpoint_get_model(state=runtime_state)


@app.post("/config/model")
async def set_model(
    model_config: ModelConfig,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    return _config_endpoint_set_model(
        state=runtime_state,
        model_config=model_config,
        credentials=credentials,
        require_service_token=_require_service_token,
        apply_runtime_config_update=_apply_runtime_config_update,
    )


@app.get("/models")
async def list_models(credentials: HTTPAuthorizationCredentials | None = Security(security)):
    """Documentation updated."""
    return await _config_endpoint_list_models(
        credentials=credentials,
        verify_token=verify_token,
        qwen_api=qwen_api,
        run_qwen_locked=_run_qwen_locked,
    )


@app.post("/sessions")
async def create_session(
    request: CreateSessionRequest | None = None,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    _require_service_token(credentials)

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    payload = await _session_endpoint_create_session(
        request,
        state=runtime_state,
        current_max_active_sessions=_current_max_active_sessions,
        new_qwen_api=_new_qwen_api,
        run_with_provider_slot=_run_with_provider_slot,
        token_expired_checker=_is_qwen_token_expired_error,
    )
    _record_qwen_event(
        runtime_state,
        "session_create",
        status=_event_status_from_payload(payload),
        message="Qwen session created" if payload.get("session_id") else "Qwen session create finished",
        session_id=str(payload.get("session_id") or ""),
        details={"title": payload.get("title")},
    )
    return payload


@app.get("/sessions")
async def list_sessions(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    _require_service_token(credentials)

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    return await _session_endpoint_list_sessions(runtime_state, run_qwen_locked=_run_qwen_locked)


@app.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    _require_service_token(credentials)

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    return await _session_endpoint_get_session(
        session_id,
        state=runtime_state,
        new_qwen_api=_new_qwen_api,
        provider_error_cls=QwenProviderError,
    )


@app.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    _require_service_token(credentials)

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    return await _session_endpoint_delete_session(
        session_id,
        state=runtime_state,
        new_qwen_api=_new_qwen_api,
        provider_error_cls=QwenProviderError,
    )


@app.post("/sessions/{session_id}/rename")
async def rename_session(
    session_id: str,
    title_data: dict[str, str],
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    _require_service_token(credentials)

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    return await _session_endpoint_rename_session(
        session_id,
        title_data,
        state=runtime_state,
        new_qwen_api=_new_qwen_api,
        provider_error_cls=QwenProviderError,
    )




@app.post("/messages")
async def send_message(
    request: SendMessageRequest,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Send one chat message under a per-session lock.

    Different session_id values run in parallel. Only messages inside the same
    session wait for each other, so Qwen provider context/parent ids do not mix.
    """
    _require_service_token(credentials)

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    try:
        payload = await _message_endpoint_send_message_payload(
            request,
            state=runtime_state,
            new_qwen_api=_new_qwen_api,
            provider_error_cls=QwenProviderError,
            run_with_provider_slot=_run_with_provider_slot,
            send_message_sync=_send_message_sync,
            continue_message_sync=_continue_message_sync,
            logger=logging,
        )
        _record_qwen_event(
            runtime_state,
            "message_send",
            status=_event_status_from_payload(payload),
            message="Qwen message sent" if not payload.get("error") else str(payload.get("message") or "Qwen message error"),
            session_id=request.session_id,
            details={
                "message_chars": len(request.message or ""),
                "response_chars": len(str(payload.get("response") or "")),
                "thinking_chars": len(str(payload.get("thinking") or "")),
                "file_count": len(request.file_ids or []),
                "continue_count": payload.get("continue_count"),
                "can_continue": payload.get("can_continue"),
            },
        )
        return payload
    except Exception as exc:
        _record_qwen_event(
            runtime_state,
            "message_send",
            status="error",
            message=str(exc),
            session_id=request.session_id,
            details={"message_chars": len(request.message or ""), "file_count": len(request.file_ids or [])},
        )
        raise



@app.post("/messages/continue")
async def continue_message(
    request: ContinueMessageRequest,
    auto_continue: bool | None = None,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Continue one Qwen message under its per-session lock."""
    _require_service_token(credentials)

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    try:
        payload = await _message_endpoint_continue_message_payload(
            request,
            auto_continue,
            state=runtime_state,
            new_qwen_api=_new_qwen_api,
            provider_error_cls=QwenProviderError,
            continue_message_sync=_continue_message_sync,
            logger=logging,
        )
        _record_qwen_event(
            runtime_state,
            "message_continue",
            status=_event_status_from_payload(payload),
            message="Qwen message continued" if not payload.get("error") else str(payload.get("message") or "Qwen continue error"),
            session_id=request.session_id,
            details={
                "message_id": request.message_id,
                "continue_count": payload.get("continue_count"),
                "response_chars": len(str(payload.get("response") or "")),
                "can_continue": payload.get("can_continue"),
            },
        )
        return payload
    except Exception as exc:
        _record_qwen_event(
            runtime_state,
            "message_continue",
            status="error",
            message=str(exc),
            session_id=request.session_id,
            details={"message_id": request.message_id},
        )
        raise


@app.post("/files/upload")
async def upload_file(
    file_path_data: dict[str, Any],
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Upload one or many files to Qwen provider and wait until parsing succeeds.

    Body accepts either legacy {"file_path": "..."} or {"file_paths": ["...", ...]}.
    Limits: up to 5 files per request, each up to QWEN_FILE_UPLOAD_MAX_SIZE_MB
    (20 MB by default).
    """
    _require_service_token(credentials)

    try:
        payload = await _file_runtime_upload_files_payload(
            file_path_data,
            state=runtime_state,
            run_qwen_locked=_run_qwen_locked,
        )
        file_count = len(payload.get("file_ids") or []) or (1 if payload.get("file_id") else 0)
        _record_qwen_event(
            runtime_state,
            "file_upload",
            status=_event_status_from_payload(payload),
            message="Qwen file upload finished",
            details={"file_count": file_count, "has_file_id": bool(payload.get("file_id") or payload.get("file_ids"))},
        )
        return payload
    except Exception as exc:
        _record_qwen_event(
            runtime_state,
            "file_upload",
            status="error",
            message=str(exc),
            details={"file_path": file_path_data.get("file_path"), "file_count": len(file_path_data.get("file_paths") or [])},
        )
        raise


@app.post("/files/upload-many")
async def upload_many_files(
    file_path_data: dict[str, Any],
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Explicit alias for multi-file upload."""
    return await upload_file(file_path_data, credentials)


@app.post("/files/upload-and-send")
async def upload_file_and_send_message(
    request: FileMessageRequest,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Upload 1..5 files and send one prompt with all files attached."""
    _require_service_token(credentials)

    try:
        payload = await _file_runtime_upload_files_and_send_message(
            request,
            state=runtime_state,
            new_qwen_api=_new_qwen_api,
            provider_error_cls=QwenProviderError,
            run_with_provider_slot=_run_with_provider_slot,
            upload_message_lock=_file_upload_and_send_lock,
            get_session_lock=_get_session_lock,
        )
        _record_qwen_event(
            runtime_state,
            "file_upload_and_send",
            status=_event_status_from_payload(payload),
            message="Qwen upload-and-send finished" if not payload.get("error") else str(payload.get("message") or "Qwen upload-and-send error"),
            session_id=str(payload.get("session_id") or request.session_id or ""),
            details={
                "file_count": len(request.file_paths or []) + (1 if request.file_path else 0),
                "message_chars": len(request.message or ""),
                "response_chars": len(str(payload.get("response") or "")),
            },
        )
        return payload
    except Exception as exc:
        _record_qwen_event(
            runtime_state,
            "file_upload_and_send",
            status="error",
            message=str(exc),
            session_id=request.session_id,
            details={"file_count": len(request.file_paths or []) + (1 if request.file_path else 0), "message_chars": len(request.message or "")},
        )
        raise


@app.post("/files/upload-many-and-send")
async def upload_many_files_and_send_message(
    request: FileMessageRequest,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Explicit alias for uploading 1..5 files and sending one prompt."""
    return await upload_file_and_send_message(request, credentials)


@app.get("/files/{file_id}")
async def get_file(
    file_id: str,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    _require_service_token(credentials)

    return await _file_runtime_fetch_file_info(
        file_id,
        state=runtime_state,
        run_qwen_locked=_run_qwen_locked,
    )


@app.get("/user/info")
async def get_user_info(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Return current Qwen account info."""
    _require_service_token(credentials)
    return await _system_user_info_payload(qwen_api=qwen_api, run_qwen_locked=_run_qwen_locked)


def main():
    """Run the standalone Qwen service."""
    host, port = _system_startup_host_port(config)
    _system_log_startup_config(config, logger=logging)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
