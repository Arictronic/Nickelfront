from __future__ import annotations

import importlib.util
import io
import shutil
from pathlib import Path
from typing import Any

from ..models import OCRConfig, OCRLine, OCRPageResult
from .base import OCREngineBase


class TesseractEngine(OCREngineBase):
    name = "tesseract"

    @staticmethod
    def _resolve_tesseract_cmd() -> str | None:
        path_cmd = shutil.which("tesseract")
        if path_cmd:
            return path_cmd
        candidates = [
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return None

    def availability(self, context: dict[str, Any] | None = None) -> tuple[bool, str]:
        missing = [
            module
            for module in ("fitz", "PIL", "pytesseract")
            if importlib.util.find_spec(module) is None
        ]
        if missing:
            return False, f"deps_missing:{','.join(missing)}"
        if not self._resolve_tesseract_cmd():
            return False, "binary_missing:tesseract"
        return True, ""

    def run_page(
        self,
        *,
        file_bytes: bytes,
        page_number: int,
        config: OCRConfig,
        context: dict[str, Any] | None = None,
    ) -> OCRPageResult:
        try:
            import fitz
            import pytesseract
            from pytesseract import Output
            from PIL import Image


            tesseract_cmd = self._resolve_tesseract_cmd()
            if not tesseract_cmd:
                return OCRPageResult(
                    page_number=page_number,
                    text="",
                    engine=self.name,
                    dpi=config.dpi,
                    languages=config.languages,
                    warnings=["ocr_dependencies_missing", "tesseract_binary_missing"],
                )
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        except Exception:
            return OCRPageResult(
                page_number=page_number,
                text="",
                engine=self.name,
                dpi=config.dpi,
                languages=config.languages,
                warnings=["ocr_dependencies_missing"],
            )

        ctx = context or {}
        owned_doc = None
        doc = ctx.get("ocr_doc")
        try:
            if doc is None:
                owned_doc = fitz.open(stream=file_bytes, filetype="pdf")
                doc = owned_doc
            page = doc.load_page(page_number - 1)
            zoom = max(120, int(config.dpi or 220)) / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            image = Image.open(io.BytesIO(pix.tobytes("png")))
            lang = config.languages or "eng+rus"
            text = pytesseract.image_to_string(image, lang=lang) or ""
            data = pytesseract.image_to_data(image, lang=lang, output_type=Output.DICT)
            lines: list[OCRLine] = []
            weighted_conf = 0.0
            weighted_len = 0
            bbox_all: list[list[float]] = []
            n = len(data.get("text") or [])
            for idx in range(n):
                raw_text = str((data.get("text") or [""])[idx] or "").strip()
                if not raw_text:
                    continue
                try:
                    conf = float((data.get("conf") or [0])[idx] or 0.0)
                except Exception:
                    conf = 0.0
                left = float((data.get("left") or [0])[idx] or 0.0)
                top = float((data.get("top") or [0])[idx] or 0.0)
                width = float((data.get("width") or [0])[idx] or 0.0)
                height = float((data.get("height") or [0])[idx] or 0.0)
                bbox = [left, top, left + max(0.0, width), top + max(0.0, height)]
                bbox_all.append(bbox)
                lines.append(OCRLine(text=raw_text, bbox=bbox, confidence=max(0.0, min(1.0, conf / 100.0))))
                weighted_conf += max(0.0, conf) * max(1, len(raw_text))
                weighted_len += max(1, len(raw_text))
            confidence = (weighted_conf / max(1, weighted_len)) / 100.0
            page_bbox = None
            if bbox_all:
                x0 = min(box[0] for box in bbox_all)
                y0 = min(box[1] for box in bbox_all)
                x1 = max(box[2] for box in bbox_all)
                y1 = max(box[3] for box in bbox_all)
                page_bbox = [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)]
            line_text = "\n".join(line.text for line in lines if str(line.text or "").strip()).strip()
            return OCRPageResult(
                page_number=page_number,
                text=line_text or text,
                lines=lines,
                bbox=page_bbox,
                confidence=round(max(0.0, min(1.0, confidence)), 4),
                engine=self.name,
                dpi=int(config.dpi or 220),
                languages=lang,
                warnings=[],
            )
        except Exception:
            return OCRPageResult(
                page_number=page_number,
                text="",
                engine=self.name,
                dpi=int(config.dpi or 220),
                languages=config.languages or "eng+rus",
                warnings=["ocr_failed"],
            )
        finally:
            if owned_doc is not None:
                try:
                    owned_doc.close()
                except Exception:
                    pass
