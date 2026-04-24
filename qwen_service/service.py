"""
Qwen Service - Мини-сервис для работы с Qwen API
Запускается как отдельный HTTP сервер с REST API
Полностью автономный - без зависимостей от основного проекта

Конфигурация загружается из .env файла (в корне проекта):
- QWEN_SERVICE_HOST - хост (по умолчанию 127.0.0.1)
- QWEN_SERVICE_PORT - порт (по умолчанию 8767)
- QWEN_TOKEN - токен Qwen API
- QWEN_API_KEY - API ключ для защиты сервиса
- QWEN_MODEL - модель (по умолчанию qwen-coder)
- QWEN_THINKING_ENABLED - режим мышления (по умолчанию true)
- QWEN_SEARCH_ENABLED - поиск в интернете (по умолчанию true)
- QWEN_AUTO_CONTINUE_ENABLED - авто-продолжение (по умолчанию true)
- QWEN_MAX_CONTINUES - макс. количество продолжений (по умолчанию 5)
"""

import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv, set_key
from fastapi import FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

# Загрузка .env из корня проекта
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    logging.info(f".env загружен из: {env_path}")

# Автономный Qwen API клиент (без внешних зависимостей)
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

try:
    from requests.exceptions import ChunkedEncodingError, ConnectionError as RequestsConnectionError, ReadTimeout
except Exception:
    ChunkedEncodingError = Exception  # type: ignore[assignment]
    RequestsConnectionError = Exception  # type: ignore[assignment]
    ReadTimeout = Exception  # type: ignore[assignment]

