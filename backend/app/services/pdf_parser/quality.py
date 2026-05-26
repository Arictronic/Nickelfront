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

logger = logging.getLogger(__name__)

class PDFQualityMixin:
    """Candidate scoring and page quality diagnostics."""

    def _candidate(self, method: str, raw_text: str, page_num: int, opts: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        cleaned = self._clean_page_text(raw_text or "", opts)
        score = self._score_text(cleaned, method=method, opts=opts, metadata=metadata)
        warnings: list[str] = []
        if not cleaned:
            warnings.append("empty_text")
        if "columns" in method:
            warnings.append("two_column_mode")
        if "word" in method:
            warnings.append("word_layout_mode")
        if self._has_many_broken_lines(cleaned):
            warnings.append("many_short_lines")
        return {"method": method, "text": cleaned, "quality_score": score, "warnings": warnings, "metadata": {"page": page_num}}

    def _select_best_candidate(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        if not candidates:
            return {"method": "empty", "text": "", "quality_score": 0.0, "warnings": ["no_candidates"], "metadata": {}}
        return max(candidates, key=lambda item: float(item.get("quality_score") or 0.0))

    def _has_many_broken_lines(self, text: str) -> bool:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if len(lines) < 20:
            return False
        short = sum(1 for line in lines if len(line) < 35)
        return short / max(1, len(lines)) > 0.55

    def _count_obvious_duplicate_math(self, text: str) -> int:
        value = text or ""
        greek = r"[Α-ωϑϕϵϰ-Ͽ𝛂-𝟋]"
        count = len(re.findall(fr"({greek})\1", value))
        count += len(re.findall(r"(?<!\w)([A-Za-zΑ-ω𝛂-𝟋]{1,4}\d*/\d+)\1(?!\w)", value))
        count += len(re.findall(r"(?<!\w)([A-Za-zΑ-ω𝛂-𝟋]{1,4}(?:[=+−\-*/^][A-Za-zΑ-ω𝛂-𝟋0-9]+){1,4})\1(?!\w)", value))
        return count

    def _count_rotated_sidebar_noise(self, text: str) -> int:
        value = text or ""
        patterns = [
            r"\bviXra\b",
            r"\b\d+v\d+\.\d+:viXra\b",
            r"\][^\n]{4,80}\[",
            r"\byaM\b",
        ]
        return sum(len(re.findall(pattern, value, flags=re.IGNORECASE)) for pattern in patterns)

    def _count_watermark_noise(self, text: str, metadata: dict[str, Any] | None = None) -> int:
        value = text or ""
        if not value:
            return 0



        removed = int((metadata or {}).get("watermark_words_removed") or 0)
        isolated = 0
        for line in value.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if _WATERMARK_LINE_RE.fullmatch(stripped) or (len(stripped) <= 40 and _WATERMARK_LINE_RE.search(stripped) and len(stripped.split()) <= 4):
                isolated += 1
        return removed + isolated

    def _count_column_mixing_noise(self, text: str) -> int:
        value = text or ""



        count = len(re.findall(r"\b(?:Abstract|Keywords?|Introduction|References|Conclusions?)\s+(?:[a-z]|direct|energy|formation|hydrogen)", value))
        count += len(re.findall(r"[a-z]{4,}-(?:[a-z]{2,})[A-Z][a-z]", value))
        count += len(re.findall(r"\b[a-z]{4,}(?:hydro|thermo|electro|micro|geo|energy)[a-z]{4,}\b", value))
        return count

    def _lexical_word_ratio(self, text: str) -> float:
        tokens = re.findall(r"[A-Za-zА-Яа-я]{3,}", text or "")
        if not tokens:
            return 0.0
        good = 0
        for token in tokens:



            if re.search(r"[aeiouyаеёиоуыэюя]", token, re.IGNORECASE):
                good += 1
            elif token.isupper() and len(token) <= 8:
                good += 1
        return good / max(1, len(tokens))

    def _noise_char_ratio(self, text: str) -> float:
        value = text or ""
        if not value:
            return 0.0
        noisy = 0
        for ch in value:
            if ch in "□�":
                noisy += 1
            elif ord(ch) < 32 and ch not in "\n\t":
                noisy += 1
            elif "\ue000" <= ch <= "\uf8ff":
                noisy += 1
        noisy += len(_CID_TOKEN_RE.findall(value)) * 4
        return noisy / max(1, len(value))

    def _quality_components(self, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
        chars = len(text or "")
        words = len(re.findall(r"\w+", text or ""))
        non_ascii_noise = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\t")
        replacement_chars = (text or "").count("�")
        return {
            "chars": chars,
            "words": words,
            "line_count": len((text or "").splitlines()),
            "replacement_chars": replacement_chars,
            "control_noise": non_ascii_noise,
            "cid_glyph_noise": len(_CID_TOKEN_RE.findall(text or "")),
            "noise_char_ratio": round(self._noise_char_ratio(text or ""), 4),
            "lexical_word_ratio": round(self._lexical_word_ratio(text or ""), 4),
            "rotated_sidebar_noise": self._count_rotated_sidebar_noise(text or ""),
            "column_mixing_noise": self._count_column_mixing_noise(text or ""),
            "watermark_line_noise": self._count_watermark_noise(text or "", metadata=metadata),
            "footnote_line_count": metadata.get("footnote_line_count", 0),
            "watermark_words_removed": metadata.get("watermark_words_removed", 0),
            "image_count": metadata.get("image_count", 0),
            "table_count": metadata.get("table_count", 0),
            "page_profile": metadata.get("page_profile", ""),
            "line_type_body": metadata.get("line_type_body", 0),
            "line_type_caption": metadata.get("line_type_caption", 0),
            "line_type_formula": metadata.get("line_type_formula", 0),
            "line_type_reference": metadata.get("line_type_reference", 0),
            "line_type_graph_axis": metadata.get("line_type_graph_axis", 0),
            "non_body_lines_removed": metadata.get("non_body_lines_removed", 0),
            "math_microline_repairs": metadata.get("math_microline_repairs", 0),
            "arxiv_footer_lines_removed": metadata.get("arxiv_footer_lines_removed", 0),
        }

    def _score_text(self, text: str, *, method: str, opts: dict[str, Any], metadata: dict[str, Any]) -> float:
        value = text or ""
        chars = len(value.strip())
        if chars == 0:
            return 0.0
        words = len(re.findall(r"\w+", value))
        noise_ratio = self._noise_char_ratio(value)
        lexical_ratio = self._lexical_word_ratio(value)
        score = 0.15



        score += min(0.28, chars / 9000)
        score += min(0.22, words / 1000)
        score += min(0.10, lexical_ratio * 0.12)
        if noise_ratio:
            score -= min(0.22, noise_ratio * 8.0)
        if words and lexical_ratio < 0.45:
            score -= min(0.12, (0.45 - lexical_ratio) * 0.30)
        if method in {"pdfplumber_columns", "pdfplumber_word_columns"}:
            score += 0.12
        if method == "pdfplumber_word_layout":
            score += 0.03
        if metadata.get("columns_detected") and method == "pdfplumber_word_layout":
            score -= 0.12
        if metadata.get("columns_detected") and method in {"pdfplumber_columns", "pdfplumber_word_columns"}:
            score += 0.08
        if method.startswith("ocr_"):
            score += 0.04
        if method == "ocr_tesseract":
            score += 0.02
        if self._has_many_broken_lines(value):
            score -= 0.08
        duplicate_math = self._count_obvious_duplicate_math(value)
        if duplicate_math:
            score -= min(0.12, duplicate_math * 0.015)
        if value.count("�"):
            score -= min(0.12, value.count("�") / 20)
        cid_noise = len(_CID_TOKEN_RE.findall(value))
        if cid_noise:
            score -= min(0.08, cid_noise * 0.006)
        sidebar_noise = self._count_rotated_sidebar_noise(value)
        if sidebar_noise:
            score -= min(0.25, sidebar_noise * 0.06)
        mixing_noise = self._count_column_mixing_noise(value)
        if mixing_noise:
            score -= min(0.20, mixing_noise * 0.04)
        watermark_noise = self._count_watermark_noise(value, metadata=metadata)
        if watermark_noise:
            score -= min(0.18, watermark_noise * 0.05)
        if metadata.get("table_count"):
            score += 0.03





        if metadata.get("formula_heavy_page"):
            score += 0.06
        if metadata.get("reference_page"):
            score += 0.04
        if metadata.get("title_page"):
            score += 0.04
        if metadata.get("figure_only_page") or metadata.get("figure_plate_page"):
            if not (cid_noise or sidebar_noise or mixing_noise or watermark_noise or value.count("�")):
                score = max(score, 0.72 if metadata.get("figure_only_page") else 0.78)
        elif metadata.get("image_count", 0) and chars < int(opts.get("min_text_chars") or 300):
            score -= 0.15
        return max(0.0, min(1.0, score))

    def _classify_page_content(self, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
        value = text or ""
        stripped = value.strip()
        image_count = int(metadata.get("image_count") or 0)
        table_count = int(metadata.get("table_count") or 0)
        chars = len(stripped)
        words = len(re.findall(r"[A-Za-zА-Яа-я]{3,}", value))
        lines = [line.strip() for line in value.splitlines() if line.strip()]


        line_type_body = int(metadata.get("line_type_body") or 0)
        line_type_caption = int(metadata.get("line_type_caption") or 0) + int(metadata.get("line_type_figure_label") or 0)
        line_type_formula = int(metadata.get("line_type_formula") or 0)
        line_type_reference = int(metadata.get("line_type_reference") or 0)
        line_type_graph_axis = int(metadata.get("line_type_graph_axis") or 0)
        line_type_arxiv = int(metadata.get("line_type_arxiv_footer") or 0)
        line_type_page_number = int(metadata.get("line_type_page_number") or 0)
        line_type_affiliation = int(metadata.get("line_type_affiliation") or 0)
        content_formula_blocks = int(metadata.get("content_block_formula_count") or 0)
        content_caption_blocks = int(metadata.get("content_block_caption_count") or 0)
        formula_candidate_count = len(re.findall(r"\[Formula candidate\]", value))
        math_symbol_count = len(_MATH_SYMBOL_RE.findall(value))
        lexical_ratio = self._lexical_word_ratio(value)

        caption_lines = line_type_caption or sum(1 for line in lines if _CAPTION_RE.match(line) or _CAPTION_START_RE.match(line) or _FIGURE_LABEL_LINE_RE.match(line))
        label_only_lines = int(metadata.get("line_type_figure_label") or 0) or sum(1 for line in lines if _LABEL_ONLY_LINE_RE.match(line))
        graph_axis_lines = line_type_graph_axis or sum(1 for line in lines if self._is_graph_axis_or_table_line(line))
        formula_lines = line_type_formula or sum(1 for line in lines if self._is_formula_like_line(line))
        reference_lines = line_type_reference or sum(1 for line in lines if self._is_reference_like_line(line))
        has_supplement_hint = bool(re.search(r"\b(?:Supplementary|Supporting\s+Information|Fig\.\s*S\d+|Figure\s*S\d+|Table\s*S\d+)\b", value, re.IGNORECASE))
        has_reference_heading = bool(re.search(r"(?:^|\n)\s*(?:References|Bibliography|Literature\s+Cited)\s*(?:\n|$)", value, re.IGNORECASE))
        has_title_signals = bool(
            re.search(r"\b(?:Abstract|Keywords?)\b", value, re.IGNORECASE)
            or line_type_affiliation >= 2
            or ("@" in value and len(lines) <= 80)
        )

        label_only_page = bool(chars < 220 and label_only_lines >= 1 and words <= 24)
        figure_plate = bool(
            image_count > 0
            and caption_lines > 0
            and (chars < 2600 or line_type_body < max(4, len(lines) // 5))
        )
        figure_heavy = bool(
            (
                image_count > 0
                and (caption_lines > 0 or has_supplement_hint or graph_axis_lines >= 2 or label_only_lines >= 2)
                and (chars < 2200 or words < 320 or graph_axis_lines >= 3)
            )
            or label_only_page
        )
        figure_only = bool(
            (
                image_count > 0
                and (chars < 650 or words < 110 or line_type_body <= 2)
                and (caption_lines > 0 or graph_axis_lines > 0 or has_supplement_hint or label_only_lines > 0)
            )
            or label_only_page
        )
        reference_page = bool(
            has_reference_heading
            or bool(metadata.get("reference_continuation_page"))
            or (reference_lines >= 4 and reference_lines >= max(2, len(lines) // 5))
            or (reference_lines >= 8 and words < 900)
        )
        prose_dominant_formula_mix = bool(
            lexical_ratio >= 0.72
            and words >= 100
            and line_type_body >= max(6, formula_lines * 2)
            and content_formula_blocks <= 1
            and formula_candidate_count == 0
        )
        profile_obj = self._domain_profile(metadata)
        domain_prose_formula_guard = bool(
            formula_candidate_count == 0
            and content_formula_blocks == 0
            and math_symbol_count <= 1
            and words >= 90
            and line_type_body >= max(8, formula_lines * 3)
            and lexical_ratio >= 0.72
            and profile_obj.prose_guard_re.search(value)
        )
        formula_heavy = bool(
            not domain_prose_formula_guard
            and (
                formula_candidate_count >= 2
                or content_formula_blocks >= 3
                or (math_symbol_count >= max(12, len(lines) // 2) and lexical_ratio < 0.72)
                or (
                    not prose_dominant_formula_mix
                    and (
                        (formula_lines >= 5 and formula_lines >= max(3, len(lines) // 5))
                        or (formula_lines >= 3 and words < 220 and len(lines) < 35)
                    )
                )
            )
        )
        graph_heavy = bool(graph_axis_lines >= max(3, len(lines) // 6) and image_count > 0)
        title_page = bool(int(metadata.get("page") or 0) == 1 and has_title_signals and not reference_page)
        supplement_page = bool(has_supplement_hint or re.search(r"(?:^|\n)\s*Supporting\s+Information\b", value, re.IGNORECASE))
        supplement_caption_page = bool(
            supplement_page
            and caption_lines >= 2
            and words <= 180
            and line_type_body <= max(4, caption_lines * 2)
        )

        if reference_page:
            page_profile = "references"
        elif label_only_page:
            page_profile = "figure_label_only"
        elif figure_only:
            page_profile = "figure_only"
        elif figure_plate:
            page_profile = "figure_plate"
        elif supplement_page and (figure_heavy or formula_heavy or supplement_caption_page):
            page_profile = "supplement"
        elif title_page:
            page_profile = "title"
        elif formula_heavy:
            page_profile = "formula_heavy"
        else:
            page_profile = "body"

        return {
            "page_profile": page_profile,
            "title_page": title_page,
            "figure_plate_page": figure_plate,
            "figure_heavy_page": figure_heavy,
            "figure_only_page": figure_only,
            "graph_heavy_page": graph_heavy,
            "graph_axis_text_detected": graph_axis_lines > 0,
            "graph_axis_line_count": graph_axis_lines,
            "reference_page": reference_page,
            "reference_line_count": reference_lines,
            "formula_heavy_page": formula_heavy,
            "formula_line_count": formula_lines,
            "formula_candidate_count": formula_candidate_count,
            "math_symbol_count": math_symbol_count,
            "content_formula_blocks": content_formula_blocks,
            "caption_line_count": caption_lines,
            "caption_continuation_lines": int(metadata.get("caption_continuation_lines") or 0),
            "caption_continuation_blocks": int(metadata.get("caption_continuation_blocks") or 0),
            "label_only_line_count": label_only_lines,
            "label_only_page": label_only_page,
            "supplement_hint": has_supplement_hint,
            "arxiv_footer_line_count": line_type_arxiv,
            "page_number_line_count": line_type_page_number,
            "body_line_count": line_type_body,
        }



__all__ = ["PDFQualityMixin"]
