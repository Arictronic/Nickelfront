"""Runtime configuration helpers for the public PDF parser API.

The parser is called from several process roots in Nickelfront: FastAPI/Celery
(``app.services``), RAG/parser_alpha (often ``backend.app.services``) and
standalone Windows audit scripts.  Keep env parsing and option aliases here so
callers can share the same stable public options without depending on ad-hoc
``PYTHONPATH`` or duplicated defaults.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

TRUTHY = {"1", "true", "yes", "y", "on"}
FALSY = {"0", "false", "no", "n", "off"}

CANONICAL_ENV_PREFIX = "NICKELFRONT_PDF_PARSER_"
LEGACY_ENV_PREFIX = "PDF_PARSER_"



DEFAULT_PARSER_OPTIONS: dict[str, Any] = {
    "parser_mode": "auto",
    "extraction_mode": "auto",
    "extraction_strategy": "auto",
    "force_strategy": "",
    "detect_columns": True,
    "extract_tables": True,
    "remove_headers_footers": True,
    "merge_hyphenated_words": True,
    "normalize_math": True,
    "normalize_cid_glyphs": True,
    "normalize_private_use_glyphs": True,
    "detect_footnotes": True,
    "filter_watermarks": True,
    "mark_formula_candidates": True,
    "drop_graph_axis_from_body": True,
    "drop_arxiv_footer_from_body": True,
    "line_type_metadata": True,
    "repair_cross_page_continuations": False,
    "document_reference_context": True,
    "caption_continuation_blocks": True,
    "emit_content_blocks": True,
    "retype_content_blocks_after_cleanup": True,
    "rebuild_content_blocks_from_final_text": True,
    "line_noise_pretyping_enabled": False,
    "max_content_blocks_per_page": 500,
    "typing_heading_max_words": 12,
    "typing_heading_max_sentence_punct_density": 0.015,
    "typing_heading_max_operator_density": 0.03,
    "typing_formula_prose_word_count": 26,
    "typing_formula_low_operator_density": 0.045,
    "typing_low_confidence_threshold": 0.52,
    "typing_warning_confidence_threshold": 0.62,
    "typing_conflict_margin_unknown": 0.075,
    "final_content_blocks_sync_fallback_threshold": 0.58,
    "final_content_blocks_sync_fallback_len_threshold": 0.35,
    "content_blocks_mode": "final",
    "domain_profile": "generic",
    "ocr_enabled": True,
    "ocr_mode": "auto",
    "ocr_control_mode": "auto",
    "ocr_engine": "auto",
    "ocr_fallback_engines": ["tesseract"],
    "ocr_force": False,
    "ocr_skip": False,
    "ocr_pages": "",
    "ocr_only_pages": "",
    "ocr_dpi": 220,
    "ocr_languages": "eng+rus",
    "ocr_merge_strategy": "replace_low_quality",
    "ocr_min_quality_score": 0.45,
    "ocr_min_confidence": 0.55,
    "ocr_min_text_chars": 180,
    "ocr_min_words": 35,
    "ocr_min_text_density": 0.35,
    "ocr_broken_encoding_noise_ratio": 0.02,
    "ocr_allow_paddle": False,
    "ocr_allow_ocrmypdf_page": False,
    "ocr_emit_lines": False,
    "ocr_debug": False,
    "ocr_surya_experimental": False,
    "ocr_create_searchable_pdf": False,
    "ocr_preserve_original_text": True,
    "ai_enabled": False,
    "ai_mode": "off",
    "ai_provider": "",
    "ai_model": "",
    "ai_endpoint": "",
    "ai_render_dpi": 220,
    "ai_page_image_format": "png",
    "ai_timeout_sec": 120,
    "ai_preserve_original_text": True,
    "ai_fallback_to_auto": True,
    "ai_delete_temp_images": True,
    "min_text_chars": 300,
    "max_page_chars": 60000,
    "table_settings": {},
}



ENV_OPTION_NAMES: dict[str, str] = {
    "PARSER_MODE": "parser_mode",
    "MODE": "parser_mode",
    "EXTRACTION_MODE": "extraction_mode",
    "EXTRACTION_STRATEGY": "extraction_strategy",
    "FORCE_STRATEGY": "force_strategy",
    "DETECT_COLUMNS": "detect_columns",
    "EXTRACT_TABLES": "extract_tables",
    "REMOVE_HEADERS_FOOTERS": "remove_headers_footers",
    "MERGE_HYPHENATED_WORDS": "merge_hyphenated_words",
    "NORMALIZE_MATH": "normalize_math",
    "NORMALIZE_CID_GLYPHS": "normalize_cid_glyphs",
    "NORMALIZE_PRIVATE_USE_GLYPHS": "normalize_private_use_glyphs",
    "DETECT_FOOTNOTES": "detect_footnotes",
    "FILTER_WATERMARKS": "filter_watermarks",
    "MARK_FORMULA_CANDIDATES": "mark_formula_candidates",
    "DROP_GRAPH_AXIS_FROM_BODY": "drop_graph_axis_from_body",
    "DROP_ARXIV_FOOTER_FROM_BODY": "drop_arxiv_footer_from_body",
    "LINE_TYPE_METADATA": "line_type_metadata",
    "REPAIR_CROSS_PAGE_CONTINUATIONS": "repair_cross_page_continuations",
    "DOCUMENT_REFERENCE_CONTEXT": "document_reference_context",
    "CAPTION_CONTINUATION_BLOCKS": "caption_continuation_blocks",
    "EMIT_CONTENT_BLOCKS": "emit_content_blocks",
    "RETYPE_CONTENT_BLOCKS_AFTER_CLEANUP": "retype_content_blocks_after_cleanup",
    "REBUILD_CONTENT_BLOCKS_FROM_FINAL_TEXT": "rebuild_content_blocks_from_final_text",
    "LINE_NOISE_PRETYPING_ENABLED": "line_noise_pretyping_enabled",
    "MAX_CONTENT_BLOCKS_PER_PAGE": "max_content_blocks_per_page",
    "TYPING_HEADING_MAX_WORDS": "typing_heading_max_words",
    "TYPING_HEADING_MAX_SENTENCE_PUNCT_DENSITY": "typing_heading_max_sentence_punct_density",
    "TYPING_HEADING_MAX_OPERATOR_DENSITY": "typing_heading_max_operator_density",
    "TYPING_FORMULA_PROSE_WORD_COUNT": "typing_formula_prose_word_count",
    "TYPING_FORMULA_LOW_OPERATOR_DENSITY": "typing_formula_low_operator_density",
    "TYPING_LOW_CONFIDENCE_THRESHOLD": "typing_low_confidence_threshold",
    "TYPING_WARNING_CONFIDENCE_THRESHOLD": "typing_warning_confidence_threshold",
    "TYPING_CONFLICT_MARGIN_UNKNOWN": "typing_conflict_margin_unknown",
    "FINAL_CONTENT_BLOCKS_SYNC_FALLBACK_THRESHOLD": "final_content_blocks_sync_fallback_threshold",
    "FINAL_CONTENT_BLOCKS_SYNC_FALLBACK_LEN_THRESHOLD": "final_content_blocks_sync_fallback_len_threshold",
    "CONTENT_BLOCKS_MODE": "content_blocks_mode",
    "DOMAIN_PROFILE": "domain_profile",
    "PARSER_DOMAIN_PROFILE": "parser_domain_profile",
    "PARSER_PROFILE": "parser_profile",
    "PROFILE": "domain_profile",
    "OCR_ENABLED": "ocr_enabled",
    "OCR": "ocr_enabled",
    "OCR_MODE": "ocr_mode",
    "OCR_CONTROL_MODE": "ocr_control_mode",
    "OCR_ENGINE": "ocr_engine",
    "OCR_FALLBACK_ENGINES": "ocr_fallback_engines",
    "OCR_FORCE": "ocr_force",
    "OCR_SKIP": "ocr_skip",
    "OCR_PAGES": "ocr_pages",
    "OCR_ONLY_PAGES": "ocr_only_pages",
    "OCR_DPI": "ocr_dpi",
    "OCR_LANGUAGES": "ocr_languages",
    "OCR_MERGE_STRATEGY": "ocr_merge_strategy",
    "OCR_MIN_QUALITY_SCORE": "ocr_min_quality_score",
    "OCR_MIN_CONFIDENCE": "ocr_min_confidence",
    "OCR_MIN_TEXT_CHARS": "ocr_min_text_chars",
    "OCR_MIN_WORDS": "ocr_min_words",
    "OCR_MIN_TEXT_DENSITY": "ocr_min_text_density",
    "OCR_BROKEN_ENCODING_NOISE_RATIO": "ocr_broken_encoding_noise_ratio",
    "OCR_ALLOW_PADDLE": "ocr_allow_paddle",
    "OCR_ALLOW_OCRMYPDF_PAGE": "ocr_allow_ocrmypdf_page",
    "OCR_EMIT_LINES": "ocr_emit_lines",
    "OCR_DEBUG": "ocr_debug",
    "OCR_SURYA_EXPERIMENTAL": "ocr_surya_experimental",
    "OCR_CREATE_SEARCHABLE_PDF": "ocr_create_searchable_pdf",
    "OCR_PRESERVE_ORIGINAL_TEXT": "ocr_preserve_original_text",
    "AI_ENABLED": "ai_enabled",
    "AI_MODE": "ai_mode",
    "AI_PROVIDER": "ai_provider",
    "AI_MODEL": "ai_model",
    "AI_ENDPOINT": "ai_endpoint",
    "AI_RENDER_DPI": "ai_render_dpi",
    "AI_PAGE_IMAGE_FORMAT": "ai_page_image_format",
    "AI_TIMEOUT_SEC": "ai_timeout_sec",
    "AI_PRESERVE_ORIGINAL_TEXT": "ai_preserve_original_text",
    "AI_FALLBACK_TO_AUTO": "ai_fallback_to_auto",
    "AI_DELETE_TEMP_IMAGES": "ai_delete_temp_images",
    "MIN_TEXT_CHARS": "min_text_chars",
    "MAX_PAGE_CHARS": "max_page_chars",
}

BOOL_OPTIONS = {
    "detect_columns",
    "extract_tables",
    "remove_headers_footers",
    "merge_hyphenated_words",
    "normalize_math",
    "normalize_cid_glyphs",
    "normalize_private_use_glyphs",
    "detect_footnotes",
    "filter_watermarks",
    "mark_formula_candidates",
    "drop_graph_axis_from_body",
    "drop_arxiv_footer_from_body",
    "line_type_metadata",
    "repair_cross_page_continuations",
    "document_reference_context",
    "caption_continuation_blocks",
    "emit_content_blocks",
    "retype_content_blocks_after_cleanup",
    "rebuild_content_blocks_from_final_text",
    "line_noise_pretyping_enabled",
    "ocr_enabled",
    "ocr_force",
    "ocr_skip",
    "ocr_allow_paddle",
    "ocr_allow_ocrmypdf_page",
    "ocr_emit_lines",
    "ocr_debug",
    "ocr_surya_experimental",
    "ocr_create_searchable_pdf",
    "ocr_preserve_original_text",
    "ai_enabled",
    "ai_preserve_original_text",
    "ai_fallback_to_auto",
    "ai_delete_temp_images",
}

INT_OPTIONS = {
    "max_content_blocks_per_page",
    "typing_heading_max_words",
    "typing_formula_prose_word_count",
    "ocr_dpi",
    "ocr_min_text_chars",
    "ocr_min_words",
    "ai_render_dpi",
    "ai_timeout_sec",
    "min_text_chars",
    "max_page_chars",
}
FLOAT_OPTIONS = {
    "ocr_min_quality_score",
    "ocr_min_confidence",
    "ocr_min_text_density",
    "ocr_broken_encoding_noise_ratio",
    "typing_heading_max_sentence_punct_density",
    "typing_heading_max_operator_density",
    "typing_formula_low_operator_density",
    "typing_low_confidence_threshold",
    "typing_warning_confidence_threshold",
    "typing_conflict_margin_unknown",
    "final_content_blocks_sync_fallback_threshold",
    "final_content_blocks_sync_fallback_len_threshold",
}
LIST_OPTIONS = {"ocr_fallback_engines"}


def _coerce_env_value(option_name: str, raw_value: str) -> Any:
    value = str(raw_value).strip()
    if option_name in BOOL_OPTIONS:
        lowered = value.lower()
        if lowered in TRUTHY:
            return True
        if lowered in FALSY:
            return False
        return value
    if option_name in INT_OPTIONS:
        try:
            return int(value)
        except ValueError:
            return value
    if option_name in FLOAT_OPTIONS:
        try:
            return float(value)
        except ValueError:
            return value
    if option_name in LIST_OPTIONS:
        return [item.strip().lower() for item in value.split(",") if item.strip()]
    return value


def parser_env_options(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Read parser defaults from environment variables.

    Supported canonical form: ``NICKELFRONT_PDF_PARSER_<OPTION>``.
    Supported legacy form: ``PDF_PARSER_<OPTION>``.
    """

    env = environ or os.environ
    options: dict[str, Any] = {}
    for env_name, option_name in ENV_OPTION_NAMES.items():
        raw_value: str | None = None
        canonical = f"{CANONICAL_ENV_PREFIX}{env_name}"
        legacy = f"{LEGACY_ENV_PREFIX}{env_name}"
        if canonical in env:
            raw_value = env[canonical]
        elif legacy in env:
            raw_value = env[legacy]
        if raw_value is not None:
            options[option_name] = _coerce_env_value(option_name, raw_value)
    return options


