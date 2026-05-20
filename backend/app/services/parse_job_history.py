"""Shared parse job history persisted outside browser localStorage."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app.core.config import settings

_LOCK = threading.Lock()
_HISTORY_PATH = Path(settings.resolve_path("data/parse_jobs.json"))
_MAX_JOBS = 100


def _read_jobs_unlocked() -> list[dict[str, Any]]:
    if not _HISTORY_PATH.exists():
        return []
    try:
        data = json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _write_jobs_unlocked(jobs: list[dict[str, Any]]) -> None:
    _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _HISTORY_PATH.write_text(
        json.dumps(jobs[:_MAX_JOBS], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_parse_jobs(limit: int = 50) -> list[dict[str, Any]]:
    with _LOCK:
        return _read_jobs_unlocked()[:limit]


def add_parse_job(job: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "jobId": str(job.get("jobId") or ""),
        "startedAt": int(job.get("startedAt") or 0),
        "query": str(job.get("query") or ""),
        "source": str(job.get("source") or "all"),
        "initialCount": int(job.get("initialCount") or 0),
        "lastObservedCount": int(job.get("lastObservedCount") or job.get("initialCount") or 0),
        "lastCountChangeAt": int(job.get("lastCountChangeAt") or job.get("startedAt") or 0),
        "status": str(job.get("status") or "in_progress"),
    }
    if not normalized["jobId"]:
        return normalized

    with _LOCK:
        jobs = [item for item in _read_jobs_unlocked() if item.get("jobId") != normalized["jobId"]]
        jobs.insert(0, normalized)
        _write_jobs_unlocked(jobs)
    return normalized


def remove_parse_job(job_id: str) -> bool:
    with _LOCK:
        jobs = _read_jobs_unlocked()
        next_jobs = [item for item in jobs if item.get("jobId") != job_id]
        if len(next_jobs) == len(jobs):
            return False
        _write_jobs_unlocked(next_jobs)
        return True
