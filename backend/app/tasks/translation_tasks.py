"""Compatibility Celery task for parser query translations.

The old implementation expected a dedicated `qwen_translation` queue and called
qwen_service directly. The current Nickelfront architecture uses one shared Qwen
gateway queue (`qwen`) for parser translations, content enrichment, RAG and alloy
analysis. This task remains only for backward compatibility with old task names.
"""

from __future__ import annotations

from typing import Any

from app.services.qwen_translation_client import QwenTranslationHTTPClient
from app.tasks.celery_app import celery_app


@celery_app.task(
    name="app.tasks.translation_tasks.translate_query_with_qwen",
    bind=True,
    autoretry_for=(),
)
def translate_query_with_qwen(
    self,
    text: str,
    source_lang: str = "auto",
    target_lang: str = "en",
) -> dict[str, Any]:
    """Translate a short parser query through the shared Qwen gateway."""

    raw = " ".join((text or "").split()).strip()
    if not raw:
        return {
            "ok": False,
            "translated_text": "",
            "engine": "qwen-shared-queue",
            "error": "empty_text",
        }

    client = QwenTranslationHTTPClient()
    result = client.translate(raw, source_lang=source_lang, target_lang=target_lang)
    if result is None:
        return {
            "ok": False,
            "translated_text": "",
            "engine": "qwen-shared-queue",
            "error": "qwen_unavailable_or_unusable_response",
        }

    return {
        "ok": True,
        "translated_text": result.translated_text,
        "engine": result.engine,
        "error": None,
    }
