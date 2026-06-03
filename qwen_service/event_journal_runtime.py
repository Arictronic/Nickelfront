"""Provider-safe event journal payload helpers for qwen_service diagnostics."""

from __future__ import annotations

from typing import Any


def event_status_from_payload(payload: Any) -> str:
    """Normalize a payload/result into event status."""
    if not isinstance(payload, dict):
        return "warning"
    if payload.get("error") or payload.get("error_code"):
        return "error"
    raw_status = str(payload.get("status") or "").lower()
    if raw_status in {"error", "failed", "invalid", "expired", "service_unavailable"}:
        return "error"
    if raw_status in {"warning", "warn", "partial", "rate_limited"}:
        return "warning"
    ok = payload.get("ok")
    if ok is False:
        return "error"
    return "ok"


def record_qwen_event(
    state: Any,
    event: str,
    *,
    status: str = "ok",
    message: str = "",
    session_id: str | None = None,
    operation: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Best-effort append to state's event journal without breaking requests."""
    record = getattr(state, "record_event", None)
    if not callable(record):
        return None
    try:
        return record(
            event,
            status=status,
            message=message,
            session_id=session_id,
            operation=operation,
            details=details,
        )
    except Exception:
        return None


def build_event_journal_payload(
    *,
    state: Any,
    limit: int = 50,
    event: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Return recent local qwen_service events without external provider calls."""
    store = getattr(state, "event_journal_store", None)
    if store is None:
        return {
            "status": "unavailable",
            "provider_called": False,
            "enabled": False,
            "events": [],
            "count": 0,
            "message": "Локальный журнал событий qwen_service не включён.",
        }
    try:
        events = store.recent(limit=limit, event=event, status=status)
        stats = store.stats() if hasattr(store, "stats") else {"enabled": True}
        return {
            "status": "ok",
            "provider_called": False,
            "enabled": True,
            "events": events,
            "count": len(events),
            "stats": stats,
        }
    except Exception as exc:
        return {
            "status": "error",
            "provider_called": False,
            "enabled": True,
            "events": [],
            "count": 0,
            "message": f"Не удалось прочитать журнал событий qwen_service: {exc}",
        }


def build_event_journal_clear_payload(*, state: Any) -> dict[str, Any]:
    """Clear local qwen_service event journal without touching provider state."""
    store = getattr(state, "event_journal_store", None)
    if store is None:
        return {
            "status": "unavailable",
            "provider_called": False,
            "enabled": False,
            "cleared": 0,
            "message": "Локальный журнал событий qwen_service не включён.",
        }
    try:
        cleared = int(store.clear())
        return {
            "status": "ok",
            "provider_called": False,
            "enabled": True,
            "cleared": cleared,
            "message": f"Журнал событий qwen_service очищен: удалено {cleared} записей.",
        }
    except Exception as exc:
        return {
            "status": "error",
            "provider_called": False,
            "enabled": True,
            "cleared": 0,
            "message": f"Не удалось очистить журнал событий qwen_service: {exc}",
        }
