"""Runtime session registry helpers for the standalone Qwen service."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any

SESSION_SOURCE_VALUES = {"env", "har", "manual", "cdp", "playwright"}
SESSION_VALUE_KEYS = (
    "token",
    "cookie",
    "bx_ua",
    "bx_umidtoken",
    "bx_v",
    "user_agent",
    "file_api_extra_headers_json",
    "file_sts_payload_template_json",
    "file_sts_url",
    "file_parse_payload_template_json",
    "file_parse_url",
    "file_parse_status_payload_template_json",
    "file_parse_status_url",
    "oss_put_headers_template_json",
)


def safe_session_source(source: str | None, default: str = "manual") -> str:
    value = str(source or default or "manual").strip().lower()
    return value if value in SESSION_SOURCE_VALUES else default


def session_update_summary(
    config: dict[str, Any],
    *,
    updated_fields: list[str],
    default_oss_put_mode: str,
    default_session_source: str,
    env_saved: bool,
    env_save_warning: str,
) -> dict[str, Any]:
    return {
        "updated_fields": sorted(updated_fields),
        "has_token": bool(config.get("token")),
        "has_qwen_cookie": bool(config.get("cookie")),
        "has_qwen_bx_ua": bool(config.get("bx_ua")),
        "has_qwen_bx_umidtoken": bool(config.get("bx_umidtoken")),
        "has_qwen_bx_v": bool(config.get("bx_v")),
        "has_qwen_user_agent": bool(config.get("user_agent")),
        "qwen_user_agent_len": len(str(config.get("user_agent") or "")),
        "has_file_api_extra_headers": bool(config.get("file_api_extra_headers_json")),
        "has_file_sts_payload_template": bool(config.get("file_sts_payload_template_json")),
        "has_file_sts_url": bool(config.get("file_sts_url")),
        "has_file_parse_payload_template": bool(config.get("file_parse_payload_template_json")),
        "has_file_parse_url": bool(config.get("file_parse_url")),
        "has_file_parse_status_payload_template": bool(config.get("file_parse_status_payload_template_json")),
        "has_file_parse_status_url": bool(config.get("file_parse_status_url")),
        "has_oss_put_headers_template": bool(config.get("oss_put_headers_template_json")),
        "oss_put_mode": config.get("oss_put_mode", default_oss_put_mode),
        "has_file_browser_session": bool(
            config.get("cookie") and config.get("bx_ua") and config.get("bx_umidtoken") and config.get("bx_v")
        ),
        "session_source": config.get("session_source", default_session_source),
        "env_saved": env_saved,
        "env_save_warning": env_save_warning,
    }


def apply_session_values(
    values: dict[str, Any],
    *,
    config: dict[str, Any],
    source: str = "manual",
    clear_missing: bool = False,
    reset_runtime_state: Callable[[], None],
    save_config: Callable[[dict[str, Any]], None],
    default_oss_put_mode: str,
    default_session_source: str,
    logger: Any,
) -> dict[str, Any]:
    """Apply browser-session values to runtime config and persist them best-effort."""
    updated: dict[str, bool] = {}
    for key in SESSION_VALUE_KEYS:
        if key not in values and not clear_missing:
            continue
        raw = values.get(key) if key in values else ""
        text = str(raw or "").strip()
        if key == "token" and text:
            text = "".join(text.split())
            if text.lower().startswith("bearer"):
                text = text[6:].strip()
        if text or clear_missing:
            config[key] = text
            updated[key] = bool(text)

    config["session_source"] = safe_session_source(source, "manual")
    reset_runtime_state()

    env_saved = True
    env_save_warning = ""
    try:
        save_config(config)
    except PermissionError as exc:
        env_saved = False
        env_save_warning = f".env is locked, runtime session was updated but persistence failed: {exc}"
        logger.warning("Qwen session runtime updated but .env persistence failed: %s", exc)
    except OSError as exc:
        env_saved = False
        env_save_warning = f".env persistence failed, runtime session was updated: {exc}"
        logger.warning("Qwen session runtime updated but .env persistence failed: %s", exc)

    return session_update_summary(
        config,
        updated_fields=list(updated.keys()),
        default_oss_put_mode=default_oss_put_mode,
        default_session_source=default_session_source,
        env_saved=env_saved,
        env_save_warning=env_save_warning,
    )


def get_session_lock(session_id: str, *, registry_lock: RLock, session_locks: dict[str, RLock]) -> RLock:
    with registry_lock:
        return session_locks.setdefault(session_id, RLock())


def get_session_client(
    session_id: str,
    *,
    registry_lock: RLock,
    session_clients: dict[str, Any],
    session_locks: dict[str, RLock],
    client_factory: Callable[[], Any],
    provider_error_cls: type[Exception],
) -> Any:
    with registry_lock:
        client = session_clients.get(session_id)
        if client is None:
            client = client_factory()
            if client is None:
                raise provider_error_cls("Qwen API is not initialized")
            client.session_id = session_id
            session_clients[session_id] = client
            session_locks.setdefault(session_id, RLock())
        return client


def register_session_client(
    session_id: str,
    client: Any,
    *,
    registry_lock: RLock,
    session_clients: dict[str, Any],
    session_locks: dict[str, RLock],
) -> None:
    with registry_lock:
        client.session_id = session_id
        session_clients[session_id] = client
        session_locks.setdefault(session_id, RLock())


def drop_session_client(
    session_id: str,
    *,
    registry_lock: RLock,
    session_clients: dict[str, Any],
    session_locks: dict[str, RLock],
    continuation_tracker: dict[str, dict[str, Any]],
) -> None:
    with registry_lock:
        session_clients.pop(session_id, None)
        session_locks.pop(session_id, None)
        continuation_tracker.pop(session_id, None)


def active_session_count(active_sessions: dict[str, dict[str, Any]], *, registry_lock: RLock) -> int:
    with registry_lock:
        return len(active_sessions)


def set_model_for_clients(
    model: str,
    *,
    registry_lock: RLock,
    control_client: Any,
    session_clients: dict[str, Any],
) -> None:
    with registry_lock:
        if control_client is not None:
            control_client.set_model(model)
        for client in session_clients.values():
            client.set_model(model)
