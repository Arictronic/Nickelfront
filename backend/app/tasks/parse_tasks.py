"""Celery tasks for scientific paper parsing via parser_alpha."""

import asyncio
import html
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from app.db.session import async_session_maker
from app.services.celery_cancel import clear_cancel_flag, is_cancelled
from app.services.paper_content_service import resolve_pdf_url
from app.services.paper_service import PaperService
from app.tasks.content_tasks import process_paper_content_task
from shared.schemas.paper import PaperCreate

from .async_runner import run_async
from .celery_app import celery_app

DEFAULT_SEARCH_QUERIES = [
    "nickel-based alloys",
    "superalloys",
    "heat resistant alloys",
    "nickel superalloys corrosion",
    "nickel alloys high temperature",
]

ARXIV_SEARCH_QUERIES = [
    "nickel-based alloys",
    "superalloys",
    "heat resistant alloys",
    "nickel superalloys",
    "nickel alloys high temperature",
    "Ni-based superalloys",
    "inconel",
    "hastelloy",
]

EXTERNAL_SEARCH_QUERIES = {
    "OpenAlex": DEFAULT_SEARCH_QUERIES,
    "Crossref": DEFAULT_SEARCH_QUERIES,
    "EuropePMC": DEFAULT_SEARCH_QUERIES,
    "CyberLeninka": DEFAULT_SEARCH_QUERIES,
    "eLibrary": DEFAULT_SEARCH_QUERIES,
    "Rospatent": DEFAULT_SEARCH_QUERIES,
    "FreePatent": DEFAULT_SEARCH_QUERIES,
    "PATENTSCOPE": DEFAULT_SEARCH_QUERIES,
}

AVAILABLE_SOURCES = ["CORE", "arXiv", *list(EXTERNAL_SEARCH_QUERIES.keys())]

PARSER_ALPHA_ROOT = Path(__file__).resolve().parents[3] / "parser_alpha"
PARSER_ALPHA_RUNNER = PARSER_ALPHA_ROOT / "run_parser.py"
PARSER_ALPHA_DATA_DIR = PARSER_ALPHA_ROOT / "data"
PARSER_ALPHA_VENV_PYTHON = PARSER_ALPHA_ROOT / ".venv" / "Scripts" / "python.exe"
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _get_task_id(task) -> str | None:
    return getattr(getattr(task, "request", None), "id", None)


def _is_cancelled(task) -> bool:
    task_id = _get_task_id(task)
    return bool(task_id and is_cancelled(task_id))


def _safe_update_state(task, state: str, meta: dict[str, Any]) -> None:
    task_id = _get_task_id(task)
    if not task_id:
        return
    task.update_state(state=state, meta=meta)


def _mark_revoked(task, query: str, source: str, current: int = 0, total: int = 0) -> dict:
    _safe_update_state(
        task,
        state="REVOKED",
        meta={
            "query": query,
            "source": source,
            "current": current,
            "total": total,
            "status": "Отменено",
        },
    )
    return {
        "status": "revoked",
        "query": query,
        "source": source,
        "current": current,
        "total": total,
        "saved_count": 0,
        "embedded_count": 0,
        "content_queued_count": 0,
        "errors": ["cancelled"],
    }


def _extract_json_payload(stdout_text: str) -> dict[str, Any]:
    text = (stdout_text or "").strip()
    if not text:
        raise RuntimeError("parser_alpha produced empty stdout")

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError(f"parser_alpha returned unexpected payload: {text[:300]}")

    return json.loads(text[start : end + 1])


