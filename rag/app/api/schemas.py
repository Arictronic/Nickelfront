"""
Модуль схем данных API.

Содержит Pydantic модели для валидации запросов и ответов API.
"""

from typing import Any

from pydantic import BaseModel, Field

# === Модели для эндпоинта /ask ===


class AskRequest(BaseModel):
    """
    Модель запроса для эндпоинта /ask.

    Attributes:
        question: Текст вопроса пользователя.
        include_sources: Включать ли информацию об источниках в ответ.
        include_scores: Включать ли оценки релевантности документов.
    """

    question: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Текст вопроса пользователя",
        examples=["Какой состав у сплава ХН77ТЮР?"],
    )
    include_sources: bool = Field(
        default=True,
        description="Включать ли информацию об источниках",
    )
    include_scores: bool = Field(
        default=False,
        description="Включать ли оценки релевантности документов",
    )


class SourceDocument(BaseModel):
    """
    Модель документа-источника.

    Attributes:
        index: Порядковый номер документа.
        content: Содержание документа (фрагмент).
        metadata: Метаданные документа.
        relevance_score: Оценка релевантности (если включена).
    """

    index: int = Field(..., description="Порядковый номер документа")
    content: str = Field(..., description="Содержание документа")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Метаданные документа",
    )
    relevance_score: float | None = Field(
        default=None,
        description="Оценка релевантности",
    )


class AskResponse(BaseModel):
    """
    Модель ответа для эндпоинта /ask.

    Attributes:
        answer: Сгенерированный ответ на вопрос.
        question: Исходный вопрос пользователя.
        sources: Список документов-источников.
        documents_found: Количество найденных документов.
    """

    answer: str = Field(..., description="Сгенерированный ответ")
    question: str = Field(..., description="Исходный вопрос")
    sources: list[SourceDocument] = Field(
        default_factory=list,
        description="Документы-источники",
    )
    documents_found: int = Field(
        default=0,
        description="Количество найденных документов",
    )


# === Модели для эндпоинта /upload ===


class UploadResponse(BaseModel):
    """
    Модель ответа для эндпоинта /upload.

    Attributes:
        message: Сообщение о результате загрузки.
        filename: Имя загруженного файла.
        documents_count: Количество созданных документов.
        file_size: Размер файла в байтах.
    """

    message: str = Field(..., description="Сообщение о результате")
    filename: str = Field(..., description="Имя файла")
    documents_count: int = Field(..., description="Количество документов")
    file_size: int = Field(..., description="Размер файла в байтах")


# === Модели для эндпоинта /health ===


class HealthResponse(BaseModel):
    """
    Модель ответа для эндпоинта /health.

    Attributes:
        status: Статус приложения ("ok" или "error").
        version: Версия приложения.
        llm_available: Доступность LLM API.
        vector_store_documents: Количество документов в векторной базе.
    """

    status: str = Field(..., description="Статус приложения")
    version: str = Field(..., description="Версия приложения")
    llm_available: bool = Field(..., description="Доступность LLM API")
    vector_store_documents: int = Field(
        ...,
        description="Количество документов в векторной базе",
    )


# === Модели для эндпоинта /stats ===


class VectorStoreStats(BaseModel):
    """
    Модель статистики векторного хранилища.

    Attributes:
        total_documents: Общее количество документов.
        collection_name: Название коллекции.
        persist_directory: Путь к хранилищу.
    """

    total_documents: int = Field(..., description="Количество документов")
    collection_name: str = Field(..., description="Название коллекции")
    persist_directory: str = Field(..., description="Путь к хранилищу")


class StatsResponse(BaseModel):
    """
    Модель ответа для эндпоинта /stats.

    Attributes:
        vector_store: Статистика векторного хранилища.
        llm_model: Название модели LLM.
        embedding_model: Название модели эмбеддингов.
    """

    vector_store: VectorStoreStats = Field(
        ...,
        description="Статистика векторного хранилища",
    )
    llm_model: str = Field(..., description="Модель LLM")
    embedding_model: str = Field(..., description="Модель эмбеддингов")


# === Модели ошибок ===


class ErrorResponse(BaseModel):
    """
    Модель ответа с ошибкой.

    Attributes:
        error: Тип ошибки.
        message: Сообщение об ошибке.
        details: Дополнительные детали (опционально).
    """

    error: str = Field(..., description="Тип ошибки")
    message: str = Field(..., description="Сообщение об ошибке")
    details: dict[str, Any] | None = Field(
        default=None,
        description="Дополнительные детали",
    )


class ClearStoreResponse(BaseModel):
    """
    Модель ответа для эндпоинта /clear.

    Attributes:
        message: Сообщение о результате.
        success: Успешность операции.
    """

    message: str = Field(..., description="Сообщение о результате")
    success: bool = Field(..., description="Успешность операции")
