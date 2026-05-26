"""Сервис для работы с научными статьями."""


from loguru import logger
from sqlalchemy import String, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.paper import Paper as PaperModel
from shared.schemas.paper import Paper as PaperSchema
from shared.schemas.paper import PaperCreate


class PaperService:
    """Сервис для управления статьями."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _enrich_existing_paper(
        self,
        existing: PaperModel,
        paper_data: PaperCreate,
    ) -> PaperModel:
        """Аккуратно дозаполнить существующую статью новыми непустыми данными."""
        updated = False
        fields_to_fill = (
            "authors",
            "publication_date",
            "journal",
            "abstract",
            "full_text",
            "keywords",
            "url",
            "pdf_url",
            "pdf_local_path",
            "processing_error",
            "summary_ru",
            "analysis_ru",
            "translation_ru",
            "parse_confidence",
            "provenance",
            "quality_flags",
            "schema_version",
        )

        for field_name in fields_to_fill:
            current_value = getattr(existing, field_name, None)
            new_value = getattr(paper_data, field_name, None)
            if not current_value and new_value:
                setattr(existing, field_name, new_value)
                updated = True

        if existing.processing_status in {None, "pending"} and paper_data.processing_status:
            existing.processing_status = paper_data.processing_status
            updated = True

        if updated:
            await self.db.commit()
            await self.db.refresh(existing)



        setattr(existing, "_nickelfront_created", False)
        setattr(existing, "_nickelfront_updated", updated)
        return existing

    async def create_paper(self, paper_data: PaperCreate) -> PaperSchema:
        """
        Создать статью в БД.

        Args:
            paper_data: Данные статьи

        Returns:
            Созданная статья
        """

        if paper_data.doi:
            existing = await self.get_by_doi(paper_data.doi)
            if existing:
                logger.info(f"Статья с DOI {paper_data.doi} уже существует")
                return await self._enrich_existing_paper(existing, paper_data)


        if paper_data.source_id:
            existing = await self.get_by_source_id(
                paper_data.source, paper_data.source_id
            )
            if existing:
                logger.info(f"Статья {paper_data.source_id} из {paper_data.source} уже существует")
                return await self._enrich_existing_paper(existing, paper_data)


        db_paper = PaperModel(
            title=paper_data.title,
            authors=paper_data.authors,
            publication_date=paper_data.publication_date,
            journal=paper_data.journal,
            doi=paper_data.doi,
            abstract=paper_data.abstract,
            full_text=paper_data.full_text,
            keywords=paper_data.keywords,
            source=paper_data.source,
            source_id=paper_data.source_id,
            url=paper_data.url,
            pdf_url=paper_data.pdf_url,
            pdf_local_path=paper_data.pdf_local_path,
            processing_status=paper_data.processing_status or "pending",
            content_task_id=paper_data.content_task_id,
            processing_error=paper_data.processing_error,
            summary_ru=paper_data.summary_ru,
            analysis_ru=paper_data.analysis_ru,
            translation_ru=paper_data.translation_ru,
            parse_confidence=paper_data.parse_confidence,
            provenance=paper_data.provenance or {},
            quality_flags=paper_data.quality_flags or [],
            schema_version=paper_data.schema_version or "2.0",
        )

        self.db.add(db_paper)
        await self.db.commit()
        await self.db.refresh(db_paper)

        setattr(db_paper, "_nickelfront_created", True)
        setattr(db_paper, "_nickelfront_updated", False)

        logger.info(f"Создана статья: {db_paper.id} - {db_paper.title[:50]}...")
        return db_paper

    async def get_by_id(self, paper_id: int) -> PaperSchema | None:
        """Получить статью по ID."""
        result = await self.db.execute(select(PaperModel).where(PaperModel.id == paper_id))
        return result.scalar_one_or_none()

    async def get_by_doi(self, doi: str) -> PaperSchema | None:
        """Получить статью по DOI."""
        result = await self.db.execute(select(PaperModel).where(PaperModel.doi == doi))
        return result.scalar_one_or_none()

    async def get_by_source_id(
        self,
        source: str,
        source_id: str,
    ) -> PaperSchema | None:
        """Получить статью по ID в источнике."""
        result = await self.db.execute(
            select(PaperModel).where(
                (PaperModel.source == source) & (PaperModel.source_id == source_id)
            )
        )
        return result.scalar_one_or_none()

    async def search(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0,
        sources: list[str] | None = None,
        full_text_only: bool = False,
    ) -> list[PaperSchema]:
        """
        Поиск статей по названию и аннотации.

        Args:
            query: Поисковый запрос
            limit: Макс. количество результатов
            offset: Смещение

        Returns:
            Список статей
        """

        search_pattern = f"%{query}%"
        stmt = select(PaperModel).where(
            (PaperModel.title.ilike(search_pattern)) |
            (PaperModel.abstract.ilike(search_pattern)) |
            (PaperModel.keywords.cast(String).ilike(search_pattern))
        )

        if sources:
            stmt = stmt.where(PaperModel.source.in_(sources))

        if full_text_only:
            stmt = stmt.where(
                (PaperModel.full_text.is_not(None)) |
                (PaperModel.pdf_local_path.is_not(None))
            )

        result = await self.db.execute(
            stmt.order_by(PaperModel.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def get_all(
        self,
        limit: int = 10,
        offset: int = 0,
        source: str | None = None,
    ) -> list[PaperSchema]:
        """Получить список статей с пагинацией и опциональным фильтром по источнику."""
        stmt = select(PaperModel).order_by(
            PaperModel.created_at.desc(),
            PaperModel.id.desc(),
        )
        if source and source != "all":
            stmt = stmt.where(PaperModel.source == source)

        result = await self.db.execute(stmt.limit(limit).offset(offset))
        return list(result.scalars().all())

    async def get_total_count(self, source: str | None = None) -> int:
        """Получить количество статей с опциональным фильтром по источнику."""
        stmt = select(func.count()).select_from(PaperModel)
        if source and source != "all":
            stmt = stmt.where(PaperModel.source == source)

        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def get_recent_lightweight(
        self,
        limit: int = 20,
        source: str | None = None,
    ) -> list[dict]:
        """Последние статьи для dashboard без тяжёлого поля full_text."""
        stmt = select(
            PaperModel.id,
            PaperModel.title,
            PaperModel.authors,
            PaperModel.publication_date,
            PaperModel.journal,
            PaperModel.doi,
            PaperModel.abstract,
            PaperModel.keywords,
            PaperModel.source,
            PaperModel.source_id,
            PaperModel.url,
            PaperModel.pdf_url,
            PaperModel.pdf_local_path,
            PaperModel.processing_status,
            PaperModel.content_task_id,
            PaperModel.processing_error,
            PaperModel.summary_ru,
            PaperModel.analysis_ru,
            PaperModel.translation_ru,
            PaperModel.parse_confidence,
            PaperModel.provenance,
            PaperModel.quality_flags,
            PaperModel.schema_version,
            PaperModel.created_at,
            PaperModel.updated_at,
            (PaperModel.full_text.isnot(None)).label("has_full_text"),
        ).order_by(
            PaperModel.created_at.desc(),
            PaperModel.id.desc(),
        )
        if source and source != "all":
            stmt = stmt.where(PaperModel.source == source)

        result = await self.db.execute(stmt.limit(limit))
        items: list[dict] = []
        for row in result.mappings().all():
            item = dict(row)
            item["full_text"] = None
            items.append(item)
        return items

    async def update_paper(
        self,
        paper_id: int,
        **kwargs,
    ) -> PaperSchema | None:
        """
        Обновить статью.

        Args:
            paper_id: ID статьи
            **kwargs: Поля для обновления

        Returns:
            Обновлённая статья или None
        """
        paper = await self.get_by_id(paper_id)
        if not paper:
            return None

        for key, value in kwargs.items():
            if hasattr(paper, key):
                setattr(paper, key, value)

        await self.db.commit()
        await self.db.refresh(paper)
        return paper

    async def delete_paper(self, paper_id: int) -> bool:
        """
        Удалить статью.

        Args:
            paper_id: ID статьи

        Returns:
            True если удалено, False если не найдено
        """
        paper = await self.get_by_id(paper_id)
        if not paper:
            return False

        await self.db.delete(paper)
        await self.db.commit()
        return True
