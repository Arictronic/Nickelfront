from __future__ import annotations

import re
from typing import Any

KEYWORD_SOURCE_CONTENT_TYPES = {"body", "heading", "abstract", "caption", "table"}
KEYWORD_SOURCE_EXCLUDED_TYPES = {"reference", "footnote", "affiliation", "formula"}
KEYWORD_REFERENCE_TITLE_RE = re.compile(r"^\s*(references|bibliography|литература|список\s+литературы)\s*$", re.IGNORECASE)
KEYWORD_REFERENCE_LINE_RE = re.compile(
    r"^\s*(?:\[?\d{1,3}\]?\.?|\(\d{1,3}\))\s+.{20,}\b(?:doi|https?://|journal|vol\.?|pp\.?|arxiv|patent)\b",
    re.IGNORECASE,
)


def clean_keyword_source_block(text: str) -> str:
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    in_references = False
    for raw_line in value.split("\n"):
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            if not in_references:
                lines.append("")
            continue
        if KEYWORD_REFERENCE_TITLE_RE.match(line):
            in_references = True
            continue
        if in_references or KEYWORD_REFERENCE_LINE_RE.match(line):
            continue
        if line.startswith(("[Formula candidate", "[Table candidate")):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def keyword_source_text_for_part(part: Any) -> str:
    content_type = str(getattr(part, "content_type", "body") or "body").strip().lower().replace("-", "_")
    page_profile = str(getattr(part, "page_profile", "") or "").strip().lower()
    metadata = getattr(part, "extraction_metadata", None) or {}
    if not isinstance(metadata, dict):
        metadata = {}

    if content_type in KEYWORD_SOURCE_EXCLUDED_TYPES or page_profile in {"references", "bibliography"}:
        return ""

    if content_type == "table":
        if int(metadata.get("table_blocks_validated_count") or 0) <= 0:
            return ""
        return clean_keyword_source_block(str(metadata.get("tables_text") or ""))

    if content_type not in KEYWORD_SOURCE_CONTENT_TYPES:
        return ""

    projected = str(metadata.get("qwen_text") or "").strip()
    raw_text = str(getattr(part, "raw_text", None) or "").strip()
    text = projected or raw_text
    return clean_keyword_source_block(text)


def keywords_raw_source_from_parts(parts: list[Any]) -> str:
    """Assemble parser-origin text for exact keyword validation.

    References, footnotes, affiliations, formula-only pages and unvalidated tables
    are intentionally excluded: a keyword must exist in the document text, but
    not every token from references/PDF noise should become a candidate term.
    ``paper.full_text`` remains a fallback inside ``generate_document_keywords``
    only when no usable raw/structured part exists.
    """
    blocks: list[str] = []
    for part in parts or []:
        text = keyword_source_text_for_part(part)
        if text:
            blocks.append(text)

    return "\n\n".join(blocks).strip()
