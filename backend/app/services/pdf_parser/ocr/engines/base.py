from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models import OCRConfig, OCRPageResult


class OCREngineBase(ABC):
    name = "base"

    def availability(self, context: dict[str, Any] | None = None) -> tuple[bool, str]:
        """Return a cheap runtime/dependency availability check.

        The method must not construct heavyweight OCR runtimes. It is used by
        auto engine selection and preflight diagnostics.
        """
        return True, ""

    @abstractmethod
    def run_page(
        self,
        *,
        file_bytes: bytes,
        page_number: int,
        config: OCRConfig,
        context: dict[str, Any] | None = None,
    ) -> OCRPageResult:
        raise NotImplementedError

