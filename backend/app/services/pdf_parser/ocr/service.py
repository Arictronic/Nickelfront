from __future__ import annotations

import logging
import re
from typing import Any

from .detector import OCRDetector
from .engines.base import OCREngineBase
from .engines.ocrmypdf_engine import OCRmyPDFEngine
from .engines.paddle_engine import PaddleEngine
from .engines.surya_engine import SuryaEngine
from .engines.tesseract_engine import TesseractEngine
from .models import OCRConfig, OCRDecision, OCRPageResult

logger = logging.getLogger(__name__)


class OCRService:
    REASON_CODES = {
        "disabled",
        "not_recommended",
        "low_quality_score",
        "empty_text_layer",
        "engine_unavailable",
        "dependencies_missing",
        "ocr_failed",
        "applied",
    }
    MIN_OCR_GAIN = 0.03
    VALID_ENGINES = {"auto", "tesseract", "paddle", "ocrmypdf", "surya"}
    HEAVY_PAGE_ENGINES = {"ocrmypdf"}

    def __init__(self) -> None:



        self._engines: dict[str, OCREngineBase] = {
            "tesseract": TesseractEngine(),
            "paddle": PaddleEngine(),
            "ocrmypdf": OCRmyPDFEngine(),
            "surya": SuryaEngine(),
        }
        self._availability_cache: dict[tuple[str, bool, bool], tuple[bool, str]] = {}

    @staticmethod
    def parse_pages_spec(raw: str | None) -> tuple[set[int], list[str]]:
        if not raw:
            return set(), []
        pages: set[int] = set()
        warnings: list[str] = []
        for chunk in re.split(r"\s*,\s*", str(raw).strip()):
            if not chunk:
                continue
            if "-" in chunk:
                left, right = chunk.split("-", 1)
                try:
                    start = int(left.strip())
                    end = int(right.strip())
                except Exception:
                    warnings.append(f"ocr_pages_invalid_chunk:{chunk}")
                    continue
                if start > end:
                    start, end = end, start
                pages.update(range(max(1, start), max(1, end) + 1))
            else:
                try:
                    pages.add(max(1, int(chunk)))
                except Exception:
                    warnings.append(f"ocr_pages_invalid_chunk:{chunk}")
                    continue
        return pages, warnings

    @staticmethod
    def _parse_engine_list(raw: Any) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, str):
            chunks = re.split(r"[;,\s]+", raw.strip())
        elif isinstance(raw, (list, tuple, set)):
            chunks = [str(item) for item in raw]
        else:
            chunks = [str(raw)]
        result: list[str] = []
        for chunk in chunks:
            name = str(chunk or "").strip().lower()
            if name and name in OCRService.VALID_ENGINES and name != "auto" and name not in result:
                result.append(name)
        return result

    @staticmethod
    def normalize_reason(value: str) -> str:
        v = str(value or "").strip().lower()
        aliases = {
            "quality_ok": "not_recommended",
            "selected_page": "applied",
            "forced_by_user": "applied",
            "not_selected_page": "not_recommended",
            "manual_skip": "disabled",
            "scanned_like_page": "applied",
            "image_only_page": "empty_text_layer",
            "low_text_density": "applied",
            "too_few_words": "applied",
            "broken_encoding": "applied",
            "poor_extraction_quality": "low_quality_score",
            "poor_line_structure": "applied",
            "reading_order_risk": "applied",
            "auto_detector": "applied",
            "ocr_engine_not_available": "engine_unavailable",
            "ocr_engine_not_allowed": "engine_unavailable",
            "ocr_dependencies_missing": "dependencies_missing",
            "tesseract_binary_missing": "dependencies_missing",
            "ocrmypdf_page_mode_disabled": "engine_unavailable",
        }
        normalized = aliases.get(v, v)
        return normalized if normalized in OCRService.REASON_CODES else "ocr_failed"

    def _engine_availability(
        self,
        engine_name: str,
        *,
        allow_ocrmypdf_page: bool = False,
        surya_experimental_enabled: bool = False,
    ) -> tuple[bool, str]:
        key = (engine_name, bool(allow_ocrmypdf_page), bool(surya_experimental_enabled))
        if key in self._availability_cache:
            return self._availability_cache[key]
        engine = self._engines.get(engine_name)
        if engine is None:
            result = (False, "engine_unknown")
        else:
            result = engine.availability(
                {
                    "allow_ocrmypdf_page": bool(allow_ocrmypdf_page),
                    "surya_experimental_enabled": bool(surya_experimental_enabled),
                }
            )
        self._availability_cache[key] = result
        return result

    def _select_auto_engine(self, *, allow_paddle: bool, warnings: list[str]) -> tuple[str, list[str], str]:
        tesseract_available, tesseract_reason = self._engine_availability("tesseract")
        if tesseract_available:
            fallbacks = ["tesseract"]
            if allow_paddle and self._engine_availability("paddle")[0]:
                fallbacks.append("paddle")
            return "tesseract", fallbacks, "auto_tesseract_available"

        warnings.append(f"ocr_tesseract_unavailable:{tesseract_reason or 'unknown'}")
        if allow_paddle:
            paddle_available, paddle_reason = self._engine_availability("paddle")
            if paddle_available:
                return "paddle", ["paddle", "tesseract"], "auto_tesseract_unavailable_paddle_allowed"
            warnings.append(f"ocr_paddle_unavailable:{paddle_reason or 'unknown'}")




        return "tesseract", ["tesseract"], "auto_no_safe_runtime_available"

    def build_config(self, opts: dict[str, Any]) -> OCRConfig:
        requested_engine = str(opts.get("ocr_engine") or "auto").strip().lower()
        if requested_engine not in self.VALID_ENGINES:
            requested_engine = "auto"
        control_mode = str(opts.get("ocr_control_mode") or "auto").strip().lower()
        if control_mode not in {"auto", "selective", "manual"}:
            control_mode = "auto"
        if control_mode == "manual":
            control_mode = "selective"
        merge_strategy = str(opts.get("ocr_merge_strategy") or "replace_low_quality").strip().lower()
        if merge_strategy not in {"replace_low_quality", "prefer_pdf_text", "prefer_ocr", "hybrid_lines", "diagnostics_only"}:
            merge_strategy = "replace_low_quality"

        explicit_fallbacks = self._parse_engine_list(opts.get("ocr_fallback_engines"))
        allow_paddle = bool(opts.get("ocr_allow_paddle")) or requested_engine == "paddle" or "paddle" in explicit_fallbacks
        allow_ocrmypdf_page = bool(opts.get("ocr_allow_ocrmypdf_page")) or requested_engine == "ocrmypdf"
        engine_warnings: list[str] = []

        if requested_engine == "auto":
            engine, fallback_engines, selection_reason = self._select_auto_engine(
                allow_paddle=allow_paddle,
                warnings=engine_warnings,
            )
        else:
            engine = requested_engine
            fallback_engines = [engine]
            if explicit_fallbacks:
                fallback_engines.extend(name for name in explicit_fallbacks if name not in fallback_engines)
            elif engine not in {"tesseract", "ocrmypdf", "surya"}:
                fallback_engines.append("tesseract")
            selection_reason = "manual_engine_selected"

        if not allow_paddle:
            fallback_engines = [name for name in fallback_engines if name != "paddle"]
        if not allow_ocrmypdf_page and requested_engine != "ocrmypdf":
            fallback_engines = [name for name in fallback_engines if name != "ocrmypdf"]
        if engine not in fallback_engines:
            fallback_engines.insert(0, engine)

        fallback_engines = list(dict.fromkeys(fallback_engines))

        pages_raw = opts.get("ocr_only_pages") or opts.get("ocr_pages") or ""
        pages, page_warnings = self.parse_pages_spec(str(pages_raw or ""))
        total_pages = int(opts.get("_pdf_total_pages") or 0)
        if total_pages > 0 and pages:
            valid_pages = {p for p in pages if 1 <= p <= total_pages}
            if len(valid_pages) != len(pages):
                page_warnings.append("ocr_pages_out_of_range_trimmed")
            pages = valid_pages
        return OCRConfig(
            enabled=bool(opts.get("ocr_enabled")) and not bool(opts.get("ocr_skip")),
            control_mode=control_mode,
            requested_engine=requested_engine,
            engine=engine,
            fallback_engines=fallback_engines,
            force=bool(opts.get("ocr_force")),
            skip=bool(opts.get("ocr_skip")),
            pages=pages,
            dpi=int(opts.get("ocr_dpi") or 220),
            languages=str(opts.get("ocr_languages") or "eng+rus"),
            merge_strategy=merge_strategy,
            min_quality_score=float(opts.get("ocr_min_quality_score") or 0.45),
            min_confidence=float(opts.get("ocr_min_confidence") or 0.55),
            min_text_chars=int(opts.get("ocr_min_text_chars") or 180),
            min_words=int(opts.get("ocr_min_words") or 35),
            min_text_density=float(opts.get("ocr_min_text_density") or 0.35),
            broken_encoding_noise_ratio=float(opts.get("ocr_broken_encoding_noise_ratio") or 0.02),
            allow_paddle=allow_paddle,
            allow_ocrmypdf_page=allow_ocrmypdf_page,
            emit_lines=bool(opts.get("ocr_emit_lines")),
            debug=bool(opts.get("ocr_debug")),
            engine_selection_reason=selection_reason,
            engine_warnings=engine_warnings,
            page_selection_warnings=page_warnings,
        )

    def decide(
        self,
        *,
        page_number: int,
        text: str,
        quality_score: float,
        warnings: list[str],
        metadata: dict[str, Any],
        config: OCRConfig,
    ) -> OCRDecision:
        return OCRDetector.decide(
            page_number=page_number,
            text=text,
            quality_score=quality_score,
            warnings=warnings,
            metadata=metadata,
            config=config,
        )

    def _engine_plan(self, config: OCRConfig) -> list[str]:
        if config.control_mode == "selective" and not config.force:
            engines = [config.engine]
        else:
            engines = [config.engine] + [name for name in config.fallback_engines if name != config.engine]
        clean: list[str] = []
        for name in engines:
            if name == "paddle" and not config.allow_paddle and config.requested_engine != "paddle":
                continue
            if name == "ocrmypdf" and not config.allow_ocrmypdf_page:
                continue
            if name not in self._engines:
                continue
            if name not in clean:
                clean.append(name)
        return clean or [config.engine]

    def run(
        self,
        *,
        file_bytes: bytes,
        page_number: int,
        config: OCRConfig,
        context: dict[str, Any] | None = None,
    ) -> OCRPageResult:
        engines = self._engine_plan(config)
        warnings: list[str] = []
        logger.info(
            "OCR page %s: engine_plan=%s requested=%s selection=%s",
            page_number,
            engines,
            config.requested_engine,
            config.engine_selection_reason,
        )
        for engine_name in engines:
            engine = self._engines.get(engine_name)
            if engine is None:
                warnings.append("ocr_engine_not_available")
                logger.info("OCR page %s: engine %s skipped, not registered", page_number, engine_name)
                continue
            available, availability_reason = self._engine_availability(
                engine_name,
                allow_ocrmypdf_page=config.allow_ocrmypdf_page,
                surya_experimental_enabled=bool((context or {}).get("surya_experimental_enabled")),
            )
            if not available and config.requested_engine == "auto":
                warnings.append("ocr_dependencies_missing" if "deps_missing" in availability_reason or "binary_missing" in availability_reason else "ocr_engine_not_available")
                warnings.append(f"{engine_name}_unavailable:{availability_reason or 'unknown'}")
                logger.info("OCR page %s: engine %s unavailable: %s", page_number, engine_name, availability_reason)
                continue
            result = engine.run_page(
                file_bytes=file_bytes,
                page_number=page_number,
                config=config,
                context={
                    **(context or {}),
                    "allow_ocrmypdf_page": bool(config.allow_ocrmypdf_page),
                },
            )
            if result.text.strip():
                result.warnings.extend(warnings)
                if engine_name != config.engine:
                    result.warnings.append(f"ocr_fallback_used:{engine_name}")
                logger.info(
                    "OCR page %s: engine %s applied, chars=%s, confidence=%s",
                    page_number,
                    result.engine,
                    len(result.text.strip()),
                    result.confidence,
                )
                return result
            warnings.extend(result.warnings)
            logger.info("OCR page %s: engine %s returned no text; warnings=%s", page_number, engine_name, result.warnings)
        return OCRPageResult(
            page_number=page_number,
            text="",
            engine=config.engine,
            dpi=config.dpi,
            languages=config.languages,
            warnings=warnings or ["ocr_failed"],
        )

    def merge_text(
        self,
        *,
        original_text: str,
        ocr_result: OCRPageResult,
        quality_score: float,
        ocr_quality_score: float | None = None,
        config: OCRConfig,
    ) -> tuple[str, str, dict[str, Any]]:
        strategy = config.merge_strategy
        ocr_text = (ocr_result.text or "").strip()
        base_text = (original_text or "").strip()
        ocr_conf = float(ocr_result.confidence or 0.0)
        ocr_conf_ok = ocr_conf >= float(config.min_confidence or 0.0)
        diagnostics: dict[str, Any] = {
            "strategy": strategy,
            "pdf_chars": len(base_text),
            "ocr_chars": len(ocr_text),
            "ocr_confidence": round(ocr_conf, 4),
            "ocr_conf_ok": bool(ocr_conf_ok),
            "quality_score_pdf": round(float(quality_score or 0.0), 4),
            "quality_score_ocr": round(float(ocr_quality_score or 0.0), 4) if ocr_quality_score is not None else None,
        }
        quality_gain = None
        if ocr_quality_score is not None:
            quality_gain = float(ocr_quality_score) - float(quality_score or 0.0)
            diagnostics["quality_gain"] = round(quality_gain, 4)
        if strategy == "diagnostics_only":
            diagnostics["decision"] = "keep_pdf"
            return base_text, "diagnostics_only", diagnostics
        if strategy == "prefer_pdf_text":
            diagnostics["decision"] = "keep_pdf"
            return base_text, "prefer_pdf_text", diagnostics
        if strategy == "prefer_ocr":
            gain_ok = quality_gain is None or quality_gain >= self.MIN_OCR_GAIN
            if ocr_text and ocr_conf_ok and gain_ok:
                diagnostics["decision"] = "use_ocr"
                return ocr_text, "prefer_ocr", diagnostics
            if ocr_text:
                diagnostics["decision"] = "fallback_pdf_low_conf_or_gain"
                return base_text, "prefer_ocr_reject", diagnostics
            diagnostics["decision"] = "fallback_pdf"
            return base_text, "prefer_ocr_fallback_pdf", diagnostics
        if strategy == "hybrid_lines":
            if not ocr_text:
                diagnostics["decision"] = "pdf_only"
                return base_text, "hybrid_lines_pdf_only", diagnostics
            if not base_text:
                diagnostics["decision"] = "ocr_only"
                return ocr_text, "hybrid_lines_ocr_only", diagnostics
            pdf_lines = [line.strip() for line in base_text.splitlines() if line.strip()]
            ocr_lines = [line.text.strip() for line in (ocr_result.lines or []) if line.text.strip()]
            if ocr_result.lines:
                merged = "\n".join(ocr_lines).strip()
                if not merged:
                    merged = "\n".join([base_text, ocr_text]).strip()
            else:
                merged = "\n".join([base_text, ocr_text]).strip()
            overlap = set(pdf_lines) & set(ocr_lines)
            diagnostics.update(
                {
                    "pdf_lines": len(pdf_lines),
                    "ocr_lines": len(ocr_lines),
                    "line_overlap": len(overlap),
                    "line_conflicts_estimate": max(0, len(ocr_lines) - len(overlap)),
                }
            )
            diagnostics["decision"] = "hybrid_merge"
            return merged, "hybrid_lines", diagnostics

        gain_ok = quality_gain is None or quality_gain >= self.MIN_OCR_GAIN
        if quality_score < config.min_quality_score and ocr_text and ocr_conf_ok and gain_ok:
            diagnostics["decision"] = "replace_with_ocr"
            return ocr_text, "replace_low_quality", diagnostics
        if quality_score < config.min_quality_score and ocr_text and not ocr_conf_ok:
            diagnostics["decision"] = "reject_ocr_low_conf"
            return base_text, "replace_low_quality_reject_low_conf", diagnostics
        if quality_score < config.min_quality_score and ocr_text and ocr_conf_ok and not gain_ok:
            diagnostics["decision"] = "reject_ocr_low_gain"
            return base_text, "replace_low_quality_reject_low_gain", diagnostics
        diagnostics["decision"] = "keep_pdf"
        return base_text, "replace_low_quality_keep_pdf", diagnostics
