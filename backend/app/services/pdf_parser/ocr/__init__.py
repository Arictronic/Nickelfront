"""OCR subsystem for PDF parser."""

from .models import OCRConfig, OCRDecision, OCRLine, OCRPageResult
from .service import OCRService

__all__ = [
    "OCRConfig",
    "OCRDecision",
    "OCRLine",
    "OCRPageResult",
    "OCRService",
]

