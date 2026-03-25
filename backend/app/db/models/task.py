# app/db/models/task.py
#временная модель, пока не используется, не разбирался глубоко

from sqlalchemy import Column, Integer, String, JSON, DateTime
from sqlalchemy.sql import func
from app.db.base import Base

class PatentTask(Base):
    __tablename__ = "patent_tasks"

    id = Column(Integer, primary_key=True, index=True)
    patent_number = Column(String, index=True)
    status = Column(String, default="pending")  # pending, processing, completed, failed
    input_data = Column(JSON)
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())