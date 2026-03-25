"""Схемы данных для научных статей."""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class PaperBase(BaseModel):
    """Базовая схема статьи."""

    title: str = Field(..., description="Название статьи")
    authors: list[str] = Field(default_factory=list, description="Список авторов")
    publication_date: Optional[datetime] = Field(None, description="Дата публикации")
    journal: Optional[str] = Field(None, description="Название журнала/источника")
    doi: Optional[str] = Field(None, description="DOI статьи")
    abstract: Optional[str] = Field(None, description="Аннотация")
    full_text: Optional[str] = Field(None, description="Полный текст статьи")
    keywords: list[str] = Field(default_factory=list, description="Ключевые слова")
    source: str = Field(..., description="Источник (CORE, arXiv, etc.)")
    source_id: Optional[str] = Field(None, description="ID в источнике")
    url: Optional[str] = Field(None, description="URL статьи")


class PaperCreate(PaperBase):
    """Схема для создания статьи."""

    pass


class Paper(PaperBase):
    """Схема статьи."""

    id: Optional[int] = Field(None, description="ID в БД")
    created_at: Optional[datetime] = Field(None, description="Дата добавления в БД")
    updated_at: Optional[datetime] = Field(None, description="Дата обновления")

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
