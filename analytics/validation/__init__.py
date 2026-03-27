"""
Валидация данных.

Модули:
- data_validator: Валидаторы данных статей и патентов
"""

from .data_validator import (
    ValidationResult,
    PaperValidator,
    PatentValidator,
    DataQualityReport,
    validate_paper,
    validate_patent,
    check_duplicates,
)

__all__ = [
    "ValidationResult",
    "PaperValidator",
    "PatentValidator",
    "DataQualityReport",
    "validate_paper",
    "validate_patent",
    "check_duplicates",
]
