"""Optional third-party compatibility helpers for the PDF parser.

The audit scripts can import the parser without LangChain installed, so keep
the lightweight fallbacks isolated here instead of inside the parser facade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from langchain_core.documents import Document
except Exception:
    @dataclass
    class Document:
        page_content: str
        metadata: dict[str, Any] = field(default_factory=dict)

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except Exception:
    class RecursiveCharacterTextSplitter:
        def __init__(
            self,
            chunk_size: int = 1000,
            chunk_overlap: int = 200,
            length_function=len,
            separators: list[str] | None = None,
        ):
            self.chunk_size = max(1, int(chunk_size or 1000))
            self.chunk_overlap = max(0, int(chunk_overlap or 0))
            self.length_function = length_function
            self.separators = separators or ["\n\n", "\n", ". ", " ", ""]

        def split_text(self, text: str) -> list[str]:
            value = text or ""
            if not value:
                return []
            step = max(1, self.chunk_size - self.chunk_overlap)
            return [
                value[i : i + self.chunk_size]
                for i in range(0, len(value), step)
                if value[i : i + self.chunk_size].strip()
            ]

__all__ = ["Document", "RecursiveCharacterTextSplitter"]
