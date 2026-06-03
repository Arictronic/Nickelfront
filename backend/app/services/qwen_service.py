"""
Qwen Service - Интеграция с Qwen API через standalone HTTP сервис.

Сервис обращается к Qwen Service через HTTP API (порт 8767).
Поддерживает режим мышления, поиск в интернете и авто-продолжение ответов.

Настройки загружаются из переменных окружения:
- QWEN_SERVICE_HOST - хост Qwen Service (по умолчанию 127.0.0.1)
- QWEN_SERVICE_PORT - порт Qwen Service (по умолчанию 8767)
- QWEN_API_KEY - API ключ для авторизации
- QWEN_MODEL - модель (по умолчанию qwen-coder)
- QWEN_THINKING_ENABLED - режим мышления (по умолчанию True)
- QWEN_SEARCH_ENABLED - поиск в интернете (по умолчанию True)
- QWEN_AUTO_CONTINUE_ENABLED - авто-продолжение (по умолчанию True)
- QWEN_MAX_CONTINUES - макс. количество продолжений (по умолчанию 5)
"""

import logging
import threading
from collections import deque
from datetime import datetime
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class QwenService:
    """
    Сервис для взаимодействия с Qwen API через HTTP.

    Обращается к standalone Qwen Service через HTTP API (порт 8767).
    Поддерживает:
    - Создание и управление сессиями
    - Отправка сообщений с режимом мышления
    - Поиск в интернете
    - Авто-продолжение ответов

    Настройки загружаются из переменных окружения:
    - QWEN_SERVICE_HOST - хост Qwen Service (по умолчанию 127.0.0.1)
    - QWEN_SERVICE_PORT - порт Qwen Service (по умолчанию 8767)
    - QWEN_API_KEY - API ключ для авторизации
    - QWEN_MODEL - модель (по умолчанию qwen-coder)
    - QWEN_THINKING_ENABLED - режим мышления (по умолчанию True)
    - QWEN_SEARCH_ENABLED - поиск в интернете (по умолчанию True)
    - QWEN_AUTO_CONTINUE_ENABLED - авто-продолжение (по умолчанию True)
    - QWEN_MAX_CONTINUES - макс. количество продолжений (по умолчанию 5)
    """

    DEFAULT_MODEL = "qwen-coder"
    DEFAULT_THINKING_ENABLED = True
    DEFAULT_SEARCH_ENABLED = True
    DEFAULT_AUTO_CONTINUE_ENABLED = True
    DEFAULT_MAX_CONTINUES = 5

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        api_key: str | None = None,
        model: str | None = None,
        thinking_enabled: bool | None = None,
        search_enabled: bool | None = None,
        auto_continue_enabled: bool | None = None,
        max_continues: int | None = None,
    ):
        """
        Инициализация Qwen сервиса.

        Args:
            host: Хост Qwen Service. По умолчанию из настроек.
            port: Порт Qwen Service. По умолчанию из настроек.
            api_key: API ключ для авторизации. По умолчанию из настроек.
            model: Название модели. По умолчанию из настроек.
            thinking_enabled: Режим мышления. По умолчанию из настроек.
            search_enabled: Поиск в интернете. По умолчанию из настроек.
            auto_continue_enabled: Авто-продолжение. По умолчанию из настроек.
            max_continues: Макс. количество продолжений. По умолчанию из настроек.
        """
        self.host = host or settings.QWEN_SERVICE_HOST
        self.port = port or settings.QWEN_SERVICE_PORT
        self.api_key = api_key or settings.QWEN_API_KEY
        self.base_url = f"http://{self.host}:{self.port}"

        self.model = model or settings.QWEN_MODEL
        self.thinking_enabled = (
            thinking_enabled
            if thinking_enabled is not None
            else settings.QWEN_THINKING_ENABLED
        )
        self.search_enabled = (
            search_enabled
            if search_enabled is not None
            else settings.QWEN_SEARCH_ENABLED
        )
        self.auto_continue_enabled = (
            auto_continue_enabled
            if auto_continue_enabled is not None
            else settings.QWEN_AUTO_CONTINUE_ENABLED
        )
        self.max_continues = (
            max_continues
            if max_continues is not None
            else settings.QWEN_MAX_CONTINUES
        )




        self._session_id: str | None = None



        self._stats_lock = threading.RLock()


        self._request_history: deque = deque(maxlen=100)
        self._active_requests = 0
        self._is_busy = False

        logger.info(
            f"Инициализация QwenService: url={self.base_url}, "
            f"model={self.model}, thinking={self.thinking_enabled}, search={self.search_enabled}"
        )

    def health_status(self) -> dict[str, Any]:
        """Проверить доступность standalone qwen_service с понятной причиной отказа.

        Backend использует это перед отправкой сообщений, чтобы отличать:
        - qwen_service не запущен / не отвечает;
        - qwen_service запущен, но в нём не загружен QWEN_TOKEN;
        - qwen_service вернул статус error/unavailable.
        """
        health, error_type = self._request_with_error("GET", "/health", timeout=3.0)

        if not health:
            reason = "Qwen Service не отвечает"
            if error_type == "timeout":
                reason = "Qwen Service не ответил на /health за 3 секунды"
            elif error_type == "http":
                reason = "HTTP-ошибка при обращении к Qwen Service /health"
            return {
                "status": "unavailable",
                "model": self.model,
                "available": False,
                "base_url": self.base_url,
                "reason": reason,
                "error_type": error_type or "unknown",
            }

        if "available" in health:
            available = bool(health.get("available"))
        else:
            available = str(health.get("status", "")).lower() == "ok"

        reason: str | None = None
        if health.get("auth_valid_known") is False and not available:
            available = False
            reason = "Последняя проверка Qwen auth завершилась ошибкой. Обновите QWEN_TOKEN/session."
        if not available and not reason:
            if health.get("has_token") is False:
                reason = "Qwen Service запущен, но QWEN_TOKEN в нём не загружен"
            else:
                reason = (
                    "Qwen Service вернул недоступный статус: "
                    f"status={health.get('status')!r}, available={health.get('available')!r}"
                )

        return {
            "status": "ok" if available else "unavailable",
            "model": health.get("model", self.model),
            "available": available,
            "base_url": self.base_url,
            "reason": reason,
            "error_type": None,
            "has_token": health.get("has_token"),
            "token_configured": health.get("token_configured", health.get("has_token")),
            "has_api_key": health.get("has_api_key"),
            "auth_required": health.get("auth_required"),
            "auth_valid_known": health.get("auth_valid_known"),
            "auth_checked_at": health.get("auth_checked_at"),
            "service_alive": health.get("service_alive", True),
        }

    @property
    def is_available(self) -> bool:
        """Проверяет доступность standalone qwen_service."""
        return bool(self.health_status().get("available"))

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
        timeout: float = 120.0,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """HTTP request to qwen_service with an explicit error type.

        Returns:
            (payload, None) on success, or (None, error_type) on failure.
            error_type is one of: timeout, http, unknown.
        """
        url = f"{self.base_url}{endpoint}"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            with httpx.Client(timeout=timeout, trust_env=False) as client:
                response = client.request(
                    method,
                    url,
                    headers=headers,
                    json=json_data,
                )
                response.raise_for_status()
                return response.json(), None

        except httpx.TimeoutException as e:
            logger.error(f"Timeout запроса к {endpoint}: {e}")
            return None, "timeout"
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
        timeout: float = 120.0,
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
        """Resolve one backend->qwen_service chat timeout."""
        if timeout is not None and timeout > 0:
            return float(timeout)
        return float(getattr(settings, "QWEN_CHAT_TIMEOUT_SECONDS", 300.0) or 300.0)

    def _retry_on_timeout_enabled(self) -> bool:
        return bool(getattr(settings, "QWEN_CHAT_RETRY_ON_TIMEOUT", True))

    def _mark_request_started(self, *, message_len: int, session_id: str) -> None:
        with self._stats_lock:
            self._active_requests += 1
            self._is_busy = self._active_requests > 0
            self._request_history.append({
                "time": datetime.now(),
                "message_len": message_len,
                "session_id": session_id,
            })

    def _mark_request_finished(self) -> None:
        with self._stats_lock:
            self._active_requests = max(0, self._active_requests - 1)
            self._is_busy = self._active_requests > 0

    def create_session(self) -> str | None:
        """
        Создать новую сессию чата.

        Returns:
            ID сессии или None при ошибке.
        """
        result = self._request("POST", "/sessions")
        if result and "session_id" in result:
            self._session_id = result["session_id"]
            logger.info(f"Создана сессия: {self._session_id}")
            return self._session_id
        return None

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
            logger.info(f"Сессия {session_id} удалена: True")
            return True
        return False

    def list_sessions(self) -> list[dict[str, Any]]:
        """
        Получить список сессий.

        Returns:
            Список сессий или пустой список при ошибке.
        """
        result = self._request("GET", "/sessions")
        return result.get("sessions", []) if result else []

    def get_session_info(self, session_id: str) -> dict[str, Any] | None:
        """
        Получить информацию о сессии.

        Args:
            session_id: ID сессии.

        Returns:
            Информация о сессии или None.
        """
        result = self._request("GET", f"/sessions/{session_id}")
        return result

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

    def send_message(
        self,
        message: str,
        session_id: str | None = None,
        thinking_enabled: bool | None = None,
        search_enabled: bool | None = None,
        file_ids: list[str] | None = None,
        auto_continue: bool | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        Отправить сообщение и получить ответ через HTTP API.

        Важно для параллельных чатов:
        - backend больше не держит глобальный lock на весь запрос;
        - если session_id не передан, всегда создаётся новая Qwen-сессия;
        - сохранённый self._session_id не используется как fallback для нового чата;
        - одинаковый session_id сериализуется уже внутри standalone qwen_service;
        - при timeout можно один раз создать новую сессию и повторить prompt.
        """
        effective_timeout = self._chat_timeout(timeout)
        retry_on_timeout = self._retry_on_timeout_enabled()
        created_for_request = session_id is None

        sid = session_id
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

        if (
            retry_on_timeout
            and result.get("_request_error_type") == "timeout"
        ):
            old_sid = sid
            new_sid = self.create_session()
            if new_sid:
                logger.warning(
                    "Qwen request timed out for session %s; retrying once in fresh session %s",
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
        elif created_for_request:
            self._session_id = sid

        result.pop("_request_error_type", None)
        return result

    def _send_message_once(
        self,
        *,
        message: str,
        sid: str,
        thinking_enabled: bool | None,
        search_enabled: bool | None,
        file_ids: list[str] | None,
        auto_continue: bool | None,
        timeout: float,
    ) -> dict[str, Any]:
        """Send one HTTP request to standalone qwen_service without global serialization."""
        self._mark_request_started(message_len=len(message), session_id=sid)
        try:
            thinking = (
                thinking_enabled
                if thinking_enabled is not None
                else self.thinking_enabled
            )
            search = search_enabled if search_enabled is not None else self.search_enabled
            do_auto_continue = (
                auto_continue
                if auto_continue is not None
                else self.auto_continue_enabled
            )

            logger.info(
                f"Отправка сообщения: session={sid[-6:] if sid else 'new'}, "
                f"thinking={thinking}, search={search}, timeout={timeout}"
            )

            json_data = {
                "session_id": sid,
                "message": message,
                "thinking_enabled": thinking,
                "search_enabled": search,
                "file_ids": file_ids or [],
                "auto_continue": do_auto_continue,
            }

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

            error_text = str(result.get("error") or "").strip()
            if error_text:
                logger.warning(
                    "Qwen service returned error for session %s: %s",
                    sid[-6:] if sid else "new",
                    error_text,
                )
                result.setdefault("session_id", sid)
                result.setdefault("response", "")
                result.setdefault("thinking", "")
                result.setdefault("message_id", 0)
                result.setdefault("continue_count", 0)
                result.setdefault("can_continue", False)
                return result

            result.setdefault("session_id", sid)
            if not result.get("message_id") and result.get("last_message_id"):
                result["message_id"] = result.get("last_message_id")

            continue_count = result.get("continue_count", 0)
            can_continue = result.get("can_continue", False)
            response_text = result.get("response", "")



            if do_auto_continue and continue_count == 0 and can_continue:
                message_id = result.get("message_id", 0)
                add_count, add_text = self._auto_continue(sid, message_id, bool(thinking))

                if add_count > 0:
                    continue_count = add_count
                    response_text = (response_text + "\n\n" + add_text).strip()
                    can_continue = False
                    result["auto_continue_performed"] = True

            result["continue_count"] = continue_count
            result["response"] = response_text
            result["can_continue"] = can_continue

            logger.info(
                f"Ответ получен: session={sid[-6:]}, len={len(response_text)}, continues={continue_count}"
            )
            return result

        except Exception as e:
            logger.error(f"Ошибка отправки сообщения: {e}", exc_info=True)
            return {
                "error": str(e),
                "response": "",
                "thinking": "",
                "session_id": sid,
                "message_id": 0,
                "continue_count": 0,
                "can_continue": False,
            }
        finally:
            self._mark_request_finished()

    def _should_continue(self, response: str) -> bool:
        """
        Проверка необходимости продолжения ответа.

        Args:
            response: Текст ответа.

        Returns:
            True если нужно продолжить.
        """
        if not response or len(response) < 50:
            return False

        text = response.strip()


        incomplete_endings = [
            "...",
            "—",
            "–",
            " и ",
            " или ",
            " а ",
            "также",
            "кроме того",
            "далее",
            "например",
            "в частности",
            "следующ",
            "этот",
            "эти ",
            "1.",
            "2.",
            "3.",
            "•",
            "-",
            "*",
            "```",
        ]

        text_lower = text.lower()
        for ending in incomplete_endings:
            if text_lower.endswith(ending):
                return True


        if (
            text.count("(") > text.count(")")
            or text.count("[") > text.count("]")
            or text.count("{") > text.count("}")
        ):
            return True


        if text.count("'") % 2 != 0 or text.count('"') % 2 != 0:
            return True


        if text.count("```") % 2 != 0:
            return True


        if text.endswith(".") or text.endswith("!") or text.endswith("?"):
            return False

        return True

    def _auto_continue(
        self,
        session_id: str,
        message_id: int,
        thinking_enabled: bool,
    ) -> tuple[int, str]:
        """
        Авто-продолжение ответа.

        Args:
            session_id: ID сессии.
            message_id: ID последнего сообщения.
            thinking_enabled: Режим мышления.

        Returns:
            Кортеж (количество продолжений, полный текст продолжений).
        """
        if not self.auto_continue_enabled:
            return 0, ""

        continue_count = 0
        all_response_parts: list[str] = []
        current_message_id = message_id

        while continue_count < self.max_continues:
            logger.info(f"Авто-продолжение #{continue_count + 1}")

            result = self.continue_message(
                session_id=session_id,
                message_id=current_message_id,
                thinking_enabled=thinking_enabled,
            )

            response = result.get("response", "")
            new_message_id = result.get("message_id", 0)
            can_continue = result.get("can_continue", False)

            if response:
                all_response_parts.append(response)

            if not can_continue and not self._should_continue(response):
                break

            current_message_id = new_message_id
            continue_count += 1

        return continue_count, "\n\n".join(all_response_parts)

    def continue_message(
        self,
        session_id: str,
        message_id: int,
        thinking_enabled: bool = True,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """
        Продолжить ответ через HTTP API.

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

        return result or {
            "error": "Ошибка продолжения сообщения",
            "response": "",
            "thinking": "",
            "message_id": 0,
            "can_continue": False,
        }

    def get_config(self) -> dict[str, Any]:
        """Получить текущую конфигурацию из standalone qwen_service.

        Раньше backend отдавал только локально сохранённые значения, поэтому UI мог
        показывать устаревшую конфигурацию. Теперь источник истины — /config qwen_service.
        """
        remote = self._request("GET", "/config", timeout=5.0) or {}

        if remote.get("model"):
            self.model = str(remote.get("model"))
        if "thinking_enabled" in remote:
            self.thinking_enabled = bool(remote.get("thinking_enabled"))
        if "search_enabled" in remote:
            self.search_enabled = bool(remote.get("search_enabled"))
        if "auto_continue_enabled" in remote:
            self.auto_continue_enabled = bool(remote.get("auto_continue_enabled"))
        if "max_continues" in remote:
            try:
                self.max_continues = int(remote.get("max_continues"))
            except (TypeError, ValueError):
                pass

        return {
            "model": remote.get("model", self.model),
            "thinking_enabled": remote.get("thinking_enabled", self.thinking_enabled),
            "search_enabled": remote.get("search_enabled", self.search_enabled),
            "auto_continue_enabled": remote.get("auto_continue_enabled", self.auto_continue_enabled),
            "max_continues": remote.get("max_continues", self.max_continues),
            "stream_retries": remote.get("stream_retries"),
            "history_recovery_attempts": remote.get("history_recovery_attempts"),
            "history_recovery_interval_sec": remote.get("history_recovery_interval_sec"),
            "has_token": remote.get("has_token"),
            "has_api_key": remote.get("has_api_key"),
            "auth_required": remote.get("auth_required"),
            "allow_unauth_without_api_key": remote.get("allow_unauth_without_api_key"),
            "is_available": self.is_available,
            "base_url": self.base_url,
        }

    def get_stats(self) -> dict[str, Any]:
        """
        Получить статистику сервиса.

        Returns:
            Словарь со статистикой.
        """
        now = datetime.now()
        with self._stats_lock:
            recent_requests = sum(
                1 for req in self._request_history
                if (now - req["time"]).total_seconds() < 60
            )
            return {
                "is_busy": self._is_busy,
                "active_requests": self._active_requests,
                "requests_last_minute": recent_requests,
                "total_requests": len(self._request_history),
                "session_id": self._session_id,
            }

    def is_busy(self) -> bool:
        """
        Проверить, занят ли сервис обработкой запроса.

        Returns:
            True если сервис обрабатывает запрос.
        """
        with self._stats_lock:
            return self._active_requests > 0

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
        """Обновить конфигурацию standalone qwen_service через POST /config."""
        payload: dict[str, Any] = {}
        if model is not None:
            payload["model"] = model
        if thinking_enabled is not None:
            payload["thinking_enabled"] = thinking_enabled
        if search_enabled is not None:
            payload["search_enabled"] = search_enabled
        if auto_continue_enabled is not None:
            payload["auto_continue_enabled"] = auto_continue_enabled
        if max_continues is not None:
            payload["max_continues"] = max(1, min(20, int(max_continues)))
        if stream_retries is not None:
            payload["stream_retries"] = max(0, min(10, int(stream_retries)))
        if history_recovery_attempts is not None:
            payload["history_recovery_attempts"] = max(1, min(60, int(history_recovery_attempts)))
        if history_recovery_interval_sec is not None:
            payload["history_recovery_interval_sec"] = max(0.2, min(30.0, float(history_recovery_interval_sec)))

        if payload:
            result = self._request("POST", "/config", json_data=payload, timeout=10.0)
            if not result:
                logger.warning("Failed to update standalone qwen_service config; keeping local fallback values")
            else:
                logger.info("Standalone qwen_service config updated: %s", {k: v for k, v in payload.items() if k != "token"})


        updated = self.get_config()
        self.model = str(updated.get("model") or self.model)
        self.thinking_enabled = bool(updated.get("thinking_enabled", self.thinking_enabled))
        self.search_enabled = bool(updated.get("search_enabled", self.search_enabled))
        self.auto_continue_enabled = bool(updated.get("auto_continue_enabled", self.auto_continue_enabled))
        try:
            self.max_continues = int(updated.get("max_continues", self.max_continues))
        except (TypeError, ValueError):
            pass

        return updated



_qwen_service: QwenService | None = None


def get_qwen_service() -> QwenService:
    """
    Получить экземпляр QwenService (singleton).

    Returns:
        QwenService: Глобальный экземпляр сервиса.
    """
    global _qwen_service
    if _qwen_service is None:
        _qwen_service = QwenService()
    return _qwen_service
