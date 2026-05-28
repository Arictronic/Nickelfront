"""API endpoints для парсинга научных статей."""

import csv
import io
import time
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin_user
from app.core.config import settings
from app.api.v1.endpoints.error_helpers import format_paper_db_error
from app.db.models.paper import Paper as PaperModel
from app.db.session import get_db
from app.services.parse_job_history import add_parse_job
from app.services.system_settings_service import SystemSettingsService
from app.services.paper_service import PaperService
from app.services.paper_content_part_service import PaperContentPartService
from shared.schemas.auth import UserResponse
from shared.schemas.paper import (
    Paper,
    PaperListItem,
    PaperListResponse,
    PaperDetailResponse,
    PaperContentPart,
    PaperContentPartRegenerateResponse,
    PaperProcessingStatusInfo,
    PaperSearchRequest,
    PaperSearchResponse,
)

router = APIRouter(prefix="/papers", tags=["papers"])


PROCESSING_STATUS_REGISTRY: dict[str, dict[str, object]] = {
    "pending": {"label": "Ожидает обработки", "group": "pending", "final": False},
    "queued_for_content_processing": {"label": "В очереди на обработку", "group": "pending", "final": False},
    "processing_content": {"label": "Обрабатывается", "group": "processing", "final": False},
    "started": {"label": "Запущено", "group": "processing", "final": False},
    "pdf_pending": {"label": "Подготовка PDF", "group": "processing", "final": False},
    "downloading_pdf": {"label": "Загрузка PDF", "group": "processing", "final": False},
    "pdf_downloaded": {"label": "PDF загружен", "group": "processing", "final": False},
    "pdf_download_failed": {"label": "PDF не загрузился", "group": "error", "final": True},
    "pdf_unavailable": {"label": "PDF недоступен", "group": "warning", "final": True},
    "pdf_download_skipped": {"label": "Загрузка PDF пропущена", "group": "warning", "final": True},
    "extracting_pdf_text": {"label": "Извлечение текста из PDF", "group": "processing", "final": False},
    "pdf_parsed": {"label": "Текст PDF извлечён", "group": "processing", "final": False},
    "pdf_text_skipped": {"label": "Извлечение текста PDF пропущено", "group": "warning", "final": True},
    "fulltext_fallback_parsed": {"label": "Текст получен из резервного источника", "group": "processing", "final": False},
    "fulltext_unavailable": {"label": "Полный текст недоступен", "group": "warning", "final": True},
    "digitizing_file": {"label": "Оцифровка файла", "group": "processing", "final": False},
    "formatting_markdown": {"label": "Оцифровка файла", "group": "processing", "final": False},
    "markdown_ready": {"label": "Файл оцифрован", "group": "processing", "final": False},
    "markdown_partial": {"label": "Файл частично оцифрован", "group": "warning", "final": False},
    "markdown_ready_without_qwen": {"label": "Текст собран без Qwen", "group": "success", "final": True},
    "markdown_failed": {"label": "Ошибка оцифровки файла", "group": "error", "final": True},
    "markdown_skipped": {"label": "Оцифровка пропущена", "group": "warning", "final": True},
    "analyzing_ru": {"label": "Анализ на русском", "group": "processing", "final": False},
    "ru_analysis_ready": {"label": "Русский анализ готов", "group": "processing", "final": False},
    "ru_analysis_fallback": {"label": "Русский анализ в резервном режиме", "group": "warning", "final": True},
    "ru_analysis_skipped": {"label": "Русский анализ пропущен", "group": "warning", "final": True},
    "extracting_keywords": {"label": "Выделение ключевых слов", "group": "processing", "final": False},
    "keywords_ready": {"label": "Ключевые слова готовы", "group": "processing", "final": False},
    "keywords_failed": {"label": "Ошибка ключевых слов", "group": "error", "final": True},
    "keywords_skipped": {"label": "Ключевые слова пропущены", "group": "warning", "final": True},
    "qwen_auth_failed": {"label": "Ошибка авторизации Qwen", "group": "error", "final": True},
    "indexing_vector": {"label": "Индексация в векторной базе", "group": "processing", "final": False},
    "embedding_ready": {"label": "Векторный индекс готов", "group": "success", "final": True},
    "embedding_skipped": {"label": "Векторная индексация пропущена", "group": "warning", "final": True},
    "ready": {"label": "Готово", "group": "success", "final": True},
    "ready_with_fallback": {"label": "Готово (резервный режим)", "group": "success", "final": True},
    "completed": {"label": "Готово", "group": "success", "final": True},
    "failed": {"label": "Ошибка обработки", "group": "error", "final": True},
}


