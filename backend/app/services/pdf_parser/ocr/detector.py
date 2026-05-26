from __future__ import annotations

from typing import Any

from .models import OCRConfig, OCRDecision


class OCRDetector:
    """Structural detector for deciding when OCR is needed."""

    @staticmethod
    def decide(
        *,
        page_number: int,
        text: str,
        quality_score: float,
        warnings: list[str],
        metadata: dict[str, Any],
        config: OCRConfig,
    ) -> OCRDecision:
        warnings_set = set(warnings or [])
        text_value = (text or "").strip()
        chars = len(text_value)
        word_count = int(metadata.get("word_count") or len(text_value.split()))
        image_count = int(metadata.get("image_count") or 0)
        line_count = int(metadata.get("word_line_count") or 0)
        graph_axis_lines = int(metadata.get("line_type_graph_axis") or 0)
        short_line_heavy = bool(metadata.get("short_line_heavy_page"))
        page_area = max(1.0, float(metadata.get("page_width") or 0.0) * float(metadata.get("page_height") or 0.0))
        text_density = chars / max(1.0, page_area / 1000.0)
        quality_components = metadata.get("pre_ocr_quality_components") or metadata.get("quality_components") or {}
        column_mixing_noise = int(quality_components.get("column_mixing_noise") or 0)
        noise_char_ratio = float(quality_components.get("noise_char_ratio") or 0.0)
        lexical_word_ratio = float(quality_components.get("lexical_word_ratio") or 0.0)
        replacement_chars = int(quality_components.get("replacement_chars") or 0)
        cid_glyph_noise = int(quality_components.get("cid_glyph_noise") or 0)

        details: dict[str, Any] = {
            "control_mode": config.control_mode,
            "requested_engine": config.requested_engine,
            "engine": config.engine,
            "engine_plan": list(config.fallback_engines or [config.engine]),
            "engine_selection_reason": config.engine_selection_reason,
            "chars": chars,
            "words": word_count,
            "image_count": image_count,
            "quality_score": round(float(quality_score or 0.0), 4),
            "min_quality_score": float(config.min_quality_score),
            "text_density": round(text_density, 4),
            "min_text_density": float(config.min_text_density),
            "noise_char_ratio": round(noise_char_ratio, 4),
            "lexical_word_ratio": round(lexical_word_ratio, 4),
            "engine_warnings": list(config.engine_warnings),
        }

        if not config.enabled or config.skip:
            return OCRDecision(
                page_number=page_number,
                apply_ocr=False,
                reason="manual_skip" if config.skip else "disabled",
                engine=config.engine,
                merge_strategy=config.merge_strategy,
                details=details,
            )
        if config.force:
            details["trigger"] = "force_ocr"
            return OCRDecision(page_number=page_number, apply_ocr=True, reason="forced_by_user", engine=config.engine, merge_strategy=config.merge_strategy, details=details)
        if config.pages and page_number in config.pages and config.control_mode == "selective":
            details["trigger"] = "selected_page"
            return OCRDecision(page_number=page_number, apply_ocr=True, reason="selected_page", engine=config.engine, merge_strategy=config.merge_strategy, details=details)
        if config.control_mode == "selective":
            details["trigger"] = "not_selected_page"
            return OCRDecision(page_number=page_number, apply_ocr=False, reason="not_selected_page", engine=config.engine, merge_strategy=config.merge_strategy, details=details)



        image_only = image_count > 0 and chars == 0 and word_count == 0
        empty_layer = "empty_text" in warnings_set or chars == 0
        low_text = chars < int(config.min_text_chars) or word_count < int(config.min_words)
        low_density = text_density < float(config.min_text_density) and (chars < 350 or word_count < 75)
        low_quality = quality_score < float(config.min_quality_score)
        scanned_like = "possible_scanned_page" in warnings_set or "ocr_recommended" in warnings_set or (image_count > 0 and (low_text or low_density))
        broken_encoding = (
            noise_char_ratio >= float(config.broken_encoding_noise_ratio)
            or replacement_chars >= 3
            or cid_glyph_noise >= 8
            or (word_count >= 20 and lexical_word_ratio > 0.0 and lexical_word_ratio < 0.28)
        )
        poor_structure = line_count > 0 and graph_axis_lines >= max(3, line_count // 3)
        ordering_risk = "possible_two_columns" in warnings_set or column_mixing_noise > 0 or short_line_heavy

        reasons: list[str] = []
        if image_only:
            reasons.append("image_only_page")
        if empty_layer:
            reasons.append("empty_text_layer")
        if scanned_like:
            reasons.append("scanned_like_page")
        if low_text:
            reasons.append("too_few_words" if word_count < int(config.min_words) else "low_text_chars")
        if low_density:
            reasons.append("low_text_density")
        if broken_encoding:
            reasons.append("broken_encoding")
        if low_quality:
            reasons.append("low_quality_score")
        if poor_structure:
            reasons.append("poor_line_structure")
        if ordering_risk:
            reasons.append("reading_order_risk")

        low_text_only_reasons = {"too_few_words", "low_text_chars", "low_text_density"}
        if reasons and set(reasons).issubset(low_text_only_reasons):
            short_clean_text_layer = (
                image_count == 0
                and chars > 0
                and word_count > 0
                and quality_score >= float(config.min_quality_score)
                and noise_char_ratio < float(config.broken_encoding_noise_ratio)
                and replacement_chars == 0
                and cid_glyph_noise == 0
                and graph_axis_lines == 0
            )
            if short_clean_text_layer:
                details["triggers"] = reasons
                details["trigger"] = "short_clean_text_layer"
                details["suppressed_triggers"] = reasons
                return OCRDecision(
                    page_number=page_number,
                    apply_ocr=False,
                    reason="short_clean_text_layer",
                    engine=config.engine,
                    merge_strategy=config.merge_strategy,
                    details=details,
                )

        details["triggers"] = reasons
        if not reasons:
            details["trigger"] = "quality_ok"
            return OCRDecision(
                page_number=page_number,
                apply_ocr=False,
                reason="not_recommended",
                engine=config.engine,
                merge_strategy=config.merge_strategy,
                details=details,
            )

        reason_priority = [
            "image_only_page",
            "empty_text_layer",
            "broken_encoding",
            "low_quality_score",
            "scanned_like_page",
            "low_text_density",
            "too_few_words",
            "low_text_chars",
            "poor_line_structure",
            "reading_order_risk",
        ]
        primary = next((reason for reason in reason_priority if reason in reasons), reasons[0])
        details["trigger"] = primary
        return OCRDecision(
            page_number=page_number,
            apply_ocr=True,
            reason=primary,
            engine=config.engine,
            merge_strategy=config.merge_strategy,
            details=details,
        )
