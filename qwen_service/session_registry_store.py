"""Persistent local registry for Qwen chat sessions.

Provider sessions are remote, but qwen_service keeps a local registry for
active session counters, titles and per-session locks/clients.  Without a small
runtime-backed registry a service restart makes the local session list empty,
while callers may still hold valid provider session ids.  This JSON store keeps
only non-secret metadata under project runtime/.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class QwenSessionRegistryStore:
    """Small JSON-backed cache for local Qwen session metadata."""

    def __init__(self, path: str | Path, *, max_entries: int = 500, logger: Any = logging) -> None:
        self.path = Path(path)
        self.max_entries = max(1, int(max_entries or 500))
        self.logger = logger
        self._lock = RLock()
        self._sessions: dict[str, dict[str, Any]] = {}

    def load(self) -> None:
        """Load local session registry from disk. Corrupted files are ignored."""
        with self._lock:
            self._sessions = {}
            if not self.path.exists():
                return
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as exc:
                self.logger.warning("Cannot read Qwen session registry %s: %s", self.path, exc)
                return

            raw_sessions = payload.get("sessions") if isinstance(payload, dict) else None
            if raw_sessions is None and isinstance(payload, dict):
                # Diagnostic-friendly shape: {session_id: metadata}
                raw_sessions = payload
            if not isinstance(raw_sessions, dict):
                return

            for session_id, meta in raw_sessions.items():
                sid = str(session_id or "").strip()
                if not sid or not isinstance(meta, dict):
                    continue
                clean_meta = self._normalize_record(sid, meta)
                if clean_meta:
                    self._sessions[sid] = clean_meta
            self._trim_locked()

    def all(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {key: dict(value) for key, value in self._sessions.items()}

    def get(self, session_id: str | None) -> dict[str, Any] | None:
        sid = str(session_id or "").strip()
        if not sid:
            return None
        with self._lock:
            meta = self._sessions.get(sid)
            return dict(meta) if isinstance(meta, dict) else None

    def register(self, session_id: str, *, title: str = "", source: str = "runtime", metadata: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Create/update a local session record and persist it."""
        sid = str(session_id or "").strip()
        if not sid:
            return None
        now = utc_now_iso()
        base = self.get(sid) or {}
        merged: dict[str, Any] = {
            **base,
            **(metadata if isinstance(metadata, dict) else {}),
            "session_id": sid,
            "title": str(title or base.get("title") or "Новый чат").strip() or "Новый чат",
            "created_at": str(base.get("created_at") or now),
            "updated_at": now,
            "last_used_at": now,
            "source": str(source or base.get("source") or "runtime"),
        }
        clean = self._normalize_record(sid, merged)
        if not clean:
            return None
        with self._lock:
            self._sessions[sid] = clean
            self._trim_locked()
            self._persist_locked()
        return dict(clean)

    def touch(self, session_id: str, *, title: str | None = None, source: str = "message") -> dict[str, Any] | None:
        sid = str(session_id or "").strip()
        if not sid:
            return None
        now = utc_now_iso()
        with self._lock:
            base = self._sessions.get(sid) or {
                "session_id": sid,
                "title": "Восстановленный чат",
                "created_at": now,
                "source": source,
            }
            if title is not None and str(title or "").strip():
                base["title"] = str(title or "").strip()
            base["updated_at"] = now
            base["last_used_at"] = now
            base.setdefault("session_id", sid)
            base.setdefault("title", "Восстановленный чат")
            base.setdefault("created_at", now)
            base.setdefault("source", source)
            clean = self._normalize_record(sid, base)
            if not clean:
                return None
            self._sessions[sid] = clean
            self._trim_locked()
            self._persist_locked()
            return dict(clean)

    def update_title(self, session_id: str, title: str) -> dict[str, Any] | None:
        sid = str(session_id or "").strip()
        clean_title = str(title or "").strip() or "Новый чат"
        if not sid:
            return None
        with self._lock:
            base = self._sessions.get(sid) or {
                "session_id": sid,
                "title": clean_title,
                "created_at": utc_now_iso(),
                "source": "rename",
            }
            base["title"] = clean_title
            base["updated_at"] = utc_now_iso()
            clean = self._normalize_record(sid, base)
            if not clean:
                return None
            self._sessions[sid] = clean
            self._persist_locked()
            return dict(clean)

    def remove(self, session_id: str) -> None:
        sid = str(session_id or "").strip()
        if not sid:
            return
        with self._lock:
            self._sessions.pop(sid, None)
            self._persist_locked()

    def clear(self) -> int:
        with self._lock:
            removed = len(self._sessions)
            self._sessions.clear()
            self._persist_locked()
            return removed

    def stats(self) -> dict[str, Any]:
        """Return secret-safe registry statistics for diagnostics/config payloads."""
        with self._lock:
            timestamps = [
                self._timestamp_sort_value(meta.get("last_used_at") or meta.get("updated_at") or meta.get("created_at"))
                for meta in self._sessions.values()
                if isinstance(meta, dict)
            ]
            timestamps = [item for item in timestamps if item > 0]
            return {
                "enabled": True,
                "path": str(self.path),
                "exists": self.path.exists(),
                "entries": len(self._sessions),
                "max_entries": self.max_entries,
                "oldest_last_used_at": self._timestamp_to_iso(min(timestamps)) if timestamps else None,
                "newest_last_used_at": self._timestamp_to_iso(max(timestamps)) if timestamps else None,
            }

    def prune_older_than_days(self, *, max_age_days: int, dry_run: bool = True) -> dict[str, Any]:
        """Remove local session metadata older than max_age_days.

        This does not delete remote Qwen chats. It only cleans local runtime
        registry entries that are no longer useful for counters/UI/debugging.
        """
        days = max(1, int(max_age_days or 1))
        cutoff_ts = time.time() - days * 86400
        with self._lock:
            stale_ids: list[str] = []
            for sid, meta in self._sessions.items():
                ts = 0.0
                if isinstance(meta, dict):
                    ts = self._timestamp_sort_value(meta.get("last_used_at") or meta.get("updated_at") or meta.get("created_at"))
                if ts and ts < cutoff_ts:
                    stale_ids.append(sid)
            if not dry_run and stale_ids:
                for sid in stale_ids:
                    self._sessions.pop(sid, None)
                self._persist_locked()
            return {
                "enabled": True,
                "dry_run": dry_run,
                "max_age_days": days,
                "cutoff": self._timestamp_to_iso(cutoff_ts),
                "candidates": len(stale_ids),
                "removed": 0 if dry_run else len(stale_ids),
                "removed_ids": stale_ids,
                "entries_before": len(self._sessions) + (0 if dry_run else len(stale_ids)),
                "entries_after": len(self._sessions),
            }

    def _trim_locked(self) -> None:
        if len(self._sessions) <= self.max_entries:
            return

        def sort_key(item: tuple[str, dict[str, Any]]) -> float:
            meta = item[1] if isinstance(item[1], dict) else {}
            for key in ("last_used_at", "updated_at", "created_at"):
                parsed = self._timestamp_sort_value(meta.get(key))
                if parsed:
                    return parsed
            return 0.0

        keep = dict(sorted(self._sessions.items(), key=sort_key)[-self.max_entries :])
        self._sessions.clear()
        self._sessions.update(keep)

    def _persist_locked(self) -> None:
        payload = {
            "version": 1,
            "updated_at": int(time.time() * 1000),
            "sessions": self._sessions,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except Exception as exc:
            self.logger.warning("Cannot persist Qwen session registry %s: %s", self.path, exc)

    @staticmethod
    def _timestamp_sort_value(value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            numeric = float(value)
            return numeric / 1000 if numeric > 10_000_000_000 else numeric
        text = str(value or "").strip()
        if not text:
            return 0.0
        try:
            numeric = float(text)
            return numeric / 1000 if numeric > 10_000_000_000 else numeric
        except Exception:
            pass
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return 0.0

    @staticmethod
    def _timestamp_to_iso(value: int | float | None) -> str | None:
        try:
            numeric = float(value or 0)
        except Exception:
            return None
        if numeric <= 0:
            return None
        if numeric > 10_000_000_000:
            numeric = numeric / 1000
        return datetime.fromtimestamp(numeric, tz=timezone.utc).isoformat()

    @staticmethod
    def _normalize_record(session_id: str, metadata: dict[str, Any]) -> dict[str, Any] | None:
        sid = str(metadata.get("session_id") or session_id or "").strip()
        if not sid:
            return None
        title = str(metadata.get("title") or "Новый чат").strip() or "Новый чат"
        now = utc_now_iso()
        clean: dict[str, Any] = {
            "session_id": sid,
            "title": title,
            "created_at": str(metadata.get("created_at") or now),
            "updated_at": str(metadata.get("updated_at") or now),
            "last_used_at": str(metadata.get("last_used_at") or metadata.get("updated_at") or now),
            "source": str(metadata.get("source") or "runtime"),
        }
        for key in ("provider", "model"):
            value = metadata.get(key)
            if value is not None:
                clean[key] = str(value)
        return clean


def build_qwen_session_registry_store(
    config: dict[str, Any],
    *,
    project_root: str | Path,
    default_path: str = "runtime/qwen_sessions.json",
    logger: Any = logging,
) -> QwenSessionRegistryStore:
    raw_path = str(config.get("session_registry_cache_path") or default_path).strip() or default_path
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(project_root) / path
    max_entries = int(config.get("session_registry_cache_max_entries") or 500)
    store = QwenSessionRegistryStore(path, max_entries=max_entries, logger=logger)
    store.load()
    return store
