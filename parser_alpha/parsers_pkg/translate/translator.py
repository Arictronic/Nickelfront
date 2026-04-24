"""Query translation module used by routing/adaptation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from loguru import logger


@dataclass(frozen=True)
class QueryTranslationResult:
    original_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    used_engine: str
    translated: bool
    reason: str


class QueryTranslator:
    """Best-effort query translator with graceful fallback."""

    def __init__(self, *, enabled: bool = True, default_target_lang: str = "en"):
        self.enabled = enabled
        self.default_target_lang = default_target_lang
        self._engine_name = "none"
        self._google_translator_cls = None
        self._init_engine()

    def _init_engine(self) -> None:
        if not self.enabled:
            self._engine_name = "disabled"
            return

        try:
            from deep_translator import GoogleTranslator  # type: ignore

            self._google_translator_cls = GoogleTranslator
            self._engine_name = "deep-translator/google"
        except Exception as exc:
            self._engine_name = "unavailable"
            logger.warning("Translation backend unavailable: {}", exc)

    @staticmethod
    def _looks_ascii(text: str) -> bool:
        return all(ord(ch) < 128 for ch in text)

    @staticmethod
    def _sanitize(text: str) -> str:
        return " ".join(text.split()).strip()

    @lru_cache(maxsize=512)
    def _translate_cached(self, text: str, source_lang: str, target_lang: str) -> str:
        if self._google_translator_cls is None:
            return text
        translator = self._google_translator_cls(source=source_lang, target=target_lang)
        translated = translator.translate(text)
        if not isinstance(translated, str):
            return text
        return self._sanitize(translated) or text

    def translate(
        self,
        text: str,
        *,
        target_lang: str | None = None,
        source_lang: str = "auto",
    ) -> QueryTranslationResult:
        raw = self._sanitize(text)
        target = (target_lang or self.default_target_lang).strip() or self.default_target_lang

        if not raw:
            return QueryTranslationResult(
                original_text=text,
                translated_text=text,
                source_lang=source_lang,
                target_lang=target,
                used_engine=self._engine_name,
                translated=False,
                reason="empty_query",
            )

        if not self.enabled:
            return QueryTranslationResult(
                original_text=raw,
                translated_text=raw,
                source_lang=source_lang,
                target_lang=target,
                used_engine=self._engine_name,
                translated=False,
                reason="translation_disabled",
            )

        if self._looks_ascii(raw) and target.lower() == "en":
            return QueryTranslationResult(
                original_text=raw,
                translated_text=raw,
                source_lang=source_lang,
                target_lang=target,
                used_engine=self._engine_name,
                translated=False,
                reason="already_ascii",
            )

        if self._google_translator_cls is None:
            return QueryTranslationResult(
                original_text=raw,
                translated_text=raw,
                source_lang=source_lang,
                target_lang=target,
                used_engine=self._engine_name,
                translated=False,
                reason="engine_unavailable",
            )

        try:
            translated = self._translate_cached(raw, source_lang, target)
            changed = translated != raw
            return QueryTranslationResult(
                original_text=raw,
                translated_text=translated,
                source_lang=source_lang,
                target_lang=target,
                used_engine=self._engine_name,
                translated=changed,
                reason="translated" if changed else "identity_after_translation",
            )
        except Exception as exc:
            logger.warning("Query translation failed for '{}': {}", raw, exc)
            return QueryTranslationResult(
                original_text=raw,
                translated_text=raw,
                source_lang=source_lang,
                target_lang=target,
                used_engine=self._engine_name,
                translated=False,
                reason="translation_error",
            )


def _env_enabled() -> bool:
    value = os.getenv("PARSER_TRANSLATE_ENABLED", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


_SHARED_TRANSLATOR: QueryTranslator | None = None


def get_shared_query_translator() -> QueryTranslator:
    global _SHARED_TRANSLATOR
    if _SHARED_TRANSLATOR is None:
        _SHARED_TRANSLATOR = QueryTranslator(enabled=_env_enabled(), default_target_lang="en")
    return _SHARED_TRANSLATOR

