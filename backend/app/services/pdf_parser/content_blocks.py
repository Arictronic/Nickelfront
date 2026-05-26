from __future__ import annotations

import io
import logging
import math
import re
import unicodedata
from collections import Counter
from dataclasses import asdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

from .compat import Document, RecursiveCharacterTextSplitter
from .constants import *
from .models import PdfExtractionError, PdfPageExtraction

logger = logging.getLogger(__name__)

class PDFContentBlockMixin:
    """Content block typing: body, headings, captions, tables, formulas, references, footnotes."""

    def _looks_like_page_number_line(self, text: str) -> bool:
        return bool(_PAGE_NUMBER_RE.match(str(text or "").strip()))

    def _looks_like_affiliation_line(self, text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        return bool(
            "@" in value
            or re.search(r"\b(?:Department|Institute|University|Laboratory|School|Faculty|College|Center|Centre|Corresponding author|E-mail|Email|Affiliation)\b", value, re.IGNORECASE)
        )

    def _classify_visual_line(self, line: dict[str, Any] | str, metadata: dict[str, Any] | None = None) -> str:
        """Classify one visual line into a content type.

        This is intentionally conservative. It does not change the core reading
        order; it only helps post-processing, audit and later RAG chunking to
        distinguish prose from captions/formulas/tables/axis labels/references.
        """
        text = str(line.get("text") if isinstance(line, dict) else line or "").strip()
        if not text:
            return "empty"
        if self._is_arxiv_footer_line(text):
            return "arxiv_footer"
        if self._looks_like_page_number_line(text):
            return "page_number"
        if _WATERMARK_LINE_RE.search(text):
            return "watermark"
        if re.match(r"^\s*(?:abstract|Р°РЅРЅРѕС‚Р°С†РёСЏ)\b", text, re.IGNORECASE):
            return "abstract"
        if _REFERENCE_HEADING_RE.match(text):
            return "reference"
        if self._is_reference_like_line(text):
            return "reference"



        if _CAPTION_RE.match(text) or _CAPTION_START_RE.match(text) or _FIGURE_LABEL_LINE_RE.match(text):
            return "caption"



        if self._is_explicit_table_line(text, metadata) or self._is_contextual_table_row(text, metadata):
            return "table"
        if _SECTION_HEADING_RE.match(text):
            return "heading"
        if self._is_formula_like_line(text):
            return "formula"
        if self._is_graph_axis_or_table_line(text, metadata):
            return "graph_axis"
        if _LABEL_ONLY_LINE_RE.match(text):
            return "figure_label"
        if self._looks_like_affiliation_line(text):
            return "affiliation"
        if self._is_heading_like_line(text):
            return "heading"
        return "body"

    def _line_type_counts(self, lines: list[dict[str, Any]] | list[str], metadata: dict[str, Any] | None = None) -> dict[str, int]:
        counts: dict[str, int] = {}
        for line in lines or []:
            kind = self._classify_visual_line(line, metadata)
            if kind == "empty":
                continue
            counts[kind] = counts.get(kind, 0) + 1
        return counts

    def _looks_ocr_noise_like_text(self, text: str) -> bool:
        value = re.sub(r"\s+", " ", str(text or "").strip())
        if len(value) < 48:
            return False
        alpha = len(re.findall(r"[A-Za-zА-Яа-я]", value))
        digits = len(re.findall(r"\d", value))
        punct = len(re.findall(r"[^A-Za-zА-Яа-я0-9\s]", value))
        upper = len(re.findall(r"[A-ZА-Я]", value))
        alpha_ratio = alpha / max(1, len(value))
        punct_ratio = punct / max(1, len(value))
        upper_ratio = upper / max(1, alpha) if alpha else 0.0
        return bool(
            alpha_ratio < 0.62
            or punct_ratio > 0.14
            or (upper_ratio > 0.72 and digits >= 4)
        )

    def _filter_lines_for_body_text(self, lines: list[dict[str, Any]], opts: dict[str, Any] | None = None, metadata: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Remove service/noise lines from rendered body text.

        Captions and headings are preserved because they are useful for search.
        Graph-axis labels, page numbers, arXiv sidebars/footers and watermark
        stamps are excluded from body and footnotes, but still counted in metadata.
        """
        opts = opts or {}
        kept: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        removed: dict[str, int] = {}
        for line in lines or []:
            kind = self._classify_visual_line(line, metadata)
            counts[kind] = counts.get(kind, 0) + 1
            drop = kind in {"page_number", "watermark"}
            if opts.get("drop_arxiv_footer_from_body", True) and kind == "arxiv_footer":
                drop = True
            if opts.get("drop_graph_axis_from_body", True) and kind == "graph_axis":
                drop = True
            if drop:
                removed[kind] = removed.get(kind, 0) + 1
                continue
            copied = dict(line)
            copied["line_type"] = kind
            kept.append(copied)
        meta = {f"line_type_{k}": v for k, v in counts.items()}
        meta.update({f"removed_{k}_lines": v for k, v in removed.items()})
        meta["non_body_lines_removed"] = sum(removed.values())
        return kept, meta

    def _looks_caption_continuation_line(self, text: str) -> bool:
        """Return True for visual lines that likely continue a figure/table caption."""
        value = (text or "").strip()
        if not value:
            return False
        if self._looks_like_page_number_line(value) or self._is_arxiv_footer_line(value):
            return False
        if _SECTION_HEADING_RE.match(value) or _REFERENCE_HEADING_RE.match(value) or _REFERENCE_STOP_HEADING_RE.match(value):
            return False
        if self._is_explicit_table_line(value) or self._is_contextual_table_row(value):
            return False
        if _CAPTION_START_RE.match(value) or _CAPTION_RE.match(value):
            return True



        word_count = len(re.findall(r"\b[^\W\d_]{2,}\b", value, flags=re.UNICODE))
        if len(value) > 240 or word_count > 34:
            return False
        if re.match(
            r"^(?:\([a-z]\)|[,;:]|and\b|where\b|with\b|for\b|respectively\b|showing\b|illustrating\b|indicating\b|denoting\b|corresponding\s+to\b)",
            value,
            re.IGNORECASE,
        ):
            return True
        if re.search(r"\b(?:respectively|inset|panel|arrow|scale bar|shown|represents|indicates|denotes|adapted from|see Methods|error bars)\b", value, re.IGNORECASE):
            return True
        return False

    def _line_bbox(self, line: dict[str, Any]) -> list[float] | None:
        try:
            x0 = float(line.get("x0"))
            top = float(line.get("top"))
            x1 = float(line.get("x1"))
            bottom = float(line.get("bottom"))
        except Exception:
            return None
        if any(math.isnan(v) or math.isinf(v) for v in (x0, top, x1, bottom)):
            return None
        return [round(x0, 3), round(top, 3), round(x1, 3), round(bottom, 3)]

    def _merge_bboxes(self, bboxes: list[list[float]]) -> list[float] | None:
        if not bboxes:
            return None
        x0 = min(box[0] for box in bboxes)
        y0 = min(box[1] for box in bboxes)
        x1 = max(box[2] for box in bboxes)
        y1 = max(box[3] for box in bboxes)
        return [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)]

    def _block_score_profile(
        self,
        *,
        text: str,
        guessed_type: str,
        metadata: dict[str, Any] | None,
        page_num: int | None = None,
        opts: dict[str, Any] | None = None,
    ) -> tuple[str, float, dict[str, float], list[str]]:
        value = str(text or "").strip()
        meta = metadata or {}
        cfg = opts or {}
        is_reference_page = bool(meta.get("reference_page") or str(meta.get("page_profile") or "").lower() == "references")
        is_formula_page = bool(meta.get("formula_heavy_page") or str(meta.get("page_profile") or "").lower() == "formula_heavy")
        is_figure_page = bool(meta.get("figure_only_page") or meta.get("figure_plate_page") or str(meta.get("page_profile") or "").lower() in {"figure_only", "figure_plate", "figure_label_only", "supplement"})

        scores: dict[str, float] = {
            "body": 0.25,
            "heading": 0.05,
            "caption": 0.05,
            "table": 0.05,
            "formula": 0.05,
            "reference": 0.05,
            "footnote": 0.03,
            "unknown": 0.02,
            "affiliation": 0.03,
            "abstract": 0.02,
        }
        reasons: list[str] = []

        if guessed_type in scores:
            scores[guessed_type] += 0.35
            reasons.append(f"seed_type_{guessed_type}")
        else:
            scores["body"] += 0.08
            reasons.append("seed_type_body_default")

        lines = [line.strip() for line in value.splitlines() if line.strip()]
        line_count = len(lines) or 1
        avg_line_len = len(value) / max(1, line_count)
        word_count = len(re.findall(r"\b[^\W\d_]{2,}\b", value, flags=re.UNICODE))
        sentence_punctuation_density = len(re.findall(r"[.!?;:]", value)) / max(1, len(value))
        operator_density = len(_MATH_SYMBOL_RE.findall(value)) / max(1, len(value))
        enumeration_pattern_density = len(re.findall(r"(?:^|\s)(?:\[\d+\]|\(\d+\)|\d+\.)\s+", value)) / max(1, line_count)
        isolation_gap_hint = 1.0 if (line_count <= 2 and avg_line_len <= 64) else 0.0
        formula_structural_signals = int(operator_density >= 0.04) + int(isolation_gap_hint > 0) + int(sentence_punctuation_density <= 0.012)
        prose_like_sentence = bool(word_count >= 14 and sentence_punctuation_density >= 0.012 and operator_density <= 0.025)
        inline_formula_prose = bool(
            word_count >= 10
            and sentence_punctuation_density >= 0.01
            and operator_density < 0.05
            and line_count <= 3
            and bool(re.search(r"[=±×÷≈≤≥πμσΩθ]", value))
        )
        inline_figure_reference_prose = bool(
            word_count >= 14
            and sentence_punctuation_density >= 0.01
            and bool(
                re.match(
                    r"^\s*(?:fig\.?|figure|table)\s*[s]?\d+[a-z]?(?:\s*\([a-z0-9]+\))?\)?[.:)]?\s+",
                    value,
                    re.IGNORECASE,
                )
            )
            and not bool(re.match(r"^\s*(?:fig(?:ure)?|table)\s*[s]?\d+[a-z]?\s*[:.-]\s*$", value, re.IGNORECASE))
        )
        figure_reference_lead_prose = bool(
            word_count >= 10
            and len(value) >= 70
            and bool(re.match(r"^\s*(?:fig\.?|figure)\s*[s]?\d+[a-z]?\b", value, re.IGNORECASE))
            and not bool(re.match(r"^\s*(?:fig(?:ure)?)\s*[s]?\d+[a-z]?\s*[:.-]\s*$", value, re.IGNORECASE))
        )
        pipe_grid_like = bool(re.match(r"^\s*\|(?:\s*\|){2,}\s*$", value)) or bool(
            re.match(r"^\s*\|(?:\s*[-:]+\s*\|){2,}\s*$", value)
        )
        pipe_separator_noise = bool(re.fullmatch(r"\s*(?:\|\s*){3,}\|?\s*", value))
        markdown_table_block_like = bool(
            len([ln for ln in lines if ln.startswith("|")]) >= 3
            and bool(re.search(r"(?m)^\s*\|(?:\s*[-:]+\s*\|){2,}\s*$", value))
        )
        figure_panel_caption_like = bool(
            re.match(r"^\s*(?:fig\.?|figure)\s*[s]?\d+[a-z]?(?:\s*[:.-]|\s+)", value, re.IGNORECASE)
            and bool(re.search(r"(?:^|\s)\(?[a-d]\)\s*", value, re.IGNORECASE))
        )
        noisy_figure_caption_marker = bool(
            re.match(r"^\s*f\s*i\s*g\s*u\s*r\s*e\s*[s]?\s*\d+[a-z]?\b", value, re.IGNORECASE)
            or re.match(r"^\s*f\s*i\s*g\.?\s*[s]?\s*\d+[a-z]?\b", value, re.IGNORECASE)
        )
        affiliation_like_but_figure_prose = bool(
            is_figure_page
            and word_count >= 12
            and sentence_punctuation_density >= 0.01
            and len(value) >= 90
        )
        author_affiliation_list_like = bool(
            re.match(r"^\s*\d+\s+[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){0,3}", value)
            and bool(re.search(r"\b(?:and|&)\b", value, re.IGNORECASE))
            and bool(re.search(r"\d", value))
            and sentence_punctuation_density < 0.02
        )
        assignment_with_units_prose = bool(
            prose_like_sentence
            and word_count >= 12
            and len(re.findall(r"=", value)) <= 2
            and operator_density < 0.05
            and bool(re.search(r"\b(?:MPa|GPa|Pa|K|°C|wt\.?%|at\.?%|nm|mm|h(?:ours?)?)\b", value, re.IGNORECASE))
        )
        assignment_fragment_prose = bool(
            len(re.findall(r"=", value)) == 1
            and operator_density < 0.06
            and bool(re.search(r"\bbetween\b", value, re.IGNORECASE))
            and bool(re.search(r"\b(?:cm|mm|nm|um|μm|MPa|GPa|K|°C)\b", value, re.IGNORECASE))
            and word_count >= 6
        )
        reference_fragment_in_reference_page = bool(
            is_reference_page
            and line_count <= 5
            and bool(
                re.search(
                    r"(?:^\s*\(?\d{1,3}\)?\.?\s+|;\s*[A-Z][A-Za-z'’.-]+|"
                    r"\b(?:J\.|Phys\.|Chem\.|Mater\.|Sci\.|Nature|Science|DOI|arXiv)\b|"
                    r"\b(?:19|20)\d{2}\b)",
                    value,
                    re.IGNORECASE,
                )
            )
        )
        short_reference_continuation_fragment = bool(
            is_reference_page
            and word_count <= 14
            and line_count <= 3
            and bool(re.search(r"\b(?:et\s+al\.|doi|pp\.?|vol\.?|No\.|In\s+Russ\.)\b", value, re.IGNORECASE))
        )
        reference_citation_id_fragment = bool(
            is_reference_page
            and line_count <= 3
            and bool(
                re.search(
                    r"(?:\b\d{4,6}-\d{4}(?:-[0-9A-Za-z-]+)?\b|"
                    r"\bS\d{8,}\b|"
                    r"https?://|doi:\s*10\.)",
                    value,
                    re.IGNORECASE,
                )
            )
        )
        reference_year_pages_fragment = bool(
            is_reference_page
            and line_count <= 4
            and word_count <= 18
            and bool(re.search(r"\b(?:19|20)\d{2}\b", value))
            and bool(
                re.search(
                    r"(?:\bpp?\.\s*\d|\bP\.\s*\d|"
                    r"\bС\.\s*\d|\bNo\.?\s*\d|"
                    r"\bVol\.?\s*\d|\bТ\.\s*\d|"
                    r"\b\d+\s*(?:p\.|pages|с\.)\b)",
                    value,
                    re.IGNORECASE,
                )
            )
        )
        repeated_isolated_glyph_line = bool(
            line_count <= 2
            and bool(re.fullmatch(r"\s*(?:[Il\|]\s+){3,}[Il\|]\s*", value))
        )
        alpha_word_count = len(re.findall(r"\b[^\W\d_]{1,}\b", value, flags=re.UNICODE))
        token_like_count = len(re.findall(r"\b\S+\b", value))
        alpha_token_ratio = (alpha_word_count / max(1, token_like_count)) if token_like_count else 0.0
        reference_structural_signals = int(enumeration_pattern_density >= 0.6) + int(bool(re.search(r"\b(?:doi|https?://)\b", value, re.IGNORECASE))) + int(line_count >= 3)
        ocr_noise_like = self._looks_ocr_noise_like_text(value)
        heading_max_words = int(cfg.get("typing_heading_max_words") or 12)
        heading_max_sentence_punct_density = float(cfg.get("typing_heading_max_sentence_punct_density") or 0.015)
        heading_max_operator_density = float(cfg.get("typing_heading_max_operator_density") or 0.03)
        formula_prose_word_count = int(cfg.get("typing_formula_prose_word_count") or 26)
        formula_low_operator_density = float(cfg.get("typing_formula_low_operator_density") or 0.045)
        low_conf_threshold = float(cfg.get("typing_low_confidence_threshold") or 0.52)
        warning_conf_threshold = float(cfg.get("typing_warning_confidence_threshold") or 0.62)
        conflict_margin_unknown = float(cfg.get("typing_conflict_margin_unknown") or 0.075)

        if value and word_count >= 10:
            scores["body"] += 0.16
            reasons.append("body_word_density")
        heading_shape_ok = bool(
            word_count <= heading_max_words
            and sentence_punctuation_density <= heading_max_sentence_punct_density
            and operator_density <= heading_max_operator_density
        )
        spaced_caps_heading_like = bool(
            line_count <= 2
            and 8 <= len(value) <= 64
            and bool(re.fullmatch(r"(?:[A-ZА-Я]\s+){3,}[A-ZА-Я]", value.strip()))
        )
        fragmented_caps_heading_like = bool(
            line_count <= 2
            and 10 <= len(value) <= 120
            and (
                len(re.findall(r"\b[A-ZА-Я]\b", value)) >= 4
                or len(re.findall(r"\b[A-ZА-Я]{2,}\b", value)) >= 2
            )
            and not bool(re.search(r"[a-zа-я]", value))
            and sentence_punctuation_density < 0.02
        )
        compact_caps_token = re.sub(r"[^A-ZА-Я]", "", value.upper())
        compact_caps_heading_label = bool(
            len(compact_caps_token) >= 5
            and len(compact_caps_token) <= 24
            and compact_caps_token
            in {
                "NOTICE",
                "ABSTRACT",
                "ARTICLEINFO",
                "TECHNICALNOTE",
                "SUMMARY",
                "INTRODUCTION",
            }
        )
        allcaps_title_heading_like = bool(
            line_count <= 3
            and 18 <= len(value) <= 180
            and value.strip().endswith(":")
            and len(re.findall(r"\b[A-ZА-Я]{3,}\b", value)) >= 3
            and sentence_punctuation_density <= 0.02
            and operator_density < 0.03
        )
        if self._is_heading_like_line(value):
            if heading_shape_ok:
                scores["heading"] += 0.30
                reasons.append("heading_like_line")
            else:
                scores["heading"] += 0.08
                scores["body"] += 0.05
                reasons.append("heading_like_but_prose_or_symbolic")
        if spaced_caps_heading_like:
            scores["heading"] += 0.24
            scores["body"] -= 0.05
            reasons.append("spaced_caps_heading_pattern")
        if fragmented_caps_heading_like:
            scores["heading"] += 0.20
            scores["body"] -= 0.04
            reasons.append("fragmented_caps_heading_pattern")
        if compact_caps_heading_label:
            scores["heading"] += 0.26
            scores["body"] -= 0.06
            reasons.append("compact_caps_heading_label")
        if allcaps_title_heading_like:
            scores["heading"] += 0.22
            scores["body"] -= 0.05
            reasons.append("allcaps_title_heading_pattern")
        heading_seed_math_like = bool(
            guessed_type == "heading"
            and (
                formula_structural_signals >= 2
                or operator_density >= 0.06
                or alpha_token_ratio < 0.45
                or bool(re.search(r"[=±×÷≈≤≥∑∫√πμσΩθ]", value))
            )
            and not prose_like_sentence
        )
        if heading_seed_math_like:
            scores["heading"] -= 0.20
            scores["formula"] += 0.12
            scores["unknown"] += 0.05
            reasons.append("heading_seed_suppressed_math_like")
        heading_formula_context_noise = bool(
            is_formula_page
            and line_count <= 2
            and (
                operator_density >= 0.045
                or alpha_token_ratio < 0.5
                or bool(re.search(r"^\s*(?:\d+(?:\.\d+)*|[IVXLC]+)\s*$", value.strip(), re.IGNORECASE))
            )
            and not prose_like_sentence
        )
        if heading_formula_context_noise:
            scores["heading"] -= 0.18
            scores["formula"] += 0.08
            scores["unknown"] += 0.04
            reasons.append("heading_suppressed_formula_context_noise")
        if (_CAPTION_RE.match(value) or _CAPTION_START_RE.match(value) or _FIGURE_LABEL_LINE_RE.match(value) or noisy_figure_caption_marker) and not ocr_noise_like:
            scores["caption"] += 0.35
            reasons.append("caption_marker" if not noisy_figure_caption_marker else "caption_marker_noisy_figure_token")
        if inline_figure_reference_prose:
            scores["caption"] -= 0.18
            scores["body"] += 0.10
            reasons.append("inline_figure_reference_prose_body_preferred")
        if figure_reference_lead_prose:
            scores["caption"] -= 0.16
            scores["body"] += 0.11
            reasons.append("figure_reference_lead_prose_body_preferred")
        caption_marker_prose = bool(("caption_marker" in reasons) and prose_like_sentence and word_count >= 16)
        if caption_marker_prose:
            scores["caption"] -= 0.20
            scores["body"] += 0.14
            reasons.append("caption_marker_prose_body_preferred")
        caption_overrun_prose = bool(
            ("caption_marker" in reasons)
            and prose_like_sentence
            and (word_count >= 22 or len(value) >= 140)
        )
        if caption_overrun_prose:
            scores["caption"] -= 0.22
            scores["body"] += 0.16
            reasons.append("caption_overrun_prose_body_preferred")
        if self._looks_caption_continuation_line(value) and is_figure_page:
            scores["caption"] += 0.18
            reasons.append("caption_continuation_on_figure_page")
        if self._is_reference_like_line(value):
            if not ocr_noise_like:
                scores["reference"] += 0.40
                reasons.append("reference_line_pattern")
            else:
                scores["reference"] += 0.08
                reasons.append("reference_pattern_noise_suppressed")
        if is_reference_page:
            scores["reference"] += 0.30
            scores["body"] -= 0.12
            reasons.append("reference_page_context")
        if reference_structural_signals >= 2:
            scores["reference"] += 0.15
            reasons.append("reference_pattern_consensus")
        if self._looks_math_heavy_text(value) or self._is_formula_like_line(value):
            if formula_structural_signals >= 2 or not prose_like_sentence:
                scores["formula"] += 0.40
                scores["body"] -= 0.08
                reasons.append("formula_like_structure")
            else:
                scores["formula"] += 0.12
                scores["body"] += 0.04
                reasons.append("formula_like_but_prose_penalized")
        if formula_structural_signals >= 2 and (self._looks_math_heavy_text(value) or self._is_formula_like_line(value)):
            scores["formula"] += 0.18
            reasons.append("formula_structural_consensus")
        if prose_like_sentence:
            scores["body"] += 0.12
            scores["formula"] -= 0.10
            reasons.append("prose_sentence_penalty_formula")
        if inline_formula_prose:
            scores["body"] += 0.08
            scores["formula"] -= 0.07
            reasons.append("inline_formula_prose_body_preferred")
        if word_count >= formula_prose_word_count and formula_structural_signals < 2 and operator_density < formula_low_operator_density:
            scores["body"] += 0.06
            scores["formula"] -= 0.08
            reasons.append("long_prose_penalty_formula")
        if ocr_noise_like:
            scores["unknown"] += 0.16
            scores["heading"] -= 0.08
            scores["caption"] -= 0.08
            scores["formula"] -= 0.06
            scores["reference"] -= 0.05
            reasons.append("ocr_noise_like_block")
        if repeated_isolated_glyph_line:
            scores["unknown"] += 0.24
            scores["body"] -= 0.06
            scores["heading"] -= 0.06
            scores["caption"] -= 0.05
            scores["formula"] -= 0.05
            reasons.append("isolated_glyph_line_noise")
        if is_formula_page:
            if formula_structural_signals >= 2 or not prose_like_sentence:
                scores["formula"] += 0.16
                scores["body"] -= 0.06
                reasons.append("formula_page_context")
            else:
                scores["formula"] += 0.04
                scores["body"] += 0.03
                reasons.append("formula_page_context_soft")
        if self._is_explicit_table_line(value, meta) or self._is_contextual_table_row(value, meta):
            scores["table"] += 0.30
            reasons.append("table_like_structure")
        if pipe_grid_like:
            scores["table"] += 0.26
            scores["body"] -= 0.10
            scores["unknown"] += 0.04
            reasons.append("pipe_grid_table_like")
        if pipe_separator_noise:
            scores["unknown"] += 0.24
            scores["table"] -= 0.10
            scores["body"] -= 0.08
            reasons.append("pipe_separator_noise_line")
        if markdown_table_block_like:
            scores["table"] += 0.34
            scores["body"] -= 0.12
            reasons.append("markdown_table_block_like")
        if self._is_likely_footnote_line(
            {"text": value, "top": 10_000.0, "font_size": 8.0},
            page_height=12_000.0,
            median_font=10.0,
        ):
            scores["footnote"] += 0.20
            reasons.append("footnote_signal")
        if self._looks_like_affiliation_line(value) and not figure_panel_caption_like and not affiliation_like_but_figure_prose:
            scores["affiliation"] += 0.24
            reasons.append("affiliation_signal")
        elif figure_panel_caption_like:
            reasons.append("affiliation_signal_suppressed_figure_caption")
        elif affiliation_like_but_figure_prose:
            scores["body"] += 0.06
            scores["affiliation"] -= 0.05
            reasons.append("affiliation_signal_suppressed_figure_prose")
        if author_affiliation_list_like:
            scores["affiliation"] += 0.18
            scores["body"] += 0.06
            scores["heading"] -= 0.08
            reasons.append("author_affiliation_list_preferred")
        if assignment_with_units_prose:
            scores["body"] += 0.10
            scores["formula"] -= 0.09
            reasons.append("assignment_units_prose_body_preferred")
        if assignment_fragment_prose:
            scores["body"] += 0.08
            scores["formula"] -= 0.07
            reasons.append("assignment_fragment_prose_body_preferred")
        if reference_fragment_in_reference_page:
            scores["reference"] += 0.14
            scores["body"] -= 0.04
            reasons.append("reference_fragment_context_boost")
        if short_reference_continuation_fragment:
            scores["reference"] += 0.12
            scores["body"] -= 0.03
            reasons.append("reference_short_continuation_boost")
        if reference_citation_id_fragment:
            scores["reference"] += 0.10
            scores["body"] -= 0.03
            reasons.append("reference_citation_id_boost")
        if reference_year_pages_fragment:
            scores["reference"] += 0.11
            scores["body"] -= 0.03
            reasons.append("reference_year_pages_boost")
        if re.match(r"^\s*(?:abstract|аннотация)\b", value, re.IGNORECASE):
            scores["abstract"] += 0.20
            reasons.append("abstract_heading")
        if not value or len(value) < 6:
            scores["unknown"] += 0.18
            reasons.append("too_short_or_empty")
        if guessed_type == "caption" and (word_count > 36 or len(value) > 320):
            scores["body"] += 0.10
            scores["caption"] -= 0.08
            reasons.append("caption_overrun_prevented")

        winner = max(scores, key=scores.get)
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top = ordered[0][1] if ordered else 0.0
        second = ordered[1][1] if len(ordered) > 1 else 0.0
        second_type = ordered[1][0] if len(ordered) > 1 else "unknown"
        margin = max(0.0, top - second)
        confidence = max(0.0, min(1.0, 0.45 + margin))
        conflict_pair = {winner, second_type}
        caption_continuation_signal = bool(
            is_figure_page
            and (
                "caption_continuation_on_figure_page" in reasons
                or ("caption_marker" in reasons and guessed_type == "caption")
            )
        )
        ambiguous_conflict = bool(
            margin < conflict_margin_unknown
            and conflict_pair in (
                {"body", "formula"},
                {"body", "heading"},
                {"body", "reference"},
                {"body", "caption"},
            )
        )
        if caption_continuation_signal and conflict_pair == {"body", "caption"} and margin < max(conflict_margin_unknown, 0.12):
            winner = "caption"
            confidence = max(confidence, low_conf_threshold + 0.01)
            reasons.append("figure_caption_continuation_preferred")
        if "caption_marker_prose_body_preferred" in reasons and conflict_pair == {"body", "caption"} and margin < max(conflict_margin_unknown, 0.12):
            winner = "body"
            confidence = max(confidence, low_conf_threshold + 0.01)
            reasons.append("caption_marker_prose_conflict_resolved_to_body")
        preserve_body_for_caption_prose = bool(winner == "body" and "caption_marker_prose_conflict_resolved_to_body" in reasons)
        if ambiguous_conflict and winner != "caption" and not preserve_body_for_caption_prose:
            winner = "unknown"
            reasons.append("conflicting_scores_unknown_fallback")
            scores["unknown"] = max(scores["unknown"], top)
            confidence = min(confidence, warning_conf_threshold - 0.01)
        if confidence < low_conf_threshold:
            winner = "unknown"
            reasons.append("low_margin_unknown_fallback")
            scores["unknown"] = max(scores["unknown"], top)
        elif confidence < warning_conf_threshold and winner != "unknown":
            reasons.append("low_margin_type_assignment")
        return winner, round(confidence, 3), {k: round(v, 4) for k, v in scores.items()}, reasons[:8]
    def _content_blocks_from_lines(
        self,
        lines: list[dict[str, Any]],
        *,
        page_num: int,
        metadata: dict[str, Any] | None = None,
        max_blocks: int = 80,
        source: str = "visual_lines",
        opts: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Build lightweight content blocks for debug/audit/RAG preparation.

        We keep this in metadata only for now to avoid schema migrations. Later
        paper_content_part_service can persist these blocks as separate
        content_type rows. v24 adds caption continuation so figure/table plates
        do not split the first caption line from its explanatory continuation.
        """
        blocks: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        current_type: str | None = None
        current_lines: list[str] = []
        current_line_dicts: list[dict[str, Any]] = []
        caption_continuation_lines = 0
        caption_continuation_blocks = 0
        in_caption = False

        def flush() -> None:
            nonlocal current_type, current_lines, current_line_dicts, in_caption, caption_continuation_blocks
            if current_type and current_lines:
                text = self._join_paragraph_lines(current_lines) if current_type in {"body", "caption", "affiliation", "abstract", "footnote"} else "\n".join(current_lines)
                if text.strip():
                    counts[current_type] = counts.get(current_type, 0) + 1
                    if current_type == "caption" and len(current_lines) > 1:
                        caption_continuation_blocks += 1
                    if len(blocks) < max_blocks:
                        bboxes = []
                        for raw_line in current_line_dicts:
                            bbox = self._line_bbox(raw_line)
                            if bbox:
                                bboxes.append(bbox)
                        bbox = self._merge_bboxes(bboxes)
                        block_type, confidence, scores, reasons = self._block_score_profile(
                            text=text.strip(),
                            guessed_type=current_type,
                            metadata=metadata,
                            page_num=page_num,
                            opts=opts,
                        )
                        block_payload = {
                            "type": block_type,
                            "block_type": block_type,
                            "page": page_num,
                            "order": len(blocks) + 1,
                            "bbox": bbox,
                            "text": text.strip(),
                            "text_chars": len(text.strip()),
                            "confidence": confidence,
                            "quality": confidence,
                            "scores": scores,
                            "reasons": reasons,
                            "source": source,
                        }
                        blocks.append(block_payload)
            current_type = None
            current_lines = []
            current_line_dicts = []
            in_caption = False

        for line in lines or []:
            if isinstance(line, dict) and line.get("paragraph_break"):
                flush()
                continue
            text = str(line.get("text") or "").strip()
            if not text:
                continue
            kind = self._classify_visual_line(line, metadata)
            if kind in {"empty", "page_number", "arxiv_footer", "watermark", "graph_axis"}:
                counts[kind] = counts.get(kind, 0) + 1
                continue

            block_type = kind
            if block_type in {"figure_label"}:
                block_type = "caption"
            if current_type == "table" and (_MARKDOWN_TABLE_ROW_RE.match(text) or _TABLE_SEPARATOR_ROW_RE.match(text)):
                block_type = "table"





            if current_type == "caption" and block_type == "body":
                current_caption = " ".join(current_lines).strip()
                caption_is_table = bool(re.match(r"(?i)^\s*table\b", current_caption))
                continuation_allowed = self._looks_caption_continuation_line(text)



                if caption_is_table and (self._is_contextual_table_row(text, metadata) or len(text) > 180):
                    continuation_allowed = False
                if continuation_allowed:
                    block_type = "caption"
                    caption_continuation_lines += 1

            if block_type == "caption":
                in_caption = True
            elif in_caption and block_type not in {"caption"}:
                in_caption = False

            if block_type != current_type:
                flush()
                current_type = block_type
                current_lines = [text]
                current_line_dicts = [dict(line)]
            else:
                current_lines.append(text)
                current_line_dicts.append(dict(line))
        flush()
        meta = {f"content_block_{k}_count": v for k, v in counts.items()}
        meta["content_block_count"] = len(blocks)
        meta["caption_continuation_lines"] = caption_continuation_lines
        meta["caption_continuation_blocks"] = caption_continuation_blocks
        return blocks, meta

    def _normalize_content_block_text(self, text: str, opts: dict[str, Any] | None = None) -> str:
        """Apply the same safe PDF text-layer cleanup to content block text.

        v25 persisted content_blocks, but those blocks were created from visual
        lines before final text cleanup and document-level page profiling. That
        allowed stale PUA/CID glyphs or references typed as body to reach RAG.
        This method keeps block text aligned with page.text cleanup.
        """
        value = self._clean_page_text(str(text or ""), opts or {})
        value = self._remove_arxiv_footer_text(value)
        value = self._stitch_math_micro_lines(value)
        return self._normalize_paragraph_breaks(value)

    def _normalize_structural_block_text(self, text: str, opts: dict[str, Any] | None = None) -> str:
        """Normalize text while preserving table column spacing.

        Generic body cleanup collapses repeated spaces, which is correct for prose
        but destructive for space-aligned tables. Use this before table/formula/
        caption splitting; non-table segments are still normalized again later.
        """
        opts = opts or {}
        value = unicodedata.normalize("NFKC", str(text or ""))
        value = value.replace("\r\n", "\n").replace("\r", "\n")
        value = re.sub(r"[ 	]+$", "", value, flags=re.MULTILINE)
        if opts.get("merge_hyphenated_words", True):
            value = self._merge_hyphenated_linebreaks(value)
        if opts.get("normalize_math", True):
            value = self._normalize_math_duplicates(value)
        value = self._remove_arxiv_footer_text(value)
        value = self._stitch_math_micro_lines(value)
        return self._normalize_paragraph_breaks(value)

    def _looks_math_heavy_text(self, text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        formula_markers = len(re.findall(r"\[Formula candidate\]", value, flags=re.IGNORECASE))
        math_hits = len(_MATH_SYMBOL_RE.findall(value))
        pua_hits = len(_PUA_GLYPH_RE.findall(value))
        cid_hits = len(_CID_TOKEN_RE.findall(value))
        words = re.findall(r"\b[^\W\d_]{3,}\b", value, flags=re.UNICODE)
        lexical_ratio = self._lexical_word_ratio(value)
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        prose_lines = sum(1 for line in lines if re.search(r"\b(the|and|or|with|from|where|which|that|this|these|those|therefore|because|respectively|prepared|using|films|substrate|shown|observed)\b", line, re.IGNORECASE))
        equation_numbered = sum(
            1
            for line in lines
            if re.search(r"\([A-Za-z]?\d+(?:\.\d+)?\)\s*$", line)
            and len(_MATH_SYMBOL_RE.findall(line)) >= 1
            and not re.search(r"\b(the|and|or|with|from|where|which|that|this|these|those|therefore|because|respectively|prepared|using|films|substrate|shown|observed)\b", line, re.IGNORECASE)
        )
        operator_dense_lines = sum(1 for line in lines if len(_MATH_SYMBOL_RE.findall(line)) >= 2 and self._lexical_word_ratio(line) < 0.75)
        return bool(
            formula_markers > 0
            or pua_hits > 0
            or cid_hits > 0
            or equation_numbered >= 1
            or operator_dense_lines >= 2
            or (math_hits >= 6 and lexical_ratio < 0.70)
            or (math_hits >= 4 and len(words) < 14 and prose_lines == 0)
            or (
                re.search(r"[в€†О”в€‚в€‘в€«в€љО©О·ОѕО±ОІОіПѓОјПЃПЂ]|\b(?:cosh|sinh|tanh|exp|log)\b", value, re.IGNORECASE)
                and re.search(r"[=/В±в€’-]|\b(?:min|max|norm|eff|sat)\b", value, re.IGNORECASE)
                and (lexical_ratio < 0.96 or len(words) <= 10)
            )
        )

    def _split_lines_by_strong_block_type(self, text: str, default_type: str, metadata: dict[str, Any] | None = None) -> list[tuple[str, str]]:
        """Split multi-line text when standalone lines have strong non-body types.

        Inline math remains inside body text, but visual lines that independently
        look like formulas, references, captions or validated table rows get their
        own block type before downstream projections/embeddings see them.
        """
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        if len(lines) <= 1:
            return []
        meta = metadata or {}
        grouped: list[tuple[str, list[str]]] = []

        for line in lines:
            kind = self._classify_visual_line(line, meta)
            if kind == "figure_label":
                kind = "caption"
            if kind == "table" and not self._is_valid_table_block(line, meta):
                accepted, reason, _confidence, _source = self._table_block_validation(line, meta)
                kind = "table" if accepted else self._fallback_type_for_rejected_table(line, reason, meta)
            if kind not in {"caption", "formula", "table", "reference", "heading", "abstract", "footnote"}:
                kind = default_type
            if grouped and grouped[-1][0] == kind:
                grouped[-1][1].append(line)
            else:
                grouped.append((kind, [line]))

        if len(grouped) <= 1 and grouped[0][0] == default_type:
            return []
        return [
            (kind, self._join_paragraph_lines(items) if kind in {"body", "caption", "affiliation", "abstract", "footnote"} else "\n".join(items))
            for kind, items in grouped
            if items
        ]

    def _split_mixed_content_block(self, text: str, block_type: str, metadata: dict[str, Any] | None = None) -> list[tuple[str, str]]:
        """Split one coarse content block into final typed sub-blocks.

        v27 still allowed mixed blocks such as ``body ... FIG. 4 ... formula``.
        For RAG persistence this is dangerous because a single body block can
        contain captions, formulas and graph labels. This splitter is deliberately
        conservative: it only splits on strong caption/table markers and blank-line
        paragraph boundaries, then lets the normal classifiers retype each piece.
        """
        value = str(text or "").strip()
        if not value:
            return []
        meta = metadata or {}
        initial_type = (block_type or "body").strip().lower().replace("-", "_")
        if initial_type == "figure_label":
            initial_type = "caption"



        paragraphs = [part.strip() for part in re.split(r"\n{2,}", value) if part.strip()]
        if not paragraphs:
            paragraphs = [value]

        pieces: list[tuple[str, str]] = []
        for paragraph in paragraphs:
            line_level_pieces = self._split_lines_by_strong_block_type(paragraph, initial_type, meta)
            if line_level_pieces:
                pieces.extend(line_level_pieces)
                continue
            if (self._is_explicit_table_line(paragraph, meta) or self._is_contextual_table_row(paragraph, meta)) and self._is_valid_table_block(paragraph, meta):
                pieces.append(("table", paragraph))
                continue
            last = 0
            matches = list(_INLINE_CAPTION_MARK_RE.finditer(paragraph))
            if not matches:
                pieces.append((initial_type, paragraph))
                continue
            for index, match in enumerate(matches):
                before = paragraph[last:match.start()].strip()
                if before:
                    pieces.append((initial_type, before))
                next_start = matches[index + 1].start() if index + 1 < len(matches) else len(paragraph)
                caption_text = paragraph[match.start():next_start].strip()
                if caption_text:
                    pieces.append(("caption", caption_text))
                last = next_start
            tail = paragraph[last:].strip()
            if tail:
                pieces.append((initial_type, tail))

        normalized: list[tuple[str, str]] = []
        for guessed_type, piece in pieces:
            text_piece = piece.strip()
            if not text_piece:
                continue
            kind = self._classify_visual_line(text_piece, meta)
            final_type = guessed_type
            if kind in {"heading", "abstract", "caption", "formula", "table", "reference", "graph_axis", "page_number", "arxiv_footer", "watermark", "affiliation"}:
                final_type = kind
            if final_type == "table" and not self._is_valid_table_block(text_piece, meta):
                accepted, reason, _confidence, _source = self._table_block_validation(text_piece, meta)
                if not accepted:
                    final_type = self._fallback_type_for_rejected_table(text_piece, reason, meta)
            elif guessed_type == "body" and self._looks_math_heavy_text(text_piece):



                final_type = "formula"
            elif guessed_type == "body" and self._looks_caption_continuation_line(text_piece) and meta.get("page_profile") in {"figure_plate", "figure_only", "figure_label_only", "supplement"}:
                final_type = "caption"
            if final_type == "figure_label":
                final_type = "caption"
            normalized.append((final_type, text_piece))
        return normalized

    def _final_content_block_count_meta(self, blocks: list[dict[str, Any]], *, metadata: dict[str, Any] | None = None) -> dict[str, int]:
        """Return counters computed only from final persisted content_blocks."""
        meta = metadata or {}
        counts = {f"content_block_{kind}_count": 0 for kind in _CONTENT_BLOCK_TYPES}
        pua_after = cid_after = latexit_after = 0
        for block in blocks or []:
            if not isinstance(block, dict):
                continue
            kind = str(block.get("type") or "body").strip().lower().replace("-", "_")
            counts[f"content_block_{kind}_count"] = counts.get(f"content_block_{kind}_count", 0) + 1
            text = str(block.get("text") or "")
            pua_after += len(_PUA_GLYPH_RE.findall(text))
            cid_after += len(_CID_TOKEN_RE.findall(text))
            latexit_after += len(_LATEXIT_TAG_RE.findall(text))
        counts["content_block_count"] = len([b for b in blocks or [] if isinstance(b, dict)])
        counts["content_blocks_pua_after_cleanup"] = pua_after
        counts["content_blocks_cid_after_cleanup"] = cid_after
        counts["content_blocks_latexit_after_cleanup"] = latexit_after
        is_reference_page = bool(meta.get("reference_page") or str(meta.get("page_profile") or "").lower() == "references")
        is_formula_heavy = bool(meta.get("formula_heavy_page") or str(meta.get("page_profile") or "").lower() == "formula_heavy")
        body_count = counts.get("content_block_body_count", 0)
        formula_count = counts.get("content_block_formula_count", 0)
        reference_count = counts.get("content_block_reference_count", 0)
        counts["body_blocks_on_reference_pages"] = body_count if is_reference_page else 0
        counts["body_blocks_on_formula_heavy_pages"] = body_count if is_formula_heavy else 0
        counts["reference_pages_without_reference_blocks"] = 1 if is_reference_page and reference_count == 0 else 0
        counts["formula_heavy_pages_without_formula_blocks"] = 1 if is_formula_heavy and formula_count == 0 else 0
        return counts

    def _retype_content_blocks(
        self,
        blocks: list[dict[str, Any]],
        *,
        metadata: dict[str, Any] | None = None,
        opts: dict[str, Any] | None = None,
        page_num: int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Normalize, split and retype content blocks using final page profile.

        Guardrails between extraction and RAG persistence:
        - reference pages cannot save references as body;
        - formula-heavy pages keep math as formula, not body;
        - body blocks are split on inline Fig./Figure/Table markers;
        - counters are recomputed from the final block list only.
        """
        meta = metadata or {}
        profile = str(meta.get("page_profile") or "").lower()
        is_reference_page = bool(meta.get("reference_page") or profile == "references")
        is_formula_heavy = bool(meta.get("formula_heavy_page") or profile == "formula_heavy")
        is_figure_page = bool(meta.get("figure_plate_page") or meta.get("figure_only_page") or profile in {"figure_plate", "figure_only", "figure_label_only", "supplement"})

        normalized: list[dict[str, Any]] = []
        retyped_ref = 0
        retyped_formula = 0
        retyped_caption = 0
        split_mixed_blocks = 0
        dropped_noise = 0
        misclassification_risk_blocks = 0
        unknown_recovered_as_strong_type = 0
        validated_tables = 0
        rejected_tables = 0
        table_reject_reasons: dict[str, int] = {}
        table_sources: dict[str, int] = {}
        weak_table_candidates: list[str] = []

        for raw in self._coalesce_adjacent_table_blocks(blocks or [], meta, page_num=page_num):
            if not isinstance(raw, dict):
                continue
            raw_text = str(raw.get("text") or "")
            raw_type = str(raw.get("type") or "body").strip().lower().replace("-", "_")
            text = self._normalize_structural_block_text(raw_text, opts)
            if not text:
                continue
            segments = [("table", text)] if raw_type == "table" else self._split_mixed_content_block(text, raw_type, meta)
            if len(segments) > 1:
                split_mixed_blocks += 1
            if not segments:
                segments = [(raw_type, text)]
            for segment_type, segment_text in segments:
                block_type = (segment_type or "body").strip().lower().replace("-", "_")
                if block_type == "table" or raw_type == "table":
                    segment_text = self._normalize_structural_block_text(segment_text, opts)
                else:
                    segment_text = self._normalize_content_block_text(segment_text, opts)
                if not segment_text:
                    continue
                if block_type in {"figure_label"}:
                    block_type = "caption"

                original_block_type = block_type
                if block_type == "caption" and not (
                    _CAPTION_RE.match(segment_text)
                    or _CAPTION_START_RE.match(segment_text)
                    or self._looks_caption_continuation_line(segment_text)
                ):
                    block_type = "body"





                if is_reference_page and block_type in {"body", "reference", "heading", "affiliation", "caption"}:
                    if self._should_force_reference_block(segment_text, original_block_type, meta):
                        block_type = "reference"
                        if original_block_type != "reference":
                            retyped_ref += 1
                    elif original_block_type == "reference":
                        block_type = "body"
                if is_reference_page and block_type == "caption" and self._is_reference_like_line(segment_text):
                    block_type = "reference"
                    if original_block_type != "reference":
                        retyped_ref += 1
                if block_type in {"body", "caption"} and self._looks_math_heavy_text(segment_text) and (
                    is_formula_heavy
                    or int(meta.get("formula_line_count") or 0) >= 2
                    or self._classify_visual_line(segment_text, meta) == "formula"
                ):
                    block_type = "formula"
                    if original_block_type != "formula":
                        retyped_formula += 1
                elif is_figure_page and block_type == "body" and (
                    _INLINE_CAPTION_MARK_RE.search(segment_text)
                    or (len(segment_text) <= 320 and self._looks_caption_continuation_line(segment_text))
                ):
                    block_type = "caption"
                    retyped_caption += 1

                table_meta: dict[str, Any] = {}
                if (
                    (block_type == "table" or raw_type == "table" or self._looks_like_semantic_table_text(segment_text, meta))
                    and len(segment_text.strip()) > 20
                    and not self._looks_reference_page_text(segment_text)
                    and not self._looks_like_plot_artifact_text(segment_text, meta)
                ):
                    weak_table_candidates.append(segment_text)
                if block_type == "table":
                    accepted, reason, confidence, source = self._table_block_validation(segment_text, meta)
                    if accepted:
                        validated_tables += 1
                        table_sources[source] = table_sources.get(source, 0) + 1
                        table_meta.update(
                            {
                                "table_validated": True,
                                "table_validation_reason": reason,
                                "table_confidence": round(confidence, 3),
                                "table_source": source,
                            }
                        )
                    else:
                        rejected_tables += 1
                        table_reject_reasons[reason] = table_reject_reasons.get(reason, 0) + 1
                        fallback_type = self._fallback_type_for_rejected_table(segment_text, reason, meta)
                        table_meta.update(
                            {
                                "table_validated": False,
                                "table_rejected_reason": reason,
                                "table_rejected_fallback_type": fallback_type,
                            }
                        )
                        block_type = fallback_type


                if block_type in {"page_number", "arxiv_footer", "watermark", "graph_axis", "empty", "noise"}:
                    dropped_noise += 1
                    continue
                if block_type not in {"body", "caption", "formula", "table", "reference", "footnote", "affiliation", "heading", "abstract", "unknown"}:
                    block_type = "body"

                copied = {k: v for k, v in raw.items() if k != "text"}
                copied.update(table_meta)
                final_type, final_confidence, final_scores, final_reasons = self._block_score_profile(
                    text=segment_text,
                    guessed_type=block_type,
                    metadata=meta,
                    page_num=page_num,
                    opts=opts,
                )
                ordered_scores = sorted((float(v) for v in final_scores.values()), reverse=True)
                top_score = ordered_scores[0] if ordered_scores else 0.0
                second_score = ordered_scores[1] if len(ordered_scores) > 1 else 0.0
                score_margin = round(max(0.0, top_score - second_score), 4)
                if score_margin < 0.12:
                    misclassification_risk_blocks += 1
                    if "low_margin_type_assignment" not in final_reasons:
                        final_reasons = [*final_reasons, "low_margin_type_assignment"][:8]
                if final_type == "unknown" and block_type in {"reference", "formula", "caption", "table"}:
                    unknown_recovered_as_strong_type += 1
                if block_type in {"heading", "abstract"} and final_type in {"body", "unknown"}:
                    final_type = block_type
                    final_confidence = max(final_confidence, 0.72)
                    final_scores[final_type] = max(final_scores.get(final_type, 0.0), final_confidence)
                    final_reasons = [*final_reasons, f"preserve_{final_type}_seed"][:8]
                copied.update({
                    "type": final_type,
                    "block_type": final_type,
                    "page": int(copied.get("page") or page_num or meta.get("page") or 0) or None,
                    "order": len(normalized) + 1,
                    "bbox": copied.get("bbox"),
                    "text": segment_text,
                    "text_chars": len(segment_text),
                    "confidence": final_confidence,
                    "quality": final_confidence,
                    "score_margin": score_margin,
                    "scores": final_scores,
                    "reasons": final_reasons,
                    "source": copied.get("source") or "raw_content_blocks_retyped",
                })
                normalized.append(copied)

        parser_table_detected = int(meta.get("table_count") or meta.get("tables_detected") or 0) > 0 or int(meta.get("table_cells") or 0) > 0
        if parser_table_detected and not any(block.get("type") == "table" for block in normalized):
            fallback_text = ""
            fallback_index: int | None = None
            for candidate in weak_table_candidates:
                candidate = self._normalize_content_block_text(candidate, opts)
                if (
                    candidate
                    and not _TABLE_CANDIDATE_RE.match(candidate)
                    and not self._looks_reference_page_text(candidate)
                    and not self._looks_like_plot_artifact_text(candidate, meta)
                ):
                    fallback_text = candidate
                    break
            if not fallback_text:
                for idx, block in enumerate(normalized):
                    candidate = str(block.get("text") or "").strip()
                    if not candidate or block.get("type") not in {"body", "caption"}:
                        continue
                    candidate_metrics = self._table_like_line_metrics(candidate)
                    numeric_hits = len(re.findall(r"[-+]?\d+(?:[.,]\d+)?", candidate))
                    element_hits = len(self._domain_element_hits(candidate, meta))
                    structural_candidate = bool(
                        int(candidate_metrics.get("markdown_rows") or 0) >= 2
                        or (
                            int(candidate_metrics.get("line_count") or 0) >= 2
                            and int(candidate_metrics.get("max_cells") or 0) >= 3
                            and int(candidate_metrics.get("repeated_cell_count") or 0) >= 2
                        )
                        or (
                            int(candidate_metrics.get("aligned_delimiter_columns") or 0) >= 2
                            and int(candidate_metrics.get("rows_with_cells") or 0) >= 2
                        )
                    )
                    profile_bonus = self._has_table_domain_bonus_signal(candidate, meta)
                    if (
                        len(candidate) >= 60
                        and (structural_candidate or profile_bonus)
                        and (numeric_hits >= 2 or element_hits >= 2 or int(meta.get("table_cells") or 0) >= 8)
                        and not self._looks_reference_page_text(candidate)
                        and not self._looks_like_plot_artifact_text(candidate, meta)
                    ):
                        fallback_text = candidate
                        fallback_index = idx
                        break
            if fallback_text:
                table_payload = {
                    "type": "table",
                    "block_type": "table",
                    "page": int(page_num or meta.get("page") or 0) or None,
                    "order": (fallback_index + 1) if fallback_index is not None else len(normalized) + 1,
                    "text": fallback_text,
                    "text_chars": len(fallback_text),
                    "confidence": 0.55,
                    "quality": 0.55,
                    "source": "parser_detected_fallback",
                    "table_validated": True,
                    "table_validation_reason": "accepted_parser_detected_fallback",
                    "table_confidence": 0.55,
                    "table_source": "parser_detected_fallback",
                }
                if fallback_index is not None:
                    normalized[fallback_index].update(table_payload)
                else:
                    normalized.append(table_payload)
                validated_tables += 1
                table_sources["parser_detected_fallback"] = table_sources.get("parser_detected_fallback", 0) + 1

        out_meta = self._final_content_block_count_meta(normalized, metadata=meta)
        out_meta["content_block_retyped_to_reference_count"] = retyped_ref
        out_meta["content_block_retyped_to_formula_count"] = retyped_formula
        out_meta["content_block_retyped_to_caption_count"] = retyped_caption
        out_meta["content_block_split_mixed_count"] = split_mixed_blocks
        out_meta["content_block_dropped_noise_count"] = dropped_noise
        out_meta["misclassification_risk_blocks"] = misclassification_risk_blocks
        out_meta["unknown_recovered_as_strong_type"] = unknown_recovered_as_strong_type
        out_meta["content_block_table_validated_count"] = validated_tables
        out_meta["content_block_table_rejected_count"] = rejected_tables
        for reason, count in table_reject_reasons.items():
            out_meta[f"content_block_table_{reason}_count"] = count
        for source, count in table_sources.items():
            out_meta[f"content_block_table_source_{source}_count"] = count
        return normalized, out_meta

    def _looks_like_table_block_fragment(self, text: str, metadata: dict[str, Any] | None = None) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        meta = metadata or {}
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if not lines:
            return False
        if any(_TABLE_CANDIDATE_RE.match(line) for line in lines):
            return True
        markdown_like = [
            line
            for line in lines
            if _MARKDOWN_TABLE_ROW_RE.match(line) or _TABLE_SEPARATOR_ROW_RE.match(line)
        ]
        if markdown_like and len(markdown_like) == len(lines):
            return True
        if int(meta.get("table_count") or 0) <= 0 and int(meta.get("table_cells") or 0) <= 0:
            return False
        return bool(
            len(lines) <= 2
            and any(_MARKDOWN_TABLE_ROW_RE.match(line) for line in lines)
        )

    def _coalesce_adjacent_table_blocks(
        self,
        blocks: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
        *,
        page_num: int | None = None,
    ) -> list[dict[str, Any]]:
        """Merge split markdown/pdfplumber table fragments before final typing.

        Rebuilding blocks from final page text can split one detected table into a
        sequence like ``[Table candidate]`` -> header row -> separator row ->
        data rows, often with some rows mis-typed as ``formula`` because of math
        symbols. Table validation then never runs because no single block still
        carries the full table. We join only adjacent explicit markdown/table
        fragments so prose blocks stay untouched.
        """
        meta = metadata or {}
        merged: list[dict[str, Any]] = []
        pending: dict[str, Any] | None = None
        pending_parts: list[str] = []

        def flush_pending() -> None:
            nonlocal pending, pending_parts
            if pending is None:
                return
            combined = "\n".join(part for part in pending_parts if str(part or "").strip()).strip()
            if combined:
                item = dict(pending)
                item["type"] = "table"
                item["block_type"] = "table"
                item["page"] = int(item.get("page") or page_num or meta.get("page") or 0) or None
                item["text"] = combined
                item["text_chars"] = len(combined)
                item.setdefault("source", pending.get("source") or "coalesced_table_blocks")
                merged.append(item)
            pending = None
            pending_parts = []

        for raw in blocks or []:
            if not isinstance(raw, dict):
                flush_pending()
                continue
            raw_text = str(raw.get("text") or "").strip()
            if self._looks_like_table_block_fragment(raw_text, meta):
                if pending is None:
                    pending = dict(raw)
                pending_parts.append(raw_text)
                continue
            flush_pending()
            merged.append(raw)

        flush_pending()
        return merged

    def _content_blocks_from_final_text(
        self,
        text: str,
        *,
        page_num: int,
        metadata: dict[str, Any] | None = None,
        opts: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Build content blocks from the already-final page text.

        This is the synchronization boundary: final blocks are derived from
        ``PdfPageExtraction.text`` after footer/header/noise cleanup, table append,
        math micro-line stitching and flow repair. Raw visual blocks are still kept
        separately for diagnostics, but downstream parser metadata reads the final
        list.
        """
        opts = opts or {}
        raw_lines = [line for line in str(text or "").splitlines()]
        page_word_count = len(re.findall(r"\b[\wА-Яа-я-]{2,}\b", str(text or ""), flags=re.UNICODE))
        content_rich = page_word_count >= int(opts.get("line_noise_content_rich_min_words") or 180)
        pretyping_noise_filter_enabled = bool(opts.get("line_noise_pretyping_enabled", False))
        drop_short = int(opts.get("line_noise_short_max_len") or 3)
        removed_noise = 0
        final_lines: list[dict[str, Any]] = []
        for line in raw_lines:
            stripped = line.strip()
            if not stripped:
                final_lines.append({"text": "", "paragraph_break": True, "source": "final_text"})
                continue


            if pretyping_noise_filter_enabled and not content_rich:
                numeric_tokens = len(re.findall(r"[-+]?\d+(?:[.,]\d+)?", stripped))
                alpha_tokens = len(re.findall(r"[A-Za-zА-Яа-я]", stripped))
                noise_like = (
                    (len(stripped) <= drop_short and alpha_tokens <= 1)
                    or (numeric_tokens >= 3 and alpha_tokens <= 2 and len(stripped) <= 40)
                    or bool(re.match(r"^[\W_]+$", stripped))
                )
                if noise_like:
                    removed_noise += 1
                    continue
            final_lines.append({"text": stripped, "source": "final_text"})
        if not final_lines:
            return [], {
                "final_content_block_count": 0,
                "final_content_blocks_source": "final_text",
                "final_content_blocks_synced": True,
                "final_text_noise_lines_removed": int(removed_noise),
            }
        blocks, meta = self._content_blocks_from_lines(
            final_lines,
            page_num=page_num,
            metadata=metadata,
            max_blocks=int(opts.get("max_content_blocks_per_page") or 500),
            source="final_text",
            opts=opts,
        )
        meta["final_content_blocks_source"] = "final_text"
        meta["final_content_blocks_synced"] = True
        meta["final_content_block_count"] = len(blocks)
        meta["final_text_noise_lines_removed"] = int(removed_noise)
        return blocks, meta

    def _normalize_text_for_block_sync(self, text: str) -> str:
        """Normalize text for page.text/final_content_blocks sync diagnostics."""
        value = str(text or "")
        value = re.sub(r"\s+", " ", value)
        return value.strip().lower()

    def _final_content_blocks_sync_meta(self, page_text: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
        """Measure how closely final_content_blocks reproduce final page.text."""
        page_norm = self._normalize_text_for_block_sync(page_text)
        blocks_text = "\n".join(str(block.get("text") or "") for block in blocks or [] if isinstance(block, dict))
        blocks_norm = self._normalize_text_for_block_sync(blocks_text)

        ratio = 1.0
        length_ratio = 1.0
        if page_norm or blocks_norm:
            ratio = SequenceMatcher(None, page_norm[:12000], blocks_norm[:12000]).ratio()
            length_ratio = len(blocks_norm) / max(1, len(page_norm))

        not_in_page = 0
        for block in blocks or []:
            if not isinstance(block, dict):
                continue
            block_norm = self._normalize_text_for_block_sync(str(block.get("text") or ""))
            probe = block_norm[: min(240, len(block_norm))]
            if len(probe) >= 40 and probe not in page_norm:
                not_in_page += 1

        synced = True
        if page_norm and not blocks_norm:
            synced = False
        elif blocks_norm and not page_norm:
            synced = False
        elif page_norm and blocks_norm and (ratio < 0.72 or length_ratio < 0.45 or length_ratio > 1.65):
            synced = False
        elif blocks and not_in_page / max(1, len(blocks)) >= 0.25:
            synced = False

        return {
            "final_text_blocks_sync_ratio": round(ratio, 4),
            "final_blocks_to_page_text_length_ratio": round(length_ratio, 4),
            "final_block_text_not_in_page_blocks": int(not_in_page),
            "final_content_blocks_synced": bool(synced),
        }

    def _prune_blocks_not_in_page_text(
        self,
        *,
        page_text: str,
        blocks: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Drop final blocks that are not grounded in final page text.

        This enforces the v41 invariant: persisted final_content_blocks must be
        reproducible from final page.text after all cleanup stages.
        """
        page_norm = self._normalize_text_for_block_sync(page_text)
        if not page_norm or not blocks:
            return blocks, {
                "final_blocks_pruned_not_in_page": 0,
                "final_blocks_pruned_not_in_page_types": "-",
            }

        pruned = 0
        type_counter: Counter[str] = Counter()
        kept: list[dict[str, Any]] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_text = str(block.get("text") or "")
            block_norm = self._normalize_text_for_block_sync(block_text)
            probe = block_norm[: min(240, len(block_norm))]

            if len(probe) < 40 or probe in page_norm:
                kept.append(block)
                continue
            pruned += 1
            block_type = str(block.get("type") or block.get("block_type") or "unknown")
            type_counter[block_type] += 1

        return kept, {
            "final_blocks_pruned_not_in_page": int(pruned),
            "final_blocks_pruned_not_in_page_types": ";".join(f"{k}:{v}" for k, v in type_counter.most_common()) or "-",
        }

    def _finalize_content_blocks_for_page(
        self,
        *,
        page_text: str,
        metadata: dict[str, Any],
        opts: dict[str, Any] | None = None,
        page_num: int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Create final content_blocks synchronized with final page.text.

        ``raw_content_blocks`` keeps the early visual-line extraction.
        ``final_content_blocks`` and backward-compatible ``content_blocks`` point
        to the retyped blocks rebuilt from final page text by default.
        """
        opts = opts or {}
        meta = metadata
        raw_blocks = meta.get("raw_content_blocks") or meta.get("content_blocks") or meta.get("content_blocks_sample") or []
        if isinstance(raw_blocks, list) and raw_blocks and "raw_content_blocks" not in meta:
            meta["raw_content_blocks"] = raw_blocks
            meta["raw_content_blocks_sample"] = raw_blocks[:40]

        blocks: list[dict[str, Any]] = []
        build_meta: dict[str, Any] = {}

        rebuilt_from_final_text = True
        if opts.get("rebuild_content_blocks_from_final_text") is False:
            build_meta["final_content_blocks_forced_rebuild"] = True
        if rebuilt_from_final_text:
            blocks, build_meta = self._content_blocks_from_final_text(
                page_text,
                page_num=int(page_num or meta.get("page") or 0) or 0,
                metadata=meta,
                opts=opts,
            )
            meta.update(build_meta)

        retyped, retyped_meta = self._retype_content_blocks(
            blocks,
            metadata=meta,
            opts=opts,
            page_num=page_num,
        )
        pre_retype_pruned, pre_retype_prune_meta = self._prune_blocks_not_in_page_text(
            page_text=page_text,
            blocks=blocks,
        )
        retyped, prune_meta = self._prune_blocks_not_in_page_text(
            page_text=page_text,
            blocks=retyped,
        )
        for idx, block in enumerate(retyped, start=1):
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or block.get("block_type") or "body").strip().lower().replace("-", "_")
            block["type"] = block_type
            block["block_type"] = block_type
            block["order"] = idx
            block["page"] = int(block.get("page") or page_num or meta.get("page") or 0) or None
            if "confidence" in block and "quality" not in block:
                block["quality"] = block.get("confidence")
            block.setdefault("source", build_meta.get("final_content_blocks_source") or "final_content_blocks")

        out_meta = dict(build_meta)
        out_meta.update(retyped_meta)
        out_meta.update(prune_meta)
        sync_meta = self._final_content_blocks_sync_meta(page_text, retyped)


        fallback_sync_threshold = float(opts.get("final_content_blocks_sync_fallback_threshold") or 0.58)
        fallback_len_threshold = float(opts.get("final_content_blocks_sync_fallback_len_threshold") or 0.35)
        sync_ratio = float(sync_meta.get("final_text_blocks_sync_ratio") or 1.0)
        sync_len_ratio = float(sync_meta.get("final_blocks_to_page_text_length_ratio") or 1.0)
        if (
            retyped
            and pre_retype_pruned
            and (
                sync_ratio < fallback_sync_threshold
                or sync_len_ratio < fallback_len_threshold
            )
        ):
            retyped = pre_retype_pruned
            out_meta["final_content_blocks_forced_sync_fallback"] = True
            out_meta["final_content_blocks_forced_sync_fallback_reason"] = "low_sync_after_retype"
            out_meta["final_content_blocks_forced_sync_fallback_ratio"] = round(sync_ratio, 4)
            out_meta["final_content_blocks_forced_sync_fallback_len_ratio"] = round(sync_len_ratio, 4)
            out_meta["final_blocks_pruned_not_in_page"] = int(pre_retype_prune_meta.get("final_blocks_pruned_not_in_page") or 0)
            out_meta["final_blocks_pruned_not_in_page_types"] = str(pre_retype_prune_meta.get("final_blocks_pruned_not_in_page_types") or "-")
            for idx, block in enumerate(retyped, start=1):
                if not isinstance(block, dict):
                    continue
                block["order"] = idx
                block["page"] = int(block.get("page") or page_num or meta.get("page") or 0) or None
                block.setdefault("source", "final_text_sync_fallback")
            sync_meta = self._final_content_blocks_sync_meta(page_text, retyped)
        out_meta.update(sync_meta)
        out_meta["final_content_block_count"] = len(retyped)
        out_meta["final_content_blocks_source"] = str(build_meta.get("final_content_blocks_source") or "final_content_blocks")
        if int(out_meta.get("final_blocks_pruned_not_in_page") or 0) > 0:
            out_meta["final_content_blocks_sync_pruned"] = True
        out_meta["raw_content_block_count"] = len(raw_blocks) if isinstance(raw_blocks, list) else 0
        out_meta["content_blocks_are_final"] = bool(
            out_meta.get("final_content_blocks_synced")
        )
        out_meta["final_content_blocks_ordered"] = all(
            int(block.get("order") or index) == index
            for index, block in enumerate(retyped, start=1)
            if isinstance(block, dict)
        )
        out_meta["final_content_blocks_text_chars"] = sum(
            len(str(block.get("text") or ""))
            for block in retyped
            if isinstance(block, dict)
        )
        out_meta["final_page_text_chars"] = len(str(page_text or ""))
        return retyped, out_meta

    def _refresh_content_blocks_after_context(self, pages: list[PdfPageExtraction], opts: dict[str, Any] | None = None) -> list[PdfPageExtraction]:
        if not pages:
            return pages
        opts = opts or {}
        if not opts.get("emit_content_blocks", True):
            return pages
        for page in pages:
            final_blocks, meta = self._finalize_content_blocks_for_page(
                page_text=page.text,
                metadata=page.metadata,
                opts=opts,
                page_num=page.page_number,
            )
            page.metadata["final_content_blocks"] = final_blocks
            page.metadata["content_blocks"] = final_blocks
            page.metadata["content_blocks_sample"] = final_blocks[:40]
            page.metadata["final_content_blocks_sample"] = final_blocks[:40]
            page.metadata.update(meta)


            try:
                refreshed_class = self._classify_page_content(page.text, page.metadata)
                page.metadata.update(refreshed_class)
                for warning_name, flag_name in (
                    ("reference_page", "reference_page"),
                    ("formula_heavy_page", "formula_heavy_page"),
                    ("figure_heavy_page", "figure_heavy_page"),
                    ("figure_only_page", "figure_only_page"),
                    ("graph_axis_text_detected", "graph_axis_text_detected"),
                ):
                    warning_set = set(page.warnings or [])
                    if refreshed_class.get(flag_name):
                        warning_set.add(warning_name)
                    else:
                        warning_set.discard(warning_name)
                    page.warnings = sorted(warning_set)
            except Exception:
                pass

            try:
                page.quality_score = round(self._score_text(page.text, method=page.method, opts=opts, metadata=page.metadata), 3)
            except Exception:
                pass
        return pages

    def _remove_arxiv_footer_text(self, text: str, metadata: dict[str, Any] | None = None) -> str:
        """Remove arXiv/date/category footer/sidebar lines from body text."""
        if not text:
            return ""
        removed = 0
        preprint_id = ""
        out_lines: list[str] = []
        for line in text.splitlines():
            if self._is_arxiv_footer_line(line):
                removed += 1
                m = _ARXIV_ID_RE.search(line)
                if m:
                    preprint_id = "arXiv:" + m.group(1)
                continue
            out_lines.append(line)
        if metadata is not None:
            metadata["arxiv_footer_lines_removed"] = int(metadata.get("arxiv_footer_lines_removed") or 0) + removed
            if preprint_id:
                metadata["preprint_id"] = preprint_id
        return "\n".join(out_lines)

    def _remove_non_body_text_lines(self, text: str, opts: dict[str, Any] | None = None, metadata: dict[str, Any] | None = None) -> str:
        """Final safety cleanup for layout/simple candidates.

        Word-based extraction filters visual lines before rendering, but the
        selected candidate can still be pdfplumber_layout/simple. Apply the same
        conservative removal to plain text lines so graph ticks, page numbers and
        arXiv footers do not leak into body text.
        """
        if not text:
            return ""
        opts = opts or {}
        removed: dict[str, int] = {}
        kept: list[str] = []
        body_word_count = len(re.findall(r"\b[^\W\d_][^\W_]{1,}\b", str(text or ""), flags=re.UNICODE))
        content_rich_page = bool(
            body_word_count >= 180
            or (metadata and metadata.get("clean_short_body_page"))
            or (metadata and metadata.get("reference_page"))
        )
        for line in text.splitlines():
            kind = self._classify_visual_line(line, metadata)
            drop = kind in {"page_number", "watermark"}
            if opts.get("drop_arxiv_footer_from_body", True) and kind == "arxiv_footer":
                drop = True
            if (
                opts.get("drop_graph_axis_from_body", True)
                and kind == "graph_axis"
                and not content_rich_page
            ):
                drop = True
            if drop:
                removed[kind] = removed.get(kind, 0) + 1
                continue
            kept.append(line)
        if metadata is not None:
            for kind, count in removed.items():
                metadata[f"removed_{kind}_lines"] = int(metadata.get(f"removed_{kind}_lines") or 0) + count
            metadata["non_body_lines_removed"] = int(metadata.get("non_body_lines_removed") or 0) + sum(removed.values())
        return "\n".join(kept)

    def _stitch_math_micro_lines(self, text: str, metadata: dict[str, Any] | None = None) -> str:
        """Repair common math micro-line fragments like eta / 2 / /8."""
        if not text:
            return ""
        lines = text.splitlines()
        result: list[str] = []
        repairs = 0
        i = 0
        while i < len(lines):
            cur = lines[i].strip()
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            nxt2 = lines[i + 2].strip() if i + 2 < len(lines) else ""
            if (
                cur
                and nxt
                and nxt2
                and re.fullmatch(r"[^\W\d_]+", cur, flags=re.UNICODE)
                and re.fullmatch(r"[0-9]{1,2}", nxt)
                and (nxt2.startswith(("/", "(", ")")) or self._is_formula_like_line(nxt2) or len(nxt2) <= 12)
            ):
                result.append(f"{cur}^{nxt}{nxt2}")
                repairs += 1
                i += 3
                continue
            result.append(lines[i])
            i += 1
        if metadata is not None:
            metadata["math_microline_repairs"] = int(metadata.get("math_microline_repairs") or 0) + repairs
        return "\n".join(result)

    def _domain_element_hits(self, text: str, metadata: dict[str, Any] | None = None) -> set[str]:
        profile = self._domain_profile(metadata)
        return {m.group(0) for m in profile.element_re.finditer(str(text or ""))}

    def _material_element_hits(self, text: str) -> set[str]:


        return self._domain_element_hits(text)

    def _domain_table_bonus(self, text: str, metadata: dict[str, Any] | None = None) -> bool:
        value = str(text or "")
        if not value:
            return False
        profile = self._domain_profile(metadata)
        return bool(profile.strong_table_hint_re.search(value) or profile.table_context_hint_re.search(value))

    def _table_domain_bonus_enabled(self, metadata: dict[str, Any] | None = None) -> bool:
        """Return True only when caller explicitly enables non-generic hints.

        The base parser stays generic. Subject-specific words can only lower
        thresholds through profiles.py, not from hardcoded core parser lists.
        """
        meta = metadata or {}
        if bool(meta.get("table_domain_bonus_enabled")):
            return True
        return self._has_explicit_domain_bonus_profile(metadata=meta)

    def _has_table_domain_bonus_signal(self, text: str, metadata: dict[str, Any] | None = None) -> bool:
        if not self._table_domain_bonus_enabled(metadata):
            return False
        value = str(text or "")
        if not value:
            return False
        profile = self._domain_profile(metadata)
        element_hits = self._domain_element_hits(value, metadata)
        return bool(
            profile.strong_table_hint_re.search(value)
            or profile.table_semantic_context_re.search(value)
            or (len(element_hits) >= 3 and profile.table_context_hint_re.search(value))
        )

    def _looks_like_plot_artifact_text(self, text: str, metadata: dict[str, Any] | None = None) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        meta = metadata or {}
        profile = self._domain_profile(meta)
        figureish = bool(profile.plot_artifact_context_re.search(value)) or bool(meta.get("figure_heavy_page") or meta.get("graph_heavy_page"))
        if not figureish:
            return False
        if re.search(r"\b(?:Table|Таблица)\s+\w*\d+", value, re.IGNORECASE | re.UNICODE):
            return False




        metrics = self._table_like_line_metrics(value)
        line_count = int(metrics.get("line_count") or 0)
        max_cells = int(metrics.get("max_cells") or 0)
        repeated_cell_count = int(metrics.get("repeated_cell_count") or 0)
        numeric_lines = int(metrics.get("numeric_lines") or 0)
        alpha_lines = int(metrics.get("alpha_lines") or 0)
        markdown_rows = int(metrics.get("markdown_rows") or 0)
        structural = bool(
            (markdown_rows >= 2)
            or (line_count >= 2 and max_cells >= 3 and repeated_cell_count >= 2 and (numeric_lines >= 1 or alpha_lines >= 2))
        )
        if structural or (self._has_table_domain_bonus_signal(value, meta) and (line_count >= 2 or numeric_lines >= 1)):
            return False

        tokens = value.split()
        numeric_tokens = sum(1 for token in tokens if re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?(?:%|В°C|K|MPa|GPa|h|s|min)?", token))
        alpha_tokens = sum(1 for token in tokens if re.search(r"[^\W\d_]", token, flags=re.UNICODE))
        return bool(numeric_tokens >= 2 or alpha_tokens <= 12)

    def _looks_like_semantic_table_text(self, text: str, metadata: dict[str, Any] | None = None) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        if self._looks_like_plot_artifact_text(value, metadata):
            return False
        if re.search(r"\b(?:Table|Таблица)\s+\w*\d+", value, re.IGNORECASE | re.UNICODE):
            return True
        profile = self._domain_profile(metadata)
        metrics = self._table_like_line_metrics(value)
        line_count = int(metrics.get("line_count") or 0)
        max_cells = int(metrics.get("max_cells") or 0)
        repeated_cell_count = int(metrics.get("repeated_cell_count") or 0)
        markdown_rows = int(metrics.get("markdown_rows") or 0)
        numeric_lines = int(metrics.get("numeric_lines") or 0)
        alpha_lines = int(metrics.get("alpha_lines") or 0)
        generic_hint = bool(_TABLE_CONTEXT_HINT_RE.search(value))

        if markdown_rows >= 2:
            return True
        if line_count >= 2 and max_cells >= 3 and repeated_cell_count >= 2 and alpha_lines >= 1:
            return True

        tokens = value.split()
        numeric_tokens = sum(1 for token in tokens if re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?(?:%|В°C|K|MPa|GPa|h|s|min)?", token))
        alpha_tokens = sum(1 for token in tokens if re.search(r"[^\W\d_]", token, flags=re.UNICODE))
        has_units = bool(profile.table_unit_hint_re.search(value))
        cell_like = len([cell for cell in _TABLE_CELL_SPLIT_RE.split(value) if cell.strip()]) >= 3
        if generic_hint and numeric_tokens >= 2 and alpha_tokens >= 1 and (has_units or cell_like):
            return True
        if self._has_table_domain_bonus_signal(value, metadata) and numeric_tokens >= 2 and (cell_like or numeric_lines >= 1):
            return True
        return False

    def _table_like_line_metrics(self, text: str) -> dict[str, int | float | bool]:
        """Return cheap structure metrics for final table validation.

        The final table gate is structural-first: repeated cell counts, markdown
        rows, delimiter density and numeric/text row mix. Domain terms are not a
        base requirement and are handled only by explicit profile bonus helpers.
        """
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        data_lines = [line for line in lines if not _TABLE_CANDIDATE_RE.match(line) and not _TABLE_SEPARATOR_ROW_RE.match(line)]
        cell_counts: list[int] = []
        numeric_lines = 0
        alpha_lines = 0
        markdown_rows = 0
        delimiter_lines = 0
        total_cells = 0
        numeric_cells = 0
        alpha_cells = 0
        delimiter_position_counts: Counter[int] = Counter()
        for line in data_lines:
            if _MARKDOWN_TABLE_ROW_RE.match(line):
                markdown_rows += 1
            if "|" in line or "\t" in line or re.search(r"\s{2,}", line):
                delimiter_lines += 1




            for match in re.finditer(r"\||\t+| {2,}", line):
                delimiter_position_counts[match.start()] += 1
            cells = [cell.strip() for cell in _TABLE_CELL_SPLIT_RE.split(line) if cell.strip()]
            if len(cells) <= 1 and _TABLE_NUMERIC_ROW_RE.match(line):
                cells = line.split()
            cell_counts.append(len(cells))
            total_cells += len(cells)
            if re.search(r"[-+]?\d+(?:[.,]\d+)?", line):
                numeric_lines += 1
            if re.search(r"[^\W\d_]", line, flags=re.UNICODE):
                alpha_lines += 1
            numeric_cells += sum(1 for cell in cells if re.search(r"[-+]?\d+(?:[.,]\d+)?", cell))
            alpha_cells += sum(1 for cell in cells if re.search(r"[^\W\d_]", cell, flags=re.UNICODE))

        repeated_cell_count = max(Counter(cell_counts).values(), default=0)
        rows_with_cells = sum(1 for count in cell_counts if count >= 2)
        aligned_delimiter_columns = sum(1 for count in delimiter_position_counts.values() if count >= 2)
        return {
            "line_count": len(data_lines),
            "max_cells": max(cell_counts or [0]),
            "total_cells": total_cells,
            "rows_with_cells": rows_with_cells,
            "repeated_cell_count": repeated_cell_count,
            "numeric_lines": numeric_lines,
            "alpha_lines": alpha_lines,
            "numeric_cells": numeric_cells,
            "alpha_cells": alpha_cells,
            "markdown_rows": markdown_rows,
            "delimiter_lines": delimiter_lines,
            "aligned_delimiter_columns": aligned_delimiter_columns,
            "has_pipe_rows": bool(markdown_rows >= 2),
        }

    def _table_block_validation(self, text: str, metadata: dict[str, Any] | None = None) -> tuple[bool, str, float, str]:
        """Single structural gate for every final ``table`` block.

        Accepted tables must be pdfplumber/markdown candidates or show repeated
        cells/rows, numeric-text mix and bbox/line consistency from extraction
        metadata. Domain words are optional profile bonus only; rejected blocks are
        forced back to body/reference/formula/caption/graph_axis before projection.
        """
        value = str(text or "").strip()
        meta = metadata or {}
        profile = str(meta.get("page_profile") or "").lower()
        if not value:
            return False, "rejected_empty", 0.0, "unknown"
        if bool(meta.get("reference_page") or profile == "references") or self._looks_reference_page_text(value):
            return False, "rejected_reference_context", 0.0, "reference_context"
        if self._is_reference_like_line(value):
            return False, "rejected_reference_like", 0.0, "reference_like"
        metrics = self._table_like_line_metrics(value)
        line_count = int(metrics.get("line_count") or 0)
        max_cells = int(metrics.get("max_cells") or 0)
        repeated_cell_count = int(metrics.get("repeated_cell_count") or 0)
        markdown_rows = int(metrics.get("markdown_rows") or 0)
        delimiter_lines = int(metrics.get("delimiter_lines") or 0)
        aligned_delimiter_columns = int(metrics.get("aligned_delimiter_columns") or 0)
        numeric_lines = int(metrics.get("numeric_lines") or 0)
        alpha_lines = int(metrics.get("alpha_lines") or 0)
        numeric_cells = int(metrics.get("numeric_cells") or 0)
        alpha_cells = int(metrics.get("alpha_cells") or 0)
        total_cells = int(metrics.get("total_cells") or 0)
        explicit_candidate = bool(_TABLE_CANDIDATE_RE.search(value) or int(meta.get("table_count") or 0) > 0)
        has_table_title = bool(re.search(r"\b(?:Table|Таблица)\s+\w*\d+", value, re.IGNORECASE | re.UNICODE))
        generic_hint = bool(_TABLE_CONTEXT_HINT_RE.search(value))
        domain_bonus = self._has_table_domain_bonus_signal(value, meta)

        structured_grid = bool(line_count >= 2 and max_cells >= 3 and repeated_cell_count >= 2)
        delimiter_grid = bool(
            line_count >= 2
            and max_cells >= 3
            and delimiter_lines >= max(1, line_count // 2)
            and (repeated_cell_count >= 2 or aligned_delimiter_columns >= 2)
        )
        numeric_text_mix = bool(numeric_lines >= 1 and alpha_lines >= 1 and numeric_cells >= 2 and alpha_cells >= 2)
        dense_enough = bool(total_cells >= max(4, line_count * 2))



        word_count = len(re.findall(r"\b[^\W\d_]{2,}\b", value, flags=re.UNICODE))
        prose_like = bool(line_count <= 1 and len(value) > 240 and word_count > 28 and _PROSE_VERB_RE.search(value))
        if prose_like and not (structured_grid or delimiter_grid or markdown_rows >= 2):
            return False, "rejected_prose_like", 0.0, "prose_like"

        if (self._looks_like_plot_artifact_text(value, meta) or self._is_graph_axis_or_table_line(value, meta)) and not (
            structured_grid or delimiter_grid or numeric_text_mix or explicit_candidate or markdown_rows >= 2 or domain_bonus
        ):
            return False, "rejected_plot_axis_grid", 0.0, "plot_axis"
        if self._looks_math_heavy_text(value) and not (markdown_rows >= 2 or (structured_grid and numeric_text_mix)):
            return False, "rejected_formula_like", 0.0, "formula_like"
        if markdown_rows >= 2 and (structured_grid or explicit_candidate or total_cells >= 4):
            return True, "accepted_markdown_table", 0.90, "markdown_table"
        if explicit_candidate and (structured_grid or delimiter_grid or numeric_text_mix or dense_enough):
            return True, "accepted_pdfplumber_structural_candidate", 0.90, "pdfplumber_candidate"
        if has_table_title and (structured_grid or delimiter_grid or numeric_text_mix):
            return True, "accepted_labeled_structural_table", 0.84, "structured_labeled_table"
        if (structured_grid or delimiter_grid) and numeric_text_mix:
            return True, "accepted_structured_numeric_table", 0.78, "structured_numeric_table"
        if (structured_grid or delimiter_grid) and generic_hint and dense_enough:
            return True, "accepted_structured_generic_table", 0.74, "structured_generic_table"
        if domain_bonus and (structured_grid or delimiter_grid or numeric_text_mix) and dense_enough:
            return True, "accepted_profile_bonus_structural_table", 0.70, "profile_bonus_table"
        if line_count < 2 or max_cells < 3:
            return False, "rejected_too_small", 0.0, "too_small"
        return False, "rejected_no_table_structure", 0.0, "table_like_text"

    def _is_valid_table_block(self, text: str, metadata: dict[str, Any] | None = None) -> bool:
        accepted, _reason, _confidence, _source = self._table_block_validation(text, metadata)
        return accepted

    def _fallback_type_for_rejected_table(self, text: str, reason: str, metadata: dict[str, Any] | None = None) -> str:
        value = str(text or "").strip()
        meta = metadata or {}
        if reason in {"rejected_reference_context", "rejected_reference_like"} or self._looks_reference_page_text(value) or self._is_reference_like_line(value):
            return "reference"
        if reason in {"rejected_formula_like"} or self._looks_math_heavy_text(value):
            return "formula"
        if reason == "rejected_plot_axis_grid" or self._is_graph_axis_or_table_line(value, meta):
            return "graph_axis"
        if _CAPTION_RE.match(value) or _CAPTION_START_RE.match(value) or (
            str(meta.get("page_profile") or "") in {"figure_plate", "figure_only", "figure_label_only", "supplement"}
            and self._looks_caption_continuation_line(value)
        ):
            return "caption"
        return "body"

    def _is_explicit_table_line(self, text: str, metadata: dict[str, Any] | None = None) -> bool:
        value = (text or "").strip()
        if not value:
            return False
        if _TABLE_CANDIDATE_RE.match(value):
            return bool(int((metadata or {}).get("table_count") or 0) > 0)
        if _MARKDOWN_TABLE_ROW_RE.match(value):
            if _TABLE_SEPARATOR_ROW_RE.match(value):
                return bool(int((metadata or {}).get("table_count") or 0) > 0)
            return bool(self._looks_like_semantic_table_text(value, metadata))
        return False

    def _is_contextual_table_row(self, text: str, metadata: dict[str, Any] | None = None) -> bool:
        """Detect real table rows without stealing graph ticks/legends.

        The row-level detector now uses generic structure: accepted pdfplumber
        table context, repeated delimiters/cells, numeric-text mix and generic
        table headers. Domain words are optional profile bonus only.
        """
        value = (text or "").strip()
        if not value:
            return False
        meta = metadata or {}
        if self._is_explicit_table_line(value, meta):
            return True
        if _CAPTION_RE.match(value) or _CAPTION_START_RE.match(value):
            return False
        if self._looks_like_plot_artifact_text(value, meta):
            return False

        tokens = value.split()
        numeric_tokens = sum(1 for token in tokens if re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?(?:%|В°C|K|MPa|GPa|h|s|min)?", token))
        alpha_tokens = sum(1 for token in tokens if re.search(r"[^\W\d_]", token, flags=re.UNICODE))
        page_has_accepted_tables = int(meta.get("table_count") or 0) > 0 or int(meta.get("table_cells") or 0) > 0
        cell_count = len([cell for cell in _TABLE_CELL_SPLIT_RE.split(value) if cell.strip()])
        generic_hint = bool(_TABLE_CONTEXT_HINT_RE.search(value))
        delimiter_like = bool("|" in value or "\t" in value or re.search(r"\s{2,}", value))

        if alpha_tokens == 0:
            return False
        if delimiter_like and cell_count >= 3 and (generic_hint or page_has_accepted_tables):
            return True
        if delimiter_like and cell_count >= 3 and numeric_tokens >= 1 and alpha_tokens >= 1:
            return True
        if self._looks_like_semantic_table_text(value, meta) and numeric_tokens >= 1:
            return True
        if not _TABLE_NUMERIC_ROW_RE.match(value):
            return False
        if page_has_accepted_tables and numeric_tokens >= 2 and alpha_tokens >= 1:
            return True
        if generic_hint and numeric_tokens >= 2 and cell_count >= 3:
            return True
        if self._has_table_domain_bonus_signal(value, meta) and numeric_tokens >= 2 and cell_count >= 3:
            return True
        return False

    def _is_graph_axis_or_table_line(self, text: str, metadata: dict[str, Any] | None = None) -> bool:
        value = (text or "").strip()
        if not value:
            return False
        token_count = len(value.split())
        if _GRAPH_AXIS_LINE_RE.match(value):
            return True
        if (len(value) <= 48 or token_count <= 6) and (_AXIS_LABEL_LINE_RE.match(value) or _REVERSED_AXIS_LABEL_RE.match(value)):
            return True
        profile_obj = self._domain_profile(metadata)
        if token_count >= 7 and profile_obj.prose_guard_re.search(value):
            return False



        if re.fullmatch(r"[-+]?\d+[.,]\d+(?:[eE][-+]?\d+)?|10[в€’-]\d+", value):
            return True



        if _TABLE_NUMERIC_ROW_RE.match(value) and self._is_contextual_table_row(value, metadata):
            return False
        if _FIGURE_LABEL_LINE_RE.match(value):
            return True

        tokens = value.split()
        numeric_tokens = sum(1 for token in tokens if re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", token))
        return len(value) <= 42 and len(tokens) >= 3 and numeric_tokens / max(1, len(tokens)) >= 0.65

    def _has_bibliographic_signal(self, text: str) -> bool:
        return bool(_BIBLIOGRAPHIC_SIGNAL_RE.search(str(text or "")))

    def _is_protected_reference_service_text(self, text: str) -> bool:
        value = str(text or "").strip()
        return bool(value and _PROTECTED_REFERENCE_SECTION_RE.match(value))

    def _is_equation_numbered_body_line(self, text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        if not _EQUATION_NUMBERED_BODY_RE.match(value):
            return False
        return not self._has_bibliographic_signal(value)

    def _is_reference_like_line(self, text: str) -> bool:
        value = (text or "").strip()
        if not value:
            return False
        if self._is_protected_reference_service_text(value) or self._is_equation_numbered_body_line(value):
            return False
        if not _REFERENCE_ENUMERATOR_RE.match(value):
            return False
        return bool(_REFERENCE_LINE_RE.match(value) and self._has_bibliographic_signal(value))

    def _should_force_reference_block(self, text: str, original_type: str, metadata: dict[str, Any] | None = None) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        if self._is_protected_reference_service_text(value):
            return False
        if self._is_equation_numbered_body_line(value):
            return False
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if not lines:
            lines = [value]
        reference_lines = sum(1 for line in lines if self._is_reference_like_line(line))
        referenceish_lines = sum(
            1
            for line in lines
            if _REFERENCE_ENUMERATOR_RE.match(line) and self._has_bibliographic_signal(line)
        )
        has_heading = any(_REFERENCE_HEADING_RE.match(line) for line in lines[:4])
        if original_type == "reference" and (reference_lines > 0 or referenceish_lines > 0 or has_heading):
            return True
        if has_heading and (reference_lines > 0 or referenceish_lines > 0):
            return True
        if reference_lines >= max(1, min(3, len(lines))):
            return True
        if referenceish_lines >= max(1, min(3, len(lines))):
            return True
        if len(value) > 220 and reference_lines >= 1 and self._has_bibliographic_signal(value):
            return True
        return False

    def _looks_reference_page_text(self, text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if not lines:
            lines = [value]
        has_heading = any(_REFERENCE_HEADING_RE.match(line) for line in lines[:6])
        reference_like = sum(1 for line in lines if self._is_reference_like_line(line))
        signal_lines = sum(1 for line in lines if _REFERENCE_ENUMERATOR_RE.match(line) and self._has_bibliographic_signal(line))
        return bool((has_heading and (reference_like + signal_lines) >= 1) or (reference_like + signal_lines) >= max(3, len(lines) // 3))

    def _looks_reference_page_lines(self, lines: list[dict[str, Any]]) -> bool:
        texts = [str(line.get("text") or "").strip() for line in lines if str(line.get("text") or "").strip()]
        if not texts:
            return False
        has_heading = any(_REFERENCE_HEADING_RE.match(text) for text in texts[:8])
        reference_like = sum(1 for text in texts if self._is_reference_like_line(text))
        signal_lines = sum(1 for text in texts if _REFERENCE_ENUMERATOR_RE.match(text) and self._has_bibliographic_signal(text))
        return bool((has_heading and (reference_like + signal_lines) >= 1) or (reference_like + signal_lines) >= max(4, len(texts) // 4))

    def _footnote_candidate_rejection_reason(self, line: dict[str, Any], *, page_height: float, median_font: float) -> str | None:
        """Return why a small bottom-page line must NOT become a footnote.

        Used for audit counters and to avoid false Footnotes blocks from chart
        tick labels, table rows, figure labels and reference lists.
        """
        text = str(line.get("text") or "").strip()
        if not text:
            return None
        top = float(line.get("top") or 0.0)
        font_size = float(line.get("font_size") or 0.0)
        near_bottom = page_height > 0 and top >= page_height * 0.78
        lower_third = page_height > 0 and top >= page_height * 0.66
        small_font = median_font > 0 and font_size > 0 and font_size <= median_font * 0.90
        marker_or_explicit = bool(_FOOTNOTE_MARKER_RE.match(text)) or bool(
            re.search(r"\b(?:correspondence|corresponding author|email|e-mail|present address|deceased|equal contribution)\b", text, re.IGNORECASE)
        ) or "@" in text
        candidate_position = near_bottom or (lower_third and small_font)
        if not (candidate_position and (small_font or marker_or_explicit)):
            return None
        if _FIGURE_LABEL_LINE_RE.match(text) or _LABEL_ONLY_LINE_RE.match(text) or _CAPTION_RE.match(text):
            return "figure_label"
        if self._is_reference_like_line(text):
            return "reference"
        if _TABLE_NUMERIC_ROW_RE.match(text):
            return "table"
        if self._is_graph_axis_or_table_line(text):
            return "graph_axis"
        if _SECTION_HEADING_RE.match(text):
            return "section_heading"
        return "weak_signal"

    def _is_likely_footnote_line(self, line: dict[str, Any], *, page_height: float, median_font: float) -> bool:
        text = str(line.get("text") or "").strip()
        if not text:
            return False
        if self._is_graph_axis_or_table_line(text) or self._is_reference_like_line(text):
            return False
        if _CAPTION_RE.match(text) or _FIGURE_LABEL_LINE_RE.match(text) or _LABEL_ONLY_LINE_RE.match(text) or _SECTION_HEADING_RE.match(text):
            return False

        top = float(line.get("top") or 0.0)
        font_size = float(line.get("font_size") or 0.0)
        near_bottom = page_height > 0 and top >= page_height * 0.82
        lower_third = page_height > 0 and top >= page_height * 0.70
        small_font = median_font > 0 and font_size > 0 and font_size <= median_font * 0.82
        marker = bool(_FOOTNOTE_MARKER_RE.match(text))
        explicit = bool(re.search(r"\b(?:correspondence|corresponding author|email|e-mail|present address|deceased|equal contribution|affiliation)\b", text, re.IGNORECASE))
        email = "@" in text
        short = len(text) <= 220




        signal = marker or explicit or email
        return short and signal and (near_bottom or (lower_third and small_font))

    def _split_footnote_lines(
        self,
        lines: list[dict[str, Any]],
        *,
        page_height: float,
        return_metadata: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        """Separate likely bottom-of-page footnotes from body lines.

        The detector is intentionally strict. Graph axis labels, numeric table
        rows, references and figure labels often use small fonts near the bottom
        but are not footnotes and must stay out of the Footnotes block.
        """
        empty_meta = {
            "rejected_footnote_graph_axis": 0,
            "rejected_footnote_reference": 0,
            "rejected_footnote_table": 0,
            "rejected_footnote_figure_label": 0,
            "rejected_footnote_section_heading": 0,
            "rejected_footnote_weak_signal": 0,
            "reference_context_footnotes_disabled": 0,
        }
        if not lines or page_height <= 0:
            return (lines, [], empty_meta) if return_metadata else (lines, [])

        font_sizes = sorted(float(line.get("font_size") or 0.0) for line in lines if float(line.get("font_size") or 0.0) > 0)
        median_font = font_sizes[len(font_sizes) // 2] if font_sizes else 0.0
        meta = dict(empty_meta)

        if self._looks_reference_page_lines(lines):
            meta["reference_context_footnotes_disabled"] = 1
            for line in lines:
                reason = self._footnote_candidate_rejection_reason(line, page_height=page_height, median_font=median_font)
                if reason:
                    key = f"rejected_footnote_{reason}"
                    if key in meta:
                        meta[key] += 1
            return (lines, [], meta) if return_metadata else (lines, [])

        footnotes: list[dict[str, Any]] = []
        body: list[dict[str, Any]] = []

        for line in lines:
            if self._is_likely_footnote_line(line, page_height=page_height, median_font=median_font):
                footnotes.append(line)
            else:
                reason = self._footnote_candidate_rejection_reason(line, page_height=page_height, median_font=median_font)
                if reason:
                    key = f"rejected_footnote_{reason}"
                    if key in meta:
                        meta[key] += 1
                body.append(line)



        if len(footnotes) == 1:
            single = str(footnotes[0].get("text") or "")
            if "@" not in single and not re.search(r"\b(?:correspondence|corresponding author|e-mail|email)\b", single, re.IGNORECASE):
                meta["rejected_footnote_weak_signal"] += 1
                return (lines, [], meta) if return_metadata else (lines, [])

        return (body, footnotes, meta) if return_metadata else (body, footnotes)



__all__ = ["PDFContentBlockMixin"]


