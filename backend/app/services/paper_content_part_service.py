"""Service for storing per-page PDF raw text and Qwen Markdown parts."""

from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.paper_content_part import PaperContentPart

_PAGE_BLOCK_RE = re.compile(
    r"(?:^|\n)\s*#{1,6}\s*Pages\s+(\d+)\s*-\s*(\d+)\s*\n+",
    flags=re.IGNORECASE,
)


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
            .order_by(PaperContentPart.part_index.asc())
        )
        return result.scalar_one_or_none()

    async def replace_raw_parts(
        self,
        paper_id: int,
        pages: Iterable[str | dict],
        *,
        source: str = "pdf",
        pages_per_part: int = 1,
    ) -> list[PaperContentPart]:
        """Replace all existing parts with raw PDF chunks.

        ``pages`` may be either plain strings or structured page dictionaries
        returned by ``PDFParser.extract_pages_from_bytes``. Structured input
        preserves extraction method, quality score, warnings and metadata.
        """
        await self.db.execute(delete(PaperContentPart).where(PaperContentPart.paper_id == paper_id))

        page_items: list[dict] = []
        for idx, item in enumerate(pages, start=1):
            if isinstance(item, dict):
                page_no = int(item.get("page_number") or item.get("page") or idx)
                text = str(item.get("text") or "").strip()
                page_items.append(
                    {
                        "page_number": page_no,
                        "text": text,
                        "method": item.get("method"),
                        "quality_score": item.get("quality_score"),
                        "warnings": list(item.get("warnings") or []),
                        "metadata": dict(item.get("metadata") or {}),
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

        page_items = [item for item in page_items if item["text"]]
        pages_per_part = max(1, int(pages_per_part or 1))

        output: list[PaperContentPart] = []
        for start in range(0, len(page_items), pages_per_part):
            chunk = page_items[start : start + pages_per_part]
            if not chunk:
                continue
            page_start = int(chunk[0]["page_number"])
            page_end = int(chunk[-1]["page_number"])
            text = "\n\n".join(str(item["text"]).strip() for item in chunk if str(item.get("text") or "").strip()).strip()
            if not text:
                continue

            methods = [str(item.get("method") or "unknown") for item in chunk]
            scores = [float(item.get("quality_score") or 0.0) for item in chunk]
            warnings: list[str] = []
            metadata_pages: list[dict] = []
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

            method = methods[0] if len(set(methods)) == 1 else "mixed"
            quality = round(sum(scores) / max(1, len(scores)), 3) if scores else None
            part = PaperContentPart(
                paper_id=paper_id,
                part_index=len(output) + 1,
                page_start=page_start,
                page_end=page_end,
                raw_text=text,
                markdown_text=None,
                status="raw_extracted",
                error=None,
                source=source,
                raw_text_chars=len(text),
                markdown_text_chars=0,
                extraction_method=method,
                extraction_quality_score=quality,
                extraction_warnings=sorted(set(warnings)),
                extraction_metadata={"pages": metadata_pages, "pages_per_part": len(chunk)},
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
            content = (part.markdown_text or part.raw_text or "").strip()
            if not content:
                continue
            blocks.append(f"### Pages {part.page_start}-{part.page_end}\n\n{content}".strip())
        return "\n\n".join(blocks).strip()


def split_page_marked_text(text: str) -> list[str]:
    """Split parser output or legacy markdown into page-sized blocks.

    Supports both raw PDF markers like ``[Page 1]`` / ``[Страница 1]`` and the
    legacy markdown marker ``### Pages 1-1``. Falls back to conservative chunks
    when markers are absent.
    """
    value = (text or "").strip()
    if not value:
        return []

    # Legacy assembled markdown: keep each Pages block as one raw chunk but strip the marker.
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

    # Raw parser output: [Page N] or [Страница N].
    marker_re = re.compile(r"(?=\[(?:Страница|Page)\s+\d+\])", flags=re.IGNORECASE)
    chunks = [part.strip() for part in marker_re.split(value) if part and part.strip()]
    if chunks:
        return chunks

    # Fallback for unmarked fulltext.
    chunk_size = 9000
    return [value[i : i + chunk_size].strip() for i in range(0, len(value), chunk_size) if value[i : i + chunk_size].strip()]
