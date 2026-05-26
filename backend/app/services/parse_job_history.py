"""Shared parse job history persisted outside browser localStorage."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from app.core.config import settings

_LOCK = threading.Lock()
_HISTORY_PATH = Path(settings.resolve_path("data/parse_jobs.json"))
_MAX_JOBS = 100
_ALLOWED_STATUSES = {"in_progress", "completed", "cancelled", "failed", "expired"}
_COUNTER_FIELDS = (
    "savedCount",
    "updatedCount",
    "duplicateCount",
    "contentQueuedCount",
    "contentSkippedCount",
)


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        if value is None or value == "":
            return fallback
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _safe_status(value: Any) -> str:
    status = str(value or "in_progress").strip()
    return status if status in _ALLOWED_STATUSES else "in_progress"


def _normalize_job(job: dict[str, Any]) -> dict[str, Any]:
    started_at = _safe_int(job.get("startedAt"), int(time.time() * 1000))
    initial_count = _safe_int(job.get("initialCount"), 0)
    normalized: dict[str, Any] = {
        "jobId": str(job.get("jobId") or ""),
        "startedAt": started_at,
        "query": str(job.get("query") or ""),
        "source": str(job.get("source") or "all"),
        "initialCount": initial_count,
        "lastObservedCount": _safe_int(job.get("lastObservedCount"), initial_count),
        "lastCountChangeAt": _safe_int(job.get("lastCountChangeAt"), started_at),
        "status": _safe_status(job.get("status")),
    }

    for field in _COUNTER_FIELDS:
        if field in job and job.get(field) is not None:
            normalized[field] = max(0, _safe_int(job.get(field), 0))

    celery_status = job.get("celeryStatus")
    if isinstance(celery_status, dict):
        normalized["celeryStatus"] = celery_status

    if job.get("lastPolledAt") is not None:
        normalized["lastPolledAt"] = _safe_int(job.get("lastPolledAt"), 0)

    return normalized


def _read_jobs_unlocked() -> list[dict[str, Any]]:
    if not _HISTORY_PATH.exists():
        return []
    try:
        data = json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [_normalize_job(item) for item in data if isinstance(item, dict)]


def _write_jobs_unlocked(jobs: list[dict[str, Any]]) -> None:
    _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _HISTORY_PATH.write_text(
        json.dumps([_normalize_job(job) for job in jobs[:_MAX_JOBS]], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_parse_jobs(limit: int = 50) -> list[dict[str, Any]]:
    with _LOCK:
        return _read_jobs_unlocked()[:limit]


def add_parse_job(job: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_job(job)
    if not normalized["jobId"]:
        return normalized

    with _LOCK:
        jobs = [item for item in _read_jobs_unlocked() if item.get("jobId") != normalized["jobId"]]
        jobs.insert(0, normalized)
        _write_jobs_unlocked(jobs)
    return normalized


def update_parse_job(job_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    """Merge fresh Celery/UI status into shared parse history."""
    if not job_id:
        return None

    with _LOCK:
        jobs = _read_jobs_unlocked()
        for index, job in enumerate(jobs):
            if job.get("jobId") != job_id:
                continue
            merged = _normalize_job({**job, **patch})
            jobs[index] = merged
            _write_jobs_unlocked(jobs)
            return merged
    return None


def remove_parse_job(job_id: str) -> bool:
    with _LOCK:
        jobs = _read_jobs_unlocked()
        next_jobs = [item for item in jobs if item.get("jobId") != job_id]
        if len(next_jobs) == len(jobs):
            return False
        _write_jobs_unlocked(next_jobs)
        return True
