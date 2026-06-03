from __future__ import annotations

import re
from typing import Any

ARTICLE_TRANSLATION_PROMPT_VERSION = "article_markdown_translation_v4_quality_gate"
ARTICLE_TRANSLATION_MAX_ATTEMPTS = 3
ARTICLE_TRANSLATION_RETRY_BASE_DELAY_SECONDS = 6.0

TRANSIENT_ARTICLE_TRANSLATION_ERRORS = {
    "qwen_oss_connect_timeout",
    "qwen_service_http_error",
    "qwen_file_message_timeout",
    "qwen_file_upload_timeout",
    "qwen_file_parse_timeout",
    "qwen_file_parse_status_failed",
    "qwen_file_not_visible",
    "qwen_rate_limited",
    "qwen_oss_put_failed",
    "qwen_file_upload_failed",
    "qwen_file_message_failed",
}

TRANSLATION_LANGUAGE_NAMES: dict[str, str] = {
    "ru": "Русский",
    "en": "English",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
    "zh": "中文",
}

TAG_ONLY_FORMULA_RE = re.compile(r"\$\$\s*\\tag\{([^}]{1,60})\}\s*\$\$", re.IGNORECASE | re.DOTALL)
LATEX_TAG_RE = re.compile(r"\\tag\{([^}]{1,60})\}", re.IGNORECASE)
EMPTY_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s*$")


def translation_language_name(code: str, name: str | None = None) -> str:
    normalized = (code or "ru").strip().lower()
    return (name or "").strip() or TRANSLATION_LANGUAGE_NAMES.get(normalized, normalized)


def is_transient_article_translation_error(error_text: str) -> bool:
    """Return True for Qwen upload/service errors that should be retried per page."""
    lowered = str(error_text or "").strip().lower()
    if not lowered:
        return False
    if any(code in lowered for code in TRANSIENT_ARTICLE_TRANSLATION_ERRORS):
        return True
    transient_markers = (
        "timeout",
        "timed out",
        "temporarily unavailable",
        "temporary failure",
        "connection reset",
        "connection aborted",
        "connect error",
        "read error",
        "network",
        "bad gateway",
        "gateway timeout",
        "service unavailable",
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
    )
    return any(marker in lowered for marker in transient_markers)


def translation_retry_delay_seconds(attempt: int) -> float:
    """Small exponential backoff between page translation attempts."""
    return min(30.0, ARTICLE_TRANSLATION_RETRY_BASE_DELAY_SECONDS * (2 ** max(0, attempt - 1)))


def extract_qwen_error_response(text: str) -> str | None:
    """Detect cases where qwen_service returned an error code in response text."""
    value = str(text or "").strip()
    if not value:
        return None
    lowered = value.lower()
    if any(code in lowered for code in TRANSIENT_ARTICLE_TRANSLATION_ERRORS):
        return value[:1000]
    if "qwen_token_expired" in lowered:
        return "qwen_token_expired"

    compact = re.sub(r"[\s`*_#>:\-—]+", "", lowered)
    if compact.startswith("qwen_") and len(value) <= 400:
        return value[:1000]
    error_markers = (
        "failed to upload",
        "cannot connect",
        "service unavailable",
        "gateway timeout",
        "bad gateway",
        "http error",
        "network error",
    )
    if len(value) <= 800 and any(marker in lowered for marker in error_markers):
        return value[:1000]
    return None


def format_translation_retry_error(error_text: str, attempt: int, max_attempts: int) -> str:
    clean = str(error_text or "temporary_qwen_error").strip() or "temporary_qwen_error"
    if is_retryable_translation_quality_error(clean):
        return f"Ошибка качества перевода Qwen: {clean}. Повторная попытка {attempt}/{max_attempts}."[:4000]
    return f"Временная ошибка Qwen: {clean}. Повторная попытка {attempt}/{max_attempts}."[:4000]


def format_translation_final_error(error_text: str, max_attempts: int) -> str:
    clean = str(error_text or "temporary_qwen_error").strip() or "temporary_qwen_error"
    if is_retryable_translation_quality_error(clean):
        return f"Qwen вернул подозрительный перевод после {max_attempts} попыток: {clean}"[:4000]
    return f"Временная ошибка Qwen не устранена после {max_attempts} попыток: {clean}"[:4000]


def unique_preserve_order(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if clean and clean not in output:
            output.append(clean)
    return output


def formula_tags(text: str) -> list[str]:
    return unique_preserve_order([match.strip() for match in LATEX_TAG_RE.findall(text or "")])


def tag_only_formula_tags(text: str) -> list[str]:
    return unique_preserve_order([match.strip() for match in TAG_ONLY_FORMULA_RE.findall(text or "")])


def duplicate_formula_tags(text: str) -> list[str]:
    tags = [match.strip() for match in LATEX_TAG_RE.findall(text or "") if str(match or "").strip()]
    seen: set[str] = set()
    dupes: list[str] = []
    for tag in tags:
        if tag in seen and tag not in dupes:
            dupes.append(tag)
        seen.add(tag)
    return dupes


def markdown_translation_source_quality(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    tag_only = tag_only_formula_tags(value)
    duplicates = duplicate_formula_tags(value)
    empty_heading_count = len(EMPTY_HEADING_RE.findall(value))
    warnings: list[str] = []
    if duplicates:
        warnings.append("duplicate_formula_tags:" + ",".join(duplicates[:20]))
    if empty_heading_count:
        warnings.append(f"empty_headings:{empty_heading_count}")
    if not value:
        return {"ok": False, "error": "source_markdown_empty", "tag_only_formula_tags": [], "warnings": warnings}
    if tag_only:
        return {
            "ok": False,
            "error": "source_markdown_tag_only_formulas:" + ",".join(tag_only[:20]),
            "tag_only_formula_tags": tag_only,
            "warnings": warnings,
        }
    return {"ok": True, "error": None, "tag_only_formula_tags": [], "warnings": warnings}


def translation_output_quality_error(source_markdown: str, translated_markdown: str) -> str | None:
    translated = str(translated_markdown or "").strip()
    if not translated:
        return "empty_translation"
    source_tags = set(formula_tags(source_markdown))
    translated_tags = set(formula_tags(translated))
    extra_tags = sorted(translated_tags - source_tags)
    if extra_tags:
        return "translation_extra_formula_tags:" + ",".join(extra_tags[:20])
    tag_only = tag_only_formula_tags(translated)
    if tag_only:
        return "translation_tag_only_formulas:" + ",".join(tag_only[:20])
    return None


def is_retryable_translation_quality_error(error_text: str) -> bool:
    lowered = str(error_text or "").strip().lower()
    return lowered.startswith((
        "translation_extra_formula_tags",
        "translation_tag_only_formulas",
        "empty_translation",
    ))