def _status_info(key: str) -> PaperProcessingStatusInfo:
    base_key = (key or "").strip().split(":", 1)[0]
    meta = PROCESSING_STATUS_REGISTRY.get(base_key) or {"label": base_key, "group": "unknown", "final": False}
    return PaperProcessingStatusInfo(
        key=base_key,
        label=str(meta.get("label") or base_key),
        group=str(meta.get("group") or "unknown"),
        final=bool(meta.get("final")),
    )


def _format_csv_list(value) -> str:
    if not value:
        return ""
    if isinstance(value, list):
        return "; ".join(str(item) for item in value if str(item).strip())
    return str(value)


def _papers_csv_response(rows: list[dict]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([
        "ID",
        "Название",
        "Источник",
        "Дата публикации",
        "DOI",
        "Журнал",
        "Авторы",
        "Ключевые слова",
        "PDF",
        "Извлечённый полный текст",
        "Статус",
    ])
    for row in rows:
        publication_date = row.get("publication_date")
        writer.writerow([
            row.get("id") or "",
            row.get("title") or "",
            row.get("source") or "",
            publication_date.date().isoformat() if hasattr(publication_date, "date") else (publication_date or ""),
            row.get("doi") or "",
            row.get("journal") or "",
            _format_csv_list(row.get("authors")),
            _format_csv_list(row.get("keywords")),
            "Да" if row.get("has_pdf") else "Нет",
            "Да" if row.get("has_full_text") else "Нет",
            _status_info(str(row.get("processing_status") or "")).label,
        ])

    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="articles.csv"'},
    )


class _LazyTaskProxy:
    """Backwards-compatible proxy for Celery tasks used by tests and endpoints."""

    def __init__(self, task_name: str):
        self._task_name = task_name

    def _task(self):
        return getattr(_get_parse_task_module(), self._task_name)

    def delay(self, *args, **kwargs):
        return self._task().delay(*args, **kwargs)

    def apply_async(self, *args, **kwargs):
        return self._task().apply_async(*args, **kwargs)

    def __getattr__(self, item):
        return getattr(self._task(), item)


parse_papers_task = _LazyTaskProxy("parse_papers_task")
parse_all_sources_task = _LazyTaskProxy("parse_all_sources_task")
parse_multiple_queries_task = _LazyTaskProxy("parse_multiple_queries_task")


def _get_parse_task_module():
    """Lazy import Celery parser tasks only when a parse endpoint is used."""
    from app.tasks import parse_tasks

    return parse_tasks


def _get_content_task():
    """Lazy import content task only when PDF post-processing is queued."""
    from app.tasks.content_tasks import process_paper_content_task

    return process_paper_content_task


def _get_regenerate_markdown_part_task():
    """Lazy import Qwen part-regeneration task."""
    from app.tasks.qwen_tasks import regenerate_markdown_part_task

    return regenerate_markdown_part_task


_PAPERS_COUNT_TTL_SECONDS = 5.0
_papers_count_cache: dict[str, tuple[int, float]] = {}

def _count_cache_key(source: str | None) -> str:
    return source or "__all__"


def _get_cached_count(source: str | None) -> tuple[int, bool] | None:
    key = _count_cache_key(source)
    cached = _papers_count_cache.get(key)
    if not cached:
        return None
    total, ts = cached
    is_stale = (time.monotonic() - ts) > _PAPERS_COUNT_TTL_SECONDS
    return total, is_stale


def _set_cached_count(source: str | None, total: int) -> None:
    _papers_count_cache[_count_cache_key(source)] = (total, time.monotonic())


def _is_source_enabled(parser_settings: dict, source: str) -> bool:
    enabled_sources = parser_settings.get("enabled_sources") or {}
    return bool(enabled_sources.get(source, True))


def _effective_parse_limit(requested_limit: int | None, parser_settings: dict, source: str) -> int:
    default_limit = int(parser_settings.get("default_limit") or 10)
    max_limit = int(parser_settings.get("max_limit") or 100)
    source_limits = parser_settings.get("source_limits") or {}
    source_limit = int(source_limits.get(source) or max_limit)
    requested = int(requested_limit or default_limit)
    return max(1, min(requested, max_limit, source_limit))


