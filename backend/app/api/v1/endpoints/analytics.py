"""API endpoints для аналитики и метрик."""

import json
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, and_, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.paper import Paper as PaperModel
from app.db.session import get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])


_SCHEMA_HINT_COLUMNS = (
    "parse_confidence",
    "provenance",
    "quality_flags",
    "schema_version",
)


def _format_analytics_error(exc: Exception) -> str:
    raw = str(exc)
    lower = raw.lower()
    if any(column in lower for column in _SCHEMA_HINT_COLUMNS) and (
        "does not exist" in lower
        or "undefinedcolumn" in lower
        or "column" in lower
    ):
        return (
            "Похоже, база данных не обновлена после патча: в таблице papers нет новых "
            "колонок parser metadata. Запусти из корня проекта: scripts\\run_migrations.bat "
            "или python backend\\apply_migrations.py, затем перезапусти backend."
        )
    return raw


def _raise_analytics_500(exc: Exception) -> None:
    raise HTTPException(status_code=500, detail=_format_analytics_error(exc))


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, str) and parsed.strip():
                return [parsed.strip()]
        except Exception:
            pass
        parts = [part.strip() for part in re.split(r"[;,]", text) if part.strip()]
        return parts or [text]
    return [value]


def _has_text(value: object) -> bool:
    return bool(str(value or "").strip())


def _text_len(value: object) -> int:
    return len(str(value or "").strip())


def _has_embedding(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, set, dict, str)):
        return len(value) > 0
    return bool(value)


def _text_present_expr(column):
    return and_(column.isnot(None), func.length(func.trim(cast(column, String))) > 0)


def _json_list_present_expr(column):
    text_value = func.trim(cast(column, String))
    return and_(
        column.isnot(None),
        func.length(text_value) > 2,
        text_value.notin_(["[]", "{}", "null", "NULL", ""])
    )


def _count_if(expr):
    return func.coalesce(func.sum(case((expr, 1), else_=0)), 0)


def _quality_score_expr():
    return (
        case((_text_present_expr(PaperModel.abstract), 20), else_=0)
        + case((_text_present_expr(PaperModel.full_text), 30), else_=0)
        + case((_json_list_present_expr(PaperModel.keywords), 20), else_=0)
        + case((_text_present_expr(PaperModel.doi), 15), else_=0)
        + case((_json_list_present_expr(PaperModel.authors), 15), else_=0)
    )


