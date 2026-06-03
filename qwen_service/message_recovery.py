"""Helpers for recovering interrupted Qwen responses and model fallbacks.

This module is intentionally transport-light: callers pass the active QwenAPI
instance and runtime config instead of importing the FastAPI service globals.
"""

from __future__ import annotations

import time
from typing import Any, Callable

LoggerLike = Any


def extract_latest_assistant_parts(
    qwen_api: Any,
    session_id: str,
    min_message_id: int = 0,
) -> tuple[str, str, int]:
    """
    Read the latest assistant message from chat history.
    Returns: (thinking, response, message_id). Empty response means not found.
    """
    if not qwen_api:
        return "", "", 0

    _, messages = qwen_api.fetch_history(session_id)
    if not messages:
        return "", "", 0

    for msg in reversed(messages):
        if msg.get("role") != "ASSISTANT":
            continue

        msg_id = int(msg.get("message_id") or 0)
        if min_message_id > 0 and msg_id < min_message_id:
            continue

        think_parts: list[str] = []
        response_parts: list[str] = []
        for fragment in msg.get("fragments") or []:
            if not isinstance(fragment, dict):
                continue
            fragment_type = str(fragment.get("type") or "")
            fragment_content = str(fragment.get("content") or "").strip()
            if not fragment_content:
                continue
            if fragment_type == "THINK":
                think_parts.append(fragment_content)
            if fragment_type == "RESPONSE":
                response_parts.append(fragment_content)

        return "\n\n".join(think_parts), "\n\n".join(response_parts), msg_id

    return "", "", 0


def pick_fallback_model(
    qwen_api: Any,
    current_model: str,
    *,
    tried_models: set[str] | None = None,
    logger: LoggerLike | None = None,
) -> str | None:
    """
    Pick the next model when provider returns `Model not found`.

    Keep track of already attempted models for the current request. Without that
    guard a bad provider model list or a stale static fallback list can cycle
    forever, for example qwen3.6-plus -> qwen3.5-plus -> qwen3.6-plus.
    """
    normalized_current = (current_model or "").strip().lower()
    tried = {item.strip().lower() for item in (tried_models or set()) if item and item.strip()}
    if normalized_current:
        tried.add(normalized_current)

    provider_candidates: list[str] = []
    if qwen_api:
        try:
            for model in qwen_api.fetch_models() or []:
                if not isinstance(model, dict):
                    continue
                model_id = str(model.get("id") or model.get("name") or "").strip()
                if model_id:
                    provider_candidates.append(model_id)
        except Exception as exc:
            if logger is not None:
                logger.warning("Failed to fetch provider model fallback list: %s", exc)
            provider_candidates = []

    static_candidates = ["qwen3.6-plus", "qwen3.5-plus", "qwen-plus", "qwen-max"]
    ordered: list[str] = []
    seen: set[str] = set()
    for candidate in provider_candidates + static_candidates:
        normalized = (candidate or "").strip()
        if not normalized:
            continue
        low = normalized.lower()
        if low in seen:
            continue
        seen.add(low)
        ordered.append(normalized)

    for candidate in ordered:
        if candidate.lower() not in tried:
            return candidate
    return None


def recover_response_from_history(
    qwen_api: Any,
    config: dict[str, Any],
    *,
    default_attempts: int,
    default_interval_sec: float,
    session_id: str,
    min_message_id: int = 0,
    attempts_override: int | None = None,
    interval_override: float | None = None,
    logger: LoggerLike | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[str, str, int]:
    """
    Fallback recovery when SSE stream is interrupted.
    Polls chat history for a saved assistant message.

    Important: when provider stream already produced chunks/thinking and then
    disconnected, the prompt must not be sent again to the same Qwen session.
    Qwen may still be generating the first answer and a duplicate send often
    returns "The chat is in progress!". In that case callers pass larger
    recovery limits here and wait for the already-started answer in history.
    """
    configured_attempts = int(config.get("history_recovery_attempts", default_attempts))
    configured_interval = float(config.get("history_recovery_interval_sec", default_interval_sec))
    attempts = max(1, int(attempts_override if attempts_override is not None else configured_attempts))
    interval = max(0.5, float(interval_override if interval_override is not None else configured_interval))

    for attempt in range(1, attempts + 1):
        thinking, response, recovered_message_id = extract_latest_assistant_parts(
            qwen_api=qwen_api,
            session_id=session_id,
            min_message_id=min_message_id,
        )
        if response.strip():
            if logger is not None:
                logger.info(
                    "Recovered response from history: session=%s, len=%s, message_id=%s, attempt=%s/%s",
                    session_id[-6:],
                    len(response),
                    recovered_message_id,
                    attempt,
                    attempts,
                )
            return thinking, response, recovered_message_id

        if attempt < attempts:
            sleep_fn(interval)

    return "", "", 0
