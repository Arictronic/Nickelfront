"""Qwen translation adapter for parser_alpha.

The adapter does not call qwen_service directly. It sends a Celery task to the
shared Qwen queue, so parser workers, alloy analysis, RAG, and content tasks all
share the same limited Qwen slot pool.
"""

from __future__ import annotations

import importlib.util
import os
import re
from typing import Any

from loguru import logger


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning("Invalid float env {}='{}'; using default {}", name, raw, default)
        return default


class QwenTranslationAdapter:
    def __init__(self) -> None:
        self.enabled = os.getenv("PARSER_TRANSLATE_QWEN_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
        self._celery_available = importlib.util.find_spec("celery") is not None




        configured_queue = (os.getenv("PARSER_TRANSLATE_QWEN_QUEUE") or os.getenv("QWEN_QUEUE_NAME") or "qwen").strip()
        allow_legacy_queue = os.getenv("PARSER_TRANSLATE_QWEN_ALLOW_LEGACY_QUEUE", "0").strip().lower() in {"1", "true", "yes", "on"}
        if configured_queue == "qwen_translation" and not allow_legacy_queue:
            logger.warning(
                "Ignoring legacy PARSER_TRANSLATE_QWEN_QUEUE=qwen_translation; using shared queue 'qwen'. "
                "Use run_qwen_worker.bat, not the removed translation worker."
            )
            configured_queue = os.getenv("QWEN_QUEUE_NAME", "qwen").strip() or "qwen"
            if configured_queue == "qwen_translation":
                configured_queue = "qwen"
        self.queue = configured_queue
        default_timeout = _env_float("QWEN_QUEUE_TIMEOUT", 1000.0)
        self.timeout = max(5.0, _env_float("PARSER_TRANSLATE_QWEN_TIMEOUT", default_timeout))
        self.broker = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://localhost:6380/0"))
        self.backend = os.getenv("CELERY_RESULT_BACKEND", self.broker)
        self._celery = None

    @property
    def celery(self):
        if self._celery is None:
            from celery import Celery

            self._celery = Celery(
                "parser_qwen_translation_client",
                broker=self.broker,
                backend=self.backend,
            )
        return self._celery

    @staticmethod
    def _build_prompt(text: str, target_lang: str) -> str:
        return (
            "Ты переводчик поисковых запросов для научных статей и патентов по материаловедению.\n"
            f"Переведи запрос на язык '{target_lang}'.\n"
            "Верни только одну строку перевода, без пояснений, кавычек, markdown, списков и вариантов.\n"
            "Сохрани технические термины: nickel alloys, superalloys, heat resistant alloys, corrosion, patents.\n"
            f"Запрос: {text}"
        )

    @staticmethod
    def _clean_translation_output(value: str) -> str:
        """Normalize a model translation answer to a one-line query candidate."""
        raw = str(value or "").replace("\r", "\n").strip()


        for line in raw.split("\n"):
            candidate = line.strip()
            if candidate:
                raw = candidate
                break
        cleaned = " ".join(raw.split()).strip()
        cleaned = cleaned.strip("`*_•- ").strip().strip('"').strip("'").strip()
        cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", cleaned).strip()
        cleaned = re.sub(
            r"^(translation|translated_text|translated query|query translation|перевод|вариант\s*\d*)\s*[:：-]\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        cleaned = cleaned.strip('"').strip("'").strip()
        return cleaned

    @staticmethod
    def _is_usable_translation(original: str, translated: str, *, target_lang: str) -> bool:
        """Prevent cache poisoning by verbose/non-English Qwen answers."""
        if not translated or translated == original:
            return False
        if "```" in translated or "\n" in translated:
            return False
        if len(translated) > max(180, len(original) * 6):
            return False

        lower = translated.lower()
        bad_prefixes = (
            "here is",
            "sure",
            "i would translate",
            "the translation",
            "translation:",
            "translated query:",
            "query translation:",
            "перевод",
            "вариант",
        )
        if lower.startswith(bad_prefixes):
            return False
        if re.match(r"^\s*(?:[-*•]|\d+[.)])\s+", translated):
            return False

        if any(marker in lower for marker in (" means ", " should be ", " can be translated", " translates to ")):
            return False

        if target_lang.lower().startswith("en"):


            if re.search(r"[А-Яа-яЁё]", translated):
                return False
            ascii_chars = sum(1 for ch in translated if ord(ch) < 128)
            if ascii_chars / max(1, len(translated)) < 0.85:
                return False

        return True

    def translate(self, text: str, *, target_lang: str = "en", source_lang: str = "auto") -> str | None:
        if not self.enabled:
            return None
        if not self._celery_available:
            return None
        raw = " ".join(text.split()).strip()
        if not raw:
            return None

        prompt = self._build_prompt(raw, target_lang)
        async_result = None
        try:
            from celery.exceptions import TimeoutError as CeleryTimeoutError

            async_result = self.celery.send_task(
                "app.tasks.qwen.send_message",
                kwargs={
                    "message": prompt,
                    "session_id": None,
                    "thinking_enabled": False,
                    "search_enabled": False,
                    "file_ids": [],
                    "auto_continue": False,
                    "timeout": self.timeout,
                    "purpose": "parser-query-translation",
                },
                queue=self.queue,
            )
            payload: Any = async_result.get(timeout=self.timeout, propagate=True, disable_sync_subtasks=False)
        except ModuleNotFoundError as exc:
            if exc.name == "celery":
                logger.warning(
                    "Qwen queued translation skipped for '{}': celery is not installed in this environment. "
                    "Install project root requirements.txt or disable PARSER_TRANSLATE_QWEN_ENABLED.",
                    raw,
                )
            else:
                logger.warning("Qwen queued translation failed for '{}': {}", raw, exc)
            return None
        except CeleryTimeoutError as exc:
            if async_result is not None:
                try:
                    async_result.revoke(terminate=False)
                except Exception:
                    logger.debug("Failed to revoke timed-out Qwen translation task", exc_info=True)
            logger.warning("Qwen queued translation timed out for '{}' after {}s: {}", raw, self.timeout, exc)
            return None
        except Exception as exc:
            logger.warning("Qwen queued translation failed for '{}': {}", raw, exc)
            return None

        if not isinstance(payload, dict):
            return None
        if payload.get("error"):
            logger.warning("Qwen queued translation returned error for '{}': {}", raw, payload.get("error"))
            return None
        translated = self._clean_translation_output(str(payload.get("response") or ""))
        if not self._is_usable_translation(raw, translated, target_lang=target_lang):
            logger.warning(
                "Qwen queued translation rejected for '{}': unusable output preview='{}'",
                raw,
                translated[:160],
            )
            return None
        return translated

_SHARED_QWEN_TRANSLATION_ADAPTER: QwenTranslationAdapter | None = None


def get_shared_qwen_translation_adapter() -> QwenTranslationAdapter:
    global _SHARED_QWEN_TRANSLATION_ADAPTER
    if _SHARED_QWEN_TRANSLATION_ADAPTER is None:
        _SHARED_QWEN_TRANSLATION_ADAPTER = QwenTranslationAdapter()
    return _SHARED_QWEN_TRANSLATION_ADAPTER
