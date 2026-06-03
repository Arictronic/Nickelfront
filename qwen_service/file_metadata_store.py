"""Persistent metadata cache for Qwen uploaded files.

Qwen file sends need the full provider file_info, not only file_id.  The
provider client keeps that map in memory, but a qwen_service restart used to
break the two-step flow: /files/upload -> later /messages with file_ids.
This store persists the provider metadata under project runtime/ so it is not
part of normal source patches or LLM archives.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any


class UploadedFileMetadataStore:
    """Small JSON-backed cache for provider file_info payloads."""

    def __init__(self, path: str | Path, *, max_entries: int = 500, logger: Any = logging) -> None:
        self.path = Path(path)
        self.max_entries = max(1, int(max_entries or 500))
        self.logger = logger
        self._lock = RLock()
        self._files: dict[str, dict[str, Any]] = {}

    def load(self) -> None:
        """Load cache from disk. Invalid/cache-corrupted files are ignored."""
        with self._lock:
            self._files = {}
            if not self.path.exists():
                return
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as exc:
                self.logger.warning("Cannot read Qwen file metadata cache %s: %s", self.path, exc)
                return

            raw_files = payload.get("files") if isinstance(payload, dict) else None
            if raw_files is None and isinstance(payload, dict):

                raw_files = payload
            if not isinstance(raw_files, dict):
                return

            for file_id, info in raw_files.items():
                if not isinstance(info, dict):
                    continue
                fid = self._file_id(info) or str(file_id or "").strip()
                if not fid:
                    continue
                clean_info = self._json_safe(info)
                if isinstance(clean_info, dict):
                    clean_info.setdefault("file_id", fid)
                    clean_info.setdefault("id", fid)
                    self._files[fid] = clean_info
            self._trim_locked()

    def all(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {key: dict(value) for key, value in self._files.items()}

    def get(self, file_id: str | None) -> dict[str, Any] | None:
        fid = str(file_id or "").strip()
        if not fid:
            return None
        with self._lock:
            info = self._files.get(fid)
            return dict(info) if isinstance(info, dict) else None

    def register(self, file_info: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(file_info, dict):
            return None
        fid = self._file_id(file_info)
        if not fid:
            return None
        clean_info = self._json_safe(file_info)
        if not isinstance(clean_info, dict):
            return None
        now_ms = int(time.time() * 1000)
        clean_info.setdefault("file_id", fid)
        clean_info.setdefault("id", fid)
        clean_info["cached_at"] = now_ms
        with self._lock:
            self._files[fid] = clean_info
            self._trim_locked()
            self._persist_locked()
        return dict(clean_info)

    def register_many(self, file_infos: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> list[dict[str, Any]]:
        registered: list[dict[str, Any]] = []
        for info in file_infos or []:
            item = self.register(info)
            if item:
                registered.append(item)
        return registered

    def hydrate_qwen_api(self, qwen_api: Any) -> int:
        """Merge cached metadata into a QwenAPI-like object's _uploaded_files map."""
        if qwen_api is None:
            return 0
        uploaded = getattr(qwen_api, "_uploaded_files", None)
        if not isinstance(uploaded, dict):
            return 0
        with self._lock:
            uploaded.update({key: dict(value) for key, value in self._files.items()})
            return len(self._files)

    def clear(self) -> int:
        """Clear all cached uploaded-file metadata and persist the empty store."""
        with self._lock:
            removed = len(self._files)
            self._files.clear()
            self._persist_locked()
            return removed

    def stats(self) -> dict[str, Any]:
        """Return secret-safe cache statistics for diagnostics/config payloads."""
        with self._lock:
            timestamps = [self._timestamp_sort_value(info.get("cached_at") or info.get("created_at")) for info in self._files.values() if isinstance(info, dict)]
            timestamps = [item for item in timestamps if item > 0]
            return {
                "enabled": True,
                "path": str(self.path),
                "exists": self.path.exists(),
                "entries": len(self._files),
                "max_entries": self.max_entries,
                "oldest_cached_at": self._timestamp_to_iso(min(timestamps)) if timestamps else None,
                "newest_cached_at": self._timestamp_to_iso(max(timestamps)) if timestamps else None,
            }

    def prune_older_than_days(self, *, max_age_days: int, dry_run: bool = True) -> dict[str, Any]:
        """Remove cached file metadata older than max_age_days.

        Qwen uploaded-file references are provider-side runtime objects. Keeping
        very old file_info records makes two-step flows harder to debug because
        callers may reuse stale ids.  This cleanup only touches the local JSON
        cache; it does not delete files from Qwen.
        """
        days = max(1, int(max_age_days or 1))
        cutoff_ms = int((time.time() - days * 86400) * 1000)
        with self._lock:
            stale_ids: list[str] = []
            for file_id, info in self._files.items():
                ts = self._timestamp_sort_value(info.get("cached_at") if isinstance(info, dict) else None)
                if not ts and isinstance(info, dict):
                    ts = self._timestamp_sort_value(info.get("created_at") or info.get("update_at"))
                if ts and ts < cutoff_ms:
                    stale_ids.append(file_id)
            if not dry_run and stale_ids:
                for file_id in stale_ids:
                    self._files.pop(file_id, None)
                self._persist_locked()
            return {
                "enabled": True,
                "dry_run": dry_run,
                "max_age_days": days,
                "cutoff": self._timestamp_to_iso(cutoff_ms),
                "candidates": len(stale_ids),
                "removed": 0 if dry_run else len(stale_ids),
                "removed_ids": stale_ids,
                "entries_before": len(self._files) + (0 if dry_run else len(stale_ids)),
                "entries_after": len(self._files),
            }

    def _trim_locked(self) -> None:
        if len(self._files) <= self.max_entries:
            return

        def sort_key(item: tuple[str, dict[str, Any]]) -> int:
            info = item[1] if isinstance(item[1], dict) else {}
            for key in ("cached_at", "created_at", "update_at"):
                try:
                    return int(info.get(key) or 0)
                except Exception:
                    continue
            return 0

        keep = dict(sorted(self._files.items(), key=sort_key)[-self.max_entries :])
        self._files.clear()
        self._files.update(keep)

    def _persist_locked(self) -> None:
        payload = {
            "version": 1,
            "updated_at": int(time.time() * 1000),
            "files": self._files,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except Exception as exc:
            self.logger.warning("Cannot persist Qwen file metadata cache %s: %s", self.path, exc)

    @staticmethod
    def _timestamp_sort_value(value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, (int, float)):

            numeric = float(value)
            return int(numeric * 1000) if 0 < numeric < 10_000_000_000 else int(numeric)
        text = str(value or "").strip()
        if not text:
            return 0
        try:
            return int(float(text))
        except Exception:
            pass
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except Exception:
            return 0

    @staticmethod
    def _timestamp_to_iso(value_ms: int | float | None) -> str | None:
        try:
            numeric = float(value_ms or 0)
        except Exception:
            return None
        if numeric <= 0:
            return None
        if numeric < 10_000_000_000:
            numeric *= 1000
        return datetime.fromtimestamp(numeric / 1000, tz=timezone.utc).isoformat()

    @staticmethod
    def _file_id(file_info: dict[str, Any]) -> str:
        return str(file_info.get("file_id") or file_info.get("id") or "").strip()

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(k): cls._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._json_safe(v) for v in value]
        return str(value)


def build_uploaded_file_metadata_store(
    config: dict[str, Any],
    *,
    project_root: str | Path,
    default_path: str = "logs/runtime/qwen/qwen_uploaded_files.json",
    logger: Any = logging,
) -> UploadedFileMetadataStore:
    raw_path = str(config.get("file_metadata_cache_path") or default_path).strip() or default_path
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(project_root) / path
    max_entries = int(config.get("file_metadata_cache_max_entries") or 500)
    store = UploadedFileMetadataStore(path, max_entries=max_entries, logger=logger)
    store.load()
    return store
