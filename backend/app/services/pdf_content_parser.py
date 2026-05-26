"""Public service entrypoint for the shared PDF/content parser.

Use this module from the backend, Celery tasks, audit scripts and parser adapters:
``app.services.pdf_content_parser``.  ``backend.app.services.pdf_content_parser``
is also supported for RAG/parser_alpha processes started from the repository root.

The heavy implementation lives in ``app.services.pdf_parser``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .pdf_parser import (
    DEFAULT_PARSER_OPTIONS,
    Document,
    PDFParser,
    PdfExtractionError,
    PdfPageExtraction,
    RecursiveCharacterTextSplitter,
    merge_parser_options,
    parser_env_options,
    pdf_parser,
)


def parse_bytes(
    file_bytes: bytes,
    filename: str = "unknown.pdf",
    metadata: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse PDF bytes through the shared parser instance."""

    return pdf_parser.parse_bytes(
        file_bytes,
        filename=filename,
        metadata=metadata,
        options=options,
    )


def extract_content(
    file_path: str | Path | None = None,
    *,
    file_bytes: bytes | None = None,
    filename: str | None = None,
    metadata: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract structured PDF content through the shared parser instance."""

    return pdf_parser.extract_content(
        file_path=file_path,
        file_bytes=file_bytes,
        filename=filename,
        metadata=metadata,
        options=options,
    )


def parse_to_documents(
    file_path: str,
    metadata: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> list[Document]:
    """Parse a PDF file into LangChain-compatible documents."""

    return pdf_parser.parse_to_documents(file_path, metadata=metadata, options=options)


def parse_bytes_to_documents(
    file_bytes: bytes,
    filename: str = "unknown.pdf",
    metadata: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> list[Document]:
    """Backward-compatible bytes-to-documents public entrypoint."""

    return pdf_parser.parse_bytes_to_documents(
        file_bytes,
        filename=filename,
        metadata=metadata,
        options=options,
    )


def parse_to_structured_documents(
    file_path: str,
    metadata: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> list[Document]:
    """Structured-block document projection public entrypoint."""

    return pdf_parser.parse_to_structured_documents(file_path, metadata=metadata, options=options)


def parse_bytes_to_structured_documents(
    file_bytes: bytes,
    filename: str = "unknown.pdf",
    metadata: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> list[Document]:
    """Structured-block bytes-to-documents public entrypoint."""

    return pdf_parser.parse_bytes_to_structured_documents(
        file_bytes,
        filename=filename,
        metadata=metadata,
        options=options,
    )


def extract_content_from_file(
    file_path: str | Path,
    metadata: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper for file-path structured extraction."""

    return pdf_parser.extract_content_from_file(file_path, metadata=metadata, options=options)


def extract_content_from_bytes(
    file_bytes: bytes,
    filename: str = "unknown.pdf",
    metadata: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper for bytes structured extraction."""

    return pdf_parser.extract_content_from_bytes(
        file_bytes,
        filename=filename,
        metadata=metadata,
        options=options,
    )


for _alias in ("app.services.pdf_content_parser", "backend.app.services.pdf_content_parser"):
    sys.modules.setdefault(_alias, sys.modules[__name__])


__all__ = [
    "DEFAULT_PARSER_OPTIONS",
    "Document",
    "RecursiveCharacterTextSplitter",
    "PDFParser",
    "pdf_parser",
    "PdfExtractionError",
    "PdfPageExtraction",
    "merge_parser_options",
    "parser_env_options",
    "parse_bytes",
    "extract_content",
    "parse_to_documents",
    "parse_bytes_to_documents",
    "parse_to_structured_documents",
    "parse_bytes_to_structured_documents",
    "extract_content_from_file",
    "extract_content_from_bytes",
]
