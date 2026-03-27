"""
Patents parser module.

Модули:
- patent_parser: Парсер патентов (Google Patents, Espacenet)
"""

from .patent_parser import (
    PatentParser,
    PatentConfig,
    parse_patents,
)

__all__ = [
    "PatentParser",
    "PatentConfig",
    "parse_patents",
]
