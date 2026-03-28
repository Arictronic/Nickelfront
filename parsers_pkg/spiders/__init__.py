"""
Spiders module.

Модули:
- researchgate_parser: Парсер для ResearchGate
"""

from .researchgate_parser import (
    ResearchGateConfig,
    ResearchGateParser,
    parse_researchgate,
)

__all__ = [
    "ResearchGateParser",
    "ResearchGateConfig",
    "parse_researchgate",
]
