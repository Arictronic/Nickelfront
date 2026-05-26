"""Qwen Service: standalone REST API wrapper around Qwen provider client."""

import logging
import os
import random
import sys
import time
from contextlib import nullcontext
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import BoundedSemaphore, RLock
from collections.abc import Callable
from typing import Any

import uvicorn
from dotenv import load_dotenv, set_key
from fastapi import FastAPI, File, HTTPException, Security, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field


env_path = Path(__file__).parent.parent / ".env"
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
    from .har_token_scanner import extract_latest_qwen_token_from_har_bytes, mask_token
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
    from har_token_scanner import extract_latest_qwen_token_from_har_bytes, mask_token

try:
    from requests.exceptions import ChunkedEncodingError, ConnectionError as RequestsConnectionError, ReadTimeout
except Exception:
    ChunkedEncodingError = Exception
    RequestsConnectionError = Exception
    ReadTimeout = Exception


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on", "вкл"}:
        return True
    if value in {"0", "false", "no", "off", "выкл"}:
        return False
    logging.warning("Invalid boolean env %s=%r; using default %s", name, raw, default)
    return default


def _env_int(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        value = default
    else:
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            logging.warning("Invalid integer env %s=%r; using default %s", name, raw, default)
            value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def _env_float(name: str, default: float, *, min_value: float | None = None, max_value: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        value = default
    else:
        try:
            value = float(str(raw).strip())
        except (TypeError, ValueError):
            logging.warning("Invalid float env %s=%r; using default %s", name, raw, default)
            value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value



DEFAULT_HOST = os.getenv("QWEN_SERVICE_HOST", "127.0.0.1")
DEFAULT_PORT = _env_int("QWEN_SERVICE_PORT", 8767, min_value=1, max_value=65535)
DEFAULT_MODEL = (os.getenv("QWEN_MODEL", "qwen3.6-plus") or "qwen3.6-plus").strip() or "qwen3.6-plus"
DEFAULT_THINKING_ENABLED = _env_bool("QWEN_THINKING_ENABLED", True)
DEFAULT_SEARCH_ENABLED = _env_bool("QWEN_SEARCH_ENABLED", True)
DEFAULT_AUTO_CONTINUE_ENABLED = _env_bool("QWEN_AUTO_CONTINUE_ENABLED", True)
DEFAULT_MAX_CONTINUES = _env_int("QWEN_MAX_CONTINUES", 5, min_value=1, max_value=20)
DEFAULT_STREAM_RETRIES = _env_int("QWEN_STREAM_RETRIES", 2, min_value=0, max_value=10)
DEFAULT_HISTORY_RECOVERY_ATTEMPTS = _env_int("QWEN_HISTORY_RECOVERY_ATTEMPTS", 3, min_value=1, max_value=60)
DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC = _env_float("QWEN_HISTORY_RECOVERY_INTERVAL_SEC", 1.0, min_value=0.2, max_value=30.0)
DEFAULT_MAX_ACTIVE_SESSIONS = _env_int("QWEN_MAX_ACTIVE_SESSIONS", 50, min_value=1, max_value=500)
DEFAULT_PROVIDER_MAX_CONCURRENT_REQUESTS = _env_int("QWEN_PROVIDER_MAX_CONCURRENT_REQUESTS", 10, min_value=1, max_value=50)
DEFAULT_PROVIDER_SLOT_TIMEOUT_SEC = _env_float("QWEN_PROVIDER_SLOT_TIMEOUT_SEC", 300.0, min_value=1.0, max_value=1800.0)
DEFAULT_PROVIDER_START_THROTTLE_ENABLED = _env_bool("QWEN_PROVIDER_START_THROTTLE_ENABLED", False)
DEFAULT_PROVIDER_START_INTERVAL_SEC = _env_float("QWEN_PROVIDER_START_INTERVAL_SEC", 0.50, min_value=0.0, max_value=10.0)
DEFAULT_PROVIDER_START_JITTER_SEC = _env_float("QWEN_PROVIDER_START_JITTER_SEC", 0.25, min_value=0.0, max_value=10.0)
DEFAULT_PROVIDER_RETRY_JITTER_ENABLED = _env_bool("QWEN_PROVIDER_RETRY_JITTER_ENABLED", DEFAULT_PROVIDER_START_THROTTLE_ENABLED)
DEFAULT_PROVIDER_RETRY_JITTER_MIN_SEC = _env_float("QWEN_PROVIDER_RETRY_JITTER_MIN_SEC", 0.25, min_value=0.0, max_value=30.0)
DEFAULT_PROVIDER_RETRY_JITTER_MAX_SEC = _env_float("QWEN_PROVIDER_RETRY_JITTER_MAX_SEC", 1.25, min_value=0.0, max_value=30.0)
DEFAULT_AUTH_STATUS_CACHE_TTL_SEC = _env_float("QWEN_AUTH_STATUS_CACHE_TTL_SEC", 60.0, min_value=5.0, max_value=600.0)


config = {
    "host": DEFAULT_HOST,
    "port": DEFAULT_PORT,
    "token": (os.getenv("QWEN_TOKEN", "") or "").strip(),
    "api_key": (os.getenv("QWEN_API_KEY", "") or "").strip(),
    "model": DEFAULT_MODEL,
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


def setup_qwen_logging() -> Path:
    """Configure qwen service logging to shared logs directory."""
    project_root = Path(__file__).resolve().parent.parent
    raw_log_file = (os.getenv("QWEN_SERVICE_LOG_FILE") or "").strip()
    if raw_log_file:
        configured = Path(raw_log_file)
        log_file = configured if configured.is_absolute() else project_root / configured
    else:
        log_file = project_root / "logs" / "qwen_service.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    level_name = os.getenv("NICKELFRONT_LOG_LEVEL", os.getenv("LOG_LEVEL", "DEBUG")).upper()
    level = getattr(logging, level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | qwen_service | pid=%(process)d | %(name)s:%(lineno)d - %(message)s"
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        filename=str(log_file),
        maxBytes=20 * 1024 * 1024,
        backupCount=14,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)
    logging.getLogger("uvicorn.access").setLevel(max(level, logging.INFO))
    logging.info("Logging initialized: service=qwen_service file=%s", log_file)
    return log_file


setup_qwen_logging()


def save_config(current_config: dict[str, Any]) -> None:
    """Persist runtime config into .env.

    Keep all mutable runtime settings in sync with .env so a qwen_service
    restart does not silently roll back tuning changed through /config.
    """
    if not env_path.exists():
        env_path.touch()

    set_key(str(env_path), "QWEN_TOKEN", str(current_config.get("token", "")))
    set_key(str(env_path), "QWEN_API_KEY", str(current_config.get("api_key", "")))
    set_key(str(env_path), "QWEN_MODEL", str(current_config.get("model", DEFAULT_MODEL)))
    set_key(str(env_path), "QWEN_THINKING_ENABLED", str(current_config.get("thinking_enabled", True)).lower())
    set_key(str(env_path), "QWEN_SEARCH_ENABLED", str(current_config.get("search_enabled", True)).lower())
    set_key(
        str(env_path),
        "QWEN_AUTO_CONTINUE_ENABLED",
        str(current_config.get("auto_continue_enabled", DEFAULT_AUTO_CONTINUE_ENABLED)).lower(),
    )
    set_key(str(env_path), "QWEN_MAX_CONTINUES", str(current_config.get("max_continues", DEFAULT_MAX_CONTINUES)))
    set_key(str(env_path), "QWEN_STREAM_RETRIES", str(current_config.get("stream_retries", DEFAULT_STREAM_RETRIES)))
    set_key(
        str(env_path),
        "QWEN_HISTORY_RECOVERY_ATTEMPTS",
        str(current_config.get("history_recovery_attempts", DEFAULT_HISTORY_RECOVERY_ATTEMPTS)),
    )
    set_key(
        str(env_path),
        "QWEN_HISTORY_RECOVERY_INTERVAL_SEC",
        str(current_config.get("history_recovery_interval_sec", DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC)),
    )
    set_key(str(env_path), "QWEN_MAX_ACTIVE_SESSIONS", str(current_config.get("max_active_sessions", DEFAULT_MAX_ACTIVE_SESSIONS)))
    set_key(
        str(env_path),
        "QWEN_PROVIDER_MAX_CONCURRENT_REQUESTS",
        str(current_config.get("provider_max_concurrent_requests", DEFAULT_PROVIDER_MAX_CONCURRENT_REQUESTS)),
    )
    set_key(
        str(env_path),
        "QWEN_PROVIDER_START_THROTTLE_ENABLED",
        str(current_config.get("provider_start_throttle_enabled", DEFAULT_PROVIDER_START_THROTTLE_ENABLED)).lower(),
    )
    set_key(
        str(env_path),
        "QWEN_PROVIDER_START_INTERVAL_SEC",
        str(current_config.get("provider_start_interval_sec", DEFAULT_PROVIDER_START_INTERVAL_SEC)),
    )
    set_key(
        str(env_path),
        "QWEN_PROVIDER_START_JITTER_SEC",
        str(current_config.get("provider_start_jitter_sec", DEFAULT_PROVIDER_START_JITTER_SEC)),
    )
    set_key(
        str(env_path),
        "QWEN_PROVIDER_RETRY_JITTER_ENABLED",
        str(current_config.get("provider_retry_jitter_enabled", DEFAULT_PROVIDER_RETRY_JITTER_ENABLED)).lower(),
    )
    set_key(
        str(env_path),
        "QWEN_PROVIDER_RETRY_JITTER_MIN_SEC",
        str(current_config.get("provider_retry_jitter_min_sec", DEFAULT_PROVIDER_RETRY_JITTER_MIN_SEC)),
    )
    set_key(
        str(env_path),
        "QWEN_PROVIDER_RETRY_JITTER_MAX_SEC",
        str(current_config.get("provider_retry_jitter_max_sec", DEFAULT_PROVIDER_RETRY_JITTER_MAX_SEC)),
    )


qwen_token = str(config.get("token", "") or "").strip()







_control_qwen_api: QwenAPI | None = None
_session_qwen_clients: dict[str, QwenAPI] = {}
_session_locks: dict[str, RLock] = {}
_qwen_registry_lock = RLock()
qwen_request_lock = RLock()
_provider_request_semaphore = BoundedSemaphore(DEFAULT_PROVIDER_MAX_CONCURRENT_REQUESTS)
_provider_start_lock = RLock()
_provider_next_start_at = 0.0
_auth_status_cache: dict[str, Any] = {"value": None, "checked_at": 0.0}
_current_qwen_client: ContextVar[QwenAPI | None] = ContextVar("current_qwen_client", default=None)


def _new_qwen_api() -> QwenAPI | None:
    token = str(config.get("token", "") or "").strip()
    if not token:
        return None
    return QwenAPI(
        token=token,
        logger=lambda msg: logging.info(msg),
        default_model=str(config.get("model", DEFAULT_MODEL)),
    )


def _ensure_control_qwen_api() -> QwenAPI | None:
    global _control_qwen_api
    if _control_qwen_api is None and str(config.get("token", "") or "").strip():
        _control_qwen_api = _new_qwen_api()
    return _control_qwen_api


class _QwenApiProxy:
    """Compatibility proxy for existing code that references global qwen_api."""

    def _target(self) -> QwenAPI:
        client = _current_qwen_client.get() or _ensure_control_qwen_api()
        if client is None:
            raise QwenProviderError("Qwen API is not initialized")
        return client

    def __bool__(self) -> bool:
        return _current_qwen_client.get() is not None or _ensure_control_qwen_api() is not None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._target(), name, value)


qwen_api = _QwenApiProxy()

if qwen_token:
    _control_qwen_api = _new_qwen_api()
    logging.info("Qwen API initialized: token found")
else:
    logging.warning("Qwen token not found in .env!")


active_sessions: dict[str, dict[str, Any]] = {}


auto_continue_tracker: dict[str, dict[str, Any]] = {}


def _get_session_lock(session_id: str) -> RLock:
    with _qwen_registry_lock:
        return _session_locks.setdefault(session_id, RLock())


def _get_session_qwen_api(session_id: str) -> QwenAPI:
    with _qwen_registry_lock:
        client = _session_qwen_clients.get(session_id)
        if client is None:
            client = _new_qwen_api()
            if client is None:
                raise QwenProviderError("Qwen API is not initialized")
            client.session_id = session_id
            _session_qwen_clients[session_id] = client
        return client


def _register_session_qwen_api(session_id: str, client: QwenAPI) -> None:
    with _qwen_registry_lock:
        client.session_id = session_id
        _session_qwen_clients[session_id] = client
        _session_locks.setdefault(session_id, RLock())


def _drop_session_qwen_api(session_id: str) -> None:
    with _qwen_registry_lock:
        _session_qwen_clients.pop(session_id, None)
        _session_locks.pop(session_id, None)
        auto_continue_tracker.pop(session_id, None)


def _active_session_count() -> int:
    with _qwen_registry_lock:
        return len(active_sessions)


def _current_max_active_sessions() -> int:
    return max(1, min(500, int(config.get("max_active_sessions", DEFAULT_MAX_ACTIVE_SESSIONS) or DEFAULT_MAX_ACTIVE_SESSIONS)))


def _current_provider_concurrency() -> int:
    return max(1, min(50, int(config.get("provider_max_concurrent_requests", DEFAULT_PROVIDER_MAX_CONCURRENT_REQUESTS) or DEFAULT_PROVIDER_MAX_CONCURRENT_REQUESTS)))


def _current_provider_start_throttle_enabled() -> bool:
    return bool(config.get("provider_start_throttle_enabled", DEFAULT_PROVIDER_START_THROTTLE_ENABLED))


def _current_provider_start_interval_sec() -> float:
    return max(0.0, min(10.0, float(config.get("provider_start_interval_sec", DEFAULT_PROVIDER_START_INTERVAL_SEC) or 0.0)))


def _current_provider_start_jitter_sec() -> float:
    return max(0.0, min(10.0, float(config.get("provider_start_jitter_sec", DEFAULT_PROVIDER_START_JITTER_SEC) or 0.0)))


def _current_provider_retry_jitter_enabled() -> bool:
    return bool(config.get("provider_retry_jitter_enabled", DEFAULT_PROVIDER_RETRY_JITTER_ENABLED))


def _current_provider_retry_jitter_bounds() -> tuple[float, float]:
    min_sec = max(0.0, min(30.0, float(config.get("provider_retry_jitter_min_sec", DEFAULT_PROVIDER_RETRY_JITTER_MIN_SEC) or 0.0)))
    max_sec = max(0.0, min(30.0, float(config.get("provider_retry_jitter_max_sec", DEFAULT_PROVIDER_RETRY_JITTER_MAX_SEC) or 0.0)))
    if max_sec < min_sec:
        max_sec = min_sec
    return min_sec, max_sec


def _wait_provider_start_spacing(operation: str) -> None:
    """Spread only the start time of provider send calls.

    This keeps several chats streaming in parallel, but prevents a burst where
    multiple requests start at the same millisecond. Disabled by default and
    controlled by QWEN_PROVIDER_START_THROTTLE_ENABLED.
    """
    if operation not in {"send_message", "continue_message"} or not _current_provider_start_throttle_enabled():
        return

    interval = _current_provider_start_interval_sec()
    jitter = _current_provider_start_jitter_sec()
    if interval <= 0 and jitter <= 0:
        return

    global _provider_next_start_at
    with _provider_start_lock:
        now = time.monotonic()
        start_at = max(now, _provider_next_start_at)
        wait_for = max(0.0, start_at - now)
        _provider_next_start_at = start_at + interval + random.uniform(0.0, jitter)

    if wait_for > 0:
        logging.info("Qwen provider start throttle: operation=%s wait=%.2fs", operation, wait_for)
        time.sleep(wait_for)


def _provider_retry_backoff(base: float) -> float:
    if not _current_provider_retry_jitter_enabled():
        return base
    min_sec, max_sec = _current_provider_retry_jitter_bounds()
    if max_sec <= 0:
        return base
    return base + random.uniform(min_sec, max_sec)


def _run_with_provider_slot(operation: str, fn: Callable[[], Any]) -> Any:
    timeout = float(os.getenv("QWEN_PROVIDER_SLOT_TIMEOUT_SEC", str(DEFAULT_PROVIDER_SLOT_TIMEOUT_SEC)) or DEFAULT_PROVIDER_SLOT_TIMEOUT_SEC)
    acquired = _provider_request_semaphore.acquire(timeout=timeout)
    if not acquired:
        raise QwenProviderError(f"Qwen provider queue timeout while waiting for {operation}")
    try:
        return fn()
    finally:
        _provider_request_semaphore.release()


def _rate_limited_error(message: str | None) -> bool:
    value = str(message or "").lower()
    return "too many requests" in value or "rate limit" in value or "частот" in value


def _set_model_for_all_clients(model: str) -> None:
    with _qwen_registry_lock:
        if _control_qwen_api is not None:
            _control_qwen_api.set_model(model)
        for client in _session_qwen_clients.values():
            client.set_model(model)


def _call_qwen_locked(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run control/list/config qwen_api operations under a small control lock."""
    with qwen_request_lock:
        return fn(*args, **kwargs)


async def _run_qwen_locked(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a control qwen_api operation without blocking the FastAPI event loop."""
    return await run_in_threadpool(_call_qwen_locked, fn, *args, **kwargs)



app = FastAPI(title="Qwen Service", description="Мини-сервис для работы с Qwen API", version="1.0.0")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


security = HTTPBearer(auto_error=False)


def verify_token(credentials: HTTPAuthorizationCredentials | None = Security(security)) -> bool:
    """Documentation updated."""
    api_key = config.get("api_key", "")
    if not api_key:
        return True
    if credentials is None:
        return False
    return credentials.credentials == api_key


def _require_service_token(credentials: HTTPAuthorizationCredentials | None) -> None:
    """Guard mutable qwen_service endpoints with the configured API key."""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")




def _is_qwen_token_expired_error(message: str | None) -> bool:
    value = str(message or "").lower()
    return any(
        marker in value
        for marker in (
            "token has expired",
            "please log in again",
            "token expired",
            "login again",
            "not logged in",
            "unauthorized",
        )
    )


def _auth_status_payload(
    *,
    status: str,
    valid: bool,
    expired: bool = False,
    message: str = "",
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "valid": valid,
        "expired": expired,
        "token_configured": bool(config.get("token")),
        "has_api_key": bool(config.get("api_key")),
        "model": config.get("model", DEFAULT_MODEL),
        "message": message,
        "user": user or None,
        "checked_by": "provider_user_api",
        "active_sessions": _active_session_count(),
        "max_active_sessions": _current_max_active_sessions(),
        "provider_max_concurrent_requests": _current_provider_concurrency(),
        "provider_start_throttle_enabled": _current_provider_start_throttle_enabled(),
        "provider_start_interval_sec": _current_provider_start_interval_sec(),
        "provider_start_jitter_sec": _current_provider_start_jitter_sec(),
        "provider_retry_jitter_enabled": _current_provider_retry_jitter_enabled(),
        "provider_retry_jitter_min_sec": _current_provider_retry_jitter_bounds()[0],
        "provider_retry_jitter_max_sec": _current_provider_retry_jitter_bounds()[1],
    }


async def _check_qwen_auth_status(*, force: bool = False) -> dict[str, Any]:
    if not str(config.get("token") or "").strip():
        return _auth_status_payload(
            status="missing",
            valid=False,
            message="QWEN_TOKEN не задан.",
        )

    cached = _auth_status_cache.get("value")
    checked_at = float(_auth_status_cache.get("checked_at") or 0.0)
    cache_age = time.monotonic() - checked_at
    if not force and isinstance(cached, dict) and cache_age <= DEFAULT_AUTH_STATUS_CACHE_TTL_SEC:
        payload = dict(cached)
        payload["cached"] = True
        payload["cache_age_sec"] = round(cache_age, 1)
        return payload

    client = _new_qwen_api()
    if client is None:
        return _auth_status_payload(
            status="missing",
            valid=False,
            message="Qwen API не инициализирован: токен отсутствует.",
        )

    try:
        info = await run_in_threadpool(lambda: _run_with_provider_slot("auth_status", client.get_user_info))
        user = {}
        if isinstance(info, dict):
            user = {
                "id": info.get("id") or info.get("user_id"),
                "name": info.get("name") or info.get("nickname") or info.get("username"),
                "email": info.get("email"),
            }
            user = {key: value for key, value in user.items() if value}
        payload = _auth_status_payload(
            status="valid",
            valid=True,
            message="Текущий Qwen токен действителен.",
            user=user,
        )
    except ValueError as exc:
        payload = _auth_status_payload(
            status="unknown",
            valid=False,
            message=(
                "Qwen /api/user вернул не-JSON ответ. Токен не помечен как истёк; "
                "для точной проверки нажмите 'Проверить действующий токен'. "
                f"Детали: {exc}"
            ),
        )
        payload["checked_by"] = "provider_user_api"
    except Exception as exc:
        message = str(exc)
        if _is_qwen_token_expired_error(message):
            payload = _auth_status_payload(
                status="expired",
                valid=False,
                expired=True,
                message="Qwen токен истёк. Обновите QWEN_TOKEN через HAR.",
            )
        elif _rate_limited_error(message):
            payload = _auth_status_payload(
                status="rate_limited",
                valid=True,
                message="Текущий Qwen токен принят, но провайдер ограничил частоту запросов.",
            )
            payload["rate_limited"] = True
        else:
            payload = _auth_status_payload(
                status="unknown",
                valid=False,
                message=message or "Не удалось достоверно проверить Qwen токен.",
            )

    _auth_status_cache["value"] = payload
    _auth_status_cache["checked_at"] = time.monotonic()
    return payload


def _active_token_smoke_check_sync() -> dict[str, Any]:
    if not str(config.get("token") or "").strip():
        return _auth_status_payload(status="missing", valid=False, message="QWEN_TOKEN не задан.")

    client = _new_qwen_api()
    if client is None:
        return _auth_status_payload(status="missing", valid=False, message="Qwen API не инициализирован: токен отсутствует.")

    session_id = ""
    started = time.monotonic()
    try:
        session_id = _run_with_provider_slot("auth_check_create_session", client.create_session)
        if not session_id:
            return _auth_status_payload(status="invalid", valid=False, message="Qwen не вернул id тестовой сессии.")

        client.session_id = session_id
        token = _current_qwen_client.set(client)
        try:
            _run_with_provider_slot(
                "auth_check_send_message",
                lambda: _send_message_sync(
                    session_id=session_id,
                    message="Ответь только: OK",
                    thinking_enabled=False,
                    search_enabled=False,
                    ref_file_ids=None,
                    timeout=60,
                ),
            )
        finally:
            _current_qwen_client.reset(token)

        payload = _auth_status_payload(
            status="valid",
            valid=True,
            message="Текущий Qwen токен действителен: тестовый чат успешно получил ответ.",
        )
        payload["checked_by"] = "smoke_chat"
        payload["duration_sec"] = round(time.monotonic() - started, 2)
        return payload
    except Exception as exc:
        message = str(exc)
        if _is_qwen_token_expired_error(message):
            payload = _auth_status_payload(
                status="expired",
                valid=False,
                expired=True,
                message="Qwen токен истёк. Обновите его через HAR.",
            )
        elif _rate_limited_error(message):
            payload = _auth_status_payload(
                status="rate_limited",
                valid=True,
                message="Текущий Qwen токен принят, но провайдер временно ограничил частоту запросов: Too many requests.",
            )
            payload["rate_limited"] = True
        else:
            payload = _auth_status_payload(
                status="invalid",
                valid=False,
                message=message or "Текущий Qwen токен не прошёл smoke-проверку.",
            )
        payload["checked_by"] = "smoke_chat"
        payload["duration_sec"] = round(time.monotonic() - started, 2)
        return payload
    finally:
        if session_id:
            try:
                _run_with_provider_slot("auth_check_delete_session", lambda: client.delete_session(session_id))
            except Exception as cleanup_exc:
                logging.warning("Smoke-check session cleanup failed for %s: %s", session_id[-8:], cleanup_exc)
            with _qwen_registry_lock:
                active_sessions.pop(session_id, None)
            _drop_session_qwen_api(session_id)


def _public_config_payload() -> dict[str, Any]:
    return {
        "model": config.get("model", DEFAULT_MODEL),
        "thinking_enabled": config.get("thinking_enabled", DEFAULT_THINKING_ENABLED),
        "search_enabled": config.get("search_enabled", DEFAULT_SEARCH_ENABLED),
        "auto_continue_enabled": config.get("auto_continue_enabled", DEFAULT_AUTO_CONTINUE_ENABLED),
        "max_continues": config.get("max_continues", DEFAULT_MAX_CONTINUES),
        "stream_retries": config.get("stream_retries", DEFAULT_STREAM_RETRIES),
        "history_recovery_attempts": config.get("history_recovery_attempts", DEFAULT_HISTORY_RECOVERY_ATTEMPTS),
        "history_recovery_interval_sec": config.get("history_recovery_interval_sec", DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC),
        "has_token": bool(config.get("token")),
        "has_api_key": bool(config.get("api_key")),
        "active_sessions": _active_session_count(),
        "max_active_sessions": _current_max_active_sessions(),
        "provider_max_concurrent_requests": _current_provider_concurrency(),
        "provider_start_throttle_enabled": _current_provider_start_throttle_enabled(),
        "provider_start_interval_sec": _current_provider_start_interval_sec(),
        "provider_start_jitter_sec": _current_provider_start_jitter_sec(),
        "provider_retry_jitter_enabled": _current_provider_retry_jitter_enabled(),
        "provider_retry_jitter_min_sec": _current_provider_retry_jitter_bounds()[0],
        "provider_retry_jitter_max_sec": _current_provider_retry_jitter_bounds()[1],
    }


def _apply_runtime_config_update(update: "RuntimeConfigUpdate") -> dict[str, Any]:
    """Apply partial runtime config without resetting omitted fields to defaults."""
    if update.model is not None:
        model = str(update.model or "").strip()
        if model:
            config["model"] = model
    if update.thinking_enabled is not None:
        config["thinking_enabled"] = bool(update.thinking_enabled)
    if update.search_enabled is not None:
        config["search_enabled"] = bool(update.search_enabled)
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
    if update.model is not None:
        _set_model_for_all_clients(str(config.get("model", DEFAULT_MODEL)))
    return _public_config_payload()



class ChatSession(BaseModel):
    session_id: str
    title: str = "Новый чат"


class CreateSessionRequest(BaseModel):
    title: str | None = None


class SendMessageRequest(BaseModel):
    session_id: str
    message: str
    thinking_enabled: bool = DEFAULT_THINKING_ENABLED
    search_enabled: bool = DEFAULT_SEARCH_ENABLED
    file_ids: list[str] = Field(default_factory=list)
    auto_continue: bool | None = None


class FileMessageRequest(BaseModel):
    file_path: str
    message: str = ""
    session_id: str | None = None
    thinking_enabled: bool = DEFAULT_THINKING_ENABLED
    search_enabled: bool = DEFAULT_SEARCH_ENABLED
    auto_continue: bool | None = None
    session_prompt: str = ""


class ContinueMessageRequest(BaseModel):
    session_id: str
    message_id: int
    thinking_enabled: bool = DEFAULT_THINKING_ENABLED


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
    auto_continue_enabled: bool | None = None
    max_continues: int | None = None
    stream_retries: int | None = None
    history_recovery_attempts: int | None = None
    history_recovery_interval_sec: float | None = None
    provider_start_throttle_enabled: bool | None = None
    provider_start_interval_sec: float | None = None
    provider_start_jitter_sec: float | None = None
    provider_retry_jitter_enabled: bool | None = None
    provider_retry_jitter_min_sec: float | None = None
    provider_retry_jitter_max_sec: float | None = None


class TokenConfig(BaseModel):
    token: str


class APIKeyConfig(BaseModel):
    api_key: str


def _can_auto_continue(session_id: str) -> bool:
    """Documentation updated."""
    if not config.get("auto_continue_enabled", DEFAULT_AUTO_CONTINUE_ENABLED):
        return False

    max_continues = config.get("max_continues", DEFAULT_MAX_CONTINUES)
    tracker = auto_continue_tracker.get(session_id, {})
    count = tracker.get("count", 0)

    return count < max_continues


def _track_continuation(session_id: str, message_id: int):
    """Documentation updated."""
    if session_id not in auto_continue_tracker:
        auto_continue_tracker[session_id] = {
            "message_ids": set(),
            "count": 0,
            "last_message_id": None,
        }

    tracker = auto_continue_tracker[session_id]


    tracker["count"] += 1
    tracker["message_ids"].add(message_id)
    tracker["last_message_id"] = message_id


def _reset_continuation_tracker(session_id: str):
    """Documentation updated."""
    auto_continue_tracker[session_id] = {
        "message_ids": set(),
        "count": 0,
        "last_message_id": None,
    }


def _should_auto_continue(response_text: str, can_continue_flag: bool) -> bool:
    """
    Continue strictly by provider signal.
    This avoids false-positive continuation loops that trigger
    "The chat is in progress!" for already-finished responses.
    """
    return bool(can_continue_flag)


def _extract_latest_assistant_parts(
    session_id: str,
    min_message_id: int = 0,
) -> tuple[str, str, int]:
    """
    Read the latest assistant message from chat history.
    Returns: (thinking, response, message_id). Empty response means not found.
    """
    if not qwen_api:
        return "", "", 0

    _, messages = qwen_api.fetch_history(session_id)
    if not messages:
        return "", "", 0

    for msg in reversed(messages):
        if msg.get("role") != "ASSISTANT":
            continue

        msg_id = int(msg.get("message_id") or 0)
        if min_message_id > 0 and msg_id < min_message_id:
            continue

        think_parts: list[str] = []
        response_parts: list[str] = []
        for fragment in msg.get("fragments") or []:
            if not isinstance(fragment, dict):
                continue
            fragment_type = str(fragment.get("type") or "")
            fragment_content = str(fragment.get("content") or "").strip()
            if not fragment_content:
                continue
            if fragment_type == "THINK":
                think_parts.append(fragment_content)
            if fragment_type == "RESPONSE":
                response_parts.append(fragment_content)

        return "\n\n".join(think_parts), "\n\n".join(response_parts), msg_id

    return "", "", 0


def _pick_fallback_model(current_model: str, *, tried_models: set[str] | None = None) -> str | None:
    """
    Pick the next model when provider returns `Model not found`.

    Keep track of already attempted models for the current request. Without that
    guard a bad provider model list or a stale static fallback list can cycle
    forever, for example qwen3.6-plus -> qwen3.5-plus -> qwen3.6-plus.
    """
    normalized_current = (current_model or "").strip().lower()
    tried = {item.strip().lower() for item in (tried_models or set()) if item and item.strip()}
    if normalized_current:
        tried.add(normalized_current)

    provider_candidates: list[str] = []
    if qwen_api:
        try:
            for m in qwen_api.fetch_models() or []:
                if not isinstance(m, dict):
                    continue
                mid = str(m.get("id") or m.get("name") or "").strip()
                if mid:
                    provider_candidates.append(mid)
        except Exception as exc:
            logging.warning("Failed to fetch provider model fallback list: %s", exc)
            provider_candidates = []

    static_candidates = ["qwen3.6-plus", "qwen3.5-plus", "qwen-plus", "qwen-max"]
    ordered: list[str] = []
    seen: set[str] = set()
    for candidate in provider_candidates + static_candidates:
        c = (candidate or "").strip()
        if not c:
            continue
        low = c.lower()
        if low in seen:
            continue
        seen.add(low)
        ordered.append(c)

    for candidate in ordered:
        if candidate.lower() not in tried:
            return candidate
    return None


def _recover_response_from_history(
    session_id: str,
    min_message_id: int = 0,
    *,
    attempts_override: int | None = None,
    interval_override: float | None = None,
) -> tuple[str, str, int]:
    """
    Fallback recovery when SSE stream is interrupted.
    Polls chat history for a saved assistant message.

    Important: when provider stream already produced chunks/thinking and then
    disconnected, the prompt must not be sent again to the same Qwen session.
    Qwen may still be generating the first answer and a duplicate send often
    returns "The chat is in progress!". In that case callers pass larger
    recovery limits here and wait for the already-started answer in history.
    """
    configured_attempts = int(config.get("history_recovery_attempts", DEFAULT_HISTORY_RECOVERY_ATTEMPTS))
    configured_interval = float(config.get("history_recovery_interval_sec", DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC))
    attempts = max(1, int(attempts_override if attempts_override is not None else configured_attempts))
    interval = max(0.5, float(interval_override if interval_override is not None else configured_interval))

    for attempt in range(1, attempts + 1):
        thinking, response, recovered_message_id = _extract_latest_assistant_parts(
            session_id=session_id,
            min_message_id=min_message_id,
        )
        if response.strip():
            logging.info(
                "Recovered response from history: session=%s, len=%s, message_id=%s, attempt=%s/%s",
                session_id[-6:],
                len(response),
                recovered_message_id,
                attempt,
                attempts,
            )
            return thinking, response, recovered_message_id

        if attempt < attempts:
            time.sleep(interval)

    return "", "", 0


def _send_message_sync(
    session_id: str,
    message: str,
    thinking_enabled: bool,
    search_enabled: bool,
    ref_file_ids: list[str] | None = None,
    timeout: int = 120,
) -> tuple[str, str, int, bool]:
    """Synchronous send with retry/partial-result resilience for unstable SSE streams."""
    qwen_api.session_id = session_id

    start_time = time.time()
    last_activity = start_time
    response_text = ""
    thinking_text = ""
    message_id = 0
    can_continue = False
    chunks_count = 0

    def on_parts(thinking: str, response: str):
        nonlocal thinking_text, response_text, last_activity, chunks_count
        thinking_text = thinking
        response_text = response
        last_activity = time.time()
        chunks_count += 1

        elapsed = last_activity - start_time
        if int(elapsed) % 15 == 0 and elapsed > 0:
            logging.info(f"  -> Receiving stream... {int(elapsed)}s, {chunks_count} chunks")

    def on_complete_parts(thinking: str, response: str):
        nonlocal thinking_text, response_text, last_activity
        thinking_text = thinking
        response_text = response
        last_activity = time.time()

    def on_meta(meta: dict[str, Any]):
        nonlocal message_id, can_continue
        message_id = int(meta.get("response_message_id", 0))
        can_continue = bool(meta.get("can_continue", False))

        if not can_continue and qwen_api.last_response_meta:
            can_continue = bool(qwen_api.last_response_meta.get("can_continue", False))

        if message_id <= 0:
            message_id = int(qwen_api.last_message_id or 0)

    send_request = SendRequest(
        session_id=session_id,
        prompt=message,
        ref_file_ids=ref_file_ids or [],
        thinking_enabled=thinking_enabled,
        search_enabled=search_enabled,
    )

    callbacks = StreamCallbacks(
        on_parts=on_parts,
        on_meta=on_meta,
        on_complete_parts=on_complete_parts,
    )

    max_retries = max(0, int(config.get("stream_retries", DEFAULT_STREAM_RETRIES)))
    attempted_model_fallbacks: set[str] = {str(config.get("model", DEFAULT_MODEL)).strip().lower()}
    max_model_fallback_switches = 4
    model_fallback_switches = 0
    attempt = 0

    while True:
        attempt += 1
        try:
            _wait_provider_start_spacing("send_message")
            qwen_api.send(send_request, callbacks)
            elapsed = time.time() - start_time
            logging.info(
                f"Message received: session={session_id[-6:]}, len={len(response_text)}, time={elapsed:.1f}s, attempt={attempt}"
            )
            break
        except (ChunkedEncodingError, ReadTimeout, RequestsConnectionError) as e:
            stream_already_started = bool(response_text.strip() or thinking_text.strip() or chunks_count > 0)

            if response_text.strip():
                logging.warning(
                    "Stream interrupted after partial response (session=%s, attempt=%s, len=%s): %s",
                    session_id[-6:],
                    attempt,
                    len(response_text),
                    e,
                )
                can_continue = True
                if message_id <= 0:
                    message_id = int(qwen_api.last_message_id or 0)
                break

            if stream_already_started:
                logging.warning(
                    "Stream interrupted after activity; will not resend prompt to busy Qwen session "
                    "(session=%s, attempt=%s, thinking_len=%s, chunks=%s): %s",
                    session_id[-6:],
                    attempt,
                    len(thinking_text),
                    chunks_count,
                    e,
                )
                recovered_thinking, recovered_response, recovered_message_id = _recover_response_from_history(
                    session_id=session_id,
                    min_message_id=max(0, message_id),
                    attempts_override=max(
                        int(config.get("history_recovery_attempts", DEFAULT_HISTORY_RECOVERY_ATTEMPTS)),
                        20,
                    ),
                    interval_override=max(
                        float(config.get("history_recovery_interval_sec", DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC)),
                        1.5,
                    ),
                )
                if recovered_response.strip():
                    thinking_text = recovered_thinking or thinking_text
                    response_text = recovered_response
                    if recovered_message_id > 0:
                        message_id = recovered_message_id
                        qwen_api.last_message_id = recovered_message_id
                    can_continue = False
                    logging.warning(
                        "Recovered active stream from history: session=%s, attempt=%s, recovered_len=%s",
                        session_id[-6:],
                        attempt,
                        len(response_text),
                    )
                    break

                raise QwenProviderError(
                    "Qwen stream was interrupted after generation started; "
                    "the prompt was not resent to avoid duplicating the request. "
                    "History recovery did not return a completed response."
                )

            if attempt <= max_retries:
                backoff = _provider_retry_backoff(min(5.0, 1.0 * attempt))
                logging.warning(
                    "Transient stream error before provider activity, retrying "
                    "(session=%s, attempt=%s/%s, backoff=%.1fs): %s",
                    session_id[-6:],
                    attempt,
                    max_retries + 1,
                    backoff,
                    e,
                )
                time.sleep(backoff)
                continue

            recovered_thinking, recovered_response, recovered_message_id = _recover_response_from_history(
                session_id=session_id,
                min_message_id=max(0, message_id),
            )
            if recovered_response.strip():
                thinking_text = recovered_thinking or thinking_text
                response_text = recovered_response
                if recovered_message_id > 0:
                    message_id = recovered_message_id
                    qwen_api.last_message_id = recovered_message_id
                can_continue = False
                logging.warning(
                    "Recovered after stream failure: session=%s, attempt=%s, recovered_len=%s",
                    session_id[-6:],
                    attempt,
                    len(response_text),
                )
                break

            logging.error(f"Error during message send: {e}")
            raise
        except (QwenRequestEndedError, QwenChatInProgressError, QwenInternalStreamError, QwenProviderError) as e:
            err_text = str(e).lower()

            if "model not found" in err_text:
                current_model = str(config.get("model", DEFAULT_MODEL))
                attempted_model_fallbacks.add(current_model.strip().lower())
                fallback_model = _pick_fallback_model(
                    current_model=current_model,
                    tried_models=attempted_model_fallbacks,
                )
                if fallback_model and fallback_model != current_model and model_fallback_switches < max_model_fallback_switches:
                    model_fallback_switches += 1
                    attempted_model_fallbacks.add(fallback_model.strip().lower())
                    config["model"] = fallback_model
                    save_config(config)
                    _set_model_for_all_clients(fallback_model)
                    logging.warning(
                        "Model '%s' is unavailable; switched to '%s' and retrying send (session=%s, fallback=%s/%s)",
                        current_model,
                        fallback_model,
                        session_id[-6:],
                        model_fallback_switches,
                        max_model_fallback_switches,
                    )
                    time.sleep(0.5)
                    continue
                logging.error(
                    "No usable Qwen fallback model left after provider model error: current=%s tried=%s",
                    current_model,
                    sorted(attempted_model_fallbacks),
                )

            recovered_thinking, recovered_response, recovered_message_id = _recover_response_from_history(
                session_id=session_id,
                min_message_id=max(0, message_id),
            )
            if recovered_response.strip():
                thinking_text = recovered_thinking or thinking_text
                response_text = recovered_response
                if recovered_message_id > 0:
                    message_id = recovered_message_id
                    qwen_api.last_message_id = recovered_message_id
                can_continue = False
                logging.warning(
                    "Recovered after provider send error from history: session=%s, attempt=%s, recovered_len=%s",
                    session_id[-6:],
                    attempt,
                    len(response_text),
                )
                break

            if isinstance(e, QwenChatInProgressError):
                backoff = min(8.0, 1.5 * attempt)
                logging.warning(
                    "Chat still in progress during send; waiting for history instead of resending prompt "
                    "(session=%s, attempt=%s/%s, backoff=%.1fs)",
                    session_id[-6:],
                    attempt,
                    max_retries + 3,
                    backoff,
                )
                time.sleep(backoff)

                recovered_thinking, recovered_response, recovered_message_id = _recover_response_from_history(
                    session_id=session_id,
                    min_message_id=max(0, message_id),
                    attempts_override=max(
                        int(config.get("history_recovery_attempts", DEFAULT_HISTORY_RECOVERY_ATTEMPTS)),
                        12,
                    ),
                    interval_override=max(
                        float(config.get("history_recovery_interval_sec", DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC)),
                        1.5,
                    ),
                )
                if recovered_response.strip():
                    thinking_text = recovered_thinking or thinking_text
                    response_text = recovered_response
                    if recovered_message_id > 0:
                        message_id = recovered_message_id
                        qwen_api.last_message_id = recovered_message_id
                    can_continue = False
                    logging.warning(
                        "Recovered in-progress chat from history: session=%s, attempt=%s, recovered_len=%s",
                        session_id[-6:],
                        attempt,
                        len(response_text),
                    )
                    break

                if attempt <= (max_retries + 2):
                    continue

                raise QwenProviderError(
                    "Qwen provider is still processing the previous message; "
                    "history recovery did not return a completed response."
                )

            if attempt <= max_retries:
                backoff = _provider_retry_backoff(min(5.0, 1.0 * attempt))
                logging.warning(
                    "Provider stream error, retrying send (session=%s, attempt=%s/%s, backoff=%.1fs): %s",
                    session_id[-6:],
                    attempt,
                    max_retries + 1,
                    backoff,
                    e,
                )
                time.sleep(backoff)
                continue

            logging.error(f"Provider error during message send: {e}")
            raise
        except Exception as e:
            logging.error(f"Error during message send: {e}")
            raise

    if not response_text.strip():
        recovered_thinking, recovered_response, recovered_message_id = _recover_response_from_history(
            session_id=session_id,
            min_message_id=max(0, message_id),
        )
        if recovered_response.strip():
            thinking_text = recovered_thinking or thinking_text
            response_text = recovered_response
            if recovered_message_id > 0:
                message_id = recovered_message_id
                qwen_api.last_message_id = recovered_message_id
            can_continue = False

    if not response_text.strip() and message_id <= 0:
        raise QwenProviderError("Qwen provider returned an empty response without message_id")

    return thinking_text, response_text, message_id, can_continue


def _continue_message_sync(
    session_id: str,
    message_id: int,
    thinking_enabled: bool,
    timeout: int = 120,
) -> tuple[str, str, int, bool]:
    """Synchronous continue with retry/partial-result resilience."""
    qwen_api.session_id = session_id
    qwen_api.last_message_id = message_id

    start_time = time.time()
    last_activity = start_time
    response_text = ""
    thinking_text = ""
    new_message_id = 0
    can_continue = False
    chunks_count = 0

    def on_parts(thinking: str, response: str):
        nonlocal thinking_text, response_text, last_activity, chunks_count
        thinking_text = thinking
        response_text = response
        last_activity = time.time()
        chunks_count += 1

        elapsed = last_activity - start_time
        if int(elapsed) % 15 == 0 and elapsed > 0:
            logging.info(f"  -> Continuing stream... {int(elapsed)}s, {chunks_count} chunks")

    def on_complete_parts(thinking: str, response: str):
        nonlocal thinking_text, response_text, last_activity
        thinking_text = thinking
        response_text = response
        last_activity = time.time()

    def on_meta(meta: dict[str, Any]):
        nonlocal new_message_id, can_continue
        new_message_id = int(meta.get("response_message_id", 0))
        can_continue = bool(meta.get("can_continue", False))

        if not can_continue and qwen_api.last_response_meta:
            can_continue = bool(qwen_api.last_response_meta.get("can_continue", False))

        if new_message_id <= 0:
            new_message_id = int(qwen_api.last_message_id or 0)

    max_retries = max(0, int(config.get("stream_retries", DEFAULT_STREAM_RETRIES)))
    attempt = 0

    while True:
        attempt += 1
        try:
            _wait_provider_start_spacing("continue_message")
            qwen_api.continue_message(
                message_id=message_id,
                on_parts=on_parts,
                on_complete_parts=on_complete_parts,
                on_meta=on_meta,
            )
            elapsed = time.time() - start_time
            logging.info(
                f"Continue received: session={session_id[-6:]}, len={len(response_text)}, time={elapsed:.1f}s, attempt={attempt}"
            )
            break
        except (ChunkedEncodingError, ReadTimeout, RequestsConnectionError) as e:
            stream_already_started = bool(response_text.strip() or thinking_text.strip() or chunks_count > 0)

            if response_text.strip():
                logging.warning(
                    "Continue stream interrupted after partial response (session=%s, attempt=%s, len=%s): %s",
                    session_id[-6:],
                    attempt,
                    len(response_text),
                    e,
                )
                can_continue = True
                if new_message_id <= 0:
                    new_message_id = int(qwen_api.last_message_id or message_id or 0)
                break

            if stream_already_started:
                logging.warning(
                    "Continue stream interrupted after activity; will not resend continue request "
                    "(session=%s, attempt=%s, thinking_len=%s, chunks=%s): %s",
                    session_id[-6:],
                    attempt,
                    len(thinking_text),
                    chunks_count,
                    e,
                )
                recovered_thinking, recovered_response, recovered_message_id = _recover_response_from_history(
                    session_id=session_id,
                    min_message_id=max(0, message_id),
                    attempts_override=max(
                        int(config.get("history_recovery_attempts", DEFAULT_HISTORY_RECOVERY_ATTEMPTS)),
                        20,
                    ),
                    interval_override=max(
                        float(config.get("history_recovery_interval_sec", DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC)),
                        1.5,
                    ),
                )
                if recovered_response.strip():
                    thinking_text = recovered_thinking or thinking_text
                    response_text = recovered_response
                    if recovered_message_id > 0:
                        new_message_id = recovered_message_id
                        qwen_api.last_message_id = recovered_message_id
                    else:
                        new_message_id = int(qwen_api.last_message_id or message_id or 0)
                    can_continue = False
                    logging.warning(
                        "Recovered active continue stream from history: session=%s, attempt=%s, recovered_len=%s",
                        session_id[-6:],
                        attempt,
                        len(response_text),
                    )
                    break

                raise QwenProviderError(
                    "Qwen continue stream was interrupted after generation started; "
                    "history recovery did not return a completed response."
                )

            if attempt <= max_retries:
                backoff = _provider_retry_backoff(min(5.0, 1.0 * attempt))
                logging.warning(
                    "Transient continue error before provider activity, retrying "
                    "(session=%s, attempt=%s/%s, backoff=%.1fs): %s",
                    session_id[-6:],
                    attempt,
                    max_retries + 1,
                    backoff,
                    e,
                )
                time.sleep(backoff)
                continue

            recovered_thinking, recovered_response, recovered_message_id = _recover_response_from_history(
                session_id=session_id,
                min_message_id=max(0, message_id),
            )
            if recovered_response.strip():
                thinking_text = recovered_thinking or thinking_text
                response_text = recovered_response
                if recovered_message_id > 0:
                    new_message_id = recovered_message_id
                    qwen_api.last_message_id = recovered_message_id
                else:
                    new_message_id = int(qwen_api.last_message_id or message_id or 0)
                can_continue = False
                logging.warning(
                    "Recovered continue from history after stream failure: session=%s, attempt=%s, recovered_len=%s",
                    session_id[-6:],
                    attempt,
                    len(response_text),
                )
                break

            logging.error(f"Error during continue: {e}")
            raise
        except (QwenRequestEndedError, QwenChatInProgressError, QwenInternalStreamError, QwenProviderError) as e:
            recovered_thinking, recovered_response, recovered_message_id = _recover_response_from_history(
                session_id=session_id,
                min_message_id=max(0, message_id),
            )
            if recovered_response.strip():
                thinking_text = recovered_thinking or thinking_text
                response_text = recovered_response
                if recovered_message_id > 0:
                    new_message_id = recovered_message_id
                    qwen_api.last_message_id = recovered_message_id
                else:
                    new_message_id = int(qwen_api.last_message_id or message_id or 0)
                can_continue = False
                logging.warning(
                    "Recovered continue after provider error from history: session=%s, attempt=%s, recovered_len=%s",
                    session_id[-6:],
                    attempt,
                    len(response_text),
                )
                break

            if isinstance(e, QwenChatInProgressError):
                backoff = min(5.0, 1.0 * attempt)
                logging.warning(
                    "Chat still in progress during continue; waiting for history instead of resending "
                    "(session=%s, attempt=%s/%s, backoff=%.1fs): %s",
                    session_id[-6:],
                    attempt,
                    max_retries + 1,
                    backoff,
                    e,
                )
                time.sleep(backoff)

                recovered_thinking, recovered_response, recovered_message_id = _recover_response_from_history(
                    session_id=session_id,
                    min_message_id=max(0, message_id),
                    attempts_override=max(
                        int(config.get("history_recovery_attempts", DEFAULT_HISTORY_RECOVERY_ATTEMPTS)),
                        12,
                    ),
                    interval_override=max(
                        float(config.get("history_recovery_interval_sec", DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC)),
                        1.5,
                    ),
                )
                if recovered_response.strip():
                    thinking_text = recovered_thinking or thinking_text
                    response_text = recovered_response
                    if recovered_message_id > 0:
                        new_message_id = recovered_message_id
                        qwen_api.last_message_id = recovered_message_id
                    else:
                        new_message_id = int(qwen_api.last_message_id or message_id or 0)
                    can_continue = False
                    logging.warning(
                        "Recovered in-progress continue from history: session=%s, attempt=%s, recovered_len=%s",
                        session_id[-6:],
                        attempt,
                        len(response_text),
                    )
                    break

                if attempt <= max_retries:
                    continue

                raise QwenProviderError(
                    "Qwen provider is still processing the previous continue request; "
                    "history recovery did not return a completed response."
                )

            logging.warning(
                "Stopping continue due to provider terminal state (session=%s, attempt=%s): %s",
                session_id[-6:],
                attempt,
                e,
            )
            can_continue = False
            if new_message_id <= 0:
                new_message_id = int(qwen_api.last_message_id or message_id or 0)
            break
        except Exception as e:
            logging.error(f"Error during continue: {e}")
            raise

    if not response_text.strip() and new_message_id <= 0:
        raise QwenProviderError("Qwen provider returned an empty continue response without message_id")

    return thinking_text, response_text, new_message_id, can_continue


@app.get("/health")
async def health_check():
    """Documentation updated."""
    available = bool(qwen_api and config.get("token"))
    return {
        "status": "ok" if available else "error",
        "model": config.get("model", DEFAULT_MODEL),
        "available": available,
        "has_token": bool(config.get("token")),
        "active_sessions": _active_session_count(),
        "max_active_sessions": _current_max_active_sessions(),
        "provider_max_concurrent_requests": _current_provider_concurrency(),
        "provider_start_throttle_enabled": _current_provider_start_throttle_enabled(),
        "provider_start_interval_sec": _current_provider_start_interval_sec(),
        "provider_start_jitter_sec": _current_provider_start_jitter_sec(),
        "provider_retry_jitter_enabled": _current_provider_retry_jitter_enabled(),
        "provider_retry_jitter_min_sec": _current_provider_retry_jitter_bounds()[0],
        "provider_retry_jitter_max_sec": _current_provider_retry_jitter_bounds()[1],
    }




@app.get("/auth/status")
async def auth_status(
    force: bool = False,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Return current Qwen token status without exposing the token.

    force=false is cache-friendly and safe for page load. force=true refreshes
    the provider /api/user check. For a real active-token smoke test use
    POST /auth/check.
    """
    _require_service_token(credentials)
    return await _check_qwen_auth_status(force=force)


@app.post("/auth/check")
async def auth_check(credentials: HTTPAuthorizationCredentials | None = Security(security)):
    """Smoke-check the active in-memory Qwen token with a minimal chat request."""
    _require_service_token(credentials)
    payload = await run_in_threadpool(_active_token_smoke_check_sync)
    _auth_status_cache["value"] = payload
    _auth_status_cache["checked_at"] = time.monotonic()
    return payload


@app.get("/config")
async def get_config():
    """Documentation updated."""
    return _public_config_payload()


@app.post("/config")
async def update_config(
    update: RuntimeConfigUpdate,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Partial runtime config update used by backend QwenServiceClient.update_config()."""
    _require_service_token(credentials)
    with qwen_request_lock:
        updated = _apply_runtime_config_update(update)
    return {"status": "ok", **updated}


@app.get("/config/auto_continue")
async def get_auto_continue_config():
    """Documentation updated."""
    return {
        "enabled": config.get("auto_continue_enabled", DEFAULT_AUTO_CONTINUE_ENABLED),
        "max_continues": config.get("max_continues", DEFAULT_MAX_CONTINUES),
    }


@app.post("/config/auto_continue")
async def set_auto_continue_config(
    enabled: bool,
    max_continues: int | None = None,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    _require_service_token(credentials)
    update = RuntimeConfigUpdate(auto_continue_enabled=enabled, max_continues=max_continues)
    with qwen_request_lock:
        updated = _apply_runtime_config_update(update)
    return {"status": "ok", "enabled": updated["auto_continue_enabled"], "max_continues": updated["max_continues"]}


@app.post("/config/token")
async def set_token(
    token_config: TokenConfig,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    _require_service_token(credentials)
    global _control_qwen_api
    token = (token_config.token or "").strip()
    with qwen_request_lock:
        config["token"] = token
        save_config(config)
        with _qwen_registry_lock:
            _session_qwen_clients.clear()
            _session_locks.clear()
            active_sessions.clear()
            auto_continue_tracker.clear()
            _control_qwen_api = _new_qwen_api() if token else None
            _auth_status_cache["value"] = None
            _auth_status_cache["checked_at"] = 0.0

    return {"status": "ok", "message": "Токен установлен" if token else "Токен очищен", "available": bool(qwen_api)}

@app.post("/config/token/update-from-har")
async def set_token_from_har(
    har_file: UploadFile = File(...),
    validate: bool = True,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Extract Qwen token from HAR and apply it inside qwen_service.

    qwen_service owns this operation because it also owns provider auth state,
    .env persistence and runtime QwenAPI client registry. The full token is
    never returned in the response.
    """
    _require_service_token(credentials)
    global _control_qwen_api

    filename = har_file.filename or ""
    if filename and not filename.lower().endswith(".har"):
        raise HTTPException(status_code=400, detail="Загрузите HAR-файл с расширением .har")

    content = await har_file.read()
    if len(content) > 120 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="HAR-файл слишком большой: максимум 120 МБ")

    try:
        token, meta = extract_latest_qwen_token_from_har_bytes(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with qwen_request_lock:
        config["token"] = token
        save_config(config)
        with _qwen_registry_lock:
            _session_qwen_clients.clear()
            _session_locks.clear()
            active_sessions.clear()
            auto_continue_tracker.clear()
            _control_qwen_api = _new_qwen_api() if token else None
            _auth_status_cache["value"] = None
            _auth_status_cache["checked_at"] = 0.0

    auth_status = await _check_qwen_auth_status() if validate else _auth_status_payload(
        status="updated",
        valid=False,
        message="Токен установлен, проверка не выполнялась.",
    )

    return {
        "status": "ok",
        "updated": True,
        "token_preview": mask_token(token),
        "token_source": meta,
        "qwen_status": auth_status,
        "message": "Qwen токен обновлён из HAR." if auth_status.get("valid") else "Токен извлечён и установлен, но проверка не прошла.",
    }


@app.post("/config/api_key")
async def set_api_key(
    api_key_config: APIKeyConfig,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    _require_service_token(credentials)
    config["api_key"] = (api_key_config.api_key or "").strip()
    save_config(config)
    return {"status": "ok", "message": "API ключ установлен"}


@app.get("/config/model")
async def get_model():
    """Documentation updated."""
    return {"model": config.get("model", DEFAULT_MODEL)}


@app.post("/config/model")
async def set_model(
    model_config: ModelConfig,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    _require_service_token(credentials)
    update = RuntimeConfigUpdate(
        model=model_config.model,
        thinking_enabled=model_config.thinking_enabled,
        search_enabled=model_config.search_enabled,
        auto_continue_enabled=model_config.auto_continue_enabled,
        max_continues=model_config.max_continues,
    )
    with qwen_request_lock:
        updated = _apply_runtime_config_update(update)

    return {"status": "ok", "model": updated["model"]}


@app.get("/models")
async def list_models(credentials: HTTPAuthorizationCredentials | None = Security(security)):
    """Documentation updated."""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API ?? ???????????????")

    try:
        models = await _run_qwen_locked(qwen_api.fetch_models)
        return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sessions")
async def create_session(
    request: CreateSessionRequest | None = None,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API ?? ???????????????")

    try:
        with _qwen_registry_lock:
            if len(active_sessions) >= _current_max_active_sessions():
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "qwen_max_active_sessions",
                        "message": f"Достигнут лимит активных Qwen-чатов: {_current_max_active_sessions()}.",
                        "active_sessions": len(active_sessions),
                        "max_active_sessions": _current_max_active_sessions(),
                    },
                )

        client = _new_qwen_api()
        if client is None:
            raise HTTPException(status_code=503, detail="Qwen API is not initialized")

        session_id = await run_in_threadpool(lambda: _run_with_provider_slot("create_session", client.create_session))
        logging.info(f"create_session returned: {session_id}")
        if not session_id:
            logging.error("create_session returned None")
            raise HTTPException(status_code=500, detail="Не удалось создать сессию")

        title = (request.title.strip() if request and request.title else "") or "Новый чат"
        if request and request.title:
            try:
                await run_in_threadpool(client.update_session_title, session_id, title)
            except Exception as rename_exc:
                logging.warning("Failed to set session title for %s: %s", session_id, rename_exc)

        _register_session_qwen_api(session_id, client)
        with _qwen_registry_lock:
            active_sessions[session_id] = {
                "session_id": session_id,
                "title": title,
                "created_at": str(Path(__file__).stat().st_mtime),
            }

        return {"session_id": session_id, "title": title}
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error creating session: {e}")
        message = str(e)
        if _is_qwen_token_expired_error(message):
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "qwen_token_expired",
                    "message": "Qwen токен истёк. Обновите QWEN_TOKEN.",
                },
            ) from e
        raise HTTPException(status_code=500, detail=message)


@app.get("/sessions")
async def list_sessions(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API ?? ???????????????")

    try:
        sessions, _ = await _run_qwen_locked(qwen_api.fetch_sessions_page)
        return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API ?? ???????????????")

    try:
        client = _get_session_qwen_api(session_id)
        session_lock = _get_session_lock(session_id)

        def _get_history() -> tuple[dict[str, Any], list[dict[str, Any]]]:
            with session_lock:
                token = _current_qwen_client.set(client)
                try:
                    client.session_id = session_id
                    return client.fetch_history(session_id)
                finally:
                    _current_qwen_client.reset(token)

        history, messages = await run_in_threadpool(_get_history)
        return {"session_id": session_id, "history": history, "messages": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API ?? ???????????????")

    try:
        client = _get_session_qwen_api(session_id)
        session_lock = _get_session_lock(session_id)

        def _delete() -> bool:
            with session_lock:
                return bool(client.delete_session(session_id))

        success = await run_in_threadpool(_delete)
        if success:
            with _qwen_registry_lock:
                active_sessions.pop(session_id, None)
            _drop_session_qwen_api(session_id)
        return {"status": "ok", "deleted": success}
    except Exception as e:
        logging.warning("Remote Qwen session delete failed for %s; dropping local session: %s", session_id[-8:], e)
        with _qwen_registry_lock:
            active_sessions.pop(session_id, None)
        _drop_session_qwen_api(session_id)
        return {
            "status": "warning",
            "deleted": False,
            "local_deleted": True,
            "message": "Локальная Qwen-сессия очищена, удалённый provider-delete не подтвердился.",
            "detail": str(e),
        }


@app.post("/sessions/{session_id}/rename")
async def rename_session(
    session_id: str,
    title_data: dict[str, str],
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API ?? ???????????????")

    title = title_data.get("title", "Новый чат")
    try:
        client = _get_session_qwen_api(session_id)
        session_lock = _get_session_lock(session_id)

        def _rename() -> bool:
            with session_lock:
                return bool(client.update_session_title(session_id, title))

        success = await run_in_threadpool(_rename)
        if success:
            with _qwen_registry_lock:
                if session_id in active_sessions:
                    active_sessions[session_id]["title"] = title
        return {"status": "ok", "title": title}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



def _send_message_impl(request: SendMessageRequest) -> dict[str, Any]:
    """Synchronous implementation of /messages. Caller holds the per-session lock."""
    try:
        with nullcontext():

            _reset_continuation_tracker(request.session_id)


            auto_continue = request.auto_continue
            if auto_continue is None:
                auto_continue = config.get("auto_continue_enabled", DEFAULT_AUTO_CONTINUE_ENABLED)


            thinking_text, response_text, message_id, can_continue = _send_message_sync(
                session_id=request.session_id,
                message=request.message,
                thinking_enabled=request.thinking_enabled,
                search_enabled=request.search_enabled,
                ref_file_ids=request.file_ids,
            )

            logging.info(
                "Message sent: session=%s, message_id=%s, can_continue=%s",
                request.session_id[-6:],
                message_id,
                can_continue,
            )

            if not response_text.strip() and message_id > 0:
                logging.warning(
                    "Initial response is empty, forcing one continue attempt: session=%s, message_id=%s",
                    request.session_id[-6:],
                    message_id,
                )
                forced_thinking, forced_response, forced_message_id, forced_can_continue = _continue_message_sync(
                    session_id=request.session_id,
                    message_id=message_id,
                    thinking_enabled=request.thinking_enabled,
                )
                if forced_thinking:
                    thinking_text = forced_thinking
                if forced_response:
                    response_text = forced_response
                if forced_message_id > 0:
                    message_id = forced_message_id
                can_continue = forced_can_continue


            continue_count = 0
            all_thinking_parts = [thinking_text] if thinking_text else []
            all_response_parts = [response_text] if response_text else []
            last_message_id = message_id
            last_response_text = response_text
            no_progress_streak = 0


            need_continue = auto_continue and _should_auto_continue(last_response_text, can_continue)

            while need_continue and _can_auto_continue(request.session_id):
                continue_count += 1
                _track_continuation(request.session_id, last_message_id)

                logging.info(
                    "Auto-continue #%s for session=%s, message_id=%s",
                    continue_count,
                    request.session_id[-6:],
                    last_message_id,
                )

                cont_thinking, cont_response, new_message_id, new_can_continue = _continue_message_sync(
                    session_id=request.session_id,
                    message_id=last_message_id,
                    thinking_enabled=request.thinking_enabled,
                )

                if cont_thinking:
                    all_thinking_parts.append(cont_thinking)
                if cont_response:
                    all_response_parts.append(cont_response)


                if not (cont_response or "").strip() and new_message_id == last_message_id:
                    no_progress_streak += 1
                    logging.warning(
                        "Auto-continue stopped due to no progress: session=%s, message_id=%s, continue_count=%s",
                        request.session_id[-6:],
                        last_message_id,
                        continue_count,
                    )
                    if no_progress_streak >= 1:
                        can_continue = False
                        break
                else:
                    no_progress_streak = 0

                last_message_id = new_message_id
                last_response_text = cont_response or last_response_text
                can_continue = new_can_continue
                need_continue = auto_continue and _should_auto_continue(last_response_text, can_continue)

                logging.info(
                    "Continue #%s done: new_message_id=%s, can_continue=%s, need_continue=%s",
                    continue_count,
                    new_message_id,
                    can_continue,
                    need_continue,
                )

            full_thinking = "\n\n".join(filter(None, all_thinking_parts))
            full_response = "\n\n".join(filter(None, all_response_parts))

            return {
                "session_id": request.session_id,
                "message": request.message,
                "response": full_response,
                "thinking": full_thinking,
                "thinking_enabled": request.thinking_enabled,
                "search_enabled": request.search_enabled,
                "auto_continue_performed": continue_count > 0,
                "continue_count": continue_count,
                "can_continue": can_continue,


                "message_id": last_message_id,
                "last_message_id": last_message_id,
                "auto_continue_reason": "API flag" if can_continue else "content analysis" if continue_count > 0 else "none",
            }
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error sending message: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/messages")
async def send_message(
    request: SendMessageRequest,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Send one chat message under a per-session lock.

    Different session_id values run in parallel. Only messages inside the same
    session wait for each other, so Qwen provider context/parent ids do not mix.
    """
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API is not initialized")

    started = time.monotonic()
    session_tail = request.session_id[-8:]
    logging.info(
        "Qwen message received: session=%s chars=%s thinking=%s search=%s auto_continue=%s files=%s",
        session_tail,
        len(request.message or ""),
        request.thinking_enabled,
        request.search_enabled,
        request.auto_continue,
        len(request.file_ids or []),
    )

    session_lock = _get_session_lock(request.session_id)
    client = _get_session_qwen_api(request.session_id)

    def _run_for_session() -> dict[str, Any]:
        with session_lock:
            token = _current_qwen_client.set(client)
            try:
                client.session_id = request.session_id
                return _run_with_provider_slot("send_message", lambda: _send_message_impl(request))
            finally:
                _current_qwen_client.reset(token)

    try:
        result = await run_in_threadpool(_run_for_session)
        elapsed = time.monotonic() - started
        logging.info(
            "Qwen message finished: session=%s elapsed=%.2fs response_chars=%s thinking_chars=%s message_id=%s can_continue=%s",
            session_tail,
            elapsed,
            len(str(result.get("response") or "")),
            len(str(result.get("thinking") or "")),
            result.get("message_id") or result.get("last_message_id"),
            result.get("can_continue"),
        )
        return result
    except Exception:
        elapsed = time.monotonic() - started
        logging.exception("Qwen message failed: session=%s elapsed=%.2fs", session_tail, elapsed)
        raise



def _continue_message_impl(
    request: ContinueMessageRequest,
    auto_continue: bool | None = None,
) -> dict[str, Any]:
    """Synchronous implementation of /messages/continue. Caller holds the per-session lock."""
    try:
        with nullcontext():

            do_auto_continue = auto_continue
            if do_auto_continue is None:
                do_auto_continue = config.get("auto_continue_enabled", DEFAULT_AUTO_CONTINUE_ENABLED)


            if request.session_id not in auto_continue_tracker:
                _reset_continuation_tracker(request.session_id)

            all_thinking_parts: list[str] = []
            all_response_parts: list[str] = []
            last_message_id = request.message_id
            continue_count = 0
            can_continue = True
            last_response_text = ""
            no_progress_streak = 0


            cont_thinking, cont_response, new_message_id, new_can_continue = _continue_message_sync(
                session_id=request.session_id,
                message_id=last_message_id,
                thinking_enabled=request.thinking_enabled,
            )

            if cont_thinking:
                all_thinking_parts.append(cont_thinking)
            if cont_response:
                all_response_parts.append(cont_response)

            last_message_id = new_message_id
            last_response_text = cont_response or ""
            can_continue = new_can_continue
            continue_count = 1


            need_continue = do_auto_continue and _should_auto_continue(last_response_text, can_continue)

            while need_continue and _can_auto_continue(request.session_id):
                continue_count += 1
                _track_continuation(request.session_id, last_message_id)

                logging.info(
                    "Auto-continue #%s for session=%s, message_id=%s",
                    continue_count,
                    request.session_id[-6:],
                    last_message_id,
                )

                cont_thinking, cont_response, new_message_id, new_can_continue = _continue_message_sync(
                    session_id=request.session_id,
                    message_id=last_message_id,
                    thinking_enabled=request.thinking_enabled,
                )

                if cont_thinking:
                    all_thinking_parts.append(cont_thinking)
                if cont_response:
                    all_response_parts.append(cont_response)


                if not (cont_response or "").strip() and new_message_id == last_message_id:
                    no_progress_streak += 1
                    logging.warning(
                        "Auto-continue stopped due to no progress: session=%s, message_id=%s, continue_count=%s",
                        request.session_id[-6:],
                        last_message_id,
                        continue_count,
                    )
                    if no_progress_streak >= 1:
                        can_continue = False
                        break
                else:
                    no_progress_streak = 0

                last_message_id = new_message_id
                last_response_text = cont_response or last_response_text
                can_continue = new_can_continue
                need_continue = do_auto_continue and _should_auto_continue(last_response_text, can_continue)

                logging.info(
                    "Continue #%s done: new_message_id=%s, can_continue=%s, need_continue=%s",
                    continue_count,
                    new_message_id,
                    can_continue,
                    need_continue,
                )

            full_thinking = "\n\n".join(filter(None, all_thinking_parts))
            full_response = "\n\n".join(filter(None, all_response_parts))

            return {
                "session_id": request.session_id,


                "message_id": last_message_id,
                "response": full_response,
                "thinking": full_thinking,
                "auto_continue_performed": continue_count > 0,
                "continue_count": continue_count,
                "can_continue": can_continue,
                "last_message_id": last_message_id,
                "auto_continue_reason": "API flag" if can_continue else "content analysis" if continue_count > 1 else "none",
            }
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error continuing message: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/messages/continue")
async def continue_message(
    request: ContinueMessageRequest,
    auto_continue: bool | None = None,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API ?? ???????????????")

    session_lock = _get_session_lock(request.session_id)
    client = _get_session_qwen_api(request.session_id)

    def _run_for_session() -> dict[str, Any]:
        with session_lock:
            token = _current_qwen_client.set(client)
            try:
                client.session_id = request.session_id
                return _continue_message_impl(request, auto_continue)
            finally:
                _current_qwen_client.reset(token)

    return await run_in_threadpool(_run_for_session)


@app.post("/files/upload")
async def upload_file(
    file_path_data: dict[str, str],
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Upload a file to Qwen provider with 3 retries.

    HAR endpoint sequence used by qwen_api.upload_file:
    /files/getstsToken -> OSS PUT -> /files/parse -> /files/parse/status.
    """
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    file_path = file_path_data.get("file_path", "")
    if not file_path:
        raise HTTPException(status_code=400, detail="Не указан путь к файлу")

    try:
        file_info = await _run_qwen_locked(qwen_api.upload_file, file_path, attempts=3)
        if not file_info:
            raise HTTPException(status_code=500, detail="Не удалось загрузить файл")
        return {"file_id": file_info.get("file_id") or file_info.get("id"), "file_info": file_info}
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Qwen file upload failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/files/upload-and-send")
async def upload_file_and_send_message(
    request: FileMessageRequest,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Upload a file and send it with an optional message.

    Tries upload/send in the requested session. If it fails, creates a new chat
    session and retries there. File upload itself is retried 3 times.
    """
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    if not request.file_path:
        raise HTTPException(status_code=400, detail="Не указан путь к файлу")

    try:
        client = _get_session_qwen_api(request.session_id) if request.session_id else _new_qwen_api()
        if client is None:
            raise QwenProviderError("Qwen API не инициализирован")
        if request.session_id:
            client.session_id = request.session_id
        result = await run_in_threadpool(
            client.send_file_message_with_recovery,
            file_path=request.file_path,
            message=request.message or "",
            session_id=request.session_id,
            thinking_enabled=request.thinking_enabled,
            search_enabled=request.search_enabled,
            auto_continue=request.auto_continue,
            session_prompt=request.session_prompt or "",
        )
        sid = str(result.get("session_id") or "")
        if sid:
            _register_session_qwen_api(sid, client)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Qwen upload-and-send failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/files/{file_id}")
async def get_file(
    file_id: str,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API ?? ???????????????")

    if not hasattr(qwen_api, "fetch_files"):
        raise HTTPException(
            status_code=501,
            detail="Qwen provider file lookup is not implemented in the standalone client",
        )

    try:
        file_info = await _run_qwen_locked(qwen_api.fetch_files, [file_id])
        if not file_info:
            raise HTTPException(status_code=404, detail="Файл не найден")
        return {"file_info": file_info[0]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/user/info")
async def get_user_info(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Documentation updated."""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API ?? ???????????????")

    try:
        user_info = await _run_qwen_locked(qwen_api.get_user_info)
        return {"user_info": user_info}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def main():
    """Documentation updated."""

    host = config.get("host", DEFAULT_HOST)
    port = config.get("port", DEFAULT_PORT)

    logging.info(f"Starting Qwen Service on {host}:{port}")
    logging.info(f"Default model: {config.get('model', DEFAULT_MODEL)}")
    logging.info(f"Thinking enabled: {config.get('thinking_enabled', DEFAULT_THINKING_ENABLED)}")
    logging.info(f"Web search enabled: {config.get('search_enabled', DEFAULT_SEARCH_ENABLED)}")
    logging.info(f"Auto-continue: {config.get('auto_continue_enabled', DEFAULT_AUTO_CONTINUE_ENABLED)} (max {config.get('max_continues', DEFAULT_MAX_CONTINUES)})")

    if not config.get("token"):
        logging.warning("WARNING: Qwen token is not set!")
        logging.warning("Run POST /config/token to set the token")

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
