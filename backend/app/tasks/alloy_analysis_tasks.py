from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import func, select

from app.db.models.paper import Paper
from app.db.session import async_session_maker
from app.services.alloy_analysis_service import (
    ALLOY_ANALYSIS_RESULTS_DIR,
    build_alloy_analysis_prompt,
    extract_json_object,
)
from app.services.qwen_client import get_qwen_client
from app.tasks.async_runner import run_async
from app.tasks.celery_app import celery_app

MAX_ANALYSIS_TEXT_CHARS = 40000
RESULTS_DIR = ALLOY_ANALYSIS_RESULTS_DIR


def _parse_id_spec(id_spec: str | None) -> set[int] | None:
    if not id_spec or not id_spec.strip():
        return None

    ids: set[int] = set()
    for part in re.split(r"[,\s]+", id_spec.strip()):
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            start = int(left.strip())
            end = int(right.strip())
            if start > end:
                start, end = end, start
            ids.update(range(start, end + 1))
        else:
            ids.add(int(part))
    return ids


def _chunk_text(text: str, size: int = MAX_ANALYSIS_TEXT_CHARS) -> list[str]:
    clean = (text or "").strip()
    if not clean:
        return []
    return [clean[index:index + size] for index in range(0, len(clean), size)]


async def _load_target_papers(
    id_spec: str | None,
    sources: list[str],
    limit: int,
) -> list[Paper]:
    ids = _parse_id_spec(id_spec)
    stmt = select(Paper).where(Paper.full_text.is_not(None), func.length(Paper.full_text) > 0)

    if ids is not None:
        if not ids:
            return []
        stmt = stmt.where(Paper.id.in_(sorted(ids)))

    normalized_sources = [source for source in sources if source]
    if normalized_sources:
        stmt = stmt.where(Paper.source.in_(normalized_sources))

    stmt = stmt.order_by(Paper.id.asc()).limit(limit)

    async with async_session_maker() as db:
        result = await db.execute(stmt)
        return list(result.scalars().all())


