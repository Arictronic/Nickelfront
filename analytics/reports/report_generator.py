"""
Генерация отчётов.

Модуль для генерации отчётов по статьям и патентам:
- Отчёт по отдельной статье
- Отчёт по отдельному патенту
- Сводный отчёт по системе
- Экспорт в различные форматы
"""

from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field
import sys
from pathlib import Path

# Добавляем корень проекта в PATH
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR / "analytics"))

from analytics.metrics.paper_metrics import PaperMetricsService, compute_paper_metrics
from analytics.metrics.patent_metrics import PatentMetricsService, compute_patent_metrics
from analytics.validation.data_validator import DataQualityReport


@dataclass
class PaperReport:
    """Отчёт по статье."""
    
    paper_id: Optional[int] = None
    title: str = ""
    
    # Основная информация
    authors: list[str] = field(default_factory=list)
    journal: Optional[str] = None
    publication_date: Optional[str] = None
    doi: Optional[str] = None
    source: Optional[str] = None
    
    # Метрики
    abstract_length: int = 0
    full_text_length: int = 0
    keywords_count: int = 0
    references_count: int = 0
    
    # Анализ содержания
    has_abstract: bool = False
    has_full_text: bool = False
    has_keywords: bool = False
    has_doi: bool = False
    
    # Оценка качества
    quality_score: float = 0.0
    completeness_score: float = 0.0
    
    # Рекомендации
    recommendations: list[str] = field(default_factory=list)
    
    # Временные метки
    generated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        """Преобразовать в словарь."""
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "authors": self.authors,
            "journal": self.journal,
            "publication_date": self.publication_date,
            "doi": self.doi,
            "source": self.source,
            "metrics": {
                "abstract_length": self.abstract_length,
                "full_text_length": self.full_text_length,
                "keywords_count": self.keywords_count,
                "references_count": self.references_count,
            },
            "content_flags": {
                "has_abstract": self.has_abstract,
                "has_full_text": self.has_full_text,
                "has_keywords": self.has_keywords,
                "has_doi": self.has_doi,
            },
            "scores": {
                "quality_score": round(self.quality_score, 2),
                "completeness_score": round(self.completeness_score, 2),
            },
            "recommendations": self.recommendations,
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass
class SystemMetricsReport:
    """Сводный отчёт по системе."""
    
    # Статистика статей
    total_papers: int = 0
    papers_by_source: dict[str, int] = field(default_factory=dict)
    papers_with_embedding: int = 0
    
    # Статистика патентов
    total_patents: int = 0
    
    # Метрики качества
    avg_paper_quality: float = 0.0
    data_completeness: float = 0.0
    
    # Временные метрики
    earliest_publication: Optional[str] = None
    latest_publication: Optional[str] = None
    
    # Тренды
    publications_trend: list[dict] = field(default_factory=list)
    
    # Топ элементов
    top_journals: list[tuple[str, int]] = field(default_factory=list)
    top_keywords: list[tuple[str, int]] = field(default_factory=list)
    top_authors: list[tuple[str, int]] = field(default_factory=list)
    
    # Временные метки
    generated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        """Преобразовать в словарь."""
        return {
            "papers": {
                "total": self.total_papers,
                "by_source": self.papers_by_source,
                "with_embedding": self.papers_with_embedding,
            },
            "patents": {
                "total": self.total_patents,
            },
            "quality": {
                "avg_paper_quality": round(self.avg_paper_quality, 2),
                "data_completeness": round(self.data_completeness, 2),
            },
            "timeline": {
                "earliest_publication": self.earliest_publication,
                "latest_publication": self.latest_publication,
                "trend": self.publications_trend[:12],  # Последние 12 периодов
            },
            "top_items": {
                "journals": [{"name": name, "count": count} for name, count in self.top_journals[:10]],
                "keywords": [{"name": name, "count": count} for name, count in self.top_keywords[:20]],
                "authors": [{"name": name, "count": count} for name, count in self.top_authors[:10]],
            },
            "generated_at": self.generated_at.isoformat(),
        }


