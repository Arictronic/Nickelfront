"""
Qwen Service Client - Клиент для standalone Qwen Service.

Обращается к Qwen Service через HTTP API (порт 8767).
Используется когда Qwen Service запущен как отдельный сервер.
"""

import logging
import os
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class QwenServiceClient:
    """
    Клиент для работы с standalone Qwen Service через HTTP API.

    Endpoints:
    - POST /sessions - создать сессию
    - GET /sessions - список сессий
    - GET /sessions/{id} - информация о сессии
    - DELETE /sessions/{id} - удалить сессию
    - POST /sessions/{id}/rename - переименовать сессию
    - POST /messages - отправить сообщение
    - POST /messages/continue - продолжить ответ
    - GET /health - проверка здоровья
    - GET /config - конфигурация
    - POST /config - обновить конфигурацию
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
        queue_enabled: bool | None = None,
    ):
        """
        Инициализация клиента.

        Args:
            base_url: URL Qwen Service. По умолчанию из настроек.
            api_key: API ключ для авторизации. По умолчанию из настроек.
            timeout: Таймаут запросов в секундах.
        """
        self.base_url = (
            base_url
            or f"http://{settings.QWEN_SERVICE_HOST}:{settings.QWEN_SERVICE_PORT}"
        )
        self.api_key = api_key or settings.QWEN_API_KEY
        self.timeout = timeout
        self.queue_enabled = settings.QWEN_QUEUE_ENABLED if queue_enabled is None else queue_enabled
        self._session_id: str | None = None

        logger.debug(
            f"Инициализация QwenServiceClient: url={self.base_url}, "
            f"api_key={'***' if self.api_key else 'None'}"
        )

    @property
    def headers(self) -> dict[str, str]:
        """Заголовки для авторизации."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @property
    def session_id(self) -> str | None:
        """Текущий ID сессии."""
        return self._session_id

    @session_id.setter
    def session_id(self, value: str):
        """Установка ID сессии."""
        self._session_id = value

    def _request_with_error(
        self,
        method: str,
        endpoint: str,
        json_data: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """
        HTTP request helper with explicit error type.

        Returns:
            (payload, None) on success, or (None, error_type) on failure.
            error_type is one of: timeout, http, unknown.
        """
        url = f"{self.base_url}{endpoint}"
        request_timeout = timeout or self.timeout

        try:
            with httpx.Client(timeout=request_timeout, trust_env=False) as client:
                response = client.request(
                    method,
                    url,
                    headers=self.headers,
                    json=json_data,
                )
                response.raise_for_status()
                try:
                    return response.json(), None
                except ValueError as e:
                    logger.error("Qwen Service returned non-JSON response for %s: %s", endpoint, e)
                    return {
                        "status": "bad_response",
                        "valid": False,
                        "expired": False,
                        "token_configured": True,
                        "message": "qwen_service вернул не-JSON ответ. Проверьте лог qwen_service и повторите проверку.",
                    }, "invalid_json"

        except httpx.TimeoutException as e:
            logger.error(f"Timeout запроса к {endpoint}: {e}")
            return None, "timeout"
        except httpx.HTTPStatusError as e:
            detail: Any = None
            try:
                payload = e.response.json()
                detail = payload.get("detail") if isinstance(payload, dict) else payload
            except Exception:
                detail = e.response.text

            detail_text = detail if isinstance(detail, str) else str(detail or e)
            lowered = detail_text.lower()
            status_code = getattr(e.response, "status_code", None)
            if "qwen_token_expired" in lowered or "token has expired" in lowered or "please log in again" in lowered:
                logger.error("Qwen auth error on %s: token expired", endpoint)
                return {
                    "error": "qwen_token_expired",
                    "message": "Qwen токен истёк. Обновите QWEN_TOKEN.",
                    "response": "",
                    "thinking": "",
                    "can_continue": False,
                }, "auth_expired"
            if status_code == 429 or "too many requests" in lowered or "rate limit" in lowered:
                logger.warning("Qwen provider rate limit on %s: %s", endpoint, detail_text)
                return {
                    "error": "qwen_rate_limited",
                    "message": "Qwen ограничил частоту запросов. Токен может быть действительным, но нагрузку нужно снизить.",
                    "response": "",
                    "thinking": "",
                    "can_continue": False,
                }, "rate_limited"

            logger.error(f"HTTP ошибка запроса к {endpoint}: {e}; detail={detail_text}")
            return None, "http"
        except httpx.HTTPError as e:
            logger.error(f"HTTP ошибка запроса к {endpoint}: {e}")
            return None, "http"
        except Exception as e:
            logger.error(f"Ошибка запроса к {endpoint}: {e}")
            return None, "unknown"

    def _request(
        self,
        method: str,
        endpoint: str,
        json_data: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        """Backward-compatible wrapper for non-message endpoints."""
        result, _error_type = self._request_with_error(
            method=method,
            endpoint=endpoint,
            json_data=json_data,
            timeout=timeout,
        )
        return result

    def _chat_timeout(self, timeout: float | None) -> float:
        if timeout is not None and timeout > 0:
            return float(timeout)
        return float(getattr(settings, "QWEN_CHAT_TIMEOUT_SECONDS", self.timeout) or self.timeout)

    def _retry_on_timeout_enabled(self) -> bool:
        return bool(getattr(settings, "QWEN_CHAT_RETRY_ON_TIMEOUT", True))

    def health_check(self) -> dict[str, Any]:
        """
        Проверка здоровья сервиса.

        Returns:
            Статус сервиса.
        """

        result = self._request("GET", "/health", timeout=3.0)
        return result or {"status": "error", "available": False}


    def get_auth_status(self, *, force: bool = False) -> dict[str, Any]:
        """Return current in-memory Qwen token status from qwen_service.

        force=False uses qwen_service cache/passive status and is safe for page load.
        force=True asks qwen_service to refresh the provider /api/user check.
        """
        endpoint = "/auth/status?force=true" if force else "/auth/status"
        result = self._request("GET", endpoint, timeout=10.0)
        if not result:
            return {
                "status": "service_unavailable",
                "valid": False,
                "expired": False,
                "token_configured": False,
                "message": "Qwen Service недоступен или не вернул статус.",
            }
        return result

    def check_active_token(self) -> dict[str, Any]:
        """Smoke-check the current token already loaded into qwen_service.

        HAR is not used here. qwen_service creates a temporary chat using the
        active in-memory/.env token and sends a minimal prompt.
        """
        result = self._request("POST", "/auth/check", timeout=90.0)
        if not result:
            return {
                "status": "service_unavailable",
                "valid": False,
                "expired": False,
                "token_configured": False,
                "message": "Qwen Service недоступен или не смог проверить текущий токен.",
            }
        return result

    def update_token(self, token: str) -> dict[str, Any]:
        """Set a new Qwen provider token in running qwen_service and persist it to .env."""
        result = self._request("POST", "/config/token", json_data={"token": token}, timeout=15.0)
        if not result:
            return {"status": "error", "message": "Не удалось обновить Qwen токен в qwen_service."}
        return result

    def update_token_from_har_bytes(
        self,
        content: bytes,
        filename: str = "qwen.har",
        *,
        validate: bool = True,
    ) -> dict[str, Any]:
        """Upload HAR to qwen_service so it extracts and applies QWEN_TOKEN itself."""
        url = f"{self.base_url}/config/token/update-from-har"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        params = {"validate": str(validate).lower()}
        safe_filename = filename or "qwen.har"

        try:
            with httpx.Client(timeout=60.0, trust_env=False) as client:
                response = client.post(
                    url,
                    headers=headers,
                    params=params,
                    files={"har_file": (safe_filename, content, "application/json")},
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            detail: Any
            try:
                payload = exc.response.json()
                detail = payload.get("detail") if isinstance(payload, dict) else payload
            except Exception:
                detail = exc.response.text
            logger.error("Qwen HAR token update failed: %s", detail)
            return {"status": "error", "message": str(detail or exc)}
        except Exception as exc:
            logger.error("Qwen HAR token update failed: %s", exc)
            return {"status": "error", "message": str(exc)}

    def get_config(self) -> dict[str, Any]:
        """
        Получить конфигурацию сервиса.

        Returns:
            Конфигурация сервиса.
        """
        result = self._request("GET", "/config")
        return result or {}

    def update_config(
        self,
        model: str | None = None,
        thinking_enabled: bool | None = None,
        search_enabled: bool | None = None,
        auto_continue_enabled: bool | None = None,
        max_continues: int | None = None,
        stream_retries: int | None = None,
        history_recovery_attempts: int | None = None,
        history_recovery_interval_sec: float | None = None,
    ) -> dict[str, Any]:
        """
        Обновить конфигурацию сервиса.

        Args:
            model: Модель.
            thinking_enabled: Режим мышления.
            search_enabled: Поиск.
            auto_continue_enabled: Авто-продолжение.
            max_continues: Макс. продолжений.
            stream_retries: Количество retry для нестабильного SSE stream.
            history_recovery_attempts: Попытки восстановления ответа из истории.
            history_recovery_interval_sec: Интервал между попытками восстановления.

        Returns:
            Новая конфигурация.
        """
        json_data = {}
        if model:
            json_data["model"] = model
        if thinking_enabled is not None:
            json_data["thinking_enabled"] = thinking_enabled
        if search_enabled is not None:
            json_data["search_enabled"] = search_enabled
        if auto_continue_enabled is not None:
            json_data["auto_continue_enabled"] = auto_continue_enabled
        if max_continues is not None:
            json_data["max_continues"] = max_continues
        if stream_retries is not None:
            json_data["stream_retries"] = stream_retries
        if history_recovery_attempts is not None:
            json_data["history_recovery_attempts"] = history_recovery_attempts
        if history_recovery_interval_sec is not None:
            json_data["history_recovery_interval_sec"] = history_recovery_interval_sec

        result = self._request("POST", "/config", json_data=json_data)
        return result or {}

    def create_session(self, title: str | None = None) -> str | None:
        """
        Создать новую сессию.

        Args:
            title: Заголовок сессии.

        Returns:
            ID сессии или None.
        """
        json_data = {}
        if title:
            json_data["title"] = title

        result = self._request("POST", "/sessions", json_data=json_data)
        if result and "session_id" in result:
            self._session_id = result["session_id"]
            logger.info(f"Создана сессия: {self._session_id}")
            return self._session_id
        return None

    def list_sessions(self) -> list[dict[str, Any]]:
        """
        Получить список сессий.

        Returns:
            Список сессий.
        """
        result = self._request("GET", "/sessions")
        return result.get("sessions", []) if result else []

    def get_session_info(self, session_id: str) -> dict[str, Any] | None:
        """
        Получить информацию о сессии.

        Args:
            session_id: ID сессии.

        Returns:
            Информация о сессии.
        """
        result = self._request("GET", f"/sessions/{session_id}")
        return result

    def delete_session(self, session_id: str) -> bool:
        """
        Удалить сессию.

        Args:
            session_id: ID сессии.

        Returns:
            True если успешно.
        """
        result = self._request("DELETE", f"/sessions/{session_id}")
        if result and result.get("deleted"):
            if self._session_id == session_id:
                self._session_id = None
            logger.info(f"Сессия {session_id} удалена")
            return True
        return False

    def rename_session(self, session_id: str, title: str) -> bool:
        """
        Переименовать сессию.

        Args:
            session_id: ID сессии.
            title: Новый заголовок.

        Returns:
            True если успешно.
        """
        result = self._request(
            "POST",
            f"/sessions/{session_id}/rename",
            json_data={"title": title},
        )
        if result and result.get("status") == "ok":
            logger.info(f"Сессия {session_id} переименована в '{title}'")
            return True
        return False

    @staticmethod
    def _queue_disabled_by_env() -> bool:
        value = os.getenv("QWEN_QUEUE_ENABLED", "").strip().lower()
        return value in {"0", "false", "no", "off"}

    def _should_use_queue(self, purpose: str | None = None) -> bool:
        if not self.queue_enabled or self._queue_disabled_by_env():
            return False

        if os.getenv("QWEN_GATEWAY_WORKER", "").strip().lower() in {"1", "true", "yes", "on"}:
            return False
        return True

    def send_message(
        self,
        message: str,
        session_id: str | None = None,
        thinking_enabled: bool = True,
        search_enabled: bool = False,
        file_ids: list[str] | None = None,
        auto_continue: bool | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        Отправить сообщение и получить ответ.

        Важно:
        - если session_id не передан, создаётся новая Qwen-сессия;
        - сохранённый self._session_id не используется как fallback для новых задач;
        - очередь qwen получает ровно тот session_id, который передал вызывающий код;
        - при timeout прямого запроса к qwen_service выполняется один retry в новой сессии.
        """
        sid = session_id
        effective_timeout = self._chat_timeout(timeout)

        if self._should_use_queue():
            try:
                from app.services.qwen_queue_client import send_qwen_message_via_queue

                result = send_qwen_message_via_queue(
                    message=message,
                    session_id=sid,
                    thinking_enabled=thinking_enabled,
                    search_enabled=search_enabled,
                    file_ids=file_ids or [],
                    auto_continue=auto_continue,
                    timeout=effective_timeout,
                    purpose="backend-qwen-client",
                )
                if result.get("session_id"):
                    self._session_id = str(result["session_id"])
                return result
            except Exception as exc:
                logger.exception("Failed to enqueue Qwen request")
                return {
                    "error": f"Failed to enqueue Qwen request: {exc}",
                    "response": "",
                    "thinking": "",
                    "message_id": 0,
                    "continue_count": 0,
                    "can_continue": False,
                }

        if not sid:
            sid = self.create_session()
            if not sid:
                return {
                    "error": "Не удалось создать сессию",
                    "response": "",
                    "thinking": "",
                    "message_id": 0,
                    "continue_count": 0,
                    "can_continue": False,
                }

        result = self._send_message_once(
            message=message,
            sid=sid,
            thinking_enabled=thinking_enabled,
            search_enabled=search_enabled,
            file_ids=file_ids,
            auto_continue=auto_continue,
            timeout=effective_timeout,
        )

        if self._retry_on_timeout_enabled() and result.get("_request_error_type") == "timeout":
            old_sid = sid
            new_sid = self.create_session()
            if new_sid:
                logger.warning(
                    "Qwen direct request timed out for session %s; retrying once in fresh session %s",
                    old_sid[-6:] if old_sid else "none",
                    new_sid[-6:],
                )
                retry_result = self._send_message_once(
                    message=message,
                    sid=new_sid,
                    thinking_enabled=thinking_enabled,
                    search_enabled=search_enabled,
                    file_ids=file_ids,
                    auto_continue=auto_continue,
                    timeout=effective_timeout,
                )
                retry_result["recreated_session"] = True
                retry_result["previous_session_id"] = old_sid
                retry_result["session_recreated_reason"] = "timeout"
                result = retry_result
            else:
                result["session_id"] = old_sid
                result["recreated_session"] = False
                result["session_recreated_reason"] = "timeout_new_session_failed"

        if result.get("session_id"):
            self._session_id = str(result["session_id"])
        result.pop("_request_error_type", None)
        return result

    def _send_message_once(
        self,
        *,
        message: str,
        sid: str,
        thinking_enabled: bool,
        search_enabled: bool,
        file_ids: list[str] | None,
        auto_continue: bool | None,
        timeout: float,
    ) -> dict[str, Any]:
        json_data = {
            "session_id": sid,
            "message": message,
            "thinking_enabled": thinking_enabled,
            "search_enabled": search_enabled,
            "file_ids": file_ids or [],
        }

        if auto_continue is not None:
            json_data["auto_continue"] = auto_continue

        logger.info(
            f"Отправка сообщения: session={sid[-6:] if sid else 'new'}, "
            f"thinking={thinking_enabled}, search={search_enabled}, timeout={timeout}"
        )

        result, error_type = self._request_with_error(
            "POST",
            "/messages",
            json_data=json_data,
            timeout=timeout,
        )

        if not result:
            return {
                "error": "Timeout запроса к Qwen Service" if error_type == "timeout" else "Ошибка запроса к Qwen Service",
                "response": "",
                "thinking": "",
                "session_id": sid,
                "message_id": 0,
                "continue_count": 0,
                "can_continue": False,
                "_request_error_type": error_type,
            }

        result.setdefault("session_id", sid)
        if result.get("error"):
            result.setdefault("response", "")
            result.setdefault("thinking", "")
            result.setdefault("message_id", 0)
            result.setdefault("continue_count", 0)
            result.setdefault("can_continue", False)
            return result

        if not result.get("message_id") and result.get("last_message_id"):
            result["message_id"] = result.get("last_message_id")

        logger.info(
            f"Ответ получен: session={sid[-6:]}, len={len(result.get('response', ''))}, "
            f"continues={result.get('continue_count', 0)}"
        )
        return result

    def continue_message(
        self,
        session_id: str,
        message_id: int,
        thinking_enabled: bool = True,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """
        Продолжить ответ.

        Args:
            session_id: ID сессии.
            message_id: ID сообщения для продолжения.
            thinking_enabled: Режим мышления.
            timeout: Таймаут запроса.

        Returns:
            Продолжение ответа.
        """
        json_data = {
            "session_id": session_id,
            "message_id": message_id,
            "thinking_enabled": thinking_enabled,
        }

        result = self._request(
            "POST",
            "/messages/continue",
            json_data=json_data,
            timeout=timeout,
        )

        if result and not result.get("message_id") and result.get("last_message_id"):
            result["message_id"] = result.get("last_message_id")

        return result or {
            "error": "Ошибка продолжения сообщения",
            "response": "",
            "thinking": "",
            "message_id": 0,
            "can_continue": False,
        }

    def upload_file(self, file_path: str, timeout: float = 180.0) -> dict[str, Any]:
        """Upload one file through standalone qwen_service.

        qwen_service performs provider upload retries internally.
        """
        result = self._request(
            "POST",
            "/files/upload",
            json_data={"file_path": file_path},
            timeout=timeout,
        )
        return result or {"error": "Ошибка загрузки файла в Qwen Service", "file_id": None}

    def upload_file_and_send_message(
        self,
        *,
        file_path: str,
        message: str = "",
        session_id: str | None = None,
        thinking_enabled: bool = True,
        search_enabled: bool = False,
        auto_continue: bool | None = None,
        timeout: float = 240.0,
        session_prompt: str | None = None,
    ) -> dict[str, Any]:
        """Upload file and send it with optional message.

        Standalone qwen_service retries file upload 3 times and creates a new
        chat session if upload/send fails in the current session.
        """
        result = self._request(
            "POST",
            "/files/upload-and-send",
            json_data={
                "file_path": file_path,
                "message": message or "",
                "session_id": session_id,
                "thinking_enabled": thinking_enabled,
                "search_enabled": search_enabled,
                "auto_continue": auto_continue,
                "session_prompt": session_prompt or "",
            },
            timeout=timeout,
        )
        if result and result.get("session_id"):
            self._session_id = str(result["session_id"])
        return result or {
            "error": "Ошибка отправки файла в Qwen Service",
            "response": "",
            "thinking": "",
            "file_id": None,
            "session_id": session_id,
        }

    def is_available(self) -> bool:
        """
        Проверить доступность сервиса.

        Standalone qwen_service can return HTTP 200 with ``status=error`` or
        ``available=false`` when QWEN_TOKEN is missing. Treat the explicit
        ``available`` flag as the source of truth and keep ``status=ok`` only as
        a backward-compatible fallback for older service versions.
        """
        health = self.health_check()
        if "available" in health:
            return bool(health.get("available"))
        return str(health.get("status", "")).lower() == "ok"



_qwen_client: QwenServiceClient | None = None


def get_qwen_client() -> QwenServiceClient:
    """
    Получить экземпляр QwenServiceClient (singleton).

    Returns:
        Клиент для работы с Qwen Service.
    """
    global _qwen_client
    if _qwen_client is None:
        _qwen_client = QwenServiceClient()
    return _qwen_client
