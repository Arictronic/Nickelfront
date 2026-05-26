from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from parsers_pkg.translate.cache import TranslationCache
from parsers_pkg.translate.qwen_adapter import QwenTranslationAdapter
from parsers_pkg.translate.translator import QueryTranslator


class TestTranslationSafety(unittest.TestCase):
    def test_qwen_translation_cleanup_accepts_plain_query(self):
        value = 'Translation: "nickel heat-resistant alloys"'
        cleaned = QwenTranslationAdapter._clean_translation_output(value)
        self.assertEqual(cleaned, "nickel heat-resistant alloys")
        self.assertTrue(
            QwenTranslationAdapter._is_usable_translation(
                "никелевые жаропрочные сплавы",
                cleaned,
                target_lang="en",
            )
        )

    def test_qwen_translation_rejects_verbose_or_cyrillic_output(self):
        self.assertFalse(
            QwenTranslationAdapter._is_usable_translation(
                "никелевые сплавы",
                "Here is the translation: nickel alloys",
                target_lang="en",
            )
        )
        self.assertFalse(
            QwenTranslationAdapter._is_usable_translation(
                "никелевые сплавы",
                "никелевые alloys",
                target_lang="en",
            )
        )


    def test_qwen_translation_cleanup_handles_numbered_list(self):
        value = "1. nickel-based superalloys\n2. nickel heat-resistant alloys"
        cleaned = QwenTranslationAdapter._clean_translation_output(value)
        self.assertEqual(cleaned, "nickel-based superalloys")
        self.assertTrue(
            QwenTranslationAdapter._is_usable_translation(
                "никелевые суперсплавы",
                cleaned,
                target_lang="en",
            )
        )

    def test_qwen_translation_rejects_explanatory_query(self):
        self.assertFalse(
            QwenTranslationAdapter._is_usable_translation(
                "никелевые сплавы",
                "nickel alloys can be translated as nickel-based alloys",
                target_lang="en",
            )
        )

    def test_translator_purges_poisoned_cache(self):
        with tempfile.TemporaryDirectory() as td:
            cache_path = Path(td) / "translations.json"
            cache = TranslationCache(path=cache_path, enabled=True)
            cache.set(
                original_text="никелевые сплавы",
                translated_text="Here is the translation: nickel alloys",
                source_lang="auto",
                target_lang="en",
                engine="qwen-queue",
            )

            translator = QueryTranslator(enabled=True, default_target_lang="en")
            translator.cache = cache
            translator.qwen_enabled = False
            translator._google_translator_cls = None

            result = translator.translate("никелевые сплавы", target_lang="en", source_lang="auto")
            self.assertFalse(result.translated)
            self.assertEqual(result.reason, "translation_unavailable")
            self.assertIsNone(cache.get("никелевые сплавы", source_lang="auto", target_lang="en"))

    def test_invalid_qwen_timeout_env_falls_back(self):
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"PARSER_TRANSLATE_QWEN_TIMEOUT": "bad", "QWEN_QUEUE_TIMEOUT": "12"}, clear=False):
            adapter = QwenTranslationAdapter()

        self.assertEqual(adapter.timeout, 12.0)


if __name__ == "__main__":
    unittest.main()

class TestTranslationCacheConcurrency(unittest.TestCase):
    def test_translation_cache_save_merges_sequential_writers(self):
        with tempfile.TemporaryDirectory() as td:
            cache_path = Path(td) / "translations.json"
            first = TranslationCache(path=cache_path, enabled=True)
            second = TranslationCache(path=cache_path, enabled=True)

            first.set(
                original_text="никелевые сплавы",
                translated_text="nickel alloys",
                source_lang="auto",
                target_lang="en",
                engine="qwen-queue",
            )
            second.set(
                original_text="жаропрочные сплавы",
                translated_text="heat-resistant alloys",
                source_lang="auto",
                target_lang="en",
                engine="qwen-queue",
            )

            merged = TranslationCache(path=cache_path, enabled=True)
            self.assertIsNotNone(merged.get("никелевые сплавы", source_lang="auto", target_lang="en"))
            self.assertIsNotNone(merged.get("жаропрочные сплавы", source_lang="auto", target_lang="en"))

    def test_translation_cache_hit_counters_merge(self):
        with tempfile.TemporaryDirectory() as td:
            cache_path = Path(td) / "translations.json"
            seed = TranslationCache(path=cache_path, enabled=True)
            seed.set(
                original_text="никелевые сплавы",
                translated_text="nickel alloys",
                source_lang="auto",
                target_lang="en",
                engine="qwen-queue",
            )

            first = TranslationCache(path=cache_path, enabled=True)
            second = TranslationCache(path=cache_path, enabled=True)
            first.get("никелевые сплавы", source_lang="auto", target_lang="en")
            second.get("никелевые сплавы", source_lang="auto", target_lang="en")

            merged = TranslationCache(path=cache_path, enabled=True)
            entry = merged.get("никелевые сплавы", source_lang="auto", target_lang="en")
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertGreaterEqual(entry.hits, 2)

class TestTranslationCacheRobustness(unittest.TestCase):
    def test_translation_cache_save_failure_is_non_fatal(self):
        with tempfile.TemporaryDirectory() as td:
            cache = TranslationCache(path=Path(td) / "translations.json", enabled=True)

            def fail_lock(*args, **kwargs):
                raise TimeoutError("locked")

            cache._acquire_save_lock = fail_lock
            entry = cache.set(
                original_text="никелевые сплавы",
                translated_text="nickel alloys",
                source_lang="auto",
                target_lang="en",
                engine="qwen-queue",
            )
            self.assertEqual(entry.translated_text, "nickel alloys")
