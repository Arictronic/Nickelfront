"""Модель научной статьи."""

from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import TSVECTOR
from app.db.base import Base


class Paper(Base):
    """Модель научной статьи в БД."""

    __tablename__ = "papers"

    id = Column(Integer, primary_key=True, index=True)

    # Основные данные
    title = Column(Text, nullable=False, index=True)
    authors = Column(JSON, default=list)  # Список авторов
    publication_date = Column(DateTime, nullable=True, index=True)
    journal = Column(String(500), nullable=True)
    doi = Column(String(200), nullable=True, unique=True, index=True)
    abstract = Column(Text, nullable=True)
    full_text = Column(Text, nullable=True)
    keywords = Column(JSON, default=list)

    # Векторный эмбеддинг (хранится как JSON массив float)
    # Размерность зависит от модели: all-MiniLM-L6-v2 = 384, all-mpnet-base-v2 = 768
    embedding = Column(JSON, nullable=True)

    # Полнотекстовый поиск (tsvector для Postgres, Text для SQLite в тестах)
    search_vector = Column(TSVECTOR().with_variant(Text, "sqlite"), nullable=True)

    # Информация об источнике
    source = Column(String(50), nullable=False, index=True)  # CORE, arXiv, etc.
    source_id = Column(String(200), nullable=True, index=True)  # ID в источнике
    url = Column(String(1000), nullable=True)
    pdf_url = Column(String(1000), nullable=True)
    pdf_local_path = Column(String(1000), nullable=True)

    # Метаданные
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Статус обработки
    processing_status = Column(String(50), nullable=False, default="pending", index=True)
    content_task_id = Column(String(100), nullable=True, index=True)
    processing_error = Column(Text, nullable=True)

    # Результаты AI-обработки
    summary_ru = Column(Text, nullable=True)
    analysis_ru = Column(Text, nullable=True)
    translation_ru = Column(Text, nullable=True)

    # Индексы
    __table_args__ = (
        # GIN индекс для полнотекстового поиска
        Index('ix_papers_search_vector', 'search_vector', postgresql_using='gin'),
    )

    def __repr__(self):
        return f"<Paper(id={self.id}, title='{self.title[:50]}...', source={self.source})>"
