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

class PDFTextCleaningMixin:
    """Text cleanup and PDF text-layer artifact repair."""

    def _clean_page_text(self, raw: str, opts: dict[str, Any]) -> str:
        text = unicodedata.normalize("NFKC", raw or "")
        text = text.replace("\u00ad", "")
        text = _CONTROL_RE.sub(" ", text)
        if opts.get("repair_utf8_mojibake", True):
            text = self._repair_utf8_mojibake(text)
        text = self._strip_latexit_artifacts(text)
        if opts.get("normalize_cid_glyphs", True):
            text = self._replace_cid_glyphs(text)
        if opts.get("normalize_private_use_glyphs", True):
            text = self._replace_private_use_glyphs(text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        if opts.get("merge_hyphenated_words", True):
            text = self._merge_hyphenated_linebreaks(text)
        if opts.get("normalize_math", True):
            text = self._normalize_math_duplicates(text)
        text = self._protect_formula_candidates(text) if opts.get("mark_formula_candidates", True) else text
        text = self._normalize_paragraph_breaks(text)
        return text.strip()

    def _repair_utf8_mojibake(self, text: str) -> str:
        """Repair common UTF-8/cp1251 mojibake in Russian PDF text layers."""
        value = str(text or "")
        if len(value) < 8:
            return value

        mojibake_hits = len(_MOJIBAKE_CYRILLIC_RE.findall(value))
        cyrillic_hits = len(_CYRILLIC_RE.findall(value))
        if mojibake_hits < 6 and not ("Р" in value and "С" in value):
            return value

        try:
            repaired = value.encode("cp1251", errors="strict").decode("utf-8", errors="strict")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return value

        repaired_cyrillic = len(_CYRILLIC_RE.findall(repaired))
        repaired_mojibake = len(_MOJIBAKE_CYRILLIC_RE.findall(repaired))
        if repaired_cyrillic >= max(8, cyrillic_hits + 4) and repaired_mojibake <= max(1, mojibake_hits // 4):
            return repaired
        return value

    def _merge_hyphenated_linebreaks(self, text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            left = match.group(1)
            right = match.group(2)
            citation_digits = match.group(3) or ""
            return f"{self._merge_hyphen_parts(left, right)}{citation_digits}"






        text = re.sub(
            r"(?<=\b)([A-Za-zА-Яа-я]{1,})-\n([A-Za-zА-Яа-я]{2,})(\d{0,4})(?=\b)",
            replace,
            text,
        )





        return re.sub(
            r"(?<=\b)([A-Za-zА-Яа-я]{1,})-\s*\n+\s*([a-zа-я]{2,})(\d{0,4})(?=\b)",
            replace,
            text,
        )

    def _merge_hyphen_parts(self, left: str, right: str) -> str:
        """Merge a word split by PDF line wrapping.

        The default is to remove the artificial break. A curated preserve-list
        keeps real scientific compounds such as low-carbon, water-rock,
        iron-bearing and field-scale.
        """
        left_value = left or ""
        right_value = right or ""
        left_key = left_value.casefold()
        right_key = right_value.casefold()

        if len(left_value) == 1:
            return f"{left_value}-{right_value}"
        if left_key in _REMOVE_HYPHEN_PREFIXES:
            return f"{left_value}{right_value}"
        if left_key in _PRESERVE_HYPHEN_PREFIXES or left_key.endswith(("based", "driven", "limited", "dependent", "bearing")):
            return f"{left_value}-{right_value}"
        if right_key in {"based", "driven", "limited", "dependent", "bearing", "rich", "scale", "rock", "carbon", "plate", "lift", "bore"}:
            return f"{left_value}-{right_value}"
        if len(left_key) <= 3:
            return f"{left_value}{right_value}"
        return f"{left_value}{right_value}"

    def _repair_page_flow_text(self, text: str, opts: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Final layout cleanup for text chosen by the extraction scorer.

        This stage is intentionally text-only and does not know a specific paper.
        It fixes common scientific-PDF artifacts: dangling hyphen fragments split
        by full-width blocks/section headers, common word-wrap leftovers and
        uppercase section-title continuations.
        """
        value = text or ""
        meta = {
            "dangling_hyphen_fragments": 0,
            "repaired_hyphen_fragments": 0,
            "common_hyphen_repairs": 0,
            "section_heading_repairs": 0,
            "misordered_section_marker_repairs": 0,
            "standalone_page_number_blocks_removed": 0,
            "cid_glyphs_repaired": 0,
            "private_use_glyphs_repaired": 0,
            "repaired_total": 0,
        }
        if not value.strip():
            return value, meta

        value, count = self._repair_dangling_hyphen_blocks(value)
        meta["dangling_hyphen_fragments"] += count
        meta["repaired_hyphen_fragments"] += count
        if count:



            value, extra_count = self._repair_dangling_hyphen_blocks(value)
            meta["dangling_hyphen_fragments"] += extra_count
            meta["repaired_hyphen_fragments"] += extra_count

        value, count = self._repair_misordered_section_markers(value)
        meta["misordered_section_marker_repairs"] += count

        value, count = self._repair_common_pdf_hyphenation(value)
        meta["common_hyphen_repairs"] += count

        value, count = self._repair_section_heading_continuations(value)
        meta["section_heading_repairs"] += count

        value, count = self._split_inline_section_heading_blocks(value)
        meta["section_heading_repairs"] += count

        value, count = self._remove_standalone_page_number_blocks(value)
        meta["standalone_page_number_blocks_removed"] += count

        if opts.get("normalize_cid_glyphs", True):
            before_cid = len(_CID_TOKEN_RE.findall(value))
            if before_cid:
                value = self._replace_cid_glyphs(value)
                after_cid = len(_CID_TOKEN_RE.findall(value))
                meta["cid_glyphs_repaired"] += max(0, before_cid - after_cid)

        if opts.get("normalize_private_use_glyphs", True):
            before_pua = len(_PUA_GLYPH_RE.findall(value))
            if before_pua:
                value = self._replace_private_use_glyphs(value)
                after_pua = len(_PUA_GLYPH_RE.findall(value))
                meta["private_use_glyphs_repaired"] += max(0, before_pua - after_pua)

        value = self._normalize_paragraph_breaks(value)
        meta["repaired_total"] = (
            meta["repaired_hyphen_fragments"]
            + meta["common_hyphen_repairs"]
            + meta["section_heading_repairs"]
            + meta["misordered_section_marker_repairs"]
            + meta["standalone_page_number_blocks_removed"]
            + meta["cid_glyphs_repaired"]
            + meta["private_use_glyphs_repaired"]
        )
        return value, meta

    def _split_paragraph_blocks(self, text: str) -> list[str]:
        return [block.strip() for block in re.split(r"\n\s*\n", text or "") if block.strip()]

    def _join_paragraph_blocks(self, blocks: list[str]) -> str:
        return "\n\n".join(block.strip() for block in blocks if block.strip())

    def _remove_standalone_page_number_blocks(self, text: str) -> tuple[str, int]:
        """Remove isolated page-number blocks from final page text.

        PDF page numbers are usually extracted as standalone blocks such as
        "2" or "15". They hurt RAG chunks and audit metrics. Equation labels are
        usually "(2)" and references are "2Author", so this keeps them intact.
        """
        blocks = self._split_paragraph_blocks(text)
        if not blocks:
            return text, 0
        kept: list[str] = []
        removed = 0
        for block in blocks:
            stripped = block.strip()
            if _PAGE_NUMBER_RE.fullmatch(stripped):
                removed += 1
                continue
            kept.append(block)
        if not removed:
            return text, 0
        return self._join_paragraph_blocks(kept), removed

    def _extract_short_suffix_fragment(self, block: str) -> tuple[str, str] | None:
        value = (block or "").strip()
        match = re.fullmatch(r"([a-zа-я]{2,10})([.,;:!?])?", value)
        if not match:
            return None
        suffix = match.group(1)
        punctuation = match.group(2) or ""
        if suffix.casefold() in {"the", "and", "or", "of", "in", "on", "for", "with", "from", "this", "that"}:
            return None
        return suffix, punctuation

    def _merge_trailing_hyphen_with_suffix(self, block: str, suffix: str, punctuation: str = "") -> str:
        match = re.search(r"([A-Za-zА-Яа-я]{2,})-\s*$", block or "")
        if not match:
            return block
        left = match.group(1)
        merged = self._merge_hyphen_parts(left, suffix) + punctuation
        return re.sub(r"([A-Za-zА-Яа-я]{2,})-\s*$", merged, block).strip()

    def _repair_dangling_hyphen_blocks(self, text: str) -> tuple[str, int]:
        blocks = self._split_paragraph_blocks(text)
        if len(blocks) < 2:
            return text, 0

        removed: set[int] = set()
        repairs = 0
        for idx, block in enumerate(blocks):
            if idx in removed:
                continue
            stem_match = re.search(r"([A-Za-zА-Яа-я]{2,})-\s*$", block)
            if not stem_match:
                continue
            stem = stem_match.group(1)








            for next_idx in range(idx + 1, min(len(blocks), idx + 7)):
                if next_idx in removed:
                    continue
                next_block = blocks[next_idx]
                suffix = self._extract_short_suffix_fragment(next_block)
                rest = ""
                if suffix:
                    suffix_text, punctuation = suffix
                else:


                    start_match = re.match(r"^([a-zа-я]{2,12})(.*)$", next_block.strip(), flags=re.DOTALL)
                    if not start_match or _CAPTION_RE.match(next_block) or self._is_heading_like_line(next_block):
                        continue
                    suffix_text = start_match.group(1)
                    punctuation = ""
                    rest = start_match.group(2).lstrip()

                completed = f"{stem}{suffix_text}".casefold()
                if len(stem) < 4 and next_idx != idx + 1 and completed not in _KNOWN_CROSS_BLOCK_SPLIT_WORDS:
                    continue
                if len(stem) < 4 and next_idx == idx + 1 and completed not in _KNOWN_CROSS_BLOCK_SPLIT_WORDS and stem.casefold() not in _PRESERVE_HYPHEN_PREFIXES:


                    continue

                merged = self._merge_trailing_hyphen_with_suffix(blocks[idx], suffix_text, punctuation)
                if rest:
                    separator = "" if rest[:1] in ".,;:!?%)]}" else " "
                    blocks[idx] = f"{merged}{separator}{rest}".strip()
                else:
                    blocks[idx] = merged


                removed.add(next_idx)
                for between_idx in range(idx + 1, next_idx):
                    if _PAGE_NUMBER_RE.match(blocks[between_idx].strip()):
                        removed.add(between_idx)
                repairs += 1
                break

        if not repairs:
            return text, 0
        return self._join_paragraph_blocks([block for i, block in enumerate(blocks) if i not in removed]), repairs

    def _is_standalone_section_marker(self, text: str) -> bool:
        value = (text or "").strip()
        return bool(re.fullmatch(r"(?:[IVXLCDM]+|\d+(?:\.\d+)*)\.", value))

    def _is_uppercase_heading_fragment(self, text: str) -> bool:
        value = (text or "").strip()
        if not value or len(value) > 100 or _CAPTION_RE.match(value):
            return False
        if self._is_standalone_section_marker(value):
            return False
        letters = re.findall(r"[A-Za-zА-Яа-я]", value)
        if len(letters) < 5:
            return False
        upper = sum(1 for ch in letters if ch.upper() == ch)
        return upper / max(1, len(letters)) >= 0.78 and not _SENTENCE_END_RE.search(value)

    def _repair_misordered_section_markers(self, text: str) -> tuple[str, int]:
        """Attach standalone section numbers to nearby uppercase headings.

        In two-column layouts a short marker like "III." can be assigned to the
        wrong side of a flow-breaker and appear after its title. This repair is
        generic: it only moves standalone section markers to an adjacent uppercase
        heading fragment, never to arbitrary prose.
        """
        blocks = self._split_paragraph_blocks(text)
        if len(blocks) < 2:
            return text, 0
        removed: set[int] = set()
        repairs = 0
        for idx, block in enumerate(blocks):
            if not self._is_standalone_section_marker(block):
                continue
            target_idx: int | None = None
            for lookback in range(idx - 1, max(-1, idx - 4), -1):
                if lookback in removed:
                    continue
                if self._is_uppercase_heading_fragment(blocks[lookback]):
                    target_idx = lookback
                    break
            if target_idx is None:
                continue
            if not blocks[target_idx].lstrip().startswith(block.strip()):
                blocks[target_idx] = f"{block.strip()} {blocks[target_idx].strip()}"
                removed.add(idx)
                repairs += 1
        if not repairs:
            return text, 0
        return self._join_paragraph_blocks([block for i, block in enumerate(blocks) if i not in removed]), repairs

    def _repair_common_pdf_hyphenation(self, text: str) -> tuple[str, int]:
        value = text or ""
        repairs = 0

        def repl_factory(replacement: str):
            def repl(match: re.Match[str]) -> str:
                nonlocal repairs
                repairs += 1
                original = match.group(0)
                if original[:1].isupper():
                    return replacement[:1].upper() + replacement[1:]
                return replacement
            return repl

        for broken, fixed in _COMMON_PDF_HYPHEN_REPAIRS.items():
            pattern = re.compile(r"\b" + re.escape(broken) + r"\b", re.IGNORECASE)
            value = pattern.sub(repl_factory(fixed), value)


        generic_patterns = [
            (r"\b([A-Za-z]{4,})-tion\b", r"\1tion"),
            (r"\b([A-Za-z]{4,})-sion\b", r"\1sion"),
            (r"\b([A-Za-z]{4,})-ment\b", r"\1ment"),
            (r"\b([A-Za-z]{4,})-ture\b", r"\1ture"),
            (r"\b([A-Za-z]{4,})-ity\b", r"\1ity"),
            (r"\b([A-Za-z]{4,})-ing\b", r"\1ing"),
        ]
        for pattern, replacement in generic_patterns:
            value, count = re.subn(pattern, replacement, value)
            repairs += count
        return value, repairs

    def _split_inline_section_heading_blocks(self, text: str) -> tuple[str, int]:
        """Split heading-like starts from following prose inside one block."""
        blocks = self._split_paragraph_blocks(text)
        if not blocks:
            return text, 0

        repaired: list[str] = []
        count = 0
        pattern = re.compile(
            r"^("
            r"(?:\d+(?:\.\d+)*\.?\s+)?"
            r"(?:Abstract|Keywords?|Introduction|Background|Related\s+Work|Prior\s+Work|"
            r"Methodology|Methods?|Materials?|Results?\s+and\s+Discussion|Results?|Discussion|"
            r"Implementation|Evaluation|Analysis|Case\s+Study|Conclusion|Conclusions|"
            r"Acknowledg(?:e)?ments?|Appendix|Supplementary(?:\s+Information|\s+Material)?|"
            r"[A-Z][A-Za-z0-9'’().,/+-]*(?:\s+[A-Z][A-Za-z0-9'’().,/+-]*){1,14})"
            r")\s+"
            r"(.+)$",
            re.IGNORECASE | re.DOTALL,
        )

        for block in blocks:
            value = block.strip()
            if not value or "\n\n" in value:
                repaired.append(block)
                continue
            match = pattern.match(value)
            if not match:
                repaired.append(block)
                continue
            heading = match.group(1).strip()
            rest = match.group(2).strip()
            if not rest:
                repaired.append(block)
                continue
            if len(rest.split()) < 8:
                repaired.append(block)
                continue
            if _CAPTION_RE.match(rest) or self._is_reference_like_line(rest):
                repaired.append(block)
                continue
            if not (self._is_heading_like_line(heading) or re.match(r"^\d+(?:\.\d+)*\.", heading)):
                repaired.append(block)
                continue
            repaired.append(heading)
            repaired.append(rest)
            count += 1

        if not count:
            return text, 0
        return self._join_paragraph_blocks(repaired), count

    def _repair_section_heading_continuations(self, text: str) -> tuple[str, int]:
        value = text or ""
        repairs = 0

        def join_heading(match: re.Match[str]) -> str:
            nonlocal repairs
            first = re.sub(r"\s+", " ", match.group(1).strip())
            second = re.sub(r"\s+", " ", match.group(2).strip())
            repairs += 1
            return f"{first} {second}\n\n"


        value = re.sub(
            r"\b((?:[IVXLCDM]+|\d+(?:\.\d+)*)\.\s+[A-Z][A-Z0-9 ,/()–—\-]{6,})\n\n([A-Z][A-Z0-9 ,/()–—\-]{2,40})\n\n",
            join_heading,
            value,
        )
        return value, repairs

    def _strip_latexit_artifacts(self, text: str) -> str:
        """Remove embedded latexit/base64 annotations from PDF text layers.

        Some PDFs contain invisible accessibility/math-source payloads that
        pdfplumber exposes as text. They look like ``<latexit ...>AAAB...`` or,
        after glyph duplication, ``llllaaaatttteeeexxxxiiiitttt``. Keeping them
        makes downstream search/RAG much worse, so replace affected lines with a
        compact formula marker.
        """
        value = text or ""
        if "latexit" not in value.casefold() and not _REPEATED_LATEXIT_TAG_RE.search(value):
            return value

        cleaned_lines: list[str] = []
        for line in value.splitlines():
            raw_line = line
            lower = raw_line.casefold()
            has_latexit = "latexit" in lower or _REPEATED_LATEXIT_TAG_RE.search(raw_line)
            if not has_latexit:
                cleaned_lines.append(raw_line)
                continue


            stripped = raw_line.strip()
            without_tag = _LATEXIT_TAG_RE.sub(" ", stripped)
            without_tag = _REPEATED_LATEXIT_TAG_RE.sub(" ", without_tag)
            without_tag = re.sub(r'sha1_base64\s*=\s*"[^"]*"', " ", without_tag, flags=re.IGNORECASE)
            without_tag = re.sub(r"\b[A-Za-z0-9+/=]{40,}\b", " ", without_tag)
            visible = re.sub(r"\s+", " ", without_tag).strip()

            if not visible or _BASE64ISH_RE.fullmatch(visible) or len(visible) < 8:



                continue



            cleaned_lines.append(visible)

        return "\n".join(cleaned_lines)

    def _replace_cid_glyphs(self, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            codepoint = match.group(1) or match.group(2)
            replacement = _CID_GLYPH_REPLACEMENTS.get(codepoint)
            if replacement is not None:
                return replacement



            return "□"

        return _CID_TOKEN_RE.sub(repl, text or "")

    def _replace_private_use_glyphs(self, text: str) -> str:
        """Normalize Symbol-font private-use glyphs from PDF text layers.

        This is a general cleanup for scientific PDFs generated with embedded
        Symbol fonts. Unknown PUA glyphs are collapsed to ``□`` instead of being
        left as unreadable private Unicode characters.
        """
        def repl(match: re.Match[str]) -> str:
            glyph = match.group(0)
            return _PUA_GLYPH_REPLACEMENTS.get(glyph, "□")

        return _PUA_GLYPH_RE.sub(repl, text or "")

    def _normalize_math_duplicates(self, text: str) -> str:
        value = text or ""
        greek = r"[Α-ωϑϕϵϰ-Ͽ𝛂-𝟋]"
        value = re.sub(fr"({greek})\1", r"\1", value)


        value = re.sub(r"(?<!\w)([A-Za-zΑ-ω𝛂-𝟋]{1,4}\d*(?:[=+−\-*/^][A-Za-zΑ-ω𝛂-𝟋0-9]+){1,4})\1(?!\w)", r"\1", value)
        value = re.sub(r"(?<!\w)([A-Za-zΑ-ω𝛂-𝟋]{1,4}\d*/\d+)\1(?!\w)", r"\1", value)
        value = re.sub(r"\b(U)\1\b", r"\1", value)
        return value

    def _protect_formula_candidates(self, text: str) -> str:




        lines = [line.strip() for line in (text or "").splitlines()]
        return "\n".join(lines)

    def _normalize_paragraph_breaks(self, text: str) -> str:

        lines = [line.rstrip() for line in text.splitlines()]
        cleaned: list[str] = []
        blank_seen = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if not blank_seen:
                    cleaned.append("")
                blank_seen = True
                continue
            cleaned.append(stripped)
            blank_seen = False
        return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip()



__all__ = ["PDFTextCleaningMixin"]
