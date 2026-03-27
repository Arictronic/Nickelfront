"""
Метрики анализа патентов.

Модуль для вычисления статистики и метрик по патентам:
- Количество патентов по источникам
- Распределение по датам
- Анализ IPC классов
- Статистика по заявителям
- Географическое распределение
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
class PatentMetrics:
    """Метрики анализа патентов."""
    
    # Общая статистика
    total_count: int = 0
    
    # Распределение по источникам
    sources_distribution: dict[str, int] = field(default_factory=dict)
    
    # Статистика по датам
    earliest_filing_date: Optional[date] = None
    latest_filing_date: Optional[date] = None
    avg_filing_year: Optional[float] = None
    
    # Распределение по годам
    filings_by_year: dict[int, int] = field(default_factory=dict)
    
    # Статистика по заявителям
    total_applicants: int = 0
    top_applicants: list[tuple[str, int]] = field(default_factory=list)
    
    # Статистика по изобретателям
    total_inventors: int = 0
    top_inventors: list[tuple[str, int]] = field(default_factory=list)
    
    # IPC классы
    ipc_classes: dict[str, int] = field(default_factory=dict)
    top_ipc_classes: list[tuple[str, int]] = field(default_factory=list)
    
    # Географическое распределение
    countries_distribution: dict[str, int] = field(default_factory=dict)
    
    # Статусы патентов
    status_distribution: dict[str, int] = field(default_factory=dict)
    
    # Метрики полноты данных
    patents_with_abstract: int = 0
    patents_with_claims: int = 0
    patents_with_description: int = 0
    completeness_score: float = 0.0
    
    # Временные метки
    generated_at: datetime = field(default_factory=datetime.now)


class PatentMetricsService:
    """Сервис для вычисления метрик патентов."""
    
    def __init__(self, patents_data: list[dict]):
        """
        Инициализация сервиса.
        
        Args:
            patents_data: Список словарей с данными патентов
        """
        self.patents_data = patents_data
        
        if POLARS_AVAILABLE and patents_data:
            self.df = pl.DataFrame(patents_data)
        else:
            self.df = None
    
    def compute_metrics(self) -> PatentMetrics:
        """
        Вычислить все метрики.
        
        Returns:
            PatentMetrics с вычисленными метриками
        """
        metrics = PatentMetrics()
        
        if not self.patents_data:
            return metrics
        
        # Общая статистика
        metrics.total_count = len(self.patents_data)
        
        # Распределение по источникам
        self._compute_source_metrics(metrics)
        
        # Статистика по датам
        self._compute_date_metrics(metrics)
        
        # Статистика по заявителям
        self._compute_applicant_metrics(metrics)
        
        # Статистика по изобретателям
        self._compute_inventor_metrics(metrics)
        
        # IPC классы
        self._compute_ipc_metrics(metrics)
        
        # Географическое распределение
        self._compute_country_metrics(metrics)
        
        # Статусы патентов
        self._compute_status_metrics(metrics)
        
        # Метрики полноты данных
        self._compute_completeness_metrics(metrics)
        
        return metrics
    
    def _compute_source_metrics(self, metrics: PatentMetrics):
        """Вычислить метрики по источникам."""
        sources = [p.get("source", "unknown") for p in self.patents_data]
        metrics.sources_distribution = dict(Counter(sources))
    
    def _compute_date_metrics(self, metrics: PatentMetrics):
        """Вычислить метрики по датам."""
        filing_dates = []
        filing_years = []
        
        for patent in self.patents_data:
            filing_date = patent.get("filing_date") or patent.get("publication_date")
            if filing_date:
                try:
                    if isinstance(filing_date, str):
                        filing_date = datetime.fromisoformat(filing_date.replace("Z", "+00:00"))
                    elif isinstance(filing_date, datetime):
                        pass
                    else:
                        continue
                    
                    filing_dates.append(filing_date)
                    filing_years.append(filing_date.year)
                except (ValueError, TypeError):
                    continue
        
        if filing_dates:
            metrics.earliest_filing_date = min(filing_dates).date()
            metrics.latest_filing_date = max(filing_dates).date()
        
        if filing_years:
            metrics.avg_filing_year = sum(filing_years) / len(filing_years)
            metrics.filings_by_year = dict(Counter(filing_years))
    
    def _compute_applicant_metrics(self, metrics: PatentMetrics):
        """Вычислить метрики по заявителям."""
        all_applicants = []
        
        for patent in self.patents_data:
            applicants = patent.get("applicants", [])
            if isinstance(applicants, list):
                all_applicants.extend(applicants)
            elif isinstance(applicants, str) and applicants:
                all_applicants.append(applicants)
        
        metrics.total_applicants = len(set(all_applicants))
        
        if all_applicants:
            applicant_counter = Counter(all_applicants)
            metrics.top_applicants = applicant_counter.most_common(10)
    
    def _compute_inventor_metrics(self, metrics: PatentMetrics):
        """Вычислить метрики по изобретателям."""
        all_inventors = []
        
        for patent in self.patents_data:
            inventors = patent.get("inventors", [])
            if isinstance(inventors, list):
                all_inventors.extend(inventors)
            elif isinstance(inventors, str) and inventors:
                all_inventors.append(inventors)
        
        metrics.total_inventors = len(set(all_inventors))
        
        if all_inventors:
            inventor_counter = Counter(all_inventors)
            metrics.top_inventors = inventor_counter.most_common(10)
    
    def _compute_ipc_metrics(self, metrics: PatentMetrics):
        """Вычислить метрики по IPC классам."""
        all_ipc = []
        
        for patent in self.patents_data:
            ipc_classes = patent.get("ipc_classes", [])
            if isinstance(ipc_classes, list):
                all_ipc.extend(ipc_classes)
            elif isinstance(ipc_classes, str) and ipc_classes:
                all_ipc.append(ipc_classes)
        
        if all_ipc:
            ipc_counter = Counter(all_ipc)
            metrics.ipc_classes = dict(ipc_counter)
            metrics.top_ipc_classes = ipc_counter.most_common(10)
    
    def _compute_country_metrics(self, metrics: PatentMetrics):
        """Вычислить метрики по странам."""
        countries = []
        
        for patent in self.patents_data:
            country = patent.get("country") or patent.get("jurisdiction")
            if country:
                countries.append(country)
        
        if countries:
            metrics.countries_distribution = dict(Counter(countries))
    
    def _compute_status_metrics(self, metrics: PatentMetrics):
        """Вычислить метрики по статусам."""
        statuses = [p.get("status", "unknown") for p in self.patents_data if p.get("status")]
        
        if statuses:
            metrics.status_distribution = dict(Counter(statuses))
    
    def _compute_completeness_metrics(self, metrics: PatentMetrics):
        """Вычислить метрики полноты данных."""
        total = metrics.total_count
        
        metrics.patents_with_abstract = sum(
            1 for p in self.patents_data 
            if p.get("abstract") and len(p.get("abstract", "")) > 0
        )
        
        metrics.patents_with_claims = sum(
            1 for p in self.patents_data 
            if p.get("claims") and len(p.get("claims", "")) > 0
        )
        
        metrics.patents_with_description = sum(
            1 for p in self.patents_data 
            if p.get("description") and len(p.get("description", "")) > 0
        )
        
        # Score полноты
        if total > 0:
            scores = [
                metrics.patents_with_abstract / total,
                metrics.patents_with_claims / total,
                metrics.patents_with_description / total,
            ]
            metrics.completeness_score = sum(scores) / len(scores) * 100
    
    def get_filings_trend(self, group_by: str = "month") -> list[dict]:
        """
        Получить тренд подачи патентов.
        
        Args:
            group_by: 'day', 'week', 'month', 'year'
            
        Returns:
            Список словарей с датой и количеством патентов
        """
        if not self.patents_data:
            return []
        
        trend_data = []
        date_counts = Counter()
        
        for patent in self.patents_data:
            filing_date = patent.get("filing_date") or patent.get("publication_date")
            if filing_date:
                try:
                    if isinstance(filing_date, str):
                        filing_date = datetime.fromisoformat(filing_date.replace("Z", "+00:00"))
                    
                    if group_by == "year":
                        key = filing_date.strftime("%Y")
                    elif group_by == "month":
                        key = filing_date.strftime("%Y-%m")
                    elif group_by == "week":
                        key = filing_date.strftime("%Y-W%W")
                    elif group_by == "day":
                        key = filing_date.strftime("%Y-%m-%d")
                    else:
                        key = filing_date.strftime("%Y-%m")
                    
                    date_counts[key] += 1
                except (ValueError, TypeError):
                    continue
        
        for date_key, count in sorted(date_counts.items()):
            trend_data.append({
                "period": date_key,
                "count": count
            })
        
        return trend_data
    
    def get_statistics_summary(self) -> dict:
        """
        Получить краткую сводку статистики.
        
        Returns:
            Dict с основными метриками
        """
        metrics = self.compute_metrics()
        
        return {
            "total_patents": metrics.total_count,
            "total_applicants": metrics.total_applicants,
            "total_inventors": metrics.total_inventors,
            "top_ipc_classes": metrics.top_ipc_classes[:5],
            "completeness_score": round(metrics.completeness_score, 2),
            "earliest_filing_date": str(metrics.earliest_filing_date) if metrics.earliest_filing_date else None,
            "latest_filing_date": str(metrics.latest_filing_date) if metrics.latest_filing_date else None,
            "generated_at": metrics.generated_at.isoformat(),
        }


def compute_patent_metrics(patents: list[dict]) -> dict:
    """
    Вычислить метрики для списка патентов.
    
    Args:
        patents: Список словарей с данными патентов
        
    Returns:
        Dict с метриками
    """
    service = PatentMetricsService(patents)
    return service.get_statistics_summary()


if __name__ == "__main__":
    # Пример использования
    sample_patents = [
        {
            "title": "Test Patent 1",
            "applicants": ["Company A"],
            "inventors": ["Inventor A", "Inventor B"],
            "filing_date": "2024-01-15",
            "ipc_classes": ["C22C19/00", "B22F3/00"],
            "abstract": "Test abstract",
            "claims": "Claim 1...",
            "status": "granted",
            "country": "US",
        },
        {
            "title": "Test Patent 2",
            "applicants": ["Company B"],
            "inventors": ["Inventor A"],
            "filing_date": "2024-02-20",
            "ipc_classes": ["C22C19/05"],
            "abstract": "Test abstract 2",
            "status": "pending",
            "country": "EP",
        },
    ]
    
    metrics = compute_patent_metrics(sample_patents)
    print(metrics)
