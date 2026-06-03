"""HAR file storage helpers for the standalone Qwen service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

DEFAULT_MAX_HAR_BYTES = 120 * 1024 * 1024


def resolve_project_path(raw_path: str | None, *, project_root: Path, default: str) -> Path:
    """Resolve service paths relative to the project root."""
    raw = str(raw_path or default or "").strip() or default
    path = Path(raw)
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def configured_har_dir(config: dict[str, Any], *, project_root: Path, default_har_dir: str) -> Path:
    return resolve_project_path(str(config.get("har_dir", default_har_dir)), project_root=project_root, default=default_har_dir)


def ensure_har_dir(config: dict[str, Any], *, project_root: Path, default_har_dir: str) -> Path:
    har_dir = configured_har_dir(config, project_root=project_root, default_har_dir=default_har_dir)
    har_dir.mkdir(parents=True, exist_ok=True)
    return har_dir


def latest_har_file(har_dir: Path) -> Path | None:
    candidates = [p for p in har_dir.glob("*.har") if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def load_har_from_service_dir(
    filename: str | None = None,
    *,
    config: dict[str, Any],
    project_root: Path,
    default_har_dir: str,
    max_bytes: int = DEFAULT_MAX_HAR_BYTES,
) -> tuple[Path, bytes]:
    """Load a HAR file from the configured Qwen HAR directory with path-safety checks."""
    har_dir = ensure_har_dir(config, project_root=project_root, default_har_dir=default_har_dir)
    if filename and str(filename).strip():
        safe_name = Path(str(filename).strip()).name
        if not safe_name.lower().endswith(".har"):
            raise HTTPException(status_code=400, detail="HAR-файл должен иметь расширение .har")
        har_path = (har_dir / safe_name).resolve()
    else:
        latest = latest_har_file(har_dir)
        if latest is None:
            raise HTTPException(
                status_code=404,
                detail=f"В папке {har_dir} нет .har файлов. Положите HAR в qwen_service/har или передайте файл через /config/token/update-from-har.",
            )
        har_path = latest.resolve()

    try:
        har_path.relative_to(har_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Недопустимое имя HAR-файла") from exc

    if not har_path.exists() or not har_path.is_file():
        raise HTTPException(status_code=404, detail=f"HAR-файл не найден: {har_path.name}")
    if har_path.stat().st_size > max_bytes:
        raise HTTPException(status_code=400, detail="HAR-файл слишком большой: максимум 120 МБ")
    return har_path, har_path.read_bytes()
