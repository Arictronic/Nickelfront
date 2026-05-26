from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AIPageResult:
    page_number: int
    text: str = ""
    confidence: float = 0.0
    provider: str = ""
    model: str = ""
    status: str = "not_configured"
    reason: str = "ai_page_recognition_stub"
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class AIPageRecognitionService:
    """Placeholder for future page-image AI recognition.

    Intended flow:
      PDF page -> rendered page image -> external AI recognizer -> normalized page text.

    The current implementation intentionally does not call any network service.
    It only records deterministic metadata and returns no replacement text so
    the parser keeps the existing PDF/OCR extraction path without data loss.
    """

    def run_page_stub(
        self,
        *,
        page_number: int,
        page_width: float = 0.0,
        page_height: float = 0.0,
        opts: dict[str, Any] | None = None,
    ) -> AIPageResult:
        options = opts or {}
        provider = str(options.get("ai_provider") or "").strip()
        model = str(options.get("ai_model") or "").strip()
        render_dpi = int(options.get("ai_render_dpi") or 220)
        image_format = str(options.get("ai_page_image_format") or "png").strip().lower() or "png"
        enabled = bool(options.get("ai_enabled"))
        mode = str(options.get("ai_mode") or "off").strip().lower()

        if not enabled:
            status = "disabled"
            reason = "ai_disabled"
        elif not provider:
            status = "not_configured"
            reason = "ai_provider_not_configured"
        else:
            status = "not_implemented"
            reason = "ai_runtime_not_implemented"

        return AIPageResult(
            page_number=page_number,
            text="",
            confidence=0.0,
            provider=provider,
            model=model,
            status=status,
            reason=reason,
            warnings=[reason],
            metadata={
                "ai_mode": mode,
                "ai_enabled": enabled,
                "ai_provider": provider,
                "ai_model": model,
                "ai_render_dpi": render_dpi,
                "ai_page_image_format": image_format,
                "ai_page_width": float(page_width or 0.0),
                "ai_page_height": float(page_height or 0.0),
                "ai_page_image_expected": True,
                "ai_external_call_performed": False,
            },
        )


__all__ = ["AIPageRecognitionService", "AIPageResult"]
