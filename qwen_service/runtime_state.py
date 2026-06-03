"""Mutable runtime state container for the standalone Qwen service.

The service module still owns FastAPI routes and startup bootstrap, but this
container centralizes runtime objects that used to live as separate globals.
Keeping the state in one object makes the next split into app factory + routes
safer without changing Qwen transport or public endpoints.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import BoundedSemaphore, RLock
from typing import Any


@dataclass(slots=True)
class QwenRuntimeState:
    """In-memory mutable state for qwen_service runtime.

    The class intentionally avoids importing QwenAPI to keep this module light
    and import-safe. API clients are typed as Any here because concrete provider
    classes are still owned by qwen_api.py / service bootstrap.
    """

    config: dict[str, Any]
    project_root: Path
    service_dir: Path
    env_path: Path
    provider_default_concurrency: int

    control_qwen_api: Any | None = None
    uploaded_file_store: Any | None = None
    session_registry_store: Any | None = None
    event_journal_store: Any | None = None
    active_sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    auto_continue_tracker: dict[str, dict[str, Any]] = field(default_factory=dict)
    session_qwen_clients: dict[str, Any] = field(default_factory=dict)
    session_locks: dict[str, RLock] = field(default_factory=dict)
    registry_lock: RLock = field(default_factory=RLock)
    request_lock: RLock = field(default_factory=RLock)
    provider_start_lock: RLock = field(default_factory=RLock)
    provider_activity_lock: RLock = field(default_factory=RLock)
    provider_active_requests: int = 0
    provider_active_operations: dict[str, int] = field(default_factory=dict)
    provider_next_start_at: float = 0.0
    auth_status_cache: dict[str, Any] = field(default_factory=lambda: {"value": None, "checked_at": 0.0})
    current_qwen_client: ContextVar[Any | None] = field(
        default_factory=lambda: ContextVar("current_qwen_client", default=None)
    )
    provider_request_semaphore: BoundedSemaphore = field(init=False)

    def __post_init__(self) -> None:
        self.provider_request_semaphore = BoundedSemaphore(int(self.provider_default_concurrency or 1))


    def begin_provider_request(self, operation: str) -> None:
        op = str(operation or "provider_request")
        with self.provider_activity_lock:
            self.provider_active_requests += 1
            self.provider_active_operations[op] = int(self.provider_active_operations.get(op) or 0) + 1

    def end_provider_request(self, operation: str) -> None:
        op = str(operation or "provider_request")
        with self.provider_activity_lock:
            self.provider_active_requests = max(0, self.provider_active_requests - 1)
            current = int(self.provider_active_operations.get(op) or 0) - 1
            if current > 0:
                self.provider_active_operations[op] = current
            else:
                self.provider_active_operations.pop(op, None)

    def provider_activity_snapshot(self) -> dict[str, Any]:
        with self.provider_activity_lock:
            return {
                "provider_active_requests": int(self.provider_active_requests),
                "provider_active_operations": dict(self.provider_active_operations),
            }

    def clear_clients_and_sessions(self, *, clear_persistent_registry: bool = True) -> None:
        """Drop provider clients/sessions after token or browser headers changed.

        Caller must hold request_lock. This method only resets local runtime
        objects; recreating the control client is still done by service.py, which
        owns the QwenAPI factory.
        """
        self.session_qwen_clients.clear()
        self.session_locks.clear()
        self.active_sessions.clear()
        if clear_persistent_registry and self.session_registry_store is not None:
            try:
                self.session_registry_store.clear()
            except Exception:
                pass
        self.auto_continue_tracker.clear()
        self.control_qwen_api = None
        self.clear_auth_cache()

    def record_event(
        self,
        event: str,
        *,
        status: str = "ok",
        message: str = "",
        session_id: str | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Best-effort append to the local diagnostics event journal."""
        store = self.event_journal_store
        if store is None:
            return None
        try:
            return store.record(
                event,
                status=status,
                message=message,
                session_id=session_id,
                operation=operation,
                details=details,
            )
        except Exception:
            return None


    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _session_sort_value(metadata: dict[str, Any]) -> float:
        if not isinstance(metadata, dict):
            return 0.0
        value = metadata.get("last_used_at") or metadata.get("updated_at") or metadata.get("created_at")
        if value is None:
            return 0.0
        try:
            numeric = float(value)
            return numeric / 1000 if numeric > 10_000_000_000 else numeric
        except Exception:
            pass
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except Exception:
            return 0.0

    def load_persisted_sessions(self, *, max_sessions: int | None = None) -> int:
        """Hydrate local active_sessions from the JSON-backed registry store."""
        store = self.session_registry_store
        if store is None:
            return 0
        try:
            sessions = store.all()
        except Exception:
            return 0
        limit = max(0, int(max_sessions or 0))
        if limit and len(sessions) > limit:
            sessions = dict(
                sorted(
                    sessions.items(),
                    key=lambda item: self._session_sort_value(item[1]),
                )[-limit:]
            )
        with self.registry_lock:
            self.active_sessions.update({sid: dict(meta) for sid, meta in sessions.items()})
            for sid in sessions:
                self.session_locks.setdefault(sid, RLock())
            return len(sessions)

    def register_active_session(
        self,
        session_id: str,
        *,
        title: str = "Новый чат",
        source: str = "runtime",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Register/update local session metadata and persist it best-effort."""
        sid = str(session_id or "").strip()
        if not sid:
            return None
        now = self._now_iso()
        with self.registry_lock:
            current = dict(self.active_sessions.get(sid) or {})
            record: dict[str, Any] = {
                **current,
                **(metadata if isinstance(metadata, dict) else {}),
                "session_id": sid,
                "title": str(title or current.get("title") or "Новый чат").strip() or "Новый чат",
                "created_at": str(current.get("created_at") or now),
                "updated_at": now,
                "last_used_at": now,
                "source": str(source or current.get("source") or "runtime"),
            }
            self.active_sessions[sid] = record
            self.session_locks.setdefault(sid, RLock())
        store = self.session_registry_store
        if store is not None:
            try:
                persisted = store.register(sid, title=record["title"], source=record["source"], metadata=record)
                if persisted:
                    with self.registry_lock:
                        self.active_sessions[sid] = dict(persisted)
                    return dict(persisted)
            except Exception:
                pass
        return dict(record)

    def touch_active_session(self, session_id: str, *, title: str | None = None, source: str = "message") -> dict[str, Any] | None:
        """Update last-used metadata for an existing or externally restored session."""
        sid = str(session_id or "").strip()
        if not sid:
            return None
        now = self._now_iso()
        with self.registry_lock:
            record = dict(self.active_sessions.get(sid) or {})
            record.setdefault("session_id", sid)
            record.setdefault("title", "Восстановленный чат")
            record.setdefault("created_at", now)
            record.setdefault("source", source)
            if title is not None and str(title or "").strip():
                record["title"] = str(title or "").strip()
            record["updated_at"] = now
            record["last_used_at"] = now
            self.active_sessions[sid] = record
            self.session_locks.setdefault(sid, RLock())
        store = self.session_registry_store
        if store is not None:
            try:
                persisted = store.touch(sid, title=title, source=source)
                if persisted:
                    with self.registry_lock:
                        self.active_sessions[sid] = dict(persisted)
                    return dict(persisted)
            except Exception:
                pass
        return dict(record)

    def rename_active_session(self, session_id: str, title: str) -> None:
        sid = str(session_id or "").strip()
        clean_title = str(title or "").strip() or "Новый чат"
        if not sid:
            return
        with self.registry_lock:
            record = dict(self.active_sessions.get(sid) or {"session_id": sid, "created_at": self._now_iso()})
            record["title"] = clean_title
            record["updated_at"] = self._now_iso()
            self.active_sessions[sid] = record
        store = self.session_registry_store
        if store is not None:
            try:
                store.update_title(sid, clean_title)
            except Exception:
                pass

    def remove_active_session(self, session_id: str) -> None:
        sid = str(session_id or "").strip()
        if not sid:
            return
        with self.registry_lock:
            self.active_sessions.pop(sid, None)
        store = self.session_registry_store
        if store is not None:
            try:
                store.remove(sid)
            except Exception:
                pass

    def clear_auth_cache(self) -> None:
        self.auth_status_cache["value"] = None
        self.auth_status_cache["checked_at"] = 0.0
    def get_session_lock(self, session_id: str) -> RLock:
        """Return a stable lock for a Qwen chat session."""
        with self.registry_lock:
            return self.session_locks.setdefault(session_id, RLock())

    def get_session_client(self, session_id: str, *, client_factory, provider_error_cls=RuntimeError) -> Any:
        """Return/create a dedicated Qwen client for one session."""
        with self.registry_lock:
            client = self.session_qwen_clients.get(session_id)
            if client is None:
                client = client_factory()
                if client is None:
                    raise provider_error_cls("Qwen API is not initialized")
                client.session_id = session_id
                self.session_qwen_clients[session_id] = client
                self.session_locks.setdefault(session_id, RLock())
            return client

    def register_session_client(self, session_id: str, client: Any) -> None:
        """Register a dedicated provider client for one session."""
        with self.registry_lock:
            client.session_id = session_id
            self.session_qwen_clients[session_id] = client
            self.session_locks.setdefault(session_id, RLock())

    def drop_session_client(self, session_id: str) -> None:
        """Drop local provider client, lock and continuation state for one session."""
        with self.registry_lock:
            self.session_qwen_clients.pop(session_id, None)
            self.session_locks.pop(session_id, None)
            self.auto_continue_tracker.pop(session_id, None)

    def active_session_count(self) -> int:
        with self.registry_lock:
            return len(self.active_sessions)

    def set_model_for_clients(self, model: str) -> None:
        """Apply selected model to control and dedicated session clients."""
        with self.registry_lock:
            if self.control_qwen_api is not None:
                self.control_qwen_api.set_model(model)
            for client in self.session_qwen_clients.values():
                client.set_model(model)

