"""Celery tasks for scientific paper parsing via parser_alpha."""

import asyncio
import html
import json
import os
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

RUSSIAN_SEARCH_QUERIES = [
    "никелевые сплавы",
    "суперсплавы",
    "жаропрочные сплавы",
    "никелевые суперсплавы",
    "коррозия никелевых сплавов",
]

RUSSIAN_PATENT_SEARCH_QUERIES = [
    "никелевый сплав",
    "жаропрочный сплав",
    "суперсплав",
    "сплав на основе никеля",
    "коррозионностойкий никелевый сплав",
]

EXTERNAL_SEARCH_QUERIES = {
    "OpenAlex": DEFAULT_SEARCH_QUERIES,
    "Crossref": DEFAULT_SEARCH_QUERIES,
    "EuropePMC": DEFAULT_SEARCH_QUERIES,
    "CyberLeninka": RUSSIAN_SEARCH_QUERIES,
    "eLibrary": RUSSIAN_SEARCH_QUERIES,
    "Rospatent": RUSSIAN_PATENT_SEARCH_QUERIES,
    "FreePatent": RUSSIAN_PATENT_SEARCH_QUERIES,
    "PATENTSCOPE": DEFAULT_SEARCH_QUERIES,
}

AVAILABLE_SOURCES = ["CORE", "arXiv", *list(EXTERNAL_SEARCH_QUERIES.keys())]

PARSER_ALPHA_ROOT = Path(__file__).resolve().parents[3] / "parser_alpha"
PARSER_ALPHA_RUNNER = PARSER_ALPHA_ROOT / "run_parser.py"
PARSER_ALPHA_DATA_DIR = PARSER_ALPHA_ROOT / "data"
PARSER_ALPHA_VENV_PYTHON = PARSER_ALPHA_ROOT / ".venv" / "Scripts" / "python.exe"
PARSER_ALPHA_DEFAULT_TIMEOUT_SECONDS = 1800.0


def _get_parser_alpha_timeout() -> float:
    """Timeout for the whole parser_alpha subprocess.

    Individual HTTP clients inside parser_alpha have their own per-request timeout,
    but the backend Celery task also needs a hard boundary. Otherwise a stuck
    source/browser/session can keep a regular worker busy until Celery kills the
    process by soft/hard time limit, leaving poorer diagnostics in the UI.
    """
    raw = (
        os.getenv("PARSER_ALPHA_SUBPROCESS_TIMEOUT")
        or os.getenv("PARSER_TASK_TIMEOUT_SECONDS")
        or str(PARSER_ALPHA_DEFAULT_TIMEOUT_SECONDS)
    )
    try:
        timeout = float(str(raw).strip())
    except (TypeError, ValueError):
        return PARSER_ALPHA_DEFAULT_TIMEOUT_SECONDS
    return max(30.0, timeout)


def _format_parser_output_for_error(stdout_text: str, stderr_text: str, limit: int = 1200) -> str:
    combined = "\n".join(part for part in [stderr_text, stdout_text] if part).strip()
    if not combined:
        return "<empty output>"
    return combined[-limit:]

_HTML_TAG_RE = re.compile(r"<[^>]+>")

_SCALAR_TEXT_OBJECT_KEYS = (
    "value",
    "text",
    "content",
    "title",
    "name",
    "display_name",
    "displayName",
    "fullName",
    "authorName",
    "url",
    "URL",
    "href",
    "id",
    "doi",
    "date",
    "publishedDate",
    "publication_date",
    "year",
)


def _first_scalar_text_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, datetime)):
        return value
    if isinstance(value, dict):
        for key in _SCALAR_TEXT_OBJECT_KEYS:
            if key in value:
                candidate = _first_scalar_text_value(value.get(key))
                if candidate not in (None, ""):
                    return candidate
        for item in value.values():
            candidate = _first_scalar_text_value(item)
            if candidate not in (None, ""):
                return candidate
        return None
    if isinstance(value, (list, tuple, set)):
        for item in value:
            candidate = _first_scalar_text_value(item)
            if candidate not in (None, ""):
                return candidate
        return None
    return value