def merge_parser_options(*sources: Mapping[str, Any] | None, include_defaults: bool = False) -> dict[str, Any]:
    """Merge parser option dictionaries while dropping ``None`` values."""

    merged: dict[str, Any] = dict(DEFAULT_PARSER_OPTIONS) if include_defaults else {}
    for source in sources:
        if not source:
            continue
        for key, value in source.items():
            if value is not None:
                merged[str(key)] = value
    return merged


def normalize_parser_options(options: Mapping[str, Any] | None = None, *, default_options: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Normalize public parser options without exposing parser internals.

    Public parser modes are ``auto`` and ``ai``.  ``simple``/``layout``/
    ``columns``/``ocr`` remain internal strategies or legacy/debug overrides.
    The implementation delegates to ``PDFParser._normalize_options`` so API,
    Celery, RAG and audit scripts all share the exact same contract.
    """

    from .pdf_content_parser import PDFParser

    return PDFParser(default_options=dict(default_options or {}))._normalize_options(dict(options or {}))


__all__ = [
    "CANONICAL_ENV_PREFIX",
    "DEFAULT_PARSER_OPTIONS",
    "ENV_OPTION_NAMES",
    "LEGACY_ENV_PREFIX",
    "merge_parser_options",
    "normalize_parser_options",
    "parser_env_options",
]
