"""Сервис для работы с научными статьями."""

import re
from datetime import datetime, time, timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from loguru import logger
from sqlalchemy import String, exists, func, literal, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.paper import Paper as PaperModel
from app.db.models.paper_content_part import PaperContentPart as PaperContentPartModel
from shared.schemas.paper import Paper as PaperSchema
from shared.schemas.paper import PaperCreate


PATENT_SOURCES = {"FreePatent", "GooglePatents", "PATENTSCOPE", "Rospatent"}


def _canonical_patent_identifier(value: str | None, source: str) -> str | None:
    """Normalize stable publication identifiers without fuzzy patent merging."""
    raw = (value or "").strip()
    if not raw or source not in PATENT_SOURCES:
        return None

    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        path_parts = [part for part in parsed.path.split("/") if part]
        lowered_parts = [part.lower() for part in path_parts]
        if "patents.google.com" in parsed.netloc.lower() and "patent" in lowered_parts:
            index = lowered_parts.index("patent")
            raw = path_parts[index + 1] if index + 1 < len(path_parts) else raw
        else:
            values = parse_qs(parsed.query).get("docId")
            raw = values[0] if values else (path_parts[-1] if path_parts else raw)

    raw = unquote(raw).strip()
    raw = re.sub(r"^(?:patents?|patent|doc|docs)/+", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"[\s_./\-]+", "", raw).upper()
    raw = re.sub(r"[^A-Z0-9]", "", raw)
    if raw.isdigit() and source in {"FreePatent", "Rospatent"} and len(raw) >= 5:
        return f"RU{raw}"
    if raw.startswith("RU"):
        raw = re.sub(r"^(RU\d{5,})[A-Z]\d?$", r"\1", raw)
    return raw or None



def _text_present(column):
    """SQL expression: поле заполнено непустой строкой."""
    return column.isnot(None) & (func.length(func.trim(column)) > 0)


def _paper_has_content_part_text_expr():
    """SQL EXISTS: у статьи есть сохранённые content-parts с raw или AI Markdown текстом."""
    return exists().where(
        PaperContentPartModel.paper_id == PaperModel.id,
        or_(
            _text_present(PaperContentPartModel.raw_text),
            _text_present(PaperContentPartModel.markdown_text),
        ),
    )


def _paper_has_full_text_expr():
    """Единый признак текста для списка: full_text или сохранённые parts."""
    return or_(
        _text_present(PaperModel.full_text),
        _paper_has_content_part_text_expr(),
    )



def _is_postgresql_session(db: AsyncSession) -> bool:
    try:
        return db.get_bind().dialect.name == "postgresql"
    except Exception:
        return False


def _apply_search_query_filter(stmt, normalized_query: str, *, use_postgres_fts: bool):
    """Поиск для вкладки «Статьи»: FTS через search_vector + точечные identifier fallback.

    FTS покрывает title/abstract/keywords/full_text согласно Alembic search_vector.
    ILIKE оставлен только для полей, которые плохо ложатся в ts_vector: DOI, source_id, journal, JSON authors.
    """
    search_pattern = f"%{normalized_query}%"
    identifier_filter = or_(
        PaperModel.doi.ilike(search_pattern),
        PaperModel.source_id.ilike(search_pattern),
        PaperModel.journal.ilike(search_pattern),
        PaperModel.authors.cast(String).ilike(search_pattern),
    )

    if not use_postgres_fts:
        return stmt.where(
            or_(
                PaperModel.title.ilike(search_pattern),
                PaperModel.abstract.ilike(search_pattern),
                PaperModel.keywords.cast(String).ilike(search_pattern),
                PaperModel.source.ilike(search_pattern),
                identifier_filter,
            )
        )

    ts_query = func.websearch_to_tsquery("english", normalized_query)
    return stmt.where(
        or_(
            PaperModel.search_vector.op("@@")(ts_query),
            identifier_filter,
        )
    )



def _paper_search_rank_expr(normalized_query: str, *, use_postgres_fts: bool):
    """Релевантность для вкладки «Статьи».

    В PostgreSQL используем тот же search_vector, что и фильтр. В SQLite/тестовой
    среде возвращаем стабильный 0, чтобы список оставался совместимым.
    """
    if not normalized_query or not use_postgres_fts:
        return literal(0.0)
    ts_query = func.websearch_to_tsquery("english", normalized_query)
    return func.ts_rank_cd(PaperModel.search_vector, ts_query)