_CONTENT_PROCESSING_ACTIVE_OR_DONE_STATUSES = {
    "queued_for_content_processing",
    "pdf_pending",
    "downloading_pdf",
    "pdf_downloaded",
    "pdf_parsed",
    "fulltext_fallback_parsed",
    "formatting_markdown",
    "analyzing_ru",
    "extracting_keywords",
    "indexing_vector",
    "ready",
    "ready_with_fallback",
}


def _should_queue_content_processing(paper: Any) -> bool:
    """Return True only when paper still needs content/Qwen post-processing.

    Re-parsing the same source can return an existing DB row. Without this guard we
    enqueue expensive PDF/Qwen processing again for papers that are already queued,
    in progress, or ready.
    """
    status = str(getattr(paper, "processing_status", "") or "").strip().lower()
    task_id = str(getattr(paper, "content_task_id", "") or "").strip()

    if status in _CONTENT_PROCESSING_ACTIVE_OR_DONE_STATUSES:
        return False
    if task_id and status != "failed":
        return False
    return True


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
        "updated_count": 0,
        "duplicate_count": 0,
        "embedded_count": 0,
        "content_queued_count": 0,
        "content_skipped_count": 0,
        "total_saved": 0,
        "total_content_queued": 0,
        "total_content_skipped": 0,
        "errors": ["cancelled"],
    }


