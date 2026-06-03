"""Qwen file upload/download endpoint runtime helpers.

This module keeps standalone service routes thin without changing the Qwen
transport implementation.  It deliberately receives runtime clients/callables
from ``service.py`` so importing it does not create QwenAPI instances.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

try:
    from .defaults import DEFAULT_FILE_UPLOAD_MAX_FILES, DEFAULT_FILE_UPLOAD_MAX_SIZE_MB
    from .qwen_api import QwenProviderError
    from .error_payload import raise_provider_http_error
    from .upload_validation import (
        file_max_size_bytes,
        max_files_per_message,
        normalize_request_file_paths,
        prevalidate_upload_paths,
        raise_upload_http_error,
    )
except ImportError:  # pragma: no cover - direct script compatibility
    from defaults import DEFAULT_FILE_UPLOAD_MAX_FILES, DEFAULT_FILE_UPLOAD_MAX_SIZE_MB
    from qwen_api import QwenProviderError
    from error_payload import raise_provider_http_error
    from upload_validation import (
        file_max_size_bytes,
        max_files_per_message,
        normalize_request_file_paths,
        prevalidate_upload_paths,
        raise_upload_http_error,
    )



def _extract_file_infos(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Collect provider file_info objects from upload responses."""
    if not isinstance(payload, dict):
        return []
    candidates: list[Any] = []
    if isinstance(payload.get("file_info"), dict):
        candidates.append(payload.get("file_info"))
    for key in ("file_infos", "files"):
        value = payload.get(key)
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))
    return [item for item in candidates if isinstance(item, dict)]


def _register_uploaded_file_infos(
    file_infos: list[dict[str, Any]],
    *,
    uploaded_file_store: Any | None = None,
    clients: list[Any] | tuple[Any, ...] | None = None,
) -> None:
    """Persist file metadata and hydrate active provider clients when available."""
    if not file_infos:
        return

    registered = file_infos
    if uploaded_file_store is not None:
        try:
            registered = uploaded_file_store.register_many(file_infos) or file_infos
        except Exception:
            logging.exception("Cannot persist Qwen uploaded file metadata")

    for client in clients or []:
        uploaded = getattr(client, "_uploaded_files", None)
        if not isinstance(uploaded, dict):
            continue
        for item in registered:
            fid = str(item.get("file_id") or item.get("id") or "").strip()
            if fid:
                uploaded[fid] = dict(item)


def _upload_limits(config: dict[str, Any] | None) -> tuple[int, int]:
    """Return (max_files, max_size_bytes) for current runtime config."""
    cfg = config or {}
    return (
        max_files_per_message(cfg, DEFAULT_FILE_UPLOAD_MAX_FILES),
        file_max_size_bytes(cfg, DEFAULT_FILE_UPLOAD_MAX_SIZE_MB),
    )


def _normalize_and_prevalidate_paths(
    *,
    config: dict[str, Any] | None,
    file_path: str = "",
    file_paths: Any = None,
) -> list[str]:
    max_files, max_size = _upload_limits(config)
    paths = normalize_request_file_paths(
        file_path=file_path,
        file_paths=file_paths,
        max_files=max_files,
    )
    if not paths:
        raise HTTPException(status_code=400, detail="Не указан путь к файлу")
    prevalidate_upload_paths(paths, max_size_bytes=max_size)
    return paths


async def upload_files_payload_from_state(
    file_path_data: dict[str, Any],
    *,
    state: Any,
    run_qwen_locked: Callable[..., Awaitable[Any]],
    uploaded_file_store: Any | None = None,
) -> dict[str, Any]:
    """Upload local files using the shared runtime state's control client."""
    return await upload_files_payload(
        file_path_data,
        qwen_api=state.control_qwen_api,
        run_qwen_locked=run_qwen_locked,
        config=state.config,
        uploaded_file_store=getattr(state, "uploaded_file_store", None),
    )