def _date_start(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.min)


def _date_exclusive_end(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value + timedelta(microseconds=1)
    return datetime.combine(value + timedelta(days=1), time.min)


def _nulls_last_order(column, direction: str):
    order = column.asc() if direction == "asc" else column.desc()
    try:
        return order.nulls_last()
    except AttributeError:
        return order


def _cleanup_local_pdf_file(pdf_local_path: str | None) -> None:
    raw_path = str(pdf_local_path or "").strip()
    if not raw_path:
        return
    try:
        path = Path(raw_path).expanduser().resolve()
        pdf_root = Path(settings.resolve_path(settings.PAPER_PDF_DIR)).expanduser().resolve()
        if not path.is_file():
            return
        if pdf_root not in path.parents and path.parent != pdf_root:
            logger.warning("Skip deleting PDF outside PAPER_PDF_DIR: {}", path)
            return
        if not path.name.startswith("paper_") or path.suffix.lower() != ".pdf":
            logger.warning("Skip deleting unexpected PDF filename: {}", path)
            return
        path.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("Failed to delete local PDF file {}: {}", raw_path, exc)


def _cleanup_vector_artifacts(paper_id: int) -> None:
    try:
        from app.services.vector_service import get_vector_service

        get_vector_service().delete_paper(paper_id)
    except Exception as exc:
        logger.warning("Failed to delete paper {} from Vector/Chroma index: {}", paper_id, exc)

    try:
        from app.services.rag_vector_store import get_rag_vector_store

        rag_store = get_rag_vector_store()
        delete_paper = getattr(rag_store, "delete_paper", None)
        if callable(delete_paper):
            delete_paper(paper_id)
    except Exception as exc:
        logger.warning("Failed to delete paper {} from RAG/Chroma index: {}", paper_id, exc)


def _paper_list_columns():
    """Единая лёгкая проекция статьи для списков без тяжёлого full_text."""
    return (
        PaperModel.id,
        PaperModel.title,
        PaperModel.authors,
        PaperModel.publication_date,
        PaperModel.journal,
        PaperModel.doi,
        PaperModel.abstract,
        PaperModel.keywords,
        PaperModel.language_code,
        PaperModel.language_name,
        PaperModel.language_confidence,
        PaperModel.language_source,
        PaperModel.available_language_codes,
        PaperModel.translation_status,
        PaperModel.translation_task_id,
        PaperModel.translation_error,
        PaperModel.source,
        PaperModel.source_id,
        PaperModel.canonical_patent_id,
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
        or_(_text_present(PaperModel.pdf_url), _text_present(PaperModel.pdf_local_path)).label("has_pdf"),
        _paper_has_full_text_expr().label("has_full_text"),
    )


def _paper_list_sort_column(sort_by: str):
    if sort_by == "id":
        return PaperModel.id
    if sort_by == "authors":
        return PaperModel.authors.cast(String)
    if sort_by == "publication_date":
        return PaperModel.publication_date
    return PaperModel.created_at


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
        filled_fields: list[str] = []
        fields_to_fill = (
            "authors",
            "publication_date",
            "journal",
            "abstract",
            "full_text",
            "keywords",
            "language_code",
            "language_name",
            "language_confidence",
            "language_source",
            "available_language_codes",
            "translation_status",
            "translation_task_id",
            "translation_error",
            "url",
            "pdf_url",
            "canonical_patent_id",
            "pdf_local_path",
            "processing_error",
            "summary_ru",
            "analysis_ru",
            "translation_ru",
            "parse_confidence",
            "schema_version",
        )

        for field_name in fields_to_fill:
            current_value = getattr(existing, field_name, None)
            new_value = getattr(paper_data, field_name, None)
            if not current_value and new_value:
                setattr(existing, field_name, new_value)
                filled_fields.append(field_name)
                updated = True

        incoming_language_code = str(getattr(paper_data, "language_code", None) or "").strip().lower()
        current_language_code = str(getattr(existing, "language_code", None) or "").strip().lower()
        if incoming_language_code and (not current_language_code or current_language_code == "unknown"):
            for field_name in ("language_code", "language_name", "language_confidence", "language_source"):
                new_value = getattr(paper_data, field_name, None)
                if new_value not in (None, "") and getattr(existing, field_name, None) != new_value:
                    setattr(existing, field_name, new_value)
                    if field_name not in filled_fields:
                        filled_fields.append(field_name)
                    updated = True

        merged_provenance = dict(existing.provenance or {})
        incoming_provenance = paper_data.provenance or {}
        for field_name in filled_fields:
            origin = incoming_provenance.get(field_name)
            if origin and merged_provenance.get(field_name) != origin:
                merged_provenance[field_name] = origin
                updated = True
        for field_name, origin in incoming_provenance.items():
            if field_name not in merged_provenance and origin:
                merged_provenance[field_name] = origin
                updated = True
        if merged_provenance != (existing.provenance or {}):
            existing.provenance = merged_provenance

        merged_flags = list(dict.fromkeys([*(existing.quality_flags or []), *(paper_data.quality_flags or [])]))
        if merged_flags != (existing.quality_flags or []):
            existing.quality_flags = merged_flags
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


        patent_key = _canonical_patent_identifier(
            paper_data.source_id or paper_data.url,
            paper_data.source,
        )
        if patent_key != paper_data.canonical_patent_id:
            paper_data = paper_data.model_copy(update={"canonical_patent_id": patent_key})
        if patent_key:
            existing = await self.get_by_patent_identifier(patent_key)
            if existing:
                logger.info("Patent {} already exists in source {}", patent_key, existing.source)
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
            language_code=paper_data.language_code,
            language_name=paper_data.language_name,
            language_confidence=paper_data.language_confidence,
            language_source=paper_data.language_source,
            available_language_codes=paper_data.available_language_codes or [],
            translation_status=paper_data.translation_status,
            translation_task_id=paper_data.translation_task_id,
            translation_error=paper_data.translation_error,
            source=paper_data.source,
            source_id=paper_data.source_id,
            canonical_patent_id=paper_data.canonical_patent_id,
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
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            if paper_data.canonical_patent_id:
                existing = await self.get_by_patent_identifier(paper_data.canonical_patent_id)
                if existing:
                    return await self._enrich_existing_paper(existing, paper_data)
            if paper_data.doi:
                existing = await self.get_by_doi(paper_data.doi)
                if existing:
                    return await self._enrich_existing_paper(existing, paper_data)
            if paper_data.source_id:
                existing = await self.get_by_source_id(paper_data.source, paper_data.source_id)
                if existing:
                    return await self._enrich_existing_paper(existing, paper_data)
            raise
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

    async def get_by_patent_identifier(self, patent_key: str) -> PaperSchema | None:
        result = await self.db.execute(
            select(PaperModel).where(PaperModel.canonical_patent_id == patent_key)
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

        normalized_query = (query or "").strip()
        stmt = select(PaperModel)
        if normalized_query:
            stmt = _apply_search_query_filter(
                stmt,
                normalized_query,
                use_postgres_fts=_is_postgresql_session(self.db),
            )

        if sources:
            stmt = stmt.where(PaperModel.source.in_(sources))

        if full_text_only:
            stmt = stmt.where(_text_present(PaperModel.full_text))

        result = await self.db.execute(
            stmt.order_by(PaperModel.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    def _apply_list_filters(
        self,
        stmt,
        *,
        source: str | None = None,
        query: str | None = None,
        date_from=None,
        date_to=None,
        processing_status: str | None = None,
        translation_status: str | None = None,
        full_text_only: bool = False,
    ):
        """Общие фильтры списка статей для items и total."""
        if source and source != "all":
            stmt = stmt.where(PaperModel.source == source)

        normalized_query = (query or "").strip()
        if normalized_query:
            stmt = _apply_search_query_filter(
                stmt,
                normalized_query,
                use_postgres_fts=_is_postgresql_session(self.db),
            )

        date_from_value = _date_start(date_from)
        date_to_value = _date_exclusive_end(date_to)
        if date_from_value is not None:
            stmt = stmt.where(PaperModel.publication_date >= date_from_value)
        if date_to_value is not None:
            stmt = stmt.where(PaperModel.publication_date < date_to_value)

        status_key = (processing_status or "").strip()
        if status_key and status_key != "all":

            stmt = stmt.where(
                or_(
                    PaperModel.processing_status == status_key,
                    PaperModel.processing_status.startswith(f"{status_key}:"),
                )
            )

        translation_status_key = (translation_status or "").strip()
        if translation_status_key and translation_status_key != "all":
            stmt = stmt.where(
                or_(
                    PaperModel.translation_status == translation_status_key,
                    PaperModel.translation_status.startswith(f"{translation_status_key}:"),
                )
            )

        if full_text_only:
            stmt = stmt.where(_paper_has_full_text_expr())

        return stmt

    async def list_filtered_lightweight(
        self,
        *,
        limit: int = 10,
        offset: int = 0,
        source: str | None = None,
        query: str | None = None,
        date_from=None,
        date_to=None,
        processing_status: str | None = None,
        translation_status: str | None = None,
        full_text_only: bool = False,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
    ) -> tuple[list[dict], int]:
        """Постраничный список статей с backend-фильтрами без payload full_text."""
        base_filters = {
            "source": source,
            "query": query,
            "date_from": date_from,
            "date_to": date_to,
            "processing_status": processing_status,
            "translation_status": translation_status,
            "full_text_only": full_text_only,
        }

        count_stmt = self._apply_list_filters(
            select(func.count()).select_from(PaperModel),
            **base_filters,
        )
        total_result = await self.db.execute(count_stmt)
        total = int(total_result.scalar() or 0)

        normalized_query = (query or "").strip()
        use_postgres_fts = _is_postgresql_session(self.db)
        rank_expr = _paper_search_rank_expr(normalized_query, use_postgres_fts=use_postgres_fts).label("rank")
        direction = (sort_dir or "desc").lower()

        stmt = self._apply_list_filters(
            select(*_paper_list_columns(), rank_expr),
            **base_filters,
        )

        if sort_by == "relevance" and normalized_query:
            order_clauses = [rank_expr.desc(), _nulls_last_order(PaperModel.created_at, "desc"), PaperModel.id.desc()]
        else:
            sort_column = _paper_list_sort_column(sort_by)
            order_clauses = [_nulls_last_order(sort_column, direction), PaperModel.id.desc()]

        stmt = stmt.order_by(*order_clauses)

        result = await self.db.execute(stmt.limit(limit).offset(offset))
        items: list[dict] = []
        for row in result.mappings().all():
            item = dict(row)
            item["full_text"] = None
            item["has_pdf"] = bool(item.get("has_pdf"))
            item["has_full_text"] = bool(item.get("has_full_text"))
            item["rank"] = float(item.get("rank") or 0)
            items.append(item)
        return items, total

    async def list_ids_for_reprocess(
        self,
        *,
        limit: int = 500,
        source: str | None = None,
    ) -> list[int]:
        """Получить только ID статей для массовой постановки content-задач без загрузки full_text."""
        stmt = select(PaperModel.id).order_by(
            PaperModel.created_at.desc(),
            PaperModel.id.desc(),
        )
        if source and source != "all":
            stmt = stmt.where(PaperModel.source == source)

        result = await self.db.execute(stmt.limit(limit))
        return [int(row[0]) for row in result.all()]

    async def list_processing_status_keys(self) -> list[str]:
        """Фактически встречающиеся статусы, нормализованные до базового ключа."""
        result = await self.db.execute(select(PaperModel.processing_status).distinct())
        keys: set[str] = set()
        for value in result.scalars().all():
            key = str(value or "").strip().split(":", 1)[0]
            if key:
                keys.add(key)
        return sorted(keys)

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
        stmt = select(*_paper_list_columns()).order_by(
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
            item["has_pdf"] = bool(item.get("has_pdf"))
            item["has_full_text"] = bool(item.get("has_full_text"))
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

        pdf_local_path = getattr(paper, "pdf_local_path", None)
        await self.db.delete(paper)
        await self.db.commit()

        _cleanup_vector_artifacts(paper_id)
        _cleanup_local_pdf_file(pdf_local_path)
        return True
