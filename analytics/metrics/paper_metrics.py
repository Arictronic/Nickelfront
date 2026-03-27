"""
Метрики анализа научных статей.

Модуль для вычисления статистики и метрик по статьям:
- Количество статей по источникам
- Распределение по датам публикаций
- Статистика по авторам
- Анализ ключевых слов
- Метрики полноты данных
"""

from datetime import datetime, date
from typing import Optional
from dataclasses import dataclass, field
from collections import Counter
import sys
from pathlib import Path

# Добавляем корень проекта в PATH
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

try:
    import polars as pl
    POLARS_AVAILABLE = True
except ImportError:
    POLARS_AVAILABLE = False
    pl = None

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None


@dataclass
class PaperMetrics:
    """Метрики анализа статей."""
    
    # Общая статистика
    total_count: int = 0
    core_count: int = 0
    arxiv_count: int = 0
    
    # Статистика по датам
    earliest_publication: Optional[date] = None
    latest_publication: Optional[date] = None
    avg_publication_year: Optional[float] = None
    
    # Распределение по годам
    publications_by_year: dict[int, int] = field(default_factory=dict)
    
    # Статистика по журналам
    top_journals: list[tuple[str, int]] = field(default_factory=list)
    
    # Статистика по авторам
    total_authors: int = 0
    avg_authors_per_paper: float = 0.0
    top_authors: list[tuple[str, int]] = field(default_factory=list)
    
    # Анализ ключевых слов
    total_keywords: int = 0
    avg_keywords_per_paper: float = 0.0
    top_keywords: list[tuple[str, int]] = field(default_factory=list)
    
    # Метрики полноты данных
    papers_with_abstract: int = 0
    papers_with_full_text: int = 0
    papers_with_keywords: int = 0
    papers_with_doi: int = 0
    completeness_score: float = 0.0
    
    # Статистика эмбеддингов
    papers_with_embedding: int = 0
    embedding_coverage: float = 0.0
    
    # Временные метки
    generated_at: datetime = field(default_factory=datetime.now)


