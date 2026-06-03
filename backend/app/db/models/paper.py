"""Модель научной статьи."""

from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey, Index, Float, text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import TSVECTOR
from app.db.base import Base


class Paper(Base):
    """Модель научной статьи в БД."""

    __tablename__ = "papers"

    id = Column(Integer, primary_key=True, index=True)


    title = Column(Text, nullable=False, index=True)
    authors = Column(JSON, default=list)
    publication_date = Column(DateTime, nullable=True, index=True)
    journal = Column(String(500), nullable=True)
    doi = Column(String(200), nullable=True, unique=True, index=True)
    abstract = Column(Text, nullable=True)
    full_text = Column(Text, nullable=True)
    keywords = Column(JSON, default=list)

    language_code = Column(String(20), nullable=True, index=True)
    language_name = Column(String(100), nullable=True)
    language_confidence = Column(Float, nullable=True)
    language_source = Column(String(50), nullable=True)

    available_language_codes = Column(JSON, nullable=False, default=list)
    translation_status = Column(String(50), nullable=True, index=True)
    translation_task_id = Column(String(100), nullable=True, index=True)
    translation_error = Column(Text, nullable=True)


    embedding = Column(JSON, nullable=True)


    search_vector = Column(TSVECTOR().with_variant(Text, "sqlite"), nullable=True)


    source = Column(String(50), nullable=False, index=True)
    source_id = Column(String(200), nullable=True, index=True)
    canonical_patent_id = Column(String(200), nullable=True)
    url = Column(String(1000), nullable=True)
    pdf_url = Column(String(1000), nullable=True)
    pdf_local_path = Column(String(1000), nullable=True)


    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


    processing_status = Column(String(50), nullable=False, default="pending", index=True)
    content_task_id = Column(String(100), nullable=True, index=True)
    processing_error = Column(Text, nullable=True)


    summary_ru = Column(Text, nullable=True)
    analysis_ru = Column(Text, nullable=True)
    translation_ru = Column(Text, nullable=True)


    parse_confidence = Column(Float, nullable=True)
    provenance = Column(JSON, nullable=False, default=dict)
    quality_flags = Column(JSON, nullable=False, default=list)
    schema_version = Column(String(20), nullable=True, default="2.0")

    content_parts = relationship(
        "PaperContentPart",
        back_populates="paper",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PaperContentPart.part_index",
    )


    __table_args__ = (

        Index('ix_papers_search_vector', 'search_vector', postgresql_using='gin'),
        Index(
            "uq_papers_canonical_patent_id_not_null",
            "canonical_patent_id",
            unique=True,
            postgresql_where=text("canonical_patent_id IS NOT NULL"),
            sqlite_where=text("canonical_patent_id IS NOT NULL"),
        ),
        Index(
            "uq_papers_source_source_id_not_null",
            "source",
            "source_id",
            unique=True,
            postgresql_where=text("source_id IS NOT NULL"),
            sqlite_where=text("source_id IS NOT NULL"),
        ),
    )

    def __repr__(self):
        return f"<Paper(id={self.id}, title='{self.title[:50]}...', source={self.source})>"
