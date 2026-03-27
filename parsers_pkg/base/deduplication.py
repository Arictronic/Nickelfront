"""
Улучшенная дедупликация для парсеров.

Использует несколько стратегий для обнаружения дубликатов:
- Точное совпадение DOI
- Точное совпадение source_id
- Similarity заголовков (Levenshtein distance)
- Similarity контента (Jaccard similarity)
"""

import re
from typing import Optional, List, Tuple
from difflib import SequenceMatcher
from dataclasses import dataclass


@dataclass
class DeduplicationResult:
    """Результат проверки на дубликат."""
    is_duplicate: bool
    confidence: float  # 0.0 - 1.0
    reason: str
    matched_existing_id: Optional[int] = None


class TextNormalizer:
    """Нормализация текста для сравнения."""
    
    @staticmethod
    def normalize(text: str) -> str:
        """Нормализовать текст."""
        if not text:
            return ""
        
        # Привести к нижнему регистру
        text = text.lower()
        
        # Удалить специальные символы
        text = re.sub(r'[^\w\s]', ' ', text)
        
        # Удалить лишние пробелы
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    @staticmethod
    def get_words(text: str) -> set:
        """Получить множество слов из текста."""
        normalized = TextNormalizer.normalize(text)
        words = set(normalized.split())
        
        # Удалить стоп-слова
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
            'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
            'dare', 'ought', 'used', 'this', 'that', 'these', 'those', 'i', 'you',
            'he', 'she', 'it', 'we', 'they', 'what', 'which', 'who', 'whom',
        }
        words = words - stop_words
        
        return words