def _extract_json_payload(stdout_text: str) -> dict[str, Any]:
    text = (stdout_text or "").strip()
    if not text:
        raise RuntimeError("parser_alpha produced empty stdout")

    decoder = json.JSONDecoder()
    last_valid: dict[str, Any] | None = None
    last_error: Exception | None = None

    # parser_alpha with --explain prints a JSON object, but some libraries may
    # write extra text before it. Try every JSON-object start and keep the last
    # object that looks like the parser report. This is safer than slicing from
    # first '{' to last '}', which breaks when logs contain braces.
    for idx, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(payload, dict):
            last_valid = payload
            if payload.get("out_path"):
                return payload

    if last_valid is not None:
        return last_valid

    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(f"parser_alpha returned unexpected payload{detail}: {text[:300]}")

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

    timeout_seconds = _get_parser_alpha_timeout()
    try:
        process = subprocess.run(
            cmd,
            cwd=str(PARSER_ALPHA_ROOT.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        out_text = exc.stdout or ""
        err_text = exc.stderr or ""
        if isinstance(out_text, bytes):
            out_text = out_text.decode("utf-8", errors="replace")
        if isinstance(err_text, bytes):
            err_text = err_text.decode("utf-8", errors="replace")
        raise RuntimeError(
            "parser_alpha timed out "
            f"after {timeout_seconds:.0f}s for source={source}, query='{query}'. "
            f"Last output: {_format_parser_output_for_error(out_text, err_text)}"
        ) from exc

    out_text = process.stdout or ""
    err_text = process.stderr or ""

    if process.returncode != 0:
        raise RuntimeError(
            f"parser_alpha failed ({process.returncode}) for source={source}, query='{query}': "
            f"{_format_parser_output_for_error(out_text, err_text)}"
        )

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


_LIST_TEXT_OBJECT_KEYS = (
    "name",
    "fullName",
    "displayName",
    "display_name",
    "authorName",
    "value",
    "text",
    "title",
    "label",
    "term",
    "subject",
)


def _dedupe_str_list(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _to_str_list(value: Any, *, split_commas: bool = False) -> list[str]:
    """Normalize parser JSON list fields before PaperCreate construction.

    Parser records can contain legacy strings, JSON-encoded lists, or objects like
    {"name": "Alice Smith"}.  Flatten objects by semantic keys instead of
    saving Python reprs.  Authors keep commas inside names; keywords/flags can opt
    into comma splitting.
    """
    if value is None:
        return []
    if isinstance(value, dict):
        for key in _LIST_TEXT_OBJECT_KEYS:
            if key in value:
                extracted = _to_str_list(value.get(key), split_commas=split_commas)
                if extracted:
                    return extracted
        output: list[str] = []
        for item in value.values():
            output.extend(_to_str_list(item, split_commas=split_commas))
        return _dedupe_str_list(output)
    if isinstance(value, (list, tuple, set)):
        output: list[str] = []
        for item in value:
            output.extend(_to_str_list(item, split_commas=split_commas))
        return _dedupe_str_list(output)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, (list, tuple, set, dict)):
                return _to_str_list(parsed, split_commas=split_commas)
            if isinstance(parsed, str) and parsed.strip():
                return [parsed.strip()]
        except Exception:
            pass
        pattern = r"[;,\n]+" if split_commas else r"[;\n]+"
        parts = [part.strip() for part in re.split(pattern, text) if part.strip()]
        return parts or [text]
    text = str(value).strip()
    return [text] if text else []


def _to_str_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, item in value.items():
        key_text = _clean_text(key)
        item_text = _clean_text(item)
        if key_text and item_text:
            result[key_text] = item_text
    return result


def _normalize_parse_confidence(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if 1 < confidence <= 100:
        confidence = confidence / 100
    return max(0.0, min(1.0, confidence))


def _clean_text(value: Any) -> str | None:
    value = _first_scalar_text_value(value)
    if value is None:
        return None
    text = html.unescape(str(value))
    text = _HTML_TAG_RE.sub(" ", text)
    text = " ".join(text.split()).strip()
    return text or None


def _normalize_publication_date(value: Any) -> datetime | None:
    value = _first_scalar_text_value(value)
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
            for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y"):
                try:
                    dt = datetime.strptime(raw[:10] if fmt == "%Y-%m-%d" else raw, fmt)
                    break
                except ValueError:
                    continue
            if dt is None:
                return None
    else:
        return None

    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _run_parse_query_for_task(task, query: str, limit: int, source: str) -> dict:
    """Run one parser query using the current Celery task context.

    Do not call another Celery task as a plain function from aggregate tasks:
    it creates a nested task context without the parent task id, so progress and
    cancellation become unreliable. This helper keeps all state updates attached
    to the task that the user sees in the UI/Flower.
    """
    if _is_cancelled(task):
        return _mark_revoked(task, query=query, source=source, current=0, total=limit)

    _safe_update_state(
        task,
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
    return run_async(_parse_async(task, query, limit, source))


def _parse_queries_for_task(
    task,
    *,
    queries: list[str],
    limit_per_query: int,
    source: str,
) -> dict:
    """Run several queries sequentially inside one visible Celery task."""
    total_queries = len(queries)
    results: list[dict] = []
    total_saved = 0
    total_content_queued = 0
    total_content_skipped = 0
    total_updated = 0
    total_duplicates = 0

    for idx, query in enumerate(queries):
        if _is_cancelled(task):
            return _mark_revoked(task, query=str(query), source=source, current=idx, total=total_queries)
        try:
            _safe_update_state(
                task,
                state="STARTED",
                meta={
                    "type": "multiple_queries",
                    "source": source,
                    "current_query": idx + 1,
                    "total_queries": total_queries,
                    "current_query_text": query,
                    "total_saved": total_saved,
                    "total_content_queued": total_content_queued,
                    "total_content_skipped": total_content_skipped,
                    "total_updated": total_updated,
                    "total_duplicates": total_duplicates,
                    "status": f"Обработка запроса {idx + 1}/{total_queries}: '{query}'",
                },
            )

            result = _run_parse_query_for_task(
                task,
                query=query,
                limit=limit_per_query,
                source=source,
            )
            results.append(result)
            total_saved += int(result.get("saved_count", 0) or 0)
            total_content_queued += int(result.get("content_queued_count", 0) or 0)
            total_content_skipped += int(result.get("content_skipped_count", 0) or 0)
            total_updated += int(result.get("updated_count", 0) or 0)
            total_duplicates += int(result.get("duplicate_count", 0) or 0)

            if result.get("status") == "revoked":
                break

        except Exception as e:
            logger.error(f"Ошибка при парсинге запроса '{query}': {e}")
            results.append({"query": query, "error": str(e)})

    _safe_update_state(
        task,
        state="SUCCESS",
        meta={
            "type": "multiple_queries",
            "source": source,
            "current_query": total_queries,
            "total_queries": total_queries,
            "total_saved": total_saved,
            "saved_count": total_saved,
            "total_content_queued": total_content_queued,
            "content_queued_count": total_content_queued,
            "total_content_skipped": total_content_skipped,
            "content_skipped_count": total_content_skipped,
            "total_updated": total_updated,
            "updated_count": total_updated,
            "total_duplicates": total_duplicates,
            "duplicate_count": total_duplicates,
            "status": "Все запросы обработаны",
        },
    )

    return {
        "total_queries": total_queries,
        "source": source,
        "results": results,
        "total_saved": total_saved,
        "saved_count": total_saved,
        "total_content_queued": total_content_queued,
        "content_queued_count": total_content_queued,
        "total_content_skipped": total_content_skipped,
        "content_skipped_count": total_content_skipped,
        "total_updated": total_updated,
        "updated_count": total_updated,
        "total_duplicates": total_duplicates,
        "duplicate_count": total_duplicates,
    }


@celery_app.task(bind=True)
def parse_papers_task(
    self,
    query: str,
    limit: int = 50,
    source: str = "CORE",
):
    try:
        return _run_parse_query_for_task(self, query=query, limit=limit, source=source)
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
        "updated_count": 0,
        "duplicate_count": 0,
        "embedded_count": 0,
        "content_queued_count": 0,
        "content_skipped_count": 0,
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
                            "updated_count": stats["updated_count"],
                            "duplicate_count": stats["duplicate_count"],
                            "content_queued_count": stats["content_queued_count"],
                            "content_skipped_count": stats["content_skipped_count"],
                            "status": f"Сохранение статей ({idx}/{len(papers)})...",
                        },
                    )

                paper_create = PaperCreate(
                    title=(_clean_text(paper.get("title")) or "Untitled"),
                    authors=[x for x in (_clean_text(a) for a in _to_str_list(paper.get("authors"), split_commas=False)) if x],
                    publication_date=_normalize_publication_date(paper.get("publication_date")),
                    journal=_clean_text(paper.get("journal")),
                    doi=_clean_text(paper.get("doi")),
                    abstract=_clean_text(paper.get("abstract")),
                    full_text=_clean_text(paper.get("full_text")),
                    keywords=[x for x in (_clean_text(k) for k in _to_str_list(paper.get("keywords"), split_commas=True)) if x],
                    source=(_clean_text(paper.get("source")) or source),
                    source_id=_clean_text(paper.get("source_id")),
                    url=_clean_text(paper.get("url")),
                    pdf_url=_clean_text(paper.get("pdf_url")),
                    parse_confidence=_normalize_parse_confidence(paper.get("parse_confidence")),
                    provenance=_to_str_dict(paper.get("provenance")),
                    quality_flags=[
                        x
                        for x in (_clean_text(flag) for flag in _to_str_list(paper.get("quality_flags"), split_commas=True))
                        if x
                    ],
                    schema_version=_clean_text(paper.get("schema_version")) or "2.0",
                )
                saved_paper = await paper_service.create_paper(paper_create)
                was_created = bool(getattr(saved_paper, "_nickelfront_created", True))
                was_updated_existing = bool(getattr(saved_paper, "_nickelfront_updated", False))
                if was_created:
                    stats["saved_count"] += 1
                elif was_updated_existing:
                    stats["updated_count"] += 1
                else:
                    stats["duplicate_count"] += 1

                if saved_paper.id:
                    if not _should_queue_content_processing(saved_paper):
                        stats["content_skipped_count"] += 1
                        logger.debug(
                            "Content/Qwen processing skipped for existing paper {}: status={}, task_id={}",
                            saved_paper.id,
                            getattr(saved_paper, "processing_status", None),
                            getattr(saved_paper, "content_task_id", None),
                        )
                    else:
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
            "updated_count": stats["updated_count"],
            "duplicate_count": stats["duplicate_count"],
            "embedded_count": stats["embedded_count"],
            "content_queued_count": stats["content_queued_count"],
            "content_skipped_count": stats["content_skipped_count"],
            "status": "Завершено",
        },
    )

    logger.info(
        f"Парсинг '{query}' ({source}): найдено={stats['found_count']}, "
        f"распарсено={stats['parsed_count']}, новых={stats['saved_count']}, "
        f"обновлено={stats['updated_count']}, дублей={stats['duplicate_count']}, "
        f"в очереди на AI/PDF={stats['content_queued_count']}, "
        f"пропущено AI/PDF={stats['content_skipped_count']}"
    )

    return stats


