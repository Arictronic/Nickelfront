"""Small JSON-backed event journal for local qwen_service diagnostics.

The journal is intentionally provider-safe and secret-free.  It stores compact
operation metadata under ``runtime/`` so the admin page can answer a practical
question without opening terminal logs: which Qwen step failed last?
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

try:
    from .defaults import DEFAULT_EVENT_JOURNAL_MAX_ENTRIES, DEFAULT_EVENT_JOURNAL_PATH
    from .har_storage import resolve_project_path
except ImportError:
    from defaults import DEFAULT_EVENT_JOURNAL_MAX_ENTRIES, DEFAULT_EVENT_JOURNAL_PATH
    from har_storage import resolve_project_path


_SECRET_KEYS = {
    "api_key",
    "authorization",
    "bearer",
    "bx_ua",
    "bx_umidtoken",
    "cookie",
    "qwen_api_key",
    "qwen_bx_ua",
    "qwen_bx_umidtoken",
    "qwen_cookie",
    "qwen_token",
    "secret",
    "security_token",
    "token",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tail(value: Any, size: int = 8) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[-size:]


def _safe_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return "<truncated>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if len(text) > 500:
            return text[:500] + "…"
        return text
    if isinstance(value, Path):
        return value.name
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            low = str(key).lower()
            if low in _SECRET_KEYS or "token" in low or "cookie" in low or "authorization" in low:
                safe[str(key)] = "<redacted>" if item else item
                continue
            if low.endswith("path") or low in {"file_path", "filename", "name"}:
                safe[str(key)] = Path(str(item)).name if item else item
                continue
            if low in {"session_id", "chat_id", "message_id"}:
                safe[str(key)] = _tail(item, 10) if low == "session_id" else item
                continue
            safe[str(key)] = _safe_value(item, depth=depth + 1)
        return safe
    if isinstance(value, (list, tuple, set)):
        result = [_safe_value(item, depth=depth + 1) for item in list(value)[:20]]
        if len(value) > 20:
            result.append("<truncated>")
        return result
    return str(value)[:500]


class QwenEventJournalStore:
    """Rolling JSON store with compact qwen_service events."""

    def __init__(self, path: Path, *, max_entries: int = DEFAULT_EVENT_JOURNAL_MAX_ENTRIES, logger: Any | None = None):
        self.path = path
        self.max_entries = max(10, min(5000, int(max_entries or DEFAULT_EVENT_JOURNAL_MAX_ENTRIES)))
        self.logger = logger
        self._lock = RLock()
        self._events: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self._events = []
                return
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(payload, list):
                    self._events = [item for item in payload if isinstance(item, dict)][-self.max_entries :]
                elif isinstance(payload, dict) and isinstance(payload.get("events"), list):
                    self._events = [item for item in payload["events"] if isinstance(item, dict)][-self.max_entries :]
                else:
                    self._events = []
            except Exception as exc:
                if self.logger:
                    self.logger.warning("Cannot read Qwen event journal %s: %s", self.path, exc)
                self._events = []

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self._events[-self.max_entries :], ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    def record(
        self,
        event: str,
        *,
        status: str = "ok",
        message: str = "",
        session_id: str | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_event = str(event or "event").strip() or "event"
        clean_status = str(status or "ok").strip().lower() or "ok"
        if clean_status not in {"ok", "warning", "error", "started"}:
            clean_status = "warning" if clean_status in {"warn", "partial"} else clean_status
        item: dict[str, Any] = {
            "ts": _now_iso(),
            "event": clean_event,
            "status": clean_status,
            "message": str(message or "").strip()[:500],
        }
        if operation:
            item["operation"] = str(operation or "").strip()[:120]
        if session_id:
            item["session_tail"] = _tail(session_id, 10)
        if details:
            safe_details = _safe_value(details)
            if isinstance(safe_details, dict) and safe_details:
                item["details"] = safe_details

        with self._lock:
            self._events.append(item)
            self._events = self._events[-self.max_entries :]
            try:
                self._save_locked()
            except Exception as exc:
                if self.logger:
                    self.logger.warning("Cannot persist Qwen event journal %s: %s", self.path, exc)
        return dict(item)

    def recent(
        self,
        *,
        limit: int = 50,
        event: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(500, int(limit or 50)))
        event_filter = str(event or "").strip().lower()
        status_filter = str(status or "").strip().lower()
        with self._lock:
            items = list(reversed(self._events))
        if event_filter:
            items = [item for item in items if str(item.get("event") or "").lower() == event_filter]
        if status_filter:
            items = [item for item in items if str(item.get("status") or "").lower() == status_filter]
        return [dict(item) for item in items[:safe_limit]]

    def clear(self) -> int:
        with self._lock:
            count = len(self._events)
            self._events = []
            try:
                self._save_locked()
            except Exception as exc:
                if self.logger:
                    self.logger.warning("Cannot clear Qwen event journal %s: %s", self.path, exc)
            return count

    def stats(self) -> dict[str, Any]:
        with self._lock:
            counts: dict[str, int] = {}
            for item in self._events:
                key = str(item.get("status") or "unknown")
                counts[key] = counts.get(key, 0) + 1
            return {
                "enabled": True,
                "path": str(self.path),
                "entries": len(self._events),
                "max_entries": self.max_entries,
                "status_counts": counts,
            }


def build_qwen_event_journal_store(config: dict[str, Any], *, project_root: Path, logger: Any | None = None) -> QwenEventJournalStore:
    raw_path = str(config.get("event_journal_path") or DEFAULT_EVENT_JOURNAL_PATH).strip() or DEFAULT_EVENT_JOURNAL_PATH
    path = resolve_project_path(raw_path, project_root=project_root, default=DEFAULT_EVENT_JOURNAL_PATH)
    max_entries = int(config.get("event_journal_max_entries") or DEFAULT_EVENT_JOURNAL_MAX_ENTRIES)
    return QwenEventJournalStore(path, max_entries=max_entries, logger=logger)
