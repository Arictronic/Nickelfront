"""
Qwen Service Client - Клиент для standalone Qwen Service.

Обращается к Qwen Service через HTTP API (порт 8767).
Используется когда Qwen Service запущен как отдельный сервер.
"""

import logging
import os
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.services.qwen_document.results import (
    classify_qwen_service_error,
    format_error_result,
    qwen_error_code,
    qwen_error_text,
)

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
            detail_payload: dict[str, Any] = {}
            try:
                payload = e.response.json()
                detail = payload.get("detail") if isinstance(payload, dict) else payload
                if isinstance(detail, dict):
                    detail_payload = detail
            except Exception:
                detail = e.response.text

            status_code = getattr(e.response, "status_code", None)
            effective_status_code = int(detail_payload.get("status_code") or status_code or 0) or None
            detail_text = (
                str(detail_payload.get("message") or detail_payload.get("detail") or "").strip()
                if detail_payload
                else (detail if isinstance(detail, str) else str(detail or e))
            )
            error_code = str(
                detail_payload.get("error_code")
                or detail_payload.get("error")
                or detail_payload.get("code")
                or ""
            ).strip()
            lowered = f"{error_code} {detail_text}".lower()

            if error_code:
                logger.error(
                    "Qwen Service structured error on %s: code=%s status=%s message=%s",
                    endpoint,
                    error_code,
                    effective_status_code,
                    detail_text,
                )

            if (
                error_code in {"qwen_token_expired", "qwen_auth_failed"}
                or "qwen_token_expired" in lowered
                or "token has expired" in lowered
                or "please log in again" in lowered
            ):
                logger.error("Qwen auth error on %s: token expired/auth failed", endpoint)
                return {
                    "error": error_code or "qwen_token_expired",
                    "error_code": error_code or "qwen_token_expired",
                    "message": detail_text or "Qwen токен истёк. Обновите QWEN_TOKEN.",
                    "response": "",
                    "thinking": "",
                    "can_continue": False,
                    "status_code": effective_status_code,
                    "detail": detail_text,
                }, "auth_expired"
            if effective_status_code == 429 or error_code == "qwen_rate_limited" or "too many requests" in lowered or "rate limit" in lowered:
                logger.warning("Qwen provider rate limit on %s: %s", endpoint, detail_text)
                return {
                    "error": "qwen_rate_limited",
                    "error_code": "qwen_rate_limited",
                    "message": detail_text or "Qwen ограничил частоту запросов. Токен может быть действительным, но нагрузку нужно снизить.",
                    "response": "",
                    "thinking": "",
                    "can_continue": False,
                    "status_code": effective_status_code,
                    "detail": detail_text,
                }, "rate_limited"

            provider_error = error_code or classify_qwen_service_error(detail_text, status_code=effective_status_code)
            logger.error("HTTP ошибка запроса к %s: %s; detail=%s", endpoint, e, detail_text)
            return {
                "error": provider_error,
                "error_code": provider_error,
                "message": detail_text or f"HTTP {effective_status_code} from qwen_service",
                "detail": detail_payload or detail_text,
                "status_code": effective_status_code,
                "response": "",
                "thinking": "",
                "can_continue": False,
            }, "http"
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
        Проверка здоровья standalone qwen_service.

        Returns:
            Raw /health payload or a compact unavailable payload.
        """

        result = self._request("GET", "/health", timeout=3.0)
        return result or {
            "status": "error",
            "available": False,
            "service_alive": False,
            "model": settings.QWEN_MODEL,
        }

    def health_status(self) -> dict[str, Any]:
        """Backend-facing health payload used by API endpoints and dashboard.

        This mirrors the legacy QwenService.health_status() contract but uses
        the same HTTP client that sends messages/files, so /qwen/health and
        /qwen/messages no longer check different client stacks.
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
                "model": settings.QWEN_MODEL,
                "available": False,
                "base_url": self.base_url,
                "reason": reason,
                "error_type": error_type or "unknown",
                "service_alive": False,
            }

        available = bool(health.get("available")) if "available" in health else str(health.get("status", "")).lower() == "ok"
        reason: str | None = None
        if health.get("auth_valid_known") is False:
            available = False
            reason = "Последняя проверка Qwen auth завершилась ошибкой. Обновите QWEN_TOKEN/session."
        if not available and not reason:
            if health.get("has_token") is False or health.get("token_configured") is False:
                reason = "Qwen Service запущен, но QWEN_TOKEN в нём не загружен"
            elif health.get("auth_required") is True and health.get("has_api_key") is False:
                reason = "Qwen Service требует Bearer API key, но QWEN_API_KEY не настроен"
            else:
                reason = (
                    "Qwen Service вернул недоступный статус: "
                    f"status={health.get('status')!r}, available={health.get('available')!r}"
                )

        return {
            "status": "ok" if available else "unavailable",
            "model": health.get("model", settings.QWEN_MODEL),
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


    def get_readiness(self) -> dict[str, Any]:
        """Return local qwen_service readiness diagnostics without external provider calls."""
        result, error_type = self._request_with_error("GET", "/diagnostics/readiness", timeout=5.0)
        if result:
            result.setdefault("base_url", self.base_url)
            return result
        return {
            "status": "unavailable",
            "ok": False,
            "service_alive": False,
            "base_url": self.base_url,
            "error_type": error_type or "unknown",
            "check_count": 0,
            "error_count": 1,
            "warning_count": 0,
            "checks": [
                {
                    "name": "qwen_service_http",
                    "status": "error",
                    "ok": False,
                    "message": "backend не смог получить /diagnostics/readiness от qwen_service.",
                    "action": "Проверь scripts\\run_qwen_service.bat, QWEN_SERVICE_HOST/PORT и QWEN_API_KEY.",
                }
            ],
            "recommendations": ["Проверь, что qwen_service запущен и backend использует тот же QWEN_API_KEY."],
        }

    def run_cache_maintenance(
        self,
        *,
        dry_run: bool = True,
        prune_file_metadata: bool = True,
        prune_session_registry: bool = True,
        file_max_age_days: int | None = None,
        session_max_age_days: int | None = None,
        clear_file_metadata: bool = False,
        clear_session_registry: bool = False,
    ) -> dict[str, Any]:
        """Run provider-safe maintenance for qwen_service runtime JSON caches."""
        payload: dict[str, Any] = {
            "dry_run": dry_run,
            "prune_file_metadata": prune_file_metadata,
            "prune_session_registry": prune_session_registry,
            "clear_file_metadata": clear_file_metadata,
            "clear_session_registry": clear_session_registry,
        }
        if file_max_age_days is not None:
            payload["file_max_age_days"] = file_max_age_days
        if session_max_age_days is not None:
            payload["session_max_age_days"] = session_max_age_days

        result, error_type = self._request_with_error(
            "POST",
            "/diagnostics/cache-maintenance",
            json_data=payload,
            timeout=10.0,
        )
        if result:
            result.setdefault("base_url", self.base_url)
            return result
        return {
            "status": "unavailable",
            "dry_run": dry_run,
            "provider_called": False,
            "base_url": self.base_url,
            "error_type": error_type or "unknown",
            "total_candidates": 0,
            "total_removed": 0,
            "message": "backend не смог выполнить cache-maintenance в qwen_service.",
        }

    def get_event_journal(
        self,
        *,
        limit: int = 50,
        event: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Return recent local qwen_service events without calling external Qwen."""
        params: dict[str, Any] = {"limit": max(1, min(500, int(limit or 50)))}
        if event:
            params["event"] = event
        if status:
            params["status"] = status
        endpoint = "/diagnostics/events?" + urlencode(params)
        result, error_type = self._request_with_error("GET", endpoint, timeout=5.0)
        if result:
            result.setdefault("base_url", self.base_url)
            return result
        return {
            "status": "unavailable",
            "enabled": False,
            "provider_called": False,
            "base_url": self.base_url,
            "error_type": error_type or "unknown",
            "events": [],
            "count": 0,
            "message": "backend не смог получить журнал событий qwen_service.",
        }

    def clear_event_journal(self) -> dict[str, Any]:
        """Clear local qwen_service event journal without touching provider state."""
        result, error_type = self._request_with_error("POST", "/diagnostics/events/clear", timeout=5.0)
        if result:
            result.setdefault("base_url", self.base_url)
            return result
        return {
            "status": "unavailable",
            "enabled": False,
            "provider_called": False,
            "base_url": self.base_url,
            "error_type": error_type or "unknown",
            "cleared": 0,
            "message": "backend не смог очистить журнал событий qwen_service.",
        }

    def get_stats(self) -> dict[str, Any]:
        """Return backend-facing qwen_service runtime stats from the same HTTP client stack.

        This intentionally does not use the legacy ``QwenService`` request
        counters because qwen_service is the actual runtime owner for sessions,
        provider slots and auth state.
        """
        health = self.health_check()
        available = self.is_available()
        active_sessions = health.get("active_sessions")
        return {
            "is_busy": bool(active_sessions or 0),
            "active_requests": active_sessions or 0,
            "requests_last_minute": None,
            "total_requests": None,
            "session_id": self._session_id,
            "model": health.get("model", settings.QWEN_MODEL),
            "is_available": available,
            "available": available,
            "service_alive": health.get("service_alive", False),
            "base_url": self.base_url,
            "active_sessions": active_sessions,
            "max_active_sessions": health.get("max_active_sessions"),
            "provider_max_concurrent_requests": health.get("provider_max_concurrent_requests"),
            "auth_required": health.get("auth_required"),
            "has_token": health.get("has_token", health.get("token_configured")),
            "has_api_key": health.get("has_api_key"),
            "auth_valid_known": health.get("auth_valid_known"),
        }

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
        require_file_api: bool = False,
    ) -> dict[str, Any]:
        """Upload HAR to qwen_service so it extracts and applies QWEN_TOKEN/session itself."""
        url = f"{self.base_url}/config/token/update-from-har"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        params = {"validate": str(validate).lower()}
        if require_file_api:
            params["require_file_api"] = "true"
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
        """Получить эффективную конфигурацию standalone qwen_service.

        Response model on backend requires ``is_available`` and ``base_url`` even
        when qwen_service is down, so do not return an empty dict on failure.
        """
        result = self._request("GET", "/config", timeout=5.0) or {}
        health = self.health_status()
        return {
            "model": result.get("model", settings.QWEN_MODEL),
            "thinking_enabled": result.get("thinking_enabled", settings.QWEN_THINKING_ENABLED),
            "search_enabled": result.get("search_enabled", settings.QWEN_SEARCH_ENABLED),
            "auto_continue_enabled": result.get("auto_continue_enabled", settings.QWEN_AUTO_CONTINUE_ENABLED),
            "max_continues": result.get("max_continues", settings.QWEN_MAX_CONTINUES),
            "stream_retries": result.get("stream_retries"),
            "history_recovery_attempts": result.get("history_recovery_attempts"),
            "history_recovery_interval_sec": result.get("history_recovery_interval_sec"),
            "has_token": result.get("has_token", health.get("has_token")),
            "has_api_key": result.get("has_api_key", health.get("has_api_key")),
            "auth_required": result.get("auth_required", health.get("auth_required")),
            "allow_unauth_without_api_key": result.get("allow_unauth_without_api_key"),
            "file_metadata_cache_enabled": result.get("file_metadata_cache_enabled"),
            "file_metadata_cache_path": result.get("file_metadata_cache_path"),
            "file_metadata_cache_entries": result.get("file_metadata_cache_entries"),
            "file_metadata_cache_max_age_days": result.get("file_metadata_cache_max_age_days"),
            "session_registry_cache_enabled": result.get("session_registry_cache_enabled"),
            "session_registry_cache_path": result.get("session_registry_cache_path"),
            "session_registry_cache_entries": result.get("session_registry_cache_entries"),
            "session_registry_cache_max_age_days": result.get("session_registry_cache_max_age_days"),
            "event_journal_enabled": result.get("event_journal_enabled"),
            "event_journal_path": result.get("event_journal_path"),
            "event_journal_entries": result.get("event_journal_entries"),
            "event_journal_max_entries": result.get("event_journal_max_entries"),
            "is_available": bool(health.get("available")),
            "base_url": self.base_url,
        }

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
        file_metadata_cache_max_age_days: int | None = None,
        session_registry_cache_max_age_days: int | None = None,
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
            file_metadata_cache_max_age_days: Возраст stale uploaded-file metadata для maintenance.
            session_registry_cache_max_age_days: Возраст stale локальных sessions для maintenance.

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
        if file_metadata_cache_max_age_days is not None:
            json_data["file_metadata_cache_max_age_days"] = file_metadata_cache_max_age_days
        if session_registry_cache_max_age_days is not None:
            json_data["session_registry_cache_max_age_days"] = session_registry_cache_max_age_days

        if json_data:
            result = self._request("POST", "/config", json_data=json_data, timeout=10.0)
            if not result:
                logger.warning("Failed to update standalone qwen_service config; returning current effective config")

        return self.get_config()

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

    @staticmethod
    def _normalize_file_ids(file_ids: list[str] | None) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in file_ids or []:
            fid = str(item or "").strip()
            if not fid or fid in seen:
                continue
            seen.add(fid)
            normalized.append(fid)
        return normalized

    @staticmethod
    def _service_error_payload(
        *,
        code: str,
        message: str,
        session_id: str | None = None,
        request_error_type: str | None = None,
        status_code: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "error",
            "error": code,
            "error_code": code,
            "message": message,
            "response": "",
            "thinking": "",
            "session_id": session_id or "",
            "message_id": 0,
            "continue_count": 0,
            "can_continue": False,
        }
        if request_error_type:
            payload["_request_error_type"] = request_error_type
        if status_code:
            payload["status_code"] = status_code
        if extra:
            payload.update(extra)
        return payload

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
        clean_message = str(message or "").strip()
        sid = str(session_id or "").strip() or None
        clean_file_ids = self._normalize_file_ids(file_ids)
        effective_timeout = self._chat_timeout(timeout)

        if not clean_message:
            return self._service_error_payload(
                code="qwen_empty_message",
                message="Сообщение для Qwen не должно быть пустым.",
                session_id=sid,
            )

        if self._should_use_queue():
            try:
                from app.services.qwen_queue_client import send_qwen_message_via_queue

                result = send_qwen_message_via_queue(
                    message=clean_message,
                    session_id=sid,
                    thinking_enabled=thinking_enabled,
                    search_enabled=search_enabled,
                    file_ids=clean_file_ids,
                    auto_continue=auto_continue,
                    timeout=effective_timeout,
                    purpose="backend-qwen-client",
                )
                if result.get("session_id"):
                    self._session_id = str(result["session_id"])
                return result
            except Exception as exc:
                logger.exception("Failed to enqueue Qwen request")
                return self._service_error_payload(
                    code="qwen_queue_enqueue_failed",
                    message=f"Failed to enqueue Qwen request: {exc}",
                    session_id=sid,
                )

        if not sid:
            sid = self.create_session()
            if not sid:
                return self._service_error_payload(
                    code="qwen_session_create_failed",
                    message="Не удалось создать сессию",
                )

        result = self._send_message_once(
            message=clean_message,
            sid=sid,
            thinking_enabled=thinking_enabled,
            search_enabled=search_enabled,
            file_ids=clean_file_ids,
            auto_continue=auto_continue,
            timeout=effective_timeout,
        )

        retry_safe = not clean_file_ids
        if retry_safe and self._retry_on_timeout_enabled() and result.get("_request_error_type") == "timeout":
            old_sid = sid
            new_sid = self.create_session()
            if new_sid:
                logger.warning(
                    "Qwen direct request timed out for session %s; retrying once in fresh session %s",
                    old_sid[-6:] if old_sid else "none",
                    new_sid[-6:],
                )
                retry_result = self._send_message_once(
                    message=clean_message,
                    sid=new_sid,
                    thinking_enabled=thinking_enabled,
                    search_enabled=search_enabled,
                    file_ids=clean_file_ids,
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
        if result.get("error"):
            result.setdefault("status", "error")
            result.setdefault("error_code", qwen_error_code(result) or "qwen_message_failed")
            result.setdefault("message", qwen_error_text(result, fallback="Qwen вернул ошибку"))
        else:
            result.setdefault("status", "ok")
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
            code = "qwen_service_timeout" if error_type == "timeout" else "qwen_service_unavailable"
            return self._service_error_payload(
                code=code,
                message="Timeout запроса к Qwen Service" if error_type == "timeout" else "Ошибка запроса к Qwen Service",
                session_id=sid,
                request_error_type=error_type,
            )

        result.setdefault("session_id", sid)
        if result.get("error"):
            result.setdefault("status", "error")
            result.setdefault("error_code", qwen_error_code(result) or "qwen_message_failed")
            result.setdefault("message", qwen_error_text(result, fallback="Qwen вернул ошибку"))
            result.setdefault("response", "")
            result.setdefault("thinking", "")
            result.setdefault("message_id", 0)
            result.setdefault("continue_count", 0)
            result.setdefault("can_continue", False)
            return result

        if not result.get("message_id") and result.get("last_message_id"):
            result["message_id"] = result.get("last_message_id")

        result.setdefault("status", "ok")
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

        result, error_type = self._request_with_error(
            "POST",
            "/messages/continue",
            json_data=json_data,
            timeout=timeout,
        )

        if result and not result.get("message_id") and result.get("last_message_id"):
            result["message_id"] = result.get("last_message_id")

        if not result or result.get("error"):
            code = qwen_error_code(result, error_type=error_type) or "qwen_continue_failed"
            return format_error_result(
                result,
                fallback_error=code,
                fallback_message="Ошибка продолжения сообщения",
                extra={"message_id": 0, "can_continue": False, "session_id": session_id},
            )

        result.setdefault("status", "ok")
        return result

    def upload_file(self, file_path: str, timeout: float = 180.0) -> dict[str, Any]:
        """Upload one file through standalone qwen_service and wait for parse success."""
        result, error_type = self._request_with_error(
            "POST",
            "/files/upload",
            json_data={"file_path": file_path},
            timeout=timeout,
        )
        if not result or result.get("error"):
            return format_error_result(
                result,
                fallback_error="qwen_file_upload_failed" if error_type != "timeout" else "qwen_file_upload_timeout",
                fallback_message="Ошибка загрузки файла в Qwen Service",
                extra={"file_id": None},
            )
        return result

    def upload_files(self, file_paths: list[str], timeout: float = 300.0) -> dict[str, Any]:
        """Upload 1..5 files through standalone qwen_service and wait for parse success."""
        result, error_type = self._request_with_error(
            "POST",
            "/files/upload-many",
            json_data={"file_paths": file_paths},
            timeout=timeout,
        )
        if not result or result.get("error"):
            return format_error_result(
                result,
                fallback_error="qwen_file_upload_failed" if error_type != "timeout" else "qwen_file_upload_timeout",
                fallback_message="Ошибка загрузки файлов в Qwen Service",
                extra={"file_ids": [], "files": [], "file_infos": []},
            )
        return result

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
        """Upload one file and send one prompt with that file attached."""
        return self.upload_files_and_send_message(
            file_paths=[file_path],
            message=message,
            session_id=session_id,
            thinking_enabled=thinking_enabled,
            search_enabled=search_enabled,
            auto_continue=auto_continue,
            timeout=timeout,
            session_prompt=session_prompt,
        )

    def upload_files_and_send_message(
        self,
        *,
        file_paths: list[str],
        message: str = "",
        session_id: str | None = None,
        thinking_enabled: bool = True,
        search_enabled: bool = False,
        auto_continue: bool | None = None,
        timeout: float = 300.0,
        session_prompt: str | None = None,
    ) -> dict[str, Any]:
        """Upload 1..5 files and send one prompt with all files attached."""
        result, error_type = self._request_with_error(
            "POST",
            "/files/upload-many-and-send",
            json_data={
                "file_paths": file_paths,
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
        if not result or result.get("error"):
            return format_error_result(
                result,
                fallback_error="qwen_file_message_failed" if error_type != "timeout" else "qwen_file_message_timeout",
                fallback_message="Ошибка отправки файлов в Qwen Service",
                extra={"file_id": None, "file_ids": [], "session_id": session_id},
            )
        return result

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
