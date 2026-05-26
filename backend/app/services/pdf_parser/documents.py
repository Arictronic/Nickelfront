from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .compat import Document
from .constants import *
from .models import PdfPageExtraction


_EMBEDDING_BLOCK_TYPES = {"abstract", "heading", "body", "caption"}
_QWEN_MAIN_BLOCK_TYPES = {"abstract", "heading", "body", "caption"}
_QWEN_SEPARATE_BLOCK_TYPES = {"table", "reference", "formula"}
_DROPPED_BLOCK_TYPES = {
    "empty",
    "unknown",
    "footnote",
    "affiliation",
    "page_number",
    "arxiv_footer",
    "watermark",
    "graph_axis",
    "figure_label",
    "noise",
}
_TABLE_CAPTION_RE = re.compile(r"^\s*(?:table|табл\.?|таблица)\b", re.IGNORECASE)
_ABSTRACT_START_RE = re.compile(r"^\s*(?:abstract|аннотация|резюме)\b\s*[:.\u2013\u2014-]?", re.IGNORECASE)
_REFERENCES_START_RE = re.compile(r"^\s*(?:references|bibliography|литература|список\s+литературы)\s*$", re.IGNORECASE)
_SERVICE_MARKER_RE = re.compile(
    r"^\s*\[(?:Страница|Page)\s+\d+\]\s*$|^\s*\[(?:Formula|Table) candidate[^\]]*\]\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_STRATEGY_METADATA_KEYS = (
    "parser_mode",
    "extraction_mode",
    "extraction_strategy",
    "selected_strategy",
    "strategy_reason",
    "force_strategy",
    "ocr_mode",
    "ocr_enabled",
    "ocr_engine",
    "ocr_force",
    "ocr_used",
    "ocr_reason",
    "ai_enabled",
    "ai_mode",
    "ai_provider",
    "ai_model",
    "ai_render_dpi",
    "ai_page_image_format",
    "ai_requested",
    "ai_used",
    "ai_status",
    "ai_reason",
    "ai_fallback_used",
)



