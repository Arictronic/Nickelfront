"""Инструменты для ручной проверки Qwen Service."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
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


_ADMIN_QWEN_TEST_LOCK = Lock()


def _provider_busy_from_health(health: dict[str, Any] | None) -> bool:
    if not isinstance(health, dict):
        return False
    try:
        return int(health.get("provider_active_requests") or 0) > 0
    except (TypeError, ValueError):
        return False


def _busy_result(
    *,
    service_url: str,
    message_used: str,
    kind: str,
    health: dict[str, Any] | None = None,
    auth_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message = (
        "Qwen сейчас занят другим запросом Nickelfront. Дождитесь завершения текущей обработки и повторите проверку."
        if _provider_busy_from_health(health)
        else "Уже выполняется другая ручная Qwen-проверка. Дождитесь её завершения и повторите запуск."
    )
    payload: dict[str, Any] = {
        "ok": False,
        "status": "busy",
        "message": message,
        "service_url": service_url,
        "message_used": message_used,
        "service_health": health or {},
        "token_status": auth_status or {},
    }
    if kind == "upload":
        payload.update({
            "duration_sec": 0.0,
            "session_id": "",
            "file_ids": [],
            "error": "",
            "response_start": "",
        })
    else:
        payload.update({
            "chat_count": 0,
            "successful_count": 0,
            "failed_count": 0,
            "looks_parallel": False,
            "processing_mode": "busy",
            "parallelism_note": "Проверка не запускалась: Qwen занят другим запросом.",
            "results": [],
        })
    return payload


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
    """Проверить доступность Qwen Service и обработку тестовых чатов."""
    client = _client(timeout)
    service_url = f"http://{settings.QWEN_SERVICE_HOST}:{settings.QWEN_SERVICE_PORT}"
    message_used = _normalize_prompt(prompt)
    health = client.health_check()
    auth_status = client.get_auth_status(force=False)

    if _provider_busy_from_health(health):
        return _busy_result(
            service_url=service_url,
            message_used=message_used,
            kind="text",
            health=health,
            auth_status=auth_status,
        )

    if not _ADMIN_QWEN_TEST_LOCK.acquire(blocking=False):
        return _busy_result(
            service_url=service_url,
            message_used=message_used,
            kind="text",
            health=health,
            auth_status=auth_status,
        )

    try:
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

        safe_chat_count = max(1, int(chat_count or 1))
        if safe_chat_count == 1:
            results.append(_run_one_chat(1, started_at, timeout, message_used))
        else:
            with ThreadPoolExecutor(max_workers=safe_chat_count) as executor:
                futures = [
                    executor.submit(_run_one_chat, chat_number, started_at, timeout, message_used)
                    for chat_number in range(1, safe_chat_count + 1)
                ]
                for future in as_completed(futures):
                    results.append(future.result())

        results.sort(key=lambda item: item.chat)
        successful = [item for item in results if not item.error]
        failed = [item for item in results if item.error]
        rate_limited = [
            item
            for item in failed
            if "too many requests" in item.error.lower()
            or "rate" in item.error.lower()
            or "частот" in item.error.lower()
        ]

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
            status = "ok"
            if safe_chat_count <= 1:
                message = "Текстовый Qwen-запрос успешно выполнен."
            else:
                message = (
                    "Qwen успешно обработал все тестовые запросы. "
                    "Ответы пришли последовательно или с ограниченной параллельностью — "
                    "это нормальный режим, если он задан в настройках."
                )

        processing_mode = "parallel" if looks_parallel else "sequential_or_limited"
        if safe_chat_count <= 1:
            processing_mode = "single_request"

        return {
            "ok": status == "ok",
            "status": status,
            "message": message,
            "service_url": service_url,
            "message_used": message_used,
            "chat_count": safe_chat_count,
            "successful_count": len(successful),
            "failed_count": len(failed),
            "rate_limited_count": len(rate_limited),
            "provider_limited": bool(rate_limited),
            "looks_parallel": looks_parallel,
            "processing_mode": processing_mode,
            "parallelism_note": (
                "Параллельная обработка подтверждена."
                if looks_parallel
                else "Последовательная или ограниченная обработка — нормальный режим, если он задан в настройках."
            ),
            "start_spread_sec": start_spread,
            "finished_spread_sec": finished_spread,
            "duration_spread_sec": duration_spread,
            "service_health": health,
            "token_status": auth_status,
            "results": [item.as_dict() for item in results],
        }
    finally:
        _ADMIN_QWEN_TEST_LOCK.release()

def run_qwen_upload_smoke_test(
    timeout: float = 300.0,
    prompt: str | None = None,
) -> dict[str, Any]:
    """Проверить полный Qwen file pipeline: local file -> upload -> attach -> message."""
    client = _client(timeout)
    service_url = f"http://{settings.QWEN_SERVICE_HOST}:{settings.QWEN_SERVICE_PORT}"
    message_used = _normalize_prompt(
        prompt
        or "Прочитай прикреплённый TXT-файл и ответь одной короткой фразой: файл получен."
    )
    health = client.health_check()
    auth_status = client.get_auth_status(force=False)

    if _provider_busy_from_health(health):
        return _busy_result(
            service_url=service_url,
            message_used=message_used,
            kind="upload",
            health=health,
            auth_status=auth_status,
        )

    if not _ADMIN_QWEN_TEST_LOCK.acquire(blocking=False):
        return _busy_result(
            service_url=service_url,
            message_used=message_used,
            kind="upload",
            health=health,
            auth_status=auth_status,
        )

    try:
        if not health.get("available", False):
            return {
                "ok": False,
                "status": "error",
                "message": str(health.get("message") or "Qwen Service недоступен."),
                "service_url": service_url,
                "message_used": message_used,
                "duration_sec": 0.0,
                "session_id": "",
                "file_ids": [],
                "error": str(health.get("message") or "Qwen Service недоступен."),
                "response_start": "",
                "service_health": health,
                "token_status": auth_status,
            }

        temp_path = ""
        started_at = perf_counter()
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                suffix=".txt",
                prefix="nickelfront_qwen_upload_probe_",
                delete=False,
            ) as file_obj:
                temp_path = file_obj.name
                file_obj.write(
                    "Nickelfront Qwen upload smoke test.\n"
                    "Этот файл создан автоматически из раздела Технический отдел -> Qwen / AI.\n"
                    "Если Qwen прочитал этот файл, file upload pipeline работает.\n"
                )

            result = client.upload_file_and_send_message(
                file_path=temp_path,
                message=message_used,
                thinking_enabled=False,
                search_enabled=False,
                auto_continue=False,
                timeout=timeout,
            )
            duration = _round(perf_counter() - started_at)
            error = _short_text(result.get("error") or result.get("message") if result.get("error") else "", limit=260)
            response_start = _short_text(result.get("response") or result.get("answer") or "", limit=220)
            file_ids = result.get("file_ids") or ([result.get("file_id")] if result.get("file_id") else [])
            status = str(result.get("status") or "").lower()
            ok = not bool(result.get("error")) and status not in {"error", "failed"}

            if ok:
                message = "Файловый pipeline Qwen работает: тестовый TXT загружен, прикреплён к сообщению и Qwen вернул ответ."
                normalized_status = "ok"
            else:
                message = error or str(result.get("message") or "Qwen file upload test завершился ошибкой.")
                normalized_status = "error"

            return {
                "ok": ok,
                "status": normalized_status,
                "message": message,
                "service_url": service_url,
                "message_used": message_used,
                "duration_sec": duration,
                "session_id": str(result.get("session_id") or ""),
                "file_ids": [str(item) for item in file_ids if item],
                "error": error if not ok else "",
                "response_start": response_start,
                "raw_status": result.get("status"),
                "service_health": health,
                "token_status": auth_status,
            }
        except Exception as exc:
            duration = _round(perf_counter() - started_at)
            return {
                "ok": False,
                "status": "error",
                "message": _short_text(exc, limit=260) or "Qwen file upload test завершился ошибкой.",
                "service_url": service_url,
                "message_used": message_used,
                "duration_sec": duration,
                "session_id": "",
                "file_ids": [],
                "error": _short_text(exc, limit=260),
                "response_start": "",
                "service_health": health,
                "token_status": auth_status,
            }
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except Exception:
                    pass
    finally:
        _ADMIN_QWEN_TEST_LOCK.release()
