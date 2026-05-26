from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AI_PAGE_OCR_SESSION_PROMPT = """Ты выполняешь точную оцифровку страниц PDF по изображениям.

Правила для всех следующих изображений:
1. Возвращай только текст, который реально виден на изображении.
2. Текст должен быть на том языке, на котором написана статья.
3. Не переводи текст на другой язык.
4. Не добавляй комментарии, объяснения, заголовки от себя или выводы.
5. Не придумывай отсутствующие слова, символы, формулы, авторов или числа.
6. Если фрагмент неразборчив, напиши [UNREADABLE].
7. Сохраняй естественный порядок чтения страницы.
8. Если страница двухколоночная, сначала верни левую колонку сверху вниз, затем правую колонку сверху вниз.
9. Формулы возвращай обычной текстовой строкой настолько точно, насколько видно.
10. Таблицы возвращай построчно как обычный текст, сохраняя разделение колонок пробелами или табуляцией.
11. Не используй Markdown-разметку специально.
12. Не возвращай JSON.
13. Не оборачивай ответ в кодовый блок.
14. Если текста на странице нет, верни пустую строку.

На каждое следующее изображение отвечай только оцифрованным текстом страницы."""

AI_PAGE_OCR_MESSAGE = "Оцифруй эту страницу в чистый текст. Верни только текст страницы на языке, на котором написана статья."


