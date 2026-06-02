from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    prompt_version = Column(String(50), nullable=False, default="1.0")
    context_preview = Column(Text, nullable=True)
    raw_response = Column(Text, nullable=True)
    structured_result = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    paper = relationship("Paper", backref="analysis_results")
    user = relationship("User", backref="analysis_results")

    __table_args__ = (
        Index("ix_analysis_results_paper_user", "paper_id", "user_id"),
    )

    def __repr__(self):
        return f"<AnalysisResult(id={self.id}, paper_id={self.paper_id}, status={self.status})>"
