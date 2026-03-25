"""Парсеры научных статей.

Поддерживаемые источники:
- CORE (core.ac.uk)
- arXiv (arxiv.org)
"""

from .base import BaseParser, BaseAPIClient
from .core import COREClient, COREParser
from .arxiv import ArxivClient, ArxivParser, ARXIV_SEARCH_QUERIES, ARXIV_CATEGORIES

__all__ = [
    "BaseParser",
    "BaseAPIClient",
    "COREClient",
    "COREParser",
    "ArxivClient",
    "ArxivParser",
    "ARXIV_SEARCH_QUERIES",
    "ARXIV_CATEGORIES",
]
