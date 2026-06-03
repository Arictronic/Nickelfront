from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger

from app.core.config import settings
from app.services.paper_content_service import extract_pdf_page_items, extract_pdf_page_items_mypdf
from app.services.qwen_document.cleaning import clean_regenerated_markdown_response
from app.services.qwen_document.prompts import build_article_markdown_image_regeneration_prompt


def normalize_regeneration_mode(value: Any) -> str:
    mode = str(value or "text").strip().lower()
    return mode if mode in {"text", "image", "auto", "mypdf", "ai"} else "text"


def build_image_regeneration_options(
    *,
    qwen_settings: dict[str, Any],
    pdf_markdown_settings: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    return {
        "parser_mode": "ai",
        "force_strategy": "ai",
        "extraction_strategy": "ai",
        "selected_strategy": "ai",
        "ai_mode": "force",
        "ai_enabled": True,
        "ai_provider": str(pdf_markdown_settings.get("ai_provider") or "qwen"),
        "ai_model": str(pdf_markdown_settings.get("ai_model") or qwen_settings.get("model") or settings.QWEN_MODEL),
        "ai_render_dpi": int(pdf_markdown_settings.get("ai_render_dpi") or 220),
        "ai_page_image_format": str(pdf_markdown_settings.get("ai_page_image_format") or "png"),
        "ai_timeout_sec": float(timeout or pdf_markdown_settings.get("ai_timeout_sec") or settings.QWEN_QUEUE_TIMEOUT),
        "ai_delete_temp_images": bool(pdf_markdown_settings.get("ai_delete_temp_images", True)),
    }


def recognize_part_pdf_pages_as_text(
    *,
    pdf_path: str,
    paper_id: int,
    part_id: int,
    page_start: int,
    page_end: int,
    options: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    path = Path(str(pdf_path or ""))
    if not path.exists() or not path.is_file():
        raise RuntimeError("pdf_file_not_found")

    try:
        from app.services.pdf_parser.ai import AIPageRecognitionService
    except Exception as exc:
        raise RuntimeError(f"ai_page_recognition_unavailable:{type(exc).__name__}:{exc}") from exc

    pdf_bytes = path.read_bytes()
    service = AIPageRecognitionService()
    service.reset_document_session()

    pages: list[dict[str, Any]] = []
    warnings: list[str] = []
    text_blocks: list[str] = []
    for page_number in range(int(page_start), int(page_end) + 1):
        result = service.recognize_page(
            file_bytes=pdf_bytes,
            page_number=page_number,
            opts=options,
        )
        page_text = str(result.text or "").strip()
        pages.append(
            {
                "page_number": page_number,
                "chars": len(page_text),
                "status": result.status,
                "reason": result.reason,
                "confidence": float(result.confidence or 0.0),
                "provider": result.provider,
                "model": result.model,
                "warnings": list(result.warnings or []),
            }
        )
        warnings.extend(str(item) for item in (result.warnings or []) if item)
        if page_text:
            text_blocks.append(f"[Страница {page_number}]\n{page_text}")

    text = "\n\n".join(text_blocks).strip()
    return text, {
        "regeneration_mode": "image",
        "paper_id": paper_id,
        "part_id": part_id,
        "pdf_path": str(path),
        "page_start": page_start,
        "page_end": page_end,
        "pages": pages,
        "text_chars": len(text),
        "warnings": sorted(set(warnings)),
        "ai_session_id": service.session_id or "",
    }


def extract_part_pdf_pages_as_text(
    *,
    pdf_path: str,
    paper_id: int,
    part_id: int,
    page_start: int,
    page_end: int,
    mode: str,
    pdf_markdown_settings: dict[str, Any],
    qwen_settings: dict[str, Any],
    timeout: float,
) -> tuple[str, dict[str, Any]]:
    """Re-extract only selected PDF pages for the raw-text layer."""
    normalized_mode = "ai" if mode == "image" else mode
    if normalized_mode == "ai":
        return recognize_part_pdf_pages_as_text(
            pdf_path=pdf_path,
            paper_id=paper_id,
            part_id=part_id,
            page_start=page_start,
            page_end=page_end,
            options=build_image_regeneration_options(
                qwen_settings=qwen_settings,
                pdf_markdown_settings=pdf_markdown_settings,
                timeout=timeout,
            ),
        )

    path = Path(str(pdf_path or ""))
    if not path.exists() or not path.is_file():
        raise RuntimeError("pdf_file_not_found")

    pdf_bytes = path.read_bytes()
    use_mypdf = normalized_mode == "mypdf"
    options = {
        "parser_mode": "mypdf" if use_mypdf else "auto",
        "ocr_mode": "off" if use_mypdf else str(pdf_markdown_settings.get("ocr_mode") or "auto"),
        "ai_mode": "off",
        "force_strategy": "mypdf" if use_mypdf else "",
        "extraction_mode": "mypdf" if use_mypdf else "auto",
        "detect_columns": False if use_mypdf else pdf_markdown_settings.get("detect_columns", True),
        "extract_tables": False if use_mypdf else pdf_markdown_settings.get("extract_tables", True),
        "remove_headers_footers": pdf_markdown_settings.get("remove_headers_footers", True),
        "merge_hyphenated_words": pdf_markdown_settings.get("merge_hyphenated_words", True),
        "normalize_math": pdf_markdown_settings.get("normalize_math", True),
        "mark_formula_candidates": False if use_mypdf else pdf_markdown_settings.get("mark_formula_candidates", True),
        "ocr_enabled": False if use_mypdf else str(pdf_markdown_settings.get("ocr_mode") or "auto").lower() != "off",
        "ocr_force": False if use_mypdf else str(pdf_markdown_settings.get("ocr_mode") or "auto").lower() == "force",
        "ocr_engine": pdf_markdown_settings.get("ocr_engine", "auto"),
        "ocr_dpi": pdf_markdown_settings.get("ocr_dpi", 220),
        "ocr_languages": pdf_markdown_settings.get("ocr_languages", "eng+rus"),
        "ai_enabled": False,
        "min_text_chars": pdf_markdown_settings.get("min_text_chars", 300),
        "max_page_chars": pdf_markdown_settings.get("max_page_chars", 60000),
    }
    page_items = extract_pdf_page_items_mypdf(pdf_bytes, options) if use_mypdf else extract_pdf_page_items(pdf_bytes, options)
    selected = [
        item
        for item in page_items
        if page_start <= int(item.get("page_number") or item.get("page") or 0) <= page_end
    ]
    warnings: list[str] = []
    scores: list[float] = []
    methods: list[str] = []
    text_blocks: list[str] = []
    pages: list[dict[str, Any]] = []
    for item in selected:
        page_number = int(item.get("page_number") or item.get("page") or 0)
        page_text = str(item.get("text") or "").strip()
        if not page_text:
            continue
        method = str(item.get("method") or ("mypdf_text_layer" if use_mypdf else "auto"))
        methods.append(method)
        try:
            scores.append(float(item.get("quality_score")))
        except (TypeError, ValueError):
            pass
        item_warnings = [str(w) for w in (item.get("warnings") or []) if w]
        warnings.extend(item_warnings)
        pages.append(
            {
                "page_number": page_number,
                "chars": len(page_text),
                "method": method,
                "quality_score": item.get("quality_score"),
                "warnings": item_warnings,
            }
        )
        text_blocks.append(f"[Страница {page_number}]\n{page_text}")

    text = "\n\n".join(text_blocks).strip()
    quality_score = round(sum(scores) / len(scores), 3) if scores else (0.8 if use_mypdf and text else None)
    return text, {
        "regeneration_mode": normalized_mode,
        "paper_id": paper_id,
        "part_id": part_id,
        "pdf_path": str(path),
        "page_start": page_start,
        "page_end": page_end,
        "pages": pages,
        "text_chars": len(text),
        "method": methods[0] if methods and len(set(methods)) == 1 else ("mixed" if methods else ("mypdf_text_layer" if use_mypdf else "auto")),
        "quality_score": quality_score,
        "warnings": sorted(set(warnings)),
        "parser_mode": normalized_mode,
        "extraction_mode": normalized_mode,
    }


def _render_pdf_page_to_image(
    *,
    pdf_bytes: bytes,
    page_number: int,
    temp_dir: Path,
    dpi: int,
    image_format: str,
) -> Path:
    try:
        import fitz
    except Exception as exc:
        raise RuntimeError(f"fitz_unavailable:{exc}") from exc

    image_format = image_format if image_format in {"png", "jpg", "jpeg"} else "png"
    suffix = ".jpg" if image_format == "jpeg" else f".{image_format}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    doc = None
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_index = max(0, int(page_number) - 1)
        if page_index >= len(doc):
            raise RuntimeError(f"page_index_out_of_range:{page_number}")
        page = doc.load_page(page_index)
        zoom = max(0.5, float(dpi) / 72.0)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        temp_path = temp_dir / f"qwen_regenerate_page_{page_number}_{id(pix)}{suffix}"
        if image_format in {"jpg", "jpeg"}:
            pix.save(str(temp_path), output="jpg")
        else:
            pix.save(str(temp_path))
        return temp_path
    finally:
        try:
            if doc is not None:
                doc.close()
        except Exception:
            pass


async def regenerate_part_markdown_from_page_images(
    *,
    client: Any,
    paper: Any,
    part: Any,
    qwen_settings: dict[str, Any],
    qwen_timeout: float,
    temp_dir: Path,
) -> tuple[str, dict[str, Any]]:
    """Restore a part Markdown layer from PDF page images through Qwen.

    This helper is intentionally transport-thin: the caller owns DB updates and
    Celery state, while this function only renders selected pages, sends them to
    Qwen and returns cleaned Markdown plus compact metadata.
    """
    pdf_path = Path(str(getattr(paper, "pdf_local_path", "") or ""))
    if not pdf_path.exists() or not pdf_path.is_file():
        raise RuntimeError("pdf_file_not_found")

    page_start = int(getattr(part, "page_start", None) or 1)
    page_end = int(getattr(part, "page_end", None) or page_start)
    dpi = int(qwen_settings.get("ai_render_dpi") or qwen_settings.get("render_dpi") or 220)
    image_format = str(qwen_settings.get("ai_page_image_format") or "png").strip().lower()
    delete_temp = bool(qwen_settings.get("ai_delete_temp_images", True))
    pdf_bytes = pdf_path.read_bytes()

    markdown_blocks: list[str] = []
    pages: list[dict[str, Any]] = []
    warnings: list[str] = []
    temp_paths: list[Path] = []
    session_id: str | None = None
    try:
        for page_number in range(page_start, page_end + 1):
            image_path = _render_pdf_page_to_image(
                pdf_bytes=pdf_bytes,
                page_number=page_number,
                temp_dir=temp_dir,
                dpi=dpi,
                image_format=image_format,
            )
            temp_paths.append(image_path)
            prompt = build_article_markdown_image_regeneration_prompt(
                paper_title=str(getattr(paper, "title", "") or ""),
                page_number=page_number,
                page_start=page_start,
                page_end=page_end,
            )
            result = await asyncio.to_thread(
                client.upload_file_and_send_message,
                file_path=str(image_path),
                message=prompt,
                session_id=session_id,
                thinking_enabled=False,
                search_enabled=False,
                auto_continue=False,
                timeout=qwen_timeout,
            )
            result_dict = result if isinstance(result, dict) else {}
            if result_dict.get("session_id"):
                session_id = str(result_dict.get("session_id") or "") or session_id
            response_text = str(result_dict.get("response") or "").strip()
            cleaned = clean_regenerated_markdown_response(response_text)
            pages.append(
                {
                    "page_number": page_number,
                    "image_path": "" if delete_temp else str(image_path),
                    "image_size_bytes": image_path.stat().st_size if image_path.exists() else 0,
                    "response_chars": len(response_text),
                    "markdown_chars": len(cleaned),
                    "message_id": result_dict.get("message_id"),
                    "session_id": session_id or "",
                    "error": result_dict.get("error"),
                }
            )
            if not cleaned:
                warnings.append(f"empty_qwen_markdown_page:{page_number}")
                continue
            markdown_blocks.append(cleaned)
    finally:
        if delete_temp:
            for path in temp_paths:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    logger.debug("Failed to delete temporary Qwen regeneration image {}", path, exc_info=True)

    markdown = "\n\n".join(block.strip() for block in markdown_blocks if block.strip()).strip()
    return markdown, {
        "regeneration_mode": "image",
        "paper_id": int(getattr(paper, "id", 0) or 0),
        "part_id": int(getattr(part, "id", 0) or 0),
        "pdf_path": str(pdf_path),
        "page_start": page_start,
        "page_end": page_end,
        "pages": pages,
        "markdown_chars": len(markdown),
        "warnings": sorted(set(warnings)),
        "ai_session_id": session_id or "",
        "method": "qwen_page_image_markdown_regeneration",
        "quality_score": 1.0 if markdown else 0.0,
    }
