"""Сервис для работы с научными статьями."""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, String
from loguru import logger

from app.db.models.paper import Paper as PaperModel
from shared.schemas.paper import PaperCreate, Paper as PaperSchema


class PaperService:
    """Сервис для управления статьями."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_paper(self, paper_data: PaperCreate) -> PaperSchema:
        """
        Создать статью в БД.

        Args:
            paper_data: Данные статьи

        Returns:
            Созданная статья
        """
        # Проверяем, нет ли уже статьи с таким DOI
        if paper_data.doi:
            existing = await self.get_by_doi(paper_data.doi)
            if existing:
                logger.info(f"Статья с DOI {paper_data.doi} уже существует")
                return existing

        # Проверяем по source_id
        if paper_data.source_id:
            existing = await self.get_by_source_id(
                paper_data.source, paper_data.source_id
            )
            if existing:
                logger.info(f"Статья {paper_data.source_id} из {paper_data.source} уже существует")
                return existing

        # Создаём новую статью
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
        )

        self.db.add(db_paper)
        await self.db.commit()
        await self.db.refresh(db_paper)

        logger.info(f"Создана статья: {db_paper.id} - {db_paper.title[:50]}...")
        return db_paper

    async def get_by_id(self, paper_id: int) -> Optional[PaperSchema]:
        """Получить статью по ID."""
        result = await self.db.execute(select(PaperModel).where(PaperModel.id == paper_id))
        return result.scalar_one_or_none()

    async def get_by_doi(self, doi: str) -> Optional[PaperSchema]:
        """Получить статью по DOI."""
        result = await self.db.execute(select(PaperModel).where(PaperModel.doi == doi))
        return result.scalar_one_or_none()

    async def get_by_source_id(
        self,
        source: str,
        source_id: str,
    ) -> Optional[PaperSchema]:
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
        # Простой поиск по подстроке (для PostgreSQL можно использовать full-text search)
        search_pattern = f"%{query}%"
        result = await self.db.execute(
            select(PaperModel)
            .where(
                (PaperModel.title.ilike(search_pattern)) |
                (PaperModel.abstract.ilike(search_pattern)) |
                (PaperModel.keywords.cast(String).ilike(search_pattern))
            )
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_all(
        self,
        limit: int = 10,
        offset: int = 0,
    ) -> list[PaperSchema]:
        """Получить список всех статей."""
        result = await self.db.execute(
            select(PaperModel)
            .order_by(PaperModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_total_count(self) -> int:
        """Получить общее количество статей."""
        result = await self.db.execute(select(func.count()).select_from(PaperModel))
        return result.scalar() or 0

    async def update_paper(
        self,
        paper_id: int,
        **kwargs,
    ) -> Optional[PaperSchema]:
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
