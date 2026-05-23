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
        pages: Iterable[str],
        *,
        source: str = "pdf",
    ) -> list[PaperContentPart]:
        """Replace all existing parts with one part per extracted page/chunk."""
        await self.db.execute(delete(PaperContentPart).where(PaperContentPart.paper_id == paper_id))

        output: list[PaperContentPart] = []
        for index, raw_text in enumerate(pages, start=1):
            text = (raw_text or "").strip()
            if not text:
                continue
            part = PaperContentPart(
                paper_id=paper_id,
                part_index=len(output) + 1,
                page_start=index,
                page_end=index,
                raw_text=text,
                markdown_text=None,
                status="raw_extracted",
                error=None,
                source=source,
                raw_text_chars=len(text),
                markdown_text_chars=0,
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
