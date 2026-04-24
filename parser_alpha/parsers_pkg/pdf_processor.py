"""Universal PDF processing module for all parsers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from loguru import logger

try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False
    logger.warning("PyPDF2 not installed. PDF text extraction will be unavailable.")

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    logger.warning("pdfplumber not installed. Advanced PDF extraction will be unavailable.")


class PDFProcessor:
    """Universal PDF processor for extracting and analyzing scientific papers."""
    
    def __init__(self):
        self.pypdf2_available = PYPDF2_AVAILABLE
        self.pdfplumber_available = PDFPLUMBER_AVAILABLE
    
    def extract_text_from_pdf(self, pdf_path: str | Path) -> str | None:
        """
        Extract text from PDF file using available libraries.
        
        Tries pdfplumber first (better quality), falls back to PyPDF2.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Extracted text or None if extraction failed
        """
        pdf_path = Path(pdf_path)
        
        if not pdf_path.exists():
            logger.error(f"PDF file not found: {pdf_path}")
            return None
        
        # Try pdfplumber first (better quality)
        if self.pdfplumber_available:
            try:
                text = self._extract_with_pdfplumber(pdf_path)
                if text:
                    logger.info(f"Extracted {len(text)} characters from {pdf_path.name} using pdfplumber")
                    return text
            except Exception as e:
                logger.warning(f"pdfplumber extraction failed for {pdf_path.name}: {e}")
        
        # Fallback to PyPDF2
        if self.pypdf2_available:
            try:
                text = self._extract_with_pypdf2(pdf_path)
                if text:
                    logger.info(f"Extracted {len(text)} characters from {pdf_path.name} using PyPDF2")
                    return text
            except Exception as e:
                logger.error(f"PyPDF2 extraction failed for {pdf_path.name}: {e}")
        
        logger.error(f"No PDF extraction library available or all methods failed for {pdf_path.name}")
        return None
    
    def _extract_with_pdfplumber(self, pdf_path: Path) -> str | None:
        """Extract text using pdfplumber."""
        import pdfplumber
        
        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        
        return "\n\n".join(text_parts) if text_parts else None
    
    def _extract_with_pypdf2(self, pdf_path: Path) -> str | None:
        """Extract text using PyPDF2."""
        import PyPDF2
        
        text_parts = []
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page in pdf_reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        
        return "\n\n".join(text_parts) if text_parts else None
    
    def create_summary(self, text: str, max_sentences: int = 3) -> str:
        """
        Create a brief summary from the text.
        
        Extracts key sentences from abstract or introduction.
        
        Args:
            text: Full text of the paper
            max_sentences: Maximum number of sentences in summary
            
        Returns:
            Summary text
        """
        if not text:
            return ""
        
        # Try to find abstract section
        abstract = self._extract_section(text, ["abstract", "аннотация", "резюме"])
        if abstract:
            sentences = self._split_into_sentences(abstract)
            return " ".join(sentences[:max_sentences])
        
        # Fallback to first few sentences
        sentences = self._split_into_sentences(text)
        return " ".join(sentences[:max_sentences])
    
    def analyze_paper(self, text: str, metadata: dict[str, Any]) -> str:
        """
        Analyze paper and create analysis text.
        
        Includes:
        - Paper type and domain
        - Key findings
        - Methodology
        - Relevance assessment
        
        Args:
            text: Full text of the paper
            metadata: Paper metadata (title, authors, year, etc.)
            
        Returns:
            Analysis text in Russian
        """
        if not text:
            return "Анализ недоступен: текст статьи не извлечен."
        
        analysis_parts = []
        
        # Basic info
        title = metadata.get("title", "Без названия")
        year = metadata.get("publication_date", "")
        if year:
            year = str(year)[:4]
        
        analysis_parts.append(f"Статья: {title}")
        if year:
            analysis_parts.append(f"Год публикации: {year}")
        
        # Detect paper type
        paper_type = self._detect_paper_type(text)
        analysis_parts.append(f"Тип работы: {paper_type}")
        
        # Extract key topics
        topics = self._extract_key_topics(text)
        if topics:
            analysis_parts.append(f"Ключевые темы: {', '.join(topics[:5])}")
        
        # Check for metallurgy relevance
        relevance = self._assess_metallurgy_relevance(text)
        analysis_parts.append(f"Релевантность для металлургии: {relevance}")
        
        return "\n".join(analysis_parts)
    
    def _extract_section(self, text: str, section_names: list[str]) -> str | None:
        """Extract a specific section from the text."""
        text_lower = text.lower()
        
        for section_name in section_names:
            # Look for section header
            pattern = rf"\b{section_name}\b[\s:]*\n(.*?)(?:\n\n|\n[A-Z]{{2,}}|\Z)"
            match = re.search(pattern, text_lower, re.DOTALL | re.IGNORECASE)
            if match:
                # Get the actual text (not lowercased)
                start = match.start(1)
                end = match.end(1)
                return text[start:end].strip()
        
        return None
    
    def _split_into_sentences(self, text: str) -> list[str]:
        """Split text into sentences."""
        # Simple sentence splitter
        sentences = re.split(r'[.!?]+\s+', text)
        return [s.strip() for s in sentences if len(s.strip()) > 20]
    
    def _detect_paper_type(self, text: str) -> str:
        """Detect the type of scientific paper."""
        text_lower = text.lower()
        
        if any(word in text_lower for word in ["review", "обзор", "survey"]):
            return "Обзорная статья"
        elif any(word in text_lower for word in ["experimental", "эксперимент", "measurement"]):
            return "Экспериментальное исследование"
        elif any(word in text_lower for word in ["simulation", "modeling", "моделирование"]):
            return "Моделирование"
        elif any(word in text_lower for word in ["theoretical", "теоретическ"]):
            return "Теоретическое исследование"
        else:
            return "Исследовательская статья"
    
    def _extract_key_topics(self, text: str) -> list[str]:
        """Extract key topics from the text."""
        # Metallurgy-specific keywords
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
        """Assess relevance to metallurgy."""
        topics = self._extract_key_topics(text)
        
        if len(topics) >= 5:
            return "Высокая (прямое отношение к металлургии)"
        elif len(topics) >= 3:
            return "Средняя (частичное отношение к металлургии)"
        elif len(topics) >= 1:
            return "Низкая (косвенное отношение к металлургии)"
        else:
            return "Не определена"
    
    def needs_translation(self, text: str) -> bool:
        """
        Check if text needs translation to Russian.
        
        Args:
            text: Text to check
            
        Returns:
            True if text is not in Russian
        """
        if not text:
            return False
        
        # Simple heuristic: check for Cyrillic characters
        cyrillic_chars = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
        total_chars = sum(1 for c in text if c.isalpha())
        
        if total_chars == 0:
            return False
        
        # If less than 30% Cyrillic, assume it needs translation
        return (cyrillic_chars / total_chars) < 0.3
    
    def process_paper_pdf(
        self,
        pdf_path: str | Path,
        metadata: dict[str, Any],
        create_translation: bool = True,
    ) -> dict[str, str]:
        """
        Complete PDF processing pipeline.
        
        Args:
            pdf_path: Path to PDF file
            metadata: Paper metadata
            create_translation: Whether to create translation placeholder
            
        Returns:
            Dictionary with:
            - full_text: Extracted text
            - summary_ru: Brief summary in Russian
            - analysis_ru: Analysis in Russian
            - translation_ru: Translation placeholder or None
        """
        result = {
            "full_text": None,
            "summary_ru": None,
            "analysis_ru": None,
            "translation_ru": None,
        }
        
        # Extract text
        text = self.extract_text_from_pdf(pdf_path)
        if not text:
            logger.error(f"Failed to extract text from {pdf_path}")
            result["analysis_ru"] = "Ошибка: не удалось извлечь текст из PDF"
            return result
        
        result["full_text"] = text
        
        # Create summary
        summary = self.create_summary(text)
        if summary:
            # If summary is in English, add note
            if self.needs_translation(summary):
                result["summary_ru"] = f"[EN] {summary}\n\n[Требуется перевод]"
            else:
                result["summary_ru"] = summary
        
        # Create analysis
        result["analysis_ru"] = self.analyze_paper(text, metadata)
        
        # Translation placeholder
        if create_translation and self.needs_translation(text):
            abstract = self._extract_section(text, ["abstract"])
            if abstract:
                result["translation_ru"] = f"[Требуется перевод аннотации]\n\nОригинал:\n{abstract[:500]}..."
        
        return result


# Global instance
pdf_processor = PDFProcessor()