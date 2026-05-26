from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..models import OCRConfig, OCRPageResult
from .base import OCREngineBase


class OCRmyPDFEngine(OCREngineBase):
    name = "ocrmypdf"

    def availability(self, context: dict[str, Any] | None = None) -> tuple[bool, str]:
        if importlib.util.find_spec("fitz") is None:
            return False, "deps_missing:fitz"
        if not shutil.which("ocrmypdf"):
            return False, "binary_missing:ocrmypdf"
        return True, ""

    def run_page(
        self,
        *,
        file_bytes: bytes,
        page_number: int,
        config: OCRConfig,
        context: dict[str, Any] | None = None,
    ) -> OCRPageResult:
        if not bool((context or {}).get("allow_ocrmypdf_page")):
            return OCRPageResult(
                page_number=page_number,
                text="",
                engine=self.name,
                dpi=int(config.dpi or 220),
                languages=config.languages or "eng+rus",
                warnings=["ocrmypdf_page_mode_disabled"],
            )
        try:
            import fitz
        except Exception:
            return OCRPageResult(
                page_number=page_number,
                text="",
                engine=self.name,
                dpi=int(config.dpi or 220),
                languages=config.languages or "eng+rus",
                warnings=["ocr_dependencies_missing"],
            )

        try:
            with tempfile.TemporaryDirectory(prefix="ocrmypdf_page_") as tmp_dir:
                input_pdf = Path(tmp_dir) / "input.pdf"
                output_pdf = Path(tmp_dir) / "output_ocr.pdf"
                input_pdf.write_bytes(file_bytes)
                cmd = [
                    "ocrmypdf",
                    "--skip-text",
                    "--redo-ocr",
                    "--force-ocr",
                    "--optimize",
                    "0",
                    "--image-dpi",
                    str(int(config.dpi or 220)),
                    str(input_pdf),
                    str(output_pdf),
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                if proc.returncode != 0 or not output_pdf.exists():
                    return OCRPageResult(
                        page_number=page_number,
                        text="",
                        engine=self.name,
                        dpi=int(config.dpi or 220),
                        languages=config.languages or "eng+rus",
                        warnings=["ocr_engine_not_available"],
                        metadata={"stderr": (proc.stderr or "")[:500]},
                    )
                doc = fitz.open(str(output_pdf))
                try:
                    if page_number < 1 or page_number > len(doc):
                        return OCRPageResult(
                            page_number=page_number,
                            text="",
                            engine=self.name,
                            dpi=int(config.dpi or 220),
                            languages=config.languages or "eng+rus",
                            warnings=["ocr_page_out_of_range"],
                        )
                    page = doc.load_page(page_number - 1)
                    text = page.get_text("text") or ""
                    return OCRPageResult(
                        page_number=page_number,
                        text=text,
                        engine=self.name,
                        dpi=int(config.dpi or 220),
                        languages=config.languages or "eng+rus",
                        warnings=[],
                    )
                finally:
                    doc.close()
        except subprocess.TimeoutExpired:
            return OCRPageResult(
                page_number=page_number,
                text="",
                engine=self.name,
                dpi=int(config.dpi or 220),
                languages=config.languages or "eng+rus",
                warnings=["ocr_timeout"],
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
