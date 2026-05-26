"""Data models and parser exceptions for the PDF content parser."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


class PdfExtractionError(RuntimeError):
    """Raised when PDF extraction/parsing fails before valid text is produced."""


@dataclass(slots=True)
class PdfPageExtraction:
    """Результат извлечения одной страницы PDF."""

    page_number: int
    text: str
    method: str
    quality_score: float
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["PdfExtractionError", "PdfPageExtraction"]
