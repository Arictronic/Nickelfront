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
from app.services.rag_parser import pdf_parser


@dataclass
class AIEnrichmentResult:
    summary_ru: str
    analysis_ru: str
    translation_ru: str
    used_fallback: bool = False
    fallback_reason: str | None = None


_PAGE_MARKER_SPLIT_RE = re.compile("(?=\\[(?:\\u0421\\u0442\\u0440\\u0430\\u043d\\u0438\\u0446\\u0430|Page)\\s+\\d+\\])")

def _decode_cp1251_utf8_mojibake(value: str) -> str:
    try:
        return value.encode("cp1251").decode("utf-8")
    except Exception:
        return value


PDF_MARKDOWN_SYSTEM_PROMPT = _decode_cp1251_utf8_mojibake("""Ты — редактор научных PDF-статей. Тебе будут по порядку передаваться сырые OCR/извлечённые данные страниц PDF.

Твоя задача: восстановить содержимое страницы в чистом Markdown, сохранив всю исходную информацию без смысловых потерь.

Правила обработки:

1. Не добавляй ничего от себя.
2. Не объясняй свои действия.
3. Не пиши вступления, комментарии, выводы или предупреждения.
4. Выводи только обработанный Markdown.
5. Сохраняй структуру статьи:
   - заголовки;
   - авторов;
   - организации;
   - abstract;
   - keywords;
   - разделы и подразделы;
   - таблицы;
   - подписи к рисункам;
   - сноски;
   - формулы;
   - references.
6. Исправляй очевидные OCR-ошибки форматирования:
   - слитые слова;
   - пропущенные пробелы;
   - переносы строк внутри предложений;
   - неправильные разрывы абзацев;
   - мусорные символы от PDF-вёрстки.
7. Не исправляй научный смысл, числа, единицы измерения, имена, даты, формулы и ссылки, если нет полной уверенности.
8. Если таблица распознана плохо, восстанови её в Markdown-таблицу настолько точно, насколько возможно.
9. Если рисунок представлен только подписью, сохрани подпись как **Figure X.** ....
10. Если встречается текст вида [Страница N], используй его только как границу страницы и не выводи в результате.
11. Не удаляй повторяющиеся или странно выглядящие данные, если они могут быть частью статьи.
12. Не объединяй разные страницы в один раздел искусственно. Обрабатывай только полученную страницу.
13. Сохраняй язык оригинала.
14. Математические выражения оформляй в Markdown/LaTeX:
    - inline: $...$
    - отдельной строкой: $$...$$
15. Если часть текста невозможно надёжно восстановить, оставь её максимально близко к оригиналу, не придумывая недостающее.

Формат ответа: только Markdown. Без дополнительного текста.""")


def _clean_arxiv_id(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    value = value.replace("http://", "https://")
    if "arxiv.org/abs/" in value:
        value = value.split("arxiv.org/abs/", 1)[1]
    elif "arxiv.org/pdf/" in value:
        value = value.split("arxiv.org/pdf/", 1)[1]
    if value.startswith("arXiv:"):
        value = value[6:]
    value = value.split("/")[-1]
    value = value.replace(".pdf", "")
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
    try:
        return pdf_parser.extract_text_from_bytes(pdf_bytes)
    except Exception as exc:
        logger.warning("Failed to extract text from PDF: {}", exc)
        return ""


def _clean_html_text(raw: str) -> str:
    # Decode entities first so encoded tags (&lt;div&gt;) are also removed.
    text = html.unescape(raw or "")
    text = html.unescape(text)
    text = re.sub(r"<script[\\s\\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\\s\\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<noscript[\\s\\S]*?</noscript>", " ", text, flags=re.IGNORECASE)
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


def normalize_pdf_text_markdown(
    paper_id: int,
    title: str,
    raw_text: str,
    session_id: str | None = None,
    on_page_markdown: Callable[[int, str], None] | None = None,
) -> str:
    pages = _split_pdf_text_into_pages(raw_text)
    if not pages:
        return ""

    qwen_client = get_qwen_client()
    normalized_parts: list[str] = []
    active_session_id = session_id
    max_page_attempts = 3
    session_needs_prompt = True
    pages_per_request = 3
    page_batches = [pages[i : i + pages_per_request] for i in range(0, len(pages), pages_per_request)]
    current_page = 1

    for batch in page_batches:
        response_text = ""
        batch_text = "\n\n".join(f"[Page {current_page + offset}]\n{page[:18000]}" for offset, page in enumerate(batch))
        batch_range_start = current_page
        batch_range_end = current_page + len(batch) - 1

        for attempt in range(1, max_page_attempts + 1):
            if session_needs_prompt:
                prompt = (
                    f"{PDF_MARKDOWN_SYSTEM_PROMPT}\n\n"
                    f"Article title: {title}\n"
                    f"{batch_text}"
                )
            else:
                prompt = batch_text

            result = qwen_client.send_message(
                message=prompt,
                session_id=active_session_id,
                thinking_enabled=True,
                search_enabled=False,
                auto_continue=False,
                timeout=240.0,
            )
            response_text = (result.get("response") or "").strip()
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

        page_payload = response_text or batch_text
        normalized_parts.append(f"### Pages {batch_range_start}-{batch_range_end}\n\n{page_payload}".strip())
        if on_page_markdown:
            try:
                on_page_markdown(batch_range_end, "\n\n".join(normalized_parts).strip())
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
        timeout=240.0,
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