class Deduplicator:
    """Сервис дедупликации."""
    
    # Пороги для различных стратегий
    DOI_MATCH_THRESHOLD = 1.0
    TITLE_SIMILARITY_THRESHOLD = 0.85
    CONTENT_SIMILARITY_THRESHOLD = 0.75
    
    def __init__(self, existing_papers: List[dict] = None):
        """
        Инициализация дедупликатора.
        
        Args:
            existing_papers: Список существующих статей для сравнения
        """
        self.existing_papers = existing_papers or []
    
    def check_duplicate(
        self,
        title: str,
        doi: Optional[str] = None,
        source_id: Optional[str] = None,
        abstract: Optional[str] = None,
    ) -> DeduplicationResult:
        """
        Проверить статью на дубликат.
        
        Args:
            title: Заголовок статьи
            doi: DOI статьи
            source_id: ID в источнике
            abstract: Аннотация
            
        Returns:
            DeduplicationResult с результатом проверки
        """
        # 1. Проверка по DOI (самая надёжная)
        if doi:
            result = self._check_by_doi(doi)
            if result.is_duplicate:
                return result
        
        # 2. Проверка по source_id
        if source_id:
            result = self._check_by_source_id(source_id)
            if result.is_duplicate:
                return result
        
        # 3. Проверка по similarity заголовка
        result = self._check_by_title_similarity(title)
        if result.is_duplicate and result.confidence >= self.TITLE_SIMILARITY_THRESHOLD:
            return result
        
        # 4. Проверка по similarity контента (если есть аннотация)
        if abstract:
            result = self._check_by_content_similarity(title, abstract)
            if result.is_duplicate and result.confidence >= self.CONTENT_SIMILARITY_THRESHOLD:
                return result
        
        # Не найдено дубликатов
        return DeduplicationResult(
            is_duplicate=False,
            confidence=0.0,
            reason="No duplicate found",
        )
    
    def _check_by_doi(self, doi: str) -> DeduplicationResult:
        """Проверка по DOI."""
        doi_normalized = doi.lower().strip()
        
        for paper in self.existing_papers:
            existing_doi = paper.get("doi", "")
            if existing_doi and existing_doi.lower().strip() == doi_normalized:
                return DeduplicationResult(
                    is_duplicate=True,
                    confidence=1.0,
                    reason="Exact DOI match",
                    matched_existing_id=paper.get("id"),
                )
        
        return DeduplicationResult(
            is_duplicate=False,
            confidence=0.0,
            reason="DOI not found in existing papers",
        )
    
    def _check_by_source_id(self, source_id: str) -> DeduplicationResult:
        """Проверка по source_id."""
        for paper in self.existing_papers:
            existing_source_id = paper.get("source_id", "")
            if existing_source_id and existing_source_id == source_id:
                return DeduplicationResult(
                    is_duplicate=True,
                    confidence=1.0,
                    reason="Exact source_id match",
                    matched_existing_id=paper.get("id"),
                )
        
        return DeduplicationResult(
            is_duplicate=False,
            confidence=0.0,
            reason="Source ID not found in existing papers",
        )
    
    def _check_by_title_similarity(self, title: str) -> DeduplicationResult:
        """Проверка по similarity заголовка."""
        if not title or not self.existing_papers:
            return DeduplicationResult(
                is_duplicate=False,
                confidence=0.0,
                reason="No title or existing papers",
            )
        
        best_match = None
        best_confidence = 0.0
        
        for paper in self.existing_papers:
            existing_title = paper.get("title", "")
            if not existing_title:
                continue
            
            # Вычислить similarity
            confidence = self._calculate_title_similarity(title, existing_title)
            
            if confidence > best_confidence:
                best_confidence = confidence
                best_match = paper
        
        if best_confidence >= self.TITLE_SIMILARITY_THRESHOLD:
            return DeduplicationResult(
                is_duplicate=True,
                confidence=best_confidence,
                reason=f"Title similarity: {best_confidence:.2f}",
                matched_existing_id=best_match.get("id") if best_match else None,
            )
        
        return DeduplicationResult(
            is_duplicate=False,
            confidence=best_confidence,
            reason=f"Title similarity below threshold: {best_confidence:.2f}",
        )
    
    def _check_by_content_similarity(
        self,
        title: str,
        abstract: str,
    ) -> DeduplicationResult:
        """Проверка по similarity контента."""
        if not title or not abstract or not self.existing_papers:
            return DeduplicationResult(
                is_duplicate=False,
                confidence=0.0,
                reason="No content or existing papers",
            )
        
        best_match = None
        best_confidence = 0.0
        
        for paper in self.existing_papers:
            existing_title = paper.get("title", "")
            existing_abstract = paper.get("abstract", "")
            
            if not existing_title or not existing_abstract:
                continue
            
            # Вычислить similarity заголовков
            title_sim = self._calculate_title_similarity(title, existing_title)
            
            # Вычислить similarity аннотаций
            abstract_sim = self._calculate_content_similarity(abstract, existing_abstract)
            
            # Комбинированный score
            confidence = (title_sim * 0.4) + (abstract_sim * 0.6)
            
            if confidence > best_confidence:
                best_confidence = confidence
                best_match = paper
        
        if best_confidence >= self.CONTENT_SIMILARITY_THRESHOLD:
            return DeduplicationResult(
                is_duplicate=True,
                confidence=best_confidence,
                reason=f"Content similarity: {best_confidence:.2f}",
                matched_existing_id=best_match.get("id") if best_match else None,
            )
        
        return DeduplicationResult(
            is_duplicate=False,
            confidence=best_confidence,
            reason=f"Content similarity below threshold: {best_confidence:.2f}",
        )
    
    def _calculate_title_similarity(self, title1: str, title2: str) -> float:
        """
        Вычислить similarity между заголовками.
        
        Использует SequenceMatcher для вычисления ratio.
        """
        norm1 = TextNormalizer.normalize(title1)
        norm2 = TextNormalizer.normalize(title2)
        
        if not norm1 or not norm2:
            return 0.0
        
        return SequenceMatcher(None, norm1, norm2).ratio()
    
    def _calculate_content_similarity(self, text1: str, text2: str) -> float:
        """
        Вычислить similarity между текстами.
        
        Использует Jaccard similarity для множеств слов.
        """
        words1 = TextNormalizer.get_words(text1)
        words2 = TextNormalizer.get_words(text2)
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        
        return intersection / union if union > 0 else 0.0
    
    def add_existing_paper(self, paper: dict):
        """Добавить статью в список существующих."""
        self.existing_papers.append(paper)
    
    def clear_existing_papers(self):
        """Очистить список существующих статей."""
        self.existing_papers.clear()


def check_duplicate(
    title: str,
    doi: Optional[str] = None,
    source_id: Optional[str] = None,
    abstract: Optional[str] = None,
    existing_papers: Optional[List[dict]] = None,
) -> DeduplicationResult:
    """
    Быстрая проверка на дубликат.
    
    Args:
        title: Заголовок статьи
        doi: DOI статьи
        source_id: ID в источнике
        abstract: Аннотация
        existing_papers: Список существующих статей
        
    Returns:
        DeduplicationResult с результатом проверки
    """
    deduplicator = Deduplicator(existing_papers)
    return deduplicator.check_duplicate(title, doi, source_id, abstract)


if __name__ == "__main__":
    # Пример использования
    existing = [
        {
            "id": 1,
            "title": "Nickel-based superalloys for high-temperature applications",
            "doi": "10.1234/test.2024.001",
            "abstract": "This paper presents a review of nickel-based superalloys...",
        },
    ]
    
    # Проверка по DOI
    result = check_duplicate(
        title="Nickel-based superalloys for high-temperature applications",
        doi="10.1234/test.2024.001",
        existing_papers=existing,
    )
    print(f"DOI check: is_duplicate={result.is_duplicate}, confidence={result.confidence}")
    
    # Проверка по similarity заголовка
    result = check_duplicate(
        title="Nickel based superalloys for high temperature applications",  # Немного другой
        doi=None,
        existing_papers=existing,
    )
    print(f"Title check: is_duplicate={result.is_duplicate}, confidence={result.confidence}")
