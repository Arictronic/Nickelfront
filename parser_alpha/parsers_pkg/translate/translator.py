"""Query translation module used by routing/adaptation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from loguru import logger

from .cache import TranslationCache
from .qwen_adapter import QwenTranslationAdapter


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
    """Best-effort query translator with persistent cache and queued Qwen fallback."""

    def __init__(self, *, enabled: bool = True, default_target_lang: str = "en"):
        self.enabled = enabled
        self.default_target_lang = default_target_lang
        self.cache_enabled = os.getenv("PARSER_TRANSLATION_CACHE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
        self.qwen_enabled = os.getenv("PARSER_TRANSLATE_QWEN_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
        self._engine_name = "none"
        self._google_translator_cls = None
        self.cache = TranslationCache(enabled=self.cache_enabled)
        self.qwen = QwenTranslationAdapter()
        self._init_engine()

    def _init_engine(self) -> None:
        if not self.enabled:
            self._engine_name = "disabled"
            return

        try:
            from deep_translator import GoogleTranslator

            self._google_translator_cls = GoogleTranslator
            self._engine_name = "deep-translator/google"
        except Exception as exc:
            self._engine_name = "unavailable"
            logger.debug("Translation backend unavailable: {}", exc)

    @staticmethod
    def _looks_ascii(text: str) -> bool:
        return all(ord(ch) < 128 for ch in text)

    @staticmethod
    def _sanitize(text: str) -> str:
        return " ".join(text.split()).strip()

    @lru_cache(maxsize=512)
    def _translate_cached_local(self, text: str, source_lang: str, target_lang: str) -> str:
        if self._google_translator_cls is None:
            return text
        translator = self._google_translator_cls(source=source_lang, target=target_lang)
        translated = translator.translate(text)
        if not isinstance(translated, str):
            return text
        return self._sanitize(translated) or text

    def _result(self, raw: str, translated: str, source_lang: str, target: str, engine: str, reason: str) -> QueryTranslationResult:
        translated = self._sanitize(translated) or raw
        return QueryTranslationResult(
            original_text=raw,
            translated_text=translated,
            source_lang=source_lang,
            target_lang=target,
            used_engine=engine,
            translated=translated != raw,
            reason=reason,
        )

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
            return self._result(text, text, source_lang, target, self._engine_name, "empty_query")
        if not self.enabled:
            return self._result(raw, raw, source_lang, target, self._engine_name, "translation_disabled")
        if self._looks_ascii(raw) and target.lower() == "en":
            return self._result(raw, raw, source_lang, target, self._engine_name, "already_ascii")

        cached = self.cache.get(raw, source_lang=source_lang, target_lang=target)
        if cached and cached.translated_text:
            cached_text = QwenTranslationAdapter._clean_translation_output(cached.translated_text)
            if QwenTranslationAdapter._is_usable_translation(raw, cached_text, target_lang=target):
                return self._result(raw, cached_text, source_lang, target, f"cache:{cached.engine}", "cache_hit")
            logger.warning("Cached query translation rejected and purged for '{}': engine={}", raw, cached.engine)
            self.cache.delete(raw, source_lang=source_lang, target_lang=target)

        if self._google_translator_cls is not None:
            try:
                translated = self._translate_cached_local(raw, source_lang, target)
                translated = QwenTranslationAdapter._clean_translation_output(translated)
                if QwenTranslationAdapter._is_usable_translation(raw, translated, target_lang=target):
                    self.cache.set(
                        original_text=raw,
                        translated_text=translated,
                        source_lang=source_lang,
                        target_lang=target,
                        engine=self._engine_name,
                    )
                    return self._result(raw, translated, source_lang, target, self._engine_name, "translated")
            except Exception as exc:
                logger.warning("Local query translation failed for '{}': {}", raw, exc)

        if self.qwen_enabled:
            translated = self.qwen.translate(raw, target_lang=target, source_lang=source_lang)
            if QwenTranslationAdapter._is_usable_translation(raw, translated or "", target_lang=target):
                assert translated is not None
                self.cache.set(
                    original_text=raw,
                    translated_text=translated,
                    source_lang=source_lang,
                    target_lang=target,
                    engine="qwen-queue",
                )
                return self._result(raw, translated, source_lang, target, "qwen-queue", "translated")

        return self._result(raw, raw, source_lang, target, self._engine_name, "translation_unavailable")


def _env_enabled() -> bool:
    value = os.getenv("PARSER_TRANSLATE_ENABLED", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


_SHARED_TRANSLATOR: QueryTranslator | None = None


def get_shared_query_translator() -> QueryTranslator:
    global _SHARED_TRANSLATOR
    if _SHARED_TRANSLATOR is None:
        _SHARED_TRANSLATOR = QueryTranslator(enabled=_env_enabled(), default_target_lang="en")
    return _SHARED_TRANSLATOR