def _normalize_metric_item(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n,;:.")
    return text[:160]


def _counter_key(value: str) -> str:
    return value.casefold()


def _count_normalized_items(values: list[object]):
    from collections import Counter

    counter: Counter[str] = Counter()
    labels: dict[str, str] = {}
    for raw in values:
        item = _normalize_metric_item(raw)
        if not item:
            continue
        key = _counter_key(item)
        counter[key] += 1
        labels.setdefault(key, item)
    return counter, labels


@router.get("/metrics/summary")
async def get_analytics_summary(
    source: str | None = Query(None, description="Фильтр по источнику"),
    db: AsyncSession = Depends(get_db),
):
    """Получить сводную статистику без вытягивания full_text в Python."""
    try:
        count_query = select(func.count()).select_from(PaperModel)
        if source and source != "all":
            count_query = count_query.where(PaperModel.source == source)

        total_count_result = await db.execute(count_query)
        total_count = int(total_count_result.scalar() or 0)

        source_query = select(PaperModel.source, func.count().label("count")).group_by(PaperModel.source)
        if source and source != "all":
            source_query = source_query.where(PaperModel.source == source)
        source_result = await db.execute(source_query)
        sources = {row.source: int(row.count or 0) for row in source_result}

        score_expr = _quality_score_expr()
        metrics_query = select(
            _count_if(_json_list_present_expr(PaperModel.embedding)).label("with_embedding"),
            func.coalesce(func.avg(score_expr), 0).label("avg_quality"),
        )
        if source and source != "all":
            metrics_query = metrics_query.where(PaperModel.source == source)

        metrics_result = await db.execute(metrics_query)
        metrics = metrics_result.one()
        with_embedding = int(metrics.with_embedding or 0)
        avg_quality = float(metrics.avg_quality or 0)

        return {
            "total_papers": total_count,
            "papers_by_source": sources,
            "papers_with_embedding": with_embedding,
            "embedding_coverage": round((with_embedding / total_count * 100) if total_count > 0 else 0, 2),
            "avg_quality_score": round(avg_quality, 2),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        _raise_analytics_500(e)


@router.get("/metrics/daily-count")
async def get_daily_papers_count(
    source: str | None = Query(None, description="Фильтр по источнику"),
    timezone_offset_minutes: int = Query(
        default=0,
        ge=-720,
        le=840,
        description="Смещение локального времени клиента от UTC в минутах",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Количество статей, добавленных за текущий день в локальной таймзоне клиента."""
    try:
        now_utc = datetime.now(timezone.utc)
        offset = timedelta(minutes=timezone_offset_minutes)
        local_now = now_utc + offset
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = local_start - offset

        query = select(func.count()).select_from(PaperModel).where(PaperModel.created_at >= today_start_utc)
        if source and source != "all":
            query = query.where(PaperModel.source == source)
        result = await db.execute(query)
        return {
            "total": int(result.scalar() or 0),
            "date": local_start.date().isoformat(),
            "timezone_offset_minutes": timezone_offset_minutes,
            "generated_at": now_utc.isoformat(),
        }
    except Exception as e:
        _raise_analytics_500(e)


@router.get("/metrics/trend")
async def get_publications_trend(
    group_by: str = Query(default="month", description="Группировка: day, week, month, year"),
    limit: int = Query(default=12, description="Максимум периодов"),
    source: str | None = Query(None, description="Фильтр по источнику"),
    db: AsyncSession = Depends(get_db),
):
    """
    Получить тренд публикаций.

    Returns:
        Список периодов с количеством публикаций
    """
    try:
        bind = db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""


        if dialect_name == "sqlite":
            if group_by == "year":
                date_trunc = func.strftime("%Y-01-01", PaperModel.publication_date)
            elif group_by == "month":
                date_trunc = func.strftime("%Y-%m-01", PaperModel.publication_date)
            elif group_by == "week":
                date_trunc = func.strftime("%Y-%W-1", PaperModel.publication_date)
            elif group_by == "day":
                date_trunc = func.strftime("%Y-%m-%d", PaperModel.publication_date)
            else:
                date_trunc = func.strftime("%Y-%m-01", PaperModel.publication_date)
        else:
            if group_by == "year":
                date_trunc = func.date_trunc("year", PaperModel.publication_date)
            elif group_by == "month":
                date_trunc = func.date_trunc("month", PaperModel.publication_date)
            elif group_by == "week":
                date_trunc = func.date_trunc("week", PaperModel.publication_date)
            elif group_by == "day":
                date_trunc = func.date_trunc("day", PaperModel.publication_date)
            else:
                date_trunc = func.date_trunc("month", PaperModel.publication_date)

        query = select(
            date_trunc.label("period"),
            func.count().label("count")
        ).where(
            PaperModel.publication_date.isnot(None)
        )

        if source and source != "all":
            query = query.where(PaperModel.source == source)

        query = query.group_by("period").order_by("period").limit(limit)

        result = await db.execute(query)
        rows = result.all()

        trend = [
            {
                "period": row.period.strftime("%Y-%m-%d") if hasattr(row.period, "strftime") else str(row.period),
                "count": row.count,
            }
            for row in rows
        ]

        return {
            "trend": trend,
            "group_by": group_by,
            "generated_at": datetime.now().isoformat(),
        }

    except Exception as e:
        _raise_analytics_500(e)


@router.get("/metrics/top")
async def get_top_items(
    item_type: str = Query(..., description="Тип: journals, authors, keywords"),
    limit: int = Query(default=10, ge=1, le=100, description="Максимум элементов"),
    source: str | None = Query(None, description="Фильтр по источнику"),
    db: AsyncSession = Depends(get_db),
):
    """Получить топ элементов, выбирая только нужные колонки."""
    try:
        if item_type == "journals":
            query = select(PaperModel.journal)
        elif item_type == "authors":
            query = select(PaperModel.authors)
        elif item_type == "keywords":
            query = select(PaperModel.keywords)
        else:
            raise HTTPException(status_code=400, detail=f"Неизвестный тип: {item_type}")

        if source and source != "all":
            query = query.where(PaperModel.source == source)

        query = query.limit(5000 if item_type in {"authors", "keywords"} else 2000)
        result = await db.execute(query)
        values = [row[0] for row in result.all()]

        if item_type == "journals":
            items = [value for value in values if value]
        else:
            items = []
            for value in values:
                items.extend(_as_list(value))

        counter, labels = _count_normalized_items(items)
        top_items = [{"name": labels[key], "count": count} for key, count in counter.most_common(limit)]

        return {
            "item_type": item_type,
            "items": top_items,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        _raise_analytics_500(e)


@router.get("/metrics/keyword-stats")
async def get_keyword_stats(
    source: str | None = Query(None, description="Фильтр по источнику"),
    db: AsyncSession = Depends(get_db),
):
    try:
        query = select(PaperModel.keywords)
        if source and source != "all":
            query = query.where(PaperModel.source == source)
        query = query.limit(5000)

        result = await db.execute(query)
        keyword_rows = [row[0] for row in result.all()]
        total = len(keyword_rows)

        keyword_values: list[object] = []
        per_paper_counts: list[int] = []
        for raw_keywords in keyword_rows:
            keywords = _as_list(raw_keywords)
            normalized = [_normalize_metric_item(item) for item in keywords]
            normalized = [item for item in normalized if item]
            keyword_values.extend(normalized)
            per_paper_counts.append(len(set(_counter_key(item) for item in normalized)))

        counter, labels = _count_normalized_items(keyword_values)
        with_keywords = sum(1 for count in per_paper_counts if count > 0)
        papers_with_3_plus = sum(1 for count in per_paper_counts if count >= 3)
        papers_with_5_plus = sum(1 for count in per_paper_counts if count >= 5)
        sparse_keywords = sum(1 for count in per_paper_counts if 0 < count < 3)
        keywordless = total - with_keywords

        rare_keywords = sum(1 for count in counter.values() if count == 1)
        top_preview = [{"name": labels[key], "count": count} for key, count in counter.most_common(10)]

        return {
            "total_papers": total,
            "papers_with_keywords": with_keywords,
            "papers_with_confirmed_keywords": with_keywords,
            "papers_with_3_plus_keywords": papers_with_3_plus,
            "papers_with_5_plus_keywords": papers_with_5_plus,
            "papers_with_sparse_keywords": sparse_keywords,


            "papers_with_10_plus_keywords": papers_with_5_plus,
            "papers_with_1_to_9_keywords": sparse_keywords,
            "papers_without_keywords": keywordless,
            "total_keyword_mentions": sum(counter.values()),
            "unique_keywords": len(counter),
            "rare_keywords": rare_keywords,
            "avg_keywords_per_paper": round(sum(per_paper_counts) / total, 2) if total else 0,
            "max_keywords_per_paper": max(per_paper_counts) if per_paper_counts else 0,
            "top_preview": top_preview,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        _raise_analytics_500(e)


@router.get("/metrics/source-distribution")
async def get_source_distribution(
    db: AsyncSession = Depends(get_db),
):
    """
    Получить распределение по источникам.

    Returns:
        Dict с распределением
    """
    try:
        query = select(
            PaperModel.source,
            func.count().label("count")
        ).group_by(PaperModel.source)

        result = await db.execute(query)
        rows = result.all()

        distribution = {
            row.source: {
                "count": row.count,
                "percent": 0
            }
            for row in rows
        }

        total = sum(d["count"] for d in distribution.values())
        if total > 0:
            for source in distribution:
                distribution[source]["percent"] = round(
                    distribution[source]["count"] / total * 100, 2
                )

        return {
            "distribution": distribution,
            "total": total,
            "generated_at": datetime.now().isoformat(),
        }

    except Exception as e:
        _raise_analytics_500(e)


@router.get("/metrics/quality-report")
async def get_quality_report(
    source: str | None = Query(None, description="Фильтр по источнику"),
    db: AsyncSession = Depends(get_db),
):
    """Получить отчёт о качестве данных через SQL-агрегации без загрузки full_text."""
    try:
        score_expr = _quality_score_expr()
        abstract_len_expr = case(
            (_text_present_expr(PaperModel.abstract), func.length(cast(PaperModel.abstract, String))),
            else_=None,
        )
        query = select(
            func.count().label("total"),
            _count_if(_text_present_expr(PaperModel.abstract)).label("with_abstract"),
            _count_if(_text_present_expr(PaperModel.full_text)).label("with_full_text"),
            _count_if(_json_list_present_expr(PaperModel.keywords)).label("with_keywords"),
            _count_if(_text_present_expr(PaperModel.doi)).label("with_doi"),
            _count_if(_json_list_present_expr(PaperModel.authors)).label("with_authors"),
            _count_if(_json_list_present_expr(PaperModel.embedding)).label("with_embedding"),
            func.coalesce(func.avg(abstract_len_expr), 0).label("avg_abstract_length"),
            func.coalesce(func.avg(score_expr), 0).label("avg_quality"),
            func.coalesce(func.min(score_expr), 0).label("min_quality"),
            func.coalesce(func.max(score_expr), 0).label("max_quality"),
        )

        if source and source != "all":
            query = query.where(PaperModel.source == source)

        result = await db.execute(query)
        row = result.one()
        total = int(row.total or 0)

        keyword_query = select(PaperModel.keywords)
        if source and source != "all":
            keyword_query = keyword_query.where(PaperModel.source == source)
        keyword_result = await db.execute(keyword_query)
        keyword_counts: list[int] = []
        for raw_keywords in keyword_result.scalars().all():
            normalized = [_normalize_metric_item(item) for item in _as_list(raw_keywords)]
            normalized = [item for item in normalized if item]
            keyword_counts.append(len(set(_counter_key(item) for item in normalized)))
        avg_keywords_count = round(sum(keyword_counts) / total, 2) if total else 0

        if not total:
            empty_completeness = {
                "with_abstract": {"count": 0, "percent": 0},
                "with_full_text": {"count": 0, "percent": 0},
                "with_keywords": {"count": 0, "percent": 0},
                "with_doi": {"count": 0, "percent": 0},
                "with_authors": {"count": 0, "percent": 0},
                "with_embedding": {"count": 0, "percent": 0},
            }
            return {
                "total": 0,
                "completeness": empty_completeness,
                "averages": {"avg_abstract_length": 0, "avg_keywords_count": 0},
                "quality_score": {"avg": 0, "min": 0, "max": 0},
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        def metric(count: object) -> dict[str, float | int]:
            value = int(count or 0)
            return {"count": value, "percent": round(value / total * 100, 2)}

        return {
            "total": total,
            "completeness": {
                "with_abstract": metric(row.with_abstract),
                "with_full_text": metric(row.with_full_text),
                "with_keywords": metric(row.with_keywords),
                "with_doi": metric(row.with_doi),
                "with_authors": metric(row.with_authors),
                "with_embedding": metric(row.with_embedding),
            },
            "averages": {
                "avg_abstract_length": round(float(row.avg_abstract_length or 0), 2),
                "avg_keywords_count": avg_keywords_count,
            },
            "quality_score": {
                "avg": round(float(row.avg_quality or 0), 2),
                "min": int(row.min_quality or 0),
                "max": int(row.max_quality or 0),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        _raise_analytics_500(e)
