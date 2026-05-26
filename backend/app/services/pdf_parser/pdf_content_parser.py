"""Primary PDF content parser facade.

``PDFParser`` keeps the public API that the backend, Celery tasks, audit scripts
and ``parser_alpha`` already use. Heavy implementation details live in small
mixin modules in this package.
"""

from __future__ import annotations

import io
import logging
import math
import re
import unicodedata
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .ai import AIPageRecognitionService
from .compat import Document, RecursiveCharacterTextSplitter
from .config import DEFAULT_PARSER_OPTIONS, merge_parser_options, parser_env_options
from .constants import *
from .models import PdfExtractionError, PdfPageExtraction

logger = logging.getLogger(__name__)

from .content_blocks import PDFContentBlockMixin
from .document_context import PDFDocumentContextMixin
from .documents import PDFDocumentMixin
from .layout import PDFLayoutMixin
from .ocr import OCRService
from .quality import PDFQualityMixin
from .tables_ocr import PDFTablesOcrMixin
from .text_cleaning import PDFTextCleaningMixin
from .utils import PDFParserUtilsMixin


class PDFParser(
    PDFDocumentMixin,
    PDFContentBlockMixin,
    PDFDocumentContextMixin,
    PDFLayoutMixin,
    PDFQualityMixin,
    PDFTablesOcrMixin,
    PDFTextCleaningMixin,
    PDFParserUtilsMixin,
):
    """
    Универсальный парсер PDF-документов.

    Поддерживает:
    - page-level extraction;
    - auto public mode with internal simple/layout/columns/ocr/ai strategies;
    - table extraction в Markdown;
    - optional OCR fallback, если установлены PyMuPDF + pytesseract;
    - quality score/warnings для каждой страницы;
    - очистку колонтитулов и переносов.
    """

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        default_options: dict[str, Any] | None = None,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.default_options = merge_parser_options(
            DEFAULT_PARSER_OPTIONS,
            parser_env_options(),
            default_options or {},
        )
        self._ocr_service = OCRService()
        self._ai_service = AIPageRecognitionService()
        self._text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        logger.info(
            "Инициализация PDFParser: chunk_size=%s, chunk_overlap=%s, mode=%s, profile=%s",
            chunk_size,
            chunk_overlap,
            self.default_options.get("extraction_mode"),
            self.default_options.get("domain_profile"),
        )

    def extract_pages_from_file(self, file_path: str, options: dict[str, Any] | None = None) -> list[PdfPageExtraction]:
        """Извлечь PDF постранично с диагностикой."""
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise FileNotFoundError(f"Файл не найден: {file_path_obj}")
        return self.extract_pages_from_bytes(file_path_obj.read_bytes(), options=options)

    def extract_pages_from_bytes(self, file_bytes: bytes, options: dict[str, Any] | None = None) -> list[PdfPageExtraction]:
        """Извлечь PDF постранично из bytes."""
        import pdfplumber

        opts = self._normalize_options(options)
        if hasattr(self._ai_service, "reset_document_session"):
            self._ai_service.reset_document_session()
        logger.info(
            "Извлечение PDF по страницам: mode=%s, ocr=%s, ocr_mode=%s, ocr_engine=%s",
            opts["extraction_mode"],
            opts["ocr_enabled"],
            opts["ocr_control_mode"],
            opts["ocr_engine"],
        )

        ocr_doc = None
        if opts.get("ocr_enabled"):
            try:
                import fitz
                ocr_doc = fitz.open(stream=file_bytes, filetype="pdf")
                opts["_ocr_doc"] = ocr_doc
            except Exception:


                opts.pop("_ocr_doc", None)

        try:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                opts["_pdf_total_pages"] = len(pdf.pages)
                pages: list[PdfPageExtraction] = []
                for page_num, page in enumerate(pdf.pages, start=1):
                    pages.append(self._extract_pdfplumber_page(page, page_num, opts, file_bytes=file_bytes))

            if opts["remove_headers_footers"]:
                pages = self._remove_repeating_headers_footers(pages)

            pages = self._apply_document_context_profiles(pages, opts)






            if opts.get("repair_cross_page_continuations"):
                pages = self._repair_cross_page_continuations(pages, opts)





            pages = self._refresh_content_blocks_after_context(pages, opts)

            return pages
        except Exception as exc:
            logger.exception("Ошибка при извлечении страниц PDF: %s", exc)
            raise RuntimeError(f"Не удалось извлечь страницы PDF: {exc}") from exc
        finally:
            if ocr_doc is not None:
                try:
                    ocr_doc.close()
                except Exception:
                    pass
            opts.pop("_ocr_doc", None)
            opts.pop("_pdf_total_pages", None)

    def extract_text_from_file(self, file_path: str, options: dict[str, Any] | None = None) -> str:
        """Backward-compatible извлечение одной строкой."""
        pages = self.extract_pages_from_file(file_path, options=options)
        return self._pages_to_legacy_text(pages)

    def extract_text_from_bytes(self, file_bytes: bytes, options: dict[str, Any] | None = None) -> str:
        """Backward-compatible извлечение одной строкой."""
        pages = self.extract_pages_from_bytes(file_bytes, options=options)
        return self._pages_to_legacy_text(pages)

    def parse_bytes(
        self,
        file_bytes: bytes,
        filename: str = "unknown.pdf",
        metadata: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Public structured parser entrypoint for bytes callers."""
        return self.extract_content_from_bytes(
            file_bytes,
            filename=filename,
            metadata=metadata,
            options=options,
        )

    def extract_content(
        self,
        file_path: str | Path | None = None,
        *,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        metadata: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Extract structured content from a file path or bytes."""
        if file_bytes is not None and file_path is not None:
            raise ValueError("extract_content expects either file_path or file_bytes, not both")
        if file_bytes is None and file_path is None:
            raise ValueError("extract_content expects file_path or file_bytes")
        if file_bytes is not None:
            return self.extract_content_from_bytes(
                file_bytes,
                filename=filename or "unknown.pdf",
                metadata=metadata,
                options=options,
            )
        return self.extract_content_from_file(
            str(file_path),
            metadata=metadata,
            options=options,
        )

    def parse_to_documents(
        self,
        file_path: str,
        metadata: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> list[Document]:
        """Backward-compatible legacy projection from full page text.

        New RAG/Qwen callers should use ``parse_to_structured_documents`` or
        ``extract_content_from_file`` so references/tables/formulas stay typed
        instead of being embedded as ordinary body text.
        """
        logger.info("Парсинг PDF в legacy документы: %s", file_path)
        pages = self.extract_pages_from_file(file_path, options=options)
        full_text = self._pages_to_legacy_text(pages)
        if not full_text.strip():
            logger.warning("PDF файл не содержит текста")
            return []

        base_metadata = self._base_pdf_metadata(
            source=Path(file_path).name,
            file_path=file_path,
            pages=pages,
            metadata=metadata,
        )
        return self._split_text_to_documents(full_text, base_metadata)

    def parse_to_structured_documents(
        self,
        file_path: str,
        metadata: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> list[Document]:
        """Parse PDF file into RAG documents from final structured blocks."""
        logger.info("Парсинг PDF в structured RAG документы: %s", file_path)
        content = self.extract_content_from_file(file_path, metadata=metadata, options=options)
        return list(content.get("documents") or [])

    def parse_bytes_to_documents(
        self,
        file_bytes: bytes,
        filename: str = "unknown.pdf",
        metadata: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> list[Document]:
        """Backward-compatible legacy projection from bytes.

        Empty text layer returns ``[]``. Parser/runtime failures raise
        ``PdfExtractionError`` so callers can distinguish a genuinely empty PDF
        from a broken extraction.
        """
        try:
            pages = self.extract_pages_from_bytes(file_bytes, options=options)
        except Exception as exc:
            logger.exception("Ошибка при парсинге PDF bytes %s: %s", filename, exc)
            raise PdfExtractionError(f"Не удалось распарсить PDF {filename}: {exc}") from exc

        full_text = self._pages_to_legacy_text(pages)
        if not full_text.strip():
            logger.warning("PDF %s не содержит извлекаемого текстового слоя", filename)
            return []

        base_metadata = self._base_pdf_metadata(source=filename, pages=pages, metadata=metadata)
        return self._split_text_to_documents(full_text, base_metadata)

    def parse_bytes_to_structured_documents(
        self,
        file_bytes: bytes,
        filename: str = "unknown.pdf",
        metadata: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> list[Document]:
        """Parse PDF bytes into RAG documents from final structured blocks."""
        content = self.extract_content_from_bytes(file_bytes, filename=filename, metadata=metadata, options=options)
        return list(content.get("documents") or [])

    def extract_content_from_file(
        self,
        file_path: str | Path,
        metadata: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return structured parser result for downstream RAG/Qwen adapters."""
        file_path_obj = Path(str(file_path))
        pages = self.extract_pages_from_file(str(file_path_obj), options=options)
        base_metadata = self._base_pdf_metadata(
            source=file_path_obj.name,
            file_path=str(file_path_obj),
            pages=pages,
            metadata=metadata,
        )
        return self._build_structured_content_payload(pages, base_metadata)

    def extract_content_from_bytes(
        self,
        file_bytes: bytes,
        filename: str = "unknown.pdf",
        metadata: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return structured parser result for downstream RAG/Qwen adapters."""
        try:
            pages = self.extract_pages_from_bytes(file_bytes, options=options)
        except Exception as exc:
            logger.exception("Ошибка при structured парсинге PDF bytes %s: %s", filename, exc)
            raise PdfExtractionError(f"Не удалось распарсить PDF {filename}: {exc}") from exc
        base_metadata = self._base_pdf_metadata(source=filename, pages=pages, metadata=metadata)
        return self._build_structured_content_payload(pages, base_metadata)

    def _build_structured_content_payload(
        self,
        pages: list[PdfPageExtraction],
        base_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        payload_metadata = dict(base_metadata)
        payload_metadata.update(self._summarize_parser_strategy_metadata(pages))
        content_parts = self.pages_to_content_parts(
            pages,
            source=str(payload_metadata.get("source") or ""),
            metadata=payload_metadata,
        )
        projection_summary = self._content_parts_projection_summary(content_parts)
        payload_metadata.update(projection_summary)
        documents = self.content_parts_to_documents(content_parts, payload_metadata)
        qwen_markdown = self.content_parts_to_qwen_markdown(content_parts)
        legacy_text = self._pages_to_legacy_text(pages)
        structured_text = self.content_parts_to_legacy_text(content_parts)
        return {
            "metadata": payload_metadata,
            "pages": [page.as_dict() for page in pages],
            "content_parts": content_parts,
            "documents": documents,
            "qwen_markdown": qwen_markdown,
            "structured_text": structured_text,
            "legacy_text": legacy_text,
        }

    def _normalize_options(self, options: dict[str, Any] | None) -> dict[str, Any]:
        incoming_options = options or {}
        raw = merge_parser_options(self.default_options, incoming_options)

        valid_strategies = {"auto", "layout", "simple", "columns", "ocr", "ai"}
        technical_strategies = {"layout", "simple", "columns", "ocr", "ai"}

        def explicit_or_raw(*names: str) -> Any:
            for name in names:
                value = incoming_options.get(name)
                if value not in {None, ""}:
                    return value
            for name in names:
                value = raw.get(name)
                if value not in {None, ""}:
                    return value
            return None

        def clean_name(value: Any, default: str = "") -> str:
            return str(value if value is not None else default).strip().lower()

        parser_mode_source = "parser_mode"
        if incoming_options.get("parser_mode") not in {None, ""}:
            parser_mode_raw = incoming_options.get("parser_mode")
            parser_mode_source = "parser_mode"
        elif incoming_options.get("mode") not in {None, ""}:
            parser_mode_raw = incoming_options.get("mode")
            parser_mode_source = "mode"
        elif raw.get("parser_mode") not in {None, ""}:
            parser_mode_raw = raw.get("parser_mode")
            parser_mode_source = "parser_mode"
        else:
            parser_mode_raw = raw.get("mode")
            parser_mode_source = "mode"

        parser_mode = clean_name(parser_mode_raw, "auto")
        legacy_extraction_mode = clean_name(explicit_or_raw("extraction_mode"), "auto")
        extraction_strategy = clean_name(explicit_or_raw("extraction_strategy"), "auto")
        force_strategy = clean_name(explicit_or_raw("force_strategy"), "")
        ocr_mode = clean_name(explicit_or_raw("ocr_mode"), "auto")
        ai_mode = clean_name(explicit_or_raw("ai_mode"), "off")

        if ai_mode in {"disabled", "disable", "false", "0", "no", "none"}:
            ai_mode = "off"
        elif ai_mode in {"forced", "true", "1", "yes", "on"}:
            ai_mode = "force"
        elif ai_mode not in {"auto", "force", "off"}:
            raise ValueError(f"Unknown ai_mode: {ai_mode}")

        if ocr_mode in {"disabled", "disable", "false", "0", "no", "none"}:
            ocr_mode = "off"
        elif ocr_mode in {"forced", "true", "1", "yes", "on"}:
            ocr_mode = "force"
        elif ocr_mode not in {"auto", "force", "off"}:
            raise ValueError(f"Unknown ocr_mode: {ocr_mode}")

        if parser_mode in {"", "none"}:
            parser_mode = "auto"

        if parser_mode == "ai":
            force_strategy = "ai"
            ai_mode = "force"
        elif parser_mode == "auto":
            pass
        elif parser_mode_source == "mode" and parser_mode == "ocr":
            parser_mode = "auto"
            force_strategy = "ocr"
            ocr_mode = "force"
        elif parser_mode_source == "mode" and parser_mode in {"layout", "simple", "columns"}:
            force_strategy = parser_mode
            parser_mode = "auto"
        else:
            raise ValueError(f"Unknown parser_mode: {parser_mode}. Public parser mode must be 'auto' or 'ai'.")

        if legacy_extraction_mode == "ai" and not force_strategy:
            parser_mode = "ai"
            force_strategy = "ai"
            ai_mode = "force"
        elif legacy_extraction_mode in {"layout", "simple", "columns", "ocr"} and not force_strategy:
            force_strategy = legacy_extraction_mode
        elif legacy_extraction_mode not in valid_strategies:
            raise ValueError(f"Unknown extraction_mode: {legacy_extraction_mode}")

        if extraction_strategy == "ai" and not force_strategy:
            parser_mode = "ai"
            force_strategy = "ai"
            ai_mode = "force"
        elif extraction_strategy in {"layout", "simple", "columns", "ocr"} and not force_strategy:
            force_strategy = extraction_strategy
        elif extraction_strategy not in valid_strategies:
            raise ValueError(f"Unknown extraction_strategy: {extraction_strategy}")

        if force_strategy and force_strategy not in technical_strategies:
            raise ValueError(f"Unknown force_strategy: {force_strategy}")

        if force_strategy == "ocr":
            ocr_mode = "force"
        if force_strategy == "ai":
            ai_mode = "force"
        if ai_mode == "force" and not force_strategy:
            force_strategy = "ai"

        if ocr_mode == "force":
            ocr_requested_enabled = True
            ocr_force = True
            ocr_engine = clean_name(raw.get("ocr_engine"), "tesseract")
            if ocr_engine == "auto":
                ocr_engine = "tesseract"
        elif ocr_mode == "off":
            ocr_requested_enabled = False
            ocr_force = False
            ocr_engine = clean_name(raw.get("ocr_engine"), "auto")
        else:
            ocr_requested_enabled = self._to_bool(raw.get("ocr_enabled"), True)
            ocr_force = self._to_bool(raw.get("ocr_force"), False)
            ocr_engine = clean_name(raw.get("ocr_engine"), "auto")

        ocr_skip = self._to_bool(raw.get("ocr_skip") or raw.get("skip_ocr"), False)
        ocr_enabled = bool(ocr_requested_enabled) and not ocr_skip

        if force_strategy in {"ocr", "ai"}:
            mode = "auto"
            selected_extraction_strategy = force_strategy
        elif force_strategy:
            mode = force_strategy
            selected_extraction_strategy = force_strategy
        else:
            mode = "auto"
            selected_extraction_strategy = "auto"

        domain_profile = self._normalize_domain_profile_name(
            raw.get("parser_domain_profile")
            or raw.get("parser_profile")
            or raw.get("document_domain_profile")
            or raw.get("profile")
            or raw.get("domain_profile")
        )
        ocr_pages_raw = raw.get("ocr_only_pages") if raw.get("ocr_only_pages") not in {None, ""} else raw.get("ocr_pages")
        return {
            "parser_mode": parser_mode,
            "extraction_mode": mode,
            "extraction_strategy": selected_extraction_strategy,
            "force_strategy": force_strategy or "",
            "ocr_mode": ocr_mode,
            "ai_mode": ai_mode,
            "ai_enabled": self._to_bool(raw.get("ai_enabled"), False) or ai_mode in {"auto", "force"} or force_strategy == "ai",
            "ai_provider": str(raw.get("ai_provider") or ""),
            "ai_model": str(raw.get("ai_model") or ""),
            "ai_endpoint": str(raw.get("ai_endpoint") or ""),
            "ai_render_dpi": self._to_int(raw.get("ai_render_dpi"), 220, minimum=72, maximum=600),
            "ai_page_image_format": str(raw.get("ai_page_image_format") or "png").lower(),
            "ai_timeout_sec": self._to_int(raw.get("ai_timeout_sec"), 120, minimum=1, maximum=600),
            "ai_preserve_original_text": self._to_bool(raw.get("ai_preserve_original_text"), True),
            "ai_fallback_to_auto": self._to_bool(raw.get("ai_fallback_to_auto"), True),
            "ai_delete_temp_images": self._to_bool(raw.get("ai_delete_temp_images"), True),
            "detect_columns": self._to_bool(raw.get("detect_columns"), True),
            "extract_tables": self._to_bool(raw.get("extract_tables"), True),
            "remove_headers_footers": self._to_bool(raw.get("remove_headers_footers"), True),
            "merge_hyphenated_words": self._to_bool(raw.get("merge_hyphenated_words"), True),
            "normalize_math": self._to_bool(raw.get("normalize_math"), True),
            "normalize_cid_glyphs": self._to_bool(raw.get("normalize_cid_glyphs"), True),
            "normalize_private_use_glyphs": self._to_bool(raw.get("normalize_private_use_glyphs"), True),
            "detect_footnotes": self._to_bool(raw.get("detect_footnotes"), True),
            "filter_watermarks": self._to_bool(raw.get("filter_watermarks"), True),
            "mark_formula_candidates": self._to_bool(raw.get("mark_formula_candidates"), True),
            "drop_graph_axis_from_body": self._to_bool(raw.get("drop_graph_axis_from_body"), True),
            "drop_arxiv_footer_from_body": self._to_bool(raw.get("drop_arxiv_footer_from_body"), True),
            "line_type_metadata": self._to_bool(raw.get("line_type_metadata"), True),
            "repair_cross_page_continuations": self._to_bool(raw.get("repair_cross_page_continuations"), False),
            "ocr_enabled": ocr_enabled,
            "ocr_requested_enabled": ocr_requested_enabled,
            "ocr_control_mode": str(raw.get("ocr_control_mode") or "auto").lower(),
            "ocr_engine": ocr_engine,
            "ocr_fallback_engines": raw.get("ocr_fallback_engines") if raw.get("ocr_fallback_engines") is not None else ["tesseract"],
            "ocr_force": ocr_force,
            "ocr_skip": ocr_skip,
            "ocr_pages": str(ocr_pages_raw or ""),
            "ocr_only_pages": str(ocr_pages_raw or ""),
            "ocr_dpi": self._to_int(raw.get("ocr_dpi"), 220, minimum=120, maximum=400),
            "ocr_languages": str(raw.get("ocr_languages") or "eng+rus"),
            "ocr_merge_strategy": str(raw.get("ocr_merge_strategy") or "replace_low_quality").lower(),
            "ocr_min_quality_score": float(raw.get("ocr_min_quality_score") or 0.45),
            "ocr_min_confidence": float(raw.get("ocr_min_confidence") or 0.55),
            "ocr_min_text_chars": self._to_int(raw.get("ocr_min_text_chars"), 180, minimum=0, maximum=10000),
            "ocr_min_words": self._to_int(raw.get("ocr_min_words"), 35, minimum=0, maximum=10000),
            "ocr_min_text_density": float(raw.get("ocr_min_text_density") or 0.35),
            "ocr_broken_encoding_noise_ratio": float(raw.get("ocr_broken_encoding_noise_ratio") or 0.02),
            "ocr_allow_paddle": self._to_bool(raw.get("ocr_allow_paddle"), False),
            "ocr_allow_ocrmypdf_page": self._to_bool(raw.get("ocr_allow_ocrmypdf_page"), False),
            "ocr_emit_lines": self._to_bool(raw.get("ocr_emit_lines"), False),
            "ocr_debug": self._to_bool(raw.get("ocr_debug"), False),
            "ocr_surya_experimental": self._to_bool(raw.get("ocr_surya_experimental"), False),
            "ocr_create_searchable_pdf": self._to_bool(raw.get("ocr_create_searchable_pdf"), False),
            "ocr_preserve_original_text": self._to_bool(raw.get("ocr_preserve_original_text"), True),
            "min_text_chars": self._to_int(raw.get("min_text_chars"), 300, minimum=0, maximum=10000),
            "max_page_chars": self._to_int(raw.get("max_page_chars"), 60000, minimum=5000, maximum=250000),
            "table_settings": raw.get("table_settings") if isinstance(raw.get("table_settings"), dict) else {},
            "document_reference_context": self._to_bool(raw.get("document_reference_context"), True),
            "caption_continuation_blocks": self._to_bool(raw.get("caption_continuation_blocks"), True),
            "emit_content_blocks": self._to_bool(raw.get("emit_content_blocks"), True),
            "retype_content_blocks_after_cleanup": self._to_bool(raw.get("retype_content_blocks_after_cleanup"), True),
            "max_content_blocks_per_page": self._to_int(raw.get("max_content_blocks_per_page"), 500, minimum=40, maximum=2000),
            "rebuild_content_blocks_from_final_text": self._to_bool(raw.get("rebuild_content_blocks_from_final_text"), True),
            "content_blocks_mode": str(raw.get("content_blocks_mode") or "final").lower(),
            "domain_profile": domain_profile,
        }

    def _extract_pdfplumber_page(self, page: Any, page_num: int, opts: dict[str, Any], *, file_bytes: bytes) -> PdfPageExtraction:
        candidates: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {
            "domain_profile": str(opts.get("domain_profile") or "generic"),
            "parser_mode": str(opts.get("parser_mode") or "auto"),
            "extraction_strategy": str(opts.get("extraction_strategy") or "auto"),
            "force_strategy": str(opts.get("force_strategy") or ""),
            "ocr_mode": str(opts.get("ocr_mode") or "auto"),
            "ocr_enabled": bool(opts.get("ocr_enabled")),
            "ocr_engine": str(opts.get("ocr_engine") or "auto"),
            "ocr_force": bool(opts.get("ocr_force")),
            "ai_mode": str(opts.get("ai_mode") or "off"),
            "ai_enabled": bool(opts.get("ai_enabled")),
            "ai_provider": str(opts.get("ai_provider") or ""),
            "ai_model": str(opts.get("ai_model") or ""),
            "ai_render_dpi": int(opts.get("ai_render_dpi") or 220),
            "ai_page_image_format": str(opts.get("ai_page_image_format") or "png"),
            "page_width": float(getattr(page, "width", 0) or 0),
            "page_height": float(getattr(page, "height", 0) or 0),
        }

        layout_text = self._safe_extract_text(page, layout=True)
        simple_text = self._safe_extract_text(page, layout=False)
        raw_words = self._safe_extract_words(page)
        words = self._dedupe_words(raw_words)
        if opts.get("filter_watermarks", True):
            words, watermark_meta = self._filter_watermark_words(words, page)
            metadata.update(watermark_meta)
        else:
            metadata.update({"watermark_words_removed": 0, "possible_watermark_words": 0})
        word_stats = self._word_stats(words)
        metadata.update(word_stats)
        metadata.update(
            {
                "raw_layout_chars": len(layout_text or ""),
                "raw_simple_chars": len(simple_text or ""),
                "word_count": len(words),
                "image_count": len(getattr(page, "images", []) or []),
            }
        )

        page_width = float(getattr(page, "width", 0) or 0)
        columns_detected = self._looks_two_column(words, page_width)
        metadata["columns_detected"] = columns_detected
        page_height = float(getattr(page, "height", 0) or 0)
        word_lines = self._words_to_lines(words, page_width=page_width) if words else []
        metadata["word_line_count"] = len(word_lines)
        if opts.get("line_type_metadata", True):
            line_counts = self._line_type_counts(word_lines, metadata)
            metadata.update({f"line_type_{k}": v for k, v in line_counts.items()})
            content_blocks, content_meta = self._content_blocks_from_lines(
                word_lines,
                page_num=page_num,
                metadata=metadata,
                max_blocks=int(opts.get("max_content_blocks_per_page") or 500),
                opts=opts,
            )
            metadata.update(content_meta)
            _, line_filter_meta = self._filter_lines_for_body_text(word_lines, opts, metadata)
            metadata.update(line_filter_meta)




            metadata["raw_content_blocks"] = content_blocks
            metadata["raw_content_blocks_sample"] = content_blocks[:40]
            if opts.get("emit_content_blocks", True):
                metadata["content_blocks"] = content_blocks
            metadata["content_blocks_sample"] = content_blocks[:40]
        if opts.get("detect_footnotes", True):
            _, footnote_lines, footnote_meta = self._split_footnote_lines(word_lines, page_height=page_height, return_metadata=True)
            metadata.update(footnote_meta)
            metadata["footnote_line_count"] = len(footnote_lines)
        else:
            metadata.update({
                "rejected_footnote_graph_axis": 0,
                "rejected_footnote_reference": 0,
                "rejected_footnote_table": 0,
                "rejected_footnote_figure_label": 0,
                "rejected_footnote_section_heading": 0,
                "rejected_footnote_weak_signal": 0,
                "reference_context_footnotes_disabled": 0,
            })
            metadata["footnote_line_count"] = 0

        if opts["extraction_mode"] in {"auto", "layout"}:
            candidates.append(self._candidate("pdfplumber_layout", layout_text, page_num, opts, metadata))
        if opts["extraction_mode"] in {"auto", "simple"}:
            candidates.append(self._candidate("pdfplumber_simple", simple_text, page_num, opts, metadata))



        if opts["extraction_mode"] == "auto":
            word_text = self._extract_words_layout_text(
                page,
                opts,
                words=words,
                force_columns=bool(opts["detect_columns"] and columns_detected),
            )
            word_method = "pdfplumber_word_columns" if columns_detected else "pdfplumber_word_layout"
            candidates.append(self._candidate(word_method, word_text, page_num, opts, metadata))



        if opts["extraction_mode"] == "columns" or (
            opts["extraction_mode"] == "auto" and opts["detect_columns"] and columns_detected
        ):
            columns_text = self._extract_columns_text(page, opts, words=words)
            candidates.append(self._candidate("pdfplumber_columns", columns_text, page_num, opts, metadata))

        if opts["extract_tables"]:
            table_md, table_meta = self._extract_tables_markdown(page, metadata=metadata)
            metadata.update(table_meta)
        else:
            table_md = ""
            metadata.update({"table_count": 0, "table_cells": 0})

        if opts.get("force_strategy") == "ai" or str(opts.get("ai_mode") or "off") == "force":
            ai_result = self._ai_service.recognize_page(
                file_bytes=file_bytes,
                page_number=page_num,
                page_width=page_width,
                page_height=page_height,
                opts=opts,
            )
            metadata.update(ai_result.metadata)
            metadata["ai_requested"] = True
            metadata["ai_status"] = ai_result.status
            metadata["ai_reason"] = ai_result.reason
            metadata["ai_used"] = bool(ai_result.text.strip())
            metadata["ai_fallback_used"] = not bool(ai_result.text.strip())
            metadata["ai_confidence"] = float(ai_result.confidence or 0.0)
            if ai_result.warnings:
                metadata["ai_warnings"] = list(ai_result.warnings)
            if ai_result.text.strip():
                ai_candidate = self._candidate("ai_page_image", ai_result.text, page_num, opts, metadata)
                ai_candidate["quality_score"] = max(float(ai_candidate.get("quality_score") or 0.0), 0.995)
                candidates.append(ai_candidate)
            elif not bool(opts.get("ai_fallback_to_auto", True)):
                candidates.clear()
                candidates.append({
                    "method": "ai_page_image_failed",
                    "text": "",
                    "quality_score": 0.0,
                    "warnings": ["ai_page_recognition_failed"],
                    "metadata": {"page": page_num},
                })

        best = self._select_best_candidate(candidates)
        text = (best.get("text") or "").strip()
        method = str(best.get("method") or "pdfplumber_empty")
        warnings = list(best.get("warnings") or [])
        quality = float(best.get("quality_score") or 0.0)

        if table_md:
            text = f"{text}\n\n{table_md}".strip() if text else table_md.strip()
            warnings.append("tables_detected")

        metadata.setdefault("ocr_decision", "skip")
        metadata.setdefault("ocr_reason", "manual_skip" if opts.get("ocr_skip") else "disabled")
        metadata.setdefault("ocr_requested_engine", str(opts.get("ocr_engine") or "auto"))
        metadata.setdefault("ocr_engine", "tesseract" if str(opts.get("ocr_engine") or "auto").lower() == "auto" else str(opts.get("ocr_engine") or "tesseract"))
        metadata.setdefault("ocr_merge_strategy", str(opts.get("ocr_merge_strategy") or "replace_low_quality"))
        metadata.setdefault("ocr_engine_selection_reason", "manual_skip" if opts.get("ocr_skip") else "disabled")
        metadata.setdefault("ocr_skip", bool(opts.get("ocr_skip")))
        metadata.setdefault("ocr_requested_enabled", bool(opts.get("ocr_requested_enabled")))
        metadata.setdefault("ocr_pages_used", 0)
        metadata.setdefault("ocr_pages_skipped", 1)
        metadata.setdefault("ocr_pages_failed", 0)
        metadata.setdefault("ocr_avg_confidence", 0.0)
        metadata.setdefault("ocr_chars", 0)

        if opts.get("ocr_skip") and opts.get("ocr_requested_enabled"):
            logger.info(
                "OCR decision page %s: decision=skip reason=manual_skip requested=%s engine=%s",
                page_num,
                opts.get("ocr_requested_enabled"),
                metadata.get("ocr_engine"),
            )

        if opts["ocr_enabled"]:
            metadata["pre_ocr_quality_score"] = round(float(quality or 0.0), 4)
            metadata["pre_ocr_quality_components"] = self._quality_components(text, metadata=metadata)
            ocr_config = self._ocr_service.build_config(opts)
            if ocr_config.page_selection_warnings:
                warnings.extend(ocr_config.page_selection_warnings)
            if ocr_config.engine_warnings:
                warnings.extend(ocr_config.engine_warnings)
            metadata["ocr_requested_engine"] = ocr_config.requested_engine
            metadata["ocr_engine"] = ocr_config.engine
            metadata["ocr_engine_plan"] = list(ocr_config.fallback_engines)
            metadata["ocr_engine_selection_reason"] = ocr_config.engine_selection_reason
            metadata["ocr_allow_paddle"] = bool(ocr_config.allow_paddle)
            metadata["ocr_allow_ocrmypdf_page"] = bool(ocr_config.allow_ocrmypdf_page)
            ocr_decision = self._ocr_service.decide(
                page_number=page_num,
                text=text,
                quality_score=quality,
                warnings=warnings,
                metadata=metadata,
                config=ocr_config,
            )
            metadata["ocr_decision"] = "apply" if ocr_decision.apply_ocr else "skip"
            metadata["ocr_reason"] = self._ocr_service.normalize_reason(ocr_decision.reason)
            metadata["ocr_reason_detail"] = ocr_decision.reason
            metadata["ocr_decision_details"] = ocr_decision.details
            metadata["ocr_engine"] = ocr_decision.engine
            metadata["ocr_merge_strategy"] = ocr_decision.merge_strategy
            logger.info(
                "OCR decision page %s: decision=%s reason=%s engine=%s details=%s",
                page_num,
                metadata["ocr_decision"],
                metadata["ocr_reason_detail"],
                metadata["ocr_engine"],
                ocr_decision.details,
            )
            if ocr_decision.apply_ocr:
                ocr_result = self._ocr_service.run(
                    file_bytes=file_bytes,
                    page_number=page_num,
                    config=ocr_config,
                    context={
                        "ocr_doc": opts.get("_ocr_doc"),
                        "surya_experimental_enabled": bool(opts.get("ocr_surya_experimental")),
                        "allow_ocrmypdf_page": bool(ocr_config.allow_ocrmypdf_page),
                    },
                )
                metadata["ocr_pages_used"] = 1 if ocr_result.text.strip() else 0
                metadata["ocr_pages_failed"] = 1 if not ocr_result.text.strip() else 0
                metadata["ocr_pages_skipped"] = 0
                metadata["ocr_chars"] = len((ocr_result.text or "").strip())
                metadata["ocr_avg_confidence"] = float(ocr_result.confidence or 0.0)
                metadata["ocr_engine"] = ocr_result.engine or ocr_decision.engine
                if not ocr_result.text.strip():
                    if any(str(w) == "ocr_dependencies_missing" for w in (ocr_result.warnings or [])):
                        metadata["ocr_reason"] = "dependencies_missing"
                    elif any("not_available" in str(w) for w in (ocr_result.warnings or [])):
                        metadata["ocr_reason"] = "engine_unavailable"
                    else:
                        metadata["ocr_reason"] = "ocr_failed"
                else:
                    metadata["ocr_reason"] = "applied"
                if opts.get("ocr_debug"):
                    metadata["ocr_warnings"] = list(ocr_result.warnings or [])
                    if ocr_config.emit_lines:
                        metadata["ocr_lines"] = [
                            {
                                "text": line.text,
                                "bbox": line.bbox,
                                "confidence": line.confidence,
                            }
                            for line in (ocr_result.lines or [])[:80]
                        ]
                ocr_quality = None
                if ocr_result.text.strip():
                    ocr_quality = self._score_text(
                        ocr_result.text,
                        method=f"ocr_{(ocr_result.engine or ocr_decision.engine or 'tesseract')}",
                        opts=opts,
                        metadata=metadata,
                    )
                    metadata["ocr_candidate_quality_score"] = round(float(ocr_quality), 3)
                merged_text, merge_strategy, merge_diag = self._ocr_service.merge_text(
                    original_text=text,
                    ocr_result=ocr_result,
                    quality_score=quality,
                    ocr_quality_score=ocr_quality,
                    config=ocr_config,
                )
                metadata["ocr_merge_strategy"] = merge_strategy
                metadata["ocr_merge_diagnostics"] = merge_diag
                if ocr_result.text.strip() and ocr_quality is not None:
                    if ocr_quality > quality:
                        metadata["ocr_quality_improved_pages"] = 1
                    elif ocr_quality < quality:
                        metadata["ocr_quality_regressed_pages"] = 1
                if opts.get("ocr_debug"):
                    metadata["ocr_debug_payload"] = {
                        "pdf_text_snippet": (text or "")[:400],
                        "ocr_text_snippet": (ocr_result.text or "")[:400],
                        "merged_text_snippet": (merged_text or "")[:400],
                        "merge_diagnostics": merge_diag,
                    }
                if merged_text.strip() != (text or "").strip():
                    text = self._clean_page_text(merged_text, opts)
                    method = f"ocr_{metadata.get('ocr_engine') or 'tesseract'}"
                    quality = self._score_text(text, method=method, opts=opts, metadata=metadata)
                    warnings.append("ocr_used")
                for warning_name in (ocr_result.warnings or []):
                    warnings.append(str(warning_name))
            else:
                metadata["ocr_pages_used"] = 0
                metadata["ocr_pages_failed"] = 0
                metadata["ocr_pages_skipped"] = 1
                if metadata["ocr_reason"] in {"empty_text_layer", "low_quality_score"}:
                    metadata["ocr_recommended_but_disabled"] = 1



        text = self._remove_arxiv_footer_text(text, metadata)
        text = self._remove_non_body_text_lines(text, opts, metadata)
        text = self._stitch_math_micro_lines(text, metadata)

        text, flow_meta = self._repair_page_flow_text(text, opts)
        if flow_meta.get("repaired_total"):
            warnings.append("flow_repaired")

        text = self._trim_page_text(text, opts["max_page_chars"])
        final_meta = dict(metadata)
        final_meta.update(best.get("metadata") or {})
        final_meta.update(flow_meta)
        final_meta["final_chars"] = len(text)
        final_meta["method_selected"] = method
        if str(method or "").startswith("ai_"):
            selected_strategy = "ai"
        elif str(method or "").startswith("ocr_"):
            selected_strategy = "ocr"
        elif "columns" in str(method or ""):
            selected_strategy = "columns"
        elif "simple" in str(method or ""):
            selected_strategy = "simple"
        elif "layout" in str(method or ""):
            selected_strategy = "layout"
        else:
            selected_strategy = str(opts.get("extraction_strategy") or "auto")
        if opts.get("force_strategy"):
            strategy_reason = f"forced_strategy:{opts.get('force_strategy')}"
        elif selected_strategy == "columns" and columns_detected:
            strategy_reason = "two_column_layout_detected"
        elif selected_strategy == "ai":
            strategy_reason = str(final_meta.get("ai_reason") or "ai_page_image_strategy_selected")
        elif selected_strategy == "ocr":
            strategy_reason = str(final_meta.get("ocr_reason") or "ocr_strategy_selected")
        else:
            strategy_reason = "auto_best_candidate"
        final_meta["parser_mode"] = str(opts.get("parser_mode") or "auto")
        final_meta["extraction_strategy"] = str(opts.get("extraction_strategy") or "auto")
        final_meta["force_strategy"] = str(opts.get("force_strategy") or "")
        final_meta["selected_strategy"] = selected_strategy
        final_meta["strategy_reason"] = strategy_reason
        final_meta["ocr_mode"] = str(opts.get("ocr_mode") or "auto")
        final_meta["ocr_enabled"] = bool(opts.get("ocr_enabled"))
        final_meta["ocr_engine"] = str(final_meta.get("ocr_engine") or opts.get("ocr_engine") or "auto")
        final_meta["ocr_force"] = bool(opts.get("ocr_force"))
        final_meta["ocr_used"] = bool(selected_strategy == "ocr" or int(final_meta.get("ocr_pages_used") or 0) > 0)
        final_meta["ai_mode"] = str(opts.get("ai_mode") or "off")
        final_meta["ai_enabled"] = bool(opts.get("ai_enabled"))
        final_meta["ai_provider"] = str(opts.get("ai_provider") or "")
        final_meta["ai_model"] = str(opts.get("ai_model") or "")
        final_meta["ai_render_dpi"] = int(opts.get("ai_render_dpi") or 220)
        final_meta["ai_page_image_format"] = str(opts.get("ai_page_image_format") or "png")
        final_meta.setdefault("ai_requested", bool(opts.get("force_strategy") == "ai" or str(opts.get("ai_mode") or "off") == "force"))
        final_meta.setdefault("ai_used", bool(selected_strategy == "ai"))
        final_meta.setdefault("ai_status", "not_requested")
        final_meta.setdefault("ai_reason", "not_requested")
        final_meta.setdefault("ai_fallback_used", False)
        page_class_meta = self._classify_page_content(text, final_meta)


        final_meta.update(page_class_meta)
        if opts.get("emit_content_blocks", True) and opts.get("retype_content_blocks_after_cleanup", True):
            final_blocks, final_blocks_meta = self._finalize_content_blocks_for_page(
                page_text=text,
                metadata=final_meta,
                opts=opts,
                page_num=page_num,
            )
            final_meta["final_content_blocks"] = final_blocks
            final_meta["content_blocks"] = final_blocks
            final_meta["content_blocks_sample"] = final_blocks[:40]
            final_meta["final_content_blocks_sample"] = final_blocks[:40]
            final_meta.update(final_blocks_meta)




            page_class_meta = self._classify_page_content(text, final_meta)
            final_meta.update(page_class_meta)
        if page_class_meta.get("figure_heavy_page"):
            warnings.append("figure_heavy_page")
        if page_class_meta.get("figure_only_page"):
            warnings.append("figure_only_page")
        if page_class_meta.get("reference_page"):
            warnings.append("reference_page")
        if page_class_meta.get("formula_heavy_page"):
            warnings.append("formula_heavy_page")
        if page_class_meta.get("graph_axis_text_detected"):
            warnings.append("graph_axis_text_detected")
        if int(final_meta.get("footnote_line_count") or 0) > 0:
            warnings.append("footnotes_detected")
        if int(final_meta.get("watermark_words_removed") or 0) > 0:
            warnings.append("watermark_words_removed")
        if self._count_watermark_noise(text, metadata=final_meta) and not final_meta.get("reference_page"):
            warnings.append("possible_watermark_text")

        if not text.strip():
            warnings.append("empty_text")
        elif len(text) < opts["min_text_chars"]:
            warnings.append("low_text_chars")
        if columns_detected and method not in {"pdfplumber_columns", "pdfplumber_word_columns"}:
            warnings.append("possible_two_columns")
        if (
            metadata.get("image_count", 0)
            and len(text) < opts["min_text_chars"]
            and not final_meta.get("figure_only_page")
            and not final_meta.get("figure_plate_page")
            and not final_meta.get("label_only_page")
        ):
            warnings.append("possible_scanned_page")

        quality = self._score_text(text, method=method, opts=opts, metadata=final_meta)
        final_meta["quality_components"] = self._quality_components(text, metadata=final_meta)
        if ("possible_scanned_page" in warnings or "low_text_chars" in warnings) and quality < 0.45:
            final_meta["low_confidence_page"] = True
            final_meta["ocr_recommended"] = True
            warnings.append("low_confidence_page")
            warnings.append("ocr_recommended")

        return PdfPageExtraction(
            page_number=page_num,
            text=text,
            method=method,
            quality_score=round(max(0.0, min(1.0, quality)), 3),
            warnings=sorted(set(warnings)),
            metadata=final_meta,
        )




pdf_parser = PDFParser(chunk_size=1000, chunk_overlap=200)


__all__ = ["PDFParser", "pdf_parser"]
