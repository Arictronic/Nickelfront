"""Article content post-processing helpers (PDF/full-text + RU AI enrichment)."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from loguru import logger

from app.core.config import settings
from app.services.qwen_client import get_qwen_client


@dataclass
class AIEnrichmentResult:
    summary_ru: str
    analysis_ru: str
    translation_ru: str
    used_fallback: bool = False
    fallback_reason: str | None = None


MAX_KEYWORD_SOURCE_CHARS = 32000
PDF_MARKDOWN_PROMPT_VERSION = "pdf-markdown-v2-parts"

# Callback arguments: processed pages, total pages, current markdown.
MarkdownProgressCallback = Callable[[int, int, str], None]


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

    # EuropePMC: do not synthesize PDF links from source_id.
    # Many records (MED/AGR/etc.) do not provide real PDF and generated links return 404.
    # We keep only explicit PDF URLs received from the upstream source.
    if src == "europepmc":
        return None

    return None


def _extract_pdf_link_from_html(base_url: str, html_text: str) -> str | None:
    if not html_text:
        return None
    matches = re.findall(r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', html_text, flags=re.IGNORECASE)
    if not matches:
        return None
    return urljoin(base_url, matches[0])


def download_pdf_bytes(pdf_url: str, timeout_sec: float = 45.0) -> bytes | None:
    try:
        with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
            response = client.get(pdf_url, headers={"Accept": "application/pdf,application/octet-stream;q=0.9,text/html;q=0.2,*/*;q=0.1"})
            response.raise_for_status()
            content = response.content or b""
            if not content:
                return None

            content_type = (response.headers.get("content-type") or "").lower()
            if "pdf" in content_type or content.startswith(b"%PDF"):
                return content

            # Fallback: landing page with a direct PDF link.
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
        logger.warning("Failed to download PDF {}: {}", pdf_url, exc)
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
        from app.services.rag_parser import pdf_parser

        return pdf_parser.extract_text_from_bytes(pdf_bytes)
    except Exception as exc:
        logger.warning("Failed to extract text from PDF: {}", exc)
        return ""


def extract_pdf_page_items(pdf_bytes: bytes, options: dict | None = None) -> list[dict]:
    """Извлечь PDF постранично с диагностикой качества.

    Возвращает список dict, чтобы content task не зависел от конкретного
    dataclass rag_parser и мог безопасно передавать данные в service-layer.
    """
    try:
        from app.services.rag_parser import pdf_parser

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


def extract_pdf_pages(pdf_bytes: bytes) -> list[str]:
    """Backward-compatible page text extraction."""
    return [str(item.get("text") or "") for item in extract_pdf_page_items(pdf_bytes)]


def _clean_html_text(raw: str) -> str:
    # Decode entities first so encoded tags (&lt;div&gt;) are also removed.
    text = html.unescape(raw or "")
    text = html.unescape(text)
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<noscript[\s\S]*?</noscript>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    # Second pass to catch tags revealed by unescape cascades.
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

    # Prefer fullTextXML endpoint for maximal text extraction.
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
    session_title = f"paper-{paper_id}: {title[:80]}".strip()
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

    # Fallback split for PDFs without explicit page markers.
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

    # Remove accidental markdown fences around the whole answer.
    value = re.sub(r"^```(?:markdown|md)?\s*", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"\s*```$", "", value).strip()
    value = value.replace("\r\n", "\n").replace("\r", "\n")

    # Keep Markdown readable: separate headings and tables from surrounding text.
    value = re.sub(r"(?<!\n)\n(#{1,6}\s+)", r"\n\n\1", value)
    value = re.sub(r"(#{1,6}[^\n]+)\n(?!\n)", r"\1\n\n", value)
    value = re.sub(r"(?<!\n)\n(\|.+\|)", r"\n\n\1", value)
    value = re.sub(r"(\|.+\|)\n(?!\n|\|)", r"\1\n\n", value)

    # Normalize common LaTeX delimiters for remark-math / KaTeX rendering.
    if normalize_math:
        value = re.sub(r"\\\((.+?)\\\)", lambda m: f"${m.group(1).strip()}$", value, flags=re.DOTALL)
        value = re.sub(r"\\\[(.+?)\\\]", lambda m: f"$$\n{m.group(1).strip()}\n$$", value, flags=re.DOTALL)

    # Separate glued headings commonly returned by LLMs from compact PDF text.
    value = re.sub(r"(?<!\n)(#{1,6}\s+)", r"\n\n\1", value)
    value = re.sub(r"(?<!\n)(\b(?:Abstract|Keywords|References|Acknowledg(?:e)?ments)\b\s*:?)", r"\n\n## \1", value, flags=re.IGNORECASE)
    value = re.sub(r"(?<!\n)(\b[IVX]{1,6}\.\s+[A-Z][A-Z0-9 ,:;()\-/]{3,})", r"\n\n## \1", value)

    # Collapse excessive blank lines, but keep paragraph breaks.
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
        batch_text = "\n\n".join(f"[Page {current_page + offset}]\n{page[:page_char_limit]}" for offset, page in enumerate(batch))
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
        normalized_parts.append(f"### Pages {batch_range_start}-{batch_range_end}\n\n{page_payload}".strip())
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


def _normalize_keyword(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n,;:.")
    return cleaned[:120]


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
        return [str(item) for item in raw if str(item or "").strip()]
    if isinstance(raw, str):
        parts = re.split(r"[,;\n]+", raw)
        return [part for part in parts if part.strip()]
    return []


def _parse_keywords_response(response_text: str) -> list[str]:
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
        return _coerce_keyword_list(parsed.get("keywords"))
    if isinstance(parsed, list):
        return _coerce_keyword_list(parsed)
    return []


def _sample_text_chunks(text: str, chunk_size: int = 6000, max_chunks: int = 5) -> list[str]:
    clean = (text or "").strip()
    if not clean:
        return []
    chunks = [clean[i : i + chunk_size].strip() for i in range(0, len(clean), chunk_size)]
    chunks = [chunk for chunk in chunks if chunk]
    if len(chunks) <= max_chunks:
        return chunks

    indexes = sorted({round(i * (len(chunks) - 1) / (max_chunks - 1)) for i in range(max_chunks)})
    return [chunks[index] for index in indexes]


def generate_article_keywords(
    *,
    title: str,
    authors: list[str] | None,
    journal: str | None,
    doi: str | None,
    source: str | None,
    source_id: str | None,
    url: str | None,
    abstract: str | None,
    full_text: str | None,
    existing_keywords: list[str] | None,
    summary_ru: str | None = None,
    analysis_ru: str | None = None,
    translation_ru: str | None = None,
    session_id: str | None = None,
    timeout_seconds: float | None = None,
) -> list[str]:
    """Generate 10-50 article keywords with Qwen, preserving useful existing keywords."""
    existing = _dedupe_keywords(existing_keywords or [])
    text_sections = _sample_text_chunks(full_text or abstract or "")
    chunks_text = "\n\n".join(
        f"[Фрагмент текста {index}/{len(text_sections)}]\n{chunk}"
        for index, chunk in enumerate(text_sections, start=1)
    )

    article_payload = {
        "title": title,
        "authors": authors or [],
        "journal": journal,
        "doi": doi,
        "source": source,
        "source_id": source_id,
        "url": url,
        "existing_keywords": existing,
        "abstract": abstract or "",
        "summary_ru": summary_ru or "",
        "analysis_ru": analysis_ru or "",
        "translation_ru": translation_ru or "",
    }

    payload_json = json.dumps(article_payload, ensure_ascii=False, indent=2)
    prompt = (
        "Ты научный ассистент по разметке статей.\n"
        "Нужно выделить от 10 до 50 ключевых слов и коротких терминологических фраз для статьи.\n\n"
        "Используй всю переданную информацию: метаданные, авторские keywords, аннотацию, AI-анализ, перевод и фрагменты полного текста.\n"
        "Если existing_keywords уже содержат полезные ключевые слова, обязательно сохрани их в итоговом списке.\n"
        "Добавь недостающие термины из содержания статьи: материалы, сплавы, методы, свойства, процессы, области применения, важные параметры.\n\n"
        "Правила:\n"
        "1) Верни только строгий JSON без markdown.\n"
        "2) Формат: {\"keywords\":[\"keyword 1\",\"keyword 2\"]}\n"
        "3) Количество keywords: минимум 10, максимум 50.\n"
        "4) Не выдумывай термины, которых нет или которые не следуют из статьи.\n"
        "5) Убирай дубли, слишком общие слова и целые предложения.\n"
        "6) Предпочитай язык оригинальной статьи для технических терминов; русские термины допустимы, если статья/анализ на русском.\n"
        "7) Один keyword должен быть коротким: обычно 1-5 слов.\n\n"
        f"Информация о статье:\n{payload_json}\n\n"
        f"Фрагменты полного текста:\n{chunks_text[:MAX_KEYWORD_SOURCE_CHARS]}"
    )

    qwen_client = get_qwen_client()
    result = qwen_client.send_message(
        message=prompt,
        session_id=session_id,
        thinking_enabled=True,
        search_enabled=False,
        auto_continue=True,
        timeout=float(timeout_seconds or getattr(settings, "QWEN_CHAT_TIMEOUT_SECONDS", 300.0) or 300.0),
    )

    response_text = (result.get("response") or "").strip()
    error_text = str(result.get("error") or "").strip()
    if not response_text:
        logger.warning("Keyword generation returned empty response for title='{}': {}", title[:80], error_text or "none")
        return existing

    generated = _parse_keywords_response(response_text)
    merged = _dedupe_keywords([*existing, *generated], limit=50)
    if not merged:
        logger.warning("Keyword generation returned no parseable keywords for title='{}'", title[:80])
        return existing

    return merged
