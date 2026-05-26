"""Compatibility import for the PDF/content parser facade.

Keep this module so direct imports of ``app.services.pdf_parser.parser`` and
``backend.app.services.pdf_parser.parser`` remain stable while callers migrate to
``app.services.pdf_content_parser``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

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
):
    return pdf_parser.parse_to_documents(file_path, metadata=metadata, options=options)


def parse_bytes_to_documents(
    file_bytes: bytes,
    filename: str = "unknown.pdf",
    metadata: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
):
    return pdf_parser.parse_bytes_to_documents(
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


for _alias in ("app.services.pdf_parser.parser", "backend.app.services.pdf_parser.parser"):
    sys.modules.setdefault(_alias, sys.modules[__name__])


__all__ = [
    "PDFParser",
    "pdf_parser",
    "parse_bytes",
    "extract_content",
    "parse_to_documents",
    "parse_bytes_to_documents",
    "extract_content_from_file",
    "extract_content_from_bytes",
]