def _merge_extractions(document_id: str, chunk_payloads: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    warnings: list[str] = []

    for payload in chunk_payloads:
        extraction = payload.get("extraction") if isinstance(payload, dict) else None
        if not isinstance(extraction, dict):
            continue
        chunk_items = extraction.get("items")
        if isinstance(chunk_items, list):
            items.extend(item for item in chunk_items if isinstance(item, dict))
        metadata = extraction.get("extraction_metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("warnings"), list):
            warnings.extend(str(item) for item in metadata["warnings"])

    return {
        "extraction_metadata": {
            "total_alloys_found": len(items),
            "document_id": document_id,
            "warnings": warnings,
        },
        "items": items,
    }


def _save_json(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


@celery_app.task(bind=True, name="app.tasks.alloy_analysis.extract_alloys")
def extract_alloys_task(self, document_id: str, text: str) -> dict[str, Any]:
    task_id = getattr(getattr(self, "request", None), "id", None)
    self.update_state(
        state="STARTED",
        meta={"stage": "qwen_analysis", "document_id": document_id, "task_id": task_id},
    )

    prompt = build_alloy_analysis_prompt(document_id, text)
    if len(prompt) > 50000:
        raise ValueError("Текст слишком длинный для Qwen: максимум 50000 символов вместе с промптом")

    qwen_client = get_qwen_client()
    qwen_result = qwen_client.send_message(
        prompt,
        thinking_enabled=True,
        search_enabled=False,
        auto_continue=True,
        timeout=1000.0,
    )

    if qwen_result.get("error"):
        raise RuntimeError(str(qwen_result["error"]))

    raw_response = qwen_result.get("response", "")
    extraction = extract_json_object(raw_response)
    extraction["extraction_metadata"]["document_id"] = document_id.strip() or "unknown"

    return {
        "status": "completed",
        "document_id": document_id,
        "extraction": extraction,
        "raw_response": raw_response,
        "session_id": qwen_result.get("session_id"),
        "message_id": qwen_result.get("message_id"),
        "continue_count": qwen_result.get("continue_count", 0),
    }


@celery_app.task(bind=True, name="app.tasks.alloy_analysis.analyze_papers_alloys")
def analyze_papers_alloys_task(
    self,
    id_spec: str | None = None,
    sources: list[str] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    task_id = getattr(getattr(self, "request", None), "id", None)
    sources = sources or []
    papers = run_async(_load_target_papers(id_spec, sources, limit))
    qwen_client = get_qwen_client()
    results: list[dict[str, Any]] = []
    total_chunks = sum(len(_chunk_text(paper.full_text or "")) for paper in papers)
    processed_chunks = 0

    self.update_state(
        state="STARTED",
        meta={
            "stage": "selected_papers",
            "stage_label": "Статьи выбраны",
            "task_id": task_id,
            "total": len(papers),
            "current": 0,
            "total_chunks": total_chunks,
            "processed_chunks": 0,
        },
    )

    for paper_index, paper in enumerate(papers, start=1):
        chunks = _chunk_text(paper.full_text or "")
        paper_dir = RESULTS_DIR / f"paper_{paper.id}"
        chunk_payloads: list[dict[str, Any]] = []
        chunk_files: list[str] = []
        paper_error: str | None = None

        self.update_state(
            state="STARTED",
            meta={
                "stage": "paper_analysis",
                "task_id": task_id,
                "current": paper_index,
                "total": len(papers),
                "paper_id": paper.id,
                "paper_title": paper.title,
                "chunks": len(chunks),
                "current_chunk": 0,
                "processed_chunks": processed_chunks,
                "total_chunks": total_chunks,
                "stage_label": "Начат анализ статьи",
            },
        )

        for chunk_index, chunk in enumerate(chunks, start=1):
            document_id = f"paper-{paper.id}-chunk-{chunk_index}"
            try:
                self.update_state(
                    state="STARTED",
                    meta={
                        "stage": "chunk_analysis",
                        "stage_label": "Анализ части текста",
                        "task_id": task_id,
                        "current": paper_index,
                        "total": len(papers),
                        "paper_id": paper.id,
                        "paper_title": paper.title,
                        "current_chunk": chunk_index,
                        "chunks": len(chunks),
                        "processed_chunks": processed_chunks,
                        "total_chunks": total_chunks,
                    },
                )
                prompt = build_alloy_analysis_prompt(document_id, chunk)
                qwen_result = qwen_client.send_message(
                    prompt,
                    thinking_enabled=True,
                    search_enabled=False,
                    auto_continue=True,
                    timeout=1000.0,
                )
                if qwen_result.get("error"):
                    raise RuntimeError(str(qwen_result["error"]))

                raw_response = qwen_result.get("response", "")
                extraction = extract_json_object(raw_response)
                extraction["extraction_metadata"]["document_id"] = document_id
                payload = {
                    "paper_id": paper.id,
                    "paper_title": paper.title,
                    "source": paper.source,
                    "chunk_index": chunk_index,
                    "chunks_total": len(chunks),
                    "extraction": extraction,
                    "raw_response": raw_response,
                    "session_id": qwen_result.get("session_id"),
                    "message_id": qwen_result.get("message_id"),
                }
                chunk_path = paper_dir / f"chunk_{chunk_index}.json"
                chunk_files.append(_save_json(chunk_path, payload))
                chunk_payloads.append(payload)
            except Exception as exc:
                paper_error = str(exc)
                chunk_payloads.append(
                    {
                        "paper_id": paper.id,
                        "paper_title": paper.title,
                        "source": paper.source,
                        "chunk_index": chunk_index,
                        "error": paper_error,
                    }
                )
            finally:
                processed_chunks += 1
                self.update_state(
                    state="STARTED",
                    meta={
                        "stage": "chunk_completed",
                        "stage_label": "Часть текста завершена",
                        "task_id": task_id,
                        "current": paper_index,
                        "total": len(papers),
                        "paper_id": paper.id,
                        "paper_title": paper.title,
                        "current_chunk": chunk_index,
                        "chunks": len(chunks),
                        "processed_chunks": processed_chunks,
                        "total_chunks": total_chunks,
                    },
                )

        self.update_state(
            state="STARTED",
            meta={
                "stage": "merging_article_json",
                "stage_label": "Сборка итогового JSON статьи",
                "task_id": task_id,
                "current": paper_index,
                "total": len(papers),
                "paper_id": paper.id,
                "paper_title": paper.title,
                "processed_chunks": processed_chunks,
                "total_chunks": total_chunks,
            },
        )
        summary = _merge_extractions(f"paper-{paper.id}", chunk_payloads)
        summary_payload = {
            "paper_id": paper.id,
            "paper_title": paper.title,
            "source": paper.source,
            "url": paper.url,
            "text_length": len(paper.full_text or ""),
            "chunks_total": len(chunks),
            "chunk_files": chunk_files,
            "summary": summary,
            "error": paper_error,
        }
        summary_path = _save_json(paper_dir / "summary.json", summary_payload)

        results.append(
            {
                "paper_id": paper.id,
                "paper_title": paper.title,
                "source": paper.source,
                "text_length": len(paper.full_text or ""),
                "chunks_total": len(chunks),
                "items_count": len(summary.get("items", [])),
                "warnings_count": len(summary.get("extraction_metadata", {}).get("warnings", [])),
                "summary_path": summary_path,
                "chunk_files": chunk_files,
                "extraction": summary,
                "error": paper_error,
            }
        )

    return {
        "status": "completed",
        "id_spec": id_spec,
        "sources": sources,
        "total": len(papers),
        "processed": len(results),
        "results": results,
        "results_dir": str(RESULTS_DIR),
    }
