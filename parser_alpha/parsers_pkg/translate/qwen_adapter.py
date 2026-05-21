"""Qwen translation adapter for parser_alpha.

The adapter does not call qwen_service directly. It sends a Celery task to the
shared Qwen queue, so parser workers, alloy analysis, RAG, and content tasks all
share the same limited Qwen slot pool.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any

from loguru import logger


class QwenTranslationAdapter:
    def __init__(self) -> None:
        self.enabled = os.getenv("PARSER_TRANSLATE_QWEN_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
        self._celery_available = importlib.util.find_spec("celery") is not None
        # Parser-specific setting wins, generic Qwen queue is fallback.
        self.queue = os.getenv("PARSER_TRANSLATE_QWEN_QUEUE") or os.getenv("QWEN_QUEUE_NAME") or "qwen"
        self.timeout = float(os.getenv("PARSER_TRANSLATE_QWEN_TIMEOUT", os.getenv("QWEN_QUEUE_TIMEOUT", "1000")))
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
            "Верни только перевод, без пояснений, кавычек, markdown и вариантов.\n"
            "Сохрани технические термины: nickel alloys, superalloys, heat resistant alloys, corrosion, patents.\n"
            f"Запрос: {text}"
        )

    def translate(self, text: str, *, target_lang: str = "en", source_lang: str = "auto") -> str | None:
        if not self.enabled:
            return None
        if not self._celery_available:
            return None
        raw = " ".join(text.split()).strip()
        if not raw:
            return None

        prompt = self._build_prompt(raw, target_lang)
        try:
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
                    "Install parser_alpha/requirements.txt or disable PARSER_TRANSLATE_QWEN_ENABLED.",
                    raw,
                )
            else:
                logger.warning("Qwen queued translation failed for '{}': {}", raw, exc)
            return None
        except Exception as exc:
            logger.warning("Qwen queued translation failed for '{}': {}", raw, exc)
            return None

        if not isinstance(payload, dict):
            return None
        if payload.get("error"):
            logger.warning("Qwen queued translation returned error for '{}': {}", raw, payload.get("error"))
            return None
        translated = str(payload.get("response") or "").strip()
        if not translated:
            return None
        # Remove common wrappers if the model still added them.
        translated = translated.strip().strip('"').strip("'").strip()
        return translated or None

_SHARED_QWEN_TRANSLATION_ADAPTER: QwenTranslationAdapter | None = None


def get_shared_qwen_translation_adapter() -> QwenTranslationAdapter:
    global _SHARED_QWEN_TRANSLATION_ADAPTER
    if _SHARED_QWEN_TRANSLATION_ADAPTER is None:
        _SHARED_QWEN_TRANSLATION_ADAPTER = QwenTranslationAdapter()
    return _SHARED_QWEN_TRANSLATION_ADAPTER
