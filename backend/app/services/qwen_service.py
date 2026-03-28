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

        # Блокировка для потокобезопасности
        self._lock = threading.RLock()

        # Статистика запросов
        self._request_history: deque = deque(maxlen=100)
        self._is_busy = False

        logger.info(
            f"Инициализация QwenService: url={self.base_url}, "
            f"model={self.model}, thinking={self.thinking_enabled}, search={self.search_enabled}"
        )

    @property
    def is_available(self) -> bool:
        """Проверяет доступность сервиса."""
        try:
            with httpx.Client(timeout=5.0, trust_env=False) as client:
                response = client.get(f"{self.base_url}/health")
                return response.status_code == 200
        except Exception:
            return False

    @property
    def session_id(self) -> str | None:
        """Текущий ID сессии."""
        return self._session_id

    @session_id.setter
    def session_id(self, value: str):
        """Установка ID сессии."""
        self._session_id = value

    def _request(
        self,
        method: str,
        endpoint: str,
        json_data: dict[str, Any] | None = None,
        timeout: float = 120.0,
    ) -> dict[str, Any] | None:
        """
        Внутренний метод для HTTP запросов к Qwen Service.

        Args:
            method: HTTP метод.
            endpoint: Endpoint (например, /sessions).
            json_data: JSON данные для тела запроса.
            timeout: Таймаут запроса.

        Returns:
            JSON ответ или None при ошибке.
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
                return response.json()

        except httpx.TimeoutException as e:
            logger.error(f"Timeout запроса к {endpoint}: {e}")
            return None
        except httpx.HTTPError as e:
            logger.error(f"HTTP ошибка запроса к {endpoint}: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка запроса к {endpoint}: {e}")
            return None

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
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """
        Отправить сообщение и получить ответ через HTTP API.

        Args:
            message: Текст сообщения.
            session_id: ID сессии (создастся новая если не указан).
            thinking_enabled: Режим мышления.
            search_enabled: Поиск в интернете.
            file_ids: Список ID файлов для ссылки.
            auto_continue: Авто-продолжение ответов.
            timeout: Максимальное время ожидания в секундах.

        Returns:
            Словарь с результатом:
            - response: текст ответа
            - thinking: текст размышлений
            - message_id: ID сообщения
            - continue_count: количество продолжений
            - can_continue: можно ли продолжить
        """
        # Блокировка для потокобезопасности
        with self._lock:
            self._is_busy = True

            try:
                # Установка сессии
                sid = session_id or self._session_id
                if not sid:
                    sid = self.create_session()
                    if not sid:
                        return {
                            "error": "Не удалось создать сессию",
                            "response": "",
                            "thinking": "",
                        }

                # Параметры
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
                    f"thinking={thinking}, search={search}"
                )

                # Запись в историю запросов
                self._request_history.append({
                    "time": datetime.now(),
                    "message_len": len(message),
                    "session_id": sid,
                })

                # Отправка запроса к Qwen Service
                json_data = {
                    "session_id": sid,
                    "message": message,
                    "thinking_enabled": thinking,
                    "search_enabled": search,
                    "file_ids": file_ids or [],
                    "auto_continue": do_auto_continue,  # Передаём в сервис
                }

                result = self._request("POST", "/messages", json_data=json_data, timeout=timeout)

                if result:
                    self._session_id = sid

                    # Локальное авто-продолжение (если сервис не сделал сам)
                    continue_count = result.get("continue_count", 0)
                    can_continue = result.get("can_continue", False)
                    response_text = result.get("response", "")

                    # Если сервис не сделал авто-продолжение, но оно включено и можно продолжить
                    if do_auto_continue and continue_count == 0 and can_continue:
                        message_id = result.get("message_id", 0)
                        add_count, add_text = self._auto_continue(sid, message_id, thinking)

                        if add_count > 0:
                            continue_count = add_count
                            response_text = (response_text + "\n\n" + add_text).strip()
                            can_continue = False  # После локального продолжения считаем завершённым
                            result["auto_continue_performed"] = True

                    result["continue_count"] = continue_count
                    result["response"] = response_text
                    result["can_continue"] = can_continue

                    logger.info(
                        f"Ответ получен: len={len(response_text)}, continues={continue_count}"
                    )

                return result or {
                    "error": "Ошибка запроса к Qwen Service",
                    "response": "",
                    "thinking": "",
                }

            except Exception as e:
                logger.error(f"Ошибка отправки сообщения: {e}", exc_info=True)
                return {
                    "error": str(e),
                    "response": "",
                    "thinking": "",
                }
            finally:
                self._is_busy = False

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

        # Проверка на незавершённость
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

        # Проверка скобок
        if (
            text.count("(") > text.count(")")
            or text.count("[") > text.count("]")
            or text.count("{") > text.count("}")
        ):
            return True

        # Проверка кавычек
        if text.count("'") % 2 != 0 or text.count('"') % 2 != 0:
            return True

        # Проверка блоков кода
        if text.count("```") % 2 != 0:
            return True

        # Завершённый ответ
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
        """
        Получить текущую конфигурацию.

        Returns:
            Словарь с конфигурацией.
        """
        return {
            "model": self.model,
            "thinking_enabled": self.thinking_enabled,
            "search_enabled": self.search_enabled,
            "auto_continue_enabled": self.auto_continue_enabled,
            "max_continues": self.max_continues,
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
        recent_requests = sum(
            1 for req in self._request_history
            if (now - req["time"]).total_seconds() < 60
        )

        return {
            "is_busy": self._is_busy,
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
        return self._is_busy

    def update_config(
        self,
        model: str | None = None,
        thinking_enabled: bool | None = None,
        search_enabled: bool | None = None,
        auto_continue_enabled: bool | None = None,
        max_continues: int | None = None,
    ):
        """
        Обновить конфигурацию.

        Args:
            model: Новая модель.
            thinking_enabled: Режим мышления.
            search_enabled: Поиск.
            auto_continue_enabled: Авто-продолжение.
            max_continues: Макс. продолжений.
        """
        if model:
            self.model = model
        if thinking_enabled is not None:
            self.thinking_enabled = thinking_enabled
        if search_enabled is not None:
            self.search_enabled = search_enabled
        if auto_continue_enabled is not None:
            self.auto_continue_enabled = auto_continue_enabled
        if max_continues is not None:
            self.max_continues = max(1, min(20, max_continues))

        logger.info(
            f"Конфигурация обновлена: model={self.model}, "
            f"thinking={self.thinking_enabled}, search={self.search_enabled}"
        )


# Глобальный экземпляр
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
