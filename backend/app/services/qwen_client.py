"""
Qwen Service Client - Клиент для standalone Qwen Service.

Обращается к Qwen Service через HTTP API (порт 8767).
Используется когда Qwen Service запущен как отдельный сервер.
"""

import logging
from typing import Any, Dict, List, Optional

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
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 120.0,
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
        self._session_id: Optional[str] = None

        logger.info(
            f"Инициализация QwenServiceClient: url={self.base_url}, "
            f"api_key={'***' if self.api_key else 'None'}"
        )

    @property
    def headers(self) -> Dict[str, str]:
        """Заголовки для авторизации."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @property
    def session_id(self) -> Optional[str]:
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
        json_data: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Внутренний метод для HTTP запросов.

        Args:
            method: HTTP метод.
            endpoint: Endpoint (например, /sessions).
            json_data: JSON данные для тела запроса.
            timeout: Таймаут запроса.

        Returns:
            JSON ответ или None при ошибке.
        """
        url = f"{self.base_url}{endpoint}"
        request_timeout = timeout or self.timeout

        try:
            with httpx.Client(timeout=request_timeout) as client:
                response = client.request(
                    method,
                    url,
                    headers=self.headers,
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

    def health_check(self) -> Dict[str, Any]:
        """
        Проверка здоровья сервиса.

        Returns:
            Статус сервиса.
        """
        result = self._request("GET", "/health")
        return result or {"status": "error", "available": False}

    def get_config(self) -> Dict[str, Any]:
        """
        Получить конфигурацию сервиса.

        Returns:
            Конфигурация сервиса.
        """
        result = self._request("GET", "/config")
        return result or {}

    def update_config(
        self,
        model: Optional[str] = None,
        thinking_enabled: Optional[bool] = None,
        search_enabled: Optional[bool] = None,
        auto_continue_enabled: Optional[bool] = None,
        max_continues: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Обновить конфигурацию сервиса.

        Args:
            model: Модель.
            thinking_enabled: Режим мышления.
            search_enabled: Поиск.
            auto_continue_enabled: Авто-продолжение.
            max_continues: Макс. продолжений.

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

        result = self._request("POST", "/config", json_data=json_data)
        return result or {}

    def create_session(self, title: Optional[str] = None) -> Optional[str]:
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

    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        Получить список сессий.

        Returns:
            Список сессий.
        """
        result = self._request("GET", "/sessions")
        return result.get("sessions", []) if result else []

    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
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

    def send_message(
        self,
        message: str,
        session_id: Optional[str] = None,
        thinking_enabled: bool = True,
        search_enabled: bool = False,
        file_ids: Optional[List[str]] = None,
        auto_continue: Optional[bool] = None,
        timeout: float = 120.0,
    ) -> Dict[str, Any]:
        """
        Отправить сообщение и получить ответ.

        Args:
            message: Текст сообщения.
            session_id: ID сессии (используется текущая если не указан).
            thinking_enabled: Режим мышления.
            search_enabled: Поиск в интернете.
            file_ids: ID файлов для ссылки.
            auto_continue: Авто-продолжение.
            timeout: Таймаут запроса.

        Returns:
            Ответ от сервиса.
        """
        sid = session_id or self._session_id

        if not sid:
            # Создаём новую сессию если нет
            sid = self.create_session()
            if not sid:
                return {
                    "error": "Не удалось создать сессию",
                    "response": "",
                    "thinking": "",
                }

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
            f"thinking={thinking_enabled}, search={search_enabled}"
        )

        result = self._request(
            "POST",
            "/messages",
            json_data=json_data,
            timeout=timeout,
        )

        if result:
            # Сохраняем session_id для последующих запросов
            self._session_id = sid
            logger.info(
                f"Ответ получен: len={len(result.get('response', ''))}, "
                f"continues={result.get('continue_count', 0)}"
            )

        return result or {
            "error": "Ошибка запроса к Qwen Service",
            "response": "",
            "thinking": "",
        }

    def continue_message(
        self,
        session_id: str,
        message_id: int,
        thinking_enabled: bool = True,
        timeout: float = 120.0,
    ) -> Dict[str, Any]:
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

        return result or {
            "error": "Ошибка продолжения сообщения",
            "response": "",
            "thinking": "",
        }

    def is_available(self) -> bool:
        """
        Проверить доступность сервиса.

        Returns:
            True если сервис доступен.
        """
        health = self.health_check()
        return health.get("status") == "ok"


# Глобальный экземпляр
_qwen_client: Optional[QwenServiceClient] = None


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
