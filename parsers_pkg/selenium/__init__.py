"""
Selenium parsers module.

Модули:
- sciencedirect_parser: Парсер для ScienceDirect
"""

from .sciencedirect_parser import (
    ScienceDirectConfig,
    ScienceDirectParser,
    parse_sciencedirect,
)

__all__ = [
    "ScienceDirectParser",
    "ScienceDirectConfig",
    "parse_sciencedirect",
]
