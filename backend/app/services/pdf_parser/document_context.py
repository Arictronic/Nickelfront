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

class PDFDocumentContextMixin:
    """Document-level context: references continuation, headers/footers, cross-page repair."""

    def _page_has_reference_heading(self, text: str) -> bool:
        return any(_REFERENCE_HEADING_RE.match(line.strip()) for line in (text or "").splitlines() if line.strip())

    def _page_has_reference_stop_heading(self, text: str) -> bool:
        return any(_REFERENCE_STOP_HEADING_RE.match(line.strip()) for line in (text or "").splitlines() if line.strip())

    def _looks_reference_continuation_page(self, page: PdfPageExtraction) -> bool:
        text = page.text or ""
        metadata = page.metadata or {}
        if not text.strip():
            return False
        if metadata.get("figure_only_page") or metadata.get("figure_plate_page") or metadata.get("title_page"):
            return False
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return False
        reference_like = sum(1 for line in lines if self._is_reference_like_line(line))
        numbered = sum(1 for line in lines if re.match(r"^\s*(?:\[?\d{1,3}\]?\.?|\(\d{1,3}\))\s+[A-ZА-Я]", line))
        citation_density = (reference_like + numbered) / max(1, len(lines))
        has_journal_signals = sum(1 for line in lines if re.search(r"\b(?:doi|journal|phys\.?|chem\.?|mater\.?|nature|science|commun\.?|vol\.?|pp\.?|et\s+al\.|\d{4})\b", line, re.IGNORECASE))



        return bool(
            (reference_like + numbered >= 2 and has_journal_signals >= 2)
            or (reference_like + numbered >= 4 and has_journal_signals >= 2)
            or (citation_density >= 0.22 and has_journal_signals >= 2)
        )

    def _mark_reference_continuation_page(self, page: PdfPageExtraction) -> None:
        page.metadata["reference_page"] = True
        page.metadata["reference_continuation_page"] = True
        page.metadata["page_profile"] = "references"
        page.metadata["reference_line_count"] = max(
            int(page.metadata.get("reference_line_count") or 0),
            sum(1 for line in (page.text or "").splitlines() if self._is_reference_like_line(line)),
        )
        page.warnings = sorted(set([*page.warnings, "reference_page", "reference_continuation_page"]))



        try:
            final_blocks, final_blocks_meta = self._finalize_content_blocks_for_page(
                page_text=page.text,
                metadata=page.metadata,
                opts={},
                page_num=page.page_number,
            )
            page.metadata["final_content_blocks"] = final_blocks
            page.metadata["content_blocks"] = final_blocks
            page.metadata["content_blocks_sample"] = final_blocks[:40]
            page.metadata["final_content_blocks_sample"] = final_blocks[:40]
            page.metadata.update(final_blocks_meta)
        except Exception:
            pass


        try:
            page.quality_score = round(self._score_text(page.text, method=page.method, opts={}, metadata=page.metadata), 3)
        except Exception:
            pass

    def _apply_document_context_profiles(self, pages: list[PdfPageExtraction], opts: dict[str, Any] | None = None) -> list[PdfPageExtraction]:
        """Apply document-level context that a single page cannot know.

        The main use is References continuation: if page N contains the
        References/Bibliography heading, page N+1 may only contain numbered items
        and no heading. v24 marks such continuation pages as references so audit
        and RAG chunking do not treat them like low-quality body text.
        """
        opts = opts or {}
        if not opts.get("document_reference_context", True):
            return pages
        in_references = False
        for page in pages:
            text = page.text or ""
            if self._page_has_reference_stop_heading(text):
                in_references = False
            has_reference_heading = self._page_has_reference_heading(text)
            if has_reference_heading:
                in_references = True
                if not page.metadata.get("reference_page"):
                    self._mark_reference_continuation_page(page)
                    page.metadata["reference_heading_page"] = True
                else:
                    page.metadata["reference_heading_page"] = True
            elif in_references and self._looks_reference_continuation_page(page):
                self._mark_reference_continuation_page(page)
            elif in_references and page.metadata.get("page_profile") in {"figure_plate", "figure_only", "supplement", "formula_heavy"}:


                in_references = False
        return pages

    def _remove_repeating_headers_footers(self, pages: list[PdfPageExtraction]) -> list[PdfPageExtraction]:
        if len(pages) < 3:
            return pages

        def edge_lines(text: str) -> list[str]:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            return lines[:3] + lines[-3:]

        counts: dict[str, int] = {}
        originals: dict[str, str] = {}
        for page in pages:
            for line in edge_lines(page.text):
                key = self._line_key(line)
                if not key or len(key) < 5:
                    continue
                counts[key] = counts.get(key, 0) + 1
                originals[key] = line

        threshold = max(2, math.ceil(len(pages) * 0.35))
        repeated = {key for key, count in counts.items() if count >= threshold}
        if not repeated:
            return pages

        for page in pages:
            lines = page.text.splitlines()
            non_empty_indices = [idx for idx, line in enumerate(lines) if line.strip()]
            edge_index_set = set(non_empty_indices[:3] + non_empty_indices[-3:])
            new_lines: list[str] = []
            removed = 0
            for idx, line in enumerate(lines):
                stripped = line.strip()
                key = self._line_key(stripped)
                is_repeated_edge_line = key in repeated
                is_edge_page_number = idx in edge_index_set and _PAGE_NUMBER_RE.match(stripped)
                if is_repeated_edge_line or is_edge_page_number:
                    removed += 1
                    continue
                new_lines.append(line)
            if removed:
                page.text = self._normalize_paragraph_breaks("\n".join(new_lines))
                page.warnings = sorted(set([*page.warnings, "headers_footers_removed"]))
                page.metadata["removed_repeated_lines"] = removed
                page.metadata["repeated_line_keys"] = sorted(repeated)[:20]
                page.quality_score = round(self._score_text(page.text, method=page.method, opts={}, metadata=page.metadata), 3)
        return pages

    def _line_key(self, line: str) -> str:
        value = unicodedata.normalize("NFKC", line or "").casefold()
        value = re.sub(r"\d+", "#", value)
        value = re.sub(r"\s+", " ", value).strip(" -–—|·")
        if _DOI_FOOTER_RE.search(value):
            return value[:120]
        return value[:120]

    def _repair_cross_page_continuations(self, pages: list[PdfPageExtraction], opts: dict[str, Any]) -> list[PdfPageExtraction]:
        """Optional experimental cross-page repair.

        Disabled by default: production extraction keeps each PDF page independent.
        When explicitly enabled, moves paragraph continuations that begin the next
        page back to the previous page.

        Scientific two-column PDFs often split a word at the page boundary while
        captions/figures are visually placed above the continuation on the next
        page. We repair only very clear cases: previous page has a trailing
        hyphenated block near its end and one of the first next-page blocks starts
        with a lowercase continuation fragment.
        """
        if len(pages) < 2:
            return pages

        for idx in range(len(pages) - 1):
            prev_page = pages[idx]
            next_page = pages[idx + 1]
            prev_blocks = self._split_paragraph_blocks(prev_page.text)
            next_blocks = self._split_paragraph_blocks(next_page.text)
            if not prev_blocks or not next_blocks:
                continue

            hyphen_idx: int | None = None
            for block_idx in range(len(prev_blocks) - 1, max(-1, len(prev_blocks) - 6), -1):
                if re.search(r"[A-Za-zА-Яа-я]{2,}-\s*$", prev_blocks[block_idx]):
                    trailing = prev_blocks[block_idx + 1 :]


                    if all(self._is_standalone_section_marker(b) or _PAGE_NUMBER_RE.match(b.strip()) for b in trailing):
                        hyphen_idx = block_idx
                    break
            if hyphen_idx is None:
                continue

            candidate_idx: int | None = None



            for block_idx, block in enumerate(next_blocks[:6]):
                stripped = block.strip()
                if not stripped:
                    continue
                if _PAGE_NUMBER_RE.match(stripped):
                    continue
                if _CAPTION_RE.match(stripped) or self._is_heading_like_line(stripped):
                    candidate_idx = None
                    break
                if re.match(r"^[a-zа-я]{2,}\b", stripped):
                    candidate_idx = block_idx
                break
            if candidate_idx is None:
                continue

            continuation = next_blocks.pop(candidate_idx)
            suffix_match = re.match(r"^([a-zа-я]{2,})(\b.*)$", continuation.strip(), flags=re.DOTALL)
            if not suffix_match:
                continue
            suffix = suffix_match.group(1)
            rest = suffix_match.group(2).lstrip()
            merged_start = self._merge_trailing_hyphen_with_suffix(prev_blocks[hyphen_idx], suffix, "")
            if rest:
                separator = "" if rest[:1] in ".,;:!?%)]}" else " "
                prev_blocks[hyphen_idx] = f"{merged_start}{separator}{rest}".strip()
            else:
                prev_blocks[hyphen_idx] = merged_start

            prev_page.text = self._normalize_paragraph_breaks(self._join_paragraph_blocks(prev_blocks))
            next_page.text = self._normalize_paragraph_breaks(self._join_paragraph_blocks(next_blocks))
            prev_page.warnings = sorted(set([*prev_page.warnings, "cross_page_continuation_repaired"]))
            next_page.warnings = sorted(set([*next_page.warnings, "cross_page_continuation_moved"]))
            prev_page.metadata["cross_page_continuations_repaired"] = int(prev_page.metadata.get("cross_page_continuations_repaired") or 0) + 1
            next_page.metadata["cross_page_continuations_moved"] = int(next_page.metadata.get("cross_page_continuations_moved") or 0) + 1
            prev_page.metadata["final_chars"] = len(prev_page.text)
            next_page.metadata["final_chars"] = len(next_page.text)
            prev_page.metadata["quality_components"] = self._quality_components(prev_page.text, metadata=prev_page.metadata)
            next_page.metadata["quality_components"] = self._quality_components(next_page.text, metadata=next_page.metadata)
            prev_page.quality_score = round(self._score_text(prev_page.text, method=prev_page.method, opts=opts, metadata=prev_page.metadata), 3)
            next_page.quality_score = round(self._score_text(next_page.text, method=next_page.method, opts=opts, metadata=next_page.metadata), 3)
        return pages



__all__ = ["PDFDocumentContextMixin"]
