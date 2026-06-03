"""Small document-context helpers shared by Qwen Celery stages.

These helpers intentionally avoid DB/Celery imports. They only normalize small
payloads, paper metadata and content-part text so Qwen task wrappers can stay as
orchestration code.
"""

from __future__ import annotations

from typing import Any



def page_markdown_heading(page_start: int | None, page_end: int | None) -> str:
    if not page_start or not page_end:
        return "### Страница"
    if page_start == page_end:
        return f"### Страница {page_start}"
    return f"### Страницы {page_start}-{page_end}"


def qwen_input_text_for_part(part: Any) -> str:
    """Return sanitized block-aware text for Qwen markdown normalization."""


    from app.services.paper_content_part_service import get_qwen_projection_text_for_part

    return get_qwen_projection_text_for_part(part)


def merge_language_codes(existing: Any, *codes: str | None) -> list[str]:
    output: list[str] = []
    for item in list(existing or []) + [code for code in codes if code]:
        code = str(item or "").strip().lower()
        if not code or code in {"unknown", "none", "null"}:
            continue
        if code not in output:
            output.append(code)
    return output


def merge_quality_flags(current: Any, *, add: list[str] | None = None, remove: set[str] | None = None) -> list[str]:
    remove = remove or set()
    output: list[str] = []
    for item in list(current or []) + list(add or []):
        text = str(item or "").strip()
        if not text or text in remove or text in output:
            continue
        output.append(text)
    return output


def mark_ai_fields_stale(paper: Any) -> dict[str, Any]:
    return {
        "quality_flags": merge_quality_flags(
            getattr(paper, "quality_flags", None),
            add=["ai_fields_stale_after_text_update", "keywords_stale_after_text_update"],
        )
    }


def fresh_markdown_input_available(previous: dict[str, Any]) -> bool:
    """Return whether this chain produced fresh text safe for Qwen markdown.

    Qwen must not read arbitrary existing ``paper_content_parts`` after a failed
    PDF/extraction stage. Abstract-only content is enough for RU analysis, but it
    is not a PDF markdown-normalization input.
    """
    if not isinstance(previous, dict):
        return False
    if previous.get("markdown_input_available") is True:
        return True
    return bool(previous.get("fresh_content_available")) and str(previous.get("text_source") or "") in {
        "pdf",
        "fallback_fulltext",
    }


def paper_id_from_previous(previous: Any) -> int | None:
    if isinstance(previous, dict):
        value = previous.get("paper_id")
    else:
        value = previous
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def root_task_id(previous: Any, fallback: str | None = None) -> str | None:
    if isinstance(previous, dict):
        return str(
            previous.get("content_root_task_id")
            or previous.get("root_task_id")
            or previous.get("content_task_id")
            or fallback
            or ""
        ) or None
    return fallback


def merge_previous(previous: Any, **updates: Any) -> dict[str, Any]:
    if isinstance(previous, dict):
        payload = dict(previous)
    else:
        payload = {"paper_id": paper_id_from_previous(previous)}
    payload.update(updates)
    return payload


def count_pdf_pages_for_ai_ocr(pdf_bytes: bytes) -> int:
    try:
        import fitz
    except Exception:
        return 0
    doc = None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return int(len(doc))
    except Exception:
        return 0
    finally:
        try:
            if doc is not None:
                doc.close()
        except Exception:
            pass
