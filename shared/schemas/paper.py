"""Схемы данных для научных статей."""

from datetime import datetime

from pydantic import BaseModel, Field


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


class PaperCreate(PaperBase):
    """Схема для создания статьи."""

    pass


class Paper(PaperBase):
    """Схема статьи."""

    id: int | None = Field(None, description="ID в БД")
    created_at: datetime | None = Field(None, description="Дата добавления в БД")
    updated_at: datetime | None = Field(None, description="Дата обновления")

    class Config:
        from_attributes = True


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
    """Ответ со статистикой векторного поиска."""

    vector_store: VectorStats
    embedding_model: str | None = Field(None, description="Модель эмбеддингов")
    embedding_dim: int | None = Field(None, description="Размерность эмбеддингов")
    embedding_available: bool = Field(..., description="Доступность эмбеддингов")


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


# =============================================================================
# Qwen Chat Schemas
# =============================================================================


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
    is_available: bool = Field(..., description="Сервис доступен")
    base_url: str | None = Field(None, description="URL сервиса")


class QwenConfigUpdateRequest(BaseModel):
    """Запрос на обновление конфигурации."""

    model: str | None = Field(None, description="Модель")
    thinking_enabled: bool | None = Field(None, description="Режим мышления")
    search_enabled: bool | None = Field(None, description="Поиск")
    auto_continue_enabled: bool | None = Field(None, description="Авто-продолжение")
    max_continues: int | None = Field(None, ge=1, le=20, description="Макс. продолжений")


class QwenHealthResponse(BaseModel):
    """Проверка здоровья Qwen сервиса."""

    status: str = Field(..., description="Статус")
    model: str = Field(..., description="Модель")
    available: bool = Field(..., description="Доступен")
