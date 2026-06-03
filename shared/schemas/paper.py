"""Схемы данных для научных статей."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


def _coerce_json_list(value: object, *, split_commas: bool = True) -> list:
    """Coerce legacy DB/parser values to a JSON-list friendly shape.

    API clients sometimes return authors/keywords as objects such as
    {"name": "Alice Smith"}.  Treat those as text payloads, not as Python
    repr strings like "{'name': 'Alice Smith'}".
    """
    import json
    import re

    semantic_keys = (
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

    def dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        output: list[str] = []
        for item in items:
            text = str(item).strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            output.append(text)
        return output

    if value is None:
        return []
    if isinstance(value, dict):
        for key in semantic_keys:
            if key in value:
                extracted = _coerce_json_list(value.get(key), split_commas=split_commas)
                if extracted:
                    return extracted
        output: list[str] = []
        for item in value.values():
            output.extend(_coerce_json_list(item, split_commas=split_commas))
        return dedupe(output)
    if isinstance(value, (list, tuple, set)):
        output: list[str] = []
        for item in value:
            output.extend(_coerce_json_list(item, split_commas=split_commas))
        return dedupe(output)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, (list, tuple, set, dict)):
                return _coerce_json_list(parsed, split_commas=split_commas)
            if isinstance(parsed, str) and parsed.strip():
                return [parsed.strip()]
        except Exception:
            pass
        pattern = r"[;,\n]+" if split_commas else r"[;\n]+"
        parts = [part.strip() for part in re.split(pattern, text) if part.strip()]
        return parts or [text]
    text = str(value).strip()
    return [text] if text else []


def _coerce_text_scalar(value: object, *, default: str | None = None) -> str | None:
    """Unwrap scalar API/legacy fields without storing Python repr strings."""
    import html
    import re

    semantic_keys = (
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

    def unwrap(item: object) -> object | None:
        if item is None:
            return None
        if isinstance(item, (str, int, float)):
            return item
        if isinstance(item, dict):
            for key in semantic_keys:
                if key in item:
                    candidate = unwrap(item.get(key))
                    if candidate not in (None, ""):
                        return candidate
            for nested in item.values():
                candidate = unwrap(nested)
                if candidate not in (None, ""):
                    return candidate
            return None
        if isinstance(item, (list, tuple, set)):
            for nested in item:
                candidate = unwrap(nested)
                if candidate not in (None, ""):
                    return candidate
            return None
        return item

    unwrapped = unwrap(value)
    if unwrapped is None:
        return default
    text = html.unescape(str(unwrapped))
    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split()).strip()
    return text or default


def _normalize_doi_value(value: object) -> str | None:
    import re
    from urllib.parse import urlparse

    text = _coerce_text_scalar(value)
    if not text:
        return None
    parsed = urlparse(text.strip())
    if parsed.scheme in {"http", "https"} and parsed.netloc.lower() in {"doi.org", "dx.doi.org"}:
        text = parsed.path.lstrip("/")
    else:
        text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = text.strip().strip(".;, ")
    return text.lower() if re.match(r"^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$", text) else None


def _coerce_json_dict(value: object) -> dict:
    """Coerce legacy/NULL metadata values to a dict for response validation."""
    import json

    if value is None:
        return {}
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_text = _coerce_text_scalar(key)
            item_text = _coerce_text_scalar(item)
            if key_text and item_text:
                result[key_text] = item_text
        return result
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return _coerce_json_dict(parsed)
        except Exception:
            return {}
    return {}


class PaperBase(BaseModel):
    """Базовая схема статьи."""

    title: str = Field(..., description="Название статьи")
    authors: list[str] = Field(default_factory=list, description="Список авторов")
    publication_date: datetime | None = Field(None, description="Дата публикации")
    journal: str | None = Field(None, description="Название журнала/источника")
    doi: str | None = Field(None, description="DOI статьи")
    abstract: str | None = Field(None, description="Аннотация")
    full_text: str | None = Field(None, description="Полный текст статьи")
    keywords: list[str] = Field(default_factory=list, description="Ключевые слова")
    language_code: str | None = Field(None, description="ISO 639-1 код основного языка документа")
    language_name: str | None = Field(None, description="Название основного языка документа")
    language_confidence: float | None = Field(None, ge=0.0, le=1.0, description="Уверенность определения языка")
    language_source: str | None = Field(None, description="Источник определения языка")
    available_language_codes: list[str] = Field(default_factory=list, description="Доступные языковые слои текста статьи")
    translation_status: str | None = Field(None, description="Статус перевода текста статьи")
    translation_task_id: str | None = Field(None, description="ID Celery задачи перевода текста статьи")
    translation_error: str | None = Field(None, description="Ошибка перевода текста статьи")
    source: str = Field(..., description="Источник (CORE, arXiv, etc.)")
    source_id: str | None = Field(None, description="ID в источнике")
    canonical_patent_id: str | None = Field(None, description="Canonical cross-source patent identifier")
    url: str | None = Field(None, description="URL статьи")
    pdf_url: str | None = Field(None, description="URL PDF")
    pdf_local_path: str | None = Field(None, description="Локальный путь к PDF")
    processing_status: str = Field(default="pending", description="Статус обработки")
    content_task_id: str | None = Field(None, description="ID Celery задачи обработки контента")
    processing_error: str | None = Field(None, description="Текст ошибки обработки")
    summary_ru: str | None = Field(None, description="Краткая суть статьи на русском")
    analysis_ru: str | None = Field(None, description="Анализ статьи на русском")
    translation_ru: str | None = Field(None, description="Перевод статьи на русский")
    parse_confidence: float | None = Field(None, ge=0.0, le=1.0, description="Parser confidence score (0-1)")
    provenance: dict[str, str] = Field(default_factory=dict, description="Per-field provenance metadata")
    quality_flags: list[str] = Field(default_factory=list, description="Quality/degradation flags from parser pipeline")
    schema_version: str | None = Field(default="2.0", description="Normalized record schema version")

    @field_validator(
        "title",
        "journal",
        "abstract",
        "full_text",
        "language_code",
        "language_name",
        "language_source",
        "translation_status",
        "translation_task_id",
        "translation_error",
        "source",
        "source_id",
        "canonical_patent_id",
        "url",
        "pdf_url",
        "pdf_local_path",
        "processing_status",
        "content_task_id",
        "processing_error",
        "summary_ru",
        "analysis_ru",
        "translation_ru",
        mode="before",
    )
    @classmethod
    def _normalize_scalar_text_fields(cls, value, info: ValidationInfo):
        if info.field_name in {"title", "source"} and isinstance(value, str) and value.strip() == "":
            return ""
        return _coerce_text_scalar(value)

    @field_validator("doi", mode="before")
    @classmethod
    def _normalize_doi(cls, value):
        return _normalize_doi_value(value)

    @field_validator("authors", "keywords", "quality_flags", "available_language_codes", mode="before")
    @classmethod
    def _normalize_list_fields(cls, value, info: ValidationInfo):



        return _coerce_json_list(value, split_commas=info.field_name != "authors")

    @field_validator("provenance", mode="before")
    @classmethod
    def _normalize_provenance(cls, value):
        return _coerce_json_dict(value)

    @field_validator("parse_confidence", "language_confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value):
        if value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number > 1 and number <= 100:
            number = number / 100
        return max(0.0, min(1.0, number))

    @field_validator("schema_version", mode="before")
    @classmethod
    def _normalize_schema_version(cls, value):
        return _coerce_text_scalar(value, default="2.0") or "2.0"


class PaperCreate(PaperBase):
    """Схема для создания статьи."""

    pass


class Paper(PaperBase):
    """Схема статьи."""

    id: int | None = Field(None, description="ID в БД")
    created_at: datetime | None = Field(None, description="Дата добавления в БД")
    updated_at: datetime | None = Field(None, description="Дата обновления")

    model_config = ConfigDict(from_attributes=True)


class PaperListItem(BaseModel):
    """Лёгкая схема списка статей без тяжёлого PDF/full_text payload."""

    id: int
    title: str
    authors: list[str] = Field(default_factory=list)
    publication_date: datetime | None = None
    journal: str | None = None
    doi: str | None = None
    abstract: str | None = None
    full_text: str | None = None
    keywords: list[str] = Field(default_factory=list)
    language_code: str | None = None
    language_name: str | None = None
    language_confidence: float | None = None
    language_source: str | None = None
    available_language_codes: list[str] = Field(default_factory=list)
    translation_status: str | None = None
    translation_task_id: str | None = None
    translation_error: str | None = None
    source: str
    source_id: str | None = None
    canonical_patent_id: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    pdf_local_path: str | None = None
    processing_status: str = "pending"
    content_task_id: str | None = None
    processing_error: str | None = None
    summary_ru: str | None = None
    analysis_ru: str | None = None
    translation_ru: str | None = None
    parse_confidence: float | None = None
    provenance: dict = Field(default_factory=dict)
    quality_flags: list[str] = Field(default_factory=list)
    schema_version: str | None = "2.0"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    has_pdf: bool = False
    has_full_text: bool = False
    rank: float | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("title", "journal", "abstract", "language_code", "language_name", "language_source", "translation_status", "translation_task_id", "translation_error", "source", "source_id", "canonical_patent_id", "url", "pdf_url", "pdf_local_path", "processing_status", "content_task_id", "processing_error", "summary_ru", "analysis_ru", "translation_ru", "schema_version", mode="before")
    @classmethod
    def _normalize_scalar_text_fields(cls, value, info: ValidationInfo):
        if info.field_name in {"title", "source"} and isinstance(value, str) and value.strip() == "":
            return ""
        return _coerce_text_scalar(value)

    @field_validator("doi", mode="before")
    @classmethod
    def _normalize_doi(cls, value):
        return _normalize_doi_value(value)

    @field_validator("parse_confidence", "language_confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value):
        if value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number > 1 and number <= 100:
            number = number / 100
        return max(0.0, min(1.0, number))

    @field_validator("authors", "keywords", "quality_flags", "available_language_codes", mode="before")
    @classmethod
    def _normalize_list_fields(cls, value, info: ValidationInfo):
        return _coerce_json_list(value, split_commas=info.field_name != "authors")

    @field_validator("provenance", mode="before")
    @classmethod
    def _normalize_provenance(cls, value):
        return _coerce_json_dict(value)


class PaperListResponse(BaseModel):
    """Постраничный ответ списка статей с backend-фильтрами."""

    items: list[PaperListItem]
    total: int
    limit: int
    offset: int


class PaperProcessingStatusInfo(BaseModel):
    """Описание статуса обработки для UI-фильтров."""

    key: str
    label: str
    group: str = "unknown"
    final: bool = False
    stage: str = "unknown"
    stage_label: str = "Неизвестный этап"


class PaperPipelineStageInfo(BaseModel):
    """Нормализованное состояние одного этапа content/Qwen pipeline.

    Это вычисляемая API-модель, не поле БД: она разделяет stage-status
    (skipped/failed/fallback/success) и итоговый статус документа.
    """

    key: str = Field(..., description="Ключ этапа: pdf, ocr, markdown, ru_analysis, keywords, embedding, final")
    label: str = Field(..., description="Человекочитаемое название этапа")
    status: str = Field(default="unknown", description="pending/processing/success/warning/error/skipped/unknown")
    status_label: str = Field(default="Нет данных", description="Короткое описание состояния этапа")
    progress: int = Field(default=0, ge=0, le=100, description="Локальный прогресс этапа")
    final: bool = Field(default=False, description="Этап больше не ожидает работы")
    enabled: bool | None = Field(default=None, description="Этап включён настройками, если это известно")
    skipped: bool = Field(default=False, description="Этап осознанно пропущен, а не упал")
    fallback_used: bool = Field(default=False, description="Этап использовал резервный сценарий")
    error: str | None = Field(default=None, description="Короткая ошибка этапа")
    source: str = Field(default="derived", description="Источник вывода: status/content_parts/paper_fields/settings/derived")
    details: dict = Field(default_factory=dict, description="Компактная диагностика без больших текстов/PDF")


class PaperProcessingPipelineStatus(BaseModel):
    """Сводная модель AI/PDF/Qwen обработки для карточки статьи."""

    aggregate_status: str = Field(default="unknown", description="success/warning/error/processing/pending/unknown")
    aggregate_label: str = Field(default="Нет данных", description="Краткий итог по всей цепочке")
    aggregate_progress: int = Field(default=0, ge=0, le=100, description="Агрегированный прогресс")
    has_errors: bool = False
    has_warnings: bool = False
    pdf_stage: PaperPipelineStageInfo
    ocr_stage: PaperPipelineStageInfo
    markdown_stage: PaperPipelineStageInfo
    ru_analysis_stage: PaperPipelineStageInfo
    keywords_stage: PaperPipelineStageInfo
    embedding_stage: PaperPipelineStageInfo
    final_stage: PaperPipelineStageInfo
    stages: list[PaperPipelineStageInfo] = Field(default_factory=list)


class PaperProcessingQualityInfo(BaseModel):
    """Итоговая оценка качества обработки файла для карточки статьи."""

    mode: str = "unknown"
    score: float | None = None
    label: str = "Нет данных обработки файла"
    basis: str = "Качество появится после завершения обработки PDF и сохранения частей документа."
    status: str = "unknown"
    pages_total: int | None = None
    pages_success: int | None = None
    pages_failed: int | None = None
    fallback_used: bool = False
    requested_mode: str | None = None
    actual_mode: str | None = None


class PaperDetailResponse(BaseModel):
    """Полная карточка статьи для страницы просмотра.

    В отличие от списка статей, этот ответ намеренно содержит весь Paper payload
    вместе со связанными частями документа: страница статьи должна показывать
    полный текст, анализ, перевод, диагностику и сохранённые content-parts.
    """

    paper: Paper
    content_parts: list["PaperContentPart"] = Field(default_factory=list)
    status_info: PaperProcessingStatusInfo
    processing_quality: PaperProcessingQualityInfo | None = None
    pipeline_status: PaperProcessingPipelineStatus | None = None


class PaperContentPartTranslation(BaseModel):
    """Переведённый Markdown для одной части статьи."""

    id: int
    paper_id: int
    part_id: int
    language_code: str
    language_name: str | None = None
    source_language_code: str | None = None
    translated_markdown_text: str | None = None
    status: str = "pending"
    error: str | None = None
    qwen_model: str | None = None
    qwen_prompt_version: str | None = None
    source_chars: int = 0
    translated_chars: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PaperContentPart(BaseModel):
    """Сырой PDF-текст и Qwen Markdown для одной части статьи."""

    id: int
    paper_id: int
    part_index: int
    page_start: int
    page_end: int
    raw_text: str | None = None
    markdown_text: str | None = None
    status: str = "raw_extracted"
    error: str | None = None
    source: str = "pdf"
    content_type: str = "body"
    section_title: str | None = None
    section_index: int | None = None
    page_profile: str | None = None
    include_in_embedding: bool = True
    qwen_model: str | None = None
    qwen_prompt_version: str | None = None
    regeneration_count: int = 0
    raw_text_chars: int = 0
    markdown_text_chars: int = 0
    extraction_method: str | None = None
    extraction_quality_score: float | None = None
    extraction_warnings: list[str] = Field(default_factory=list)
    extraction_metadata: dict = Field(default_factory=dict)
    translations: list[PaperContentPartTranslation] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PaperContentPartRegenerateResponse(BaseModel):
    """Ответ на постановку перегенерации одной markdown-части."""

    paper_id: int
    part_id: int
    task_id: str
    status: str = "queued"
    page_start: int
    page_end: int
    mode: str = "text"


class PaperTranslateRequest(BaseModel):
    """Запрос на перевод Markdown-текста статьи по частям."""

    target_language_code: str = Field(default="ru", min_length=2, max_length=20)
    target_language_name: str | None = Field(default="Русский", max_length=100)
    source_layer: str = Field(default="markdown", description="Сейчас поддерживается только markdown")
    scope: str = Field(default="displayed_pages", description="Переводятся все сохранённые отображаемые части")
    force: bool = Field(default=False, description="Перегенерировать уже готовый перевод")

    @field_validator("target_language_code", mode="before")
    @classmethod
    def _normalize_language_code(cls, value):
        return (_coerce_text_scalar(value, default="ru") or "ru").strip().lower()

    @field_validator("target_language_name", "source_layer", "scope", mode="before")
    @classmethod
    def _normalize_text_fields(cls, value):
        return _coerce_text_scalar(value)


class PaperTranslateResponse(BaseModel):
    """Ответ постановки перевода статьи в очередь."""

    paper_id: int
    task_id: str
    status: str = "queued"
    target_language_code: str
    target_language_name: str | None = None
    parts_total: int
    parts_ready: int = 0


class PaperSearchRequest(BaseModel):
    """Запрос на поиск статей."""

    query: str = Field(..., description="Поисковый запрос")
    limit: int = Field(default=10, ge=1, le=100, description="Макс. количество результатов")
    sources: list[str] = Field(
        default_factory=lambda: ["CORE"],
        description="Источники для поиска"
    )
    full_text_only: bool = Field(default=False, description="Только статьи с полным текстом")


class PaperSearchResponse(BaseModel):
    """Ответ на поиск статей."""

    papers: list[Paper]
    total: int
    query: str
    sources: list[str]




class FullTextSearchStats(BaseModel):
    """Статистика полнотекстового поиска для текущего запроса и фильтров."""

    total_matches: int = 0
    avg_relevance: float = 0
    max_relevance: float = 0


class FullTextSearchItem(BaseModel):
    """Лёгкий элемент выдачи полнотекстового поиска.

    `full_text` намеренно остаётся пустым, чтобы список результатов не тащил
    большие PDF-тексты. Полный текст загружается только в карточке статьи.
    """

    id: int
    title: str
    authors: list[str] = Field(default_factory=list)
    publication_date: datetime | None = None
    journal: str | None = None
    doi: str | None = None
    abstract: str | None = None
    full_text: str | None = None
    keywords: list[str] = Field(default_factory=list)
    language_code: str | None = None
    language_name: str | None = None
    language_confidence: float | None = None
    language_source: str | None = None
    available_language_codes: list[str] = Field(default_factory=list)
    translation_status: str | None = None
    translation_task_id: str | None = None
    translation_error: str | None = None
    source: str
    source_id: str | None = None
    canonical_patent_id: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    pdf_local_path: str | None = None
    processing_status: str = "pending"
    content_task_id: str | None = None
    processing_error: str | None = None
    summary_ru: str | None = None
    analysis_ru: str | None = None
    translation_ru: str | None = None
    parse_confidence: float | None = None
    provenance: dict = Field(default_factory=dict)
    quality_flags: list[str] = Field(default_factory=list)
    schema_version: str | None = "2.0"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    rank: float = 0
    snippet: str | None = None
    title_highlight: str | None = None
    abstract_highlight: str | None = None
    full_text_highlight: str | None = None
    has_pdf: bool = False
    has_full_text: bool = False
    full_text_indexed: bool = False
    matched_fields: list[str] = Field(default_factory=list)


class FullTextSearchResponse(BaseModel):
    """Ответ PostgreSQL FTS без тяжёлого полного текста в выдаче."""

    papers: list[FullTextSearchItem]
    total: int
    query: str
    sources: list[str]
    search_mode: str = "websearch"
    limit: int = 20
    offset: int = 0
    stats: FullTextSearchStats = Field(default_factory=FullTextSearchStats)


class VectorSearchRequest(BaseModel):
    """Запрос на векторный поиск."""

    query: str = Field(..., description="Поисковый запрос")
    limit: int = Field(default=10, ge=1, le=100, description="Макс. количество результатов")
    source: str | None = Field(None, description="Фильтр по источнику (CORE, arXiv)")
    date_from: str | None = Field(None, description="Дата от (YYYY-MM-DD)")
    date_to: str | None = Field(None, description="Дата до (YYYY-MM-DD)")
    search_type: str = Field(default="vector", description="Тип поиска: vector, semantic, hybrid")


class VectorSearchResultItem(BaseModel):
    """Результат векторного поиска."""

    paper: Paper
    similarity: float = Field(..., description="Сходство (0-1)")


class VectorSearchResponse(BaseModel):
    """Ответ на векторный поиск."""

    results: list[VectorSearchResultItem]
    total: int
    query: str
    search_type: str


class VectorStats(BaseModel):
    """Статистика векторного хранилища."""

    count: int = Field(..., description="Количество документов")
    available: bool = Field(..., description="Доступность сервиса")
    collection: str = Field(..., description="Название коллекции")
    persist_directory: str = Field(..., description="Путь к хранилищу")


class VectorStatsResponse(BaseModel):
    """Ответ со статистикой векторного поиска.

    `vector_store` — основная структурированная форма.
    Верхнеуровневые поля оставлены для обратной совместимости со старыми клиентами/тестами.
    """

    vector_store: VectorStats
    embedding_model: str | None = Field(None, description="Модель эмбеддингов")
    embedding_dim: int | None = Field(None, description="Размерность эмбеддингов")
    embedding_available: bool = Field(..., description="Доступность эмбеддингов")
    count: int = Field(default=0, description="Количество документов, backward-compatible alias")
    available: bool = Field(default=False, description="Доступность vector store, backward-compatible alias")
    collection: str | None = Field(None, description="Название коллекции, backward-compatible alias")


class VectorRebuildRequest(BaseModel):
    """Запрос на перестройку векторного индекса."""

    limit: int = Field(default=10000, ge=1, le=100000, description="Макс. количество статей")
    batch_size: int = Field(default=32, ge=1, le=128, description="Размер пакета")


class VectorRebuildResponse(BaseModel):
    """Ответ на перестройку векторного индекса."""

    message: str = Field(..., description="Сообщение о результате")
    indexed: int = Field(..., description="Количество проиндексированных статей")
    total: int = Field(..., description="Всего статей в БД")


class VectorClearRequest(BaseModel):
    """Запрос на очистку векторного индекса."""

    confirm: bool = Field(..., description="Подтверждение очистки (должно быть True)")


class VectorClearResponse(BaseModel):
    """Ответ на очистку векторного индекса."""

    message: str = Field(..., description="Сообщение о результате")
    success: bool = Field(..., description="Успешность операции")







class QwenMessageRequest(BaseModel):
    """Запрос на отправку сообщения Qwen."""

    message: str = Field(..., min_length=1, max_length=50000, description="Текст сообщения")
    session_id: str | None = Field(None, description="ID сессии (создастся новая если не указан)")
    thinking_enabled: bool = Field(default=True, description="Режим мышления")
    search_enabled: bool = Field(default=False, description="Поиск в интернете")
    file_ids: list[str] = Field(default_factory=list, description="ID файлов для ссылки")
    auto_continue: bool = Field(default=True, description="Авто-продолжение ответов")

    @field_validator("message", mode="before")
    @classmethod
    def _strip_message(cls, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("message must not be empty")
        return text

    @field_validator("session_id", mode="before")
    @classmethod
    def _strip_optional_session_id(cls, value: object) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("file_ids", mode="before")
    @classmethod
    def _normalize_file_ids(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("file_ids must be a list")
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            fid = str(item or "").strip()
            if not fid or fid in seen:
                continue
            seen.add(fid)
            normalized.append(fid)
        return normalized


class QwenMessageResponse(BaseModel):
    """Ответ на сообщение Qwen."""

    status: str = Field(default="ok", description="Статус ответа: ok/error")
    session_id: str = Field(..., description="ID сессии")
    message: str = Field(..., description="Исходное сообщение")
    response: str = Field(..., description="Текст ответа")
    thinking: str = Field(default="", description="Текст размышлений")
    thinking_enabled: bool = Field(..., description="Режим мышления включен")
    search_enabled: bool = Field(..., description="Поиск включен")
    message_id: int = Field(default=0, description="ID сообщения")
    continue_count: int = Field(default=0, description="Количество продолжений")
    can_continue: bool = Field(default=False, description="Можно ли продолжить")
    auto_continue_performed: bool = Field(default=False, description="Авто-продолжение выполнено")
    task_id: str | None = Field(None, description="Celery task_id, если запрос шёл через очередь")
    queued: bool | None = Field(None, description="Признак обработки через Qwen queue")
    error_code: str | None = Field(None, description="Стабильный код ошибки Qwen")
    status_code: int | None = Field(None, description="HTTP/provider status code, если доступен")
    error: str | None = Field(None, description="Текст ошибки")


class QwenSessionCreateRequest(BaseModel):
    """Запрос на создание сессии."""

    title: str | None = Field(default="Новый чат", description="Заголовок сессии")

    @field_validator("title", mode="before")
    @classmethod
    def _strip_title(cls, value: object) -> str:
        return str(value or "Новый чат").strip() or "Новый чат"


class QwenSessionCreateResponse(BaseModel):
    """Ответ на создание сессии."""

    session_id: str = Field(..., description="ID сессии")
    title: str = Field(..., description="Заголовок сессии")


class QwenSessionInfo(BaseModel):
    """Информация о сессии."""

    session_id: str = Field(..., description="ID сессии")
    title: str = Field(..., description="Заголовок")
    created_at: str | None = Field(None, description="Дата создания")


class QwenSessionListResponse(BaseModel):
    """Список сессий."""

    sessions: list[QwenSessionInfo] = Field(default_factory=list, description="Список сессий")


class QwenRenameRequest(BaseModel):
    """Запрос на переименование сессии."""

    title: str = Field(..., min_length=1, max_length=100, description="Новый заголовок")

    @field_validator("title", mode="before")
    @classmethod
    def _strip_title(cls, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("title must not be empty")
        return text


class QwenRenameResponse(BaseModel):
    """Ответ на переименование сессии."""

    status: str = Field(..., description="Статус операции")
    title: str = Field(..., description="Новый заголовок")


class QwenDeleteResponse(BaseModel):
    """Ответ на удаление сессии."""

    status: str = Field(..., description="Статус операции")
    deleted: bool = Field(..., description="Удалено ли")


class QwenConfigResponse(BaseModel):
    """Конфигурация Qwen сервиса."""

    model: str = Field(..., description="Модель")
    thinking_enabled: bool = Field(..., description="Режим мышления")
    search_enabled: bool = Field(..., description="Поиск")
    auto_continue_enabled: bool = Field(..., description="Авто-продолжение")
    max_continues: int = Field(..., description="Макс. продолжений")
    stream_retries: int | None = Field(None, description="Retry для нестабильного Qwen SSE stream")
    history_recovery_attempts: int | None = Field(None, description="Попытки восстановления ответа из истории")
    history_recovery_interval_sec: float | None = Field(None, description="Интервал восстановления истории, сек")
    has_token: bool | None = Field(None, description="Настроен ли QWEN_TOKEN")
    has_api_key: bool | None = Field(None, description="Настроен ли QWEN_API_KEY")
    auth_required: bool | None = Field(None, description="Требуется ли Bearer API key для qwen_service")
    allow_unauth_without_api_key: bool | None = Field(None, description="Включён ли явный unauth-режим без QWEN_API_KEY")
    file_metadata_cache_enabled: bool | None = Field(None, description="Включён ли runtime-cache metadata загруженных Qwen файлов")
    file_metadata_cache_path: str | None = Field(None, description="Путь к runtime-cache metadata загруженных Qwen файлов")
    file_metadata_cache_entries: int | None = Field(None, description="Количество файловых metadata-записей в qwen_service cache")
    file_metadata_cache_max_age_days: int | None = Field(None, description="Возраст stale metadata uploaded files для maintenance, дней")
    session_registry_cache_enabled: bool | None = Field(None, description="Включён ли runtime-cache локального реестра Qwen-сессий")
    session_registry_cache_path: str | None = Field(None, description="Путь к runtime-cache локального реестра Qwen-сессий")
    session_registry_cache_entries: int | None = Field(None, description="Количество локальных Qwen-сессий в cache")
    session_registry_cache_max_age_days: int | None = Field(None, description="Возраст stale локальных Qwen-сессий для maintenance, дней")
    event_journal_enabled: bool | None = Field(None, description="Включён ли локальный журнал событий qwen_service")
    event_journal_path: str | None = Field(None, description="Путь к локальному журналу событий qwen_service")
    event_journal_entries: int | None = Field(None, description="Количество записей в журнале событий qwen_service")
    event_journal_max_entries: int | None = Field(None, description="Максимум записей в журнале событий qwen_service")
    is_available: bool = Field(..., description="Сервис доступен")
    base_url: str | None = Field(None, description="URL сервиса")


class QwenConfigUpdateRequest(BaseModel):
    """Запрос на обновление конфигурации."""

    model: str | None = Field(None, description="Модель")
    thinking_enabled: bool | None = Field(None, description="Режим мышления")
    search_enabled: bool | None = Field(None, description="Поиск")
    auto_continue_enabled: bool | None = Field(None, description="Авто-продолжение")
    max_continues: int | None = Field(None, ge=1, le=20, description="Макс. продолжений")
    stream_retries: int | None = Field(None, ge=0, le=10, description="Retry для нестабильного Qwen SSE stream")
    history_recovery_attempts: int | None = Field(None, ge=1, le=60, description="Попытки восстановления ответа из истории")
    history_recovery_interval_sec: float | None = Field(None, ge=0.2, le=30.0, description="Интервал восстановления истории, сек")
    file_metadata_cache_max_age_days: int | None = Field(None, ge=1, le=3650, description="Возраст stale metadata uploaded files для maintenance, дней")
    session_registry_cache_max_age_days: int | None = Field(None, ge=1, le=3650, description="Возраст stale локальных Qwen-сессий для maintenance, дней")


class QwenHealthResponse(BaseModel):
    """Проверка здоровья Qwen сервиса."""

    status: str = Field(..., description="Статус")
    model: str = Field(..., description="Модель")
    available: bool = Field(..., description="Доступен")
    base_url: str | None = Field(None, description="URL standalone Qwen Service")
    reason: str | None = Field(None, description="Причина недоступности")
    error_type: str | None = Field(None, description="Тип ошибки проверки здоровья")
    has_token: bool | None = Field(None, description="Загружен ли QWEN_TOKEN в qwen_service")
    token_configured: bool | None = Field(None, description="Настроен ли QWEN_TOKEN в qwen_service")
    has_api_key: bool | None = Field(None, description="Настроен ли QWEN_API_KEY в qwen_service")
    auth_required: bool | None = Field(None, description="Требуется ли Bearer API key")
    auth_valid_known: bool | None = Field(None, description="Последняя известная валидность Qwen auth")
    auth_checked_at: float | None = Field(None, description="monotonic-время последней auth-проверки")
    service_alive: bool | None = Field(None, description="Жив ли HTTP-сервис qwen_service")
