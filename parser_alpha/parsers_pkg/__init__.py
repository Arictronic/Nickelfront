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
- GooglePatents
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
from __future__ import annotations

import sys
from pathlib import Path

_PARSER_ALPHA_DIR = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _PARSER_ALPHA_DIR.parent
_BACKEND_DIR = _PROJECT_ROOT / "backend"

# Keep the canonical project-level `shared` package ahead of parser_alpha.
# The previous insert(0) loop reversed the intended order and could make
# `from shared.schemas...` resolve to parser_alpha/shared instead of /shared.
_PATH_ORDER = (_PROJECT_ROOT, _BACKEND_DIR, _PARSER_ALPHA_DIR)
_path_strings = [str(_path) for _path in _PATH_ORDER if _path.exists()]
if _path_strings:
    sys.path[:] = [_existing for _existing in sys.path if _existing not in _path_strings]
    sys.path[:0] = _path_strings



def _is_missing_optional_module(exc: ModuleNotFoundError, module_name: str) -> bool:
    """Return True only when this trimmed parser package misses its own module."""
    missing = str(getattr(exc, "name", "") or "")
    return missing in {module_name, f"{__name__}.{module_name}"}

try:
    from .base import (
        BaseAPIClient,
        BaseParser,
        DeduplicationResult,
        Deduplicator,
        check_duplicate,
    )
except ModuleNotFoundError as exc:
    if not _is_missing_optional_module(exc, "base"):
        raise

try:
    from .pipelines import (
        CleaningStage,
        DataPipeline,
        DeduplicationStage,
        EnrichmentStage,
        ValidationStage,
        create_default_pipeline,
        process_papers,
    )
except ModuleNotFoundError as exc:
    if not _is_missing_optional_module(exc, "pipelines"):
        raise

try:
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
except ModuleNotFoundError as exc:
    if not _is_missing_optional_module(exc, "errors"):
        raise

try:
    from .sources import (
        SourceCapabilities,
        SourceMetadata,
        SourceRegistry,
        SourceRuntimeDefaults,
        build_default_source_registry,
    )
except ModuleNotFoundError as exc:
    if not _is_missing_optional_module(exc, "sources"):
        raise

__version__ = "1.0.0"

_PUBLIC_NAMES = [
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

__all__ = [name for name in _PUBLIC_NAMES if name in globals()]
