"""Service for storing per-page/type-aware PDF raw text and Qwen Markdown parts."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.paper_content_part import PaperContentPart

_PAGE_BLOCK_RE = re.compile(
    r"(?:^|\n)\s*#{1,6}\s*(?:Pages|Страницы?)\s+(\d+)(?:\s*-\s*(\d+))?[^\n]*\n+",
    flags=re.IGNORECASE,
)
_SECTION_HEADING_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?\s+|[IVXLCDM]+\.\s+)?"
    r"(?:Abstract|Keywords?|Introduction|Background|Related\s+Work|Prior\s+Work|"
    r"Methodology|Methods?|Materials?|Experimental\s+Setup|Experimental\s+Procedure|Experiments?|"
    r"Implementation|Evaluation|Analysis|Results?|Discussion|Case\s+Study|Ablation|"
    r"Limitations?|Future\s+Work|Nomenclature|Conclusion|Conclusions|References|Bibliography|"
    r"Funding|Data\s+Availability|Code\s+Availability|Author\s+Contributions?|"
    r"Conflict\s+of\s+Interest|Competing\s+Interests|Ethics|"
    r"Acknowledg(?:e)?ments?|Appendix|Supplementary(?:\s+Information|\s+Material)?|Supporting\s+Information)\b",
    re.IGNORECASE,
)
_MARKER_CLEAN_RE = re.compile(r"^\s*\[(?:Formula candidate|Table candidate\s*\d*)\]\s*$", re.IGNORECASE | re.MULTILINE)
_INLINE_MARKER_CLEAN_RE = re.compile(r"\[(?:Formula candidate|Table candidate\s*\d*)\]", re.IGNORECASE)
_CID_TOKEN_RE = re.compile(r"\(cid:\d+\)|\bcid:\d+\b", re.IGNORECASE)
_PRIVATE_USE_RE = re.compile(r"[\ue000-\uf8ff]")
_LATEXIT_RE = re.compile(r"<+\s*latexit\b|l+\s*a+\s*t+\s*e+\s*x+\s*i+\s*t+", re.IGNORECASE)
_BOX_GLYPH_RE = re.compile(r"[□�]")
_REFERENCE_HEADING_LEAK_RE = re.compile(r"(?:^|\n)\s*(?:References|Bibliography|Литература|Список\s+литературы)\s*(?:\n|$)", re.IGNORECASE)
_REFERENCE_BIB_LINE_RE = re.compile(
    r"^\s*(?:\[?\d{1,3}\]?\.?|\(\d{1,3}\))\s+"
    r"(?:[A-ZА-Я][A-Za-zА-Яа-я'’.-]{2,}(?:,|\s+et\s+al\.|\s+and\s+|\s*&\s+)|"
    r"[A-ZА-Я][A-Za-zА-Яа-я'’.-]{2,}\s+[A-Z]\.)"
    r".{20,}\b(?:doi|journal|vol\.?|pp\.?|https?://|arxiv|proceedings|phys\.|sci\.|nature|materials|acta|metall|alloys?\s+compd)\b",
    re.IGNORECASE | re.MULTILINE,
)
_MATH_HEAVY_RE = re.compile(r"[=∑∫√≈≤≥±×÷→←↔∞αβγδλμσΩωπθ{}^_]|\[Formula candidate\]", re.IGNORECASE)

CONTENT_PROJECTION_VERSION = "v32_validated_table_projection"
EMBEDDABLE_CONTENT_TYPES = {"body", "caption", "heading", "abstract", "affiliation"}
QWEN_MARKDOWN_CONTENT_TYPES = {"body", "caption", "heading", "abstract", "affiliation", "table", "footnote"}
PERSIST_CONTENT_TYPES = {
    "body",
    "heading",
    "caption",
    "formula",
    "table",
    "reference",
    "footnote",
    "affiliation",
    "abstract",
}


PARSER_METADATA_KEYS = {
    "parser_mode",
    "extraction_mode",
    "extraction_strategy",
    "selected_strategy",
    "selected_strategies",
    "selected_strategy_counts",
    "primary_selected_strategy",
    "strategy_reason",
    "force_strategy",
    "ocr_mode",
    "ocr_enabled",
    "ocr_engine",
    "ocr_force",
    "ocr_used",
    "ocr_reason",
    "ocr_used_pages",
    "ocr_used_page_count",
    "ai_mode",
    "ai_enabled",
    "ai_status",
    "ai_reason",
    "ai_used",
    "ai_used_pages",
    "ai_used_page_count",
    "ai_requested",
    "ai_requested_pages",
    "ai_fallback_used",
    "ai_fallback_pages",
    "ai_external_call_performed",
    "ai_provider",
    "ai_model",
}


def _parser_metadata_from_mapping(metadata: Mapping[str, Any] | dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        return {}

    output = {key: metadata.get(key) for key in PARSER_METADATA_KEYS if key in metadata}

    page_metadata = metadata.get("page_metadata")
    if isinstance(page_metadata, Mapping):
        for key in PARSER_METADATA_KEYS:
            if key in page_metadata and key not in output:
                output[key] = page_metadata.get(key)

    return {key: value for key, value in output.items() if value is not None}


def _safe_content_type(value: object) -> str:
    text = str(value or "body").strip().lower().replace("-", "_")
    aliases = {
        "figure_label": "caption",
        "page": "body",
        "text": "body",
        "heading": "heading",
        "reference_page": "reference",
        "references": "reference",
    }
    text = aliases.get(text, text)
    if text not in PERSIST_CONTENT_TYPES:
        return "body"
    return text


def should_embed_content_type(content_type: str | None) -> bool:
    return _safe_content_type(content_type) in EMBEDDABLE_CONTENT_TYPES


def should_qwen_markdown_content_type(content_type: str | None) -> bool:
    return _safe_content_type(content_type) in QWEN_MARKDOWN_CONTENT_TYPES


def _clean_projection_text(text: str) -> str:
    """Last-mile cleanup for text sent to Qwen/embeddings.

    Parser markers and placeholder glyphs are useful in audit metadata, but they
    should not leak into LLM prompts, embeddings or paper.full_text.
    """
    value = str(text or "")
    value = _LATEXIT_RE.sub(" ", value)
    value = _CID_TOKEN_RE.sub(" ", value)
    value = _PRIVATE_USE_RE.sub(" ", value)
    value = _MARKER_CLEAN_RE.sub("", value)
    value = _INLINE_MARKER_CLEAN_RE.sub("", value)
    value = re.sub(r"(?m)^\s*[□�]+\s*$", "", value)
    value = _BOX_GLYPH_RE.sub(" ", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _clean_embedding_text(text: str) -> str:
    return _clean_projection_text(text)


def _clean_pipeline_text(text: str) -> str:
    """Clean text prepared from typed blocks before Qwen/embedding assembly."""
    return _clean_projection_text(text)


def _clean_persisted_part_text(text: str) -> str:
    """Last-chance cleanup before storing parser content_blocks in DB."""
    value = str(text or "")
    value = _LATEXIT_RE.sub(" ", value)
    value = _CID_TOKEN_RE.sub("□", value)
    value = _PRIVATE_USE_RE.sub("□", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _looks_math_heavy_text(text: str) -> bool:
    value = str(text or "")
    if not value.strip():
        return False
    math_hits = len(_MATH_HEAVY_RE.findall(value))
    pua_hits = len(_PRIVATE_USE_RE.findall(value))
    cid_hits = len(_CID_TOKEN_RE.findall(value))
    lexical_words = re.findall(r"[A-Za-zА-Яа-я]{3,}", value)
    return bool(pua_hits or cid_hits or math_hits >= 5 or (math_hits >= 2 and len(lexical_words) <= 12))



def _reference_leak_hits(text: str) -> int:
    value = str(text or "")
    return len(_REFERENCE_HEADING_LEAK_RE.findall(value)) + len(_REFERENCE_BIB_LINE_RE.findall(value))

def _projection_issue_counts(text: str, *, prefix: str) -> dict[str, int]:
    value = str(text or "")
    return {
        f"{prefix}_formula_candidate_markers": len(_INLINE_MARKER_CLEAN_RE.findall(value)),
        f"{prefix}_box_glyphs": len(_BOX_GLYPH_RE.findall(value)),
        f"{prefix}_cid_tokens": len(_CID_TOKEN_RE.findall(value)),
        f"{prefix}_pua_glyphs": len(_PRIVATE_USE_RE.findall(value)),
        f"{prefix}_latexit_tokens": len(_LATEXIT_RE.findall(value)),
        f"{prefix}_reference_hits": _reference_leak_hits(value),
    }


def _projection_has_issues(counts: dict[str, int]) -> bool:
    return any(int(value or 0) > 0 for value in counts.values())


def _content_block_texts_by_type(page_blocks: list[dict[str, Any]], content_type: str) -> list[str]:
    safe_type = _safe_content_type(content_type)
    return [
        str(block.get("text") or "").strip()
        for block in page_blocks
        if _safe_content_type(block.get("content_type")) == safe_type and str(block.get("text") or "").strip()
    ]


def _is_validated_table_block(block: dict[str, Any]) -> bool:
    """Only parser-validated table blocks may feed ``tables_text``.

    v31 showed that block.type == table was not enough: ordinary prose could be
    retyped as table after the semantic pdfplumber filter. v32 treats table as a
    structured projection only when the parser attached explicit validation
    metadata.
    """
    if _safe_content_type(block.get("content_type") or block.get("type")) != "table":
        return False
    metadata = block.get("metadata") if isinstance(block.get("metadata"), dict) else block
    return bool(metadata.get("table_validated") is True and str(metadata.get("table_source") or "") in {
        "pdfplumber_candidate",
        "markdown_table",
        "structured_labeled_table",
        "structured_material_table",
        "structured_numeric_table",
    })


def _fallback_type_for_unvalidated_table(text: str, page_profile: str | None) -> str:
    profile = str(page_profile or "").strip().lower()
    value = str(text or "")
    if profile == "references" or _reference_leak_hits(value) > 0:
        return "reference"
    if _looks_math_heavy_text(value):
        return "formula"
    if re.search(r"\b(?:Fig\.?|Figure|Table|panel|inset|shown|represents|indicates|error bars)\b", value, re.IGNORECASE):
        return "caption"
    return "body"


def get_qwen_projection_text_for_part(part: PaperContentPart) -> str:
    """Return exactly the block-aware text allowed for Qwen markdown.

    Important: for structured PDF pages an empty ``qwen_text`` is intentional
    (for example formula/reference-only pages). Do not fall back to raw_text in
    that case, otherwise the cleaned parser projections are bypassed.
    """
    metadata = getattr(part, "extraction_metadata", None) or {}
    if isinstance(metadata, dict) and (metadata.get("from_content_block") or "qwen_text" in metadata):
        return _clean_pipeline_text(str(metadata.get("qwen_text") or ""))
    return _clean_pipeline_text(getattr(part, "raw_text", None) or getattr(part, "markdown_text", None) or "")


def get_markdown_assembly_text_for_part(part: PaperContentPart) -> str:
    """Return the safe text used when rebuilding paper.full_text from parts."""
    markdown_text = (getattr(part, "markdown_text", None) or "").strip()
    if markdown_text:
        return markdown_text
    metadata = getattr(part, "extraction_metadata", None) or {}
    if isinstance(metadata, dict) and (metadata.get("from_content_block") or "qwen_text" in metadata):
        return _clean_pipeline_text(str(metadata.get("qwen_text") or ""))
    return _clean_pipeline_text(getattr(part, "raw_text", None) or "")


def _force_content_type_by_page_profile(content_type: str, text: str, page_profile: str | None) -> str:
    profile = str(page_profile or "").strip().lower()
    ctype = _safe_content_type(content_type)
    if profile == "references":
        return "reference"
    if profile == "formula_heavy" and ctype == "body" and _looks_math_heavy_text(text):
        return "formula"
    if profile in {"figure_plate", "figure_only", "figure_label_only", "supplement"} and ctype == "body":
        if re.search(r"\b(?:Fig\.?|Figure|Table|respectively|shown|indicates|represents|panel|inset|error bars)\b", text, re.IGNORECASE):
            return "caption"
    return ctype


def _detect_section_title(text: str) -> str | None:
    for line in (text or "").splitlines():
        stripped = line.strip(" #\t")
        if not stripped:
            continue
        if _SECTION_HEADING_RE.match(stripped):
            return stripped[:180]
        break
    return None


def _page_heading_label(page_start: int | None, page_end: int | None) -> str:
    if not page_start or not page_end:
        return "Страница"
    if page_start == page_end:
        return f"Страница {page_start}"
    return f"Страницы {page_start}-{page_end}"


def _part_heading(part: PaperContentPart) -> str:
    content_type = _safe_content_type(getattr(part, "content_type", "body"))
    page_label = _page_heading_label(part.page_start, part.page_end)
    section = (getattr(part, "section_title", None) or "").strip()
    type_label = content_type.replace("_", " ").title()
    if section and content_type in {"body", "heading"}:
        return f"### {page_label} · {section}"
    if content_type != "body":
        return f"### {page_label} · {type_label}"
    return f"### {page_label}"


class PaperContentPartService:
    """CRUD helpers for ``paper_content_parts``."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_parts(self, paper_id: int) -> list[PaperContentPart]:
        result = await self.db.execute(
            select(PaperContentPart)
            .where(PaperContentPart.paper_id == paper_id)
            .order_by(PaperContentPart.part_index.asc(), PaperContentPart.id.asc())
        )
        return list(result.scalars().all())

    async def list_embedding_parts(self, paper_id: int) -> list[PaperContentPart]:
        result = await self.db.execute(
            select(PaperContentPart)
            .where(
                PaperContentPart.paper_id == paper_id,
                PaperContentPart.include_in_embedding.is_(True),
            )
            .order_by(PaperContentPart.part_index.asc(), PaperContentPart.id.asc())
        )
        return list(result.scalars().all())

    async def get_part(self, paper_id: int, part_id: int) -> PaperContentPart | None:
        result = await self.db.execute(
            select(PaperContentPart).where(
                PaperContentPart.paper_id == paper_id,
                PaperContentPart.id == part_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_part_by_pages(
        self,
        paper_id: int,
        page_start: int,
        page_end: int,
    ) -> PaperContentPart | None:
        result = await self.db.execute(
            select(PaperContentPart)
            .where(
                PaperContentPart.paper_id == paper_id,
                PaperContentPart.page_start == page_start,
                PaperContentPart.page_end == page_end,
            )
            .order_by(PaperContentPart.include_in_embedding.desc(), PaperContentPart.part_index.asc())
        )
        return result.scalar_one_or_none()

    async def clear_parts(self, paper_id: int) -> int:
        """Remove all stored parser/Qwen parts for a paper.

        Reprocess chains must start from an empty part set. Otherwise a failed
        PDF download/extraction can silently feed stale page parts into Qwen,
        embeddings and assembled ``paper.full_text``.
        """
        result = await self.db.execute(delete(PaperContentPart).where(PaperContentPart.paper_id == paper_id))
        await self.db.commit()
        return int(result.rowcount or 0)

    def _normalize_page_items(self, pages: Iterable[str | dict]) -> list[dict[str, Any]]:
        page_items: list[dict[str, Any]] = []
        for idx, item in enumerate(pages, start=1):
            if isinstance(item, dict):
                page_no = int(item.get("page_number") or item.get("page") or idx)
                text = str(item.get("text") or "").strip()
                metadata = dict(item.get("metadata") or {})
                page_items.append(
                    {
                        "page_number": page_no,
                        "text": text,
                        "method": item.get("method"),
                        "quality_score": item.get("quality_score"),
                        "warnings": list(item.get("warnings") or []),
                        "metadata": metadata,
                    }
                )
            else:
                text = str(item or "").strip()
                page_items.append(
                    {
                        "page_number": idx,
                        "text": text,
                        "method": "legacy_text",
                        "quality_score": 0.35 if text else 0.0,
                        "warnings": ["legacy_text_part"],
                        "metadata": {"chars": len(text)},
                    }
                )
        return [item for item in page_items if item["text"]]

    def _build_block_rows(self, page_items: list[dict[str, Any]], *, source: str) -> list[dict[str, Any]]:
        """Build one persisted ``paper_content_parts`` row per physical PDF page.

        ``PDFParser`` may provide fine-grained ``content_blocks`` for a page
        (body/caption/table/formula/reference). UI still gets one visible row per
        page, but Qwen and embeddings now receive separate sanitized projections
        from typed blocks so formula/reference noise does not leak downstream.
        """
        rows: list[dict[str, Any]] = []
        current_section: str | None = None
        section_index = -1

        for item in page_items:
            page_no = int(item["page_number"])
            metadata = dict(item.get("metadata") or {})
            blocks = metadata.get("content_blocks") or metadata.get("content_blocks_sample") or []
            if not isinstance(blocks, list) or not blocks:
                continue

            page_profile = str(metadata.get("page_profile") or "") or None
            normalized_profile = str(page_profile or "").strip().lower()
            page_blocks: list[dict[str, Any]] = []
            qwen_text_blocks: list[str] = []
            embedding_text_blocks: list[str] = []
            content_types: list[str] = []
            projection_excluded_blocks: dict[str, int] = {}
            table_projection_excluded_blocks: dict[str, int] = {}
            table_blocks_validated = 0
            table_blocks_unvalidated = 0
            table_source_counts: dict[str, int] = {}
            warnings = sorted(set(str(w) for w in (item.get("warnings") or []) if w))

            for block in blocks:
                if not isinstance(block, dict):
                    continue

                text = _clean_persisted_part_text(str(block.get("text") or ""))
                if not text:
                    continue

                content_type = _force_content_type_by_page_profile(
                    _safe_content_type(block.get("type")),
                    text,
                    page_profile,
                )
                if content_type == "table" and not _is_validated_table_block(block):
                    table_blocks_unvalidated += 1
                    reason = str(block.get("table_rejected_reason") or "missing_validation")
                    table_projection_excluded_blocks[reason] = table_projection_excluded_blocks.get(reason, 0) + 1
                    projection_excluded_blocks["table_unvalidated"] = projection_excluded_blocks.get("table_unvalidated", 0) + 1
                    content_type = _fallback_type_for_unvalidated_table(text, page_profile)
                elif content_type == "table":
                    table_blocks_validated += 1
                    table_source = str(block.get("table_source") or "unknown")
                    table_source_counts[table_source] = table_source_counts.get(table_source, 0) + 1
                if content_type not in PERSIST_CONTENT_TYPES:
                    continue

                detected_section = _detect_section_title(text)
                if detected_section:
                    current_section = detected_section
                    section_index += 1

                content_types.append(content_type)
                qwen_text = _clean_pipeline_text(text)
                if should_qwen_markdown_content_type(content_type) and qwen_text:
                    qwen_text_blocks.append(qwen_text)
                else:
                    projection_excluded_blocks[content_type] = projection_excluded_blocks.get(content_type, 0) + 1

                embedding_text = _clean_pipeline_text(text)
                if should_embed_content_type(content_type) and embedding_text:


                    if _reference_leak_hits(embedding_text) > 0 or _looks_math_heavy_text(embedding_text) and len(re.findall(r"[A-Za-zА-Яа-я]{3,}", embedding_text)) <= 12:
                        projection_excluded_blocks[f"{content_type}_embedding_noise"] = projection_excluded_blocks.get(f"{content_type}_embedding_noise", 0) + 1
                    else:
                        embedding_text_blocks.append(embedding_text)
                else:
                    projection_excluded_blocks[f"{content_type}_embedding"] = projection_excluded_blocks.get(f"{content_type}_embedding", 0) + 1
                page_blocks.append(
                    {
                        "page": int(block.get("page") or page_no),
                        "text": text,
                        "content_type": content_type,
                        "metadata": {k: v for k, v in block.items() if k != "text"},
                    }
                )

            if not page_blocks:
                continue

            page_text = "\n\n".join(str(block["text"]).strip() for block in page_blocks if str(block.get("text") or "").strip()).strip()
            if not page_text:
                continue

            unique_content_types = sorted(set(content_types))
            page_metadata = {k: v for k, v in metadata.items() if k not in {"content_blocks", "content_blocks_sample"}}
            parser_metadata = _parser_metadata_from_mapping(page_metadata)




            if normalized_profile == "references":
                page_content_type = "reference"
            elif unique_content_types and all(content_type == "formula" for content_type in unique_content_types):
                page_content_type = "formula"
            else:
                page_content_type = "body"

            qwen_text = _clean_pipeline_text("\n\n".join(qwen_text_blocks))
            embedding_text = _clean_pipeline_text("\n\n".join(embedding_text_blocks))
            valid_table_texts = [str(block.get("text") or "").strip() for block in page_blocks if _is_validated_table_block(block)]
            tables_text = _clean_pipeline_text("\n\n".join(valid_table_texts))
            formulas_text = _clean_pipeline_text("\n\n".join(_content_block_texts_by_type(page_blocks, "formula")))
            references_text = _clean_pipeline_text("\n\n".join(_content_block_texts_by_type(page_blocks, "reference")))
            qwen_projection_counts = _projection_issue_counts(qwen_text, prefix="qwen_text")
            embedding_projection_counts = _projection_issue_counts(embedding_text, prefix="embedding_text")
            downstream_projection_issues: list[str] = []
            if _projection_has_issues(qwen_projection_counts):
                downstream_projection_issues.append("qwen_projection_leakage")
            if _projection_has_issues(embedding_projection_counts):
                downstream_projection_issues.append("embedding_projection_leakage")
            if "table" in unique_content_types and not tables_text:
                downstream_projection_issues.append("table_block_without_table_projection")
            if table_blocks_unvalidated:
                downstream_projection_issues.append("unvalidated_table_blocks_retyped")
            if "reference" in unique_content_types and embedding_text:
                downstream_projection_issues.append("reference_page_has_embedding_text")

            include_in_embedding = bool(embedding_text)
            if page_content_type in {"reference", "formula"}:
                include_in_embedding = False

            rows.append(
                {
                    "page_start": page_no,
                    "page_end": page_no,
                    "text": page_text,
                    "content_type": page_content_type,
                    "section_title": current_section,
                    "section_index": section_index if current_section else None,
                    "page_profile": page_profile,
                    "include_in_embedding": include_in_embedding,
                    "method": item.get("method") or "unknown",
                    "quality_score": item.get("quality_score"),
                    "warnings": warnings,
                    "metadata": {
                        "page_number": page_no,
                        "source": source,
                        "from_content_block": True,
                        "content_blocks_grouped": len(page_blocks),
                        "content_block_types": unique_content_types,
                        "projection_version": CONTENT_PROJECTION_VERSION,
                        "qwen_text": qwen_text,
                        "embedding_text": embedding_text if include_in_embedding else "",
                        "tables_text": tables_text,
                        "formulas_text": formulas_text,
                        "references_text_preview": references_text[:1000],
                        "qwen_text_chars": len(qwen_text),
                        "embedding_text_chars": len(embedding_text if include_in_embedding else ""),
                        "tables_text_chars": len(tables_text),
                        "formulas_text_chars": len(formulas_text),
                        "table_blocks_count": content_types.count("table"),
                        "table_blocks_validated_count": table_blocks_validated,
                        "table_blocks_unvalidated_count": table_blocks_unvalidated,
                        "table_source_counts": table_source_counts,
                        "formula_blocks_count": content_types.count("formula"),
                        "reference_blocks_count": content_types.count("reference"),
                        "projection_excluded_blocks": projection_excluded_blocks,
                        "table_projection_excluded_blocks": table_projection_excluded_blocks,
                        "downstream_projection_issues": downstream_projection_issues,
                        **parser_metadata,
                        **qwen_projection_counts,
                        **embedding_projection_counts,
                        "page_metadata": page_metadata,
                        "blocks": [
                            {
                                "page": block["page"],
                                "content_type": block["content_type"],
                                "chars": len(str(block["text"])),
                                "metadata": block["metadata"],
                            }
                            for block in page_blocks
                        ],
                    },
                }
            )

        return rows

    def _build_legacy_page_rows(self, page_items: list[dict[str, Any]], *, source: str, pages_per_part: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        pages_per_part = max(1, int(pages_per_part or 1))
        current_section: str | None = None
        section_index = -1
        for start in range(0, len(page_items), pages_per_part):
            chunk = page_items[start : start + pages_per_part]
            if not chunk:
                continue
            page_start = int(chunk[0]["page_number"])
            page_end = int(chunk[-1]["page_number"])
            text = "\n\n".join(str(item["text"]).strip() for item in chunk if str(item.get("text") or "").strip()).strip()
            if not text:
                continue
            detected_section = _detect_section_title(text)
            if detected_section:
                current_section = detected_section
                section_index += 1
            methods = [str(item.get("method") or "unknown") for item in chunk]
            scores = [float(item.get("quality_score") or 0.0) for item in chunk]
            warnings: list[str] = []
            metadata_pages: list[dict[str, Any]] = []
            for item in chunk:
                warnings.extend(str(w) for w in (item.get("warnings") or []) if w)
                metadata_pages.append(
                    {
                        "page_number": item.get("page_number"),
                        "method": item.get("method"),
                        "quality_score": item.get("quality_score"),
                        "metadata": item.get("metadata") or {},
                    }
                )
            rows.append(
                {
                    "page_start": page_start,
                    "page_end": page_end,
                    "text": text,
                    "content_type": "body",
                    "section_title": current_section,
                    "section_index": section_index if current_section else None,
                    "page_profile": None,
                    "include_in_embedding": True,
                    "method": methods[0] if len(set(methods)) == 1 else "mixed",
                    "quality_score": round(sum(scores) / max(1, len(scores)), 3) if scores else None,
                    "warnings": sorted(set(warnings)),
                    "metadata": {
                        "pages": metadata_pages,
                        "pages_per_part": len(chunk),
                        "from_content_block": False,
                        **_parser_metadata_from_mapping(metadata_pages[0].get("metadata") if metadata_pages else {}),
                    },
                }
            )
        return rows

    async def replace_raw_parts(
        self,
        paper_id: int,
        pages: Iterable[str | dict],
        *,
        source: str = "pdf",
        pages_per_part: int = 1,
    ) -> list[PaperContentPart]:
        """Replace existing parts with page-sized raw PDF chunks.

        Structured page dictionaries may include ``metadata.content_blocks`` from
        ``PDFParser``. Those parser blocks are grouped back into one persisted
        ``paper_content_parts`` row per physical page and stored in
        ``extraction_metadata`` for diagnostics. Legacy callers still get
        page-sized body rows.
        """
        await self.clear_parts(paper_id)

        page_items = self._normalize_page_items(pages)
        block_rows = self._build_block_rows(page_items, source=source)
        rows = block_rows or self._build_legacy_page_rows(page_items, source=source, pages_per_part=pages_per_part)

        output: list[PaperContentPart] = []
        for row in rows:
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            part = PaperContentPart(
                paper_id=paper_id,
                part_index=len(output) + 1,
                page_start=int(row["page_start"]),
                page_end=int(row["page_end"]),
                raw_text=text,
                markdown_text=None,
                status="raw_extracted",
                error=None,
                source=source,
                content_type=_safe_content_type(row.get("content_type")),
                section_title=row.get("section_title"),
                section_index=row.get("section_index"),
                page_profile=row.get("page_profile"),
                include_in_embedding=bool(row.get("include_in_embedding")),
                raw_text_chars=len(text),
                markdown_text_chars=0,
                extraction_method=row.get("method"),
                extraction_quality_score=row.get("quality_score"),
                extraction_warnings=sorted(set(str(w) for w in (row.get("warnings") or []) if w)),
                extraction_metadata=row.get("metadata") or {},
            )
            self.db.add(part)
            output.append(part)

        await self.db.commit()
        for part in output:
            await self.db.refresh(part)
        return output

    async def ensure_parts_from_text(
        self,
        paper_id: int,
        text: str,
        *,
        source: str = "legacy_full_text",
    ) -> list[PaperContentPart]:
        """Create parts from text only when the paper has no stored parts yet."""
        existing = await self.list_parts(paper_id)
        if existing:
            return existing
        pages = split_page_marked_text(text)
        return await self.replace_raw_parts(paper_id, pages, source=source)

    async def set_part_processing(self, part: PaperContentPart, *, task_id: str | None = None) -> PaperContentPart:
        part.status = "processing"
        part.error = None
        await self.db.commit()
        await self.db.refresh(part)
        return part

    async def set_part_markdown(
        self,
        part: PaperContentPart,
        markdown_text: str,
        *,
        qwen_model: str | None = None,
        prompt_version: str | None = None,
        increment_regeneration: bool = False,
    ) -> PaperContentPart:
        text = (markdown_text or "").strip()
        part.markdown_text = text
        part.markdown_text_chars = len(text)
        part.status = "ready" if text else "failed"
        part.error = None if text else "empty_markdown"
        part.qwen_model = qwen_model
        part.qwen_prompt_version = prompt_version
        if increment_regeneration:
            part.regeneration_count = int(part.regeneration_count or 0) + 1
        await self.db.commit()
        await self.db.refresh(part)
        return part

    async def set_part_failed(self, part: PaperContentPart, error: str) -> PaperContentPart:
        part.status = "failed"
        part.error = (error or "unknown_error")[:4000]
        await self.db.commit()
        await self.db.refresh(part)
        return part

    async def set_part_ready_without_markdown(self, part: PaperContentPart) -> PaperContentPart:
        """Mark part as processed while keeping markdown_text empty by settings policy."""
        part.status = "ready"
        part.error = None
        part.markdown_text = None
        part.markdown_text_chars = 0
        await self.db.commit()
        await self.db.refresh(part)
        return part

    async def assemble_markdown(self, paper_id: int) -> str:
        """Build a backward-compatible full markdown document from ready parts."""
        parts = await self.list_parts(paper_id)
        blocks: list[str] = []
        for part in parts:
            content = get_markdown_assembly_text_for_part(part)
            if not content:
                continue
            blocks.append(f"{_part_heading(part)}\n\n{content}".strip())
        return "\n\n".join(blocks).strip()

    async def assemble_embedding_text(self, paper_id: int, *, max_chars: int = 12000) -> str:
        """Assemble text intended for embeddings/search.

        Formula/table/reference/graph-axis content is intentionally excluded by
        ``include_in_embedding`` so embeddings focus on body/caption semantics.
        """
        parts = await self.list_embedding_parts(paper_id)
        blocks: list[str] = []
        for part in parts:
            metadata = getattr(part, "extraction_metadata", None) or {}
            block_embedding_text = ""
            if isinstance(metadata, dict):
                block_embedding_text = str(metadata.get("embedding_text") or "").strip()
            content = _clean_embedding_text(block_embedding_text or part.markdown_text or part.raw_text or "")
            if not content:
                continue
            prefix = ""
            section = (part.section_title or "").strip()
            if section:
                prefix = f"Section: {section}\n"
            blocks.append((prefix + content).strip())
            if sum(len(block) for block in blocks) >= max_chars:
                break
        return "\n\n".join(blocks).strip()[:max_chars]


def split_page_marked_text(text: str) -> list[str]:
    """Split parser output or legacy markdown into page-sized blocks.

    Supports raw PDF markers like ``[Page 1]`` / ``[Страница 1]`` and both
    legacy ``### Pages 1-1`` and current ``### Страница 1`` markdown markers.
    Falls back to conservative chunks when markers are absent.
    """
    value = (text or "").strip()
    if not value:
        return []


    matches = list(_PAGE_BLOCK_RE.finditer(value))
    if matches:
        chunks: list[str] = []
        for i, match in enumerate(matches):
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(value)
            chunk = value[start:end].strip()
            if chunk:
                chunks.append(chunk)
        if chunks:
            return chunks


    marker_re = re.compile(r"(?=\[(?:Страница|Page)\s+\d+\])", flags=re.IGNORECASE)
    chunks = [part.strip() for part in marker_re.split(value) if part and part.strip()]
    if chunks:
        return chunks


    chunk_size = 9000
    return [value[i : i + chunk_size].strip() for i in range(0, len(value), chunk_size) if value[i : i + chunk_size].strip()]
