"""Сервис постобработки контента статьи (PDF + AI-анализ + перевод)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
from loguru import logger

from app.core.config import settings
from app.services.qwen_client import get_qwen_client
from app.services.rag_parser import pdf_parser


@dataclass
class AIEnrichmentResult:
    summary_ru: str
    analysis_ru: str
    translation_ru: str
    used_fallback: bool = False
    fallback_reason: str | None = None


def _clean_arxiv_id(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    value = value.replace("http://", "https://")
    if "arxiv.org/abs/" in value:
        value = value.split("arxiv.org/abs/", 1)[1]
    elif "arxiv.org/pdf/" in value:
        value = value.split("arxiv.org/pdf/", 1)[1]
    if value.startswith("arXiv:"):
        value = value[6:]
    value = value.split("/")[-1]
    value = value.replace(".pdf", "")
    return value


def resolve_pdf_url(source: str, source_id: str | None, url: str | None) -> str | None:
    src = (source or "").strip().lower()
    raw_url = (url or "").strip()
    sid = (source_id or "").strip()

    if src == "arxiv":
        arxiv_id = _clean_arxiv_id(sid or raw_url)
        if arxiv_id:
            return f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    if raw_url and raw_url.lower().endswith(".pdf"):
        return raw_url

    return None


def download_pdf_bytes(pdf_url: str, timeout_sec: float = 45.0) -> bytes | None:
    try:
        with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
            response = client.get(pdf_url)
            response.raise_for_status()
            content = response.content or b""
            if not content:
                return None
            content_type = response.headers.get("content-type", "").lower()
            if "pdf" not in content_type and not content.startswith(b"%PDF"):
                logger.warning(f"URL не похож на PDF: {pdf_url} ({content_type})")
                return None
            return content
    except Exception as exc:
        logger.warning(f"Не удалось скачать PDF {pdf_url}: {exc}")
        return None


def save_pdf_locally(paper_id: int, pdf_bytes: bytes) -> str:
    base_dir = Path(settings.resolve_path(settings.PAPER_PDF_DIR))
    base_dir.mkdir(parents=True, exist_ok=True)
    target = base_dir / f"paper_{paper_id}.pdf"
    target.write_bytes(pdf_bytes)
    return str(target)


def extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        return pdf_parser.extract_text_from_bytes(pdf_bytes)
    except Exception as exc:
        logger.warning(f"Не удалось извлечь текст из PDF: {exc}")
        return ""


def _fallback_enrichment(
    title: str,
    abstract: str,
    text: str,
    reason: str,
) -> AIEnrichmentResult:
    source_text = (text or abstract or "").strip()
    short = source_text[:1800] if source_text else "Текст статьи недоступен."
    return AIEnrichmentResult(
        summary_ru=f"Статья: {title}. Краткая суть: {short[:500]}",
        analysis_ru=(
            "Автоанализ выполнен в fallback-режиме. "
            "Рекомендуется повторный запуск при доступном Qwen Service."
        ),
        translation_ru=short,
        used_fallback=True,
        fallback_reason=reason,
    )


def generate_ai_enrichment_ru(title: str, abstract: str, text: str) -> AIEnrichmentResult:
    text_for_model = (text or abstract or "").strip()
    if not text_for_model:
        return _fallback_enrichment(
            title=title,
            abstract=abstract,
            text=text,
            reason="no_input_text_for_enrichment",
        )

    qwen_client = get_qwen_client()
    if not qwen_client.is_available():
        return _fallback_enrichment(
            title=title,
            abstract=abstract,
            text=text,
            reason="qwen_service_unavailable",
        )

    payload_text = text_for_model[:22000]
    prompt = (
        "Сделай научный разбор статьи и перевод на русский.\n"
        "Верни СТРОГО JSON-объект без markdown:\n"
        '{"summary_ru":"...","analysis_ru":"...","translation_ru":"..."}\n'
        "Требования:\n"
        "1) Всё на русском языке.\n"
        "2) summary_ru: 5-8 предложений, суть и практическая ценность.\n"
        "3) analysis_ru: структурированный анализ (материалы, метод, результаты, ограничения).\n"
        "4) translation_ru: перевод ключевого содержания статьи на русский (не менее 8 предложений).\n"
        f"Название: {title}\n"
        f"Аннотация: {abstract or 'нет'}\n"
        f"Текст: {payload_text}"
    )

    result = qwen_client.send_message(
        message=prompt,
        thinking_enabled=True,
        search_enabled=False,
        auto_continue=True,
        timeout=240.0,
    )
    response_text = (result.get("response") or "").strip()
    if not response_text:
        return _fallback_enrichment(
            title=title,
            abstract=abstract,
            text=text,
            reason="qwen_empty_response",
        )

    parsed = None
    try:
        parsed = json.loads(response_text)
    except Exception:
        match = re.search(r"\{[\s\S]*\}", response_text)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except Exception:
                parsed = None

    if not isinstance(parsed, dict):
        return _fallback_enrichment(
            title=title,
            abstract=abstract,
            text=text,
            reason="qwen_invalid_json",
        )

    summary_ru = str(parsed.get("summary_ru") or "").strip()
    analysis_ru = str(parsed.get("analysis_ru") or "").strip()
    translation_ru = str(parsed.get("translation_ru") or "").strip()

    if not (summary_ru and analysis_ru and translation_ru):
        return _fallback_enrichment(
            title=title,
            abstract=abstract,
            text=text,
            reason="qwen_incomplete_fields",
        )

    return AIEnrichmentResult(
        summary_ru=summary_ru,
        analysis_ru=analysis_ru,
        translation_ru=translation_ru,
    )