# Настройки из переменных окружения
DEFAULT_HOST = os.getenv("QWEN_SERVICE_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("QWEN_SERVICE_PORT", "8767"))
DEFAULT_MODEL = os.getenv("QWEN_MODEL", "qwen3.6-plus")
DEFAULT_THINKING_ENABLED = os.getenv("QWEN_THINKING_ENABLED", "true").lower() in ("true", "1", "yes", "вкл")
DEFAULT_SEARCH_ENABLED = os.getenv("QWEN_SEARCH_ENABLED", "true").lower() in ("true", "1", "yes", "вкл")
DEFAULT_AUTO_CONTINUE_ENABLED = os.getenv("QWEN_AUTO_CONTINUE_ENABLED", "true").lower() in ("true", "1", "yes", "вкл")
DEFAULT_MAX_CONTINUES = int(os.getenv("QWEN_MAX_CONTINUES", "5"))
DEFAULT_STREAM_RETRIES = int(os.getenv("QWEN_STREAM_RETRIES", "2"))
DEFAULT_HISTORY_RECOVERY_ATTEMPTS = int(os.getenv("QWEN_HISTORY_RECOVERY_ATTEMPTS", "15"))
DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC = float(os.getenv("QWEN_HISTORY_RECOVERY_INTERVAL_SEC", "2"))

# Конфигурация в памяти
config = {
    "host": DEFAULT_HOST,
    "port": DEFAULT_PORT,
    "token": os.getenv("QWEN_TOKEN", ""),
    "api_key": os.getenv("QWEN_API_KEY", ""),
    "model": DEFAULT_MODEL,
    "thinking_enabled": DEFAULT_THINKING_ENABLED,
    "search_enabled": DEFAULT_SEARCH_ENABLED,
    "auto_continue_enabled": DEFAULT_AUTO_CONTINUE_ENABLED,
    "max_continues": DEFAULT_MAX_CONTINUES,
    "stream_retries": DEFAULT_STREAM_RETRIES,
    "history_recovery_attempts": DEFAULT_HISTORY_RECOVERY_ATTEMPTS,
    "history_recovery_interval_sec": DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC,
}


def setup_qwen_logging() -> Path:
    """Configure qwen service logging to shared logs directory."""
    project_root = Path(__file__).resolve().parent.parent
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "qwen_service.log"

    level_name = os.getenv("LOG_LEVEL", "DEBUG").upper()
    level = getattr(logging, level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d - %(message)s")

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
    logging.info("Logging initialized for qwen_service -> %s", log_file)
    return log_file


setup_qwen_logging()


def save_config(current_config: dict[str, Any]) -> None:
    """Persist runtime config into .env."""
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

# Инициализация API
qwen_token = config.get("token", "")
qwen_api: QwenAPI | None = None

if qwen_token:
    qwen_api = QwenAPI(
        token=qwen_token,
        logger=lambda msg: logging.info(msg),
        default_model=str(config.get("model", DEFAULT_MODEL)),
    )
    logging.info(f"Qwen API ??????????????? ? ???????: {qwen_token[:20]}...")
else:
    logging.warning("Qwen ????? ?? ?????? ? .env!")

# Хранилище сессий в памяти
active_sessions: dict[str, dict[str, Any]] = {}

# Трекинг авто-продолжений: session_id -> {message_ids: set, count: int, last_message_id: int}
auto_continue_tracker: dict[str, dict[str, Any]] = {}


# FastAPI приложение
app = FastAPI(title="Qwen Service", description="Мини-сервис для работы с Qwen API", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer(auto_error=False)


def verify_token(credentials: HTTPAuthorizationCredentials | None = Security(security)) -> bool:
    """Проверка API токена"""
    api_key = config.get("api_key", "")
    if not api_key:
        return True  # Если ключ не установлен, разрешаем все запросы
    if credentials is None:
        return False
    return credentials.credentials == api_key


# Модели данных
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
    auto_continue: bool | None = None  # Переопределение глобальной настройки


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


class TokenConfig(BaseModel):
    token: str


class APIKeyConfig(BaseModel):
    api_key: str


def _can_auto_continue(session_id: str) -> bool:
    """Проверка возможности авто-продолжения"""
    if not config.get("auto_continue_enabled", DEFAULT_AUTO_CONTINUE_ENABLED):
        return False

    max_continues = config.get("max_continues", DEFAULT_MAX_CONTINUES)
    tracker = auto_continue_tracker.get(session_id, {})
    count = tracker.get("count", 0)

    return count < max_continues


def _track_continuation(session_id: str, message_id: int):
    """Отслеживание продолжения"""
    if session_id not in auto_continue_tracker:
        auto_continue_tracker[session_id] = {
            "message_ids": set(),
            "count": 0,
            "last_message_id": None,
        }

    tracker = auto_continue_tracker[session_id]
    # Count every continuation attempt, not only unique message IDs.
    # Otherwise repeated same message_id can bypass max_continues.
    tracker["count"] += 1
    tracker["message_ids"].add(message_id)
    tracker["last_message_id"] = message_id


def _reset_continuation_tracker(session_id: str):
    """Сброс трекера для новой сессии"""
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


def _pick_fallback_model(current_model: str) -> str | None:
    """
    Pick next model when provider returns `Model not found`.
    Priority:
    1) models from provider /models response
    2) static safe fallback list
    """
    normalized_current = (current_model or "").strip().lower()

    provider_candidates: list[str] = []
    if qwen_api:
        try:
            for m in qwen_api.fetch_models() or []:
                if not isinstance(m, dict):
                    continue
                mid = str(m.get("id") or m.get("name") or "").strip()
                if mid:
                    provider_candidates.append(mid)
        except Exception:
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
        if candidate.lower() != normalized_current:
            return candidate
    return None


def _recover_response_from_history(
    session_id: str,
    min_message_id: int = 0,
) -> tuple[str, str, int]:
    """
    Fallback recovery when SSE stream is interrupted.
    Polls chat history for a saved assistant message.
    """
    attempts = max(1, int(config.get("history_recovery_attempts", DEFAULT_HISTORY_RECOVERY_ATTEMPTS)))
    interval = max(0.5, float(config.get("history_recovery_interval_sec", DEFAULT_HISTORY_RECOVERY_INTERVAL_SEC)))

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
    attempt = 0

    while True:
        attempt += 1
        try:
            qwen_api.send(send_request, callbacks)
            elapsed = time.time() - start_time
            logging.info(
                f"Message received: session={session_id[-6:]}, len={len(response_text)}, time={elapsed:.1f}s, attempt={attempt}"
            )
            break
        except (ChunkedEncodingError, ReadTimeout, RequestsConnectionError) as e:
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

            if attempt <= max_retries:
                backoff = min(5.0, 1.0 * attempt)
                logging.warning(
                    "Transient stream error, retrying (session=%s, attempt=%s/%s, backoff=%.1fs): %s",
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
                fallback_model = _pick_fallback_model(current_model=current_model)
                if fallback_model and fallback_model != current_model:
                    config["model"] = fallback_model
                    save_config(config)
                    if qwen_api:
                        qwen_api.set_model(fallback_model)
                    logging.warning(
                        "Model '%s' is unavailable; switched to '%s' and retrying send (session=%s)",
                        current_model,
                        fallback_model,
                        session_id[-6:],
                    )
                    time.sleep(0.5)
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
                    "Recovered after provider send error from history: session=%s, attempt=%s, recovered_len=%s",
                    session_id[-6:],
                    attempt,
                    len(response_text),
                )
                break

            if isinstance(e, QwenChatInProgressError):
                if attempt <= (max_retries + 2):
                    backoff = min(8.0, 1.5 * attempt)
                    logging.warning(
                        "Chat still in progress during send; waiting and retrying (session=%s, attempt=%s/%s, backoff=%.1fs)",
                        session_id[-6:],
                        attempt,
                        max_retries + 3,
                        backoff,
                    )
                    time.sleep(backoff)
                    continue

                logging.warning(
                    "Stopping send due to in-progress state without recovery (session=%s, attempt=%s)",
                    session_id[-6:],
                    attempt,
                )
                can_continue = False
                break

            if attempt <= max_retries:
                backoff = min(5.0, 1.0 * attempt)
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

    def on_complete_parts(thinking: str, response: str):
        nonlocal thinking_text, response_text, last_activity, chunks_count
        thinking_text = thinking
        response_text = response
        last_activity = time.time()
        chunks_count += 1

        elapsed = last_activity - start_time
        if int(elapsed) % 15 == 0 and elapsed > 0:
            logging.info(f"  -> Continuing stream... {int(elapsed)}s, {chunks_count} chunks")

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
            qwen_api.continue_message(
                message_id=message_id,
                on_complete_parts=on_complete_parts,
                on_meta=on_meta,
            )
            elapsed = time.time() - start_time
            logging.info(
                f"Continue received: session={session_id[-6:]}, len={len(response_text)}, time={elapsed:.1f}s, attempt={attempt}"
            )
            break
        except (ChunkedEncodingError, ReadTimeout, RequestsConnectionError) as e:
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

            if attempt <= max_retries:
                backoff = min(5.0, 1.0 * attempt)
                logging.warning(
                    "Transient continue error, retrying (session=%s, attempt=%s/%s, backoff=%.1fs): %s",
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

            if isinstance(e, QwenChatInProgressError) and attempt <= max_retries:
                backoff = min(5.0, 1.0 * attempt)
                logging.warning(
                    "Chat still in progress, retrying continue (session=%s, attempt=%s/%s, backoff=%.1fs): %s",
                    session_id[-6:],
                    attempt,
                    max_retries + 1,
                    backoff,
                    e,
                )
                time.sleep(backoff)
                continue

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

    return thinking_text, response_text, new_message_id, can_continue


@app.get("/health")
async def health_check():
    """Проверка здоровья сервиса"""
    return {"status": "ok", "model": config.get("model", DEFAULT_MODEL)}


@app.get("/config")
async def get_config():
    """Получение текущей конфигурации"""
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
    }


@app.get("/config/auto_continue")
async def get_auto_continue_config():
    """Получение настроек авто-продолжения"""
    return {
        "enabled": config.get("auto_continue_enabled", DEFAULT_AUTO_CONTINUE_ENABLED),
        "max_continues": config.get("max_continues", DEFAULT_MAX_CONTINUES),
    }


@app.post("/config/auto_continue")
async def set_auto_continue_config(enabled: bool, max_continues: int | None = None):
    """Настройка авто-продолжения"""
    config["auto_continue_enabled"] = bool(enabled)
    if max_continues is not None:
        config["max_continues"] = max(1, min(20, int(max_continues)))
    save_config(config)
    return {"status": "ok", "enabled": config["auto_continue_enabled"], "max_continues": config["max_continues"]}


@app.post("/config/token")
async def set_token(token_config: TokenConfig):
    """Установка токена Qwen"""
    config["token"] = token_config.token
    save_config(config)

    # Переинициализация API
    global qwen_api
    qwen_api = QwenAPI(
        token=token_config.token,
        logger=lambda msg: logging.info(msg),
        default_model=str(config.get("model", DEFAULT_MODEL)),
    )

    return {"status": "ok", "message": "Токен установлен"}


@app.post("/config/api_key")
async def set_api_key(api_key_config: APIKeyConfig):
    """Установка API ключа для защиты сервиса"""
    config["api_key"] = api_key_config.api_key
    save_config(config)
    return {"status": "ok", "message": "API ключ установлен"}


@app.get("/config/model")
async def get_model():
    """Получение текущей модели"""
    return {"model": config.get("model", DEFAULT_MODEL)}


@app.post("/config/model")
async def set_model(model_config: ModelConfig):
    """Настройка модели и параметров"""
    config["model"] = model_config.model
    config["thinking_enabled"] = model_config.thinking_enabled
    config["search_enabled"] = model_config.search_enabled
    if hasattr(model_config, "auto_continue_enabled"):
        config["auto_continue_enabled"] = model_config.auto_continue_enabled
    if hasattr(model_config, "max_continues"):
        config["max_continues"] = model_config.max_continues
    save_config(config)

    if qwen_api:
        qwen_api.set_model(model_config.model)

    return {"status": "ok", "model": model_config.model}


@app.get("/models")
async def list_models(credentials: HTTPAuthorizationCredentials | None = Security(security)):
    """Получение списка доступных моделей"""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    try:
        models = qwen_api.fetch_models()
        return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sessions")
async def create_session(
    request: CreateSessionRequest | None = None,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Создание новой сессии чата"""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    try:
        session_id = qwen_api.create_session()
        logging.info(f"create_session returned: {session_id}")
        if not session_id:
            logging.error("create_session returned None")
            raise HTTPException(status_code=500, detail="Не удалось создать сессию")

        title = (request.title.strip() if request and request.title else "") or "Новый чат"
        if request and request.title:
            try:
                qwen_api.update_session_title(session_id, title)
            except Exception as rename_exc:
                logging.warning("Failed to set session title for %s: %s", session_id, rename_exc)

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
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions")
async def list_sessions(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Получение списка сессий"""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    try:
        sessions, _ = qwen_api.fetch_sessions_page()
        return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Получение информации о сессии"""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    try:
        qwen_api.session_id = session_id
        history, messages = qwen_api.fetch_history(session_id)
        return {"session_id": session_id, "history": history, "messages": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Удаление сессии"""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    try:
        success = qwen_api.delete_session(session_id)
        if success and session_id in active_sessions:
            del active_sessions[session_id]
        return {"status": "ok", "deleted": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sessions/{session_id}/rename")
async def rename_session(
    session_id: str,
    title_data: dict[str, str],
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Переименование сессии"""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    title = title_data.get("title", "Новый чат")
    try:
        success = qwen_api.update_session_title(session_id, title)
        if success and session_id in active_sessions:
            active_sessions[session_id]["title"] = title
        return {"status": "ok", "title": title}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/messages")
async def send_message(
    request: SendMessageRequest,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Отправка сообщения в чат с поддержкой авто-продолжения"""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    try:
        # Сброс трекера для нового сообщения (не для продолжения)
        _reset_continuation_tracker(request.session_id)

        # Определение параметра авто-продолжения
        auto_continue = request.auto_continue
        if auto_continue is None:
            auto_continue = config.get("auto_continue_enabled", DEFAULT_AUTO_CONTINUE_ENABLED)

        # Первое отправление сообщения
        thinking_text, response_text, message_id, can_continue = _send_message_sync(
            session_id=request.session_id,
            message=request.message,
            thinking_enabled=request.thinking_enabled,
            search_enabled=request.search_enabled,
            ref_file_ids=request.file_ids,
        )

        logging.info(f"Message sent: session={request.session_id[-6:]}, message_id={message_id}, can_continue={can_continue}")

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

        # Авто-продолнение с использованием автоматического определения
        continue_count = 0
        all_thinking_parts = [thinking_text] if thinking_text else []
        all_response_parts = [response_text] if response_text else []
        last_message_id = message_id
        last_response_text = response_text
        no_progress_streak = 0

        # Определяем необходимость продолжения автоматически
        need_continue = auto_continue and _should_auto_continue(last_response_text, can_continue)

        while need_continue and _can_auto_continue(request.session_id):
            continue_count += 1
            _track_continuation(request.session_id, last_message_id)

            logging.info(f"Auto-continue #{continue_count} for session={request.session_id[-6:]}, message_id={last_message_id} (detected by {'API flag' if can_continue else 'content analysis'})")

            # Продолжение ответа
            cont_thinking, cont_response, new_message_id, new_can_continue = _continue_message_sync(
                session_id=request.session_id,
                message_id=last_message_id,
                thinking_enabled=request.thinking_enabled,
            )

            # Накопление частей
            if cont_thinking:
                all_thinking_parts.append(cont_thinking)
            if cont_response:
                all_response_parts.append(cont_response)

            # Stop infinite loop: no content and no message id progress.
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

            # Снова проверяем необходимость продолжения
            need_continue = auto_continue and _should_auto_continue(last_response_text, can_continue)

            logging.info(f"Continue #{continue_count} done: new_message_id={new_message_id}, can_continue={can_continue}, need_continue={need_continue}")

        # Сборка полного ответа
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
            "last_message_id": last_message_id,
            "auto_continue_reason": "API flag" if can_continue else "content analysis" if continue_count > 0 else "none",
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error sending message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/messages/continue")
async def continue_message(
    request: ContinueMessageRequest,
    auto_continue: bool | None = None,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Продолжение ответа с поддержкой авто-продолжения"""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    try:
        # Определение параметра авто-продолжения
        do_auto_continue = auto_continue
        if do_auto_continue is None:
            do_auto_continue = config.get("auto_continue_enabled", DEFAULT_AUTO_CONTINUE_ENABLED)

        # Инициализация трекера если нужно
        if request.session_id not in auto_continue_tracker:
            _reset_continuation_tracker(request.session_id)

        all_thinking_parts = []
        all_response_parts = []
        last_message_id = request.message_id
        continue_count = 0
        can_continue = True
        last_response_text = ""
        no_progress_streak = 0

        # Первое продолжение
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

        # Авто-продолжение с автоматическим определением
        need_continue = do_auto_continue and _should_auto_continue(last_response_text, can_continue)

        while need_continue and _can_auto_continue(request.session_id):
            continue_count += 1
            _track_continuation(request.session_id, last_message_id)

            logging.info(f"Auto-continue #{continue_count} for session={request.session_id[-6:]}, message_id={last_message_id} (detected by {'API flag' if can_continue else 'content analysis'})")

            # Продолжение ответа
            cont_thinking, cont_response, new_message_id, new_can_continue = _continue_message_sync(
                session_id=request.session_id,
                message_id=last_message_id,
                thinking_enabled=request.thinking_enabled,
            )

            # Накопление частей
            if cont_thinking:
                all_thinking_parts.append(cont_thinking)
            if cont_response:
                all_response_parts.append(cont_response)

            # Stop infinite loop: no content and no message id progress.
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

            # Проверяем необходимость следующего продолжения
            need_continue = do_auto_continue and _should_auto_continue(last_response_text, can_continue)

            logging.info(f"Continue #{continue_count} done: new_message_id={new_message_id}, can_continue={can_continue}, need_continue={need_continue}")

        # Сборка полного ответа
        full_thinking = "\n\n".join(filter(None, all_thinking_parts))
        full_response = "\n\n".join(filter(None, all_response_parts))

        return {
            "session_id": request.session_id,
            "message_id": request.message_id,
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
        logging.exception(f"Error continuing message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/files/upload")
async def upload_file(
    file_path_data: dict[str, str],
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Загрузка файла"""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    file_path = file_path_data.get("file_path", "")
    if not file_path:
        raise HTTPException(status_code=400, detail="Не указан путь к файлу")

    try:
        file_info = qwen_api.upload_file(file_path)
        if not file_info:
            raise HTTPException(status_code=500, detail="Не удалось загрузить файл")
        return {"file_id": file_info.get("id"), "file_info": file_info}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/files/{file_id}")
async def get_file(
    file_id: str,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Получение информации о файле"""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    try:
        file_info = qwen_api.fetch_files([file_id])
        if not file_info:
            raise HTTPException(status_code=404, detail="Файл не найден")
        return {"file_info": file_info[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/user/info")
async def get_user_info(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """Получение информации о пользователе"""
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Неверный API ключ")

    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")

    try:
        user_info = qwen_api.get_user_info()
        return {"user_info": user_info}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def main():
    """Точка входа для запуска сервиса"""
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    host = config.get("host", DEFAULT_HOST)
    port = config.get("port", DEFAULT_PORT)

    logging.info(f"Запуск Qwen Service на {host}:{port}")
    logging.info(f"Модель по умолчанию: {config.get('model', DEFAULT_MODEL)}")
    logging.info(f"Режим мышления: {config.get('thinking_enabled', DEFAULT_THINKING_ENABLED)}")
    logging.info(f"Поиск в интернете: {config.get('search_enabled', DEFAULT_SEARCH_ENABLED)}")
    logging.info(f"Авто-продолжение: {config.get('auto_continue_enabled', DEFAULT_AUTO_CONTINUE_ENABLED)} (макс. {config.get('max_continues', DEFAULT_MAX_CONTINUES)})")

    if not config.get("token"):
        logging.warning("⚠️  ВНИМАНИЕ: Токен Qwen не установлен!")
        logging.warning("Запустите POST /config/token для установки токена")

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
