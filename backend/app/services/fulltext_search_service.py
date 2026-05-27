"""
Сервис полнотекстового поиска.

Использует PostgreSQL FTS:
- tsvector для индексированного текста;
- tsquery для запроса;
- GIN индекс ix_papers_search_vector;
- ts_headline для сниппетов выдачи.
"""

from typing import Any

from sqlalchemy import String, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.paper import Paper as PaperModel


class FullTextSearchService:
    """Сервис полнотекстового поиска."""

    _MODE_TO_TSQUERY = {
        "plain": "plainto_tsquery",
        "phrase": "phraseto_tsquery",
        "websearch": "websearch_to_tsquery",
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    @classmethod
    def _tsquery_function(cls, search_mode: str) -> str:
        return cls._MODE_TO_TSQUERY.get(search_mode, cls._MODE_TO_TSQUERY["websearch"])

    @staticmethod
    def _normalize_query(query: str) -> str:
        return " ".join((query or "").split())

    @staticmethod
    def _normalize_source(source: str | None) -> str | None:
        if not source or source == "all":
            return None
        return source

    @staticmethod
    def _coerce_text_list(value: Any) -> list[str]:
        semantic_keys = ("name", "displayName", "display_name", "value", "text", "title", "label")

        def flatten(item: Any) -> list[str]:
            if item is None:
                return []
            if isinstance(item, dict):
                for key in semantic_keys:
                    if key in item:
                        nested = flatten(item.get(key))
                        if nested:
                            return nested
                output: list[str] = []
                for nested_item in item.values():
                    output.extend(flatten(nested_item))
                return output
            if isinstance(item, (list, tuple, set)):
                output: list[str] = []
                for nested_item in item:
                    output.extend(flatten(nested_item))
                return output
            text_value = str(item).strip()
            return [text_value] if text_value else []

        seen: set[str] = set()
        result: list[str] = []
        for text_value in flatten(value):
            key = text_value.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(text_value)
        return result

    @staticmethod
    def _row_to_item(row: Any) -> dict[str, Any]:
        mapping = dict(row)
        authors = FullTextSearchService._coerce_text_list(mapping.get("authors"))
        keywords = FullTextSearchService._coerce_text_list(mapping.get("keywords"))
        quality_flags = FullTextSearchService._coerce_text_list(mapping.get("quality_flags"))
        provenance = mapping.get("provenance") or {}

        if not isinstance(provenance, dict):
            provenance = {}

        matched_fields = []
        if mapping.get("title_match"):
            matched_fields.append("title")
        if mapping.get("abstract_match"):
            matched_fields.append("abstract")
        if mapping.get("full_text_match"):
            matched_fields.append("full_text")

        abstract_highlight = mapping.get("abstract_highlight") or None
        full_text_highlight = mapping.get("full_text_highlight") or None
        snippet = full_text_highlight or abstract_highlight or mapping.get("abstract")

        return {
            "id": mapping.get("id"),
            "title": mapping.get("title") or "Untitled",
            "authors": authors,
            "publication_date": mapping.get("publication_date"),
            "journal": mapping.get("journal"),
            "doi": mapping.get("doi"),
            "abstract": mapping.get("abstract"),

            "full_text": None,
            "keywords": keywords,
            "source": mapping.get("source"),
            "source_id": mapping.get("source_id"),
            "canonical_patent_id": mapping.get("canonical_patent_id"),
            "url": mapping.get("url"),
            "pdf_url": mapping.get("pdf_url"),
            "pdf_local_path": mapping.get("pdf_local_path"),
            "processing_status": mapping.get("processing_status") or "pending",
            "content_task_id": mapping.get("content_task_id"),
            "processing_error": mapping.get("processing_error"),
            "summary_ru": None,
            "analysis_ru": None,
            "translation_ru": None,
            "parse_confidence": mapping.get("parse_confidence"),
            "provenance": provenance,
            "quality_flags": quality_flags,
            "schema_version": mapping.get("schema_version") or "2.0",
            "created_at": mapping.get("created_at"),
            "updated_at": mapping.get("updated_at"),
            "rank": float(mapping.get("rank") or 0),
            "snippet": snippet,
            "title_highlight": mapping.get("title_highlight") or mapping.get("title") or "Untitled",
            "abstract_highlight": abstract_highlight,
            "full_text_highlight": full_text_highlight,
            "has_pdf": bool(mapping.get("has_pdf")),
            "has_full_text": bool(mapping.get("has_full_text")),
            "full_text_indexed": bool(mapping.get("full_text_indexed")),
            "matched_fields": matched_fields,
        }

    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
        search_mode: str = "websearch",
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        """
        Полнотекстовый поиск по title/abstract/keywords/full_text.

        Возвращает лёгкие элементы выдачи: без поля full_text, но со сниппетами,
        подсветкой, рангом и признаками наличия PDF/извлечённого текста.
        """
        normalized_query = self._normalize_query(query)
        normalized_source = self._normalize_source(source)
        limit = max(1, min(100, int(limit or 20)))
        offset = max(0, int(offset or 0))

        if not normalized_query:
            return [], 0, {
                "total_matches": 0,
                "avg_relevance": 0,
                "max_relevance": 0,
            }

        tsquery_function = self._tsquery_function(search_mode)
        params = {
            "query": normalized_query,
            "source": normalized_source,
            "limit": limit,
            "offset": offset,
        }

        match_filter = "p.search_vector @@ q.query"
        source_filter = "(:source IS NULL OR p.source = :source)"

        stats_sql = text(f"""
            WITH q AS (SELECT {tsquery_function}('english', :query) AS query)
            SELECT
                COUNT(*) AS total_matches,
                COALESCE(AVG(ts_rank_cd(p.search_vector, q.query)), 0) AS avg_relevance,
                COALESCE(MAX(ts_rank_cd(p.search_vector, q.query)), 0) AS max_relevance
            FROM papers p, q
            WHERE {match_filter}
              AND {source_filter}
        """)
        stats_result = await self.db.execute(stats_sql, params)
        stats_row = stats_result.mappings().first()
        total = int(stats_row["total_matches"] or 0) if stats_row else 0
        stats = {
            "total_matches": total,
            "avg_relevance": float(stats_row["avg_relevance"] or 0) if stats_row else 0,
            "max_relevance": float(stats_row["max_relevance"] or 0) if stats_row else 0,
        }

        if total == 0:
            return [], 0, stats

        search_sql = text(f"""
            WITH q AS (SELECT {tsquery_function}('english', :query) AS query)
            SELECT
                p.id,
                p.title,
                p.authors,
                p.publication_date,
                p.journal,
                p.doi,
                p.abstract,
                p.keywords,
                p.source,
                p.source_id,
                p.canonical_patent_id,
                p.url,
                p.pdf_url,
                p.pdf_local_path,
                p.processing_status,
                p.content_task_id,
                p.processing_error,
                p.parse_confidence,
                p.provenance,
                p.quality_flags,
                p.schema_version,
                p.created_at,
                p.updated_at,
                ts_rank_cd(p.search_vector, q.query) AS rank,
                ts_headline(
                    'english',
                    COALESCE(p.title, ''),
                    q.query,
                    'StartSel=<mark>, StopSel=</mark>, MaxWords=18, MinWords=4, ShortWord=2'
                ) AS title_highlight,
                ts_headline(
                    'english',
                    COALESCE(p.abstract, ''),
                    q.query,
                    'StartSel=<mark>, StopSel=</mark>, MaxWords=36, MinWords=12, ShortWord=2'
                ) AS abstract_highlight,
                ts_headline(
                    'english',
                    COALESCE(p.full_text, ''),
                    q.query,
                    'StartSel=<mark>, StopSel=</mark>, MaxWords=46, MinWords=16, ShortWord=2, MaxFragments=2, FragmentDelimiter=…'
                ) AS full_text_highlight,
                (COALESCE(NULLIF(BTRIM(p.pdf_url), ''), NULLIF(BTRIM(p.pdf_local_path), '')) IS NOT NULL) AS has_pdf,
                (NULLIF(BTRIM(COALESCE(p.full_text, '')), '') IS NOT NULL) AS has_full_text,
                (p.search_vector IS NOT NULL AND NULLIF(BTRIM(COALESCE(p.full_text, '')), '') IS NOT NULL) AS full_text_indexed,
                (to_tsvector('english', COALESCE(p.title, '')) @@ q.query) AS title_match,
                (to_tsvector('english', COALESCE(p.abstract, '')) @@ q.query) AS abstract_match,
                (to_tsvector('english', COALESCE(p.full_text, '')) @@ q.query) AS full_text_match
            FROM papers p, q
            WHERE {match_filter}
              AND {source_filter}
            ORDER BY rank DESC, p.publication_date DESC NULLS LAST, p.id DESC
            LIMIT :limit OFFSET :offset
        """)
        result = await self.db.execute(search_sql, params)
        items = [self._row_to_item(row) for row in result.mappings().all()]

        return items, total, stats

    async def search_with_highlight(
        self,
        query: str,
        paper: PaperModel,
        max_length: int = 200,
        search_mode: str = "websearch",
    ) -> dict:
        """Получить подсветку title/abstract/full_text для одной статьи."""
        normalized_query = self._normalize_query(query)
        if not normalized_query:
            return {
                "title_highlight": paper.title,
                "abstract_highlight": paper.abstract,
                "full_text_highlight": None,
            }

        tsquery_function = self._tsquery_function(search_mode)
        highlight_sql = text(f"""
            WITH q AS (SELECT {tsquery_function}('english', :query) AS query)
            SELECT
                ts_headline(
                    'english',
                    COALESCE(p.title, ''),
                    q.query,
                    'StartSel=<mark>, StopSel=</mark>, MaxWords=18, MinWords=4, ShortWord=2'
                ) AS title_highlight,
                ts_headline(
                    'english',
                    COALESCE(p.abstract, ''),
                    q.query,
                    'StartSel=<mark>, StopSel=</mark>, MaxWords=36, MinWords=12, ShortWord=2'
                ) AS abstract_highlight,
                ts_headline(
                    'english',
                    COALESCE(p.full_text, ''),
                    q.query,
                    'StartSel=<mark>, StopSel=</mark>, MaxWords=46, MinWords=16, ShortWord=2, MaxFragments=2, FragmentDelimiter=…'
                ) AS full_text_highlight
            FROM papers p, q
            WHERE p.id = :paper_id
        """)
        result = await self.db.execute(
            highlight_sql,
            {"query": normalized_query, "paper_id": paper.id},
        )
        row = result.mappings().first()

        return {
            "title_highlight": row["title_highlight"] if row else paper.title,
            "abstract_highlight": row["abstract_highlight"] if row else paper.abstract,
            "full_text_highlight": row["full_text_highlight"] if row else None,
        }

    async def suggest(
        self,
        prefix: str,
        limit: int = 10,
    ) -> list[str]:
        """Автодополнение по title/journal/keywords."""
        normalized_prefix = self._normalize_query(prefix)
        if len(normalized_prefix) < 2:
            return []

        params = {
            "prefix_like": f"{normalized_prefix}%",
            "contains_like": f"%{normalized_prefix}%",
            "prefix": normalized_prefix,
            "limit": max(1, min(20, int(limit or 10))),
        }
        suggest_sql = text("""
            WITH candidates AS (
                SELECT p.title AS suggestion, 1 AS priority
                FROM papers p
                WHERE p.title ILIKE :contains_like

                UNION ALL

                SELECT p.journal AS suggestion, 2 AS priority
                FROM papers p
                WHERE p.journal ILIKE :contains_like

                UNION ALL

                SELECT keyword.value AS suggestion, 3 AS priority
                FROM papers p,
                     jsonb_array_elements_text(
                         CASE
                             WHEN jsonb_typeof(p.keywords::jsonb) = 'array' THEN p.keywords::jsonb
                             ELSE '[]'::jsonb
                         END
                     ) AS keyword(value)
                WHERE keyword.value ILIKE :contains_like
            )
            SELECT suggestion
            FROM candidates
            WHERE suggestion IS NOT NULL AND BTRIM(suggestion) <> ''
            GROUP BY suggestion
            ORDER BY
                CASE WHEN suggestion ILIKE :prefix_like THEN 0 ELSE 1 END,
                MIN(priority),
                similarity(LOWER(suggestion), LOWER(:prefix)) DESC,
                suggestion
            LIMIT :limit
        """)
        result = await self.db.execute(suggest_sql, params)
        return [row["suggestion"] for row in result.mappings().all()]

    async def search_keywords(
        self,
        keywords: list[str],
        match_all: bool = True,
        limit: int = 20,
    ) -> list[PaperModel]:
        """Поиск по ключевым словам."""

        conditions = []
        for keyword in keywords:
            conditions.append(
                PaperModel.keywords.cast(String).ilike(f"%{keyword}%")
            )

        if match_all:
            from sqlalchemy import and_
            filter_condition = and_(*conditions)
        else:
            from sqlalchemy import or_
            filter_condition = or_(*conditions)

        search_query = select(PaperModel).where(
            filter_condition
        ).order_by(
            PaperModel.publication_date.desc()
        ).limit(limit)

        result = await self.db.execute(search_query)
        papers = result.scalars().all()

        return papers

    async def get_search_stats(
        self,
        query: str,
        source: str | None = None,
        search_mode: str = "websearch",
    ) -> dict:
        """Получить статистику поискового запроса с теми же фильтрами, что и поиск."""
        _, _, stats = await self.search(
            query=query,
            limit=1,
            offset=0,
            source=source,
            search_mode=search_mode,
        )
        return stats


async def fulltext_search(
    db: AsyncSession,
    query: str,
    limit: int = 20,
    offset: int = 0,
    source: str | None = None,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    """Функция для быстрого доступа к полнотекстовому поиску."""
    service = FullTextSearchService(db)
    return await service.search(query, limit, offset, source)
