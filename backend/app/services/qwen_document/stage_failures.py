from __future__ import annotations

from typing import Any

PIPELINE_ERROR_MESSAGE_MAX = 1200
PIPELINE_STAGE_ERRORS_MAX = 20


def short_error(exc: BaseException | str | None, *, default: str = "qwen_stage_failed") -> str:
    if exc is None:
        return default
    if isinstance(exc, BaseException):
        text = f"{type(exc).__name__}: {exc}"
    else:
        text = str(exc)
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split()).strip()
    return (text or default)[:PIPELINE_ERROR_MESSAGE_MAX]


def stage_errors_from_previous(previous: Any) -> list[dict[str, Any]]:
    if not isinstance(previous, dict):
        return []
    raw = previous.get("stage_errors")
    if not isinstance(raw, list):
        return []
    output: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage") or "").strip()
        message = str(item.get("error_message") or item.get("error") or "").strip()
        if not stage and not message:
            continue
        output.append(
            {
                "stage": stage or "unknown",
                "task_id": str(item.get("task_id") or "").strip() or None,
                "error_type": str(item.get("error_type") or "").strip() or None,
                "error_message": message[:PIPELINE_ERROR_MESSAGE_MAX],
                "retry_allowed": bool(item.get("retry_allowed", True)),
                "fallback_used": bool(item.get("fallback_used", True)),
            }
        )
    return output[:PIPELINE_STAGE_ERRORS_MAX]


def append_stage_error(
    previous: Any,
    *,
    stage: str,
    task_id: str | None,
    exc: BaseException | str | None,
    retry_allowed: bool = True,
    fallback_used: bool = True,
) -> list[dict[str, Any]]:
    errors = stage_errors_from_previous(previous)
    error_type = type(exc).__name__ if isinstance(exc, BaseException) else None
    errors.append(
        {
            "stage": stage,
            "task_id": task_id,
            "error_type": error_type,
            "error_message": short_error(exc),
            "retry_allowed": bool(retry_allowed),
            "fallback_used": bool(fallback_used),
        }
    )
    return errors[-PIPELINE_STAGE_ERRORS_MAX:]


def paper_id_from_previous(previous: Any) -> int | None:
    if isinstance(previous, dict):
        value = previous.get("paper_id")
        try:
            return int(value) if value is not None else None
        except Exception:
            return None
    try:
        return int(previous) if previous is not None else None
    except Exception:
        return None


def merge_previous(previous: Any, **updates: Any) -> dict[str, Any]:
    payload = dict(previous) if isinstance(previous, dict) else {"paper_id": previous}
    payload.update(updates)
    return payload


def stage_failure_payload(
    previous: Any,
    *,
    stage: str,
    task_id: str | None,
    exc: BaseException | str | None,
    paper_id: int | None = None,
    retry_allowed: bool = True,
    fallback_used: bool = True,
    **updates: Any,
) -> dict[str, Any]:
    previous_payload = previous if isinstance(previous, dict) else {}
    first_failed_stage = str(previous_payload.get("first_failed_stage") or "").strip() or stage
    error_text = short_error(exc)
    return merge_previous(
        previous,
        status="stage_failed",
        paper_id=paper_id or paper_id_from_previous(previous),
        pipeline_error=True,
        first_failed_stage=first_failed_stage,
        failed_stage=stage,
        failed_task_id=task_id,
        error=error_text,
        pipeline_error_message=error_text,
        retry_allowed=bool(retry_allowed),
        fallback_used=bool(fallback_used),
        stage_errors=append_stage_error(
            previous,
            stage=stage,
            task_id=task_id,
            exc=exc,
            retry_allowed=retry_allowed,
            fallback_used=fallback_used,
        ),
        **{f"{stage}_error": error_text},
        **updates,
    )
