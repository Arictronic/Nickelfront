from __future__ import annotations

import io
import logging
import math
import re
import unicodedata
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .compat import Document, RecursiveCharacterTextSplitter
from .constants import *
from .models import PdfExtractionError, PdfPageExtraction
from .profiles import ParserDomainProfile, get_domain_profile, is_domain_bonus_profile, normalize_domain_profile_name

logger = logging.getLogger(__name__)

class PDFParserUtilsMixin:
    """Small parser utilities and legacy conversion helpers."""

    def _normalize_domain_profile_name(self, value: Any | None) -> str:
        return normalize_domain_profile_name(value)

    def _domain_profile_name_from_sources(
        self,
        metadata: dict[str, Any] | None = None,
        opts: dict[str, Any] | None = None,
    ) -> str:



        for source in (opts or {}, metadata or {}):
            for key in ("parser_domain_profile", "parser_profile", "document_domain_profile", "profile", "domain_profile"):
                value = source.get(key)
                if value not in {None, ""}:
                    return self._normalize_domain_profile_name(value)
        return "generic"

    def _domain_profile(self, metadata: dict[str, Any] | None = None, opts: dict[str, Any] | None = None) -> ParserDomainProfile:
        return get_domain_profile(self._domain_profile_name_from_sources(metadata=metadata, opts=opts))

    def _has_explicit_domain_bonus_profile(
        self,
        metadata: dict[str, Any] | None = None,
        opts: dict[str, Any] | None = None,
    ) -> bool:
        return is_domain_bonus_profile(self._domain_profile_name_from_sources(metadata=metadata, opts=opts))

    def _trim_page_text(self, text: str, max_chars: int) -> str:
        value = (text or "").strip()
        if len(value) <= max_chars:
            return value
        cut = value[:max_chars]

        boundary = cut.rfind("\n\n")
        if boundary > max_chars * 0.65:
            cut = cut[:boundary]
        return cut.rstrip() + "\n\n[Truncated by PDF extraction max_page_chars]"

    def _pages_to_legacy_text(self, pages: Iterable[PdfPageExtraction]) -> str:
        blocks = []
        for page in pages:
            if page.text.strip():
                blocks.append(f"[Страница {page.page_number}]\n{page.text.strip()}")
        return "\n\n".join(blocks).strip()

    def _to_bool(self, value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on", "да"}
        if value is None:
            return default
        return bool(value)

    def _to_int(self, value: Any, default: int, *, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))



__all__ = ["PDFParserUtilsMixin"]
