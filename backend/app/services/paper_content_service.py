"""Article content post-processing helpers (PDF/full-text + RU AI enrichment)."""

from __future__ import annotations

import html
import json
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx
from loguru import logger

from app.core.config import settings
from app.services.qwen_client import get_qwen_client
from app.services.qwen_document.sessions import build_paper_session_title


@dataclass
class AIEnrichmentResult:
    summary_ru: str
    analysis_ru: str
    translation_ru: str
    used_fallback: bool = False
    fallback_reason: str | None = None


@dataclass
class DocumentLanguageResult:
    code: str = "unknown"
    name: str = "Не определён"
    confidence: float | None = None
    source: str = "qwen_keywords"


@dataclass
class KeywordGenerationResult:
    keywords: list[str]
    generated_count: int = 0
    validated_count: int = 0
    rejected_count: int = 0
    source_chars: int = 0
    source_mode: str = "empty"
    session_id: str | None = None
    rejected_keywords: list[str] | None = None
    language_code: str | None = None
    language_name: str | None = None
    language_confidence: float | None = None
    language_source: str | None = None


PDF_MARKDOWN_PROMPT_VERSION = "pdf-markdown-v2-parts"


MarkdownProgressCallback = Callable[[int, int, str], None]


def _page_markdown_heading(page_start: int, page_end: int) -> str:
    if page_start == page_end:
        return f"### Страница {page_start}"
    return f"### Страницы {page_start}-{page_end}"


_PAGE_MARKER_SPLIT_RE = re.compile("(?=\\[(?:\\u0421\\u0442\\u0440\\u0430\\u043d\\u0438\\u0446\\u0430|Page)\\s+\\d+\\])")

def _decode_cp1251_utf8_mojibake(value: str) -> str:
    try:
        return value.encode("cp1251").decode("utf-8")
    except Exception:
        return value


PDF_MARKDOWN_SYSTEM_PROMPT = _decode_cp1251_utf8_mojibake("""Ты — OCR/Markdown-редактор научных PDF-фрагментов.

Тебе передан сырой текст одного фрагмента PDF: одна страница или диапазон страниц.
Твоя задача — восстановить только этот фрагмент в чистом Markdown, без смысловых потерь и без добавления текста от себя.

Жёсткие правила:
1. Верни только Markdown. Без пояснений, комментариев, вступлений и заключений.
2. Не добавляй заголовки вида "Page", "Pages", "Страница", если они не являются частью самой статьи.
3. Не добавляй текст, которого нет во входном фрагменте.
4. Не объединяй фрагмент с предыдущими или следующими страницами.
5. Не исправляй научный смысл, числа, единицы измерения, имена, ссылки и формулы.
6. Если символ/формула распознаны плохо — сохрани максимально близко к исходнику, не угадывай.
7. Заголовки статьи оформи через #, ##, ### только если они явно есть во входе.
8. Abstract, Keywords, References, Figure captions и Table captions сохраняй отдельными блоками.
9. Если во входе есть блоки [Table candidate N], используй их как основу таблиц и не удаляй числовые значения. Таблицы восстанавливай в Markdown-таблицы, если структура понятна; иначе сохраняй как preformatted text.
10. Если во входе есть блок [Formula candidate], сохрани следующую строку как формулу или максимально близкий текст формулы; не преобразуй её в обычное предложение.
11. Формулы оформляй так:
    - inline формулы: $...$
    - отдельные формулы: $$...$$
    - не используй \\( \\) и \\[ \\]
    - не выдумывай недостающие части формул.
12. Между абзацами оставляй пустую строку.
13. Не склеивай заголовки, абзацы, таблицы, подписи рисунков и references в одну строку.
14. Сохраняй язык оригинала.
15. Если часть текста невозможно восстановить надёжно, оставь её максимально близко к исходнику.

Формат ответа: только Markdown. Без дополнительного текста.""")

PDF_MARKDOWN_CONTINUE_PROMPT = _decode_cp1251_utf8_mojibake("""Продолжай ту же OCR/Markdown-задачу для нового PDF-фрагмента.
Верни только Markdown этого фрагмента. Не добавляй Page/Pages/Страница, комментарии или текст от себя.
Формулы: inline $...$, отдельные $$...$$. Блоки [Formula candidate] и [Table candidate] используй как технические подсказки, но не выводи эти маркеры в ответ.""")

