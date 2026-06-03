"""API endpoints для парсинга научных статей."""

import csv
import io
import time
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin_user
from app.core.config import settings
from app.api.v1.endpoints.error_helpers import format_paper_db_error
from app.db.models.paper import Paper as PaperModel
from app.db.session import get_db
from app.services.parse_job_history import add_parse_job, update_parse_job
from app.services.parse_admission_service import (
    ParseAdmissionLimitError,
    ParseAdmissionSlot,
    ParseAdmissionUnavailableError,
    get_parse_admission_snapshot,
    release_parse_slot,
    reserve_parse_slot,
)
from app.services.system_settings_service import SystemSettingsService
from app.services.paper_service import PaperService
from app.services.paper_content_part_service import PaperContentPartService
from shared.schemas.auth import UserResponse
from shared.schemas.paper import (
    Paper,
    PaperListItem,
    PaperListResponse,
    PaperDetailResponse,
    PaperContentPart,
    PaperContentPartRegenerateResponse,
    PaperTranslateRequest,
    PaperTranslateResponse,
    PaperProcessingStatusInfo,
    PaperProcessingQualityInfo,
    PaperPipelineStageInfo,
    PaperProcessingPipelineStatus,
    PaperSearchRequest,
    PaperSearchResponse,
)

router = APIRouter(prefix="/papers", tags=["papers"])


PROCESSING_STATUS_REGISTRY: dict[str, dict[str, object]] = {
    "pending": {"label": "Ожидает обработки", "group": "pending", "final": False},
    "queued_for_content_processing": {"label": "В очереди на обработку", "group": "pending", "final": False},
    "processing_content": {"label": "Обрабатывается", "group": "processing", "final": False},
    "content_queue_failed": {"label": "Ошибка постановки content pipeline", "group": "error", "final": False, "stage": "content_queue"},
    "started": {"label": "Запущено", "group": "processing", "final": False},
    "pdf_pending": {"label": "Подготовка PDF", "group": "processing", "final": False},
    "downloading_pdf": {"label": "Загрузка PDF", "group": "processing", "final": False},
    "pdf_downloaded": {"label": "PDF загружен", "group": "processing", "final": False},
    "pdf_download_failed": {"label": "PDF не загрузился", "group": "error", "final": False, "stage": "pdf"},
    "pdf_unavailable": {"label": "PDF недоступен", "group": "warning", "final": True},
    "pdf_download_skipped": {"label": "Загрузка PDF пропущена", "group": "warning", "final": False, "stage": "pdf"},
    "extracting_pdf_text": {"label": "Извлечение текста из PDF", "group": "processing", "final": False},
    "pdf_parsed": {"label": "Текст PDF извлечён", "group": "processing", "final": False},
    "pdf_text_failed": {"label": "Ошибка извлечения текста PDF", "group": "error", "final": False, "stage": "pdf"},
    "pdf_text_skipped": {"label": "Извлечение текста PDF пропущено", "group": "warning", "final": False, "stage": "pdf"},
    "fulltext_fallback_parsed": {"label": "Текст получен из резервного источника", "group": "warning", "final": False},
    "fulltext_unavailable": {"label": "Полный текст недоступен", "group": "warning", "final": True},
    "digitizing_file": {"label": "Оцифровка файла", "group": "processing", "final": False},
    "formatting_markdown": {"label": "Оцифровка файла", "group": "processing", "final": False},
    "markdown_ready": {"label": "Файл оцифрован", "group": "processing", "final": False},
    "markdown_partial": {"label": "Файл частично оцифрован", "group": "warning", "final": False},
    "markdown_ready_without_qwen": {"label": "Текст собран без Qwen", "group": "warning", "final": False, "stage": "qwen_markdown"},
    "page_regenerated": {"label": "Страница переоцифрована", "group": "success", "final": False, "stage": "qwen_markdown"},
    "markdown_failed": {"label": "Ошибка оцифровки файла", "group": "error", "final": False, "stage": "qwen_markdown"},
    "markdown_skipped": {"label": "Оцифровка пропущена", "group": "warning", "final": False, "stage": "qwen_markdown"},
    "analyzing_ru": {"label": "Анализ на русском", "group": "processing", "final": False},
    "ru_analysis_ready": {"label": "Русский анализ готов", "group": "processing", "final": False, "stage": "qwen_ru_analysis"},
    "ru_analysis_failed": {"label": "Ошибка русского анализа", "group": "error", "final": False, "stage": "qwen_ru_analysis"},
    "ru_analysis_fallback": {"label": "Русский анализ в резервном режиме", "group": "warning", "final": False, "stage": "qwen_ru_analysis"},
    "ru_analysis_skipped": {"label": "Русский анализ пропущен", "group": "warning", "final": False, "stage": "qwen_ru_analysis"},
    "translating_article": {"label": "Перевод текста статьи", "group": "processing", "final": False},
    "translation_ready": {"label": "Перевод текста готов", "group": "success", "final": True},
    "translation_partial": {"label": "Перевод текста частично готов", "group": "warning", "final": True},
    "translation_failed": {"label": "Ошибка перевода текста", "group": "error", "final": True},
    "extracting_keywords": {"label": "Выделение ключевых слов", "group": "processing", "final": False},
    "keywords_ready": {"label": "Ключевые слова готовы", "group": "processing", "final": False},
    "keywords_failed": {"label": "Ошибка ключевых слов", "group": "error", "final": False, "stage": "qwen_keywords"},
    "keywords_skipped": {"label": "Ключевые слова пропущены", "group": "warning", "final": False, "stage": "qwen_keywords"},
    "qwen_auth_failed": {"label": "Ошибка авторизации Qwen", "group": "error", "final": False, "stage": "qwen_ocr"},
    "indexing_vector": {"label": "Индексация в векторной базе", "group": "processing", "final": False},
    "embedding_ready": {"label": "Векторный индекс готов", "group": "success", "final": False, "stage": "embedding"},
    "embedding_failed": {"label": "Ошибка векторной индексации", "group": "error", "final": False, "stage": "embedding"},
    "embedding_skipped": {"label": "Векторная индексация пропущена", "group": "warning", "final": False, "stage": "embedding"},
    "ready": {"label": "Готово", "group": "success", "final": True},
    "ready_with_fallback": {"label": "Готово (резервный режим)", "group": "warning", "final": True},
    "completed": {"label": "Готово", "group": "success", "final": True},
    "failed": {"label": "Ошибка обработки", "group": "error", "final": True},
}

TRANSLATION_STATUS_KEYS = {
    "translating_article",
    "translation_ready",
    "translation_partial",
    "translation_failed",
}

PROCESSING_STAGE_LABELS: dict[str, str] = {
    "pending": "Очередь",
    "parser": "Парсер",
    "pdf": "PDF / текст",
    "qwen_ocr": "AI OCR",
    "qwen_markdown": "Qwen Markdown",
    "qwen_ru_analysis": "Русский анализ",
    "qwen_keywords": "Ключевые слова",
    "translation": "Перевод",
    "embedding": "Embedding / Chroma",
    "final": "Финализация",
    "unknown": "Неизвестный этап",
}


def _infer_processing_stage(key: str, meta: dict[str, object]) -> str:
    explicit = str(meta.get("stage") or "").strip()
    if explicit:
        return explicit
    if key in {"pending", "queued_for_content_processing"}:
        return "pending"
    if key in {"processing_content", "started"}:
        return "parser"
    if key.startswith("pdf_") or key in {"downloading_pdf", "extracting_pdf_text", "fulltext_fallback_parsed", "fulltext_unavailable"}:
        return "pdf"
    if key in {"digitizing_file"}:
        return "qwen_ocr"
    if key.startswith("markdown_") or key in {"formatting_markdown", "page_regenerated"}:
        return "qwen_markdown"
    if key.startswith("ru_analysis_") or key == "analyzing_ru" or key == "qwen_auth_failed":
        return "qwen_ru_analysis"
    if key.startswith("keywords_") or key == "extracting_keywords":
        return "qwen_keywords"
    if key.startswith("translation_") or key == "translating_article":
        return "translation"
    if key.startswith("embedding_") or key == "indexing_vector":
        return "embedding"
    if key in {"ready", "ready_with_fallback", "completed", "failed"}:
        return "final"
    return "unknown"


def _status_info(key: str) -> PaperProcessingStatusInfo:
    base_key = (key or "").strip().split(":", 1)[0]
    meta = PROCESSING_STATUS_REGISTRY.get(base_key) or {"label": base_key, "group": "unknown", "final": False}
    stage = _infer_processing_stage(base_key, meta)
    return PaperProcessingStatusInfo(
        key=base_key,
        label=str(meta.get("label") or base_key),
        group=str(meta.get("group") or "unknown"),
        final=bool(meta.get("final")),
        stage=stage,
        stage_label=PROCESSING_STAGE_LABELS.get(stage, stage),
    )


