"""Runtime helpers for Qwen session endpoints.

This module keeps FastAPI route functions in ``service.py`` thin while avoiding
changes to Qwen transport/session provider behavior.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool


def _not_initialized() -> HTTPException:
    return HTTPException(status_code=503, detail="Qwen API не инициализирован")



async def create_session_payload_from_state(
    request: Any | None,
    *,
    state: Any,
    current_max_active_sessions: Callable[[], int],
    new_qwen_api: Callable[[], Any],
    run_with_provider_slot: Callable[[str, Callable[[], Any]], Any],
    token_expired_checker: Callable[[str | None], bool],
) -> dict[str, Any]:
    """Create a provider session using the shared runtime state container."""
    if not state.control_qwen_api:
        raise _not_initialized()

    try:
        with state.registry_lock:
            active_count = len(state.active_sessions)
            max_active = current_max_active_sessions()
            if active_count >= max_active:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "qwen_max_active_sessions",
                        "message": f"Достигнут лимит активных Qwen-чатов: {max_active}.",
                        "active_sessions": active_count,
                        "max_active_sessions": max_active,
                    },
                )

        client = new_qwen_api()
        if client is None:
            raise _not_initialized()

        session_id = await run_in_threadpool(
            lambda: run_with_provider_slot("create_session", client.create_session)
        )
        logging.info("create_session returned: %s", session_id)
        if not session_id:
            logging.error("create_session returned None")
            raise HTTPException(status_code=500, detail="Не удалось создать сессию")

        title = (request.title.strip() if request and getattr(request, "title", None) else "") or "Новый чат"
        if request and getattr(request, "title", None):
            try:
                await run_in_threadpool(client.update_session_title, session_id, title)
            except Exception as rename_exc:  # pragma: no cover - provider/network specific
                logging.warning("Failed to set session title for %s: %s", session_id, rename_exc)

        state.register_session_client(session_id, client)
        if hasattr(state, "register_active_session"):
            state.register_active_session(session_id, title=title, source="create_session")
        else:
            with state.registry_lock:
                state.active_sessions[session_id] = {
                    "session_id": session_id,
                    "title": title,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }

        return {"session_id": session_id, "title": title}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Error creating session: %s", exc)
        message = str(exc)
        if token_expired_checker(message):
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "qwen_token_expired",
                    "message": "Qwen токен истёк. Обновите QWEN_TOKEN.",
                },
            ) from exc
        raise HTTPException(status_code=500, detail=message) from exc


async def list_sessions_payload_from_state(
    state: Any,
    *,
    run_qwen_locked: Callable[..., Any],
) -> dict[str, Any]:
    return await list_sessions_payload(state.control_qwen_api, run_qwen_locked=run_qwen_locked)


async def get_session_payload_from_state(
    session_id: str,
    *,
    state: Any,
    new_qwen_api: Callable[[], Any],
    provider_error_cls: type[Exception],
) -> dict[str, Any]:
    """Fetch history using the session client stored in runtime state."""
    try:
        client = state.get_session_client(
            session_id,
            client_factory=new_qwen_api,
            provider_error_cls=provider_error_cls,
        )
        session_lock = state.get_session_lock(session_id)

        def _get_history() -> tuple[dict[str, Any], list[dict[str, Any]]]:
            with session_lock:
                token = state.current_qwen_client.set(client)
                try:
                    client.session_id = session_id
                    return client.fetch_history(session_id)
                finally:
                    state.current_qwen_client.reset(token)

        history, messages = await run_in_threadpool(_get_history)
        return {"session_id": session_id, "history": history, "messages": messages}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def delete_session_payload_from_state(
    session_id: str,
    *,
    state: Any,
    new_qwen_api: Callable[[], Any],
    provider_error_cls: type[Exception],
) -> dict[str, Any]:
    """Delete provider session and always clean local runtime state on failure."""
    try:
        client = state.get_session_client(
            session_id,
            client_factory=new_qwen_api,
            provider_error_cls=provider_error_cls,
        )
        session_lock = state.get_session_lock(session_id)

        def _delete() -> bool:
            with session_lock:
                return bool(client.delete_session(session_id))

        success = await run_in_threadpool(_delete)
        if success:
            if hasattr(state, "remove_active_session"):
                state.remove_active_session(session_id)
            else:
                with state.registry_lock:
                    state.active_sessions.pop(session_id, None)
            state.drop_session_client(session_id)
        return {"status": "ok", "deleted": success}
    except Exception as exc:
        logging.warning(
            "Remote Qwen session delete failed for %s; dropping local session: %s",
            session_id[-8:],
            exc,
        )
        if hasattr(state, "remove_active_session"):
            state.remove_active_session(session_id)
        else:
            with state.registry_lock:
                state.active_sessions.pop(session_id, None)
        state.drop_session_client(session_id)
        return {
            "status": "warning",
            "deleted": False,
            "local_deleted": True,
            "message": "Локальная Qwen-сессия очищена, удалённый provider-delete не подтвердился.",
            "detail": str(exc),
        }


async def rename_session_payload_from_state(
    session_id: str,
    title_data: dict[str, str],
    *,
    state: Any,
    new_qwen_api: Callable[[], Any],
    provider_error_cls: type[Exception],
) -> dict[str, Any]:
    title = str(title_data.get("title") or "Новый чат").strip() or "Новый чат"
    try:
        client = state.get_session_client(
            session_id,
            client_factory=new_qwen_api,
            provider_error_cls=provider_error_cls,
        )
        session_lock = state.get_session_lock(session_id)

        def _rename() -> bool:
            with session_lock:
                return bool(client.update_session_title(session_id, title))

        success = await run_in_threadpool(_rename)
        if success:
            if hasattr(state, "rename_active_session"):
                state.rename_active_session(session_id, title)
            else:
                with state.registry_lock:
                    if session_id in state.active_sessions:
                        state.active_sessions[session_id]["title"] = title
        return {"status": "ok", "title": title}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def create_session_payload(
    request: Any | None,
    *,
    qwen_api: Any,
    registry_lock: Any,
    active_sessions: dict[str, dict[str, Any]],
    current_max_active_sessions: Callable[[], int],
    new_qwen_api: Callable[[], Any],
    run_with_provider_slot: Callable[[str, Callable[[], Any]], Any],
    register_session_qwen_api: Callable[[str, Any], None],
    token_expired_checker: Callable[[str | None], bool],
    service_file: str | Path,
) -> dict[str, Any]:
    """Create a Qwen provider session and register its dedicated client."""
    if not qwen_api:
        raise _not_initialized()

    try:
        with registry_lock:
            active_count = len(active_sessions)
            max_active = current_max_active_sessions()
            if active_count >= max_active:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "qwen_max_active_sessions",
                        "message": f"Достигнут лимит активных Qwen-чатов: {max_active}.",
                        "active_sessions": active_count,
                        "max_active_sessions": max_active,
                    },
                )

        client = new_qwen_api()
        if client is None:
            raise _not_initialized()

        session_id = await run_in_threadpool(
            lambda: run_with_provider_slot("create_session", client.create_session)
        )
        logging.info("create_session returned: %s", session_id)
        if not session_id:
            logging.error("create_session returned None")
            raise HTTPException(status_code=500, detail="Не удалось создать сессию")

        title = (request.title.strip() if request and getattr(request, "title", None) else "") or "Новый чат"
        if request and getattr(request, "title", None):
            try:
                await run_in_threadpool(client.update_session_title, session_id, title)
            except Exception as rename_exc:  # pragma: no cover - provider/network specific
                logging.warning("Failed to set session title for %s: %s", session_id, rename_exc)

        register_session_qwen_api(session_id, client)
        with registry_lock:
            active_sessions[session_id] = {
                "session_id": session_id,
                "title": title,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "last_used_at": datetime.now(timezone.utc).isoformat(),
                "source": "create_session",
            }

        return {"session_id": session_id, "title": title}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Error creating session: %s", exc)
        message = str(exc)
        if token_expired_checker(message):
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "qwen_token_expired",
                    "message": "Qwen токен истёк. Обновите QWEN_TOKEN.",
                },
            ) from exc
        raise HTTPException(status_code=500, detail=message) from exc


async def list_sessions_payload(
    qwen_api: Any,
    *,
    run_qwen_locked: Callable[..., Any],
) -> dict[str, Any]:
    """Return Qwen provider session list."""
    if not qwen_api:
        raise _not_initialized()
    try:
        sessions, _ = await run_qwen_locked(qwen_api.fetch_sessions_page)
        return {"sessions": sessions}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def get_session_payload(
    session_id: str,
    *,
    get_session_qwen_api: Callable[[str], Any],
    get_session_lock: Callable[[str], Any],
    current_qwen_client: Any,
) -> dict[str, Any]:
    """Fetch Qwen session history/messages using its dedicated client."""
    try:
        client = get_session_qwen_api(session_id)
        session_lock = get_session_lock(session_id)

        def _get_history() -> tuple[dict[str, Any], list[dict[str, Any]]]:
            with session_lock:
                token = current_qwen_client.set(client)
                try:
                    client.session_id = session_id
                    return client.fetch_history(session_id)
                finally:
                    current_qwen_client.reset(token)

        history, messages = await run_in_threadpool(_get_history)
        return {"session_id": session_id, "history": history, "messages": messages}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def delete_session_payload(
    session_id: str,
    *,
    registry_lock: Any,
    active_sessions: dict[str, dict[str, Any]],
    get_session_qwen_api: Callable[[str], Any],
    get_session_lock: Callable[[str], Any],
    drop_session_qwen_api: Callable[[str], None],
) -> dict[str, Any]:
    """Delete a provider session and always clean up local state on provider error."""
    try:
        client = get_session_qwen_api(session_id)
        session_lock = get_session_lock(session_id)

        def _delete() -> bool:
            with session_lock:
                return bool(client.delete_session(session_id))

        success = await run_in_threadpool(_delete)
        if success:
            with registry_lock:
                active_sessions.pop(session_id, None)
            drop_session_qwen_api(session_id)
        return {"status": "ok", "deleted": success}
    except Exception as exc:
        logging.warning(
            "Remote Qwen session delete failed for %s; dropping local session: %s",
            session_id[-8:],
            exc,
        )
        with registry_lock:
            active_sessions.pop(session_id, None)
        drop_session_qwen_api(session_id)
        return {
            "status": "warning",
            "deleted": False,
            "local_deleted": True,
            "message": "Локальная Qwen-сессия очищена, удалённый provider-delete не подтвердился.",
            "detail": str(exc),
        }


async def rename_session_payload(
    session_id: str,
    title_data: dict[str, str],
    *,
    registry_lock: Any,
    active_sessions: dict[str, dict[str, Any]],
    get_session_qwen_api: Callable[[str], Any],
    get_session_lock: Callable[[str], Any],
) -> dict[str, Any]:
    """Rename Qwen session both remotely and in local registry."""
    title = str(title_data.get("title") or "Новый чат").strip() or "Новый чат"
    try:
        client = get_session_qwen_api(session_id)
        session_lock = get_session_lock(session_id)

        def _rename() -> bool:
            with session_lock:
                return bool(client.update_session_title(session_id, title))

        success = await run_in_threadpool(_rename)
        if success:
            with registry_lock:
                if session_id in active_sessions:
                    active_sessions[session_id]["title"] = title
        return {"status": "ok", "title": title}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
