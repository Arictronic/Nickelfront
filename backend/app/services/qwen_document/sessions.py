"""Qwen session naming and normalization helpers.

No HTTP calls live here; clients/services still own transport. Keeping session
metadata helpers separate prevents task/service code from duplicating title and
ID normalization rules.
"""

from __future__ import annotations

from typing import Any


def normalize_session_id(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "null", "undefined"}:
        return None
    return text


def session_tail(session_id: Any, *, width: int = 6, fallback: str = "new") -> str:
    sid = normalize_session_id(session_id)
    if not sid:
        return fallback
    return sid[-max(1, int(width or 6)) :]


def build_paper_session_title(paper_id: int | str | None, title: str | None, *, prefix: str = "paper") -> str:
    safe_prefix = str(prefix or "paper").strip() or "paper"
    paper_part = str(paper_id or "unknown").strip() or "unknown"
    title_part = str(title or "").strip().replace("\r", " ").replace("\n", " ")[:80]
    return f"{safe_prefix}-{paper_part}: {title_part}".strip()


def session_metadata(session_id: Any, *, title: str | None = None, purpose: str | None = None) -> dict[str, Any]:
    sid = normalize_session_id(session_id)
    payload: dict[str, Any] = {"session_id": sid, "session_tail": session_tail(sid, fallback="none")}
    if title is not None:
        payload["session_title"] = str(title or "").strip()
    if purpose is not None:
        payload["purpose"] = str(purpose or "").strip() or None
    return payload
