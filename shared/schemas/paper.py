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
    source: str = Field(..., description="Источник (CORE, arXiv, etc.)")
    source_id: str | None = Field(None, description="ID в источнике")
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
        "doi",
        "abstract",
        "full_text",
        "source",
        "source_id",
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

    @field_validator("authors", "keywords", "quality_flags", mode="before")
    @classmethod
    def _normalize_list_fields(cls, value, info: ValidationInfo):



        return _coerce_json_list(value, split_commas=info.field_name != "authors")

    @field_validator("provenance", mode="before")
    @classmethod
    def _normalize_provenance(cls, value):
        return _coerce_json_dict(value)

    @field_validator("parse_confidence", mode="before")
    @classmethod
    def _normalize_parse_confidence(cls, value):
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


class QwenMessageResponse(BaseModel):
    """Ответ на сообщение Qwen."""

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
    error: str | None = Field(None, description="Текст ошибки")


class QwenSessionCreateRequest(BaseModel):
    """Запрос на создание сессии."""

    title: str | None = Field(default="Новый чат", description="Заголовок сессии")


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


class QwenHealthResponse(BaseModel):
    """Проверка здоровья Qwen сервиса."""

    status: str = Field(..., description="Статус")
    model: str = Field(..., description="Модель")
    available: bool = Field(..., description="Доступен")
    base_url: str | None = Field(None, description="URL standalone Qwen Service")
    reason: str | None = Field(None, description="Причина недоступности")
    error_type: str | None = Field(None, description="Тип ошибки проверки здоровья")
    has_token: bool | None = Field(None, description="Загружен ли QWEN_TOKEN в qwen_service")
