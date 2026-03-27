"""
Base module for parsers.

Модули:
- base_client: Базовый класс для API клиентов
- base_parser: Базовый класс для парсеров
- deduplication: Сервис дедупликации
"""

from .base_client import BaseAPIClient
from .base_parser import BaseParser
from .deduplication import Deduplicator, DeduplicationResult, check_duplicate

__all__ = [
    "BaseAPIClient",
    "BaseParser",
    "Deduplicator",
    "DeduplicationResult",
    "check_duplicate",
]
