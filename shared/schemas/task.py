# shared/schemas/task.py

from pydantic import BaseModel
from datetime import datetime

class TaskCreate(BaseModel):
    patent_number: str
    options: dict = {}

class TaskOut(BaseModel):
    id: int
    patent_number: str
    status: str
    result: dict | None
    created_at: datetime