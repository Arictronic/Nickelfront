"""Модель научной статьи."""

from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
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
    
    # Информация об источнике
    source = Column(String(50), nullable=False, index=True)  # CORE, arXiv, etc.
    source_id = Column(String(200), nullable=True, index=True)  # ID в источнике
    url = Column(String(1000), nullable=True)
    
    # Метаданные
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Индексы для полнотекстового поиска
    # Для PostgreSQL можно добавить GIN индекс на title и abstract

    def __repr__(self):
        return f"<Paper(id={self.id}, title='{self.title[:50]}...', source={self.source})>"
