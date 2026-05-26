"""Инструменты для ручной проверки Qwen Service."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from app.core.config import settings
from app.services.qwen_client import QwenServiceClient


@dataclass(slots=True)
class QwenTestChatResult:
    chat: int
    started_at_sec: float
    finished_at_sec: float
    duration_sec: float
    session_id: str
    error: str
    response_start: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "chat": self.chat,
            "started_at_sec": self.started_at_sec,
            "finished_at_sec": self.finished_at_sec,
            "duration_sec": self.duration_sec,
            "session_id": self.session_id,
            "error": self.error,
            "response_start": self.response_start,
        }


def _round(value: float) -> float:
    return round(float(value), 2)


def _short_text(value: Any, limit: int = 160) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _normalize_prompt(prompt: str | None) -> str:
    text = str(prompt or "").strip()
    if text:
        return text
    return "Напиши короткий ответ: OK"


def _client(timeout: float) -> QwenServiceClient:
    return QwenServiceClient(queue_enabled=False, timeout=timeout)


def _run_one_chat(
    chat_number: int,
    started_at: float,
    timeout: float,
    prompt: str,
) -> QwenTestChatResult:
    client = _client(timeout)
    session_id = ""
    chat_started = perf_counter()

    try:
        result = client.send_message(
            message=prompt,
            thinking_enabled=False,
            search_enabled=False,
            auto_continue=False,
            timeout=timeout,
        )
        chat_finished = perf_counter()
        session_id = str(result.get("session_id") or "")
        response_start = _short_text(result.get("response") or "", limit=120)
        error = _short_text(result.get("error") or "", limit=220)
        return QwenTestChatResult(
            chat=chat_number,
            started_at_sec=_round(chat_started - started_at),
            finished_at_sec=_round(chat_finished - started_at),
            duration_sec=_round(chat_finished - chat_started),
            session_id=session_id,
            error=error,
            response_start=response_start,
        )
    except Exception as exc:
        chat_finished = perf_counter()
        return QwenTestChatResult(
            chat=chat_number,
            started_at_sec=_round(chat_started - started_at),
            finished_at_sec=_round(chat_finished - started_at),
            duration_sec=_round(chat_finished - chat_started),
            session_id=session_id,
            error=_short_text(exc, limit=220),
            response_start="",
        )
    finally:
        if session_id:
            try:
                client.delete_session(session_id)
            except Exception:
                pass


def run_qwen_service_test(
    chat_count: int = 5,
    timeout: float = 240.0,
    prompt: str | None = None,
) -> dict[str, Any]:
    """Проверить доступность Qwen Service и параллельную обработку нескольких чатов."""
    client = _client(timeout)
    service_url = f"http://{settings.QWEN_SERVICE_HOST}:{settings.QWEN_SERVICE_PORT}"
    message_used = _normalize_prompt(prompt)
    health = client.health_check()
    auth_status = client.get_auth_status(force=False)

    if not health.get("available", False):
        return {
            "ok": False,
            "status": "error",
            "message": str(health.get("message") or "Qwen Service недоступен."),
            "service_url": service_url,
            "message_used": message_used,
            "chat_count": chat_count,
            "successful_count": 0,
            "failed_count": chat_count,
            "looks_parallel": False,
            "service_health": health,
            "token_status": auth_status,
            "results": [],
        }

    started_at = perf_counter()
    results: list[QwenTestChatResult] = []

    with ThreadPoolExecutor(max_workers=max(1, chat_count)) as executor:
        futures = [
            executor.submit(_run_one_chat, chat_number, started_at, timeout, message_used)
            for chat_number in range(1, chat_count + 1)
        ]
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: item.chat)
    successful = [item for item in results if not item.error]
    failed = [item for item in results if item.error]
    rate_limited = [item for item in failed if "too many requests" in item.error.lower() or "rate" in item.error.lower() or "частот" in item.error.lower()]

    started_values = [item.started_at_sec for item in results]
    start_spread = _round(max(started_values) - min(started_values)) if started_values else 0.0

    finished_spread = None
    duration_spread = None
    if len(successful) > 1:
        finished_values = [item.finished_at_sec for item in successful]
        duration_values = [item.duration_sec for item in successful]
        finished_spread = _round(max(finished_values) - min(finished_values))
        duration_spread = _round(max(duration_values) - min(duration_values))

    looks_parallel = bool(
        len(successful) > 1
        and not failed
        and finished_spread is not None
        and duration_spread is not None
        and finished_spread <= 8
        and duration_spread <= 8
    )

    if len(failed) == len(results) and len(rate_limited) == len(results):
        status = "rate_limited"
        message = "Текущий Qwen токен принят, но провайдер ограничил частоту запросов. Уменьшите параллельность или повторите позже."
    elif len(failed) == len(results):
        status = "error"
        message = "Все тестовые запросы завершились ошибкой. Проверьте токен, доступность сервиса и сеть."
    elif rate_limited:
        status = "partial"
        message = "Токен работает, но часть чатов упёрлась в лимит Qwen: Too many requests in a short period."
    elif failed:
        status = "partial"
        message = "Часть тестовых запросов завершилась ошибкой. Сначала устраните первую ошибку, затем повторите тест."
    elif looks_parallel:
        status = "ok"
        message = "Qwen Service успешно обработал тестовые чаты параллельно."
    else:
        status = "warning"
        message = "Запросы выполнились, но похоже на последовательную обработку. Проверьте нагрузку и настройки Qwen."

    return {
        "ok": status == "ok",
        "status": status,
        "message": message,
        "service_url": service_url,
        "message_used": message_used,
        "chat_count": chat_count,
        "successful_count": len(successful),
        "failed_count": len(failed),
        "rate_limited_count": len(rate_limited),
        "provider_limited": bool(rate_limited),
        "looks_parallel": looks_parallel,
        "start_spread_sec": start_spread,
        "finished_spread_sec": finished_spread,
        "duration_spread_sec": duration_spread,
        "service_health": health,
        "token_status": auth_status,
        "results": [item.as_dict() for item in results],
    }
