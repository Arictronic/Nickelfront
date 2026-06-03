"""Small helpers for parse/content Celery lifecycle status normalization.

Soft-fail content/Qwen stages intentionally return compact result payloads instead
of raising, so Celery may report ``SUCCESS`` while the stage result says
``stage_failed``. Dashboard and parse-job history must therefore inspect both the
Celery state and the compact result/info payload.
"""

from __future__ import annotations

import time
from typing import Any

PARTIAL_RESULT_STATUSES = {
    "completed_with_errors",
    "partial_success",
    "warning",
    "partial",
    "stage_failed",
}
ACTIVE_DOWNSTREAM_STATES = {"PENDING", "RECEIVED", "STARTED", "PROGRESS", "RETRY", "UNKNOWN"}
FAILED_DOWNSTREAM_STATES = {"FAILURE"}
TERMINAL_DOWNSTREAM_STATES = {"SUCCESS", "FAILURE", "REVOKED"}
UNKNOWN_DOWNSTREAM_STATES = {"PENDING", "UNKNOWN"}
DOWNSTREAM_UNKNOWN_STALE_MS = 60 * 60 * 1000

SOFT_FAILURE_STATUS_VALUES = {
    "stage_failed",
    "qwen_stage_failed",
    "pipeline_stage_failed",
    "ready_with_fallback",
}
PIPELINE_ERROR_KEYS = {
    "pipeline_error",
    "failed_stage",
    "first_failed_stage",
    "failed_task_id",
    "pipeline_error_message",
    "error_message",
    "retry_allowed",
    "fallback_used",
    "markdown_error",
    "keywords_error",
    "embedding_error",
    "qwen_fallback_reason",
    "qwen_used_fallback",
}
STAGE_ERRORS_KEYS = {"stage_errors", "errors"}

COMPACT_CHILD_PAYLOAD_KEYS = {
    "status",
    "result_status",
    "status_key",
    "status_label",
    "stage",
    "stage_label",
    "paper_id",
    "root_task_id",
    "content_root_task_id",
    "content_wrapper_task_id",
    "parse_root_task_id",
    "chain_result_id",
    "pdf_mode",
    "pdf_downloaded",
    "pdf_skipped",
    "pdf_url",
    "text_available",
    "text_source",
    "fresh_content_available",
    "fresh_parts_created",
    "content_parts_count",
    "markdown_ready",
    "markdown_skipped",
    "markdown_partial",
    "markdown_error",
    "markdown_parts_ready",
    "markdown_parts_failed",
    "markdown_parts_skipped",
    "markdown_parts_total",
    "ru_analysis_ready",
    "qwen_analysis_skipped",
    "qwen_used_fallback",
    "qwen_fallback_reason",
    "keywords_ready",
    "keywords_error",
    "keywords_count",
    "keywords_generated_count",
    "keywords_validated_count",
    "keywords_rejected_count",
    "embedded",
    "embedding_skipped",
    "embedding_error",
    "final_stage",
    "error",
    "errors",
    "errors_count",
    "current",
    "total",
    "percent",
    "stage_task_ids",
    "stage_tasks",
    "related_task_ids",
    "child_task_ids",


    "pipeline_error",
    "failed_stage",
    "first_failed_stage",
    "failed_task_id",
    "pipeline_error_message",
    "error_type",
    "error_message",
    "retry_allowed",
    "fallback_used",
    "stage_errors",
}


def safe_int(value: Any, fallback: int = 0) -> int:
    try:
        if value in (None, ""):
            return fallback
        return int(value)
    except (TypeError, ValueError):
        return fallback


def now_ms() -> int:
    return int(time.time() * 1000)


def compact_child_payload(payload: dict | None) -> dict | None:
    """Keep task-tree payloads small enough for parse_jobs.json and dashboard UI."""
    if not isinstance(payload, dict):
        return None
    output: dict[str, Any] = {}
    for key in COMPACT_CHILD_PAYLOAD_KEYS:
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, str):
            output[key] = value[:1200]
        elif key in {"errors", "stage_errors"} and isinstance(value, list):
            compact_items: list[Any] = []
            for item in value[:10]:
                if isinstance(item, dict):
                    compact_items.append({str(k): (str(v)[:600] if isinstance(v, str) else v) for k, v in item.items()})
                else:
                    compact_items.append(str(item)[:600])
            output[key] = compact_items
        else:
            output[key] = value
    return output or None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, "", 0, "0", "false", "False", "no", "No"):
        return False
    return bool(value)


