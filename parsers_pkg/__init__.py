"""Парсеры научных статей и патентов.

Поддерживаемые источники:
- CORE (core.ac.uk)
- arXiv (arxiv.org)
- ScienceDirect (sciencedirect.com) - Selenium
- ResearchGate (researchgate.net)
- Google Patents
- Espacenet

Модули:
- base: Базовые классы и дедупликация
- pipelines: Конвейеры обработки данных
- arxiv: Парсер arXiv
- core: Парсер CORE
- selenium: Selenium парсеры (ScienceDirect)
- spiders: Spider парсеры (ResearchGate)
- patents: Парсеры патентов
"""

from .base import (
    BaseParser,
    BaseAPIClient,
    Deduplicator,
    DeduplicationResult,
    check_duplicate,
)

from .pipelines import (
    DataPipeline,
    CleaningStage,
    ValidationStage,
    DeduplicationStage,
    EnrichmentStage,
    create_default_pipeline,
    process_papers,
)

__version__ = "1.0.0"

__all__ = [
    # Base
    "BaseParser",
    "BaseAPIClient",
    "Deduplicator",
    "DeduplicationResult",
    "check_duplicate",
    
    # Pipelines
    "DataPipeline",
    "CleaningStage",
    "ValidationStage",
    "DeduplicationStage",
    "EnrichmentStage",
    "create_default_pipeline",
    "process_papers",
]