def _run_parser_alpha_sync(query: str, limit: int, source: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not PARSER_ALPHA_RUNNER.exists():
        raise RuntimeError(f"parser_alpha runner not found: {PARSER_ALPHA_RUNNER}")

    PARSER_ALPHA_DATA_DIR.mkdir(parents=True, exist_ok=True)

    python_exec = str(PARSER_ALPHA_VENV_PYTHON if PARSER_ALPHA_VENV_PYTHON.exists() else Path(sys.executable))

    cmd = [
        python_exec,
        str(PARSER_ALPHA_RUNNER),
        "--source",
        source,
        "--query",
        query,
        "--limit",
        str(limit),
        "--out",
        str(PARSER_ALPHA_DATA_DIR),
        "--strict-source",
        "--explain",
    ]

    process = subprocess.run(
        cmd,
        cwd=str(PARSER_ALPHA_ROOT.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    out_text = process.stdout or ""
    err_text = process.stderr or ""

    if process.returncode != 0:
        raise RuntimeError(f"parser_alpha failed ({process.returncode}): {(err_text or out_text)[-1200:]}")

    report = _extract_json_payload(out_text)
    out_path_raw = report.get("out_path")
    if not out_path_raw:
        raise RuntimeError("parser_alpha report does not contain out_path")

    out_path = Path(str(out_path_raw))
    if not out_path.is_absolute():
        out_path = PARSER_ALPHA_ROOT.parent / out_path

    if not out_path.exists():
        raise RuntimeError(f"parser_alpha output file does not exist: {out_path}")

    records = json.loads(out_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise RuntimeError("parser_alpha output is not a JSON array")

    return report, records


async def _run_parser_alpha(query: str, limit: int, source: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return await asyncio.to_thread(_run_parser_alpha_sync, query, limit, source)


def _to_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value))
    text = _HTML_TAG_RE.sub(" ", text)
    text = " ".join(text.split()).strip()
    return text or None


def _normalize_publication_date(value: Any) -> datetime | str | None:
    if value is None:
        return None

    dt: datetime | None = None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return value
    else:
        return value

    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@celery_app.task(bind=True)
def parse_papers_task(
    self,
    query: str,
    limit: int = 50,
    source: str = "CORE",
):
    try:
        if _is_cancelled(self):
            return _mark_revoked(self, query=query, source=source, current=0, total=limit)

        _safe_update_state(
            self,
            state="STARTED",
            meta={
                "query": query,
                "source": source,
                "limit": limit,
                "current": 0,
                "total": limit,
                "status": "Инициализация...",
            },
        )
        return run_async(_parse_async(self, query, limit, source))
    except Exception:
        logger.exception("Ошибка парсинга task_id={} source={} query='{}'", _get_task_id(self), source, query)
        raise
    finally:
        task_id = _get_task_id(self)
        if task_id:
            clear_cancel_flag(task_id)


async def _parse_async(
    self,
    query: str,
    limit: int = 50,
    source: str = "CORE",
) -> dict:
    if _is_cancelled(self):
        return _mark_revoked(self, query=query, source=source, current=0, total=limit)

    stats = {
        "query": query,
        "source": source,
        "found_count": 0,
        "parsed_count": 0,
        "saved_count": 0,
        "embedded_count": 0,
        "content_queued_count": 0,
        "errors": [],
    }

    _safe_update_state(
        self,
        state="STARTED",
        meta={
            "query": query,
            "source": source,
            "current": 0,
            "total": limit,
            "status": f"Поиск статей по запросу '{query}'...",
        },
    )

    report, papers = await _run_parser_alpha(query=query, limit=limit, source=source)

    stats["found_count"] = int(report.get("raw_count") or len(papers))
    stats["parsed_count"] = len(papers)

    _safe_update_state(
        self,
        state="STARTED",
        meta={
            "query": query,
            "source": source,
            "current": len(papers),
            "total": limit,
            "status": f"Парсинг результатов ({len(papers)} найдено)...",
        },
    )

    async with async_session_maker() as db:
        paper_service = PaperService(db)

        for idx, paper in enumerate(papers):
            if _is_cancelled(self):
                return _mark_revoked(self, query=query, source=source, current=idx, total=len(papers))
            try:
                if idx % 5 == 0:
                    if _is_cancelled(self):
                        return _mark_revoked(self, query=query, source=source, current=idx, total=len(papers))

                    _safe_update_state(
                        self,
                        state="STARTED",
                        meta={
                            "query": query,
                            "source": source,
                            "current": idx,
                            "total": len(papers),
                            "saved_count": stats["saved_count"],
                            "content_queued_count": stats["content_queued_count"],
                            "status": f"Сохранение статей ({idx}/{len(papers)})...",
                        },
                    )

                paper_create = PaperCreate(
                    title=(_clean_text(paper.get("title")) or "Untitled"),
                    authors=[x for x in (_clean_text(a) for a in _to_str_list(paper.get("authors"))) if x],
                    publication_date=_normalize_publication_date(paper.get("publication_date")),
                    journal=_clean_text(paper.get("journal")),
                    doi=_clean_text(paper.get("doi")),
                    abstract=_clean_text(paper.get("abstract")),
                    full_text=_clean_text(paper.get("full_text")),
                    keywords=[x for x in (_clean_text(k) for k in _to_str_list(paper.get("keywords"))) if x],
                    source=(_clean_text(paper.get("source")) or source),
                    source_id=_clean_text(paper.get("source_id")),
                    url=(str(paper.get("url")).strip() if paper.get("url") else None),
                    pdf_url=(str(paper.get("pdf_url")).strip() if paper.get("pdf_url") else None),
                )
                saved_paper = await paper_service.create_paper(paper_create)
                stats["saved_count"] += 1

                if saved_paper.id:
                    try:
                        inferred_pdf_url = resolve_pdf_url(
                            source=saved_paper.source,
                            source_id=saved_paper.source_id,
                            url=saved_paper.url,
                        )
                        final_pdf_url = saved_paper.pdf_url or inferred_pdf_url

                        content_task = process_paper_content_task.delay(saved_paper.id)
                        await paper_service.update_paper(
                            saved_paper.id,
                            processing_status="queued_for_content_processing",
                            content_task_id=content_task.id,
                            pdf_url=final_pdf_url,
                            processing_error=None,
                        )
                        stats["content_queued_count"] += 1
                    except Exception as e:
                        logger.warning(
                            f"Не удалось поставить content-task для статьи {saved_paper.id}: {e}"
                        )

            except Exception as e:
                paper_title = str(paper.get("title") or "")[:50]
                error_msg = f"Error saving paper '{paper_title}...': {e}"
                logger.error(error_msg)
                stats["errors"].append(error_msg)
                await db.rollback()

    _safe_update_state(
        self,
        state="SUCCESS",
        meta={
            "query": query,
            "source": source,
            "current": len(papers),
            "total": len(papers),
            "saved_count": stats["saved_count"],
            "embedded_count": stats["embedded_count"],
            "content_queued_count": stats["content_queued_count"],
            "status": "Завершено",
        },
    )

    logger.info(
        f"Парсинг '{query}' ({source}): найдено={stats['found_count']}, "
        f"распарсено={stats['parsed_count']}, сохранено={stats['saved_count']}, "
        f"в очереди на AI/PDF={stats['content_queued_count']}"
    )

    return stats


@celery_app.task(bind=True)
def parse_multiple_queries_task(
    self,
    queries: list[str] = None,
    limit_per_query: int = 50,
    source: str = "CORE",
):
    if queries is None:
        if source == "arXiv":
            queries = ARXIV_SEARCH_QUERIES
        elif source == "CORE":
            queries = DEFAULT_SEARCH_QUERIES
        else:
            queries = EXTERNAL_SEARCH_QUERIES.get(source, DEFAULT_SEARCH_QUERIES)

    total_queries = len(queries)
    results = []
    total_saved = 0

    for idx, query in enumerate(queries):
        if _is_cancelled(self):
            return _mark_revoked(self, query=str(query), source=source, current=idx, total=total_queries)
        try:
            _safe_update_state(
                self,
                state="STARTED",
                meta={
                    "type": "multiple_queries",
                    "source": source,
                    "current_query": idx + 1,
                    "total_queries": total_queries,
                    "current_query_text": query,
                    "total_saved": total_saved,
                    "status": f"Обработка запроса {idx + 1}/{total_queries}: '{query}'",
                },
            )

            result = parse_papers_task(
                query=query,
                limit=limit_per_query,
                source=source,
            )
            results.append(result)
            total_saved += result.get("saved_count", 0)

        except Exception as e:
            logger.error(f"Ошибка при парсинге запроса '{query}': {e}")
            results.append({"query": query, "error": str(e)})

    _safe_update_state(
        self,
        state="SUCCESS",
        meta={
            "type": "multiple_queries",
            "source": source,
            "current_query": total_queries,
            "total_queries": total_queries,
            "total_saved": total_saved,
            "status": "Все запросы обработаны",
        },
    )

    return {
        "total_queries": total_queries,
        "source": source,
        "results": results,
        "total_saved": total_saved,
    }


@celery_app.task(bind=True)
def parse_all_sources_task(
    self,
    limit_per_query: int = 50,
    query: str | None = None,
    queries: list[str] | None = None,
):
    if _is_cancelled(self):
        return _mark_revoked(self, query="all_sources", source="CORE", current=0, total=len(AVAILABLE_SOURCES))

    logger.info("Запуск парсинга по всем источникам: {}", AVAILABLE_SOURCES)

    total_sources = len(AVAILABLE_SOURCES)
    results_by_source: dict[str, dict] = {}
    total_saved = 0

    if queries is not None:
        user_queries = [str(q).strip() for q in queries if str(q).strip()]
    else:
        user_queries = []
    if not user_queries and query is not None and str(query).strip():
        user_queries = [str(query).strip()]

    for idx, source in enumerate(AVAILABLE_SOURCES, start=1):
        _safe_update_state(
            self,
            state="STARTED",
            meta={
                "type": "all_sources",
                "current_source": idx,
                "total_sources": total_sources,
                "source": source,
                "status": f"Парсинг источника {source}...",
            },
        )

        if _is_cancelled(self):
            return _mark_revoked(self, query="all_sources", source=source, current=idx - 1, total=total_sources)

        if user_queries:
            source_queries = user_queries
        elif source == "arXiv":
            source_queries = ARXIV_SEARCH_QUERIES
        elif source == "CORE":
            source_queries = DEFAULT_SEARCH_QUERIES
        else:
            source_queries = EXTERNAL_SEARCH_QUERIES.get(source, DEFAULT_SEARCH_QUERIES)

        source_result = parse_multiple_queries_task(
            queries=source_queries,
            limit_per_query=limit_per_query,
            source=source,
        )
        results_by_source[source] = source_result
        total_saved += source_result.get("total_saved", 0)

    _safe_update_state(
        self,
        state="SUCCESS",
        meta={
            "type": "all_sources",
            "current_source": total_sources,
            "total_sources": total_sources,
            "total_saved": total_saved,
            "status": "Все источники обработаны",
        },
    )

    legacy_core = results_by_source.get("CORE", {"total_saved": 0, "results": []})
    legacy_arxiv = results_by_source.get("arXiv", {"total_saved": 0, "results": []})
    return {
        "core": legacy_core,
        "arxiv": legacy_arxiv,
        "sources": results_by_source,
        "total_saved": total_saved,
    }
