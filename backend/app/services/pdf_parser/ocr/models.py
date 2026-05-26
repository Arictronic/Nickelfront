from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class OCRLine:
    text: str
    bbox: list[float] | None = None
    confidence: float | None = None


@dataclass(slots=True)
class OCRPageResult:
    page_number: int
    text: str
    lines: list[OCRLine] = field(default_factory=list)
    bbox: list[float] | None = None
    confidence: float | None = None
    engine: str = "unknown"
    dpi: int = 220
    languages: str = "eng+rus"
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OCRConfig:
    enabled: bool = False
    control_mode: str = "auto"
    requested_engine: str = "auto"
    engine: str = "tesseract"
    fallback_engines: list[str] = field(default_factory=lambda: ["tesseract"])
    force: bool = False
    skip: bool = False
    pages: set[int] = field(default_factory=set)
    dpi: int = 220
    languages: str = "eng+rus"
    merge_strategy: str = "replace_low_quality"
    min_quality_score: float = 0.45
    min_confidence: float = 0.55
    min_text_chars: int = 180
    min_words: int = 35
    min_text_density: float = 0.35
    broken_encoding_noise_ratio: float = 0.02
    allow_paddle: bool = False
    allow_ocrmypdf_page: bool = False
    emit_lines: bool = False
    debug: bool = False
    engine_selection_reason: str = "default_tesseract"
    engine_warnings: list[str] = field(default_factory=list)
    page_selection_warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OCRDecision:
    page_number: int
    apply_ocr: bool
    reason: str
    engine: str = "tesseract"
    merge_strategy: str = "replace_low_quality"
    details: dict[str, Any] = field(default_factory=dict)