async def _get_parser_settings(db: AsyncSession) -> dict:
    return await SystemSettingsService(db).get_parser_settings()


def _count_active_parse_tasks() -> int:
    """Best-effort count of running parse tasks across workers for UI-configured limit."""
    try:
        from app.tasks.celery_app import celery_app

        active = celery_app.control.inspect(timeout=1.0).active() or {}
    except Exception as exc:
        logger.warning("Failed to inspect active parse tasks: {}", exc)
        return 0

    count = 0
    for tasks in active.values():
        for task in tasks or []:
            task_name = str(task.get("name") or task.get("type") or "")
            if task_name.startswith("app.tasks.parse_tasks."):
                count += 1
    return count


def _ensure_parallel_parse_limit(parser_settings: dict) -> None:
    max_parallel = int(parser_settings.get("max_parallel_parse_jobs") or 1)
    if max_parallel <= 0:
        return
    active_count = _count_active_parse_tasks()
    if active_count >= max_parallel:
        raise HTTPException(
            status_code=409,
            detail=f"Достигнут лимит активных parse-задач: {active_count}/{max_parallel}",
        )


async def _count_papers_for_source(db: AsyncSession, source: str | None) -> int:
    stmt = select(func.count()).select_from(PaperModel)
    if source and source != "all":
        stmt = stmt.where(PaperModel.source == source)
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


def _record_parse_job(
    *,
    task_id: str,
    query: str,
    source: str,
    initial_count: int,
) -> None:
    started_at = int(time.time() * 1000)
    add_parse_job(
        {
            "jobId": task_id,
            "startedAt": started_at,
            "query": query,
            "source": source,
            "initialCount": initial_count,
            "lastObservedCount": initial_count,
            "lastCountChangeAt": started_at,
            "status": "in_progress",
        }
    )