async def upload_files_and_send_message_from_state(
    request: Any,
    *,
    state: Any,
    new_qwen_api: Callable[[], Any],
    provider_error_cls: type[Exception] = QwenProviderError,
    run_with_provider_slot: Callable[[str, Callable[[], Any]], Any] | None = None,
    upload_message_lock: Any | None = None,
    get_session_lock: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Upload files and send a prompt using runtime-state session clients."""
    paths = _normalize_and_prevalidate_paths(
        config=state.config,
        file_path=request.file_path,
        file_paths=request.file_paths,
    )

    try:
        if request.session_id:
            client = state.get_session_client(
                request.session_id,
                client_factory=new_qwen_api,
                provider_error_cls=provider_error_cls,
            )
            client.session_id = request.session_id
        else:
            client = new_qwen_api()
            if client is None:
                raise provider_error_cls("Qwen API не инициализирован")

        def _send_files_message() -> dict[str, Any]:
            return client.send_files_message(
                file_paths=paths,
                message=request.message or "",
                session_id=request.session_id,
                thinking_enabled=request.thinking_enabled,
                search_enabled=request.search_enabled,
                auto_continue=request.auto_continue,
                session_prompt=request.session_prompt or "",
            )

        def _run_send_with_optional_guards() -> dict[str, Any]:
            def _with_provider_slot() -> dict[str, Any]:
                if run_with_provider_slot is not None:
                    return run_with_provider_slot("upload_and_send", _send_files_message)
                return _send_files_message()

            lock = get_session_lock(request.session_id) if request.session_id and get_session_lock else None
            if upload_message_lock is not None:
                with upload_message_lock:
                    if lock is not None:
                        with lock:
                            return _with_provider_slot()
                    return _with_provider_slot()
            if lock is not None:
                with lock:
                    return _with_provider_slot()
            return _with_provider_slot()

        result = await run_in_threadpool(_run_send_with_optional_guards)
        file_infos = _extract_file_infos(result)
        _register_uploaded_file_infos(
            file_infos,
            uploaded_file_store=getattr(state, "uploaded_file_store", None),
            clients=[client, state.control_qwen_api],
        )

        sid = str(result.get("session_id") or "")
        if sid:
            state.register_session_client(sid, client)
            if hasattr(state, "touch_active_session"):
                state.touch_active_session(sid, title=str(result.get("title") or "Файловый чат"), source="upload_and_send")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Qwen upload-and-send failed")
        raise_provider_http_error(exc, operation="upload_and_send")


async def fetch_file_info_from_state(
    file_id: str,
    *,
    state: Any,
    run_qwen_locked: Callable[..., Awaitable[Any]],
) -> dict[str, Any]:
    """Fetch uploaded file metadata using the shared runtime state's control client."""
    return await fetch_file_info(
        file_id,
        qwen_api=state.control_qwen_api,
        run_qwen_locked=run_qwen_locked,
        uploaded_file_store=getattr(state, "uploaded_file_store", None),
    )


def _ensure_qwen_api(qwen_api: Any) -> Any:
    if not qwen_api:
        raise HTTPException(status_code=503, detail="Qwen API не инициализирован")
    return qwen_api


async def upload_files_payload(
    file_path_data: dict[str, Any],
    *,
    qwen_api: Any,
    run_qwen_locked: Callable[..., Awaitable[Any]],
    config: dict[str, Any] | None = None,
    uploaded_file_store: Any | None = None,
) -> dict[str, Any]:
    """Upload one or many existing local files to Qwen provider."""

    client = _ensure_qwen_api(qwen_api)
    file_path = str(file_path_data.get("file_path") or "").strip()
    raw_file_paths = file_path_data.get("file_paths") or []
    if raw_file_paths and not isinstance(raw_file_paths, list):
        raise HTTPException(status_code=400, detail="file_paths must be a list")

    paths = _normalize_and_prevalidate_paths(
        config=config,
        file_path=file_path,
        file_paths=raw_file_paths,
    )

    try:
        if len(paths) == 1:
            file_info = await run_qwen_locked(client.upload_file, paths[0])
            if not file_info:
                raise HTTPException(status_code=500, detail="Не удалось загрузить файл")
            _register_uploaded_file_infos(
                [file_info],
                uploaded_file_store=uploaded_file_store,
                clients=[client],
            )
            return {"file_id": file_info.get("file_id") or file_info.get("id"), "file_info": file_info}

        file_infos = await run_qwen_locked(client.upload_files, paths)
        file_ids = [str(item.get("file_id") or item.get("id")) for item in file_infos if item]
        _register_uploaded_file_infos(
            [item for item in file_infos if isinstance(item, dict)],
            uploaded_file_store=uploaded_file_store,
            clients=[client],
        )
        return {"file_ids": file_ids, "files": file_infos, "file_infos": file_infos}
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Qwen file upload failed")
        raise_upload_http_error(exc)


async def upload_files_and_send_message(
    request: Any,
    *,
    new_qwen_api: Callable[[], Any],
    get_session_qwen_api: Callable[[str], Any],
    register_session_qwen_api: Callable[[str, Any], None],
) -> dict[str, Any]:
    """Upload one or many files and send one prompt with all files attached."""

    paths = _normalize_and_prevalidate_paths(
        config=None,
        file_path=request.file_path,
        file_paths=request.file_paths,
    )

    try:
        client = get_session_qwen_api(request.session_id) if request.session_id else new_qwen_api()
        if client is None:
            raise QwenProviderError("Qwen API не инициализирован")
        if request.session_id:
            client.session_id = request.session_id

        def _send_files_message() -> dict[str, Any]:
            return client.send_files_message(
                file_paths=paths,
                message=request.message or "",
                session_id=request.session_id,
                thinking_enabled=request.thinking_enabled,
                search_enabled=request.search_enabled,
                auto_continue=request.auto_continue,
                session_prompt=request.session_prompt or "",
            )

        def _run_send_with_optional_guards() -> dict[str, Any]:
            def _with_provider_slot() -> dict[str, Any]:
                if run_with_provider_slot is not None:
                    return run_with_provider_slot("upload_and_send", _send_files_message)
                return _send_files_message()

            lock = get_session_lock(request.session_id) if request.session_id and get_session_lock else None
            if upload_message_lock is not None:
                with upload_message_lock:
                    if lock is not None:
                        with lock:
                            return _with_provider_slot()
                    return _with_provider_slot()
            if lock is not None:
                with lock:
                    return _with_provider_slot()
            return _with_provider_slot()

        result = await run_in_threadpool(_run_send_with_optional_guards)
        file_infos = _extract_file_infos(result)
        _register_uploaded_file_infos(file_infos, clients=[client])

        sid = str(result.get("session_id") or "")
        if sid:
            register_session_qwen_api(sid, client)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Qwen upload-and-send failed")
        raise_provider_http_error(exc, operation="upload_and_send")


async def fetch_file_info(
    file_id: str,
    *,
    qwen_api: Any,
    run_qwen_locked: Callable[..., Awaitable[Any]],
    uploaded_file_store: Any | None = None,
) -> dict[str, Any]:
    """Fetch uploaded file metadata when provider client supports it."""

    client = _ensure_qwen_api(qwen_api)
    fid = str(file_id or "").strip()
    if not fid:
        raise HTTPException(status_code=400, detail="file_id must not be empty")

    if uploaded_file_store is not None:
        stored = uploaded_file_store.get(fid)
        if stored:
            uploaded = getattr(client, "_uploaded_files", None)
            if isinstance(uploaded, dict):
                uploaded[fid] = dict(stored)
            return {"file_info": stored, "source": "metadata_store"}

    cached = getattr(client, "_uploaded_files", {}).get(fid)
    if cached:
        return {"file_info": cached, "source": "runtime_cache"}

    if not hasattr(client, "fetch_files"):
        raise HTTPException(
            status_code=404,
            detail=(
                "Файл не найден в runtime-cache qwen_service. Повторите upload-and-send "
                "или загрузите файл через /files/upload в текущем процессе qwen_service."
            ),
        )

    try:
        file_info = await run_qwen_locked(client.fetch_files, [fid])
        if not file_info:
            raise HTTPException(status_code=404, detail="Файл не найден")
        return {"file_info": file_info[0], "source": "provider"}
    except HTTPException:
        raise
    except Exception as exc:
        raise_provider_http_error(exc, operation="file_info")
