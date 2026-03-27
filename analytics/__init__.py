"""
Analytics - Модуль аналитики и метрик.

Система анализа научных статей и патентов в области материаловедения.

Модули:
- metrics: Метрики анализа данных
- reports: Генерация отчётов
- validation: Валидация данных
"""

from analytics.metrics import (
    PaperMetrics,
    PaperMetricsService,
    compute_paper_metrics,
    PatentMetrics,
    PatentMetricsService,
    compute_patent_metrics,
)

from analytics.reports import (
    PaperReport,
    SystemMetricsReport,
    ReportGenerator,
    generate_paper_report,
    generate_system_report,
)

from analytics.validation import (
    ValidationResult,
    PaperValidator,
    PatentValidator,
    DataQualityReport,
    validate_paper,
    validate_patent,
    check_duplicates,
)

__version__ = "1.0.0"

__all__ = [
    # Metrics
    "PaperMetrics",
    "PaperMetricsService",
    "compute_paper_metrics",
    "PatentMetrics",
    "PatentMetricsService",
    "compute_patent_metrics",
    
    # Reports
    "PaperReport",
    "SystemMetricsReport",
    "ReportGenerator",
    "generate_paper_report",
    "generate_system_report",
    
    # Validation
    "ValidationResult",
    "PaperValidator",
    "PatentValidator",
    "DataQualityReport",
    "validate_paper",
    "validate_patent",
    "check_duplicates",
]
