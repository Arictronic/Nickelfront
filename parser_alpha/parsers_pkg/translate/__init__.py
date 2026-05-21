"""Translation helpers for source query adaptation."""

from .cache import TranslationCache, TranslationCacheEntry, get_shared_translation_cache
from .qwen_adapter import QwenTranslationAdapter, get_shared_qwen_translation_adapter
from .translator import QueryTranslationResult, QueryTranslator, get_shared_query_translator

# Backward-compatible aliases for older imports/tests.
CachedTranslation = TranslationCacheEntry
QwenTranslationResponse = str

__all__ = [
    "CachedTranslation",
    "TranslationCacheEntry",
    "QwenTranslationAdapter",
    "QwenTranslationResponse",
    "QueryTranslationResult",
    "QueryTranslator",
    "TranslationCache",
    "get_shared_qwen_translation_adapter",
    "get_shared_query_translator",
    "get_shared_translation_cache",
]
