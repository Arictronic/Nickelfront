"""Compatibility client for Qwen-powered parser translations.

Legacy code used this module to call qwen_service HTTP directly from a separate
`qwen_translation` worker. The current architecture uses the shared `qwen` Celery
gateway. Keep the public class name for old imports/tests, but route requests
through QwenServiceClient so all background Qwen work shares the same queue and
rate limits.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from loguru import logger

from app.services.qwen_client import QwenServiceClient


@dataclass(frozen=True)
class QwenQueuedTranslation:
    translated_text: str
    engine: str
    raw_response: str


class QwenTranslationHTTPClient:
    """Backward-compatible translation client using the shared Qwen gateway."""

    def __init__(self, *, timeout_seconds: float | None = None, **_: object):
        self.timeout_seconds = float(timeout_seconds or 120.0)
        self.client = QwenServiceClient(timeout=self.timeout_seconds)

    @property
    def available(self) -> bool:
        return True

    def translate(
        self,
        text: str,
        *,
        source_lang: str = "auto",
        target_lang: str = "en",
    ) -> QwenQueuedTranslation | None:
        raw = " ".join((text or "").split()).strip()
        if not raw:
            return None

        prompt = _build_translation_prompt(raw, source_lang=source_lang, target_lang=target_lang)
        result = self.client.send_message(
            message=prompt,
            session_id=None,
            thinking_enabled=False,
            search_enabled=False,
            file_ids=[],
            auto_continue=False,
            timeout=self.timeout_seconds,
        )
        response_text = str(result.get("response") or "").strip()
        error_text = str(result.get("error") or "").strip()
        if not response_text:
            logger.warning("Qwen translation returned empty response: {}", error_text or "none")
            return None

        translated = _extract_translation(response_text)
        if not _is_usable_translation(raw, translated, target_lang=target_lang):
            logger.warning("Qwen translation returned unusable text: {}", response_text[:200])
            return None

        return QwenQueuedTranslation(
            translated_text=translated,
            engine="qwen-shared-queue",
            raw_response=response_text,
        )


def _lang_label(lang: str) -> str:
    normalized = (lang or "auto").lower()
    return {
        "auto": "auto-detected source language",
        "ru": "Russian",
        "en": "English",
    }.get(normalized, normalized)


def _build_translation_prompt(text: str, *, source_lang: str, target_lang: str) -> str:
    return (
        "You are a translation adapter for a scientific literature and patent parser.\n"
        "Translate the query exactly and concisely. Preserve chemical symbols, alloy names, abbreviations, "
        "phase names, temperatures, formulas, DOI fragments, and patent identifiers.\n"
        "Return only valid JSON with this exact schema: {\"translation\": \"...\"}.\n"
        "No explanations, no markdown, no alternatives.\n\n"
        f"Source language: {_lang_label(source_lang)}\n"
        f"Target language: {_lang_label(target_lang)}\n"
        f"Text: {json.dumps(text, ensure_ascii=False)}"
    )


def _extract_translation(response_text: str) -> str:
    cleaned = (response_text or "").strip()
    if not cleaned:
        return ""

    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()

    try:
        payload = json.loads(cleaned)
        if isinstance(payload, dict):
            value = payload.get("translation") or payload.get("translated_text") or payload.get("text")
            if isinstance(value, str):
                return _strip_wrapping_quotes(value)
    except Exception:
        pass

    match = re.search(r'"translation"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', cleaned)
    if match:
        try:
            return _strip_wrapping_quotes(json.loads(f'"{match.group(1)}"'))
        except Exception:
            return _strip_wrapping_quotes(match.group(1))
    return _strip_wrapping_quotes(cleaned)


def _strip_wrapping_quotes(text: str) -> str:
    value = " ".join(str(text or "").split()).strip()
    value = re.sub(r"^(translation|translated_text|перевод)\s*:\s*", "", value, flags=re.IGNORECASE).strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1].strip()
    return value


def _is_usable_translation(original: str, translated: str, *, target_lang: str) -> bool:
    if not translated or translated == original:
        return False
    if len(translated) > max(240, len(original) * 6):
        return False
    if target_lang.lower() == "en":
        ascii_chars = sum(1 for ch in translated if ord(ch) < 128)
        if ascii_chars / max(1, len(translated)) < 0.65:
            return False
    return True