@celery_app.task(bind=True)
def parse_multiple_queries_task(
    self,
    queries: list[str] = None,
    limit_per_query: int = 50,
    source: str = "CORE",
):
    try:
        if queries is None:
            if source == "arXiv":
                queries = ARXIV_SEARCH_QUERIES
            elif source == "CORE":
                queries = DEFAULT_SEARCH_QUERIES
            else:
                queries = EXTERNAL_SEARCH_QUERIES.get(source, DEFAULT_SEARCH_QUERIES)

        normalized_queries = [str(q).strip() for q in queries if str(q).strip()]
        return _parse_queries_for_task(
            self,
            queries=normalized_queries,
            limit_per_query=limit_per_query,
            source=source,
        )
    finally:
        task_id = _get_task_id(self)
        if task_id:
            clear_cancel_flag(task_id)


@celery_app.task(bind=True)
def parse_all_sources_task(
    self,
    limit_per_query: int = 50,
    query: str | None = None,
    queries: list[str] | None = None,
):
    try:
        if _is_cancelled(self):
            return _mark_revoked(self, query="all_sources", source="CORE", current=0, total=len(AVAILABLE_SOURCES))

        logger.info("Запуск парсинга по всем источникам: {}", AVAILABLE_SOURCES)

        total_sources = len(AVAILABLE_SOURCES)
        results_by_source: dict[str, dict] = {}
        total_saved = 0
        total_content_queued = 0
        total_content_skipped = 0
        total_updated = 0
        total_duplicates = 0

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
                    "total_saved": total_saved,
                    "total_content_queued": total_content_queued,
                    "total_content_skipped": total_content_skipped,
                    "total_updated": total_updated,
                    "total_duplicates": total_duplicates,
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

            source_result = _parse_queries_for_task(
                self,
                queries=source_queries,
                limit_per_query=limit_per_query,
                source=source,
            )
            results_by_source[source] = source_result
            total_saved += int(source_result.get("total_saved", 0) or 0)
            total_content_queued += int(source_result.get("total_content_queued", 0) or 0)
            total_content_skipped += int(source_result.get("total_content_skipped", 0) or 0)
            total_updated += int(source_result.get("total_updated", 0) or source_result.get("updated_count", 0) or 0)
            total_duplicates += int(source_result.get("total_duplicates", 0) or source_result.get("duplicate_count", 0) or 0)

            if source_result.get("status") == "revoked":
                break

        _safe_update_state(
            self,
            state="SUCCESS",
            meta={
                "type": "all_sources",
                "current_source": total_sources,
                "total_sources": total_sources,
                "total_saved": total_saved,
                "saved_count": total_saved,
                "total_content_queued": total_content_queued,
                "content_queued_count": total_content_queued,
                "total_content_skipped": total_content_skipped,
                "content_skipped_count": total_content_skipped,
                "total_updated": total_updated,
                "updated_count": total_updated,
                "total_duplicates": total_duplicates,
                "duplicate_count": total_duplicates,
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
            "saved_count": total_saved,
            "total_content_queued": total_content_queued,
            "content_queued_count": total_content_queued,
            "total_content_skipped": total_content_skipped,
            "content_skipped_count": total_content_skipped,
            "total_updated": total_updated,
            "updated_count": total_updated,
            "total_duplicates": total_duplicates,
            "duplicate_count": total_duplicates,
        }
    finally:
        task_id = _get_task_id(self)
        if task_id:
            clear_cancel_flag(task_id)