class PDFDocumentMixin:
    """Legacy and structured LangChain/RAG document projection helpers."""

    def _copy_strategy_metadata(
        self,
        *sources: dict[str, Any] | None,
        include_empty: bool = False,
    ) -> dict[str, Any]:
        copied: dict[str, Any] = {}
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key in _STRATEGY_METADATA_KEYS:
                value = source.get(key)
                if include_empty or value not in {None, ""}:
                    copied[key] = value
        return copied

    def _summarize_parser_strategy_metadata(self, pages: list[PdfPageExtraction]) -> dict[str, Any]:
        strategy_counts: dict[str, int] = {}
        selected_strategies: list[str] = []
        ocr_used_pages: list[int] = []
        ai_used_pages: list[int] = []
        ai_requested_pages: list[int] = []
        ai_fallback_pages: list[int] = []
        summary: dict[str, Any] = {
            "parser_mode": "auto",
            "selected_strategies": [],
            "selected_strategy_counts": {},
            "primary_selected_strategy": "auto",
            "ocr_used_pages": [],
            "ocr_used_page_count": 0,
            "ai_used_pages": [],
            "ai_used_page_count": 0,
            "ai_requested_pages": [],
            "ai_requested_page_count": 0,
            "ai_fallback_pages": [],
            "ai_fallback_page_count": 0,
        }

        def add_strategy(value: Any) -> None:
            strategy = str(value or "").strip().lower()
            if not strategy:
                return
            if strategy not in selected_strategies:
                selected_strategies.append(strategy)
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1

        def is_blank(value: Any) -> bool:
            return value is None or value == "" or value == [] or value == {}

        for page in pages or []:
            page_meta = page.metadata if isinstance(page.metadata, dict) else {}
            for key in (
                "parser_mode",
                "extraction_mode",
                "extraction_strategy",
                "force_strategy",
                "ocr_mode",
                "ocr_enabled",
                "ocr_engine",
                "ocr_force",
                "ai_mode",
                "ai_enabled",
                "ai_provider",
                "ai_model",
                "ai_status",
                "ai_reason",
                "ai_requested",
                "ai_fallback_used",
            ):
                if is_blank(summary.get(key)) and not is_blank(page_meta.get(key)):
                    summary[key] = page_meta.get(key)
            add_strategy(page_meta.get("selected_strategy") or page_meta.get("extraction_strategy") or page.method)
            try:
                page_no = int(page.page_number)
            except Exception:
                page_no = 0
            ocr_used = bool(
                page_meta.get("ocr_used")
                or int(page_meta.get("ocr_pages_used") or 0) > 0
                or str(page_meta.get("selected_strategy") or "").lower() == "ocr"
                or str(page.method or "").lower().startswith("ocr")
            )
            if ocr_used and page_no > 0:
                ocr_used_pages.append(page_no)
            ai_used = bool(page_meta.get("ai_used") or str(page_meta.get("selected_strategy") or "").lower() == "ai")
            ai_requested = bool(page_meta.get("ai_requested"))
            ai_fallback = bool(page_meta.get("ai_fallback_used"))
            if ai_used and page_no > 0:
                ai_used_pages.append(page_no)
            if ai_requested and page_no > 0:
                ai_requested_pages.append(page_no)
            if ai_fallback and page_no > 0:
                ai_fallback_pages.append(page_no)

        if selected_strategies:
            summary["selected_strategies"] = selected_strategies
            summary["selected_strategy_counts"] = {name: strategy_counts[name] for name in selected_strategies}
            summary["primary_selected_strategy"] = max(
                selected_strategies,
                key=lambda name: (strategy_counts.get(name, 0), -selected_strategies.index(name)),
            )
        summary["ocr_used_pages"] = ocr_used_pages
        summary["ocr_used_page_count"] = len(ocr_used_pages)
        summary["ocr_used"] = bool(ocr_used_pages)
        summary["ai_used_pages"] = ai_used_pages
        summary["ai_used_page_count"] = len(ai_used_pages)
        summary["ai_used"] = bool(ai_used_pages)
        summary["ai_requested_pages"] = ai_requested_pages
        summary["ai_requested_page_count"] = len(ai_requested_pages)
        summary["ai_requested"] = bool(ai_requested_pages)
        summary["ai_fallback_pages"] = ai_fallback_pages
        summary["ai_fallback_page_count"] = len(ai_fallback_pages)
        summary["ai_fallback_used"] = bool(ai_fallback_pages)
        summary.setdefault("ocr_mode", "auto")
        summary.setdefault("ocr_enabled", True)
        summary.setdefault("ocr_engine", "auto")
        summary.setdefault("ocr_force", False)
        summary.setdefault("force_strategy", "")
        summary.setdefault("ai_mode", "off")
        summary.setdefault("ai_enabled", False)
        summary.setdefault("ai_used", False)
        summary.setdefault("ai_status", "not_requested")
        return summary



    def _split_text_to_documents(self, full_text: str, base_metadata: dict[str, Any]) -> list[Document]:
        """Split text into section-aware LangChain documents.

        This keeps the legacy character splitter but prevents overlap from
        crossing section boundaries. It is intentionally dependency-free: exact
        tokenizer splitting can be added later without changing callers.
        """
        sections = self._split_text_into_sections(full_text)
        docs: list[Document] = []
        section_count = len(sections)
        for section_index, section in enumerate(sections):
            section_text = section.get("text", "")
            chunks = self._text_splitter.split_text(section_text)
            for local_index, chunk in enumerate(chunks):
                cleaned = self._clean_text_for_embeddings(chunk)
                if not cleaned.strip():
                    continue
                doc_metadata = dict(base_metadata)
                doc_metadata["chunk_index"] = len(docs)
                doc_metadata["section_chunk_index"] = local_index
                doc_metadata["section_index"] = section_index
                doc_metadata["section_count"] = section_count
                doc_metadata["projection_mode"] = "legacy_full_text"
                if section.get("title"):
                    doc_metadata["section_title"] = section["title"]
                docs.append(Document(page_content=cleaned, metadata=doc_metadata))
        total = len(docs)
        for i, doc in enumerate(docs):
            doc.metadata["chunk_index"] = i
            doc.metadata["total_chunks"] = total
        return docs

    def _split_text_into_sections(self, text: str) -> list[dict[str, str]]:
        value = (text or "").strip()
        if not value:
            return []
        sections: list[dict[str, str]] = []
        current_title: str | None = None
        current_lines: list[str] = []

        def flush() -> None:
            nonlocal current_lines, current_title
            body = "\n".join(current_lines).strip()
            if body:
                sections.append({"title": current_title or "", "text": body})
            current_lines = []

        for line in value.splitlines():
            stripped = line.strip()
            if stripped and (_SECTION_HEADING_RE.match(stripped) or _REFERENCE_HEADING_RE.match(stripped)):
                flush()
                current_title = stripped[:180]
                current_lines = [stripped]
                continue
            current_lines.append(line)
        flush()
        return sections or [{"title": "", "text": value}]

    def _guess_chunk_section(self, chunk: str) -> str | None:
        for line in (chunk or "").splitlines():
            stripped = line.strip()
            if stripped and _SECTION_HEADING_RE.match(stripped):
                return stripped[:160]
        return None

    def _clean_text_for_embeddings(self, text: str) -> str:



        value = text or ""
        value = _SERVICE_MARKER_RE.sub("", value)
        return self._normalize_paragraph_breaks(value)




    def _base_pdf_metadata(
        self,
        *,
        source: str,
        pages: list[PdfPageExtraction],
        file_path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build parser metadata without forcing a domain-specific document type."""
        incoming = dict(metadata or {})
        explicit_type = incoming.get("type") or incoming.get("document_type") or incoming.get("source_type")
        page_domain_profile = next(
            (
                str(page.metadata.get("domain_profile") or page.metadata.get("parser_domain_profile") or "").strip()
                for page in pages or []
                if isinstance(page.metadata, dict)
                and (page.metadata.get("domain_profile") or page.metadata.get("parser_domain_profile"))
            ),
            "",
        )
        domain_profile = str(
            incoming.get("domain_profile")
            or incoming.get("parser_domain_profile")
            or incoming.get("document_domain_profile")
            or page_domain_profile
            or "generic"
        ).strip() or "generic"
        base: dict[str, Any] = {
            "source": incoming.get("source") or source,
            "document_type": explicit_type or "pdf",
            "type": explicit_type or "pdf",
            "domain_profile": domain_profile,
            "page_count": len(pages),
            "extraction_methods": sorted({page.method for page in pages}),
            "min_quality_score": min((page.quality_score for page in pages), default=0.0),
            "avg_quality_score": round(
                sum(page.quality_score for page in pages) / max(1, len(pages)),
                3,
            ),
        }
        if file_path:
            base["file_path"] = str(Path(file_path).absolute())
        base.update(incoming)
        base.setdefault("domain_profile", domain_profile)
        return base

    def _normalize_content_part_type(self, raw_type: Any, text: str, page_metadata: dict[str, Any] | None = None) -> str:
        kind = str(raw_type or "body").strip().lower().replace("-", "_")
        value = (text or "").strip()
        page_meta = page_metadata or {}
        if kind == "figure_label":
            kind = "caption"
        if kind in {"page_header", "page_footer", "header", "footer"}:
            kind = "noise"
        if kind == "body" and value:
            if _ABSTRACT_START_RE.match(value):
                return "abstract"
            if _REFERENCES_START_RE.match(value) or bool(page_meta.get("reference_page") and self._is_reference_like_line(value)):
                return "reference"
            try:
                if self._is_heading_like_line(value):
                    return "heading"
            except Exception:
                pass
        if kind == "heading" and _REFERENCES_START_RE.match(value):
            return "reference"
        if kind not in (_EMBEDDING_BLOCK_TYPES | _QWEN_SEPARATE_BLOCK_TYPES | _DROPPED_BLOCK_TYPES):
            return "body"
        return kind

    def _clean_content_part_text(self, text: str, *, block_type: str) -> str:
        value = _SERVICE_MARKER_RE.sub("", str(text or ""))
        if block_type == "table":

            lines = [line.rstrip() for line in value.splitlines() if line.strip()]
            return "\n".join(lines).strip()
        return self._normalize_paragraph_breaks(value)

    def _is_meaningful_caption_for_embeddings(self, text: str) -> bool:
        value = (text or "").strip()
        if not value:
            return False
        words = re.findall(r"[A-Za-zА-Яа-я]{2,}", value)



        if len(words) < 8 and len(value) < 80:
            return False
        if self._looks_math_heavy_text(value):
            return False
        return True

    def _part_should_go_to_embeddings(self, part: dict[str, Any]) -> bool:
        block_type = str(part.get("type") or "").lower()
        text = str(part.get("text") or "")
        if block_type in {"abstract", "heading", "body"}:
            return bool(text.strip())
        if block_type == "caption":
            return self._is_meaningful_caption_for_embeddings(text)
        return False

    def _iter_page_content_blocks(self, page: PdfPageExtraction) -> list[dict[str, Any]]:
        """Return downstream-safe blocks, preferring synchronized final blocks.

        During old/new pipeline transitions ``content_blocks`` may still contain
        raw or stale blocks. RAG/Qwen projections must therefore prefer
        ``final_content_blocks`` explicitly and only fall back to legacy
        ``content_blocks`` when final blocks are unavailable.
        """
        meta = page.metadata or {}

        def as_block_list(value: Any) -> list[dict[str, Any]]:
            if not isinstance(value, list):
                return []
            return [block for block in value if isinstance(block, dict)]

        final_blocks = as_block_list(meta.get("final_content_blocks"))
        if final_blocks:
            return final_blocks

        final_sample = as_block_list(meta.get("final_content_blocks_sample"))
        if final_sample:
            return final_sample

        legacy_blocks = as_block_list(meta.get("content_blocks"))
        if legacy_blocks:
            return legacy_blocks

        legacy_sample = as_block_list(meta.get("content_blocks_sample"))
        if legacy_sample:
            return legacy_sample

        if page.text.strip():
            return [
                {
                    "type": "body",
                    "page": page.page_number,
                    "text": page.text.strip(),
                    "confidence": page.quality_score,
                    "projection_fallback": "page_text_without_content_blocks",
                }
            ]
        return []

    def pages_to_content_parts(
        self,
        pages: list[PdfPageExtraction],
        *,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Project final page ``content_blocks`` to ordered typed content parts.

        This is the boundary used by RAG/Qwen adapters. It intentionally does
        not read from legacy ``full_text`` while structured blocks are present.
        """
        parts: list[dict[str, Any]] = []
        order = 0
        for page in pages or []:
            page_meta = page.metadata or {}
            for local_order, block in enumerate(self._iter_page_content_blocks(page), start=1):
                raw_text = str(block.get("text") or "")
                raw_type = block.get("type") or block.get("block_type") or block.get("content_type")
                block_type = self._normalize_content_part_type(raw_type, raw_text, page_meta)
                if block_type in _DROPPED_BLOCK_TYPES:
                    continue
                text = self._clean_content_part_text(raw_text, block_type=block_type)
                if not text:
                    continue
                order += 1
                part_metadata: dict[str, Any] = {
                    "source": source or (metadata or {}).get("source"),
                    "page": int(block.get("page") or page.page_number),
                    "page_number": int(block.get("page") or page.page_number),
                    "order": order,
                    "page_order": int(block.get("order") or local_order),
                    "content_type": block_type,
                    "block_type": block_type,
                    "projection_mode": "structured_content_blocks",
                    "content_blocks_source": page_meta.get("final_content_blocks_source") or page_meta.get("content_blocks_source"),
                    "content_blocks_are_final": bool(page_meta.get("content_blocks_are_final", True)),
                    "final_content_blocks_synced": bool(page_meta.get("final_content_blocks_synced", True)),
                    "method": page.method,
                    "quality_score": page.quality_score,
                }
                part_metadata.update(
                    self._copy_strategy_metadata(
                        metadata or {},
                        page_meta,
                        block if isinstance(block, dict) else {},
                    )
                )
                for key in (
                    "bbox",
                    "confidence",
                    "table_validated",
                    "table_confidence",
                    "table_source",
                    "table_validation_reason",
                    "table_rejected_reason",
                    "projection_fallback",
                ):
                    if key in block:
                        part_metadata[key] = block.get(key)
                domain_profile = (page_meta.get("domain_profile") or (metadata or {}).get("domain_profile"))
                if domain_profile:
                    part_metadata["domain_profile"] = domain_profile
                document_type = (metadata or {}).get("document_type") or (metadata or {}).get("type")
                if document_type:
                    part_metadata["document_type"] = document_type
                if page_meta.get("page_profile"):
                    part_metadata["page_profile"] = page_meta.get("page_profile")
                if page_meta.get("reference_page"):
                    part_metadata["reference_page"] = True
                if page_meta.get("formula_heavy_page"):
                    part_metadata["formula_heavy_page"] = True
                if block_type == "caption":
                    part_metadata["caption_kind"] = "table" if _TABLE_CAPTION_RE.match(text) else "figure"
                if block_type == "table":
                    part_metadata["stored_separately"] = True
                    part_metadata["is_markdown_table"] = "|" in text and "\n" in text
                if block_type in {"reference", "formula"}:
                    part_metadata["stored_separately"] = True

                part = {
                    "type": block_type,
                    "text": text,
                    "page": part_metadata["page"],
                    "order": order,
                    "metadata": part_metadata,
                }
                part["embedding_enabled"] = self._part_should_go_to_embeddings(part)
                part["qwen_enabled"] = block_type in (_QWEN_MAIN_BLOCK_TYPES | _QWEN_SEPARATE_BLOCK_TYPES)
                parts.append(part)
        return parts

    def _content_parts_projection_summary(self, parts: list[dict[str, Any]]) -> dict[str, Any]:
        counts: dict[str, int] = {}
        embedding_counts: dict[str, int] = {}
        qwen_counts: dict[str, int] = {}
        for part in parts or []:
            kind = str(part.get("type") or "unknown")
            counts[kind] = counts.get(kind, 0) + 1
            if part.get("embedding_enabled"):
                embedding_counts[kind] = embedding_counts.get(kind, 0) + 1
            if part.get("qwen_enabled"):
                qwen_counts[kind] = qwen_counts.get(kind, 0) + 1
        return {
            "content_part_count": len(parts or []),
            "content_part_type_counts": counts,
            "embedding_content_type_counts": embedding_counts,
            "qwen_content_type_counts": qwen_counts,
            "embedding_block_types": sorted(_EMBEDDING_BLOCK_TYPES),
            "qwen_main_block_types": sorted(_QWEN_MAIN_BLOCK_TYPES),
            "qwen_separate_block_types": sorted(_QWEN_SEPARATE_BLOCK_TYPES),
            "excluded_block_types": sorted(_DROPPED_BLOCK_TYPES | {"table", "reference", "formula"}),
        }

    def content_parts_to_documents(
        self,
        content_parts: list[dict[str, Any]],
        base_metadata: dict[str, Any],
        *,
        include_captions: bool = True,
    ) -> list[Document]:
        """Convert useful semantic content parts to LangChain documents.

        Tables, references, formulas, page chrome and noise are never embedded as
        body chunks here. They remain available as structured content parts.
        """
        docs: list[Document] = []
        section_title: str | None = None
        semantic_parts = [part for part in content_parts or [] if part.get("embedding_enabled")]
        if not include_captions:
            semantic_parts = [part for part in semantic_parts if part.get("type") != "caption"]

        for part_index, part in enumerate(semantic_parts):
            block_type = str(part.get("type") or "body")
            text = self._clean_text_for_embeddings(str(part.get("text") or ""))
            if not text.strip():
                continue
            if block_type == "heading":
                section_title = text.strip()[:180]
            chunks = self._text_splitter.split_text(text)
            for local_index, chunk in enumerate(chunks):
                cleaned = self._clean_text_for_embeddings(chunk)
                if not cleaned.strip():
                    continue
                doc_metadata = dict(base_metadata)
                part_meta = dict(part.get("metadata") or {})
                doc_metadata.update(part_meta)
                doc_metadata.update(
                    {
                        "chunk_index": len(docs),
                        "part_index": part_index,
                        "part_chunk_index": local_index,
                        "content_type": block_type,
                        "block_type": block_type,
                        "projection_mode": "structured_content_blocks",
                    }
                )
                if section_title and block_type != "heading":
                    doc_metadata["section_title"] = section_title
                docs.append(Document(page_content=cleaned, metadata=doc_metadata))
        total = len(docs)
        for i, doc in enumerate(docs):
            doc.metadata["chunk_index"] = i
            doc.metadata["total_chunks"] = total
        return docs

    def content_parts_to_qwen_markdown(
        self,
        content_parts: list[dict[str, Any]],
        *,
        include_references: bool = True,
        include_formulas: bool = True,
        include_tables: bool = True,
        max_chars: int | None = None,
    ) -> str:
        """Render structured content parts for Qwen/RAG analysis prompts."""
        main_lines: list[str] = []
        table_lines: list[str] = []
        formula_lines: list[str] = []
        reference_lines: list[str] = []
        current_page: int | None = None

        def append_page_header(target: list[str], page: int | None) -> None:
            nonlocal current_page
            if page and target is main_lines and page != current_page:
                target.append(f"\n## Page {page}")
                current_page = page

        for part in content_parts or []:
            if not part.get("qwen_enabled"):
                continue
            block_type = str(part.get("type") or "body")
            text = str(part.get("text") or "").strip()
            if not text:
                continue
            page = int(part.get("page") or 0) or None
            if block_type in _QWEN_MAIN_BLOCK_TYPES:
                append_page_header(main_lines, page)
                if block_type == "heading":
                    main_lines.append(f"\n### {text}")
                elif block_type == "abstract":
                    main_lines.append(f"\n### Abstract\n{text}")
                elif block_type == "caption":
                    main_lines.append(f"\n> Caption: {text}")
                else:
                    main_lines.append(text)
            elif block_type == "table" and include_tables:
                table_lines.append(f"\n### Table, page {page or '?'} / part {part.get('order')}\n{text}")
            elif block_type == "formula" and include_formulas:
                formula_lines.append(f"\n### Formula, page {page or '?'} / part {part.get('order')}\n```text\n{text}\n```")
            elif block_type == "reference" and include_references:
                reference_lines.append(f"- p.{page or '?'} #{part.get('order')}: {text}")

        sections: list[str] = []
        main = "\n".join(line for line in main_lines if str(line).strip()).strip()
        if main:
            sections.append(main)
        if table_lines:
            sections.append("\n## Tables\n" + "\n".join(table_lines).strip())
        if formula_lines:
            sections.append("\n## Formulas\n" + "\n".join(formula_lines).strip())
        if reference_lines:
            sections.append("\n## References\n" + "\n".join(reference_lines).strip())
        rendered = "\n\n".join(section.strip() for section in sections if section.strip()).strip()
        if max_chars and max_chars > 0 and len(rendered) > max_chars:
            rendered = rendered[:max_chars].rstrip() + "\n\n[Truncated for Qwen input]"
        return rendered

    def content_parts_to_legacy_text(self, content_parts: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        current_page: int | None = None
        for part in content_parts or []:
            if str(part.get("type") or "") in _DROPPED_BLOCK_TYPES:
                continue
            page = int(part.get("page") or 0) or None
            if page and page != current_page:
                lines.append(f"[Страница {page}]")
                current_page = page
            text = str(part.get("text") or "").strip()
            if text:
                lines.append(text)
        return self._normalize_paragraph_breaks("\n\n".join(lines))


__all__ = ["PDFDocumentMixin"]
