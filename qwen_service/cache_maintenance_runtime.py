"""Runtime cache maintenance for standalone Qwen service.

The Qwen service keeps two small JSON-backed runtime caches under ``runtime/``:
provider file metadata and local session registry.  They are intentionally not
source files, but without a maintenance hook they can grow stale after many
PDF/upload/debug runs.  This module provides a protected, provider-safe cleanup
payload that does not call external Qwen endpoints.
"""

from __future__ import annotations

from typing import Any


DEFAULT_FILE_CACHE_MAX_AGE_DAYS = 7
DEFAULT_SESSION_CACHE_MAX_AGE_DAYS = 30


def _positive_int(value: Any, default: int, *, min_value: int = 1, max_value: int = 3650) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(min_value, min(max_value, parsed))


def _store_stats(store: Any | None) -> dict[str, Any]:
    if store is None:
        return {"enabled": False, "entries": 0}
    stats_fn = getattr(store, "stats", None)
    if callable(stats_fn):
        try:
            payload = stats_fn()
            if isinstance(payload, dict):
                payload.setdefault("enabled", True)
                return payload
        except Exception as exc:
            return {"enabled": True, "error": str(exc)}
    all_fn = getattr(store, "all", None)
    entries = 0
    if callable(all_fn):
        try:
            data = all_fn()
            entries = len(data) if isinstance(data, dict) else 0
        except Exception:
            entries = 0
    path = str(getattr(store, "path", "") or "")
    return {"enabled": True, "path": path, "entries": entries}


def _clear_store(store: Any | None) -> int:
    if store is None:
        return 0
    before = 0
    all_fn = getattr(store, "all", None)
    if callable(all_fn):
        try:
            data = all_fn()
            before = len(data) if isinstance(data, dict) else 0
        except Exception:
            before = 0
    clear_fn = getattr(store, "clear", None)
    if callable(clear_fn):
        result = clear_fn()
        if isinstance(result, int):
            return result
        return before
    return 0


def _prune_store(store: Any | None, *, max_age_days: int, dry_run: bool) -> dict[str, Any]:
    if store is None:
        return {"enabled": False, "max_age_days": max_age_days, "dry_run": dry_run, "removed": 0, "candidates": 0}
    prune_fn = getattr(store, "prune_older_than_days", None)
    if not callable(prune_fn):
        return {
            "enabled": True,
            "max_age_days": max_age_days,
            "dry_run": dry_run,
            "removed": 0,
            "candidates": 0,
            "error": "store does not support prune_older_than_days",
        }
    result = prune_fn(max_age_days=max_age_days, dry_run=dry_run)
    return result if isinstance(result, dict) else {"enabled": True, "removed": 0, "candidates": 0}


def build_cache_maintenance_payload(*, state: Any, request: Any) -> dict[str, Any]:
    """Inspect/prune local runtime caches without contacting external Qwen.

    ``request`` is intentionally duck-typed so service.py can pass a Pydantic
    model without coupling this helper to FastAPI imports.
    """
    config: dict[str, Any] = getattr(state, "config", {}) or {}
    dry_run = bool(getattr(request, "dry_run", True))
    clear_file_metadata = bool(getattr(request, "clear_file_metadata", False))
    clear_session_registry = bool(getattr(request, "clear_session_registry", False))
    prune_file_metadata = bool(getattr(request, "prune_file_metadata", True))
    prune_session_registry = bool(getattr(request, "prune_session_registry", True))

    file_max_age_days = _positive_int(
        getattr(request, "file_max_age_days", None) or config.get("file_metadata_cache_max_age_days"),
        DEFAULT_FILE_CACHE_MAX_AGE_DAYS,
    )
    session_max_age_days = _positive_int(
        getattr(request, "session_max_age_days", None) or config.get("session_registry_cache_max_age_days"),
        DEFAULT_SESSION_CACHE_MAX_AGE_DAYS,
    )

    file_store = getattr(state, "uploaded_file_store", None)
    session_store = getattr(state, "session_registry_store", None)

    before = {
        "file_metadata": _store_stats(file_store),
        "session_registry": _store_stats(session_store),
    }

    file_result: dict[str, Any]
    session_result: dict[str, Any]

    if clear_file_metadata:
        removed = 0 if dry_run else _clear_store(file_store)
        file_result = {
            "enabled": file_store is not None,
            "operation": "clear",
            "dry_run": dry_run,
            "removed": removed,
            "candidates": int(before["file_metadata"].get("entries") or 0),
        }
    elif prune_file_metadata:
        file_result = _prune_store(file_store, max_age_days=file_max_age_days, dry_run=dry_run)
        file_result["operation"] = "prune_older_than"
    else:
        file_result = {"enabled": file_store is not None, "operation": "skip", "dry_run": dry_run, "removed": 0, "candidates": 0}

    if clear_session_registry:
        removed = 0 if dry_run else _clear_store(session_store)
        session_result = {
            "enabled": session_store is not None,
            "operation": "clear",
            "dry_run": dry_run,
            "removed": removed,
            "candidates": int(before["session_registry"].get("entries") or 0),
        }
        if not dry_run:


            with state.registry_lock:
                state.active_sessions.clear()
                state.session_qwen_clients.clear()
                state.session_locks.clear()
                state.auto_continue_tracker.clear()
    elif prune_session_registry:
        session_result = _prune_store(session_store, max_age_days=session_max_age_days, dry_run=dry_run)
        session_result["operation"] = "prune_older_than"
        removed_ids = session_result.get("removed_ids") if isinstance(session_result, dict) else []
        if not dry_run and isinstance(removed_ids, list) and removed_ids:
            with state.registry_lock:
                for sid in removed_ids:
                    clean_sid = str(sid or "").strip()
                    if not clean_sid:
                        continue
                    state.active_sessions.pop(clean_sid, None)
                    state.session_qwen_clients.pop(clean_sid, None)
                    state.session_locks.pop(clean_sid, None)
                    state.auto_continue_tracker.pop(clean_sid, None)
    else:
        session_result = {"enabled": session_store is not None, "operation": "skip", "dry_run": dry_run, "removed": 0, "candidates": 0}

    after = {
        "file_metadata": _store_stats(file_store),
        "session_registry": _store_stats(session_store),
        "runtime": {
            "active_sessions": len(getattr(state, "active_sessions", {}) or {}),
            "session_clients": len(getattr(state, "session_qwen_clients", {}) or {}),
            "session_locks": len(getattr(state, "session_locks", {}) or {}),
        },
    }

    total_candidates = int(file_result.get("candidates") or 0) + int(session_result.get("candidates") or 0)
    total_removed = int(file_result.get("removed") or 0) + int(session_result.get("removed") or 0)

    return {
        "status": "ok",
        "dry_run": dry_run,
        "provider_called": False,
        "file_max_age_days": file_max_age_days,
        "session_max_age_days": session_max_age_days,
        "total_candidates": total_candidates,
        "total_removed": 0 if dry_run else total_removed,
        "before": before,
        "operations": {
            "file_metadata": file_result,
            "session_registry": session_result,
        },
        "after": after,
        "message": (
            "Dry-run выполнен: runtime-кэши не изменены."
            if dry_run
            else f"Maintenance выполнен: удалено {total_removed} stale runtime-записей."
        ),
    }