class PaperMetricsService:
    """Сервис для вычисления метрик статей."""
    
    def __init__(self, papers_data: list[dict]):
        """
        Инициализация сервиса.
        
        Args:
            papers_data: Список словарей с данными статей
        """
        self.papers_data = papers_data
        
        if POLARS_AVAILABLE and papers_data:
            self.df = pl.DataFrame(papers_data)
        else:
            self.df = None
    
    def compute_metrics(self) -> PaperMetrics:
        """
        Вычислить все метрики.
        
        Returns:
            PaperMetrics с вычисленными метриками
        """
        metrics = PaperMetrics()
        
        if not self.papers_data:
            return metrics
        
        # Общая статистика
        metrics.total_count = len(self.papers_data)
        metrics.core_count = sum(1 for p in self.papers_data if p.get("source") == "CORE")
        metrics.arxiv_count = sum(1 for p in self.papers_data if p.get("source") == "arXiv")
        
        # Статистика по датам
        self._compute_date_metrics(metrics)
        
        # Статистика по журналам
        self._compute_journal_metrics(metrics)
        
        # Статистика по авторам
        self._compute_author_metrics(metrics)
        
        # Анализ ключевых слов
        self._compute_keyword_metrics(metrics)
        
        # Метрики полноты данных
        self._compute_completeness_metrics(metrics)
        
        # Статистика эмбеддингов
        self._compute_embedding_metrics(metrics)
        
        return metrics
    
    def _compute_date_metrics(self, metrics: PaperMetrics):
        """Вычислить метрики по датам публикаций."""
        publication_dates = []
        publication_years = []
        
        for paper in self.papers_data:
            pub_date = paper.get("publication_date")
            if pub_date:
                try:
                    if isinstance(pub_date, str):
                        pub_date = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                    elif isinstance(pub_date, datetime):
                        pass
                    else:
                        continue
                    
                    publication_dates.append(pub_date)
                    publication_years.append(pub_date.year)
                except (ValueError, TypeError):
                    continue
        
        if publication_dates:
            metrics.earliest_publication = min(publication_dates).date()
            metrics.latest_publication = max(publication_dates).date()
        
        if publication_years:
            metrics.avg_publication_year = sum(publication_years) / len(publication_years)
            metrics.publications_by_year = dict(Counter(publication_years))
    
    def _compute_journal_metrics(self, metrics: PaperMetrics):
        """Вычислить метрики по журналам."""
        journals = [
            p.get("journal") 
            for p in self.papers_data 
            if p.get("journal")
        ]
        
        if journals:
            journal_counts = Counter(journals)
            metrics.top_journals = journal_counts.most_common(10)
    
    def _compute_author_metrics(self, metrics: PaperMetrics):
        """Вычислить метрики по авторам."""
        all_authors = []
        author_counts = []
        
        for paper in self.papers_data:
            authors = paper.get("authors", [])
            if isinstance(authors, list):
                all_authors.extend(authors)
                author_counts.append(len(authors))
        
        metrics.total_authors = len(set(all_authors))
        
        if author_counts:
            metrics.avg_authors_per_paper = sum(author_counts) / len(author_counts)
            author_counter = Counter(all_authors)
            metrics.top_authors = author_counter.most_common(10)
    
    def _compute_keyword_metrics(self, metrics: PaperMetrics):
        """Вычислить метрики по ключевым словам."""
        all_keywords = []
        keyword_counts = []
        
        for paper in self.papers_data:
            keywords = paper.get("keywords", [])
            if isinstance(keywords, list):
                all_keywords.extend(keywords)
                keyword_counts.append(len(keywords))
        
        metrics.total_keywords = len(set(all_keywords))
        
        if keyword_counts:
            metrics.avg_keywords_per_paper = sum(keyword_counts) / len(keyword_counts)
            keyword_counter = Counter(all_keywords)
            metrics.top_keywords = keyword_counter.most_common(20)
    
    def _compute_completeness_metrics(self, metrics: PaperMetrics):
        """Вычислить метрики полноты данных."""
        total = metrics.total_count
        
        metrics.papers_with_abstract = sum(
            1 for p in self.papers_data 
            if p.get("abstract") and len(p.get("abstract", "")) > 0
        )
        
        metrics.papers_with_full_text = sum(
            1 for p in self.papers_data 
            if p.get("full_text") and len(p.get("full_text", "")) > 0
        )
        
        metrics.papers_with_keywords = sum(
            1 for p in self.papers_data 
            if p.get("keywords") and len(p.get("keywords", [])) > 0
        )
        
        metrics.papers_with_doi = sum(
            1 for p in self.papers_data 
            if p.get("doi") and len(p.get("doi", "")) > 0
        )
        
        # Score полноты (среднее по всем метрикам)
        if total > 0:
            scores = [
                metrics.papers_with_abstract / total,
                metrics.papers_with_full_text / total,
                metrics.papers_with_keywords / total,
                metrics.papers_with_doi / total,
            ]
            metrics.completeness_score = sum(scores) / len(scores) * 100
    
    def _compute_embedding_metrics(self, metrics: PaperMetrics):
        """Вычислить метрики эмбеддингов."""
        total = metrics.total_count
        
        metrics.papers_with_embedding = sum(
            1 for p in self.papers_data 
            if p.get("embedding") and len(p.get("embedding", [])) > 0
        )
        
        if total > 0:
            metrics.embedding_coverage = (metrics.papers_with_embedding / total) * 100
    
    def get_publications_trend(self, group_by: str = "month") -> list[dict]:
        """
        Получить тренд публикаций.
        
        Args:
            group_by: 'day', 'week', 'month', 'year'
            
        Returns:
            Список словарей с датой и количеством публикаций
        """
        if not self.papers_data:
            return []
        
        trend_data = []
        date_counts = Counter()
        
        for paper in self.papers_data:
            pub_date = paper.get("publication_date")
            if pub_date:
                try:
                    if isinstance(pub_date, str):
                        pub_date = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                    
                    if group_by == "year":
                        key = pub_date.strftime("%Y")
                    elif group_by == "month":
                        key = pub_date.strftime("%Y-%m")
                    elif group_by == "week":
                        key = pub_date.strftime("%Y-W%W")
                    elif group_by == "day":
                        key = pub_date.strftime("%Y-%m-%d")
                    else:
                        key = pub_date.strftime("%Y-%m")
                    
                    date_counts[key] += 1
                except (ValueError, TypeError):
                    continue
        
        for date_key, count in sorted(date_counts.items()):
            trend_data.append({
                "period": date_key,
                "count": count
            })
        
        return trend_data
    
    def get_source_distribution(self) -> list[dict]:
        """
        Получить распределение по источникам.
        
        Returns:
            Список словарей с источником и количеством
        """
        if not self.papers_data:
            return []
        
        source_counts = Counter(p.get("source", "unknown") for p in self.papers_data)
        
        return [
            {"source": source, "count": count}
            for source, count in source_counts.items()
        ]
    
    def get_statistics_summary(self) -> dict:
        """
        Получить краткую сводку статистики.
        
        Returns:
            Dict с основными метриками
        """
        metrics = self.compute_metrics()
        
        return {
            "total_papers": metrics.total_count,
            "core_count": metrics.core_count,
            "arxiv_count": metrics.arxiv_count,
            "total_authors": metrics.total_authors,
            "avg_authors_per_paper": round(metrics.avg_authors_per_paper, 2),
            "total_keywords": metrics.total_keywords,
            "avg_keywords_per_paper": round(metrics.avg_keywords_per_paper, 2),
            "completeness_score": round(metrics.completeness_score, 2),
            "embedding_coverage": round(metrics.embedding_coverage, 2),
            "earliest_publication": str(metrics.earliest_publication) if metrics.earliest_publication else None,
            "latest_publication": str(metrics.latest_publication) if metrics.latest_publication else None,
            "generated_at": metrics.generated_at.isoformat(),
        }


def compute_paper_metrics(papers: list[dict]) -> dict:
    """
    Вычислить метрики для списка статей.
    
    Args:
        papers: Список словарей с данными статей
        
    Returns:
        Dict с метриками
    """
    service = PaperMetricsService(papers)
    return service.get_statistics_summary()


if __name__ == "__main__":
    # Пример использования
    sample_papers = [
        {
            "title": "Test Paper 1",
            "authors": ["Author A", "Author B"],
            "publication_date": "2024-01-15",
            "journal": "Materials Science",
            "source": "CORE",
            "abstract": "Test abstract",
            "keywords": ["nickel", "alloys"],
            "doi": "10.1234/test1",
        },
        {
            "title": "Test Paper 2",
            "authors": ["Author A", "Author C"],
            "publication_date": "2024-02-20",
            "journal": "Materials Science",
            "source": "arXiv",
            "abstract": "Test abstract 2",
            "keywords": ["superalloys", "nickel"],
            "doi": "10.1234/test2",
        },
    ]
    
    metrics = compute_paper_metrics(sample_papers)
    print(metrics)
