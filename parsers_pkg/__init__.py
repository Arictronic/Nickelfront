"""Парсеры научных статей и патентов.

Активно используемые источники статей:
- CORE (core.ac.uk)
- arXiv (arxiv.org)
- OpenAlex
- Crossref
- SemanticScholar
- EuropePMC

Доступные модули:
- base: базовые классы и дедупликация
- pipelines: конвейеры обработки данных
- arxiv: парсер arXiv
- core: парсер CORE
- external: внешние API-источники (OpenAlex/Crossref/SemanticScholar/EuropePMC)

Legacy-модули (не используются в текущем pipeline статей):
- selenium: Selenium-парсеры
- spiders: Spider-парсеры
- patents: парсеры патентов
"""

from .base import (
    BaseAPIClient,
    BaseParser,
    DeduplicationResult,
    Deduplicator,
    check_duplicate,
)
from .pipelines import (
    CleaningStage,
    DataPipeline,
    DeduplicationStage,
    EnrichmentStage,
    ValidationStage,
    create_default_pipeline,
    process_papers,
)

__version__ = "1.0.0"

__all__ = [
    "BaseParser",
    "BaseAPIClient",
    "Deduplicator",
    "DeduplicationResult",
    "check_duplicate",
    "DataPipeline",
    "CleaningStage",
    "ValidationStage",
    "DeduplicationStage",
    "EnrichmentStage",
    "create_default_pipeline",
    "process_papers",
]
