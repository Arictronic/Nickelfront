"""Persistent JSON cache for parser query translations."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


logger = logging.getLogger(__name__)


@dataclass
class TranslationCacheEntry:
    original_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    engine: str
    created_at: str
    updated_at: str
    hits: int = 0


class TranslationCache:
    def __init__(self, path: str | Path | None = None, enabled: bool = True):
        default_path = Path(__file__).resolve().parents[2] / "cache" / "translations" / "query_translations.json"
        self.path = Path(path or os.getenv("PARSER_TRANSLATION_CACHE_PATH") or default_path)
        self.enabled = enabled
        self._data: dict[str, dict] = {}
        self._base_data: dict[str, dict] = {}
        if self.enabled:
            self._load()

    @staticmethod
    def _key(text: str, source_lang: str, target_lang: str) -> str:
        return json.dumps(
            {
                "text": " ".join(text.split()).strip().lower(),
                "source_lang": (source_lang or "auto").lower(),
                "target_lang": (target_lang or "en").lower(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _read_disk_data(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _load(self) -> None:
        self._data = self._read_disk_data()
        self._base_data = deepcopy(self._data)

    def _acquire_save_lock(self, *, timeout: float = 10.0, stale_after: float = 60.0) -> Path:
        """Acquire a small cross-process lock for translation cache writes.

        ``Path.replace`` prevents half-written JSON, but without a lock two
        parser subprocesses can still read the same old cache and overwrite each
        other's translations/hit counters. Directory locks are cross-platform and
        require no dependency on Windows.
        """
        lock_path = self.path.with_name(f"{self.path.name}.lock")
        deadline = time.monotonic() + max(0.5, timeout)

        while True:
            try:
                lock_path.mkdir(parents=True, exist_ok=False)
                return lock_path
            except FileExistsError:
                try:
                    age = time.time() - lock_path.stat().st_mtime
                    if age > stale_after:
                        lock_path.rmdir()
                        continue
                except FileNotFoundError:
                    continue
                except OSError:
                    pass

                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for translation cache lock: {lock_path}")
                time.sleep(0.05)

    @staticmethod
    def _release_save_lock(lock_path: Path | None) -> None:
        if lock_path is None:
            return
        try:
            lock_path.rmdir()
        except FileNotFoundError:
            return

    @staticmethod
    def _as_int(value: object, default: int = 0) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return default

    def _merge_with_current_disk_data(self) -> dict[str, dict]:
        """Merge in-process cache changes with the latest on-disk cache.

        This preserves translations created by other parser workers and adds hit
        counter deltas instead of overwriting them. Explicit deletes are also
        propagated, which is needed when a poisoned translation is purged.
        """
        disk_data = self._read_disk_data()
        merged: dict[str, dict] = deepcopy(disk_data)

        base_keys = set(self._base_data.keys())
        current_keys = set(self._data.keys())


        for key in base_keys - current_keys:
            merged.pop(key, None)

        for key, current_entry in self._data.items():
            if not isinstance(current_entry, dict):
                continue

            base_entry = self._base_data.get(key)
            disk_entry = merged.get(key)
            current_hits = self._as_int(current_entry.get("hits"))
            base_hits = self._as_int(base_entry.get("hits")) if isinstance(base_entry, dict) else 0
            disk_hits = self._as_int(disk_entry.get("hits")) if isinstance(disk_entry, dict) else 0
            hit_delta = max(0, current_hits - base_hits)

            if isinstance(disk_entry, dict):
                next_entry = dict(disk_entry)


                if current_entry != base_entry:
                    for field in (
                        "original_text",
                        "translated_text",
                        "source_lang",
                        "target_lang",
                        "engine",
                        "updated_at",
                    ):
                        if field in current_entry:
                            next_entry[field] = current_entry[field]
                next_entry["created_at"] = disk_entry.get("created_at") or current_entry.get("created_at") or self._now()
                next_entry["hits"] = disk_hits + hit_delta
                merged[key] = next_entry
            else:
                next_entry = dict(current_entry)
                next_entry["hits"] = current_hits
                merged[key] = next_entry

        return merged

    def _save(self) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path: Path | None = None
        tmp_path: Path | None = None
        try:
            lock_path = self._acquire_save_lock()
            merged_data = self._merge_with_current_disk_data()
            payload = json.dumps(merged_data, ensure_ascii=False, indent=2, sort_keys=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(self.path.parent)) as tmp:
                tmp.write(payload)
                tmp_path = Path(tmp.name)
            tmp_path.replace(self.path)
            self._data = merged_data
            self._base_data = deepcopy(merged_data)
        except Exception as exc:




            logger.warning("Failed to save translation cache to %s: %s", self.path, exc)
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
        finally:
            self._release_save_lock(lock_path)

    def get(self, text: str, source_lang: str = "auto", target_lang: str = "en") -> TranslationCacheEntry | None:
        if not self.enabled:
            return None
        self._load()
        key = self._key(text, source_lang, target_lang)
        value = self._data.get(key)
        if not isinstance(value, dict):
            return None
        value["hits"] = int(value.get("hits", 0)) + 1
        value["updated_at"] = self._now()
        self._data[key] = value
        self._save()
        try:
            return TranslationCacheEntry(**value)
        except TypeError:
            return None

    def delete(self, text: str, source_lang: str = "auto", target_lang: str = "en") -> None:
        """Remove a cached translation entry, used to purge previously poisoned cache values."""
        if not self.enabled:
            return
        self._load()
        key = self._key(text, source_lang, target_lang)
        if key in self._data:
            self._data.pop(key, None)
            self._save()

    def set(
        self,
        *,
        original_text: str,
        translated_text: str,
        source_lang: str = "auto",
        target_lang: str = "en",
        engine: str,
    ) -> TranslationCacheEntry:
        if self.enabled:
            self._load()
        now = self._now()
        key = self._key(original_text, source_lang, target_lang)
        existing = self._data.get(key) if self.enabled else None
        entry = TranslationCacheEntry(
            original_text=" ".join(original_text.split()).strip(),
            translated_text=" ".join(translated_text.split()).strip(),
            source_lang=source_lang,
            target_lang=target_lang,
            engine=engine,
            created_at=str(existing.get("created_at")) if isinstance(existing, dict) and existing.get("created_at") else now,
            updated_at=now,
            hits=int(existing.get("hits", 0)) if isinstance(existing, dict) else 0,
        )
        if self.enabled:
            self._data[key] = asdict(entry)
            self._save()
        return entry


_SHARED_TRANSLATION_CACHE: TranslationCache | None = None


def get_shared_translation_cache() -> TranslationCache:
    global _SHARED_TRANSLATION_CACHE
    if _SHARED_TRANSLATION_CACHE is None:
        _SHARED_TRANSLATION_CACHE = TranslationCache()
    return _SHARED_TRANSLATION_CACHE
