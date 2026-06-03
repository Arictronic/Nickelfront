"""Upload request validation helpers for qwen_service.service.

This module is intentionally transport-agnostic: it does not import QwenAPI or
FastAPI route state. The service layer passes current runtime limits in.
"""

from pathlib import Path
from typing import Iterable

from fastapi import HTTPException

try:
    from .error_payload import raise_provider_http_error
except ImportError:
    from error_payload import raise_provider_http_error


def file_max_size_bytes(config: dict, default_max_mb: int) -> int:
    """Return configured per-file upload limit in bytes."""
    max_mb = int(config.get("file_upload_max_size_mb") or default_max_mb)
    return max_mb * 1024 * 1024


def max_files_per_message(config: dict, default_max_files: int) -> int:
    """Return configured maximum number of files accepted in one message."""
    return int(config.get("file_upload_max_files") or default_max_files)


def normalize_request_file_paths(
    *,
    file_path: str = "",
    file_paths: Iterable[str] | None = None,
    max_files: int,
) -> list[str]:
    """Merge single and multi-file request fields, preserving order and removing duplicates."""
    paths: list[str] = []
    if file_paths:
        paths.extend(str(item or "").strip() for item in file_paths)
    single = str(file_path or "").strip()
    if single:
        paths.append(single)

    normalized: list[str] = []
    seen: set[str] = set()
    for item in paths:
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)

    if len(normalized) > max_files:
        raise HTTPException(status_code=400, detail=f"qwen_too_many_files: maximum {max_files} files per message")
    return normalized


def prevalidate_upload_paths(paths: list[str], *, max_size_bytes: int) -> None:
    """Validate local paths before handing them to Qwen upload transport."""
    max_mb = max_size_bytes // (1024 * 1024)
    for item in paths:
        path = Path(item)
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=400, detail=f"File does not exist: {item}")
        size = path.stat().st_size
        if size > max_size_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"qwen_file_too_large: file size {size} bytes exceeds maximum {max_mb} MB",
            )


def raise_upload_http_error(exc: Exception) -> None:
    """Map upload-layer exceptions to stable HTTP errors."""
    message = str(exc)
    if "qwen_file_too_large" in message:
        raise HTTPException(
            status_code=413,
            detail={
                "error": "qwen_file_too_large",
                "error_code": "qwen_file_too_large",
                "message": message,
                "status_code": 413,
            },
        )
    if "qwen_too_many_files" in message:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "qwen_too_many_files",
                "error_code": "qwen_too_many_files",
                "message": message,
                "status_code": 400,
            },
        )
    if "qwen_no_files" in message or "File does not exist" in message:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "qwen_upload_bad_request",
                "error_code": "qwen_upload_bad_request",
                "message": message,
                "status_code": 400,
            },
        )
    raise_provider_http_error(exc, operation="file_upload")