def _part_metadata_value(part: object, key: str) -> str:
    metadata = getattr(part, "extraction_metadata", None) or {}
    if not isinstance(metadata, dict):
        return ""
    value = metadata.get(key)
    if value is None:
        return ""
    return str(value).strip().lower()


def _part_mode_signal(part: object) -> str:
    values = [
        getattr(part, "extraction_method", None),
        _part_metadata_value(part, "parser_mode"),
        _part_metadata_value(part, "extraction_mode"),
        _part_metadata_value(part, "force_strategy"),
        _part_metadata_value(part, "selected_strategy"),
        _part_metadata_value(part, "primary_selected_strategy"),
        _part_metadata_value(part, "extraction_strategy"),
        _part_metadata_value(part, "regeneration_mode"),
    ]
    return " ".join(str(value or "").lower() for value in values)


def _classify_part_processing_mode(part: object) -> str:
    signal = _part_mode_signal(part)
    if "ai_page_image" in signal or " ai" in f" {signal}" or signal == "ai":
        return "ai"
    if "mypdf" in signal:
        return "mypdf"
    return "auto"


def _normalized_quality_score(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 1 and number <= 100:
        number = number / 100
    return max(0.0, min(1.0, number))


def _document_processing_summary_from_part(part: object) -> dict[str, object] | None:
    """Return persisted document-level processing summary from a content part.

    The summary is written by the PDF extraction task before empty pages are
    filtered out. This keeps AI quality honest: 8 saved text pages out of a
    10-page PDF should be shown as 8/10, not 8/8.
    """
    metadata = getattr(part, "extraction_metadata", None) or {}
    if not isinstance(metadata, dict):
        return None

    direct = metadata.get("document_processing")
    if isinstance(direct, dict):
        return direct

    pages = metadata.get("pages")
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue
            nested_metadata = page.get("metadata")
            if isinstance(nested_metadata, dict) and isinstance(nested_metadata.get("document_processing"), dict):
                return nested_metadata["document_processing"]
    return None


def _coerce_int(value: object) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _processing_quality_from_summary(summary: dict[str, object]) -> PaperProcessingQualityInfo | None:
    requested_mode = str(summary.get("requested_mode") or summary.get("mode") or "").strip().lower() or None
    actual_mode = str(summary.get("actual_mode") or summary.get("mode") or "").strip().lower() or None
    mode = actual_mode or requested_mode or "unknown"
    pages_total = _coerce_int(summary.get("pages_total"))
    pages_success = _coerce_int(summary.get("pages_success"))
    pages_failed = _coerce_int(summary.get("pages_failed"))
    fallback_used = bool(summary.get("fallback_used"))
    score = _normalized_quality_score(summary.get("quality_score"))

    if mode == "mypdf" or requested_mode == "mypdf":
        return PaperProcessingQualityInfo(
            mode="mypdf",
            score=0.8,
            label="MyPDF — 80%",
            basis="MyPDF берёт только текстовый слой PDF без OCR, фото и восстановления таблиц; поэтому для режима фиксируется 80% независимо от внутреннего fallback.",
            status="success",
            pages_total=pages_total,
            pages_success=pages_success,
            pages_failed=pages_failed,
            fallback_used=fallback_used,
            requested_mode=requested_mode,
            actual_mode=actual_mode,
        )

    if requested_mode == "ai" and fallback_used and mode != "ai":
        percent = round((score or 0) * 100) if score is not None else None
        return PaperProcessingQualityInfo(
            mode="mixed",
            score=score,
            label=f"AI → Auto — {percent}%" if percent is not None else "AI → Auto — качество не рассчитано",
            basis="Запуск был в режиме AI, но AI-распознавание не дало текст и сработал fallback на локальный auto-парсер. Это не считается AI 100%.",
            status="warning",
            pages_total=pages_total,
            pages_success=pages_success,
            pages_failed=pages_failed,
            fallback_used=True,
            requested_mode=requested_mode,
            actual_mode=actual_mode,
        )

    if mode == "ai" or requested_mode == "ai":
        if pages_total and pages_success is not None:
            ratio = pages_success / max(1, pages_total)
            percent = round(ratio * 100)
            failed = pages_failed if pages_failed is not None else max(0, pages_total - pages_success)
            return PaperProcessingQualityInfo(
                mode="ai",
                score=round(ratio, 4),
                label=f"AI — {percent}%",
                basis=f"Успешно распознано AI-страниц: {pages_success}/{pages_total}. 100% показывается только когда все страницы исходного PDF распознаны успешно.",
                status="success" if failed == 0 and pages_success == pages_total else "warning",
                pages_total=pages_total,
                pages_success=pages_success,
                pages_failed=failed,
                fallback_used=fallback_used,
                requested_mode=requested_mode,
                actual_mode=actual_mode,
            )
        if score is not None:
            percent = round(score * 100)
            return PaperProcessingQualityInfo(
                mode="ai",
                score=score,
                label=f"AI — {percent}%",
                basis="AI-качество рассчитано по сохранённому document_processing. Для старых записей без счётчиков страниц точность ниже.",
                status="success" if score >= 0.995 else "warning",
                pages_total=pages_total,
                pages_success=pages_success,
                pages_failed=pages_failed,
                fallback_used=fallback_used,
                requested_mode=requested_mode,
                actual_mode=actual_mode,
            )

    if mode == "auto" or requested_mode == "auto":
        percent = round(score * 100) if score is not None else None
        return PaperProcessingQualityInfo(
            mode="auto",
            score=score,
            label=f"Auto — {percent}%" if percent is not None else "Auto — качество ещё не рассчитано",
            basis="Auto показывает качество после отработки локального PDF-парсера. Расчёт берётся из document_processing, а не из догадки frontend.",
            status="success" if (score or 0) >= 0.75 else ("unknown" if score is None else "warning"),
            pages_total=pages_total,
            pages_success=pages_success,
            pages_failed=pages_failed,
            fallback_used=fallback_used,
            requested_mode=requested_mode,
            actual_mode=actual_mode,
        )

    return None


def _paper_processing_quality(content_parts: list[object]) -> PaperProcessingQualityInfo:
    for part in content_parts:
        summary = _document_processing_summary_from_part(part)
        if summary:
            from_summary = _processing_quality_from_summary(summary)
            if from_summary:
                return from_summary

    usable_parts = [
        part
        for part in content_parts
        if (
            _normalized_quality_score(getattr(part, "extraction_quality_score", None)) is not None
            or bool(str(getattr(part, "raw_text", "") or "").strip())
            or bool(str(getattr(part, "extraction_method", "") or "").strip())
            or bool(getattr(part, "extraction_metadata", None))
        )
    ]
    if not usable_parts:
        return PaperProcessingQualityInfo()

    modes = [_classify_part_processing_mode(part) for part in usable_parts]
    unique_modes = set(modes)

    if unique_modes == {"mypdf"}:
        return PaperProcessingQualityInfo(
            mode="mypdf",
            score=0.8,
            label="MyPDF — 80%",
            basis="MyPDF берёт только текстовый слой PDF без OCR, фото и восстановления таблиц; поэтому для режима фиксируется 80%.",
            status="success",
            pages_total=len(usable_parts),
            pages_success=len(usable_parts),
            pages_failed=0,
        )

    if "ai" in unique_modes and unique_modes <= {"ai"}:
        total = len(usable_parts)
        success = 0
        scored = 0
        for part in usable_parts:
            score = _normalized_quality_score(getattr(part, "extraction_quality_score", None))
            raw_text = str(getattr(part, "raw_text", "") or "").strip()
            if score is not None:
                scored += 1
                if score >= 0.995:
                    success += 1
            elif raw_text:
                success += 1
        ratio = success / max(1, total)
        percent = round(ratio * 100)
        status = "success" if total > 0 and success == total and scored == total else "warning"
        score_note = "" if scored == total else " Это legacy-оценка только по сохранённым частям; для честного AI-процента нужна новая обработка с document_processing."
        return PaperProcessingQualityInfo(
            mode="ai",
            score=round(ratio, 4),
            label=f"AI — {percent}%",
            basis=f"Успешно распознано сохранённых AI-частей: {success}/{total}.{score_note}",
            status=status,
            pages_total=total,
            pages_success=success,
            pages_failed=max(0, total - success),
        )

    if len(unique_modes) > 1:
        scores = [
            score
            for part in usable_parts
            if (score := _normalized_quality_score(getattr(part, "extraction_quality_score", None))) is not None
        ]
        avg = sum(scores) / len(scores) if scores else None
        label = f"Смешанный режим — {round(avg * 100)}%" if avg is not None else "Смешанный режим — качество не рассчитано"
        return PaperProcessingQualityInfo(
            mode="mixed",
            score=round(avg, 4) if avg is not None else None,
            label=label,
            basis="В документе смешаны разные способы обработки страниц: auto, MyPDF и/или AI. Обычно это результат частичной перегенерации страниц.",
            status="warning",
            pages_total=len(usable_parts),
        )

    scores = [
        score
        for part in usable_parts
        if (score := _normalized_quality_score(getattr(part, "extraction_quality_score", None))) is not None
    ]
    if not scores:
        return PaperProcessingQualityInfo(
            mode="auto",
            score=None,
            label="Auto — качество ещё не рассчитано",
            basis="Auto должен показывать среднее extraction_quality_score после локального PDF-парсера, но у частей пока нет сохранённого score.",
            status="unknown",
            pages_total=len(usable_parts),
        )

    avg = sum(scores) / len(scores)
    return PaperProcessingQualityInfo(
        mode="auto",
        score=round(avg, 4),
        label=f"Auto — {round(avg * 100)}%",
        basis="Auto показывает среднее extraction_quality_score по сохранённым частям после локального PDF-парсера.",
        status="success" if avg >= 0.75 else "warning",
        pages_total=len(usable_parts),
        pages_success=len([score for score in scores if score > 0]),
        pages_failed=len(usable_parts) - len([score for score in scores if score > 0]),
    )




def _short_pipeline_error(value: object, limit: int = 600) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = " ".join(text.split())
    return text[:limit]


def _paper_text_available(paper: object) -> bool:
    return bool(str(getattr(paper, "full_text", None) or getattr(paper, "abstract", None) or "").strip())


def _paper_keywords_count(paper: object) -> int:
    keywords = getattr(paper, "keywords", None) or []
    if isinstance(keywords, str):
        return len([item for item in keywords.replace(";", ",").split(",") if item.strip()])
    try:
        return len([item for item in keywords if str(item).strip()])
    except TypeError:
        return 0


def _part_text_chars(part: object, attr: str) -> int:
    explicit = getattr(part, f"{attr}_chars", None)
    if isinstance(explicit, int) and explicit > 0:
        return explicit
    return len(str(getattr(part, attr, None) or "").strip())


def _part_metadata(part: object) -> dict:
    metadata = getattr(part, "extraction_metadata", None) or {}
    return metadata if isinstance(metadata, dict) else {}


def _parts_document_summaries(content_parts: list[object]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for part in content_parts:
        summary = _document_processing_summary_from_part(part)
        if isinstance(summary, dict):
            summaries.append(summary)
    return summaries


def _pipeline_stage(
    key: str,
    label: str,
    status: str,
    status_label: str,
    progress: int,
    *,
    final: bool = False,
    enabled: bool | None = None,
    skipped: bool = False,
    fallback_used: bool = False,
    error: object | None = None,
    source: str = "derived",
    details: dict[str, object] | None = None,
) -> PaperPipelineStageInfo:
    return PaperPipelineStageInfo(
        key=key,
        label=label,
        status=status,
        status_label=status_label,
        progress=max(0, min(100, int(progress or 0))),
        final=final,
        enabled=enabled,
        skipped=skipped,
        fallback_used=fallback_used,
        error=_short_pipeline_error(error),
        source=source,
        details=details or {},
    )


def _build_paper_pipeline_status(
    paper: object,
    content_parts: list[object],
) -> PaperProcessingPipelineStatus:
    """Build a compact, stage-based AI/PDF/Qwen status model for article details.

    Это вычисляемая модель поверх текущих полей БД: она не требует миграции и
    специально не кладёт в details большие тексты, Markdown или OCR payload.
    """
    status_key = _status_info(getattr(paper, "processing_status", None)).key
    processing_error = _short_pipeline_error(getattr(paper, "processing_error", None))
    has_full_text = bool(str(getattr(paper, "full_text", None) or "").strip())
    has_any_text = _paper_text_available(paper)
    has_pdf_url = bool(str(getattr(paper, "pdf_url", None) or "").strip())
    has_pdf_file = bool(str(getattr(paper, "pdf_local_path", None) or "").strip())
    raw_parts = [part for part in content_parts if _part_text_chars(part, "raw_text") > 0]
    markdown_parts = [part for part in content_parts if _part_text_chars(part, "markdown_text") > 0]
    summaries = _parts_document_summaries(content_parts)
    requested_modes = {
        str(summary.get("requested_mode") or summary.get("mode") or "").strip().lower()
        for summary in summaries
        if str(summary.get("requested_mode") or summary.get("mode") or "").strip()
    }
    actual_modes = {
        str(summary.get("actual_mode") or summary.get("mode") or "").strip().lower()
        for summary in summaries
        if str(summary.get("actual_mode") or summary.get("mode") or "").strip()
    }
    modes_from_parts = {_classify_part_processing_mode(part) for part in content_parts}
    ai_requested = "ai" in requested_modes or "ai" in modes_from_parts
    ai_used = "ai" in actual_modes or "ai" in modes_from_parts
    mypdf_used = "mypdf" in requested_modes or "mypdf" in actual_modes or "mypdf" in modes_from_parts
    doc_fallback_used = any(bool(summary.get("fallback_used")) for summary in summaries)
    pages_total = next((summary.get("pages_total") for summary in summaries if summary.get("pages_total") is not None), None)
    pages_success = next((summary.get("pages_success") for summary in summaries if summary.get("pages_success") is not None), None)
    pages_failed = next((summary.get("pages_failed") for summary in summaries if summary.get("pages_failed") is not None), None)

    pdf_error_keys = {"pdf_download_failed", "pdf_text_failed"}
    pdf_skipped_keys = {"pdf_unavailable", "pdf_download_skipped", "pdf_text_skipped", "fulltext_unavailable"}
    if status_key in {"pdf_pending", "downloading_pdf", "extracting_pdf_text"}:
        pdf_stage = _pipeline_stage("pdf", "PDF / текст", "processing", _format_processing_status_label(status_key), 40, source="processing_status")
    elif status_key in pdf_error_keys:
        pdf_stage = _pipeline_stage("pdf", "PDF / текст", "error", _format_processing_status_label(status_key), 50, final=True, error=processing_error, source="processing_status")
    elif status_key in pdf_skipped_keys and not has_any_text:
        pdf_stage = _pipeline_stage("pdf", "PDF / текст", "skipped", _format_processing_status_label(status_key), 100, final=True, skipped=True, source="processing_status")
    elif has_pdf_file or raw_parts or has_full_text:
        pdf_stage = _pipeline_stage(
            "pdf",
            "PDF / текст",
            "success",
            "Текстовый слой получен" if (raw_parts or has_full_text) else "PDF загружен",
            100,
            final=True,
            source="content_parts" if raw_parts else "paper_fields",
            details={
                "raw_parts": len(raw_parts),
                "has_pdf_file": has_pdf_file,
                "has_full_text": has_full_text,
                "mode": "mypdf" if mypdf_used else ("auto" if not ai_used else "ai"),
            },
        )
    elif has_pdf_url:
        pdf_stage = _pipeline_stage("pdf", "PDF / текст", "pending", "PDF найден, обработка ещё не запускалась", 15, source="paper_fields")
    else:
        pdf_stage = _pipeline_stage("pdf", "PDF / текст", "skipped", "PDF не найден; используется metadata/abstract", 100, final=True, skipped=True, source="paper_fields")

    if status_key in {"digitizing_file"} or status_key.startswith("digitizing_file:"):
        ocr_stage = _pipeline_stage("ocr", "AI OCR", "processing", _format_processing_status_label(getattr(paper, "processing_status", None)), 55, enabled=True, source="processing_status")
    elif status_key == "qwen_auth_failed":
        ocr_stage = _pipeline_stage("ocr", "AI OCR", "error", "Ошибка авторизации Qwen", 80, final=True, enabled=True, error=processing_error, source="processing_status")
    elif ai_used and markdown_parts:
        ocr_stage = _pipeline_stage("ocr", "AI OCR", "success", "AI OCR завершён", 100, final=True, enabled=True, source="content_parts", details={"markdown_parts": len(markdown_parts), "pages_total": pages_total, "pages_success": pages_success})
    elif ai_requested and doc_fallback_used:
        ocr_stage = _pipeline_stage("ocr", "AI OCR", "warning", "AI OCR не дал полный результат, использован fallback", 100, final=True, enabled=True, fallback_used=True, source="document_processing", details={"pages_total": pages_total, "pages_success": pages_success, "pages_failed": pages_failed})
    elif ai_requested:
        ocr_stage = _pipeline_stage("ocr", "AI OCR", "pending", "AI OCR запрошен, но результата ещё нет", 30, enabled=True, source="document_processing")
    else:
        ocr_stage = _pipeline_stage("ocr", "AI OCR", "skipped", "AI OCR не использовался", 100, final=True, enabled=False, skipped=True, source="derived")

    if status_key in {"formatting_markdown", "digitizing_file"} or status_key.startswith("digitizing_file:"):
        markdown_stage = _pipeline_stage("markdown", "Qwen Markdown", "processing", _format_processing_status_label(getattr(paper, "processing_status", None)), 62, enabled=True, source="processing_status")
    elif status_key == "markdown_failed":
        markdown_stage = _pipeline_stage("markdown", "Qwen Markdown", "error", "Markdown не сформирован", 72, final=True, enabled=True, error=processing_error, source="processing_status")
    elif status_key == "markdown_partial":
        markdown_stage = _pipeline_stage("markdown", "Qwen Markdown", "warning", "Markdown сформирован частично", 85, final=True, enabled=True, fallback_used=True, error=processing_error, source="processing_status")
    elif markdown_parts:
        markdown_stage = _pipeline_stage("markdown", "Qwen Markdown", "success", "Markdown готов", 100, final=True, enabled=True, source="content_parts", details={"markdown_parts": len(markdown_parts)})
    elif status_key in {"markdown_skipped", "markdown_ready_without_qwen"}:
        markdown_stage = _pipeline_stage("markdown", "Qwen Markdown", "skipped", _format_processing_status_label(status_key), 100, final=True, enabled=False, skipped=True, fallback_used=status_key == "markdown_ready_without_qwen", source="processing_status")
    elif raw_parts or has_any_text:
        markdown_stage = _pipeline_stage("markdown", "Qwen Markdown", "skipped", "Есть текст без Qwen Markdown", 100, final=True, enabled=None, skipped=True, source="paper_fields")
    else:
        markdown_stage = _pipeline_stage("markdown", "Qwen Markdown", "pending", "Markdown ещё не сформирован", 0, enabled=None, source="derived")

    has_ru_analysis = bool(str(getattr(paper, "summary_ru", None) or getattr(paper, "analysis_ru", None) or "").strip())
    if status_key == "analyzing_ru":
        ru_stage = _pipeline_stage("ru_analysis", "Русский анализ", "processing", "Русский анализ выполняется", 80, enabled=True, source="processing_status")
    elif status_key in {"ru_analysis_failed", "qwen_auth_failed"}:
        ru_stage = _pipeline_stage("ru_analysis", "Русский анализ", "error", _format_processing_status_label(status_key), 86, final=True, enabled=True, error=processing_error, source="processing_status")
    elif status_key == "ru_analysis_fallback":
        ru_stage = _pipeline_stage("ru_analysis", "Русский анализ", "warning", "Русский анализ выполнен в fallback-режиме", 100, final=True, enabled=True, fallback_used=True, error=processing_error, source="processing_status")
    elif has_ru_analysis:
        ru_stage = _pipeline_stage("ru_analysis", "Русский анализ", "success", "Русский анализ готов", 100, final=True, enabled=True, source="paper_fields")
    elif status_key == "ru_analysis_skipped" or status_key in {"ready", "completed"}:
        ru_stage = _pipeline_stage("ru_analysis", "Русский анализ", "skipped", "Русский анализ не запускался или отключён", 100, final=True, enabled=None, skipped=True, source="processing_status" if status_key == "ru_analysis_skipped" else "derived")
    elif status_key == "ready_with_fallback" and processing_error:
        ru_stage = _pipeline_stage("ru_analysis", "Русский анализ", "warning", "Русский анализ недоступен или выполнен с fallback", 100, final=True, enabled=True, fallback_used=True, error=processing_error, source="processing_status")
    else:
        ru_stage = _pipeline_stage("ru_analysis", "Русский анализ", "pending" if has_any_text else "skipped", "Ожидает текста" if has_any_text else "Нет текста для анализа", 0 if has_any_text else 100, final=not has_any_text, enabled=None, skipped=not has_any_text, source="derived")

    keywords_count = _paper_keywords_count(paper)
    if status_key == "extracting_keywords":
        keywords_stage = _pipeline_stage("keywords", "Ключевые слова", "processing", "Выделение ключевых слов", 90, enabled=True, source="processing_status")
    elif status_key == "keywords_failed":
        keywords_stage = _pipeline_stage("keywords", "Ключевые слова", "error", "Ключевые слова не сформированы", 92, final=True, enabled=True, error=processing_error, source="processing_status")
    elif keywords_count > 0:
        keywords_stage = _pipeline_stage("keywords", "Ключевые слова", "success", f"Ключевые слова готовы: {keywords_count}", 100, final=True, enabled=True, source="paper_fields", details={"keywords_count": keywords_count})
    elif status_key == "keywords_skipped" or status_key in {"ready", "completed"}:
        keywords_stage = _pipeline_stage("keywords", "Ключевые слова", "skipped", "Ключевые слова не запускались или отключены", 100, final=True, enabled=None, skipped=True, source="processing_status" if status_key == "keywords_skipped" else "derived")
    elif status_key == "ready_with_fallback" and processing_error:
        keywords_stage = _pipeline_stage("keywords", "Ключевые слова", "warning", "Ключевые слова недоступны или получены fallback-ом", 100, final=True, enabled=True, fallback_used=True, error=processing_error, source="processing_status")
    else:
        keywords_stage = _pipeline_stage("keywords", "Ключевые слова", "pending" if has_any_text else "skipped", "Ожидает текста" if has_any_text else "Нет текста для ключевых слов", 0 if has_any_text else 100, final=not has_any_text, enabled=None, skipped=not has_any_text, source="derived")

    has_embedding = getattr(paper, "embedding", None) not in (None, "")
    if status_key == "indexing_vector":
        embedding_stage = _pipeline_stage("embedding", "Embedding / Chroma", "processing", "Индексация в векторной базе", 96, enabled=True, source="processing_status")
    elif status_key == "embedding_failed":
        embedding_stage = _pipeline_stage("embedding", "Embedding / Chroma", "error", "Векторная индексация не выполнена", 96, final=True, enabled=True, error=processing_error, source="processing_status")
    elif status_key == "embedding_ready" or has_embedding:
        embedding_stage = _pipeline_stage("embedding", "Embedding / Chroma", "success", "Векторный индекс готов", 100, final=True, enabled=True, source="processing_status" if status_key == "embedding_ready" else "paper_fields")
    elif status_key == "embedding_skipped" or status_key in {"ready", "ready_with_fallback", "completed"}:
        embedding_stage = _pipeline_stage("embedding", "Embedding / Chroma", "skipped", "Векторная индексация пропущена или не настроена", 100, final=True, enabled=None, skipped=True, source="processing_status" if status_key == "embedding_skipped" else "derived")
    else:
        embedding_stage = _pipeline_stage("embedding", "Embedding / Chroma", "pending" if has_any_text else "skipped", "Ожидает текста" if has_any_text else "Нет текста для индексации", 0 if has_any_text else 100, final=not has_any_text, enabled=None, skipped=not has_any_text, source="derived")

    if status_key in {"ready", "completed"}:
        final_stage = _pipeline_stage("final", "Финализация", "success", "Документ готов", 100, final=True, source="processing_status")
    elif status_key == "ready_with_fallback":
        final_stage = _pipeline_stage("final", "Финализация", "warning", "Документ готов с fallback/предупреждениями", 100, final=True, fallback_used=True, error=processing_error, source="processing_status")
    elif status_key == "failed":
        final_stage = _pipeline_stage("final", "Финализация", "error", "Документ завершился ошибкой", 100, final=True, error=processing_error, source="processing_status")
    elif status_key in {"pending", "queued_for_content_processing"}:
        final_stage = _pipeline_stage("final", "Финализация", "pending", "Финализация ещё не началась", 0, source="processing_status")
    else:
        final_stage = _pipeline_stage("final", "Финализация", "processing", "Pipeline ещё не финализирован", 70, source="processing_status")

    stages = [pdf_stage, ocr_stage, markdown_stage, ru_stage, keywords_stage, embedding_stage, final_stage]
    has_errors = any(stage.status == "error" for stage in stages)
    has_warnings = any(stage.status == "warning" or stage.fallback_used for stage in stages)
    if final_stage.status == "error":
        aggregate_status = "error"
        aggregate_label = "Обработка завершилась ошибкой"
    elif final_stage.status == "warning" or has_warnings or has_errors:
        aggregate_status = "warning"
        aggregate_label = "Готово с fallback/предупреждениями" if final_stage.final else "Есть предупреждения по этапам"
    elif final_stage.status == "success":
        aggregate_status = "success"
        aggregate_label = "Обработка завершена"
    elif any(stage.status == "processing" for stage in stages):
        aggregate_status = "processing"
        aggregate_label = "Обработка выполняется"
    elif any(stage.status == "pending" for stage in stages):
        aggregate_status = "pending"
        aggregate_label = "Ожидает обработки"
    else:
        aggregate_status = "unknown"
        aggregate_label = "Нет данных обработки"
    if final_stage.final:
        aggregate_progress = 100
    else:
        aggregate_progress = round(sum(stage.progress for stage in stages) / max(1, len(stages)))

    return PaperProcessingPipelineStatus(
        aggregate_status=aggregate_status,
        aggregate_label=aggregate_label,
        aggregate_progress=aggregate_progress,
        has_errors=has_errors,
        has_warnings=has_warnings,
        pdf_stage=pdf_stage,
        ocr_stage=ocr_stage,
        markdown_stage=markdown_stage,
        ru_analysis_stage=ru_stage,
        keywords_stage=keywords_stage,
        embedding_stage=embedding_stage,
        final_stage=final_stage,
        stages=stages,
    )

def _format_processing_status_label(status: object) -> str:
    raw = str(status or "").strip()
    if not raw:
        return _status_info("").label
    info = _status_info(raw)
    if raw.startswith("digitizing_file:"):
        try:
            current_text, total_text = raw.split(":", 1)[1].split("/", 1)
            current = max(0, int(current_text))
            total = max(1, int(total_text))
            return f"{info.label} — {min(current, total)}/{total} стр."
        except Exception:
            return info.label
    return info.label

def _format_csv_list(value) -> str:
    if not value:
        return ""
    if isinstance(value, list):
        return "; ".join(str(item) for item in value if str(item).strip())
    return str(value)


def _papers_csv_response(rows: list[dict]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([
        "ID",
        "Название",
        "Источник",
        "Язык",
        "Дата публикации",
        "DOI",
        "Журнал",
        "Авторы",
        "Ключевые слова",
        "PDF",
        "Извлечённый полный текст",
        "Статус",
    ])
    for row in rows:
        publication_date = row.get("publication_date")
        writer.writerow([
            row.get("id") or "",
            row.get("title") or "",
            row.get("source") or "",
            row.get("language_name") or row.get("language_code") or "",
            publication_date.date().isoformat() if hasattr(publication_date, "date") else (publication_date or ""),
            row.get("doi") or "",
            row.get("journal") or "",
            _format_csv_list(row.get("authors")),
            _format_csv_list(row.get("keywords")),
            "Да" if row.get("has_pdf") else "Нет",
            "Да" if row.get("has_full_text") else "Нет",
            _format_processing_status_label(row.get("processing_status")),
        ])

    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="articles.csv"'},
    )


class _LazyTaskProxy:
    """Backwards-compatible proxy for Celery tasks used by tests and endpoints."""

    def __init__(self, task_name: str):
        self._task_name = task_name

    def _task(self):
        return getattr(_get_parse_task_module(), self._task_name)

    def delay(self, *args, **kwargs):
        return self._task().delay(*args, **kwargs)

    def apply_async(self, *args, **kwargs):
        return self._task().apply_async(*args, **kwargs)

    def __getattr__(self, item):
        return getattr(self._task(), item)


parse_papers_task = _LazyTaskProxy("parse_papers_task")
parse_all_sources_task = _LazyTaskProxy("parse_all_sources_task")
parse_multiple_queries_task = _LazyTaskProxy("parse_multiple_queries_task")


def _get_parse_task_module():
    """Lazy import Celery parser tasks only when a parse endpoint is used."""
    from app.tasks import parse_tasks

    return parse_tasks


def _get_content_task():
    """Lazy import content task only when PDF post-processing is queued."""
    from app.tasks.content_tasks import process_paper_content_task

    return process_paper_content_task


def _get_regenerate_markdown_part_task():
    """Lazy import Qwen part-regeneration task."""
    from app.tasks.qwen_tasks import regenerate_markdown_part_task

    return regenerate_markdown_part_task


def _get_translate_markdown_parts_task():
    """Lazy import Qwen article translation task."""
    from app.tasks.qwen_tasks import translate_markdown_parts_task

    return translate_markdown_parts_task


_PAPERS_COUNT_TTL_SECONDS = 5.0
_papers_count_cache: dict[str, tuple[int, float]] = {}

def _count_cache_key(source: str | None) -> str:
    return source or "__all__"


def _get_cached_count(source: str | None) -> tuple[int, bool] | None:
    key = _count_cache_key(source)
    cached = _papers_count_cache.get(key)
    if not cached:
        return None
    total, ts = cached
    is_stale = (time.monotonic() - ts) > _PAPERS_COUNT_TTL_SECONDS
    return total, is_stale


def _set_cached_count(source: str | None, total: int) -> None:
    _papers_count_cache[_count_cache_key(source)] = (total, time.monotonic())


def _is_source_enabled(parser_settings: dict, source: str) -> bool:
    enabled_sources = parser_settings.get("enabled_sources") or {}
    return bool(enabled_sources.get(source, True))


def _effective_parse_limit(requested_limit: int | None, parser_settings: dict, source: str) -> int:
    default_limit = int(parser_settings.get("default_limit") or 10)
    max_limit = int(parser_settings.get("max_limit") or 100)
    source_limits = parser_settings.get("source_limits") or {}
    source_limit = int(source_limits.get(source) or max_limit)
    requested = int(requested_limit or default_limit)
    return max(1, min(requested, max_limit, source_limit))


async def _get_parser_settings(db: AsyncSession) -> dict:
    return await SystemSettingsService(db).get_parser_settings()


def _max_parallel_parse_jobs(parser_settings: dict) -> int:
    try:
        return int(parser_settings.get("max_parallel_parse_jobs") or 1)
    except (TypeError, ValueError):
        return 1


def _reserve_parallel_parse_slot(
    *,
    parser_settings: dict,
    task_name: str,
    source: str,
    query: str,
) -> ParseAdmissionSlot:
    """Reserve a root parser slot before publishing the Celery message.

    This counts already accepted queued/reserved/root-running jobs immediately,
    instead of waiting until workers expose them through Celery inspect.active().
    """
    max_parallel = _max_parallel_parse_jobs(parser_settings)
    try:
        return reserve_parse_slot(
            max_parallel=max_parallel,
            task_name=task_name,
            source=source,
            query=query,
        )
    except ParseAdmissionLimitError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Достигнут лимит parse-задач: {exc.occupied}/{exc.max_parallel}. "
                "Учитываются ожидающие, зарезервированные и выполняющиеся root parse-задачи."
            ),
        ) from exc
    except ParseAdmissionUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Redis недоступен для безопасной постановки parse-задачи: {exc}",
        ) from exc