def payload_has_pipeline_warning(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False
    status = str(payload.get("status") or payload.get("result_status") or "").strip()
    final_stage = str(payload.get("final_stage") or "").strip()
    if status in PARTIAL_RESULT_STATUSES or status in SOFT_FAILURE_STATUS_VALUES:
        return True
    if final_stage == "ready_with_fallback":
        return True
    if safe_int(payload.get("errors_count"), 0) > 0:
        return True
    for key in PIPELINE_ERROR_KEYS:
        if key in payload and _truthy(payload.get(key)):
            return True
    for key in STAGE_ERRORS_KEYS:
        value = payload.get(key)
        if isinstance(value, list) and bool(value):
            return True
    return False


def payload_error_text(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("pipeline_error_message", "error_message", "error", "markdown_error", "keywords_error", "embedding_error", "qwen_fallback_reason"):
        value = payload.get(key)
        if value:
            return str(value)[:600]
    stage_errors = payload.get("stage_errors")
    if isinstance(stage_errors, list) and stage_errors:
        first = stage_errors[0]
        if isinstance(first, dict):
            return str(first.get("error_message") or first.get("message") or first)[:600]
        return str(first)[:600]
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        return str(errors[0])[:600]
    return None


def child_payloads(child: dict | None) -> list[dict]:
    if not isinstance(child, dict):
        return []
    result = child.get("result") if isinstance(child.get("result"), dict) else None
    info = child.get("info") if isinstance(child.get("info"), dict) else None
    return [payload for payload in (result, info) if isinstance(payload, dict)]


def child_has_pipeline_warning(child: dict | None) -> bool:
    return any(payload_has_pipeline_warning(payload) for payload in child_payloads(child))


def result_is_partial(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    status = str(result.get("status") or result.get("result_status") or "").strip()
    errors = result.get("errors")
    return (
        status in PARTIAL_RESULT_STATUSES
        or payload_has_pipeline_warning(result)
        or safe_int(result.get("errors_count"), 0) > 0
        or (isinstance(errors, list) and bool(errors))
    )


def related_statuses(task_info: dict | None) -> list[dict]:
    raw = (task_info or {}).get("related_child_statuses")
    return [item for item in raw or [] if isinstance(item, dict)]


def _has_finalize_result(task_info: dict | None) -> bool:
    for child in related_statuses(task_info):
        stage = " ".join(
            str(value or "").lower()
            for value in (
                child.get("name"),
                child.get("stage"),
                *(payload.get("stage") for payload in child_payloads(child)),
            )
        )
        if "finalize" not in stage:
            continue
        status = str(child.get("status") or child.get("state") or "").upper()
        if status in TERMINAL_DOWNSTREAM_STATES or child_payloads(child):
            return True
    result = task_info.get("result") if isinstance((task_info or {}).get("result"), dict) else None
    return bool(result and result.get("final_stage"))


def downstream_is_active(task_info: dict | None, *, stale_after_ms: int | None = None) -> bool:
    finalized = _has_finalize_result(task_info)
    for child in related_statuses(task_info):
        status = str(child.get("status") or child.get("state") or "UNKNOWN").strip().upper()
        if status not in ACTIVE_DOWNSTREAM_STATES:
            continue
        if status in UNKNOWN_DOWNSTREAM_STATES:
            if finalized:
                continue
            if stale_after_ms is not None and stale_after_ms >= DOWNSTREAM_UNKNOWN_STALE_MS:
                continue
        return True
    return False


def downstream_has_failure(task_info: dict | None) -> bool:
    for child in related_statuses(task_info):
        status = str(child.get("status") or child.get("state") or "").strip().upper()
        if status in FAILED_DOWNSTREAM_STATES or child_has_pipeline_warning(child):
            return True
    return False


def parse_job_status_from_celery(
    celery_status: str | None,
    result: dict | None = None,
    task_info: dict | None = None,
    *,
    stale_after_ms: int | None = None,
) -> str:
    if celery_status == "SUCCESS":
        if downstream_is_active(task_info, stale_after_ms=stale_after_ms):
            return "in_progress"
        if result_is_partial(result) or downstream_has_failure(task_info):
            return "partial"
        return "completed"
    if celery_status == "FAILURE":
        return "failed"
    if celery_status == "REVOKED":
        return "cancelled"
    return "in_progress"
