"""Read-only diagnostics payloads for standalone Qwen service.

The helpers in this module intentionally do not call the external Qwen
provider.  They only inspect local runtime state/config/files so the endpoint is
safe to call from admin pages and diagnostic scripts before running expensive
text/upload probes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from .defaults import DEFAULT_FILE_UPLOAD_MAX_FILES, DEFAULT_FILE_UPLOAD_MAX_SIZE_MB
    from .upload_validation import file_max_size_bytes, max_files_per_message
except ImportError:
    from defaults import DEFAULT_FILE_UPLOAD_MAX_FILES, DEFAULT_FILE_UPLOAD_MAX_SIZE_MB
    from upload_validation import file_max_size_bytes, max_files_per_message


CheckStatus = str


def _check(
    name: str,
    status: CheckStatus,
    message: str,
    *,
    action: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "status": status,
        "ok": status == "ok",
        "message": message,
    }
    if action:
        payload["action"] = action
    if details:
        payload["details"] = details
    return payload


def _path_info(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"configured": False}
    return {
        "configured": True,
        "path": str(path),
        "exists": path.exists(),
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
    }


def _count_store_entries(store: Any | None) -> int | None:
    if store is None or not hasattr(store, "all"):
        return None
    try:
        entries = store.all()
    except Exception:
        return None
    return len(entries) if isinstance(entries, dict) else None


def _writable_parent(path: Path | None) -> bool | None:
    if path is None:
        return None
    parent = path.parent if path.suffix else path
    try:
        parent.mkdir(parents=True, exist_ok=True)
        probe = parent / ".nf_qwen_write_probe.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _har_dir_details(har_dir: Path) -> dict[str, Any]:
    details = _path_info(har_dir)
    files: list[Path] = []
    try:
        if har_dir.exists() and har_dir.is_dir():
            files = sorted(har_dir.glob("*.har"), key=lambda item: item.stat().st_mtime, reverse=True)
    except Exception:
        files = []
    details["har_count"] = len(files)
    details["latest_har"] = str(files[0]) if files else ""
    details["latest_har_size_bytes"] = files[0].stat().st_size if files else 0
    return details


def _session_header_state(config: dict[str, Any]) -> dict[str, bool]:
    return {
        "cookie": bool(config.get("cookie")),
        "bx_ua": bool(config.get("bx_ua")),
        "bx_umidtoken": bool(config.get("bx_umidtoken")),
        "bx_v": bool(config.get("bx_v")),
        "user_agent": bool(config.get("user_agent")),
    }




def _latest_successful_file_upload_event(state: Any) -> dict[str, Any] | None:
    store = getattr(state, "event_journal_store", None)
    if store is None or not hasattr(store, "recent"):
        return None
    try:
        events = store.recent(limit=100)
    except Exception:
        return None
    for item in events:
        if not isinstance(item, dict):
            continue
        event = str(item.get("event") or "").strip().lower()
        status = str(item.get("status") or "").strip().lower()
        operation = str(item.get("operation") or "").strip().lower()
        if status != "ok":
            continue
        if event in {"file_upload_and_send", "file_upload", "upload_and_send"} or operation in {"upload_and_send", "file_upload"}:
            return dict(item)
    return None

def _file_api_state(config: dict[str, Any]) -> dict[str, bool]:
    return {
        "file_sts_url": bool(config.get("file_sts_url")),
        "file_sts_payload_template_json": bool(config.get("file_sts_payload_template_json")),
        "file_parse_url": bool(config.get("file_parse_url")),
        "file_parse_payload_template_json": bool(config.get("file_parse_payload_template_json")),
        "file_parse_status_url": bool(config.get("file_parse_status_url")),
        "file_parse_status_payload_template_json": bool(config.get("file_parse_status_payload_template_json")),
        "oss_put_headers_template_json": bool(config.get("oss_put_headers_template_json")),
        "file_api_extra_headers_json": bool(config.get("file_api_extra_headers_json")),
    }


def build_readiness_payload(
    *,
    state: Any,
    qwen_api: Any | None,
    har_dir: Path,
    service_base_url: str = "",
) -> dict[str, Any]:
    """Build a local, secret-safe readiness report for Qwen diagnostics."""
    config: dict[str, Any] = getattr(state, "config", {}) or {}
    checks: list[dict[str, Any]] = []

    has_api_key = bool(config.get("api_key"))
    allow_unauth = bool(config.get("allow_unauth_without_api_key"))
    if has_api_key:
        checks.append(_check("service_api_key", "ok", "QWEN_API_KEY настроен, protected endpoints закрыты Bearer-токеном."))
    elif allow_unauth:
        checks.append(
            _check(
                "service_api_key",
                "warn",
                "QWEN_API_KEY пустой, но unauth dev-режим включён явно.",
                action="Использовать только локально на 127.0.0.1; для обычного запуска задай QWEN_API_KEY.",
            )
        )
    else:
        checks.append(
            _check(
                "service_api_key",
                "error",
                "QWEN_API_KEY пустой, protected endpoints будут отдавать 401.",
                action="Добавь QWEN_API_KEY в .env или временно включи QWEN_ALLOW_UNAUTH_WITHOUT_API_KEY=true для локальной диагностики.",
            )
        )

    has_token = bool(config.get("token"))
    checks.append(
        _check(
            "provider_token",
            "ok" if has_token else "error",
            "QWEN_TOKEN загружен." if has_token else "QWEN_TOKEN не загружен в qwen_service.",
            action="Обнови токен через HAR/CDP/manual session refresh." if not has_token else "",
        )
    )

    header_state = _session_header_state(config)
    required_headers = ["cookie", "bx_ua", "bx_umidtoken", "bx_v"]
    present_required_headers = [name for name in required_headers if header_state.get(name)]
    if len(present_required_headers) == len(required_headers):
        header_status = "ok"
        header_message = "Browser/session headers для file API выглядят полными."
        header_action = ""
    elif present_required_headers:
        header_status = "warn"
        header_message = "Browser/session headers заполнены частично; upload может падать на STS/parse шагах."
        header_action = "Обнови session из HAR/CDP/browser-refresh с require_file_api=true."
    else:
        header_status = "warn"
        header_message = "Browser/session headers не загружены; текстовые запросы могут работать, а file upload — нет."
        header_action = "Для upload обнови session из HAR/CDP/browser-refresh."
    checks.append(
        _check(
            "browser_session_headers",
            header_status,
            header_message,
            action=header_action,
            details=header_state,
        )
    )

    file_api = _file_api_state(config)
    critical_file_keys = [
        "file_sts_url",
        "file_parse_url",
        "file_parse_status_url",
        "oss_put_headers_template_json",
    ]
    missing_critical = [key for key in critical_file_keys if not file_api.get(key)]
    latest_upload_ok = _latest_successful_file_upload_event(state)
    file_api_details = {
        "present": file_api,
        "missing_critical": missing_critical,
        "latest_successful_upload_event": latest_upload_ok,
    }
    if missing_critical and latest_upload_ok:
        checks.append(
            _check(
                "file_api_templates",
                "ok",
                "Часть сохранённых file API templates отсутствует, но последний реальный upload прошёл успешно. Runtime-восстановление работает, предупреждение не требуется.",
                details=file_api_details,
            )
        )
    elif missing_critical:
        checks.append(
            _check(
                "file_api_templates",
                "warn",
                "Часть file API templates не сохранена статически. Это не ломает текстовые запросы; upload нужно проверить реальным тестом.",
                action="Нажми «Проверить upload». Если тест успешен — это предупреждение можно игнорировать; если падает — импортируй свежий HAR с require_file_api=true.",
                details=file_api_details,
            )
        )
    else:
        checks.append(
            _check(
                "file_api_templates",
                "ok",
                "Основные file API endpoints/templates присутствуют.",
                details=file_api_details,
            )
        )

    har_details = _har_dir_details(har_dir)
    checks.append(
        _check(
            "har_directory",
            "ok" if har_details.get("exists") and har_details.get("is_dir") else "warn",
            "HAR-папка доступна." if har_details.get("exists") and har_details.get("is_dir") else "HAR-папка не найдена или недоступна.",
            action="Создай qwen_service/har или проверь QWEN_HAR_DIR." if not har_details.get("is_dir") else "",
            details=har_details,
        )
    )

    max_files = max_files_per_message(config, DEFAULT_FILE_UPLOAD_MAX_FILES)
    max_size_bytes = file_max_size_bytes(config, DEFAULT_FILE_UPLOAD_MAX_SIZE_MB)
    checks.append(
        _check(
            "upload_limits",
            "ok",
            f"Upload limits: до {max_files} файлов, до {round(max_size_bytes / 1024 / 1024, 2)} MB на файл.",
            details={"max_files": max_files, "max_size_bytes": max_size_bytes},
        )
    )

    file_store = getattr(state, "uploaded_file_store", None)
    file_store_path = Path(file_store.path) if file_store is not None and hasattr(file_store, "path") else None
    file_store_writable = _writable_parent(file_store_path)
    file_store_problem = file_store is None or file_store_writable is False
    checks.append(
        _check(
            "file_metadata_cache",
            "warn" if file_store_problem else "ok",
            "Persistent metadata cache для uploaded files недоступен или не writable."
            if file_store_problem
            else "Persistent metadata cache для uploaded files доступен.",
            action="Проверь runtime/ и права записи, иначе two-step upload после рестарта будет хрупким." if file_store_problem else "",
            details={
                **_path_info(file_store_path),
                "entries": _count_store_entries(file_store),
                "parent_writable": file_store_writable,
            },
        )
    )

    session_store = getattr(state, "session_registry_store", None)
    session_store_path = Path(session_store.path) if session_store is not None and hasattr(session_store, "path") else None
    session_store_writable = _writable_parent(session_store_path)
    session_store_problem = session_store is None or session_store_writable is False
    checks.append(
        _check(
            "session_registry_cache",
            "warn" if session_store_problem else "ok",
            "Persistent registry локальных Qwen-сессий недоступен или не writable."
            if session_store_problem
            else "Persistent registry локальных Qwen-сессий доступен.",
            action="Проверь runtime/ и права записи, иначе список локальных sessions будет теряться после рестарта." if session_store_problem else "",
            details={
                **_path_info(session_store_path),
                "entries": _count_store_entries(session_store),
                "parent_writable": session_store_writable,
            },
        )
    )

    event_store = getattr(state, "event_journal_store", None)
    event_store_path = Path(event_store.path) if event_store is not None and hasattr(event_store, "path") else None
    event_store_writable = _writable_parent(event_store_path)
    event_entries = 0
    if event_store is not None:
        try:
            event_entries = int((event_store.stats() or {}).get("entries") or 0)
        except Exception:
            event_entries = 0
    event_store_problem = event_store is None or event_store_writable is False
    checks.append(
        _check(
            "event_journal",
            "warn" if event_store_problem else "ok",
            "Локальный журнал Qwen-событий недоступен или не writable."
            if event_store_problem
            else "Локальный журнал Qwen-событий доступен.",
            action="Проверь runtime/ и права записи, иначе последние Qwen send/upload/auth ошибки будут видны только в терминале." if event_store_problem else "",
            details={
                **_path_info(event_store_path),
                "entries": event_entries,
                "parent_writable": event_store_writable,
            },
        )
    )

    active_sessions = getattr(state, "active_sessions", {}) or {}
    session_clients = getattr(state, "session_qwen_clients", {}) or {}
    control_ready = bool(qwen_api or getattr(state, "control_qwen_api", None))
    checks.append(
        _check(
            "runtime_clients",
            "ok" if control_ready else "warn",
            "Control Qwen client создан." if control_ready else "Control Qwen client ещё не создан или нет QWEN_TOKEN.",
            action="Если token есть, перезапусти qwen_service или вызови auth/status/auth/check." if has_token and not control_ready else "",
            details={
                "active_sessions": len(active_sessions) if isinstance(active_sessions, dict) else 0,
                "session_clients": len(session_clients) if isinstance(session_clients, dict) else 0,
                "control_client_ready": control_ready,
            },
        )
    )

    status_rank = {"ok": 0, "warn": 1, "error": 2}
    worst = max((status_rank.get(item["status"], 2) for item in checks), default=0)
    status = "ok" if worst == 0 else "warning" if worst == 1 else "error"
    recommendations: list[str] = []
    for item in checks:
        action = item.get("action")
        if item.get("status") == "ok" or not isinstance(action, str) or not action.strip():
            continue
        if action not in recommendations:
            recommendations.append(action)

    return {
        "status": status,
        "ok": status == "ok",
        "service_alive": True,
        "service_base_url": service_base_url,
        "model": config.get("model"),
        "file_upload_mode": config.get("file_upload_mode"),
        "session_source": config.get("session_source"),
        "auth_required": has_api_key or not allow_unauth,
        "has_api_key": has_api_key,
        "has_token": has_token,
        "check_count": len(checks),
        "error_count": sum(1 for item in checks if item.get("status") == "error"),
        "warning_count": sum(1 for item in checks if item.get("status") == "warn"),
        "checks": checks,
        "recommendations": recommendations,
    }
