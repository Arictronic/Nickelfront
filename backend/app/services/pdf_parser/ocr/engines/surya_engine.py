from __future__ import annotations

import importlib.util
from typing import Any

from ..models import OCRConfig, OCRPageResult
from .base import OCREngineBase


class SuryaEngine(OCREngineBase):
    name = "surya"

    def availability(self, context: dict[str, Any] | None = None) -> tuple[bool, str]:
        if not bool((context or {}).get("surya_experimental_enabled")):
            return False, "experimental_disabled:surya"
        missing = [module for module in ("surya",) if importlib.util.find_spec(module) is None]
        if missing:
            return False, f"deps_missing:{','.join(missing)}"
        return False, "engine_not_implemented:surya"

    def run_page(
        self,
        *,
        file_bytes: bytes,
        page_number: int,
        config: OCRConfig,
        context: dict[str, Any] | None = None,
    ) -> OCRPageResult:
        if not bool((context or {}).get("surya_experimental_enabled")):
            return OCRPageResult(
                page_number=page_number,
                text="",
                engine=self.name,
                dpi=int(config.dpi or 220),
                languages=config.languages or "eng+rus",
                warnings=["ocr_engine_experimental_disabled"],
            )
        return OCRPageResult(
            page_number=page_number,
            text="",
            engine=self.name,
            dpi=int(config.dpi or 220),
            languages=config.languages or "eng+rus",
            warnings=["ocr_engine_not_available"],
        )
