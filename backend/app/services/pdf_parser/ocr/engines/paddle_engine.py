from __future__ import annotations

import importlib.util
import io
from typing import Any

from ..models import OCRConfig, OCRLine, OCRPageResult
from .base import OCREngineBase


class PaddleEngine(OCREngineBase):
    name = "paddle"

    def __init__(self) -> None:
        self._ocr_instances: dict[str, Any] = {}

    def availability(self, context: dict[str, Any] | None = None) -> tuple[bool, str]:
        missing = [
            module
            for module in ("fitz", "numpy", "PIL", "paddleocr", "paddle")
            if importlib.util.find_spec(module) is None
        ]
        if missing:
            return False, f"deps_missing:{','.join(missing)}"
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
            import numpy as np
            from PIL import Image
            from paddleocr import PaddleOCR
        except Exception:
            return OCRPageResult(
                page_number=page_number,
                text="",
                engine=self.name,
                dpi=int(config.dpi or 220),
                languages=config.languages or "eng+rus",
                warnings=["ocr_engine_not_available"],
            )

        lang = "en"
        lowered = (config.languages or "").lower()
        if "ru" in lowered:
            lang = "ru"

        ctx = context or {}
        cache_key = lang or "en"
        ocr_instance = ctx.get("_paddle_ocr_instance") or self._ocr_instances.get(cache_key)
        if ocr_instance is None:
            try:
                ocr_instance = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)
                self._ocr_instances[cache_key] = ocr_instance
                ctx["_paddle_ocr_instance"] = ocr_instance
            except Exception:
                return OCRPageResult(
                    page_number=page_number,
                    text="",
                    engine=self.name,
                    dpi=int(config.dpi or 220),
                    languages=config.languages or "eng+rus",
                    warnings=["ocr_engine_not_available"],
                )

        owned_doc = None
        doc = ctx.get("ocr_doc")
        try:
            if doc is None:
                owned_doc = fitz.open(stream=file_bytes, filetype="pdf")
                doc = owned_doc
            page = doc.load_page(page_number - 1)
            zoom = max(120, int(config.dpi or 220)) / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            img = np.array(image)
            raw = ocr_instance.ocr(img, cls=True) or []

            items = raw[0] if raw and isinstance(raw[0], list) else []
            lines: list[OCRLine] = []
            texts: list[str] = []
            conf_sum = 0.0
            conf_count = 0
            bbox_all: list[list[float]] = []
            for item in items:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                box = item[0]
                payload = item[1]
                if not isinstance(payload, (list, tuple)) or len(payload) < 2:
                    continue
                text = str(payload[0] or "").strip()
                if not text:
                    continue
                try:
                    conf = float(payload[1] or 0.0)
                except Exception:
                    conf = 0.0
                xs = [float(p[0]) for p in (box or []) if isinstance(p, (list, tuple)) and len(p) >= 2]
                ys = [float(p[1]) for p in (box or []) if isinstance(p, (list, tuple)) and len(p) >= 2]
                if xs and ys:
                    bbox = [min(xs), min(ys), max(xs), max(ys)]
                    bbox_all.append(bbox)
                else:
                    bbox = None
                lines.append(OCRLine(text=text, bbox=bbox, confidence=max(0.0, min(1.0, conf))))
                texts.append(text)
                conf_sum += max(0.0, min(1.0, conf))
                conf_count += 1
            page_bbox = None
            if bbox_all:
                page_bbox = [
                    round(min(box[0] for box in bbox_all), 3),
                    round(min(box[1] for box in bbox_all), 3),
                    round(max(box[2] for box in bbox_all), 3),
                    round(max(box[3] for box in bbox_all), 3),
                ]
            return OCRPageResult(
                page_number=page_number,
                text="\n".join(texts).strip(),
                lines=lines,
                bbox=page_bbox,
                confidence=round(conf_sum / max(1, conf_count), 4) if conf_count else None,
                engine=self.name,
                dpi=int(config.dpi or 220),
                languages=config.languages or "eng+rus",
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
