"""Persistent JSON cache for parser query translations."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


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

    def _load(self) -> None:
        if not self.path.exists():
            self._data = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._data = raw if isinstance(raw, dict) else {}
        except Exception:
            self._data = {}

    def _save(self) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(self.path.parent)) as tmp:
            tmp.write(payload)
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.path)

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

    def set(
        self,
        *,
        original_text: str,
        translated_text: str,
        source_lang: str = "auto",
        target_lang: str = "en",
        engine: str,
    ) -> TranslationCacheEntry:
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
