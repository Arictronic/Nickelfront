"""
Сервис парсинга документов для RAG и PDF-content pipeline.

Ключевой режим для Nickelfront: извлечение PDF не одной большой строкой,
а структурированными страницами с диагностикой качества. Это даёт более
чистый raw_text для Qwen Markdown и позволяет видеть плохие страницы.
"""

from __future__ import annotations

import io
import logging
import math
import os
import re
import tempfile
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

_MATH_SYMBOL_RE = re.compile(r"[=∑∫√≈≤≥±×÷→←↔∞αβγδλμσΩωπθ{}^_]|\\(?:frac|sum|int|sqrt|begin|end|alpha|beta|gamma)")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_PAGE_NUMBER_RE = re.compile(r"^\s*(?:[-–—]\s*)?\d{1,4}\s*(?:[-–—])?\s*$")
_DOI_FOOTER_RE = re.compile(r"\b(?:doi\s*:?\s*10\.|https?://doi\.org/10\.)", re.IGNORECASE)


@dataclass(slots=True)
class PdfPageExtraction:
    """Результат извлечения одной страницы PDF."""

    page_number: int
    text: str
    method: str
    quality_score: float
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PDFParser:
    """
    Парсер PDF для научных статей/патентов.

    Поддерживает:
    - page-level extraction;
    - auto/layout/simple/columns режимы;
    - table extraction в Markdown;
    - optional OCR fallback, если установлены PyMuPDF + pytesseract;
    - quality score/warnings для каждой страницы;
    - очистку колонтитулов и переносов.
    """

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        logger.info("Инициализация PDFParser: chunk_size=%s, chunk_overlap=%s", chunk_size, chunk_overlap)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
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
        logger.info("Извлечение PDF по страницам: mode=%s, ocr=%s", opts["extraction_mode"], opts["ocr_enabled"])

        try:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                pages: list[PdfPageExtraction] = []
                for page_num, page in enumerate(pdf.pages, start=1):
                    pages.append(self._extract_pdfplumber_page(page, page_num, opts, file_bytes=file_bytes))

            if opts["remove_headers_footers"]:
                pages = self._remove_repeating_headers_footers(pages)

            return pages
        except Exception as exc:
            logger.exception("Ошибка при извлечении страниц PDF: %s", exc)
            raise RuntimeError(f"Не удалось извлечь страницы PDF: {exc}") from exc

    def extract_text_from_file(self, file_path: str) -> str:
        """Backward-compatible извлечение одной строкой."""
        pages = self.extract_pages_from_file(file_path)
        return self._pages_to_legacy_text(pages)

    def extract_text_from_bytes(self, file_bytes: bytes) -> str:
        """Backward-compatible извлечение одной строкой."""
        pages = self.extract_pages_from_bytes(file_bytes)
        return self._pages_to_legacy_text(pages)

    def parse_to_documents(self, file_path: str, metadata: dict[str, Any] | None = None) -> list[Document]:
        logger.info("Парсинг PDF в документы: %s", file_path)
        full_text = self.extract_text_from_file(file_path)
        if not full_text.strip():
            logger.warning("PDF файл не содержит текста")
            return []

        chunks = self._text_splitter.split_text(full_text)
        base_metadata = {
            "source": Path(file_path).name,
            "file_path": str(Path(file_path).absolute()),
            "type": "patent_pdf",
        }
        if metadata:
            base_metadata.update(metadata)

        docs: list[Document] = []
        for i, chunk in enumerate(chunks):
            doc_metadata = base_metadata.copy()
            doc_metadata["chunk_index"] = i
            doc_metadata["total_chunks"] = len(chunks)
            docs.append(Document(page_content=chunk, metadata=doc_metadata))
        return docs

    def parse_bytes_to_documents(
        self,
        file_bytes: bytes,
        filename: str = "unknown.pdf",
        metadata: dict[str, Any] | None = None,
    ) -> list[Document]:
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
                tmp_file.write(file_bytes)
                tmp_path = tmp_file.name
            try:
                docs = self.parse_to_documents(tmp_path, metadata=metadata)
                for doc in docs:
                    doc.metadata["source"] = filename
                return docs
            finally:
                os.unlink(tmp_path)
        except Exception as exc:
            logger.error("Ошибка при парсинге PDF bytes: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Extraction core
    # ------------------------------------------------------------------
    def _normalize_options(self, options: dict[str, Any] | None) -> dict[str, Any]:
        raw = dict(options or {})
        mode = str(raw.get("extraction_mode") or "auto").lower()
        if mode not in {"auto", "layout", "simple", "columns", "ocr"}:
            mode = "auto"
        return {
            "extraction_mode": mode,
            "detect_columns": self._to_bool(raw.get("detect_columns"), True),
            "extract_tables": self._to_bool(raw.get("extract_tables"), True),
            "remove_headers_footers": self._to_bool(raw.get("remove_headers_footers"), True),
            "merge_hyphenated_words": self._to_bool(raw.get("merge_hyphenated_words"), True),
            "normalize_math": self._to_bool(raw.get("normalize_math"), True),
            "mark_formula_candidates": self._to_bool(raw.get("mark_formula_candidates"), True),
            "ocr_enabled": self._to_bool(raw.get("ocr_enabled"), False),
            "ocr_dpi": self._to_int(raw.get("ocr_dpi"), 220, minimum=120, maximum=400),
            "ocr_languages": str(raw.get("ocr_languages") or "eng+rus"),
            "min_text_chars": self._to_int(raw.get("min_text_chars"), 300, minimum=0, maximum=10000),
            "max_page_chars": self._to_int(raw.get("max_page_chars"), 60000, minimum=5000, maximum=250000),
            "table_settings": raw.get("table_settings") if isinstance(raw.get("table_settings"), dict) else {},
        }

    def _extract_pdfplumber_page(self, page: Any, page_num: int, opts: dict[str, Any], *, file_bytes: bytes) -> PdfPageExtraction:
        candidates: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {
            "page_width": float(getattr(page, "width", 0) or 0),
            "page_height": float(getattr(page, "height", 0) or 0),
        }

        layout_text = self._safe_extract_text(page, layout=True)
        simple_text = self._safe_extract_text(page, layout=False)
        words = self._safe_extract_words(page)
        metadata.update(
            {
                "raw_layout_chars": len(layout_text or ""),
                "raw_simple_chars": len(simple_text or ""),
                "word_count": len(words),
                "image_count": len(getattr(page, "images", []) or []),
            }
        )

        columns_detected = self._looks_two_column(words, float(getattr(page, "width", 0) or 0))
        metadata["columns_detected"] = columns_detected

        if opts["extraction_mode"] in {"auto", "layout"}:
            candidates.append(self._candidate("pdfplumber_layout", layout_text, page_num, opts, metadata))
        if opts["extraction_mode"] in {"auto", "simple"}:
            candidates.append(self._candidate("pdfplumber_simple", simple_text, page_num, opts, metadata))
        if opts["extraction_mode"] in {"auto", "columns"} and opts["detect_columns"] and columns_detected:
            columns_text = self._extract_columns_text(page, opts)
            candidates.append(self._candidate("pdfplumber_columns", columns_text, page_num, opts, metadata))

        if opts["extract_tables"]:
            table_md, table_meta = self._extract_tables_markdown(page)
            metadata.update(table_meta)
        else:
            table_md = ""
            metadata.update({"table_count": 0, "table_cells": 0})

        best = self._select_best_candidate(candidates)
        text = (best.get("text") or "").strip()
        method = str(best.get("method") or "pdfplumber_empty")
        warnings = list(best.get("warnings") or [])
        quality = float(best.get("quality_score") or 0.0)

        if table_md:
            text = f"{text}\n\n{table_md}".strip() if text else table_md.strip()
            warnings.append("tables_detected")

        if opts["ocr_enabled"] and (len(text) < opts["min_text_chars"] or opts["extraction_mode"] == "ocr"):
            ocr_text, ocr_warning = self._try_ocr_page(file_bytes, page_num, opts)
            if ocr_text and self._score_text(ocr_text, method="ocr", opts=opts, metadata=metadata) > quality:
                text = self._clean_page_text(ocr_text, opts)
                method = "ocr_tesseract"
                quality = self._score_text(text, method=method, opts=opts, metadata=metadata)
                warnings.append("ocr_used")
            elif ocr_warning:
                warnings.append(ocr_warning)

        text = self._trim_page_text(text, opts["max_page_chars"])
        final_meta = dict(metadata)
        final_meta.update(best.get("metadata") or {})
        final_meta["final_chars"] = len(text)
        final_meta["method_selected"] = method

        if not text.strip():
            warnings.append("empty_text")
        elif len(text) < opts["min_text_chars"]:
            warnings.append("low_text_chars")
        if columns_detected and method != "pdfplumber_columns":
            warnings.append("possible_two_columns")
        if metadata.get("image_count", 0) and len(text) < opts["min_text_chars"]:
            warnings.append("possible_scanned_page")

        quality = self._score_text(text, method=method, opts=opts, metadata=final_meta)
        final_meta["quality_components"] = self._quality_components(text, metadata=final_meta)

        return PdfPageExtraction(
            page_number=page_num,
            text=text,
            method=method,
            quality_score=round(max(0.0, min(1.0, quality)), 3),
            warnings=sorted(set(warnings)),
            metadata=final_meta,
        )

    def _safe_extract_text(self, page: Any, *, layout: bool) -> str:
        try:
            if layout:
                return page.extract_text(layout=True, x_tolerance=2, y_tolerance=3) or ""
            return page.extract_text(x_tolerance=2, y_tolerance=3) or ""
        except TypeError:
            try:
                return page.extract_text(layout=layout) or ""
            except Exception:
                return ""
        except Exception:
            return ""

    def _safe_extract_words(self, page: Any) -> list[dict[str, Any]]:
        try:
            return page.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False, use_text_flow=False) or []
        except TypeError:
            try:
                return page.extract_words() or []
            except Exception:
                return []
        except Exception:
            return []

    def _extract_columns_text(self, page: Any, opts: dict[str, Any]) -> str:
        width = float(getattr(page, "width", 0) or 0)
        height = float(getattr(page, "height", 0) or 0)
        if width <= 0 or height <= 0:
            return ""
        gutter = max(12.0, width * 0.025)
        mid = width / 2.0
        boxes = [
            (0, 0, mid - gutter / 2, height),
            (mid + gutter / 2, 0, width, height),
        ]
        parts: list[str] = []
        for box in boxes:
            try:
                crop = page.crop(box)
                text = self._safe_extract_text(crop, layout=True) or self._safe_extract_text(crop, layout=False)
                text = self._clean_page_text(text, opts)
                if text:
                    parts.append(text)
            except Exception:
                continue
        return "\n\n".join(parts).strip()

    def _looks_two_column(self, words: list[dict[str, Any]], width: float) -> bool:
        if width <= 0 or len(words) < 80:
            return False
        left = right = middle = 0
        for word in words:
            try:
                x0 = float(word.get("x0") or 0)
                x1 = float(word.get("x1") or x0)
                center = (x0 + x1) / 2
            except Exception:
                continue
            if center < width * 0.43:
                left += 1
            elif center > width * 0.57:
                right += 1
            else:
                middle += 1
        total = left + right + middle
        if total <= 0:
            return False
        return left / total > 0.25 and right / total > 0.25 and middle / total < 0.28

    def _candidate(self, method: str, raw_text: str, page_num: int, opts: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        cleaned = self._clean_page_text(raw_text or "", opts)
        score = self._score_text(cleaned, method=method, opts=opts, metadata=metadata)
        warnings: list[str] = []
        if not cleaned:
            warnings.append("empty_text")
        if "columns" in method:
            warnings.append("two_column_mode")
        if self._has_many_broken_lines(cleaned):
            warnings.append("many_short_lines")
        return {"method": method, "text": cleaned, "quality_score": score, "warnings": warnings, "metadata": {"page": page_num}}

    def _select_best_candidate(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        if not candidates:
            return {"method": "empty", "text": "", "quality_score": 0.0, "warnings": ["no_candidates"], "metadata": {}}
        return max(candidates, key=lambda item: float(item.get("quality_score") or 0.0))

    # ------------------------------------------------------------------
    # Cleaning / quality
    # ------------------------------------------------------------------
    def _clean_page_text(self, raw: str, opts: dict[str, Any]) -> str:
        text = unicodedata.normalize("NFKC", raw or "")
        text = text.replace("\u00ad", "")
        text = _CONTROL_RE.sub(" ", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        if opts.get("merge_hyphenated_words", True):
            text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
        text = self._protect_formula_candidates(text) if opts.get("mark_formula_candidates", True) else text
        text = self._normalize_paragraph_breaks(text)
        return text.strip()

    def _protect_formula_candidates(self, text: str) -> str:
        lines = [line.strip() for line in (text or "").splitlines()]
        output: list[str] = []
        for line in lines:
            if not line:
                output.append("")
                continue
            math_hits = len(_MATH_SYMBOL_RE.findall(line))
            is_shortish = len(line) <= 180
            has_letters = bool(re.search(r"[A-Za-zА-Яа-я]", line))
            # Do not wrap ordinary prose with one equality sign, only dense formula-like lines.
            if is_shortish and math_hits >= 2 and (not has_letters or len(line.split()) <= 14):
                output.extend(["", "[Formula candidate]", line, ""])
            else:
                output.append(line)
        return "\n".join(output)

    def _normalize_paragraph_breaks(self, text: str) -> str:
        # Collapse excessive blank lines but preserve formula/table block separation.
        lines = [line.rstrip() for line in text.splitlines()]
        cleaned: list[str] = []
        blank_seen = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if not blank_seen:
                    cleaned.append("")
                blank_seen = True
                continue
            cleaned.append(stripped)
            blank_seen = False
        return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip()

    def _remove_repeating_headers_footers(self, pages: list[PdfPageExtraction]) -> list[PdfPageExtraction]:
        if len(pages) < 3:
            return pages

        def edge_lines(text: str) -> list[str]:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            return lines[:3] + lines[-3:]

        counts: dict[str, int] = {}
        originals: dict[str, str] = {}
        for page in pages:
            for line in edge_lines(page.text):
                key = self._line_key(line)
                if not key or len(key) < 5:
                    continue
                counts[key] = counts.get(key, 0) + 1
                originals[key] = line

        threshold = max(2, math.ceil(len(pages) * 0.45))
        repeated = {key for key, count in counts.items() if count >= threshold}
        if not repeated:
            return pages

        for page in pages:
            new_lines: list[str] = []
            removed = 0
            for line in page.text.splitlines():
                stripped = line.strip()
                key = self._line_key(stripped)
                if key in repeated or _PAGE_NUMBER_RE.match(stripped):
                    removed += 1
                    continue
                new_lines.append(line)
            if removed:
                page.text = self._normalize_paragraph_breaks("\n".join(new_lines))
                page.warnings = sorted(set([*page.warnings, "headers_footers_removed"]))
                page.metadata["removed_repeated_lines"] = removed
                page.metadata["repeated_line_keys"] = sorted(repeated)[:20]
                page.quality_score = round(self._score_text(page.text, method=page.method, opts={}, metadata=page.metadata), 3)
        return pages

    def _line_key(self, line: str) -> str:
        value = unicodedata.normalize("NFKC", line or "").casefold()
        value = re.sub(r"\d+", "#", value)
        value = re.sub(r"\s+", " ", value).strip(" -–—|·")
        if _DOI_FOOTER_RE.search(value):
            return value[:120]
        return value[:120]

    def _has_many_broken_lines(self, text: str) -> bool:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if len(lines) < 20:
            return False
        short = sum(1 for line in lines if len(line) < 35)
        return short / max(1, len(lines)) > 0.55

    def _quality_components(self, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
        chars = len(text or "")
        words = len(re.findall(r"\w+", text or ""))
        non_ascii_noise = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\t")
        replacement_chars = (text or "").count("�")
        return {
            "chars": chars,
            "words": words,
            "line_count": len((text or "").splitlines()),
            "replacement_chars": replacement_chars,
            "control_noise": non_ascii_noise,
            "image_count": metadata.get("image_count", 0),
            "table_count": metadata.get("table_count", 0),
        }

    def _score_text(self, text: str, *, method: str, opts: dict[str, Any], metadata: dict[str, Any]) -> float:
        value = text or ""
        chars = len(value.strip())
        if chars == 0:
            return 0.0
        words = len(re.findall(r"\w+", value))
        score = 0.15
        score += min(0.35, chars / 8000)
        score += min(0.25, words / 900)
        if method == "pdfplumber_columns":
            score += 0.08
        if method == "ocr_tesseract":
            score += 0.05
        if self._has_many_broken_lines(value):
            score -= 0.08
        if value.count("�"):
            score -= min(0.12, value.count("�") / 20)
        if metadata.get("table_count"):
            score += 0.03
        if metadata.get("image_count", 0) and chars < int(opts.get("min_text_chars") or 300):
            score -= 0.15
        return max(0.0, min(1.0, score))

    def _trim_page_text(self, text: str, max_chars: int) -> str:
        value = (text or "").strip()
        if len(value) <= max_chars:
            return value
        cut = value[:max_chars]
        # Prefer to cut on paragraph boundary.
        boundary = cut.rfind("\n\n")
        if boundary > max_chars * 0.65:
            cut = cut[:boundary]
        return cut.rstrip() + "\n\n[Truncated by PDF extraction max_page_chars]"

    # ------------------------------------------------------------------
    # Tables / OCR
    # ------------------------------------------------------------------
    def _extract_tables_markdown(self, page: Any) -> tuple[str, dict[str, Any]]:
        try:
            tables = page.extract_tables() or []
        except Exception:
            return "", {"table_count": 0, "table_cells": 0, "table_error": "extract_failed"}

        blocks: list[str] = []
        cell_count = 0
        for table_idx, table in enumerate(tables, start=1):
            if not table:
                continue
            markdown = self._table_to_markdown(table)
            if markdown:
                blocks.append(f"[Table candidate {table_idx}]\n\n{markdown}")
                cell_count += sum(len(row or []) for row in table)
        return "\n\n".join(blocks).strip(), {"table_count": len(blocks), "table_cells": cell_count}

    def _table_to_markdown(self, table: list[list[str | None]]) -> str:
        rows: list[list[str]] = []
        max_cols = 0
        for row in table:
            if not row:
                continue
            cleaned = [self._clean_table_cell(cell) for cell in row]
            if not any(cleaned):
                continue
            max_cols = max(max_cols, len(cleaned))
            rows.append(cleaned)
        if not rows or max_cols <= 1:
            return ""
        normalized = [row + [""] * (max_cols - len(row)) for row in rows]
        header = normalized[0]
        body = normalized[1:] or [[""] * max_cols]
        out = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(["---"] * max_cols) + " |",
        ]
        out.extend("| " + " | ".join(row) + " |" for row in body)
        return "\n".join(out)

    def _clean_table_cell(self, cell: str | None) -> str:
        text = unicodedata.normalize("NFKC", str(cell or ""))
        text = _CONTROL_RE.sub(" ", text)
        text = text.replace("|", "\\|")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _try_ocr_page(self, file_bytes: bytes, page_number: int, opts: dict[str, Any]) -> tuple[str, str | None]:
        """Optional OCR. Does nothing unless PyMuPDF + pytesseract are installed."""
        try:
            import fitz  # PyMuPDF
            import pytesseract
            from PIL import Image
        except Exception:
            return "", "ocr_dependencies_missing"

        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            try:
                page = doc.load_page(page_number - 1)
                dpi = int(opts.get("ocr_dpi") or 220)
                zoom = dpi / 72.0
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                image = Image.open(io.BytesIO(pix.tobytes("png")))
                text = pytesseract.image_to_string(image, lang=str(opts.get("ocr_languages") or "eng+rus"))
                return text or "", None
            finally:
                doc.close()
        except Exception as exc:
            logger.warning("OCR failed for page %s: %s", page_number, exc)
            return "", "ocr_failed"

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def _pages_to_legacy_text(self, pages: Iterable[PdfPageExtraction]) -> str:
        blocks = []
        for page in pages:
            if page.text.strip():
                blocks.append(f"[Страница {page.page_number}]\n{page.text.strip()}")
        return "\n\n".join(blocks).strip()

    def _to_bool(self, value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on", "да"}
        if value is None:
            return default
        return bool(value)

    def _to_int(self, value: Any, default: int, *, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))


# Глобальный экземпляр PDF парсера
pdf_parser = PDFParser(chunk_size=1000, chunk_overlap=200)