class ReportGenerator:
    """Генератор отчётов."""
    
    def __init__(self):
        self.quality_report = DataQualityReport()
    
    def generate_paper_report(self, paper: dict) -> PaperReport:
        """
        Сгенерировать отчёт по статье.
        
        Args:
            paper: Словарь с данными статьи
            
        Returns:
            PaperReport с отчётом
        """
        report = PaperReport(
            paper_id=paper.get("id"),
            title=paper.get("title", ""),
            authors=paper.get("authors", []) or [],
            journal=paper.get("journal"),
            publication_date=paper.get("publication_date"),
            doi=paper.get("doi"),
            source=paper.get("source"),
        )
        
        # Метрики
        abstract = paper.get("abstract", "") or ""
        full_text = paper.get("full_text", "") or ""
        keywords = paper.get("keywords", []) or []
        
        report.abstract_length = len(abstract)
        report.full_text_length = len(full_text)
        report.keywords_count = len(keywords)
        
        # Флаги содержания
        report.has_abstract = len(abstract) > 0
        report.has_full_text = len(full_text) > 0
        report.has_keywords = len(keywords) > 0
        report.has_doi = bool(paper.get("doi"))
        
        # Оценка качества
        quality_fields = [
            report.has_abstract,
            report.has_full_text,
            report.has_keywords,
            report.has_doi,
            bool(report.authors),
            bool(report.journal),
            bool(report.publication_date),
        ]
        
        filled_count = sum(quality_fields)
        report.completeness_score = (filled_count / len(quality_fields)) * 100 if quality_fields else 0
        
        # Дополнительные метрики качества
        if report.abstract_length > 100:
            report.quality_score += 20
        if report.full_text_length > 1000:
            report.quality_score += 30
        if report.keywords_count >= 5:
            report.quality_score += 20
        if report.has_doi:
            report.quality_score += 15
        if report.authors and len(report.authors) > 0:
            report.quality_score += 15
        
        report.quality_score = min(100, report.quality_score)
        
        # Рекомендации
        if not report.has_abstract:
            report.recommendations.append("Добавить аннотацию")
        if not report.has_full_text:
            report.recommendations.append("Добавить полный текст")
        if report.keywords_count < 5:
            report.recommendations.append(f"Добавить ключевые слова (текущее: {report.keywords_count}, рекомендуется: 5+)")
        if not report.has_doi:
            report.recommendations.append("Добавить DOI")
        if not report.authors:
            report.recommendations.append("Добавить авторов")
        
        return report
    
    def generate_system_report(
        self,
        papers: list[dict],
        patents: list[dict] = None
    ) -> SystemMetricsReport:
        """
        Сгенерировать сводный отчёт по системе.
        
        Args:
            papers: Список статей
            patents: Список патентов (опционально)
            
        Returns:
            SystemMetricsReport с отчётом
        """
        report = SystemMetricsReport()
        
        # Метрики статей
        if papers:
            report.total_papers = len(papers)
            
            # Вычисляем метрики
            paper_metrics = compute_paper_metrics(papers)
            
            report.papers_by_source = {
                "CORE": paper_metrics.get("core_count", 0),
                "arXiv": paper_metrics.get("arxiv_count", 0),
            }
            
            report.papers_with_embedding = sum(
                1 for p in papers if p.get("embedding")
            )
            
            report.avg_paper_quality = paper_metrics.get("completeness_score", 0)
            report.data_completeness = paper_metrics.get("completeness_score", 0)
            
            # Топ элементов
            paper_service = PaperMetricsService(papers)
            metrics = paper_service.compute_metrics()
            
            report.top_journals = metrics.top_journals
            report.top_keywords = metrics.top_keywords
            report.top_authors = metrics.top_authors
            
            # Временные метрики
            if metrics.earliest_publication:
                report.earliest_publication = str(metrics.earliest_publication)
            if metrics.latest_publication:
                report.latest_publication = str(metrics.latest_publication)
            
            # Тренды
            report.publications_trend = paper_service.get_publications_trend("month")
        
        # Метрики патентов
        if patents:
            report.total_patents = len(patents)
            
            patent_metrics = compute_patent_metrics(patents)
            # Можно добавить дополнительные метрики патентов
        
        return report
    
    def get_quick_stats(self, papers: list[dict]) -> dict:
        """
        Получить быструю статистику.
        
        Args:
            papers: Список статей
            
        Returns:
            Dict с быстрой статистикой
        """
        if not papers:
            return {
                "total": 0,
                "core_count": 0,
                "arxiv_count": 0,
                "avg_quality": 0,
            }
        
        total = len(papers)
        core_count = sum(1 for p in papers if p.get("source") == "CORE")
        arxiv_count = sum(1 for p in papers if p.get("source") == "arXiv")
        
        # Быстрая оценка качества
        quality_scores = []
        for paper in papers:
            score = 0
            if paper.get("abstract"): score += 20
            if paper.get("full_text"): score += 30
            if paper.get("keywords"): score += 20
            if paper.get("doi"): score += 15
            if paper.get("authors"): score += 15
            quality_scores.append(min(100, score))
        
        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0
        
        return {
            "total": total,
            "core_count": core_count,
            "arxiv_count": arxiv_count,
            "avg_quality": round(avg_quality, 2),
        }


def generate_paper_report(paper: dict) -> dict:
    """Сгенерировать отчёт по статье."""
    generator = ReportGenerator()
    report = generator.generate_paper_report(paper)
    return report.to_dict()


def generate_system_report(papers: list[dict], patents: list[dict] = None) -> dict:
    """Сгенерировать сводный отчёт по системе."""
    generator = ReportGenerator()
    report = generator.generate_system_report(papers, patents)
    return report.to_dict()


if __name__ == "__main__":
    # Пример использования
    sample_paper = {
        "id": 1,
        "title": "Test Paper",
        "authors": ["Author A", "Author B"],
        "publication_date": "2024-01-15",
        "journal": "Materials Science",
        "doi": "10.1234/test",
        "source": "CORE",
        "abstract": "Test abstract with some content",
        "full_text": "Full text content here...",
        "keywords": ["nickel", "alloys", "superalloys"],
    }
    
    report = generate_paper_report(sample_paper)
    print("Paper Report:")
    print(report)
    
    # Сводный отчёт
    sample_papers = [sample_paper] * 10
    
    system_report = generate_system_report(sample_papers)
    print("\nSystem Report:")
    print(system_report)