def _clean_arxiv_id(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""

    value = value.replace("http://", "https://")
    if "arxiv.org/abs/" in value:
        value = value.split("arxiv.org/abs/", 1)[1]
    elif "arxiv.org/pdf/" in value:
        value = value.split("arxiv.org/pdf/", 1)[1]

    if value.lower().startswith("arxiv:"):
        value = value.split(":", 1)[1]

    value = value.split("?", 1)[0].split("#", 1)[0].strip("/")
    value = value.removesuffix(".pdf")
    value = re.sub(r"v\d+$", "", value)
    return value


def _is_probably_pdf_url(raw_url: str) -> bool:
    if not raw_url:
        return False
    parsed = urlparse(raw_url)
    path = (parsed.path or "").lower()
    return path.endswith(".pdf") or "/pdf/" in path


def resolve_pdf_url(source: str, source_id: str | None, url: str | None) -> str | None:
    src = (source or "").strip().lower()
    raw_url = (url or "").strip()

    if src == "arxiv":
        sid = (source_id or "").strip()
        arxiv_id = _clean_arxiv_id(sid or raw_url)
        if arxiv_id:
            return f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    if _is_probably_pdf_url(raw_url):
        return raw_url




    if src == "europepmc":
        return None

    return None


def prepare_pdf_request(pdf_url: str) -> tuple[str, dict[str, str]]:
    """Attach server-side PDF credentials without persisting them in paper URLs."""
    headers = {"Accept": "application/pdf,application/octet-stream;q=0.9,text/html;q=0.2,*/*;q=0.1"}
    parsed = urlparse(pdf_url)
    if parsed.netloc.lower() != "content.openalex.org" or not settings.OPENALEX_API_KEY:
        return pdf_url, headers

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["api_key"] = settings.OPENALEX_API_KEY
    request_url = urlunparse(parsed._replace(query=urlencode(query)))
    return request_url, headers


def _extract_pdf_link_from_html(base_url: str, html_text: str) -> str | None:
    if not html_text:
        return None
    matches = re.findall(r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', html_text, flags=re.IGNORECASE)
    if not matches:
        return None
    return urljoin(base_url, matches[0])


def download_pdf_bytes(pdf_url: str, timeout_sec: float = 45.0) -> bytes | None:
    try:
        request_url, request_headers = prepare_pdf_request(pdf_url)
        with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
            response = client.get(request_url, headers=request_headers)
            response.raise_for_status()
            content = response.content or b""
            if not content:
                return None

            content_type = (response.headers.get("content-type") or "").lower()
            if "pdf" in content_type or content.startswith(b"%PDF"):
                return content


            html_text = response.text or ""
            guessed_pdf = _extract_pdf_link_from_html(str(response.url), html_text)
            if guessed_pdf:
                pdf_resp = client.get(guessed_pdf, headers={"Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.1"})
                pdf_resp.raise_for_status()
                pdf_bytes = pdf_resp.content or b""
                pdf_type = (pdf_resp.headers.get("content-type") or "").lower()
                if pdf_bytes and ("pdf" in pdf_type or pdf_bytes.startswith(b"%PDF")):
                    logger.info("Resolved PDF via landing page: {} -> {}", pdf_url, guessed_pdf)
                    return pdf_bytes

            logger.warning("URL is not a direct PDF and no PDF link detected: {} ({})", pdf_url, content_type)
            return None
    except Exception as exc:
        logger.warning("Failed to download PDF {}: {}", pdf_url, type(exc).__name__)
        return None


def save_pdf_locally(paper_id: int, pdf_bytes: bytes) -> str:
    base_dir = Path(settings.resolve_path(settings.PAPER_PDF_DIR))
    base_dir.mkdir(parents=True, exist_ok=True)
    target = base_dir / f"paper_{paper_id}.pdf"
    target.write_bytes(pdf_bytes)
    return str(target)


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Извлечь текст из PDF в legacy-формате одной строкой."""
    try:
        from app.services.pdf_content_parser import pdf_parser

        return pdf_parser.extract_text_from_bytes(pdf_bytes)
    except Exception as exc:
        logger.warning("Failed to extract text from PDF: {}", exc)
        return ""


def extract_pdf_page_items(pdf_bytes: bytes, options: dict | None = None) -> list[dict]:
    """Извлечь PDF постранично с диагностикой качества.

    Возвращает список dict, чтобы content task не зависел от конкретного
    dataclass pdf_content_parser и мог безопасно передавать данные в service-layer.
    """
    try:
        from app.services.pdf_content_parser import pdf_parser

        pages = pdf_parser.extract_pages_from_bytes(pdf_bytes, options=options or {})
        return [page.as_dict() if hasattr(page, "as_dict") else dict(page) for page in pages]
    except Exception as exc:
        logger.warning("Failed to extract structured PDF pages: {}", exc)
        text = extract_pdf_text(pdf_bytes)
        return [
            {
                "page_number": index,
                "text": page_text,
                "method": "legacy_split",
                "quality_score": 0.35 if page_text.strip() else 0.0,
                "warnings": ["legacy_pdf_extraction"],
                "metadata": {"fallback": True, "chars": len(page_text or "")},
            }
            for index, page_text in enumerate(_split_pdf_text_into_pages(text), start=1)
            if page_text.strip()
        ]


def _clean_fast_pdf_text(value: str) -> str:
    text = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf_page_items_mypdf(pdf_bytes: bytes, options: dict | None = None) -> list[dict]:
    """Fast text-layer PDF extraction through PyMuPDF/fitz.

    This mode intentionally does not run OCR, image/page AI recognition or table
    reconstruction. It is meant for PDFs with a good embedded text layer where
    speed is more important than layout/table recovery.
    """
    opts = options or {}
    max_page_chars = int(opts.get("max_page_chars") or 60000)
    try:
        import fitz

        page_items: list[dict] = []
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page_index in range(len(doc)):
                page = doc.load_page(page_index)
                raw_text = page.get_text("text", sort=True) or ""
                text = _clean_fast_pdf_text(raw_text)[:max_page_chars]
                if not text:
                    continue
                word_count = len(re.findall(r"[A-Za-zА-Яа-я0-9]{2,}", text))


                quality = 0.8
                page_items.append(
                    {
                        "page_number": page_index + 1,
                        "text": text,
                        "method": "mypdf_text_layer",
                        "quality_score": round(quality, 3),
                        "warnings": [],
                        "metadata": {
                            "parser_mode": "mypdf",
                            "extraction_mode": "mypdf",
                            "extraction_strategy": "mypdf_text_layer",
                            "selected_strategy": "mypdf_text_layer",
                            "primary_selected_strategy": "mypdf_text_layer",
                            "ocr_enabled": False,
                            "ocr_used": False,
                            "ai_enabled": False,
                            "ai_used": False,
                            "extract_tables": False,
                            "images_processed": False,
                            "chars": len(text),
                            "words": word_count,
                        },
                    }
                )
        return page_items
    except Exception as exc:
        logger.warning("Fast mypdf/PyMuPDF extraction failed: {}", exc)
        fallback_options = {
            **opts,
            "parser_mode": "auto",
            "extraction_mode": "simple",
            "force_strategy": "simple",
            "extract_tables": False,
            "detect_columns": False,
            "ocr_enabled": False,
            "ocr_mode": "off",
            "ocr_force": False,
            "ai_enabled": False,
            "ai_mode": "off",
        }
        items = extract_pdf_page_items(pdf_bytes, fallback_options)
        for item in items:
            metadata = dict(item.get("metadata") or {})
            metadata.update(
                {
                    "parser_mode": "mypdf",
                    "extraction_mode": "mypdf",
                    "extraction_strategy": "simple_text_layer_fallback",
                    "selected_strategy": metadata.get("selected_strategy") or "simple_text_layer_fallback",
                    "ocr_enabled": False,
                    "ocr_used": False,
                    "ai_enabled": False,
                    "ai_used": False,
                    "extract_tables": False,
                    "mypdf_fallback_reason": type(exc).__name__,
                }
            )
            item["metadata"] = metadata
            item["method"] = item.get("method") or "simple_text_layer_fallback"


            item["quality_score"] = 0.8 if str(item.get("text") or "").strip() else 0.0
            item["warnings"] = sorted(set(list(item.get("warnings") or []) + ["mypdf_fallback_used"]))
        return items


def extract_pdf_pages(pdf_bytes: bytes) -> list[str]:
    """Backward-compatible page text extraction."""
    return [str(item.get("text") or "") for item in extract_pdf_page_items(pdf_bytes)]


def _clean_html_text(raw: str) -> str:

    text = html.unescape(raw or "")
    text = html.unescape(text)
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<noscript[\s\S]*?</noscript>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)

    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fetch_europepmc_fulltext(source_id: str) -> str:
    if not source_id:
        return ""

    if ":" in source_id:
        source_db, article_id = source_id.split(":", 1)
    else:
        source_db, article_id = "PPR", source_id

    source_db = source_db.strip()
    article_id = article_id.strip()
    if not source_db or not article_id:
        return ""


    xml_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{source_db}/{article_id}/fullTextXML"
    try:
        with httpx.Client(timeout=45.0, follow_redirects=True) as client:
            resp = client.get(xml_url, headers={"Accept": "application/xml,text/xml;q=0.9,*/*;q=0.1"})
            if resp.status_code == 200 and resp.text:
                text = _clean_html_text(resp.text)
                return text[:200000]
    except Exception as exc:
        logger.warning("EuropePMC fullTextXML fetch failed for {}: {}", source_id, exc)

    return ""


def fetch_additional_full_text(source: str, source_id: str | None, url: str | None, abstract: str = "") -> str:
    """Fallback full-text fetch when PDF is unavailable.

    Returns non-empty text only when useful content is found.
    """
    src = (source or "").strip().lower()
    sid = (source_id or "").strip()
    raw_url = (url or "").strip()

    if src == "europepmc":
        epmc_text = _fetch_europepmc_fulltext(sid)
        if epmc_text and len(epmc_text) > max(1200, len((abstract or "")) + 500):
            return epmc_text

    if raw_url:
        try:
            with httpx.Client(timeout=40.0, follow_redirects=True) as client:
                resp = client.get(raw_url, headers={"Accept": "text/html,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.1"})
                resp.raise_for_status()
                ctype = (resp.headers.get("content-type") or "").lower()
                if "text" in ctype or "html" in ctype or "xml" in ctype:
                    text = _clean_html_text(resp.text or "")
                    if text and len(text) > max(1200, len((abstract or "")) + 500):
                        return text[:200000]
        except Exception as exc:
            logger.warning("Fallback text fetch failed for {}: {}", raw_url, exc)

    return ""


def _fallback_enrichment(
    title: str,
    abstract: str,
    text: str,
    reason: str,
) -> AIEnrichmentResult:
    source_text = (text or abstract or "").strip()
    short = source_text[:1800] if source_text else "Текст статьи недоступен."
    return AIEnrichmentResult(
        summary_ru=f"Статья: {title}. Краткая суть: {short[:500]}",
        analysis_ru=(
            "Автоанализ выполнен в fallback-режиме. "
            "Рекомендуется повторный запуск при доступном Qwen Service."
        ),
        translation_ru=short,
        used_fallback=True,
        fallback_reason=reason,
    )


def create_qwen_session_for_paper(paper_id: int, title: str) -> str | None:
    qwen_client = get_qwen_client()
    session_title = build_paper_session_title(paper_id, title)
    try:
        return qwen_client.create_session(title=session_title)
    except Exception as exc:
        logger.warning("Failed to create Qwen session for paper {}: {}", paper_id, exc)
        return None


def _split_pdf_text_into_pages(raw_text: str) -> list[str]:
    text = (raw_text or "").strip()
    if not text:
        return []

    parts = [p.strip() for p in _PAGE_MARKER_SPLIT_RE.split(text) if p and p.strip()]
    if parts:
        return parts


    chunk_size = 9000
    return [text[i : i + chunk_size].strip() for i in range(0, len(text), chunk_size) if text[i : i + chunk_size].strip()]



def _clean_markdown_response(text: str, *, normalize_math: bool = True) -> str:
    """Small post-processing pass after Qwen Markdown normalization.

    Qwen usually does the semantic restoration, but PDF/OCR output can still come
    back with extra fences or with headings/tables glued to adjacent paragraphs.
    This pass is deliberately conservative: it normalizes spacing without trying
    to rewrite scientific content.
    """
    value = (text or "").strip()
    if not value:
        return ""


    value = re.sub(r"^```(?:markdown|md)?\s*", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"\s*```$", "", value).strip()
    value = value.replace("\r\n", "\n").replace("\r", "\n")


    value = re.sub(r"(?<!\n)\n(#{1,6}\s+)", r"\n\n\1", value)
    value = re.sub(r"(#{1,6}[^\n]+)\n(?!\n)", r"\1\n\n", value)
    value = re.sub(r"(?<!\n)\n(\|.+\|)", r"\n\n\1", value)
    value = re.sub(r"(\|.+\|)\n(?!\n|\|)", r"\1\n\n", value)


    if normalize_math:
        value = re.sub(r"\\\((.+?)\\\)", lambda m: f"${m.group(1).strip()}$", value, flags=re.DOTALL)
        value = re.sub(r"\\\[(.+?)\\\]", lambda m: f"$$\n{m.group(1).strip()}\n$$", value, flags=re.DOTALL)


    value = re.sub(r"(?<!\n)(#{1,6}\s+)", r"\n\n\1", value)
    value = re.sub(r"(?<!\n)(\b(?:Abstract|Keywords|References|Acknowledg(?:e)?ments)\b\s*:?)", r"\n\n## \1", value, flags=re.IGNORECASE)
    value = re.sub(r"(?<!\n)(\b[IVX]{1,6}\.\s+[A-Z][A-Z0-9 ,:;()\-/]{3,})", r"\n\n## \1", value)


    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _build_markdown_prompt(
    *,
    title: str,
    page_start: int,
    page_end: int,
    raw_text: str,
    include_full_instruction: bool = True,
) -> str:
    instruction = PDF_MARKDOWN_SYSTEM_PROMPT if include_full_instruction else PDF_MARKDOWN_CONTINUE_PROMPT
    return (
        f"{instruction}\n\n"
        f"Article title: {title}\n"
        f"Input pages: {page_start}-{page_end}\n"
        "Raw PDF fragment:\n"
        f"{(raw_text or '').strip()}"
    ).strip()


def normalize_pdf_text_part(
    paper_id: int,
    title: str,
    raw_text: str,
    page_start: int,
    page_end: int,
    session_id: str | None = None,
    *,
    include_full_instruction: bool = True,
    page_char_limit: int | None = None,
    timeout_seconds: float | None = None,
    normalize_math: bool = True,
) -> str:
    """Normalize one stored PDF page/chunk through Qwen and return Markdown only."""
    source_text = (raw_text or "").strip()
    if page_char_limit and page_char_limit > 0:
        source_text = source_text[:page_char_limit]
    if not source_text:
        return ""

    qwen_client = get_qwen_client()
    prompt = _build_markdown_prompt(
        title=title,
        page_start=page_start,
        page_end=page_end,
        raw_text=source_text,
        include_full_instruction=include_full_instruction,
    )

    result = qwen_client.send_message(
        message=prompt,
        session_id=session_id,
        thinking_enabled=True,
        search_enabled=False,
        auto_continue=False,
        timeout=float(timeout_seconds or getattr(settings, "QWEN_CHAT_TIMEOUT_SECONDS", 300.0) or 300.0),
    )
    response_text = _clean_markdown_response(result.get("response") or "", normalize_math=normalize_math)
    if response_text:
        return response_text

    error_text = str(result.get("error") or "").strip()
    logger.warning(
        "Empty Qwen markdown part response for paper={} pages={}..{} session={} error={}",
        paper_id,
        page_start,
        page_end,
        (session_id or "none"),
        (error_text or "none"),
    )
    return ""


def normalize_pdf_text_markdown(
    paper_id: int,
    title: str,
    raw_text: str,
    session_id: str | None = None,
    on_page_markdown: MarkdownProgressCallback | None = None,
    *,
    pages_per_request: int | None = None,
    page_char_limit: int | None = None,
    timeout_seconds: float | None = None,
    normalize_math: bool = True,
) -> str:
    pages = _split_pdf_text_into_pages(raw_text)
    if not pages:
        return ""

    qwen_client = get_qwen_client()
    normalized_parts: list[str] = []
    active_session_id = session_id
    max_page_attempts = 3
    session_needs_prompt = True
    pages_per_request = max(1, int(pages_per_request or getattr(settings, "QWEN_MARKDOWN_PAGES_PER_REQUEST", 1) or 1))
    page_char_limit = max(1000, int(page_char_limit or getattr(settings, "QWEN_MARKDOWN_PAGE_CHARS", 14000) or 14000))
    page_batches = [pages[i : i + pages_per_request] for i in range(0, len(pages), pages_per_request)]
    current_page = 1

    for batch in page_batches:
        response_text = ""
        batch_text = "\n\n".join(f"[Страница {current_page + offset}]\n{page[:page_char_limit]}" for offset, page in enumerate(batch))
        batch_range_start = current_page
        batch_range_end = current_page + len(batch) - 1

        for attempt in range(1, max_page_attempts + 1):
            prompt = _build_markdown_prompt(
                title=title,
                page_start=batch_range_start,
                page_end=batch_range_end,
                raw_text=batch_text,
                include_full_instruction=session_needs_prompt,
            )

            result = qwen_client.send_message(
                message=prompt,
                session_id=active_session_id,
                thinking_enabled=True,
                search_enabled=False,
                auto_continue=False,
                timeout=float(timeout_seconds or getattr(settings, "QWEN_CHAT_TIMEOUT_SECONDS", 300.0) or 300.0),
            )
            response_text = _clean_markdown_response(result.get("response") or "", normalize_math=normalize_math)
            error_text = str(result.get("error") or "").strip()

            if response_text:
                session_needs_prompt = False
                break

            logger.warning(
                "Empty page-normalization response for paper={} pages={}..{} attempt={} session={} error={}",
                paper_id,
                batch_range_start,
                batch_range_end,
                attempt,
                (active_session_id or "none"),
                (error_text or "none"),
            )

            if attempt < max_page_attempts:
                lowered_error = (error_text or "").lower()
                should_rotate_session = ("chat is in progress" in lowered_error) or ("model not found" in lowered_error)
                if should_rotate_session:
                    replacement_session = create_qwen_session_for_paper(paper_id=paper_id, title=title)
                    if replacement_session:
                        active_session_id = replacement_session
                        session_needs_prompt = True
                        logger.info(
                            "Switched Qwen session for paper={} pages={}..{} to recover stream issues: {}",
                            paper_id,
                            batch_range_start,
                            batch_range_end,
                            active_session_id,
                        )

        page_payload = _clean_markdown_response(response_text or batch_text, normalize_math=normalize_math)
        normalized_parts.append(f"{_page_markdown_heading(batch_range_start, batch_range_end)}\n\n{page_payload}".strip())
        if on_page_markdown:
            try:
                on_page_markdown(batch_range_end, len(pages), "\n\n".join(normalized_parts).strip())
            except Exception as callback_exc:
                logger.warning(
                    "on_page_markdown callback failed for paper={} pages={}..{}: {}",
                    paper_id,
                    batch_range_start,
                    batch_range_end,
                    callback_exc,
                )
        current_page += len(batch)

    merged = "\n\n".join(part for part in normalized_parts if part and part.strip()).strip()
    logger.info("Normalized PDF text for paper {}: pages={}, chars={}", paper_id, len(pages), len(merged))
    return merged


def generate_ai_enrichment_ru(
    title: str,
    abstract: str,
    text: str,
    session_id: str | None = None,
    *,
    timeout_seconds: float | None = None,
) -> AIEnrichmentResult:
    text_for_model = (text or abstract or "").strip()
    if not text_for_model:
        return _fallback_enrichment(
            title=title,
            abstract=abstract,
            text=text,
            reason="no_input_text_for_enrichment",
        )

    qwen_client = get_qwen_client()

    payload_text = text_for_model[:22000]
    prompt = (
        "Сделай научный разбор статьи и перевод на русский.\n"
        "Верни СТРОГО JSON-объект без markdown:\n"
        '{"summary_ru":"...","analysis_ru":"...","translation_ru":"..."}\n'
        "Требования:\n"
        "1) Всё на русском языке.\n"
        "2) summary_ru: 5-8 предложений, суть и практическая ценность.\n"
        "3) analysis_ru: структурированный анализ (материалы, метод, результаты, ограничения).\n"
        "4) translation_ru: перевод ключевого содержания статьи на русский (не менее 8 предложений).\n"
        f"Название: {title}\n"
        f"Аннотация: {abstract or 'нет'}\n"
        f"Текст: {payload_text}"
    )

    result = qwen_client.send_message(
        message=prompt,
        session_id=session_id,
        thinking_enabled=True,
        search_enabled=False,
        auto_continue=True,
        timeout=float(timeout_seconds or getattr(settings, "QWEN_CHAT_TIMEOUT_SECONDS", 300.0) or 300.0),
    )
    response_text = (result.get("response") or "").strip()
    if not response_text:
        return _fallback_enrichment(
            title=title,
            abstract=abstract,
            text=text,
            reason="qwen_empty_response",
        )

    parsed = None
    try:
        parsed = json.loads(response_text)
    except Exception:
        match = re.search(r"\{[\s\S]*\}", response_text)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except Exception:
                parsed = None

    if not isinstance(parsed, dict):
        return _fallback_enrichment(
            title=title,
            abstract=abstract,
            text=text,
            reason="qwen_invalid_json",
        )

    summary_ru = str(parsed.get("summary_ru") or "").strip()
    analysis_ru = str(parsed.get("analysis_ru") or "").strip()
    translation_ru = str(parsed.get("translation_ru") or "").strip()

    if not (summary_ru and analysis_ru and translation_ru):
        return _fallback_enrichment(
            title=title,
            abstract=abstract,
            text=text,
            reason="qwen_incomplete_fields",
        )

    return AIEnrichmentResult(
        summary_ru=summary_ru,
        analysis_ru=analysis_ru,
        translation_ru=translation_ru,
    )


_KEYWORD_COMMON_STOPWORDS = {

    "abstract", "introduction", "background", "method", "methods", "result", "results",
    "discussion", "conclusion", "conclusions", "article", "paper", "study", "studies",
    "analysis", "data", "table", "figure", "fig", "reference", "references", "section",
    "materials", "material", "sample", "samples", "experiment", "experimental", "model",
    "models", "property", "properties", "effect", "effects", "using", "based", "obtained",
    "present", "work", "this work", "research", "investigation",

    "аннотация", "введение", "метод", "методы", "результат", "результаты",
    "обсуждение", "вывод", "выводы", "статья", "исследование", "анализ", "данные",
    "таблица", "рисунок", "литература", "источники", "раздел", "материалы",
    "образец", "образцы", "эксперимент", "модель", "свойства", "эффект", "работа",
}

_KEYWORD_ALLOWED_SHORT_TERMS = {
    "Ni", "Al", "Co", "Cr", "Mo", "W", "Ta", "Ti", "Fe", "Nb", "Re", "Ru",
    "Hf", "Zr", "V", "Y", "B", "C", "N", "O", "Si", "Mn", "Mg", "Cu",
    "γ", "γ′", "γ'", "γ-phase", "γ-matrix",
}


def _normalize_keyword(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n,;:.")
    return cleaned[:120]


def _keyword_word_count(value: str) -> int:
    return len(re.findall(r"[\wА-Яа-яЁё]+", value, flags=re.UNICODE))


def _is_informative_keyword(value: str) -> bool:
    """Filter exact-but-useless keywords before saving them.

    Validation still requires an exact source-text match. This gate only rejects
    generic UI/parser/article words that are present in the document but do not
    work as scientific keywords. Short chemical symbols are allowed explicitly.
    """
    keyword = _normalize_keyword(value)
    if not keyword:
        return False

    folded = keyword.casefold()
    if folded in _KEYWORD_COMMON_STOPWORDS:
        return False
    if re.search(r"https?://|www\.|@|doi\s*:|^10\.\d{4,}/", keyword, flags=re.IGNORECASE):
        return False
    if re.fullmatch(r"[\d\W_]+", keyword, flags=re.UNICODE):
        return False
    if keyword.endswith((".", "?", "!")):
        return False

    words = _keyword_word_count(keyword)
    if words > 5:
        return False


    if words <= 1:
        alpha = re.sub(r"[^A-Za-zА-Яа-яЁёΑ-Ωα-ω]", "", keyword)
        if len(alpha) <= 2 and keyword not in _KEYWORD_ALLOWED_SHORT_TERMS:
            return False
        if len(alpha) <= 3 and folded not in {term.casefold() for term in _KEYWORD_ALLOWED_SHORT_TERMS}:

            if not (len(alpha) >= 3 and alpha.isupper()):
                return False

    return True


def _dedupe_keywords(values: list[str], limit: int = 50) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()
    for raw in values:
        keyword = _normalize_keyword(raw)
        if not keyword:
            continue
        key = keyword.casefold()
        if key in seen:
            continue
        seen.add(key)
        keywords.append(keyword)
        if len(keywords) >= limit:
            break
    return keywords


def _coerce_keyword_list(raw: object) -> list[str]:
    if isinstance(raw, list):
        values: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                item = item.get("keyword") or item.get("term") or item.get("value") or ""
            if str(item or "").strip():
                values.append(str(item))
        return values
    if isinstance(raw, str):
        parts = re.split(r"[,;\n]+", raw)
        return [part for part in parts if part.strip()]
    return []


_LANGUAGE_NAMES_RU = {
    "en": "Английский",
    "ru": "Русский",
    "de": "Немецкий",
    "fr": "Французский",
    "es": "Испанский",
    "zh": "Китайский",
    "ja": "Японский",
    "ko": "Корейский",
    "it": "Итальянский",
    "pt": "Португальский",
    "pl": "Польский",
    "uk": "Украинский",
    "mixed": "Смешанный",
    "unknown": "Не определён",
}

_LANGUAGE_CODE_ALIASES = {
    "eng": "en",
    "english": "en",
    "английский": "en",
    "rus": "ru",
    "russian": "ru",
    "русский": "ru",
    "deu": "de",
    "ger": "de",
    "german": "de",
    "немецкий": "de",
    "fra": "fr",
    "fre": "fr",
    "french": "fr",
    "французский": "fr",
    "spa": "es",
    "spanish": "es",
    "испанский": "es",
    "chi": "zh",
    "zho": "zh",
    "chinese": "zh",
    "китайский": "zh",
    "jpn": "ja",
    "japanese": "ja",
    "японский": "ja",
    "kor": "ko",
    "korean": "ko",
    "корейский": "ko",
    "ita": "it",
    "italian": "it",
    "итальянский": "it",
    "por": "pt",
    "portuguese": "pt",
    "португальский": "pt",
    "pol": "pl",
    "polish": "pl",
    "польский": "pl",
    "ukr": "uk",
    "ukrainian": "uk",
    "украинский": "uk",
    "multi": "mixed",
    "multiple": "mixed",
    "mixed language": "mixed",
    "смешанный": "mixed",
}


def _normalize_language_code(value: object) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    if not raw:
        return "unknown"
    raw = raw.split("-", 1)[0] if len(raw) > 2 and "-" in raw else raw
    raw = _LANGUAGE_CODE_ALIASES.get(raw, raw)
    allowed = set(_LANGUAGE_NAMES_RU)
    return raw if raw in allowed else "unknown"


def _coerce_language_confidence(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 1 and number <= 100:
        number = number / 100
    return max(0.0, min(1.0, number))


def _coerce_language_result(raw: object) -> DocumentLanguageResult:
    if not isinstance(raw, dict):
        return DocumentLanguageResult()
    code = _normalize_language_code(raw.get("code") or raw.get("language_code") or raw.get("lang") or raw.get("name"))
    confidence_value = raw.get("confidence")
    if confidence_value is None:
        confidence_value = raw.get("score")
    if confidence_value is None:
        confidence_value = raw.get("probability")
    return DocumentLanguageResult(
        code=code,
        name=_LANGUAGE_NAMES_RU.get(code, "Не определён"),
        confidence=_coerce_language_confidence(confidence_value),
        source="qwen_keywords",
    )


def _parse_keywords_response(response_text: str) -> list[str]:
    keywords, _, _ = _parse_keywords_response_with_status(response_text)
    return keywords


def _parse_keywords_response_with_status(response_text: str) -> tuple[list[str], bool, DocumentLanguageResult]:
    parsed = None
    try:
        parsed = json.loads(response_text)
    except Exception:
        match = re.search(r"\{[\s\S]*\}", response_text or "")
        if match:
            try:
                parsed = json.loads(match.group(0))
            except Exception:
                parsed = None

    if isinstance(parsed, dict):
        return _coerce_keyword_list(parsed.get("keywords")), True, _coerce_language_result(parsed.get("language"))
    if isinstance(parsed, list):
        return _coerce_keyword_list(parsed), True, DocumentLanguageResult()
    return [], False, DocumentLanguageResult()


def _build_keyword_source_text(
    *,
    title: str | None,
    abstract: str | None,
    full_text: str | None,
    raw_text: str | None = None,
) -> tuple[str, str]:
    """Build one canonical text source for keyword extraction.

    Article and patent records go through the same path. Prefer raw parser text
    from ``paper_content_parts.raw_text`` because ``paper.full_text`` may already
    be Qwen-normalized Markdown. Metadata, translations, summaries and old
    keywords are intentionally excluded so Qwen cannot reuse tags that are not
    present in the document itself.
    """
    sections: list[str] = []
    title_clean = (title or "").strip()
    abstract_clean = (abstract or "").strip()
    raw_text_clean = (raw_text or "").strip()
    full_text_clean = (full_text or "").strip()

    def add_section(value: str) -> None:
        text = value.strip()
        if not text:
            return
        if text.casefold() in {item.casefold() for item in sections}:
            return
        sections.append(text)

    add_section(title_clean)
    add_section(abstract_clean)
    if raw_text_clean:
        add_section(raw_text_clean)
        source_mode = "title_abstract_raw_parts" if (title_clean or abstract_clean) else "raw_parts"
    elif full_text_clean:
        add_section(full_text_clean)
        source_mode = "title_abstract_full_text" if (title_clean or abstract_clean) else "full_text"
    elif abstract_clean:
        source_mode = "title_abstract" if title_clean else "abstract"
    elif title_clean:
        source_mode = "title"
    else:
        source_mode = "empty"

    return "\n\n".join(sections).strip(), source_mode


def _keyword_boundary_pattern(keyword: str) -> re.Pattern[str] | None:
    keyword_clean = _normalize_keyword(keyword)
    if not keyword_clean:
        return None

    pieces: list[str] = []
    for char in keyword_clean:
        if char.isspace():
            pieces.append(r"\s+")
        elif char in "-‐‑‒–—−":
            pieces.append(r"\s*[\-‐‑‒–—−]\s*")
        else:
            pieces.append(re.escape(char))

    if not pieces:
        return None

    pattern = "".join(pieces)
    if keyword_clean[0].isalnum() or keyword_clean[0] == "_":
        pattern = r"(?<!\w)" + pattern
    if keyword_clean[-1].isalnum() or keyword_clean[-1] == "_":
        pattern = pattern + r"(?!\w)"

    try:
        return re.compile(pattern, flags=re.IGNORECASE | re.UNICODE)
    except re.error:
        logger.debug("Invalid keyword regex pattern for keyword={!r}", keyword_clean)
        return None


def _clean_keyword_match_from_source(value: str) -> str:
    text = str(value or "").replace("\u00ad", "")
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    text = re.sub(r"\s*([\-‐‑‒–—−])\s*", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return _normalize_keyword(text)


def _keyword_match_in_source(keyword: str, source_text: str) -> str | None:
    """Return exact source form for a keyword, or None if it is not a term match.

    Matching is boundary-aware, so short terms like ``Al``/``Ni`` do not pass
    because they occur inside ``alloy``/``nickel``/``superalloy``. Hyphen and
    whitespace variants are tolerated only around the same visible term.
    """
    if not keyword or not source_text:
        return None

    pattern = _keyword_boundary_pattern(keyword)
    if pattern is None:
        return None

    match = pattern.search(source_text)
    if not match:
        return None

    source_form = _clean_keyword_match_from_source(match.group(0))
    return source_form or _normalize_keyword(keyword)


def _validate_keywords_against_source(
    keywords: list[str],
    source_text: str,
    *,
    limit: int = 50,
) -> tuple[list[str], list[str]]:
    accepted: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()

    for raw in keywords:
        keyword = _normalize_keyword(raw)
        if not keyword:
            continue

        matched_keyword = _keyword_match_in_source(keyword, source_text)
        if not matched_keyword or not _is_informative_keyword(matched_keyword):
            rejected.append(keyword)
            continue

        key = matched_keyword.casefold()
        if key in seen:
            continue
        seen.add(key)
        accepted.append(matched_keyword)
        if len(accepted) >= limit:
            break

    return accepted, rejected


def _build_document_keywords_prompt() -> str:
    return (
        "Ты получаешь один TXT-файл с текстом научного или технического документа. "
        "Документ может быть статьёй, патентом или другой записью, но процесс одинаковый.\n\n"
        "Задача: извлеки ключевые слова и короткие терминологические фразы, "
        "которые ДОСЛОВНО встречаются в прикреплённом TXT-файле.\n\n"
        "Жёсткие правила:\n"
        "1) Используй только текст из прикреплённого TXT-файла.\n"
        "2) Не используй внешние знания, перевод, синонимы, классификаторы, темы или обобщения.\n"
        "3) Каждый keyword должен быть точной подстрокой текста файла.\n"
        "4) Если термин в файле написан через дефис, с цифрами, индексами или в конкретном регистре — сохрани форму из файла.\n"
        "5) Язык keyword должен совпадать с тем, как термин написан в файле.\n"
        "6) Не добавляй авторов, DOI, URL, название журнала, source ID и служебные слова, если это не технический термин из текста.\n"
        "7) Не возвращай общие слова структуры статьи: abstract, introduction, method, result, table, figure, references и их аналоги.\n"
        "8) Один keyword обычно 1-5 слов. Не возвращай длинные предложения.\n"
        "9) Верни от 0 до 50 keywords. Если подходящих точных терминов меньше 10 — верни меньше 10.\n"
        "10) Если точных keywords нет — верни пустой массив.\n"
        "11) Дополнительно определи основной язык документа по этому же TXT-файлу. Язык — это метаданные, не keyword.\n"
        "12) language.code верни в ISO 639-1: en, ru, de, fr, es, zh, ja, ko, it, pt, pl, uk. "
        "Если основной язык выбрать нельзя — mixed, если определить нельзя — unknown.\n"
        "13) language.name верни на английском, language.confidence — число от 0 до 1.\n"
        "14) Верни только строгий JSON без markdown и пояснений.\n\n"
        "Формат ответа: {\"keywords\":[\"keyword 1\",\"keyword 2\"],"
        "\"language\":{\"code\":\"en\",\"name\":\"English\",\"confidence\":0.95}}"
    )



def generate_document_keywords(
    *,
    title: str | None,
    abstract: str | None,
    full_text: str | None,
    raw_text: str | None = None,
    existing_keywords: list[str] | None = None,
    session_id: str | None = None,
    timeout_seconds: float | None = None,
) -> KeywordGenerationResult:
    """Extract validated document keywords through Qwen.

    The same pipeline is used for articles and patents. Qwen receives only one
    UTF-8 TXT file with document text. Returned keywords and pre-existing
    keywords are accepted only if they are present in that source text.
    """
    source_text, source_mode = _build_keyword_source_text(
        title=title,
        abstract=abstract,
        full_text=full_text,
        raw_text=raw_text,
    )
    source_chars = len(source_text)
    existing = _dedupe_keywords(existing_keywords or [])

    if not source_text:
        logger.warning("Keyword extraction skipped: empty document text for title='{}'", str(title or "")[:80])
        return KeywordGenerationResult(
            keywords=[],
            generated_count=0,
            validated_count=0,
            rejected_count=len(existing),
            source_chars=0,
            source_mode=source_mode,
            session_id=session_id,
            rejected_keywords=existing,
            language_code="unknown",
            language_name="Не определён",
            language_confidence=None,
            language_source="heuristic",
        )

    validated_existing, rejected_existing = _validate_keywords_against_source(existing, source_text, limit=50)
    prompt = _build_document_keywords_prompt()
    timeout = float(timeout_seconds or getattr(settings, "QWEN_CHAT_TIMEOUT_SECONDS", 300.0) or 300.0)

    response_text = ""
    error_text = ""
    effective_session_id = session_id
    with tempfile.TemporaryDirectory(prefix="nickelfront_keywords_") as temp_dir:
        temp_path = Path(temp_dir) / "document_keywords_source.txt"
        temp_path.write_text(source_text, encoding="utf-8")
        max_upload_mb = float(os.getenv("QWEN_FILE_UPLOAD_MAX_SIZE_MB", "20") or 20)
        max_upload_bytes = int(max_upload_mb * 1024 * 1024)
        source_file_size = temp_path.stat().st_size
        if source_file_size > max_upload_bytes:
            raise RuntimeError(
                f"qwen_file_too_large: document keywords source is {source_file_size} bytes, "
                f"maximum is {max_upload_bytes} bytes ({max_upload_mb:g} MB)"
            )

        qwen_client = get_qwen_client()
        result = qwen_client.upload_file_and_send_message(
            file_path=str(temp_path),
            message=prompt,
            session_id=session_id,
            thinking_enabled=False,
            search_enabled=False,
            auto_continue=False,
            timeout=timeout,
        )
        response_text = (result.get("response") or "").strip()
        error_text = str(result.get("error") or "").strip()
        effective_session_id = str(result.get("session_id") or session_id or "") or None

    if not response_text:
        message = error_text or "empty_qwen_response"
        logger.warning(
            "Keyword extraction returned empty response for title='{}': {}",
            str(title or "")[:80],
            message,
        )
        raise RuntimeError(f"qwen_keywords_empty_response: {message}")

    generated, parsed_ok, language = _parse_keywords_response_with_status(response_text)
    if not parsed_ok:
        logger.warning(
            "Keyword extraction returned non-JSON response for title='{}': {}",
            str(title or "")[:80],
            response_text[:300],
        )
        raise RuntimeError("qwen_keywords_invalid_json_response")
    validated_generated, rejected_generated = _validate_keywords_against_source(generated, source_text, limit=50)
    merged = _dedupe_keywords([*validated_existing, *validated_generated], limit=50)
    rejected = [*rejected_existing, *rejected_generated]

    if rejected:
        logger.info(
            "Rejected {} keyword(s) not found in document text for title='{}': {}",
            len(rejected),
            str(title or "")[:80],
            rejected[:20],
        )
    if not merged:
        logger.warning("Keyword extraction produced no validated keywords for title='{}'", str(title or "")[:80])

    return KeywordGenerationResult(
        keywords=merged,
        generated_count=len(generated),
        validated_count=len(merged),
        rejected_count=len(rejected),
        source_chars=source_chars,
        source_mode=source_mode,
        session_id=effective_session_id,
        rejected_keywords=rejected[:50],
        language_code=language.code,
        language_name=language.name,
        language_confidence=language.confidence,
        language_source=language.source,
    )


def generate_article_keywords(
    *,
    title: str,
    authors: list[str] | None = None,
    journal: str | None = None,
    doi: str | None = None,
    source: str | None = None,
    source_id: str | None = None,
    url: str | None = None,
    abstract: str | None,
    full_text: str | None,
    existing_keywords: list[str] | None,
    summary_ru: str | None = None,
    analysis_ru: str | None = None,
    translation_ru: str | None = None,
    session_id: str | None = None,
    timeout_seconds: float | None = None,
) -> list[str]:
    """Backward-compatible wrapper for old article keyword callers.

    Metadata, summaries, translations and AI analysis are intentionally ignored:
    keywords must be validated against the original document text only.
    """
    _ = (authors, journal, doi, source, source_id, url, summary_ru, analysis_ru, translation_ru)
    result = generate_document_keywords(
        title=title,
        abstract=abstract,
        full_text=full_text,
        existing_keywords=existing_keywords,
        session_id=session_id,
        timeout_seconds=timeout_seconds,
    )
    return result.keywords
