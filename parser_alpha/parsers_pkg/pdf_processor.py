"""Compatibility wrapper for PDF processing used by parser_alpha.

The project has one canonical PDF extraction implementation:
``backend.app.services.pdf_content_parser.PDFParser``.  Older parser_alpha code used a
separate pdfplumber/PyPDF2 pipeline here, which produced text of different
quality from the backend content pipeline.  This module deliberately stays as a
thin adapter so all parsers receive the same cleaned/layout-aware PDF text.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from loguru import logger

PARSER_ALPHA_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PARSER_ALPHA_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
for _path in (PROJECT_ROOT, BACKEND_DIR, PARSER_ALPHA_DIR):
    _path_str = str(_path)
    if _path.exists() and _path_str not in sys.path:
        sys.path.insert(0, _path_str)


def _is_missing_import_path(exc: ModuleNotFoundError, roots: tuple[str, ...]) -> bool:
    """Detect only missing package roots, not failures inside parser modules."""

    missing = str(getattr(exc, "name", "") or "")
    return any(missing == root or missing.startswith(f"{root}.") for root in roots)


try:
    from app.services.pdf_content_parser import PDFParser as CanonicalPDFParser
    from app.services.pdf_content_parser import PdfExtractionError
except ModuleNotFoundError as exc:
    if not _is_missing_import_path(exc, ("app",)):
        raise
    try:
        from backend.app.services.pdf_content_parser import PDFParser as CanonicalPDFParser
        from backend.app.services.pdf_content_parser import PdfExtractionError
    except ModuleNotFoundError as backend_exc:
        if not _is_missing_import_path(backend_exc, ("backend",)):
            raise
        CanonicalPDFParser = None
        PdfExtractionError = RuntimeError
        _IMPORT_ERROR = backend_exc
    else:
        _IMPORT_ERROR = None
else:
    _IMPORT_ERROR = None


class PDFProcessor:
    """Universal PDF processor for extracting and analyzing scientific papers.

    Extraction is delegated to ``backend.app.services.pdf_content_parser.PDFParser``.
    The summary/analysis helpers are kept for backward compatibility with
    parser_alpha callers.
    """

    def __init__(self, parser: Any | None = None):
        if parser is not None:
            self.parser = parser
            return
        if CanonicalPDFParser is None:
            raise RuntimeError(
                "Canonical PDFParser is unavailable. Run parser_alpha from the "
                f"Nickelfront project root. Import error: {_IMPORT_ERROR}"
            )
        self.parser = CanonicalPDFParser()

    def parse_bytes(
        self,
        file_bytes: bytes,
        filename: str = "unknown.pdf",
        metadata: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return structured parser content for bytes callers."""

        try:
            return self.parser.parse_bytes(
                file_bytes,
                filename=filename,
                metadata=metadata,
                options=options,
            )
        except Exception as exc:
            logger.exception(f"PDF parse_bytes failed for {filename}: {exc}")
            raise

    def extract_content(
        self,
        pdf_path: str | Path | None = None,
        *,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        metadata: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return structured final text/pages/content_blocks."""

        if file_bytes is not None:
            return self.parser.extract_content(
                file_bytes=file_bytes,
                filename=filename or "unknown.pdf",
                metadata=metadata,
                options=options,
            )
        if pdf_path is None:
            raise ValueError("extract_content expects pdf_path or file_bytes")
        return self.parser.extract_content(
            file_path=str(pdf_path),
            filename=filename,
            metadata=metadata,
            options=options,
        )

    def extract_text_from_pdf(self, pdf_path: str | Path) -> str | None:
        """Extract text from a PDF file using the canonical project parser."""
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            logger.error(f"PDF file not found: {pdf_path}")
            return None
        try:
            text = self.parser.extract_text_from_file(str(pdf_path))
            if text:
                logger.info(f"Extracted {len(text)} characters from {pdf_path.name} using canonical PDFParser")
                return text
            logger.warning(f"Canonical PDFParser returned empty text for {pdf_path.name}")
            return None
        except Exception as exc:
            logger.exception(f"PDF extraction failed for {pdf_path.name}: {exc}")
            return None

    def extract_content_from_pdf(self, pdf_path: str | Path, metadata: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Extract structured final content blocks for downstream RAG/Qwen adapters."""
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            logger.error(f"PDF file not found: {pdf_path}")
            return None
        try:
            content = self.parser.extract_content_from_file(str(pdf_path), metadata=metadata)
            part_count = len(content.get("content_parts") or [])
            logger.info(f"Extracted {part_count} structured content parts from {pdf_path.name}")
            return content
        except Exception as exc:
            logger.exception(f"Structured PDF extraction failed for {pdf_path.name}: {exc}")
            return None

    def extract_qwen_markdown_from_pdf(self, pdf_path: str | Path, metadata: dict[str, Any] | None = None) -> str | None:
        """Extract Qwen-ready markdown from structured parser content parts."""
        content = self.extract_content_from_pdf(pdf_path, metadata=metadata)
        if not content:
            return None
        markdown = str(content.get("qwen_markdown") or "").strip()
        return markdown or None

    def create_summary(self, text: str, max_sentences: int = 3) -> str:
        """Create a brief summary from the text."""
        if not text:
            return ""

        abstract = self._extract_section(text, ["abstract", "аннотация", "резюме"])
        if abstract:
            sentences = self._split_into_sentences(abstract)
            return " ".join(sentences[:max_sentences])

        sentences = self._split_into_sentences(text)
        return " ".join(sentences[:max_sentences])

    def analyze_paper(self, text: str, metadata: dict[str, Any]) -> str:
        """Analyze paper and create a compact Russian analysis text."""
        if not text:
            return "Анализ недоступен: текст статьи не извлечен."

        analysis_parts = []
        title = metadata.get("title", "Без названия")
        year = metadata.get("publication_date", "")
        if year:
            year = str(year)[:4]

        analysis_parts.append(f"Статья: {title}")
        if year:
            analysis_parts.append(f"Год публикации: {year}")

        paper_type = self._detect_paper_type(text)
        analysis_parts.append(f"Тип работы: {paper_type}")

        topics = self._extract_key_topics(text)
        if topics:
            analysis_parts.append(f"Ключевые темы: {', '.join(topics[:5])}")

        relevance = self._assess_metallurgy_relevance(text)
        analysis_parts.append(f"Релевантность для металлургии: {relevance}")
        return "\n".join(analysis_parts)

    def _extract_section(self, text: str, section_names: list[str]) -> str | None:
        """Extract a section without applying lower-case indexes to original text."""
        if not text:
            return None
        for section_name in section_names:
            pattern = rf"(?im)^\s*(?:\d+(?:\.\d+)*\.?\s+)?{re.escape(section_name)}\s*:?\s*$"
            match = re.search(pattern, text)
            if not match:
                continue
            start = match.end()
            next_header = re.search(
                r"(?m)^\s*(?:\d+(?:\.\d+)*\.?\s+)?(?:abstract|keywords?|introduction|background|"
                r"related work|methodology|methods?|materials?|experimental setup|results?|discussion|"
                r"limitations|future work|conclusions?|references|acknowledg(?:e)?ments?|appendix|nomenclature)\b.*$",
                text[start:],
                flags=re.IGNORECASE,
            )
            end = start + next_header.start() if next_header else len(text)
            section_text = text[start:end].strip()
            return section_text or None
        return None

    def _split_into_sentences(self, text: str) -> list[str]:
        sentences = re.split(r"(?<=[.!?])\s+", text or "")
        return [s.strip() for s in sentences if len(s.strip()) > 20]

    def _detect_paper_type(self, text: str) -> str:
        text_lower = text.lower()
        if any(word in text_lower for word in ["review", "обзор", "survey"]):
            return "Обзорная статья"
        if any(word in text_lower for word in ["experimental", "эксперимент", "measurement"]):
            return "Экспериментальное исследование"
        if any(word in text_lower for word in ["simulation", "modeling", "моделирование"]):
            return "Моделирование"
        if any(word in text_lower for word in ["theoretical", "теоретическ"]):
            return "Теоретическое исследование"
        return "Исследовательская статья"

    def _extract_key_topics(self, text: str) -> list[str]:
        metallurgy_keywords = {
            "nickel": "никель",
            "alloy": "сплав",
            "superalloy": "суперсплав",
            "corrosion": "коррозия",
            "oxidation": "окисление",
            "microstructure": "микроструктура",
            "mechanical properties": "механические свойства",
            "heat treatment": "термообработка",
            "welding": "сварка",
            "casting": "литье",
            "forging": "ковка",
            "precipitation": "выделение",
            "strengthening": "упрочнение",
            "creep": "ползучесть",
            "fatigue": "усталость",
            "fracture": "разрушение",
        }
        text_lower = text.lower()
        found_topics = []
        for eng, rus in metallurgy_keywords.items():
            if eng in text_lower or rus in text_lower:
                found_topics.append(rus)
        return found_topics

    def _assess_metallurgy_relevance(self, text: str) -> str:
        text_lower = text.lower()
        high_relevance = ["nickel", "superalloy", "alloy", "metal", "microstructure"]
        medium_relevance = ["corrosion", "oxidation", "mechanical", "thermal", "materials"]

        high_count = sum(1 for word in high_relevance if word in text_lower)
        medium_count = sum(1 for word in medium_relevance if word in text_lower)

        if high_count >= 3:
            return "Высокая"
        if high_count >= 1 or medium_count >= 3:
            return "Средняя"
        return "Низкая"