@dataclass(slots=True)
class AIPageResult:
    page_number: int
    text: str = ""
    confidence: float = 0.0
    provider: str = ""
    model: str = ""
    status: str = "not_configured"
    reason: str = "ai_page_recognition_stub"
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class AIPageRecognitionService:
    """AI page-image OCR helper.

    Public parser mode ``ai`` is implemented as an optional page-image OCR path:
    one Qwen chat session per document, one instruction prompt at session start,
    then each page image is sent with a short "ocr to text" message.

    The model is not asked for JSON/Markdown/blocks. It returns plain page text;
    parser code wraps that text into page dictionaries and metadata.
    """

    def __init__(self) -> None:
        self._session_id: str | None = None
        self._session_prompt_sent = False
        self._pages_processed = 0

    def reset_document_session(self) -> None:
        self._session_id = None
        self._session_prompt_sent = False
        self._pages_processed = 0

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def _provider(self, opts: dict[str, Any] | None) -> str:
        options = opts or {}
        return str(options.get("ai_provider") or "qwen").strip().lower() or "qwen"

    def _image_format(self, opts: dict[str, Any] | None) -> str:
        fmt = str((opts or {}).get("ai_page_image_format") or "png").strip().lower()
        return fmt if fmt in {"png", "jpg", "jpeg"} else "png"

    def _render_pdf_page_to_image(
        self,
        *,
        file_bytes: bytes,
        page_number: int,
        opts: dict[str, Any] | None,
    ) -> Path:
        options = opts or {}
        dpi = int(options.get("ai_render_dpi") or 220)
        image_format = self._image_format(options)
        suffix = ".jpg" if image_format == "jpeg" else f".{image_format}"

        try:
            import fitz
        except Exception as exc:
            raise RuntimeError(f"fitz_unavailable:{exc}") from exc

        doc = None
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            page_index = max(0, int(page_number) - 1)
            if page_index >= len(doc):
                raise RuntimeError(f"page_index_out_of_range:{page_number}")
            page = doc.load_page(page_index)
            zoom = max(0.5, float(dpi) / 72.0)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            temp = tempfile.NamedTemporaryFile(prefix=f"nickelfront_ai_page_{page_number}_", suffix=suffix, delete=False)
            temp_path = Path(temp.name)
            temp.close()
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

    def _clean_ai_text(self, value: str) -> str:
        text = (value or "").strip()
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            if len(lines) >= 2:
                lines = lines[1:-1]
                text = "\n".join(lines).strip()
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text.strip()

    def _start_qwen_session(self, *, opts: dict[str, Any] | None) -> tuple[str | None, list[str]]:
        warnings: list[str] = []
        if self._session_id and self._session_prompt_sent:
            return self._session_id, warnings

        try:
            from app.services.qwen_client import get_qwen_client
        except Exception as exc:
            warnings.append(f"qwen_client_import_failed:{exc}")
            return None, warnings

        client = get_qwen_client()
        timeout = float((opts or {}).get("ai_timeout_sec") or 120)
        try:
            result = client.send_message(
                AI_PAGE_OCR_SESSION_PROMPT,
                session_id=None,
                thinking_enabled=False,
                search_enabled=False,
                auto_continue=False,
                timeout=timeout,
            )
        except Exception as exc:
            warnings.append(f"qwen_session_prompt_failed:{type(exc).__name__}:{exc}")
            return None, warnings

        if not isinstance(result, dict) or result.get("error"):
            warnings.append(f"qwen_session_prompt_error:{(result or {}).get('error') or 'unknown'}")
            return None, warnings

        sid = str(result.get("session_id") or client.session_id or "").strip()
        if not sid:
            warnings.append("qwen_session_id_missing")
            return None, warnings

        self._session_id = sid
        self._session_prompt_sent = True
        return sid, warnings

    def recognize_page(
        self,
        *,
        file_bytes: bytes,
        page_number: int,
        page_width: float = 0.0,
        page_height: float = 0.0,
        opts: dict[str, Any] | None = None,
    ) -> AIPageResult:
        options = opts or {}
        provider = self._provider(options)
        model = str(options.get("ai_model") or "").strip()
        render_dpi = int(options.get("ai_render_dpi") or 220)
        image_format = self._image_format(options)
        enabled = bool(options.get("ai_enabled"))
        mode = str(options.get("ai_mode") or "off").strip().lower()
        timeout = float(options.get("ai_timeout_sec") or 120)
        delete_temp = bool(options.get("ai_delete_temp_images", True))

        base_meta = {
            "ai_mode": mode,
            "ai_enabled": enabled,
            "ai_provider": provider,
            "ai_model": model,
            "ai_render_dpi": render_dpi,
            "ai_page_image_format": image_format,
            "ai_page_width": float(page_width or 0.0),
            "ai_page_height": float(page_height or 0.0),
            "ai_page_image_expected": True,
            "ai_prompt_version": "plain_page_text_v1",
            "ai_session_prompt_sent": bool(self._session_prompt_sent),
            "ai_external_call_performed": False,
        }

        if not enabled:
            return AIPageResult(
                page_number=page_number,
                provider=provider,
                model=model,
                status="disabled",
                reason="ai_disabled",
                warnings=["ai_disabled"],
                metadata=base_meta,
            )
        if provider != "qwen":
            return AIPageResult(
                page_number=page_number,
                provider=provider,
                model=model,
                status="not_configured",
                reason="unsupported_ai_provider",
                warnings=["unsupported_ai_provider"],
                metadata=base_meta,
            )

        temp_path: Path | None = None
        warnings: list[str] = []
        try:
            sid, start_warnings = self._start_qwen_session(opts=options)
            warnings.extend(start_warnings)
            if not sid:
                return AIPageResult(
                    page_number=page_number,
                    provider=provider,
                    model=model,
                    status="not_configured",
                    reason="qwen_session_not_available",
                    warnings=warnings or ["qwen_session_not_available"],
                    metadata={**base_meta, "ai_session_id": ""},
                )

            temp_path = self._render_pdf_page_to_image(
                file_bytes=file_bytes,
                page_number=page_number,
                opts=options,
            )

            from app.services.qwen_client import get_qwen_client

            client = get_qwen_client()
            result = client.upload_file_and_send_message(
                file_path=str(temp_path),
                message=AI_PAGE_OCR_MESSAGE,
                session_id=sid,
                thinking_enabled=False,
                search_enabled=False,
                auto_continue=False,
                timeout=timeout,
                session_prompt=AI_PAGE_OCR_SESSION_PROMPT,
            )
            response = self._clean_ai_text(str((result or {}).get("response") or ""))
            replacement_session = bool((result or {}).get("used_replacement_session"))
            returned_sid = str((result or {}).get("session_id") or sid)
            if returned_sid:
                self._session_id = returned_sid
                self._session_prompt_sent = True

            self._pages_processed += 1
            status = "success" if response else "empty_response"
            reason = "ai_page_text_received" if response else "ai_empty_response"
            if not response:
                warnings.append("ai_empty_response")
            meta = {
                **base_meta,
                "ai_session_id": self._session_id or sid,
                "ai_session_prompt_sent": True,
                "ai_page_index": int(page_number),
                "ai_pages_processed": self._pages_processed,
                "ai_temp_image_path": str(temp_path) if not delete_temp else "",
                "ai_external_call_performed": True,
                "ai_response_chars": len(response),
                "ai_page_text_chars": len(response),
                "ai_upload_attempts": int((result or {}).get("upload_attempts") or 3),
                "ai_replacement_session_used": replacement_session,
                "ai_message_id": (result or {}).get("message_id") or 0,
            }
            if replacement_session:
                warnings.append("ai_replacement_session_used")
            return AIPageResult(
                page_number=page_number,
                text=response,
                confidence=1.0 if response else 0.0,
                provider=provider,
                model=model,
                status=status,
                reason=reason,
                warnings=warnings,
                metadata=meta,
            )
        except Exception as exc:
            logger.exception("AI page recognition failed for page %s", page_number)
            reason = f"ai_provider_error:{type(exc).__name__}"
            return AIPageResult(
                page_number=page_number,
                provider=provider,
                model=model,
                status="provider_error",
                reason=reason,
                warnings=[reason],
                metadata={**base_meta, "ai_error": str(exc), "ai_session_id": self._session_id or ""},
            )
        finally:
            if temp_path and delete_temp:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def run_page_stub(
        self,
        *,
        page_number: int,
        page_width: float = 0.0,
        page_height: float = 0.0,
        opts: dict[str, Any] | None = None,
    ) -> AIPageResult:
        options = opts or {}
        provider = self._provider(options)
        model = str(options.get("ai_model") or "").strip()
        render_dpi = int(options.get("ai_render_dpi") or 220)
        image_format = self._image_format(options)
        enabled = bool(options.get("ai_enabled"))
        mode = str(options.get("ai_mode") or "off").strip().lower()
        reason = "ai_disabled" if not enabled else "ai_runtime_not_called"
        return AIPageResult(
            page_number=page_number,
            text="",
            confidence=0.0,
            provider=provider,
            model=model,
            status="disabled" if not enabled else "not_implemented",
            reason=reason,
            warnings=[reason],
            metadata={
                "ai_mode": mode,
                "ai_enabled": enabled,
                "ai_provider": provider,
                "ai_model": model,
                "ai_render_dpi": render_dpi,
                "ai_page_image_format": image_format,
                "ai_page_width": float(page_width or 0.0),
                "ai_page_height": float(page_height or 0.0),
                "ai_page_image_expected": True,
                "ai_external_call_performed": False,
            },
        )


__all__ = [
    "AI_PAGE_OCR_MESSAGE",
    "AI_PAGE_OCR_SESSION_PROMPT",
    "AIPageRecognitionService",
    "AIPageResult",
]