async def _count_papers_for_source(db: AsyncSession, source: str | None) -> int:
    stmt = select(func.count()).select_from(PaperModel)
    if source and source != "all":
        stmt = stmt.where(PaperModel.source == source)
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


def _record_parse_job(
    *,
    task_id: str,
    query: str,
    source: str,
    initial_count: int,
    status: str = "in_progress",
    celery_status: dict[str, object] | None = None,
) -> bool:
    started_at = int(time.time() * 1000)
    payload = {
        "jobId": task_id,
        "startedAt": started_at,
        "query": query,
        "source": source,
        "initialCount": initial_count,
        "lastObservedCount": initial_count,
        "lastCountChangeAt": started_at,
        "status": status,
        "jobType": "parse",
    }
    if celery_status is not None:
        payload["celeryStatus"] = celery_status
    try:
        add_parse_job(payload)
        return True
    except Exception as exc:
        logger.warning("Failed to record parse job {} in shared history: {}", task_id, exc)
        return False


def _safe_patch_parse_job(task_id: str, patch: dict[str, object]) -> None:
    try:
        update_parse_job(task_id, patch)
    except Exception as exc:
        logger.warning("Failed to patch parse job {} in shared history: {}", task_id, exc)


@router.post("/search", response_model=PaperSearchResponse)
async def search_papers(
    request: PaperSearchRequest,
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Поиск статей в локальной базе данных."""
    paper_service = PaperService(db)
    try:
        papers = await paper_service.search(
            query=request.query,
            limit=request.limit,
            sources=request.sources,
            full_text_only=request.full_text_only,
        )
    except Exception as exc:
        logger.exception("Failed to search papers")
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    return PaperSearchResponse(
        papers=papers,
        total=len(papers),
        query=request.query,
        sources=request.sources or ["CORE"],
    )


@router.get("", response_model=PaperListResponse)
async def get_papers(
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source: str | None = Query(None, description="Фильтр по источнику"),
    query: str | None = Query(None, description="Поиск по названию, аннотации, авторам, журналу, DOI и ключевым словам"),
    date_from: date | None = Query(None, description="Дата публикации с"),
    date_to: date | None = Query(None, description="Дата публикации по"),
    processing_status: str | None = Query(None, description="Фильтр по статусу обработки"),
    translation_status: str | None = Query(None, description="Фильтр по статусу перевода"),
    full_text_only: bool = Query(False, description="Только записи с извлечённым полным текстом"),
    sort_by: Literal["id", "authors", "created_at", "publication_date", "relevance"] = Query("created_at"),
    sort_dir: Literal["asc", "desc"] = Query("desc"),
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Лёгкий список статей с backend-фильтрами, сортировкой и total."""
    paper_service = PaperService(db)
    try:
        items, total = await paper_service.list_filtered_lightweight(
            limit=limit,
            offset=offset,
            source=source,
            query=query,
            date_from=date_from,
            date_to=date_to,
            processing_status=processing_status,
            translation_status=translation_status,
            full_text_only=full_text_only,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except Exception as exc:
        logger.exception("Failed to list papers")
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    return PaperListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/recent", response_model=list[PaperListItem])
async def get_recent_papers(
    limit: int = Query(default=20, ge=1, le=100),
    source: str | None = Query(None, description="Фильтр по источнику"),
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Лёгкий список последних статей для dashboard без full_text."""
    paper_service = PaperService(db)
    try:
        return await paper_service.get_recent_lightweight(limit=limit, source=source)
    except Exception as exc:
        logger.exception("Failed to load recent papers")
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))


@router.get("/count")
async def get_papers_count(
    source: str | None = Query(None),
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить общее количество статей."""
    cached = _get_cached_count(source)
    if cached and not cached[1]:
        return {"total": cached[0], "cached": True, "stale": False}

    paper_service = PaperService(db)

    try:
        if source:
            from sqlalchemy import func, select

            from app.db.models.paper import Paper as PaperModel
            result = await db.execute(select(func.count()).where(PaperModel.source == source))
            count = result.scalar() or 0
        else:
            count = await paper_service.get_total_count()
    except (SQLAlchemyError, TimeoutError, OSError) as exc:
        if cached:
            logger.warning("papers/count timeout, returning stale cache: {}", exc)
            return {"total": cached[0], "cached": True, "stale": True}
        logger.error("papers/count failed without cache: {}", exc)
        raise HTTPException(status_code=503, detail="База данных временно недоступна")

    total = int(count)
    _set_cached_count(source, total)
    return {"total": total, "cached": False, "stale": False}


@router.get("/statuses", response_model=list[PaperProcessingStatusInfo])
async def get_paper_processing_statuses(
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Единый словарь статусов обработки для UI-фильтров."""
    paper_service = PaperService(db)
    try:
        observed = [key for key in await paper_service.list_processing_status_keys() if key not in TRANSLATION_STATUS_KEYS]
    except Exception as exc:
        logger.warning("Failed to load observed paper statuses: {}", exc)
        observed = []

    keys = sorted(
        (set(PROCESSING_STATUS_REGISTRY.keys()) - TRANSLATION_STATUS_KEYS) | set(observed),
        key=lambda key: (_status_info(key).label, key),
    )
    return [_status_info(key) for key in keys]


@router.get("/export.csv")
async def export_papers_csv(
    source: str | None = Query(None, description="Фильтр по источнику"),
    query: str | None = Query(None, description="Поиск по статьям"),
    date_from: date | None = Query(None, description="Дата публикации с"),
    date_to: date | None = Query(None, description="Дата публикации по"),
    processing_status: str | None = Query(None, description="Фильтр по статусу обработки"),
    translation_status: str | None = Query(None, description="Фильтр по статусу перевода"),
    full_text_only: bool = Query(False, description="Только записи с извлечённым полным текстом"),
    sort_by: Literal["id", "authors", "created_at", "publication_date", "relevance"] = Query("created_at"),
    sort_dir: Literal["asc", "desc"] = Query("desc"),
    max_rows: int = Query(default=10000, ge=1, le=50000),
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """CSV-экспорт всех найденных статей без загрузки full_text."""
    paper_service = PaperService(db)
    try:
        rows, _total = await paper_service.list_filtered_lightweight(
            limit=max_rows,
            offset=0,
            source=source,
            query=query,
            date_from=date_from,
            date_to=date_to,
            processing_status=processing_status,
            translation_status=translation_status,
            full_text_only=full_text_only,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except Exception as exc:
        logger.exception("Failed to export papers CSV")
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    return _papers_csv_response(rows)


@router.post("/parse")
async def start_parsing(
    query: str = Query(..., description="Поисковый запрос"),
    limit: int | None = Query(default=None, ge=1, le=5000, description="Макс. количество результатов"),
    source: str = Query(default="CORE", description="Источник"),
    pdf_mode: Literal["auto", "ai", "mypdf"] = Query(default="auto", description="Режим обработки PDF: auto, ai или mypdf"),
    _current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Запустить парсинг статей.

    Доступные источники берутся из parser_alpha реестра.
    """
    normalized_query = query.strip()
    if not normalized_query:
        raise HTTPException(status_code=400, detail="Поле query обязательно и не может быть пустым")

    parse_tasks = _get_parse_task_module()
    available_sources = parse_tasks.AVAILABLE_SOURCES
    if source not in available_sources:
        raise HTTPException(status_code=400, detail=f"Неподдерживаемый источник. Доступны: {', '.join(available_sources)}")

    parser_settings = await _get_parser_settings(db)
    if not parser_settings.get("enabled", True):
        raise HTTPException(status_code=409, detail="Парсинг временно отключён в технических настройках")
    if not _is_source_enabled(parser_settings, source):
        raise HTTPException(status_code=409, detail=f"Источник {source} отключён в технических настройках")
    effective_limit = _effective_parse_limit(limit, parser_settings, source)
    slot = _reserve_parallel_parse_slot(
        parser_settings=parser_settings,
        task_name="app.tasks.parse_tasks.parse_papers_task",
        source=source,
        query=normalized_query,
    )
    initial_count = await _count_papers_for_source(db, source)
    if not _record_parse_job(
        task_id=slot.task_id,
        query=normalized_query,
        source=source,
        initial_count=initial_count,
        celery_status={
            "task_id": slot.task_id,
            "status": "RESERVED",
            "state": "RESERVED",
            "name": "app.tasks.parse_tasks.parse_papers_task",
            "parse_admission_reserved": True,
        },
    ):
        release_parse_slot(slot.task_id)
        raise HTTPException(
            status_code=503,
            detail="Не удалось записать задачу парсинга в историю. Celery-задача не поставлена, слот освобождён.",
        )

    try:
        task = parse_papers_task.apply_async(
            kwargs={
                "query": normalized_query,
                "limit": effective_limit,
                "source": source,
                "pdf_mode": pdf_mode,
            },
            task_id=slot.task_id,
        )
    except Exception as exc:
        release_parse_slot(slot.task_id)
        _safe_patch_parse_job(
            slot.task_id,
            {
                "status": "failed",
                "celeryStatus": {
                    "task_id": slot.task_id,
                    "status": "PUBLISH_FAILED",
                    "state": "PUBLISH_FAILED",
                    "error": str(exc)[:1000],
                },
            },
        )
        logger.exception("Failed to publish parse task after slot reservation: {}", slot.task_id)
        raise

    _safe_patch_parse_job(
        task.id,
        {
            "status": "in_progress",
            "celeryStatus": {
                "task_id": task.id,
                "status": "PENDING",
                "state": "PENDING",
                "name": "app.tasks.parse_tasks.parse_papers_task",
                "parse_admission_reserved": True,
            },
        },
    )
    logger.info(f"Запущен парсинг: source={source}, query={normalized_query}, task_id={task.id}")

    return {
        "message": "Парсинг запущен",
        "task_id": task.id,
        "source": source,
        "query": normalized_query,
        "limit": effective_limit,
        "pdf_mode": pdf_mode,
        "parse_admission": get_parse_admission_snapshot(_max_parallel_parse_jobs(parser_settings)),
    }


@router.post("/parse-all")
async def start_parsing_all(
    limit_per_query: int | None = Query(default=None, ge=1, le=5000),
    source: str = Query(default="all", description="Источник (или all)"),
    query: str = Query(..., description="Пользовательский запрос для всех источников"),
    pdf_mode: Literal["auto", "ai", "mypdf"] = Query(default="auto", description="Режим обработки PDF: auto, ai или mypdf"),
    _current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Запустить парсинг по всем стандартным запросам.

    Источники: `AVAILABLE_SOURCES` и `all`.
    """
    parse_tasks = _get_parse_task_module()
    available_sources = parse_tasks.AVAILABLE_SOURCES
    parser_settings = await _get_parser_settings(db)
    if not parser_settings.get("enabled", True):
        raise HTTPException(status_code=409, detail="Парсинг временно отключён в технических настройках")

    enabled_sources = [s for s in available_sources if _is_source_enabled(parser_settings, s)]
    allowed_with_all = [*available_sources, "all"]
    if source not in allowed_with_all:
        raise HTTPException(status_code=400, detail=f"Неподдерживаемый источник. Доступны: {', '.join(allowed_with_all)}")
    if source != "all" and source not in enabled_sources:
        raise HTTPException(status_code=409, detail=f"Источник {source} отключён в технических настройках")
    if source == "all" and not enabled_sources:
        raise HTTPException(status_code=409, detail="Все источники отключены в технических настройках")

    normalized_query = query.strip()
    if not normalized_query:
        raise HTTPException(status_code=400, detail="Поле query обязательно и не может быть пустым")
    user_queries = [normalized_query]

    if source == "all":
        effective_limit = min(_effective_parse_limit(limit_per_query, parser_settings, src) for src in enabled_sources)
        task_proxy = parse_all_sources_task
        task_name = "app.tasks.parse_tasks.parse_all_sources_task"
        task_kwargs = {
            "limit_per_query": effective_limit,
            "queries": user_queries,
            "query": normalized_query or None,
            "sources": enabled_sources,
            "pdf_mode": pdf_mode,
        }
        source_list = enabled_sources
        slot_source = "all"
    elif source == "arXiv":
        effective_limit = _effective_parse_limit(limit_per_query, parser_settings, "arXiv")
        task_proxy = parse_multiple_queries_task
        task_name = "app.tasks.parse_tasks.parse_multiple_queries_task"
        task_kwargs = {
            "queries": user_queries or parse_tasks.ARXIV_SEARCH_QUERIES,
            "limit_per_query": effective_limit,
            "source": "arXiv",
            "pdf_mode": pdf_mode,
        }
        source_list = ["arXiv"]
        slot_source = "arXiv"
    elif source == "CORE":
        effective_limit = _effective_parse_limit(limit_per_query, parser_settings, "CORE")
        task_proxy = parse_multiple_queries_task
        task_name = "app.tasks.parse_tasks.parse_multiple_queries_task"
        task_kwargs = {
            "queries": user_queries or parse_tasks.DEFAULT_SEARCH_QUERIES,
            "limit_per_query": effective_limit,
            "source": "CORE",
            "pdf_mode": pdf_mode,
        }
        source_list = ["CORE"]
        slot_source = "CORE"
    else:
        effective_limit = _effective_parse_limit(limit_per_query, parser_settings, source)
        task_proxy = parse_multiple_queries_task
        task_name = "app.tasks.parse_tasks.parse_multiple_queries_task"
        task_kwargs = {
            "queries": user_queries or parse_tasks.DEFAULT_SEARCH_QUERIES,
            "limit_per_query": effective_limit,
            "source": source,
            "pdf_mode": pdf_mode,
        }
        source_list = [source]
        slot_source = source

    slot = _reserve_parallel_parse_slot(
        parser_settings=parser_settings,
        task_name=task_name,
        source=slot_source,
        query=normalized_query,
    )
    history_source = "all" if source == "all" else source_list[0]
    initial_count = await _count_papers_for_source(db, history_source)
    if not _record_parse_job(
        task_id=slot.task_id,
        query=normalized_query,
        source=history_source,
        initial_count=initial_count,
        celery_status={
            "task_id": slot.task_id,
            "status": "RESERVED",
            "state": "RESERVED",
            "name": task_name,
            "parse_admission_reserved": True,
        },
    ):
        release_parse_slot(slot.task_id)
        raise HTTPException(
            status_code=503,
            detail="Не удалось записать задачу парсинга в историю. Celery-задача не поставлена, слот освобождён.",
        )
    try:
        task = task_proxy.apply_async(kwargs=task_kwargs, task_id=slot.task_id)
    except Exception as exc:
        release_parse_slot(slot.task_id)
        _safe_patch_parse_job(
            slot.task_id,
            {
                "status": "failed",
                "celeryStatus": {
                    "task_id": slot.task_id,
                    "status": "PUBLISH_FAILED",
                    "state": "PUBLISH_FAILED",
                    "error": str(exc)[:1000],
                },
            },
        )
        logger.exception("Failed to publish parse-all task after slot reservation: {}", slot.task_id)
        raise


    logger.info(
        "Запущен массовый парсинг: sources={}, query='{}', limit_per_query={}, task_id={}",
        source_list,
        normalized_query or "<default_templates>",
        effective_limit,
        task.id,
    )
    _safe_patch_parse_job(
        task.id,
        {
            "status": "in_progress",
            "celeryStatus": {
                "task_id": task.id,
                "status": "PENDING",
                "state": "PENDING",
                "name": task_name,
                "parse_admission_reserved": True,
            },
        },
    )

    return {
        "message": "Массовый парсинг запущен",
        "task_id": task.id,
        "sources": source_list,
        "limit_per_query": effective_limit,
        "query": normalized_query,
        "pdf_mode": pdf_mode,
        "parse_admission": get_parse_admission_snapshot(_max_parallel_parse_jobs(parser_settings)),
    }


@router.get("/id/{paper_id}", response_model=Paper)
async def get_paper(
    paper_id: int,
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить статью по ID."""
    paper_service = PaperService(db)
    try:
        paper = await paper_service.get_by_id(paper_id)
    except Exception as exc:
        logger.exception("Failed to load paper {}", paper_id)
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    return paper


@router.get("/id/{paper_id}/details", response_model=PaperDetailResponse)
async def get_paper_details(
    paper_id: int,
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Полная карточка статьи для страницы просмотра.

    Список /papers остаётся лёгким, но при открытии конкретной статьи UI должен
    получить весь Paper payload и связанные content-parts одним запросом.
    """
    paper_service = PaperService(db)
    try:
        paper = await paper_service.get_by_id(paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Статья не найдена")
        content_parts = await PaperContentPartService(db).list_parts(paper_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to load full paper details {}", paper_id)
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    return PaperDetailResponse(
        paper=paper,
        content_parts=content_parts,
        status_info=_status_info(paper.processing_status),
        processing_quality=_paper_processing_quality(content_parts),
        pipeline_status=_build_paper_pipeline_status(paper, content_parts),
    )


@router.get("/id/{paper_id}/content-parts", response_model=list[PaperContentPart])
async def get_paper_content_parts(
    paper_id: int,
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить сохранённые части PDF/raw text + Qwen Markdown по статье."""
    paper = await PaperService(db).get_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return await PaperContentPartService(db).list_parts(paper_id)


@router.post("/id/{paper_id}/translate", response_model=PaperTranslateResponse)
async def translate_paper_markdown_parts(
    paper_id: int,
    payload: PaperTranslateRequest | None = None,
    _current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Поставить перевод всех отображаемых Markdown-частей статьи в Qwen-очередь."""
    request = payload or PaperTranslateRequest()
    target_code = (request.target_language_code or "ru").strip().lower()
    target_name = (request.target_language_name or "").strip() or ("Русский" if target_code == "ru" else target_code)
    if request.source_layer != "markdown":
        raise HTTPException(status_code=400, detail="Сейчас поддерживается перевод только слоя markdown")

    paper_service = PaperService(db)
    paper = await paper_service.get_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    part_service = PaperContentPartService(db)
    parts = await part_service.list_parts(paper_id)
    if not parts and (paper.full_text or "").strip():
        parts = await part_service.ensure_parts_from_text(paper_id, paper.full_text or "", source="legacy_full_text")
    translatable_parts = [part for part in parts if ((part.markdown_text or "").strip() or ((part.source or "") == "legacy_full_text" and (part.raw_text or "").strip()))]
    if not translatable_parts:
        raise HTTPException(
            status_code=409,
            detail="Нет сохранённого Markdown-текста для перевода. Сначала выполните оцифровку файла через Qwen.",
        )

    ready_existing = 0
    if not request.force:
        for part in translatable_parts:
            for translation in getattr(part, "translations", []) or []:
                if (translation.language_code or "").strip().lower() == target_code and translation.status == "ready" and translation.translated_markdown_text:
                    ready_existing += 1
                    break
        if ready_existing == len(translatable_parts):
            available = list(dict.fromkeys([*(paper.available_language_codes or []), target_code]))
            await paper_service.update_paper(
                paper_id,
                available_language_codes=available,
                translation_status="translation_ready",
                translation_error=None,
            )
            return PaperTranslateResponse(
                paper_id=paper_id,
                task_id=paper.translation_task_id or "already_ready",
                status="already_ready",
                target_language_code=target_code,
                target_language_name=target_name,
                parts_total=len(translatable_parts),
                parts_ready=ready_existing,
            )

    task = _get_translate_markdown_parts_task().apply_async(
        args=[paper_id, target_code, target_name, request.force],
        queue=settings.QWEN_QUEUE_NAME,
    )
    await paper_service.update_paper(
        paper_id,
        translation_status=f"translating_article:0/{len(translatable_parts)}",
        translation_task_id=task.id,
        translation_error=None,
    )
    return PaperTranslateResponse(
        paper_id=paper_id,
        task_id=task.id,
        status="queued",
        target_language_code=target_code,
        target_language_name=target_name,
        parts_total=len(translatable_parts),
        parts_ready=ready_existing,
    )


@router.post("/id/{paper_id}/content-parts/{part_id}/regenerate", response_model=PaperContentPartRegenerateResponse)
async def regenerate_paper_content_part(
    paper_id: int,
    part_id: int,
    mode: Literal["text", "image", "auto", "mypdf", "ai"] = Query(
        "text",
        description="Режим перегенерации: text — из сохранённого текста, image/ai — по изображению PDF, auto/mypdf — повторное извлечение текста выбранных страниц",
    ),
    _current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Перегенерировать Markdown только для одной сохранённой части."""
    paper = await PaperService(db).get_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    part_service = PaperContentPartService(db)
    part = await part_service.get_part(paper_id, part_id)
    if not part:
        raise HTTPException(status_code=404, detail="Часть статьи не найдена")
    if mode == "text" and not (part.raw_text or "").strip():
        raise HTTPException(status_code=400, detail="У части нет сохранённого исходного текста")
    if mode in {"image", "ai", "auto", "mypdf"} and not (paper.pdf_local_path or "").strip():
        raise HTTPException(status_code=400, detail="Для перегенерации страницы из PDF нужен локально сохранённый PDF")

    qwen_settings = await SystemSettingsService(db).get_qwen_settings()
    if not qwen_settings.get("markdown_enabled", True):
        raise HTTPException(status_code=409, detail="Markdown-оцифровка Qwen выключена в технических настройках")

    task = _get_regenerate_markdown_part_task().apply_async(
        args=[paper_id, part_id, mode],
        queue=settings.QWEN_QUEUE_NAME,
    )
    total_parts = len(await part_service.list_parts(paper_id)) or max(1, part.part_index)
    await PaperService(db).update_paper(
        paper_id,
        processing_status=f"digitizing_file:{part.part_index}/{max(1, total_parts)}",
        content_task_id=task.id,
        processing_error=None,
    )
    return PaperContentPartRegenerateResponse(
        paper_id=paper_id,
        part_id=part_id,
        task_id=task.id,
        status="queued",
        page_start=part.page_start,
        page_end=part.page_end,
        mode=mode,
    )


@router.post("/id/{paper_id}/markdown-pages/regenerate", response_model=PaperContentPartRegenerateResponse)
async def regenerate_paper_markdown_pages(
    paper_id: int,
    page_start: int = Query(..., ge=1),
    page_end: int = Query(..., ge=1),
    mode: Literal["text", "image", "auto", "mypdf", "ai"] = Query(
        "text",
        description="Режим перегенерации: text — из сохранённого текста, image/ai — по изображению PDF, auto/mypdf — повторное извлечение текста выбранных страниц",
    ),
    _current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Совместимый endpoint: найти часть по диапазону страниц и перегенерировать её."""
    if page_end < page_start:
        raise HTTPException(status_code=400, detail="page_end должен быть >= page_start")

    paper = await PaperService(db).get_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    part_service = PaperContentPartService(db)
    part = await part_service.get_part_by_pages(paper_id, page_start, page_end)
    if not part:
        raise HTTPException(status_code=404, detail="Часть с указанными страницами не найдена")
    if mode == "text" and not (part.raw_text or "").strip():
        raise HTTPException(status_code=400, detail="У части нет сохранённого исходного текста")
    if mode in {"image", "ai", "auto", "mypdf"} and not (paper.pdf_local_path or "").strip():
        raise HTTPException(status_code=400, detail="Для перегенерации страницы из PDF нужен локально сохранённый PDF")

    qwen_settings = await SystemSettingsService(db).get_qwen_settings()
    if not qwen_settings.get("markdown_enabled", True):
        raise HTTPException(status_code=409, detail="Markdown-оцифровка Qwen выключена в технических настройках")

    task = _get_regenerate_markdown_part_task().apply_async(
        args=[paper_id, part.id, mode],
        queue=settings.QWEN_QUEUE_NAME,
    )
    total_parts = len(await part_service.list_parts(paper_id)) or max(1, part.part_index)
    await PaperService(db).update_paper(
        paper_id,
        processing_status=f"digitizing_file:{part.part_index}/{max(1, total_parts)}",
        content_task_id=task.id,
        processing_error=None,
    )
    return PaperContentPartRegenerateResponse(
        paper_id=paper_id,
        part_id=part.id,
        task_id=task.id,
        status="queued",
        page_start=part.page_start,
        page_end=part.page_end,
        mode=mode,
    )


@router.get("/id/{paper_id}/pdf")
async def get_paper_pdf(
    paper_id: int,
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить PDF статьи: локальный файл или редирект на внешний URL."""
    try:
        paper = await PaperService(db).get_by_id(paper_id)
    except Exception as exc:
        logger.exception("Failed to load paper PDF metadata {}", paper_id)
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    if paper.pdf_local_path:
        path = Path(paper.pdf_local_path)
        if path.exists() and path.is_file():
            return FileResponse(
                path=path,
                media_type="application/pdf",
                filename=f"paper_{paper_id}.pdf",
                content_disposition_type="inline",
            )

    if paper.pdf_url:
        raise HTTPException(
            status_code=409,
            detail=(
                "PDF есть только как внешняя ссылка и ещё не сохранён локально. "
                "Запустите обработку документа, чтобы скачать PDF через Celery."
            ),
        )

    raise HTTPException(status_code=404, detail="PDF не найден")


@router.post("/id/{paper_id}/reprocess")
async def reprocess_paper_content(
    paper_id: int,
    pdf_mode: Literal["auto", "ai", "mypdf"] = Query("auto", description="Режим обработки PDF: auto — обычные алгоритмы, ai — по изображениям страниц, mypdf — быстрый текстовый слой без OCR/таблиц"),
    _current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Поставить статью в очередь на повторную PDF+AI обработку."""
    paper_service = PaperService(db)
    try:
        paper = await paper_service.get_by_id(paper_id)
    except Exception as exc:
        logger.exception("Failed to load paper for reprocess {}", paper_id)
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    process_paper_content_task = _get_content_task()
    task = process_paper_content_task.apply_async(
        args=[paper_id, pdf_mode],
        queue=settings.CONTENT_QUEUE_NAME,
    )
    await paper_service.update_paper(
        paper_id,
        processing_status="queued_for_content_processing",
        content_task_id=task.id,
        processing_error=None,
    )
    return {"paper_id": paper_id, "task_id": task.id, "status": "queued", "pdf_mode": pdf_mode, "preserved_existing_content": True}


@router.post("/reprocess-all")
async def reprocess_all_papers(
    limit: int = Query(default=500, ge=1, le=5000),
    source: str | None = Query(default=None, description="Фильтр по источнику"),
    pdf_mode: Literal["auto", "ai", "mypdf"] = Query("auto", description="Режим обработки PDF: auto, ai или mypdf"),
    _current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Поставить в очередь постобработку набора существующих статей."""
    paper_service = PaperService(db)
    try:
        paper_ids = await paper_service.list_ids_for_reprocess(limit=limit, source=source)
    except Exception as exc:
        logger.exception("Failed to load paper ids for reprocess-all")
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    process_paper_content_task = _get_content_task()
    queued = 0
    task_ids: list[str] = []
    for paper_id in paper_ids:
        task = process_paper_content_task.apply_async(
            args=[paper_id, pdf_mode],
            queue=settings.CONTENT_QUEUE_NAME,
        )
        await paper_service.update_paper(
            paper_id,
            processing_status="queued_for_content_processing",
            content_task_id=task.id,
            processing_error=None,
        )
        task_ids.append(task.id)
        queued += 1

    return {"queued": queued, "task_ids": task_ids, "pdf_mode": pdf_mode, "preserved_existing_content": True}


@router.delete("/id/{paper_id}")
async def delete_paper(
    paper_id: int,
    _current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Удалить статью."""
    paper_service = PaperService(db)
    try:
        deleted = await paper_service.delete_paper(paper_id)
    except Exception as exc:
        logger.exception("Failed to delete paper {}", paper_id)
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    if not deleted:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    return {"message": "Статья удалена"}