@router.post("/search", response_model=PaperSearchResponse)
async def search_papers(
    request: PaperSearchRequest,
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Поиск статей в локальной базе данных."""
    paper_service = PaperService(db)
    try:
        papers = await paper_service.search(
            query=request.query,
            limit=request.limit,
            sources=request.sources,
            full_text_only=request.full_text_only,
        )
    except Exception as exc:
        logger.exception("Failed to search papers")
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    return PaperSearchResponse(
        papers=papers,
        total=len(papers),
        query=request.query,
        sources=request.sources or ["CORE"],
    )


@router.get("", response_model=PaperListResponse)
async def get_papers(
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source: str | None = Query(None, description="Фильтр по источнику"),
    query: str | None = Query(None, description="Поиск по названию, аннотации, авторам, журналу, DOI и ключевым словам"),
    date_from: date | None = Query(None, description="Дата публикации с"),
    date_to: date | None = Query(None, description="Дата публикации по"),
    processing_status: str | None = Query(None, description="Фильтр по статусу обработки"),
    full_text_only: bool = Query(False, description="Только записи с извлечённым полным текстом"),
    sort_by: Literal["id", "authors", "created_at", "publication_date", "relevance"] = Query("created_at"),
    sort_dir: Literal["asc", "desc"] = Query("desc"),
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Лёгкий список статей с backend-фильтрами, сортировкой и total."""
    paper_service = PaperService(db)
    try:
        items, total = await paper_service.list_filtered_lightweight(
            limit=limit,
            offset=offset,
            source=source,
            query=query,
            date_from=date_from,
            date_to=date_to,
            processing_status=processing_status,
            full_text_only=full_text_only,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except Exception as exc:
        logger.exception("Failed to list papers")
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    return PaperListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/recent", response_model=list[PaperListItem])
async def get_recent_papers(
    limit: int = Query(default=20, ge=1, le=100),
    source: str | None = Query(None, description="Фильтр по источнику"),
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Лёгкий список последних статей для dashboard без full_text."""
    paper_service = PaperService(db)
    try:
        return await paper_service.get_recent_lightweight(limit=limit, source=source)
    except Exception as exc:
        logger.exception("Failed to load recent papers")
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))


@router.get("/count")
async def get_papers_count(
    source: str | None = Query(None),
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить общее количество статей."""
    cached = _get_cached_count(source)
    if cached and not cached[1]:
        return {"total": cached[0], "cached": True, "stale": False}

    paper_service = PaperService(db)

    try:
        if source:
            from sqlalchemy import func, select

            from app.db.models.paper import Paper as PaperModel
            result = await db.execute(select(func.count()).where(PaperModel.source == source))
            count = result.scalar() or 0
        else:
            count = await paper_service.get_total_count()
    except (SQLAlchemyError, TimeoutError, OSError) as exc:
        if cached:
            logger.warning("papers/count timeout, returning stale cache: {}", exc)
            return {"total": cached[0], "cached": True, "stale": True}
        logger.error("papers/count failed without cache: {}", exc)
        raise HTTPException(status_code=503, detail="База данных временно недоступна")

    total = int(count)
    _set_cached_count(source, total)
    return {"total": total, "cached": False, "stale": False}


@router.get("/statuses", response_model=list[PaperProcessingStatusInfo])
async def get_paper_processing_statuses(
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Единый словарь статусов обработки для UI-фильтров."""
    paper_service = PaperService(db)
    try:
        observed = await paper_service.list_processing_status_keys()
    except Exception as exc:
        logger.warning("Failed to load observed paper statuses: {}", exc)
        observed = []

    keys = sorted(
        set(PROCESSING_STATUS_REGISTRY.keys()) | set(observed),
        key=lambda key: (_status_info(key).label, key),
    )
    return [_status_info(key) for key in keys]


@router.get("/export.csv")
async def export_papers_csv(
    source: str | None = Query(None, description="Фильтр по источнику"),
    query: str | None = Query(None, description="Поиск по статьям"),
    date_from: date | None = Query(None, description="Дата публикации с"),
    date_to: date | None = Query(None, description="Дата публикации по"),
    processing_status: str | None = Query(None, description="Фильтр по статусу обработки"),
    full_text_only: bool = Query(False, description="Только записи с извлечённым полным текстом"),
    sort_by: Literal["id", "authors", "created_at", "publication_date", "relevance"] = Query("created_at"),
    sort_dir: Literal["asc", "desc"] = Query("desc"),
    max_rows: int = Query(default=10000, ge=1, le=50000),
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """CSV-экспорт всех найденных статей без загрузки full_text."""
    paper_service = PaperService(db)
    try:
        rows, _total = await paper_service.list_filtered_lightweight(
            limit=max_rows,
            offset=0,
            source=source,
            query=query,
            date_from=date_from,
            date_to=date_to,
            processing_status=processing_status,
            full_text_only=full_text_only,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except Exception as exc:
        logger.exception("Failed to export papers CSV")
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    return _papers_csv_response(rows)


@router.post("/parse")
async def start_parsing(
    query: str = Query(..., description="Поисковый запрос"),
    limit: int | None = Query(default=None, ge=1, le=5000, description="Макс. количество результатов"),
    source: str = Query(default="CORE", description="Источник"),
    pdf_mode: Literal["auto", "ai", "mypdf"] = Query(default="auto", description="Режим обработки PDF: auto, ai или mypdf"),
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Запустить парсинг статей.

    Доступные источники берутся из parser_alpha реестра.
    """
    normalized_query = query.strip()
    if not normalized_query:
        raise HTTPException(status_code=400, detail="Поле query обязательно и не может быть пустым")

    parse_tasks = _get_parse_task_module()
    available_sources = parse_tasks.AVAILABLE_SOURCES
    if source not in available_sources:
        raise HTTPException(status_code=400, detail=f"Неподдерживаемый источник. Доступны: {', '.join(available_sources)}")

    parser_settings = await _get_parser_settings(db)
    if not parser_settings.get("enabled", True):
        raise HTTPException(status_code=409, detail="Парсинг временно отключён в технических настройках")
    if not _is_source_enabled(parser_settings, source):
        raise HTTPException(status_code=409, detail=f"Источник {source} отключён в технических настройках")
    _ensure_parallel_parse_limit(parser_settings)
    effective_limit = _effective_parse_limit(limit, parser_settings, source)

    task = parse_papers_task.delay(
        query=normalized_query,
        limit=effective_limit,
        source=source,
        pdf_mode=pdf_mode,
    )
    initial_count = await _count_papers_for_source(db, source)
    _record_parse_job(
        task_id=task.id,
        query=normalized_query,
        source=source,
        initial_count=initial_count,
    )
    logger.info(f"Запущен парсинг: source={source}, query={normalized_query}, task_id={task.id}")

    return {
        "message": "Парсинг запущен",
        "task_id": task.id,
        "source": source,
        "query": normalized_query,
        "limit": effective_limit,
        "pdf_mode": pdf_mode,
    }


@router.post("/parse-all")
async def start_parsing_all(
    limit_per_query: int | None = Query(default=None, ge=1, le=5000),
    source: str = Query(default="all", description="Источник (или all)"),
    query: str = Query(..., description="Пользовательский запрос для всех источников"),
    pdf_mode: Literal["auto", "ai", "mypdf"] = Query(default="auto", description="Режим обработки PDF: auto, ai или mypdf"),
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Запустить парсинг по всем стандартным запросам.

    Источники: `AVAILABLE_SOURCES` и `all`.
    """
    parse_tasks = _get_parse_task_module()
    available_sources = parse_tasks.AVAILABLE_SOURCES
    parser_settings = await _get_parser_settings(db)
    if not parser_settings.get("enabled", True):
        raise HTTPException(status_code=409, detail="Парсинг временно отключён в технических настройках")
    _ensure_parallel_parse_limit(parser_settings)

    enabled_sources = [s for s in available_sources if _is_source_enabled(parser_settings, s)]
    allowed_with_all = [*available_sources, "all"]
    if source not in allowed_with_all:
        raise HTTPException(status_code=400, detail=f"Неподдерживаемый источник. Доступны: {', '.join(allowed_with_all)}")
    if source != "all" and source not in enabled_sources:
        raise HTTPException(status_code=409, detail=f"Источник {source} отключён в технических настройках")
    if source == "all" and not enabled_sources:
        raise HTTPException(status_code=409, detail="Все источники отключены в технических настройках")

    normalized_query = query.strip()
    if not normalized_query:
        raise HTTPException(status_code=400, detail="Поле query обязательно и не может быть пустым")
    user_queries = [normalized_query]

    if source == "all":
        effective_limit = min(_effective_parse_limit(limit_per_query, parser_settings, src) for src in enabled_sources)
        task = parse_all_sources_task.delay(
            limit_per_query=effective_limit,
            queries=user_queries,
            query=normalized_query or None,
            sources=enabled_sources,
            pdf_mode=pdf_mode,
        )
        source_list = enabled_sources
    elif source == "arXiv":
        task = parse_multiple_queries_task.delay(
            queries=user_queries or parse_tasks.ARXIV_SEARCH_QUERIES,
            limit_per_query=_effective_parse_limit(limit_per_query, parser_settings, "arXiv"),
            source="arXiv",
            pdf_mode=pdf_mode,
        )
        source_list = ["arXiv"]
    elif source == "CORE":
        task = parse_multiple_queries_task.delay(
            queries=user_queries or parse_tasks.DEFAULT_SEARCH_QUERIES,
            limit_per_query=_effective_parse_limit(limit_per_query, parser_settings, "CORE"),
            source="CORE",
            pdf_mode=pdf_mode,
        )
        source_list = ["CORE"]
    else:
        task = parse_multiple_queries_task.delay(
            queries=user_queries or parse_tasks.DEFAULT_SEARCH_QUERIES,
            limit_per_query=_effective_parse_limit(limit_per_query, parser_settings, source),
            source=source,
            pdf_mode=pdf_mode,
        )
        source_list = [source]

    logger.info(
        "Запущен массовый парсинг: sources={}, query='{}', limit_per_query={}, task_id={}",
        source_list,
        normalized_query or "<default_templates>",
        effective_limit if source == "all" else _effective_parse_limit(limit_per_query, parser_settings, source),
        task.id,
    )
    initial_count = await _count_papers_for_source(db, "all" if source == "all" else source_list[0])
    _record_parse_job(
        task_id=task.id,
        query=normalized_query,
        source="all" if source == "all" else source_list[0],
        initial_count=initial_count,
    )

    return {
        "message": "Массовый парсинг запущен",
        "task_id": task.id,
        "sources": source_list,
        "limit_per_query": effective_limit if source == "all" else _effective_parse_limit(limit_per_query, parser_settings, source),
        "query": normalized_query,
        "pdf_mode": pdf_mode,
    }


@router.get("/id/{paper_id}", response_model=Paper)
async def get_paper(
    paper_id: int,
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить статью по ID."""
    paper_service = PaperService(db)
    try:
        paper = await paper_service.get_by_id(paper_id)
    except Exception as exc:
        logger.exception("Failed to load paper {}", paper_id)
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    return paper


@router.get("/id/{paper_id}/details", response_model=PaperDetailResponse)
async def get_paper_details(
    paper_id: int,
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Полная карточка статьи для страницы просмотра.

    Список /papers остаётся лёгким, но при открытии конкретной статьи UI должен
    получить весь Paper payload и связанные content-parts одним запросом.
    """
    paper_service = PaperService(db)
    try:
        paper = await paper_service.get_by_id(paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Статья не найдена")
        content_parts = await PaperContentPartService(db).list_parts(paper_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to load full paper details {}", paper_id)
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    return PaperDetailResponse(
        paper=paper,
        content_parts=content_parts,
        status_info=_status_info(paper.processing_status),
    )


@router.get("/id/{paper_id}/content-parts", response_model=list[PaperContentPart])
async def get_paper_content_parts(
    paper_id: int,
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить сохранённые части PDF/raw text + Qwen Markdown по статье."""
    paper = await PaperService(db).get_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return await PaperContentPartService(db).list_parts(paper_id)


@router.post("/id/{paper_id}/content-parts/{part_id}/regenerate", response_model=PaperContentPartRegenerateResponse)
async def regenerate_paper_content_part(
    paper_id: int,
    part_id: int,
    mode: Literal["text", "image"] = Query("text", description="Режим перегенерации: text — из сохранённого текста, image — по изображению страницы PDF"),
    _current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Перегенерировать Markdown только для одной сохранённой части."""
    paper = await PaperService(db).get_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    part_service = PaperContentPartService(db)
    part = await part_service.get_part(paper_id, part_id)
    if not part:
        raise HTTPException(status_code=404, detail="Часть статьи не найдена")
    if mode == "text" and not (part.raw_text or "").strip():
        raise HTTPException(status_code=400, detail="У части нет сохранённого исходного текста")
    if mode == "image" and not (paper.pdf_local_path or "").strip():
        raise HTTPException(status_code=400, detail="Для режима по фото нужен локально сохранённый PDF")

    qwen_settings = await SystemSettingsService(db).get_qwen_settings()
    if not qwen_settings.get("markdown_enabled", True):
        raise HTTPException(status_code=409, detail="Markdown-оцифровка Qwen выключена в технических настройках")

    task = _get_regenerate_markdown_part_task().apply_async(
        args=[paper_id, part_id, mode],
        queue=settings.QWEN_QUEUE_NAME,
    )
    total_parts = len(await part_service.list_parts(paper_id)) or max(1, part.part_index)
    await PaperService(db).update_paper(
        paper_id,
        processing_status=f"digitizing_file:{part.part_index}/{max(1, total_parts)}",
        content_task_id=task.id,
        processing_error=None,
    )
    return PaperContentPartRegenerateResponse(
        paper_id=paper_id,
        part_id=part_id,
        task_id=task.id,
        status="queued",
        page_start=part.page_start,
        page_end=part.page_end,
        mode=mode,
    )


@router.post("/id/{paper_id}/markdown-pages/regenerate", response_model=PaperContentPartRegenerateResponse)
async def regenerate_paper_markdown_pages(
    paper_id: int,
    page_start: int = Query(..., ge=1),
    page_end: int = Query(..., ge=1),
    mode: Literal["text", "image"] = Query("text", description="Режим перегенерации: text — из сохранённого текста, image — по изображению страницы PDF"),
    _current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Совместимый endpoint: найти часть по диапазону страниц и перегенерировать её."""
    if page_end < page_start:
        raise HTTPException(status_code=400, detail="page_end должен быть >= page_start")

    paper = await PaperService(db).get_by_id(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    part_service = PaperContentPartService(db)
    part = await part_service.get_part_by_pages(paper_id, page_start, page_end)
    if not part:
        raise HTTPException(status_code=404, detail="Часть с указанными страницами не найдена")
    if mode == "text" and not (part.raw_text or "").strip():
        raise HTTPException(status_code=400, detail="У части нет сохранённого исходного текста")
    if mode == "image" and not (paper.pdf_local_path or "").strip():
        raise HTTPException(status_code=400, detail="Для режима по фото нужен локально сохранённый PDF")

    qwen_settings = await SystemSettingsService(db).get_qwen_settings()
    if not qwen_settings.get("markdown_enabled", True):
        raise HTTPException(status_code=409, detail="Markdown-оцифровка Qwen выключена в технических настройках")

    task = _get_regenerate_markdown_part_task().apply_async(
        args=[paper_id, part.id, mode],
        queue=settings.QWEN_QUEUE_NAME,
    )
    total_parts = len(await part_service.list_parts(paper_id)) or max(1, part.part_index)
    await PaperService(db).update_paper(
        paper_id,
        processing_status=f"digitizing_file:{part.part_index}/{max(1, total_parts)}",
        content_task_id=task.id,
        processing_error=None,
    )
    return PaperContentPartRegenerateResponse(
        paper_id=paper_id,
        part_id=part.id,
        task_id=task.id,
        status="queued",
        page_start=part.page_start,
        page_end=part.page_end,
        mode=mode,
    )


@router.get("/id/{paper_id}/pdf")
async def get_paper_pdf(
    paper_id: int,
    _current_user: UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить PDF статьи: локальный файл или редирект на внешний URL."""
    try:
        paper = await PaperService(db).get_by_id(paper_id)
    except Exception as exc:
        logger.exception("Failed to load paper PDF metadata {}", paper_id)
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    if paper.pdf_local_path:
        path = Path(paper.pdf_local_path)
        if path.exists() and path.is_file():
            return FileResponse(
                path=path,
                media_type="application/pdf",
                filename=f"paper_{paper_id}.pdf",
                content_disposition_type="inline",
            )

    if paper.pdf_url:
        raise HTTPException(
            status_code=409,
            detail=(
                "PDF есть только как внешняя ссылка и ещё не сохранён локально. "
                "Запустите обработку документа, чтобы скачать PDF через Celery."
            ),
        )

    raise HTTPException(status_code=404, detail="PDF не найден")


@router.post("/id/{paper_id}/reprocess")
async def reprocess_paper_content(
    paper_id: int,
    pdf_mode: Literal["auto", "ai", "mypdf"] = Query("auto", description="Режим обработки PDF: auto — обычные алгоритмы, ai — по изображениям страниц, mypdf — быстрый текстовый слой без OCR/таблиц"),
    _current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Поставить статью в очередь на повторную PDF+AI обработку."""
    paper_service = PaperService(db)
    try:
        paper = await paper_service.get_by_id(paper_id)
    except Exception as exc:
        logger.exception("Failed to load paper for reprocess {}", paper_id)
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))
    if not paper:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    process_paper_content_task = _get_content_task()
    task = process_paper_content_task.apply_async(
        args=[paper_id, pdf_mode],
        queue=settings.CONTENT_QUEUE_NAME,
    )
    await paper_service.update_paper(
        paper_id,
        processing_status="queued_for_content_processing",
        content_task_id=task.id,
        processing_error=None,
    )
    return {"paper_id": paper_id, "task_id": task.id, "status": "queued", "pdf_mode": pdf_mode, "preserved_existing_content": True}


@router.post("/reprocess-all")
async def reprocess_all_papers(
    limit: int = Query(default=500, ge=1, le=5000),
    source: str | None = Query(default=None, description="Фильтр по источнику"),
    pdf_mode: Literal["auto", "ai", "mypdf"] = Query("auto", description="Режим обработки PDF: auto, ai или mypdf"),
    _current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Поставить в очередь постобработку набора существующих статей."""
    paper_service = PaperService(db)
    try:
        paper_ids = await paper_service.list_ids_for_reprocess(limit=limit, source=source)
    except Exception as exc:
        logger.exception("Failed to load paper ids for reprocess-all")
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    process_paper_content_task = _get_content_task()
    queued = 0
    task_ids: list[str] = []
    for paper_id in paper_ids:
        task = process_paper_content_task.apply_async(
            args=[paper_id, pdf_mode],
            queue=settings.CONTENT_QUEUE_NAME,
        )
        await paper_service.update_paper(
            paper_id,
            processing_status="queued_for_content_processing",
            content_task_id=task.id,
            processing_error=None,
        )
        task_ids.append(task.id)
        queued += 1

    return {"queued": queued, "task_ids": task_ids, "pdf_mode": pdf_mode, "preserved_existing_content": True}


@router.delete("/id/{paper_id}")
async def delete_paper(
    paper_id: int,
    _current_user: UserResponse = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Удалить статью."""
    paper_service = PaperService(db)
    try:
        deleted = await paper_service.delete_paper(paper_id)
    except Exception as exc:
        logger.exception("Failed to delete paper {}", paper_id)
        raise HTTPException(status_code=500, detail=format_paper_db_error(exc))

    if not deleted:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    return {"message": "Статья удалена"}
