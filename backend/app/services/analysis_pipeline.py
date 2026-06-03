import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.analysis_prompts import ANALYSIS_OUTPUT_SCHEMA, ANALYSIS_SYSTEM_PROMPT
from app.db.models.analysis_result import AnalysisResult
from app.db.models.paper import Paper
from app.db.models.paper_content_part import PaperContentPart
from app.services.qwen_client import get_qwen_client

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 50000
CONTEXT_PREVIEW_CHARS = 500


class AnalysisPipelineService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.qwen = get_qwen_client()

    async def _load_paper(self, paper_id: int) -> Paper | None:
        result = await self.db.execute(select(Paper).where(Paper.id == paper_id))
        return result.scalar_one_or_none()

    async def _load_content_parts(self, paper_id: int) -> list[PaperContentPart]:
        result = await self.db.execute(
            select(PaperContentPart)
            .where(PaperContentPart.paper_id == paper_id)
            .order_by(PaperContentPart.part_index)
        )
        return list(result.scalars().all())

    async def build_context(self, paper_id: int) -> dict:
        paper = await self._load_paper(paper_id)
        if not paper:
            return {}

        metadata = {}
        if paper.title:
            metadata["title"] = paper.title
        if paper.authors:
            metadata["authors"] = paper.authors if isinstance(paper.authors, list) else json.loads(paper.authors)
        if paper.publication_date:
            metadata["publication_date"] = str(paper.publication_date)
        if paper.journal:
            metadata["journal"] = paper.journal
        if paper.doi:
            metadata["doi"] = paper.doi

        parts = await self._load_content_parts(paper_id)
        content_pieces = []
        for part in parts:
            text = part.markdown_text or part.raw_text or ""
            if text.strip():
                content_pieces.append(text)

        combined_text = "\n\n".join(content_pieces)
        if not combined_text.strip() and paper.full_text:
            combined_text = paper.full_text

        truncated = combined_text[:MAX_CONTEXT_CHARS]
        preview = combined_text[:CONTEXT_PREVIEW_CHARS]

        return {
            "metadata": metadata,
            "content": truncated,
            "content_length": len(combined_text),
            "preview": preview,
        }

    async def run_analysis(self, paper_id: int, user_id: int | None = None) -> AnalysisResult:
        context_data = await self.build_context(paper_id)
        if not context_data:
            raise ValueError("Статья не найдена")

        entry = AnalysisResult(
            paper_id=paper_id,
            user_id=user_id,
            status="running",
        )
        self.db.add(entry)
        await self.db.commit()
        await self.db.refresh(entry)

        try:
            if not context_data.get("content"):
                entry.status = "failed"
                entry.error_message = "Не удалось собрать контекст для анализа"
                entry.completed_at = datetime.now(timezone.utc)
                await self.db.commit()
                await self.db.refresh(entry)
                return entry

            entry.context_preview = context_data.get("preview", "")[:CONTEXT_PREVIEW_CHARS]

            prompt_parts = [ANALYSIS_SYSTEM_PROMPT]
            meta = context_data.get("metadata", {})
            if meta:
                prompt_parts.append("\n## Метаданные")
                for key, value in meta.items():
                    prompt_parts.append(f"{key}: {value}")
            prompt_parts.append("\n## Текст для анализа")
            prompt_parts.append(context_data["content"])
            prompt_parts.append(f"\n## Схема ответа\n{ANALYSIS_OUTPUT_SCHEMA}")
            prompt_parts.append("\nВерни только JSON, без пояснений.")

            full_prompt = "\n".join(prompt_parts)
            qwen_response = await asyncio.to_thread(self.qwen.send_message, full_prompt)

            error = qwen_response.get("error")
            if error:
                entry.status = "failed"
                entry.error_message = str(error)[:1000]
                entry.completed_at = datetime.now(timezone.utc)
                await self.db.commit()
                await self.db.refresh(entry)
                return entry

            raw = qwen_response.get("response", "")
            entry.raw_response = raw

            try:
                parsed = json.loads(raw)
                entry.structured_result = parsed
                entry.status = "completed"
            except (json.JSONDecodeError, TypeError):
                entry.structured_result = {"raw": raw}
                entry.status = "completed"

        except Exception as exc:
            logger.exception("Ошибка при анализе статьи %s", paper_id)
            entry.status = "failed"
            entry.error_message = str(exc)[:1000]

        entry.completed_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(entry)
        return entry
