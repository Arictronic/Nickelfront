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

class PDFLayoutMixin:
    """PDF layout recovery: words, lines, columns, reading order."""

    def _safe_extract_text(self, page: Any, *, layout: bool) -> str:
        try:
            if layout:
                return page.extract_text(layout=True, x_tolerance=2, y_tolerance=3) or ""
            return page.extract_text(x_tolerance=2, y_tolerance=3) or ""
        except TypeError:
            try:
                return page.extract_text(layout=layout) or ""
            except Exception:
                return ""
        except Exception:
            return ""

    def _safe_extract_words(self, page: Any) -> list[dict[str, Any]]:
        try:
            return page.extract_words(
                x_tolerance=1.5,
                y_tolerance=3,
                keep_blank_chars=False,
                use_text_flow=False,
                extra_attrs=["upright", "fontname", "size"],
            ) or []
        except TypeError:
            try:
                return page.extract_words(
                    x_tolerance=1.5,
                    y_tolerance=3,
                    keep_blank_chars=False,
                    use_text_flow=False,
                ) or []
            except TypeError:
                try:
                    return page.extract_words() or []
                except Exception:
                    return []
            except Exception:
                return []
        except Exception:
            return []

    def _dedupe_words(self, words: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove duplicated overlay words from PDF text layer.

        Some scientific PDFs contain the same glyph twice at almost identical
        coordinates. Plain extraction then produces ηη, UU, duplicated author
        markers, etc. Coordinate-level dedupe is safer than blind text replace.
        """
        if not words:
            return []
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int, int, int]] = set()
        for word in words:



            if word.get("upright") is False:
                continue
            if str(word.get("direction") or "ltr").lower() not in {"", "ltr"}:
                continue

            text = unicodedata.normalize("NFKC", str(word.get("text") or "")).strip()
            if not text:
                continue
            try:
                key = (
                    text,
                    round(float(word.get("x0") or 0) * 2),
                    round(float(word.get("top") or word.get("y0") or 0) * 2),
                    round(float(word.get("x1") or 0) * 2),
                    round(float(word.get("bottom") or word.get("y1") or 0) * 2),
                )
            except Exception:
                key = (text, len(deduped), 0, 0, 0)
            if key in seen:
                continue
            seen.add(key)
            copied = dict(word)
            copied["text"] = text
            deduped.append(copied)
        return deduped

    def _word_float(self, word: dict[str, Any], key: str, default: float = 0.0) -> float:
        try:
            return float(word.get(key) if word.get(key) is not None else default)
        except Exception:
            return default

    def _median_number(self, values: Iterable[float], default: float = 0.0) -> float:
        cleaned = sorted(float(v) for v in values if v is not None and float(v) > 0)
        if not cleaned:
            return default
        return cleaned[len(cleaned) // 2]

    def _median_word_height(self, words: list[dict[str, Any]], default: float = 10.0) -> float:
        return self._median_number(
            (
                max(1.0, self._word_float(w, "bottom", self._word_float(w, "y1")) - self._word_float(w, "top", self._word_float(w, "y0")))
                for w in words
            ),
            default=default,
        )

    def _median_word_size(self, words: list[dict[str, Any]], default: float = 0.0) -> float:
        return self._median_number((self._word_float(w, "size", 0.0) for w in words), default=default)

    def _percentile_number(self, values: Iterable[float], percentile: float, default: float = 0.0) -> float:
        cleaned = sorted(float(v) for v in values if v is not None)
        if not cleaned:
            return default
        if len(cleaned) == 1:
            return cleaned[0]
        pos = max(0.0, min(1.0, percentile)) * (len(cleaned) - 1)
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            return cleaned[lo]
        return cleaned[lo] + (cleaned[hi] - cleaned[lo]) * (pos - lo)

    def _line_float(self, line: dict[str, Any], key: str, default: float = 0.0) -> float:
        try:
            return float(line.get(key) if line.get(key) is not None else default)
        except Exception:
            return default

    def _line_center_x(self, line: dict[str, Any]) -> float:
        return (self._line_float(line, "x0") + self._line_float(line, "x1")) / 2.0

    def _line_span(self, line: dict[str, Any]) -> float:
        return max(0.0, self._line_float(line, "x1") - self._line_float(line, "x0"))

    def _same_visual_baseline(self, word: dict[str, Any], group: list[dict[str, Any]], *, y_tolerance: float) -> bool:
        """Return True when a word belongs to the current visual baseline.

        Scientific PDFs often have slightly different ``top`` values inside one
        line because of mixed font sizes, superscripts or equation tokens.  A
        pure top-distance check can split one visual line; a pure y-overlap check
        can merge neighbouring lines.  Use both signals conservatively.
        """
        if not group:
            return True
        top = self._word_float(word, "top", self._word_float(word, "y0"))
        bottom = self._word_float(word, "bottom", self._word_float(word, "y1"))
        group_top = self._percentile_number((self._word_float(w, "top", self._word_float(w, "y0")) for w in group), 0.5, top)
        group_bottom = self._percentile_number((self._word_float(w, "bottom", self._word_float(w, "y1")) for w in group), 0.5, bottom)
        top_close = abs(top - group_top) <= y_tolerance
        overlap = max(0.0, min(bottom, group_bottom) - max(top, group_top))
        min_height = max(1.0, min(bottom - top, group_bottom - group_top))
        strong_overlap = overlap / min_height >= 0.58 and abs(top - group_top) <= y_tolerance * 1.8
        return top_close or strong_overlap

    def _line_vertical_range(self, lines: list[dict[str, Any]]) -> tuple[float, float]:
        if not lines:
            return 0.0, 0.0
        return min(self._line_float(line, "top") for line in lines), max(self._line_float(line, "bottom", self._line_float(line, "top")) for line in lines)

    def _range_overlap_ratio(self, a: tuple[float, float], b: tuple[float, float]) -> float:
        overlap = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
        shortest = max(1.0, min(max(1.0, a[1] - a[0]), max(1.0, b[1] - b[0])))
        return overlap / shortest

    def _line_word_count(self, line: dict[str, Any]) -> int:
        text = str(line.get("text") or "")
        return int(line.get("word_count") or max(1, len(text.split())))

    def _build_column_profile(
        self,
        lines: list[dict[str, Any]],
        width: float,
        *,
        height: float = 0.0,
        paired_baselines: int = 0,
        force: bool = False,
    ) -> dict[str, Any]:
        """Detect left/right column geometry from visual-line bboxes.

        The detector is intentionally geometry-only: x clusters, bboxes,
        vertical overlap and gutter size.  It ignores domain terms and section
        names so the parser stays usable for non-materials PDFs.
        """
        profile: dict[str, Any] = {
            "is_two_column": False,
            "confidence": 0.0,
            "reason": "insufficient_geometry",
            "left_count": 0,
            "right_count": 0,
            "middle_count": 0,
            "full_width_count": 0,
            "paired_baselines": paired_baselines,
            "gutter_left": width * 0.49 if width > 0 else 0.0,
            "gutter_right": width * 0.51 if width > 0 else 0.0,
            "left_x0": 0.0,
            "left_x1": width * 0.49 if width > 0 else 0.0,
            "right_x0": width * 0.51 if width > 0 else 0.0,
            "right_x1": width if width > 0 else 0.0,
        }
        if width <= 0 or not lines:
            return profile

        usable: list[dict[str, Any]] = []
        full_width_count = 0
        for line in lines:
            text = str(line.get("text") or "").strip()
            if not text:
                continue
            span = self._line_span(line)
            if (
                self._is_full_width_line(line, width)
                or self._is_centered_layout_breaker_line(line, width)
                or span >= width * 0.62
            ):
                full_width_count += 1
                continue


            if self._line_word_count(line) <= 1 and len(lines) >= 10:
                continue
            if span <= 0 or span > width * 0.60:
                continue
            usable.append(line)

        profile["full_width_count"] = full_width_count
        if len(usable) < (4 if not force else 2):
            if force:
                profile.update({"is_two_column": True, "confidence": 0.5, "reason": "forced_midpoint_fallback"})
            return profile

        left_seed = [line for line in usable if self._line_center_x(line) < width * 0.49 or self._line_float(line, "x1") <= width * 0.53]
        right_seed = [line for line in usable if self._line_center_x(line) > width * 0.51 or self._line_float(line, "x0") >= width * 0.47]

        if not left_seed or not right_seed:
            if force:
                profile.update({"is_two_column": True, "confidence": 0.5, "reason": "forced_midpoint_fallback"})
            return profile



        left_x0 = self._percentile_number((self._line_float(line, "x0") for line in left_seed), 0.15, 0.0)
        left_x1 = self._percentile_number((self._line_float(line, "x1") for line in left_seed), 0.85, width * 0.49)
        right_x0 = self._percentile_number((self._line_float(line, "x0") for line in right_seed), 0.15, width * 0.51)
        right_x1 = self._percentile_number((self._line_float(line, "x1") for line in right_seed), 0.85, width)
        gutter = right_x0 - left_x1

        left_lines: list[dict[str, Any]] = []
        right_lines: list[dict[str, Any]] = []
        middle_lines: list[dict[str, Any]] = []
        margin = max(6.0, width * 0.012)
        for line in usable:
            x0 = self._line_float(line, "x0")
            x1 = self._line_float(line, "x1")
            center = self._line_center_x(line)
            if x1 <= left_x1 + margin or center < (left_x1 + right_x0) / 2.0:
                left_lines.append(line)
            elif x0 >= right_x0 - margin or center >= (left_x1 + right_x0) / 2.0:
                right_lines.append(line)
            else:
                middle_lines.append(line)

        left_count = len(left_lines)
        right_count = len(right_lines)
        middle_count = len(middle_lines)
        total = max(1, left_count + right_count + middle_count)
        min_side = min(left_count, right_count)
        side_balance = min_side / max(1, max(left_count, right_count))
        clear_gutter = gutter >= max(10.0, width * 0.022)
        middle_ratio = middle_count / total
        full_ratio = full_width_count / max(1, len(lines))
        y_overlap = self._range_overlap_ratio(self._line_vertical_range(left_lines), self._line_vertical_range(right_lines))

        short_page = len(lines) < 18 or len(usable) < 14
        enough_sides = min_side >= (2 if short_page else 4)
        enough_total = total >= (4 if short_page else 10)
        paired_signal = paired_baselines >= (2 if short_page else 5)

        confidence = 0.0
        if enough_sides and enough_total:
            confidence += 0.25
        if clear_gutter:
            confidence += 0.25
        if side_balance >= 0.35:
            confidence += 0.18
        elif side_balance >= 0.22:
            confidence += 0.10
        if middle_ratio <= 0.22:
            confidence += 0.12
        if y_overlap >= 0.22:
            confidence += 0.10
        if paired_signal:
            confidence += 0.14
        if full_ratio <= 0.65:
            confidence += 0.06
        confidence = max(0.0, min(1.0, confidence))

        geometry_two_column = bool(
            enough_sides
            and enough_total
            and clear_gutter
            and middle_ratio <= 0.34
            and (confidence >= (0.58 if short_page else 0.62) or paired_signal)
        )
        is_two_column = geometry_two_column or force
        reason = "two_column_geometry" if geometry_two_column else "low_confidence_geometry"
        if force and not geometry_two_column:
            reason = "forced_midpoint_fallback"
            confidence = max(confidence, 0.5)

        profile.update(
            {
                "is_two_column": is_two_column,
                "confidence": round(confidence, 3),
                "reason": reason,
                "left_count": left_count,
                "right_count": right_count,
                "middle_count": middle_count,
                "paired_baselines": paired_baselines,
                "gutter_left": round(left_x1, 3),
                "gutter_right": round(right_x0, 3),
                "gutter_width": round(max(0.0, gutter), 3),
                "left_x0": round(left_x0, 3),
                "left_x1": round(left_x1, 3),
                "right_x0": round(right_x0, 3),
                "right_x1": round(right_x1, 3),
                "side_balance": round(side_balance, 3),
                "middle_ratio": round(middle_ratio, 3),
                "full_width_ratio": round(full_ratio, 3),
                "vertical_overlap": round(y_overlap, 3),
            }
        )
        return profile

    def _assign_line_to_column(self, line: dict[str, Any], profile: dict[str, Any], width: float) -> str:
        if not profile.get("is_two_column") or width <= 0:
            return "center"
        x0 = self._line_float(line, "x0")
        x1 = self._line_float(line, "x1")
        center = self._line_center_x(line)
        span = max(0.0, x1 - x0)
        gutter_left = float(profile.get("gutter_left") or width * 0.49)
        gutter_right = float(profile.get("gutter_right") or width * 0.51)
        margin = max(6.0, width * 0.012)
        gutter_mid = (gutter_left + gutter_right) / 2.0





        crosses_gutter = x0 <= gutter_right - margin and x1 >= gutter_left + margin
        compact_centered = span <= width * 0.52 and abs(center - gutter_mid) <= max(24.0, width * 0.055)
        if crosses_gutter and compact_centered:
            return "center"

        if x1 <= gutter_left + margin or center < gutter_mid:
            return "left"
        if x0 >= gutter_right - margin or center >= gutter_mid:
            return "right"
        return "center"

    def _dominant_fontname(self, words: list[dict[str, Any]]) -> str:
        fontnames: dict[str, int] = {}
        for word in words:
            name = str(word.get("fontname") or "").strip()
            if name:
                fontnames[name] = fontnames.get(name, 0) + 1
        return (max(fontnames.items(), key=lambda kv: kv[1])[0] if fontnames else "")[:120]

    def _filter_watermark_words(self, words: list[dict[str, Any]], page: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Drop obvious layout watermarks while keeping normal references/prose.

        Do not remove a word just because it says "preprint" or "manuscript":
        those words are common in References. We only remove watermark-like words
        when there is a layout signal: very large font, rotated text, isolated
        central token, or a repeated edge/center stamp.
        """
        if not words:
            return [], {"watermark_words_removed": 0, "possible_watermark_words": 0}

        page_width = float(getattr(page, "width", 0) or 0)
        page_height = float(getattr(page, "height", 0) or 0)
        median_size = self._median_word_size(words, default=10.0)
        kept: list[dict[str, Any]] = []
        removed = 0
        possible = 0

        for word in words:
            text = unicodedata.normalize("NFKC", str(word.get("text") or "")).strip()
            if not text or not _WATERMARK_WORD_RE.fullmatch(text):
                kept.append(word)
                continue

            possible += 1
            top = self._word_float(word, "top", self._word_float(word, "y0"))
            bottom = self._word_float(word, "bottom", self._word_float(word, "y1"))
            x0 = self._word_float(word, "x0")
            x1 = self._word_float(word, "x1")
            center_x = (x0 + x1) / 2 if x1 or x0 else 0.0
            font_size = self._word_float(word, "size", 0.0)
            upright = word.get("upright")

            edge_band = page_height > 0 and (top <= page_height * 0.10 or bottom >= page_height * 0.90)
            center_band = page_width > 0 and abs(center_x - page_width / 2.0) <= max(30.0, page_width * 0.16)
            very_large = median_size > 0 and font_size >= max(14.0, median_size * 1.55)
            rotated = upright is False
            isolated = len(text) >= 5 and len(text.split()) == 1

            if rotated or (center_band and very_large and isolated) or (edge_band and very_large and isolated):
                removed += 1
                continue

            kept.append(word)

        return kept, {"watermark_words_removed": removed, "possible_watermark_words": possible}

    def _is_arxiv_footer_line(self, text: str) -> bool:
        value = unicodedata.normalize("NFKC", str(text or "")).strip()
        return bool(_ARXIV_FOOTER_RE.match(value))

    def _word_stats(self, words: list[dict[str, Any]]) -> dict[str, Any]:
        if not words:
            return {"median_word_height": 0.0, "median_font_size": 0.0, "fontname_top": ""}
        return {
            "median_word_height": round(self._median_word_height(words), 3),
            "median_font_size": round(self._median_word_size(words), 3),
            "fontname_top": self._dominant_fontname(words),
        }

    def _words_to_lines(self, words: list[dict[str, Any]], page_width: float = 0.0) -> list[dict[str, Any]]:
        """Build visual text lines from PDF words.

        pdfplumber returns words as positioned glyph groups. A naïve y-sort can
        merge left and right column rows when both columns have the same vertical
        coordinate. This function first groups by baseline, then splits each
        baseline into independent horizontal segments when there is a large gap
        between words. That makes downstream column ordering much safer.
        """
        if not words:
            return []

        median_height = self._median_word_height(words, default=10.0)
        y_tolerance = max(2.0, min(7.0, median_height * 0.45))

        ordered = sorted(
            words,
            key=lambda w: (
                self._word_float(w, "top", self._word_float(w, "y0")),
                self._word_float(w, "x0"),
            ),
        )
        baselines: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []

        for word in ordered:
            if self._same_visual_baseline(word, current, y_tolerance=y_tolerance):
                current.append(word)
                continue
            baselines.append(current)
            current = [word]
        if current:
            baselines.append(current)

        result: list[dict[str, Any]] = []
        for baseline in baselines:
            for segment in self._split_word_line_segments(baseline, page_width=page_width):
                segment = sorted(segment, key=lambda w: self._word_float(w, "x0"))
                text = self._join_line_words(segment)
                if not text:
                    continue
                x0 = min(self._word_float(w, "x0") for w in segment)
                x1 = max(self._word_float(w, "x1") for w in segment)
                top = min(self._word_float(w, "top", self._word_float(w, "y0")) for w in segment)
                bottom = max(self._word_float(w, "bottom", self._word_float(w, "y1")) for w in segment)
                result.append(
                    {
                        "x0": x0,
                        "x1": x1,
                        "top": top,
                        "bottom": bottom,
                        "text": text,
                        "word_count": len(segment),
                        "height": max(1.0, bottom - top),
                        "font_size": self._median_word_size(segment, default=0.0),
                        "fontname": self._dominant_fontname(segment),
                    }
                )
        return result

    def _split_word_line_segments(self, words: list[dict[str, Any]], *, page_width: float = 0.0) -> list[list[dict[str, Any]]]:
        """Split one baseline into independent visual line segments.

        This prevents two-column rows with the same y coordinate from becoming
        one artificial line like "left column text right column text".  The split
        is based on a dominant horizontal gap plus a gutter-position check; this
        avoids over-splitting normal justified one-column prose near the middle.
        """
        ordered = sorted(words, key=lambda w: self._word_float(w, "x0"))
        if len(ordered) <= 1:
            return [ordered]

        widths = [
            max(1.0, self._word_float(w, "x1") - self._word_float(w, "x0"))
            for w in ordered
        ]
        widths_sorted = sorted(widths)
        median_word_width = widths_sorted[len(widths_sorted) // 2] if widths_sorted else 12.0
        gaps = [
            max(0.0, self._word_float(word, "x0") - self._word_float(prev, "x1"))
            for prev, word in zip(ordered, ordered[1:])
        ]
        positive_gaps = sorted(g for g in gaps if g > 0)
        median_gap = positive_gaps[len(positive_gaps) // 2] if positive_gaps else 3.0
        page_gap = page_width * 0.045 if page_width > 0 else 0.0
        split_gap = max(22.0, median_word_width * 2.7, median_gap * 4.0, page_gap)
        middle_gap = max(10.0, median_gap * 3.0, page_width * 0.016) if page_width > 0 else max(10.0, median_gap * 3.0)

        segments: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = [ordered[0]]
        for index, (prev, word) in enumerate(zip(ordered, ordered[1:]), start=1):
            gap = self._word_float(word, "x0") - self._word_float(prev, "x1")
            prev_x0 = self._word_float(prev, "x0")
            prev_x1 = self._word_float(prev, "x1")
            word_x0 = self._word_float(word, "x0")
            word_x1 = self._word_float(word, "x1")
            prev_center = (prev_x0 + prev_x1) / 2
            word_center = (word_x0 + word_x1) / 2
            prefix = ordered[:index]
            suffix = ordered[index:]
            prefix_span = max(self._word_float(w, "x1") for w in prefix) - min(self._word_float(w, "x0") for w in prefix)
            suffix_span = max(self._word_float(w, "x1") for w in suffix) - min(self._word_float(w, "x0") for w in suffix)
            prefix_words = len(prefix)
            suffix_words = len(suffix)
            min_fragment_span = max(35.0, page_width * 0.12 if page_width > 0 else 35.0)
            strong_fragment_span = max(50.0, page_width * 0.18 if page_width > 0 else 50.0)
            enough_column_text = (
                prefix_span >= min_fragment_span
                and suffix_span >= min_fragment_span
                and (
                    (prefix_words >= 2 and suffix_words >= 2)
                    or (prefix_span >= strong_fragment_span and suffix_span >= strong_fragment_span)
                )
            )
            crosses_page_middle = page_width > 0 and prev_center < page_width * 0.49 < word_center
            crosses_column_boundary = (
                page_width > 0
                and prev_x1 <= page_width * 0.54
                and word_x0 >= page_width * 0.46
            )
            dominant_gap = gap >= split_gap
            gutter_gap = (crosses_page_middle or crosses_column_boundary) and enough_column_text and gap >= middle_gap
            if dominant_gap or gutter_gap:
                segments.append(current)
                current = [word]
            else:
                current.append(word)
        if current:
            segments.append(current)
        return [segment for segment in segments if segment]

    def _join_line_words(self, words: list[dict[str, Any]]) -> str:
        chunks: list[str] = []
        prev_x1: float | None = None
        prev_text = ""
        for word in words:
            text = str(word.get("text") or "").strip()
            if not text:
                continue
            x0 = self._word_float(word, "x0")
            x1 = self._word_float(word, "x1")
            if not chunks:
                chunks.append(text)
            else:
                gap = x0 - float(prev_x1 or x0)


                if re.match(r"^[,.;:!?%\])}]$", text) or gap < -1.0:
                    chunks[-1] += text
                elif prev_text.endswith(("(", "[", "{", "/", "=", "−", "-")):
                    chunks[-1] += text
                else:
                    chunks.append(text)
            prev_x1 = x1
            prev_text = text
        line = " ".join(chunks)
        line = re.sub(r"\s+([,.;:!?%\])}])", r"\1", line)
        line = re.sub(r"([([{])\s+", r"\1", line)
        line = re.sub(r"\s+([=/])\s+", r"\1", line)
        return line.strip()

    def _extract_words_layout_text(
        self,
        page: Any,
        opts: dict[str, Any],
        *,
        words: list[dict[str, Any]] | None = None,
        force_columns: bool = False,
    ) -> str:
        words = words if words is not None else self._dedupe_words(self._safe_extract_words(page))
        width = float(getattr(page, "width", 0) or 0)
        lines = self._words_to_lines(words, page_width=width)
        if not lines:
            return ""
        lines, _line_filter_meta = self._filter_lines_for_body_text(lines, opts)
        if not lines:
            return ""
        if force_columns and width > 0:
            text = self._lines_to_column_text(lines, width, height=float(getattr(page, "height", 0) or 0), opts=opts)
        else:
            text = self._render_lines_as_paragraphs(sorted(lines, key=lambda item: (item["top"], item["x0"])))
        return self._clean_page_text(text, opts)

    def _extract_columns_text(self, page: Any, opts: dict[str, Any], *, words: list[dict[str, Any]] | None = None) -> str:
        words = words if words is not None else self._dedupe_words(self._safe_extract_words(page))
        width = float(getattr(page, "width", 0) or 0)
        lines = self._words_to_lines(words, page_width=width)
        lines, _line_filter_meta = self._filter_lines_for_body_text(lines, opts)
        if lines and width > 0:
            text = self._lines_to_column_text(lines, width, height=float(getattr(page, "height", 0) or 0), opts=opts)
            text = self._clean_page_text(text, opts)
            if text:
                return text
        return self._extract_crop_columns_text(page, opts)

    def _extract_crop_columns_text(self, page: Any, opts: dict[str, Any]) -> str:
        width = float(getattr(page, "width", 0) or 0)
        height = float(getattr(page, "height", 0) or 0)
        if width <= 0 or height <= 0:
            return ""
        gutter = max(12.0, width * 0.025)
        mid = width / 2.0
        boxes = [
            (0, 0, mid - gutter / 2, height),
            (mid + gutter / 2, 0, width, height),
        ]
        parts: list[str] = []
        for box in boxes:
            try:
                crop = page.crop(box)
                text = self._safe_extract_text(crop, layout=True) or self._safe_extract_text(crop, layout=False)
                text = self._clean_page_text(text, opts)
                if text:
                    parts.append(text)
            except Exception:
                continue
        return "\n\n".join(parts).strip()

    def _lines_to_column_text(self, lines: list[dict[str, Any]], width: float, *, height: float = 0.0, opts: dict[str, Any] | None = None) -> str:
        if not lines:
            return ""
        lines, _line_filter_meta = self._filter_lines_for_body_text(lines, opts)
        if not lines:
            return ""
        footnote_lines: list[dict[str, Any]] = []
        if (opts or {}).get("detect_footnotes", True) and height > 0:
            lines, footnote_lines = self._split_footnote_lines(lines, page_height=height)

        force_columns = bool((opts or {}).get("extraction_mode") == "columns")
        paired = 0
        try:


            paired = self._count_paired_line_baselines(lines, width)
        except Exception:
            paired = 0
        profile = self._build_column_profile(lines, width, height=height, paired_baselines=paired, force=force_columns)

        sorted_lines = sorted(lines, key=lambda item: (item["top"], item["x0"]))
        result_blocks: list[str] = []
        pending: list[dict[str, Any]] = []

        def append_block(text: str) -> None:
            block = (text or "").strip()
            if block:
                result_blocks.append(block)

        def flush_pending() -> None:
            if not pending:
                return
            if not profile.get("is_two_column"):
                append_block(self._render_lines_as_paragraphs(pending))
                pending.clear()
                return

            left: list[dict[str, Any]] = []
            right: list[dict[str, Any]] = []
            center: list[dict[str, Any]] = []
            for line in pending:
                column = self._assign_line_to_column(line, profile, width)
                if column == "left":
                    left.append(line)
                elif column == "right":
                    right.append(line)
                else:
                    center.append(line)




            if len(left) < 2 or len(right) < 2:
                append_block(self._render_lines_as_paragraphs(pending))
            else:
                append_block(self._render_lines_as_paragraphs(left))
                append_block(self._render_lines_as_paragraphs(right))
                if center:
                    append_block(self._render_lines_as_paragraphs(center))
            pending.clear()

        idx = 0
        while idx < len(sorted_lines):
            line = sorted_lines[idx]




            if self._is_cross_gutter_formula_line(line, width):
                flush_pending()
                formula_group = [line]
                idx += 1
                while idx < len(sorted_lines) and self._is_formula_continuation_line(formula_group[-1], sorted_lines[idx], width):
                    formula_group.append(sorted_lines[idx])
                    idx += 1
                append_block(self._render_lines_as_paragraphs(formula_group))
                continue





            if self._is_full_width_line(line, width) or self._is_centered_layout_breaker_line(line, width):
                flush_pending()
                append_block(self._render_lines_as_paragraphs([line]))
            else:
                pending.append(line)
            idx += 1
        flush_pending()
        if footnote_lines:
            footnote_text = self._render_lines_as_paragraphs(footnote_lines)
            if footnote_text:
                result_blocks.append("Footnotes\n" + footnote_text)
        return "\n\n".join(result_blocks).strip()

    def _is_cross_gutter_formula_line(self, line: dict[str, Any], width: float) -> bool:
        if width <= 0:
            return False
        text = str(line.get("text") or "").strip()
        if not text:
            return False
        x0 = float(line.get("x0") or 0)
        x1 = float(line.get("x1") or 0)
        span = x1 - x0


        crosses_gutter = x0 < width * 0.48 and x1 > width * 0.52
        wide_enough = span > width * 0.32
        if not (crosses_gutter and wide_enough):
            return False
        math_hits = len(_MATH_SYMBOL_RE.findall(text))
        chemical_equation = "→" in text or "->" in text or ("+" in text and re.search(r"\d", text) is not None)
        compact = len(text.split()) <= 32
        return compact and (self._is_formula_like_line(text) or math_hits >= 2 or chemical_equation)

    def _is_formula_continuation_line(self, prev: dict[str, Any], current: dict[str, Any], width: float) -> bool:
        text = str(current.get("text") or "").strip()
        if not text:
            return False
        prev_bottom = float(prev.get("bottom") or prev.get("top") or 0)
        top = float(current.get("top") or 0)
        if top - prev_bottom > 28:
            return False
        if self._is_formula_like_line(text):
            return True
        if re.match(r"^[+−=]", text):
            return True
        if re.fullmatch(r"\(?\d{1,3}\)?", text):
            return True
        return False

    def _is_full_width_line(self, line: dict[str, Any], width: float) -> bool:
        if width <= 0:
            return False
        x0 = float(line.get("x0") or 0)
        x1 = float(line.get("x1") or 0)
        span = x1 - x0
        text = str(line.get("text") or "").strip()
        word_count = int(line.get("word_count") or max(1, len(text.split())))
        if span <= 0:
            return False
        crosses_middle = x0 < width * 0.40 and x1 > width * 0.60
        very_wide = span >= width * 0.68
        edge_to_edge = x0 < width * 0.18 and x1 > width * 0.82
        title_like = word_count >= 5 and span >= width * 0.56 and x0 < width * 0.25 and x1 > width * 0.55


        short_centered = word_count <= 3 and span < width * 0.50
        if short_centered:
            return False
        return very_wide or edge_to_edge or (crosses_middle and word_count >= 4) or title_like

    def _is_centered_layout_breaker_line(self, line: dict[str, Any], width: float) -> bool:
        """Detect short centered flow breakers without subject-specific words.

        Examples: numbered section headings, compact title-case headings and
        centered labels that start/stop a mixed-layout zone.  The check is
        geometry-first and deliberately excludes captions/references/formulas so
        their specialised classifiers keep ownership of those blocks.
        """
        if width <= 0:
            return False
        text = str(line.get("text") or "").strip()
        if not text:
            return False
        if _CAPTION_RE.match(text) or self._is_reference_like_line(text) or self._is_formula_like_line(text):
            return False

        x0 = self._line_float(line, "x0")
        x1 = self._line_float(line, "x1")
        span = max(0.0, x1 - x0)
        center = (x0 + x1) / 2.0
        if span <= 0 or span > width * 0.55:
            return False

        crosses_gutter = x0 <= width * 0.52 and x1 >= width * 0.48
        centered = abs(center - width / 2.0) <= max(28.0, width * 0.065)
        if not (crosses_gutter and centered):
            return False



        if _SENTENCE_END_RE.search(text):
            return False
        words = re.findall(r"[^\W\d_]+", text, flags=re.UNICODE)
        if not words or len(words) > 10:
            return False
        if re.match(r"^\d+(?:\.\d+)*\.?\s+\S+", text):
            return True
        alpha_words = [word for word in words if word]
        if not alpha_words:
            return False
        titleish = sum(1 for word in alpha_words if word[:1].isupper()) / max(1, len(alpha_words))
        all_caps = sum(1 for word in alpha_words if len(word) > 1 and word.isupper()) / max(1, len(alpha_words))
        return titleish >= 0.62 or all_caps >= 0.75

    def _count_paired_line_baselines(self, lines: list[dict[str, Any]], width: float) -> int:
        if width <= 0 or not lines:
            return 0
        heights = [
            max(1.0, self._line_float(line, "bottom", self._line_float(line, "top")) - self._line_float(line, "top"))
            for line in lines
        ]
        median_height = sorted(heights)[len(heights) // 2] if heights else 10.0
        y_tolerance = max(2.0, min(6.0, median_height * 0.45))
        ordered = sorted(lines, key=lambda line: (self._line_float(line, "top"), self._line_float(line, "x0")))
        groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        current_top: float | None = None
        for line in ordered:
            top = self._line_float(line, "top")
            if current_top is None or abs(top - current_top) <= y_tolerance:
                current.append(line)
                current_top = top if current_top is None else (current_top * (len(current) - 1) + top) / len(current)
                continue
            groups.append(current)
            current = [line]
            current_top = top
        if current:
            groups.append(current)

        paired = 0
        for group in groups:
            left = [line for line in group if self._line_center_x(line) < width * 0.48]
            right = [line for line in group if self._line_center_x(line) > width * 0.52]
            if not left or not right:
                continue
            left_end = max(self._line_float(line, "x1") for line in left)
            right_start = min(self._line_float(line, "x0") for line in right)
            if right_start - left_end >= max(8.0, width * 0.014):
                paired += 1
        return paired

    def _render_lines_as_paragraphs(self, lines: list[dict[str, Any]]) -> str:
        ordered = sorted(lines, key=lambda item: (item["top"], item["x0"]))
        if not ordered:
            return ""
        heights = [max(1.0, float(line.get("height") or (float(line.get("bottom") or 0) - float(line.get("top") or 0)) or 1.0)) for line in ordered]
        median_height = sorted(heights)[len(heights) // 2] if heights else 10.0

        paragraphs: list[list[str]] = []
        current: list[str] = []
        prev: dict[str, Any] | None = None
        for line in ordered:
            text = str(line.get("text") or "").strip()
            if not text:
                continue
            if prev is not None:
                gap = float(line.get("top") or 0) - float(prev.get("bottom") or prev.get("top") or 0)
                if self._should_start_new_paragraph(prev, line, gap, median_height):
                    if current:
                        paragraphs.append(current)
                    current = [text]
                else:
                    current.append(text)
            else:
                current.append(text)
            prev = line
        if current:
            paragraphs.append(current)

        return "\n\n".join(self._join_paragraph_lines(group) for group in paragraphs if group).strip()

    def _join_paragraph_lines(self, lines: list[str]) -> str:
        if not lines:
            return ""
        value = lines[0].strip()
        for line in lines[1:]:
            part = line.strip()
            if not part:
                continue
            if value.endswith("-"):
                value += "\n" + part
            elif self._is_formula_like_line(value) or self._is_formula_like_line(part):
                value += "\n" + part
            else:
                value += " " + part
        return re.sub(r"[ \t]+", " ", value).strip()

    def _looks_like_heading_fragment_line(self, text: str) -> bool:
        value = (text or "").strip()
        if not value:
            return False
        if self._is_heading_like_line(value):
            return True
        if _CAPTION_RE.match(value) or self._is_reference_like_line(value):
            return False
        if _SENTENCE_END_RE.search(value):
            return False
        words = re.findall(r"[^\W\d_]+", value, flags=re.UNICODE)
        if not words or len(words) > 8:
            return False
        if words[0][:1].islower():
            if len(words) <= 5 and not re.search(r"\b(the|or|with|from|where|which|that|this|these|those|therefore|because|respectively|shown|observed|results?|discussion|given|instead)\b", value, re.IGNORECASE):
                return True
            return False
        titleish = sum(1 for w in words if w[:1].isupper()) / max(1, len(words))
        return titleish >= 0.45

    def _looks_like_prose_sentence_start(self, text: str) -> bool:
        value = (text or "").strip()
        if not value:
            return False
        if self._is_formula_like_line(value) or _CAPTION_RE.match(value) or self._is_reference_like_line(value):
            return False
        words = re.findall(r"[^\W\d_]+", value, flags=re.UNICODE)
        if len(words) < 6:
            return False
        if words[0][:1].islower():
            return False
        if re.search(r"\b(the|this|these|that|given|instead|overall|results?|discussion|identifying|present|furthermore|therefore|however|meanwhile|first|second|third|for|in|on|at|to)\b", value, re.IGNORECASE):
            return True
        return bool(_SENTENCE_END_RE.search(value) or len(words) >= 10)

    def _should_start_new_paragraph(
        self,
        prev: dict[str, Any],
        current: dict[str, Any],
        gap: float,
        median_height: float,
    ) -> bool:
        prev_text = str(prev.get("text") or "").strip()
        text = str(current.get("text") or "").strip()
        if not prev_text or not text:
            return False
        if self._is_formula_like_line(prev_text) or self._is_formula_like_line(text):
            return True
        if self._is_heading_like_line(text) or _CAPTION_RE.match(text):
            return True
        if self._looks_like_heading_fragment_line(prev_text) and self._looks_like_prose_sentence_start(text):
            return True
        if _BULLET_RE.match(text):
            return True
        if gap > max(5.0, median_height * 0.85):
            return True
        indent_delta = abs(float(current.get("x0") or 0) - float(prev.get("x0") or 0))
        if indent_delta > 18 and _SENTENCE_END_RE.search(prev_text):
            return True
        return False

    def _looks_like_prose_text(self, text: str) -> bool:
        value = (text or "").strip()
        if not value:
            return False
        words = re.findall(r"[A-Za-zА-Яа-я]{3,}", value)
        if len(words) < 8:
            return False
        lexical_ratio = self._lexical_word_ratio(value)
        if lexical_ratio < 0.7:
            return False
        prose_markers = re.search(
            r"\b("
            r"the|and|with|from|where|which|that|this|these|those|"
            r"results?|discussion|conclusions?|shown|observed|measured|reported|"
            r"prepared|using|obtained|indicates|described|"
            r"представл|показан|получен|использ|содерж|наблюд|измерен|"
            r"установлен|соответств|является|были|было|после"
            r")\b",
            value,
            re.IGNORECASE,
        )
        if not prose_markers:
            return False
        math_hits = len(_MATH_SYMBOL_RE.findall(value))
        return math_hits <= 4

    def _looks_like_materials_prose_text(self, text: str) -> bool:

        return self._looks_like_prose_text(text)

    def _is_formula_like_line(self, text: str) -> bool:
        value = (text or "").strip()
        if not value:
            return False
        if self._looks_like_prose_text(value):
            return False
        math_hits = len(_MATH_SYMBOL_RE.findall(value))
        pua_hits = len(_PUA_GLYPH_RE.findall(value))
        cid_hits = len(_CID_TOKEN_RE.findall(value))
        token_count = len(value.split())
        prose_signal = re.search(r"\b(the|and|or|with|from|where|which|that|this|these|those|therefore|because|respectively|prepared|using|films?|substrates?|shown|observed|measured|reported|corresponds?|revealed|following|obtained|indicates|described|представл|показан|получен|использ|содерж|наблюд|измерен|установлен|соответств|является|были|было|после)\b", value, re.IGNORECASE)
        lexical_ratio = self._lexical_word_ratio(value)
        word_count = len(re.findall(r"[A-Za-zА-Яа-я]{3,}", value))
        if word_count >= 8 and lexical_ratio >= 0.75 and math_hits <= 2 and not (pua_hits or cid_hits):
            return False
        if prose_signal and word_count >= 12 and lexical_ratio >= 0.72 and math_hits <= 4 and token_count >= 16:
            return False
        equation_number = re.search(r"\([A-Za-z]?\d+(?:\.\d+)?\)\s*$", value)
        if (pua_hits or cid_hits) and (math_hits >= 1 or equation_number or token_count <= 24):
            return True
        if equation_number and math_hits >= 1 and token_count <= 36 and not prose_signal:
            return True
        if math_hits >= 3 and token_count <= 22:
            return True
        if len(value) <= 180 and math_hits >= 2 and not prose_signal:
            return True
        if len(value) <= 90 and math_hits >= 1 and re.search(r"[=<>≤≥±×÷→←↔]|[Α-Ωα-ω𝛼-𝜔]", value) and not prose_signal:
            return True
        return False

    def _is_heading_like_line(self, text: str) -> bool:
        value = (text or "").strip()
        if not value:
            return False
        if _SECTION_HEADING_RE.match(value):
            return True
        if len(value) <= 90 and len(value.split()) <= 10 and not _SENTENCE_END_RE.search(value):

            if re.match(r"^\d+(?:\.\d+)*\.?\s+", value):
                return True
            words = re.findall(r"[A-Za-zА-Яа-я]+", value)
            if words and sum(1 for w in words if w[:1].isupper()) / len(words) >= 0.65:
                return True
        return False

    def _looks_two_column(self, words: list[dict[str, Any]], width: float) -> bool:
        if width <= 0 or len(words) < 12:
            return False





        paired = self._count_paired_column_baselines(words, width)





        lines = self._words_to_lines(words, page_width=width)
        if len(lines) < 4:
            return paired >= 2

        line_paired = self._count_paired_line_baselines(lines, width)
        profile = self._build_column_profile(lines, width, paired_baselines=max(paired, line_paired))
        return bool(profile.get("is_two_column"))

    def _count_paired_column_baselines(self, words: list[dict[str, Any]], width: float) -> int:
        if width <= 0 or not words:
            return 0
        upright_words = [
            w for w in words
            if w.get("upright", True) is not False
            and str(w.get("direction") or "ltr").lower() in {"", "ltr"}
        ]
        if len(upright_words) < 12:
            return 0

        heights = [
            max(1.0, self._word_float(w, "bottom", self._word_float(w, "y1")) - self._word_float(w, "top", self._word_float(w, "y0")))
            for w in upright_words
        ]
        heights_sorted = sorted(heights)
        median_height = heights_sorted[len(heights_sorted) // 2] if heights_sorted else 10.0
        y_tolerance = max(2.0, min(5.5, median_height * 0.40))

        ordered = sorted(upright_words, key=lambda w: (self._word_float(w, "top", self._word_float(w, "y0")), self._word_float(w, "x0")))
        groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for word in ordered:
            if self._same_visual_baseline(word, current, y_tolerance=y_tolerance):
                current.append(word)
                continue
            groups.append(current)
            current = [word]
        if current:
            groups.append(current)

        paired = 0
        for group in groups:
            left = [w for w in group if (self._word_float(w, "x0") + self._word_float(w, "x1")) / 2 < width * 0.48]
            right = [w for w in group if (self._word_float(w, "x0") + self._word_float(w, "x1")) / 2 > width * 0.52]
            if not left or not right:
                continue
            left_end = max(self._word_float(w, "x1") for w in left)
            right_start = min(self._word_float(w, "x0") for w in right)
            gap = right_start - left_end
            left_span = left_end - min(self._word_float(w, "x0") for w in left)
            right_span = max(self._word_float(w, "x1") for w in right) - right_start
            enough_text = len(left) >= 2 and len(right) >= 2 and left_span >= width * 0.10 and right_span >= width * 0.10


            if enough_text and gap >= max(8.0, width * 0.014):
                paired += 1
        return paired



__all__ = ["PDFLayoutMixin"]
