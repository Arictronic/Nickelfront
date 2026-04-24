"""Парсеры научных статей и патентов.

Активно используемые источники статей:
- CORE (core.ac.uk)
- arXiv (arxiv.org)
- OpenAlex
- Crossref
- EuropePMC
- CyberLeninka
- eLibrary
- Rospatent
- FreePatent
- PATENTSCOPE

Доступные модули:
- base: базовые классы и дедупликация
- pipelines: конвейеры обработки данных
- arxiv: парсер arXiv
- core: парсер CORE
- external: внешние API-источники (OpenAlex/Crossref/EuropePMC)
- russian: парсеры русскоязычных источников
- translate: модуль перевода поисковых запросов

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
from .errors import (
    AntiBotBlockedError,
    AuthenticationError,
    EmptyResultError,
    MisconfigurationError,
    ParsingError,
    RateLimitedError,
    SchemaChangedError,
    SourceError,
    SourceTimeoutError,
    SourceUnavailableError,
)
from .sources import (
    SourceCapabilities,
    SourceMetadata,
    SourceRegistry,
    SourceRuntimeDefaults,
    build_default_source_registry,
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
    "SourceError",
    "SourceUnavailableError",
    "RateLimitedError",
    "AuthenticationError",
    "ParsingError",
    "SchemaChangedError",
    "AntiBotBlockedError",
    "SourceTimeoutError",
    "EmptyResultError",
    "MisconfigurationError",
    "SourceCapabilities",
    "SourceMetadata",
    "SourceRuntimeDefaults",
    "SourceRegistry",
    "build_default_source_registry",
]
