"""PDF/content parser package.

``PDFParser`` is the public facade. The implementation is split into focused
mixins so PDF extraction, text cleanup, layout recovery, content-block typing,
quality scoring and table/OCR helpers do not live in one giant service file.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .compat import Document, RecursiveCharacterTextSplitter
from .config import DEFAULT_PARSER_OPTIONS, merge_parser_options, parser_env_options
from .models import PdfExtractionError, PdfPageExtraction
from .profiles import ParserDomainProfile, get_domain_profile, is_domain_bonus_profile, normalize_domain_profile_name
from .pdf_content_parser import PDFParser, pdf_parser


def parse_bytes(
    file_bytes: bytes,
    filename: str = "unknown.pdf",
    metadata: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return pdf_parser.parse_bytes(file_bytes, filename=filename, metadata=metadata, options=options)


def extract_content(
    file_path: str | Path | None = None,
    *,
    file_bytes: bytes | None = None,
    filename: str | None = None,
    metadata: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    return pdf_parser.parse_to_documents(file_path, metadata=metadata, options=options)


def parse_bytes_to_documents(
    file_bytes: bytes,
    filename: str = "unknown.pdf",
    metadata: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> list[Document]:
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
    return pdf_parser.parse_to_structured_documents(file_path, metadata=metadata, options=options)


def parse_bytes_to_structured_documents(
    file_bytes: bytes,
    filename: str = "unknown.pdf",
    metadata: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> list[Document]:
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
    return pdf_parser.extract_content_from_file(file_path, metadata=metadata, options=options)


def extract_content_from_bytes(
    file_bytes: bytes,
    filename: str = "unknown.pdf",
    metadata: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return pdf_parser.extract_content_from_bytes(
        file_bytes,
        filename=filename,
        metadata=metadata,
        options=options,
    )


for _alias in ("app.services.pdf_parser", "backend.app.services.pdf_parser"):
    sys.modules.setdefault(_alias, sys.modules[__name__])


__all__ = [
    "DEFAULT_PARSER_OPTIONS",
    "Document",
    "RecursiveCharacterTextSplitter",
    "PDFParser",
    "pdf_parser",
    "PdfExtractionError",
    "PdfPageExtraction",
    "ParserDomainProfile",
    "get_domain_profile",
    "is_domain_bonus_profile",
    "normalize_domain_profile_name",
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
