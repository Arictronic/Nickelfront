"""Streaming send/continue runtime helpers for qwen_service.

This module contains the retry, history-recovery and partial-stream handling
logic used by service.py. It is intentionally transport-compatible: callers pass
the active QwenAPI proxy/client and runtime callbacks, so FastAPI routes and
Qwen upload/session/token behavior stay unchanged.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

try:
    from .qwen_api import (
        QwenChatInProgressError,
        QwenInternalStreamError,
        QwenProviderError,
        QwenRequestEndedError,
        SendRequest,
        StreamCallbacks,
    )
except ImportError:  # pragma: no cover - direct script import compatibility
    from qwen_api import (
        QwenChatInProgressError,
        QwenInternalStreamError,
        QwenProviderError,
        QwenRequestEndedError,
        SendRequest,
        StreamCallbacks,
    )

try:
    from requests.exceptions import ChunkedEncodingError, ConnectionError as RequestsConnectionError, ReadTimeout
except Exception:  # pragma: no cover - dependency fallback for diagnostics/imports
    ChunkedEncodingError = Exception
    RequestsConnectionError = Exception
    ReadTimeout = Exception


def send_message_sync(
    *,
    qwen_api: Any,
    config: dict[str, Any],
    session_id: str,
    message: str,
    thinking_enabled: bool,
    search_enabled: bool,
    ref_file_ids: list[str] | None = None,
    timeout: int = 120,
    default_stream_retries: int,
    default_model: str,
    default_history_recovery_attempts: int,
    default_history_recovery_interval_sec: float,
    wait_provider_start_spacing: Callable[[str], None],
    provider_retry_backoff: Callable[[float], float],
    recover_response_from_history: Callable[..., tuple[str, str, int]],
    pick_fallback_model: Callable[..., str | None],
    save_config: Callable[[dict[str, Any]], None],
    set_model_for_all_clients: Callable[[str], None],
) -> tuple[str, str, int, bool]:
    """Synchronous send with retry/partial-result resilience for unstable SSE streams."""
    qwen_api.session_id = session_id

    start_time = time.time()
    last_activity = start_time
    response_text = ""
    thinking_text = ""
    message_id = 0
    can_continue = False
    chunks_count = 0

    def on_parts(thinking: str, response: str):
        nonlocal thinking_text, response_text, last_activity, chunks_count
        thinking_text = thinking
        response_text = response
        last_activity = time.time()
        chunks_count += 1

        elapsed = last_activity - start_time
        if int(elapsed) % 15 == 0 and elapsed > 0:
            logging.info(f"  -> Receiving stream... {int(elapsed)}s, {chunks_count} chunks")

    def on_complete_parts(thinking: str, response: str):
        nonlocal thinking_text, response_text, last_activity
        thinking_text = thinking
        response_text = response
        last_activity = time.time()

    def on_meta(meta: dict[str, Any]):
        nonlocal message_id, can_continue
        message_id = int(meta.get("response_message_id", 0))
        can_continue = bool(meta.get("can_continue", False))

        if not can_continue and qwen_api.last_response_meta:
            can_continue = bool(qwen_api.last_response_meta.get("can_continue", False))

        if message_id <= 0:
            message_id = int(qwen_api.last_message_id or 0)

    send_request = SendRequest(
        session_id=session_id,
        prompt=message,
        ref_file_ids=ref_file_ids or [],
        thinking_enabled=thinking_enabled,
        search_enabled=search_enabled,
    )

    callbacks = StreamCallbacks(
        on_parts=on_parts,
        on_meta=on_meta,
        on_complete_parts=on_complete_parts,
    )

    max_retries = max(0, int(config.get("stream_retries", default_stream_retries)))
    attempted_model_fallbacks: set[str] = {str(config.get("model", default_model)).strip().lower()}
    max_model_fallback_switches = 4
    model_fallback_switches = 0
    attempt = 0

    while True:
        attempt += 1
        try:
            wait_provider_start_spacing("send_message")
            qwen_api.send(send_request, callbacks)
            elapsed = time.time() - start_time
            logging.info(
                f"Message received: session={session_id[-6:]}, len={len(response_text)}, time={elapsed:.1f}s, attempt={attempt}"
            )
            break
        except (ChunkedEncodingError, ReadTimeout, RequestsConnectionError) as e:
            stream_already_started = bool(response_text.strip() or thinking_text.strip() or chunks_count > 0)

            if response_text.strip():
                logging.warning(
                    "Stream interrupted after partial response (session=%s, attempt=%s, len=%s): %s",
                    session_id[-6:],
                    attempt,
                    len(response_text),
                    e,
                )
                can_continue = True
                if message_id <= 0:
                    message_id = int(qwen_api.last_message_id or 0)
                break

            if stream_already_started:
                logging.warning(
                    "Stream interrupted after activity; will not resend prompt to busy Qwen session "
                    "(session=%s, attempt=%s, thinking_len=%s, chunks=%s): %s",
                    session_id[-6:],
                    attempt,
                    len(thinking_text),
                    chunks_count,
                    e,
                )
                recovered_thinking, recovered_response, recovered_message_id = recover_response_from_history(
                    session_id=session_id,
                    min_message_id=max(0, message_id),
                    attempts_override=max(
                        int(config.get("history_recovery_attempts", default_history_recovery_attempts)),
                        20,
                    ),
                    interval_override=max(
                        float(config.get("history_recovery_interval_sec", default_history_recovery_interval_sec)),
                        1.5,
                    ),
                )
                if recovered_response.strip():
                    thinking_text = recovered_thinking or thinking_text
                    response_text = recovered_response
                    if recovered_message_id > 0:
                        message_id = recovered_message_id
                        qwen_api.last_message_id = recovered_message_id
                    can_continue = False
                    logging.warning(
                        "Recovered active stream from history: session=%s, attempt=%s, recovered_len=%s",
                        session_id[-6:],
                        attempt,
                        len(response_text),
                    )
                    break

                raise QwenProviderError(
                    "Qwen stream was interrupted after generation started; "
                    "the prompt was not resent to avoid duplicating the request. "
                    "History recovery did not return a completed response."
                )

            if attempt <= max_retries:
                backoff = provider_retry_backoff(min(5.0, 1.0 * attempt))
                logging.warning(
                    "Transient stream error before provider activity, retrying "
                    "(session=%s, attempt=%s/%s, backoff=%.1fs): %s",
                    session_id[-6:],
                    attempt,
                    max_retries + 1,
                    backoff,
                    e,
                )
                time.sleep(backoff)
                continue

            recovered_thinking, recovered_response, recovered_message_id = recover_response_from_history(
                session_id=session_id,
                min_message_id=max(0, message_id),
            )
            if recovered_response.strip():
                thinking_text = recovered_thinking or thinking_text
                response_text = recovered_response
                if recovered_message_id > 0:
                    message_id = recovered_message_id
                    qwen_api.last_message_id = recovered_message_id
                can_continue = False
                logging.warning(
                    "Recovered after stream failure: session=%s, attempt=%s, recovered_len=%s",
                    session_id[-6:],
                    attempt,
                    len(response_text),
                )
                break

            logging.error(f"Error during message send: {e}")
            raise
        except (QwenRequestEndedError, QwenChatInProgressError, QwenInternalStreamError, QwenProviderError) as e:
            err_text = str(e).lower()

            if "model not found" in err_text:
                current_model = str(config.get("model", default_model))
                attempted_model_fallbacks.add(current_model.strip().lower())
                fallback_model = pick_fallback_model(
                    current_model=current_model,
                    tried_models=attempted_model_fallbacks,
                )
                if fallback_model and fallback_model != current_model and model_fallback_switches < max_model_fallback_switches:
                    model_fallback_switches += 1
                    attempted_model_fallbacks.add(fallback_model.strip().lower())
                    config["model"] = fallback_model
                    save_config(config)
                    set_model_for_all_clients(fallback_model)
                    logging.warning(
                        "Model '%s' is unavailable; switched to '%s' and retrying send (session=%s, fallback=%s/%s)",
                        current_model,
                        fallback_model,
                        session_id[-6:],
                        model_fallback_switches,
                        max_model_fallback_switches,
                    )
                    time.sleep(0.5)
                    continue
                logging.error(
                    "No usable Qwen fallback model left after provider model error: current=%s tried=%s",
                    current_model,
                    sorted(attempted_model_fallbacks),
                )

            recovered_thinking, recovered_response, recovered_message_id = recover_response_from_history(
                session_id=session_id,
                min_message_id=max(0, message_id),
            )
            if recovered_response.strip():
                thinking_text = recovered_thinking or thinking_text
                response_text = recovered_response
                if recovered_message_id > 0:
                    message_id = recovered_message_id
                    qwen_api.last_message_id = recovered_message_id
                can_continue = False
                logging.warning(
                    "Recovered after provider send error from history: session=%s, attempt=%s, recovered_len=%s",
                    session_id[-6:],
                    attempt,
                    len(response_text),
                )
                break

            if isinstance(e, QwenChatInProgressError):
                backoff = min(8.0, 1.5 * attempt)
                logging.warning(
                    "Chat still in progress during send; waiting for history instead of resending prompt "
                    "(session=%s, attempt=%s/%s, backoff=%.1fs)",
                    session_id[-6:],
                    attempt,
                    max_retries + 3,
                    backoff,
                )
                time.sleep(backoff)

                recovered_thinking, recovered_response, recovered_message_id = recover_response_from_history(
                    session_id=session_id,
                    min_message_id=max(0, message_id),
                    attempts_override=max(
                        int(config.get("history_recovery_attempts", default_history_recovery_attempts)),
                        12,
                    ),
                    interval_override=max(
                        float(config.get("history_recovery_interval_sec", default_history_recovery_interval_sec)),
                        1.5,
                    ),
                )
                if recovered_response.strip():
                    thinking_text = recovered_thinking or thinking_text
                    response_text = recovered_response
                    if recovered_message_id > 0:
                        message_id = recovered_message_id
                        qwen_api.last_message_id = recovered_message_id
                    can_continue = False
                    logging.warning(
                        "Recovered in-progress chat from history: session=%s, attempt=%s, recovered_len=%s",
                        session_id[-6:],
                        attempt,
                        len(response_text),
                    )
                    break

                if attempt <= (max_retries + 2):
                    continue

                raise QwenProviderError(
                    "Qwen provider is still processing the previous message; "
                    "history recovery did not return a completed response."
                )

            if attempt <= max_retries:
                backoff = provider_retry_backoff(min(5.0, 1.0 * attempt))
                logging.warning(
                    "Provider stream error, retrying send (session=%s, attempt=%s/%s, backoff=%.1fs): %s",
                    session_id[-6:],
                    attempt,
                    max_retries + 1,
                    backoff,
                    e,
                )
                time.sleep(backoff)
                continue

            logging.error(f"Provider error during message send: {e}")
            raise
        except Exception as e:
            logging.error(f"Error during message send: {e}")
            raise

    if not response_text.strip():
        recovered_thinking, recovered_response, recovered_message_id = recover_response_from_history(
            session_id=session_id,
            min_message_id=max(0, message_id),
        )
        if recovered_response.strip():
            thinking_text = recovered_thinking or thinking_text
            response_text = recovered_response
            if recovered_message_id > 0:
                message_id = recovered_message_id
                qwen_api.last_message_id = recovered_message_id
            can_continue = False

    if not response_text.strip() and message_id <= 0:
        raise QwenProviderError("Qwen provider returned an empty response without message_id")

    return thinking_text, response_text, message_id, can_continue


def continue_message_sync(
    *,
    qwen_api: Any,
    config: dict[str, Any],
    session_id: str,
    message_id: int,
    thinking_enabled: bool,
    timeout: int = 120,
    default_stream_retries: int,
    default_history_recovery_attempts: int,
    default_history_recovery_interval_sec: float,
    wait_provider_start_spacing: Callable[[str], None],
    provider_retry_backoff: Callable[[float], float],
    recover_response_from_history: Callable[..., tuple[str, str, int]],
) -> tuple[str, str, int, bool]:
    """Synchronous continue with retry/partial-result resilience."""
    qwen_api.session_id = session_id
    qwen_api.last_message_id = message_id

    start_time = time.time()
    last_activity = start_time
    response_text = ""
    thinking_text = ""
    new_message_id = 0
    can_continue = False
    chunks_count = 0

    def on_parts(thinking: str, response: str):
        nonlocal thinking_text, response_text, last_activity, chunks_count
        thinking_text = thinking
        response_text = response
        last_activity = time.time()
        chunks_count += 1

        elapsed = last_activity - start_time
        if int(elapsed) % 15 == 0 and elapsed > 0:
            logging.info(f"  -> Continuing stream... {int(elapsed)}s, {chunks_count} chunks")

    def on_complete_parts(thinking: str, response: str):
        nonlocal thinking_text, response_text, last_activity
        thinking_text = thinking
        response_text = response
        last_activity = time.time()

    def on_meta(meta: dict[str, Any]):
        nonlocal new_message_id, can_continue
        new_message_id = int(meta.get("response_message_id", 0))
        can_continue = bool(meta.get("can_continue", False))

        if not can_continue and qwen_api.last_response_meta:
            can_continue = bool(qwen_api.last_response_meta.get("can_continue", False))

        if new_message_id <= 0:
            new_message_id = int(qwen_api.last_message_id or 0)

    max_retries = max(0, int(config.get("stream_retries", default_stream_retries)))
    attempt = 0

    while True:
        attempt += 1
        try:
            wait_provider_start_spacing("continue_message")
            qwen_api.continue_message(
                message_id=message_id,
                on_parts=on_parts,
                on_complete_parts=on_complete_parts,
                on_meta=on_meta,
            )
            elapsed = time.time() - start_time
            logging.info(
                f"Continue received: session={session_id[-6:]}, len={len(response_text)}, time={elapsed:.1f}s, attempt={attempt}"
            )
            break
        except (ChunkedEncodingError, ReadTimeout, RequestsConnectionError) as e:
            stream_already_started = bool(response_text.strip() or thinking_text.strip() or chunks_count > 0)

            if response_text.strip():
                logging.warning(
                    "Continue stream interrupted after partial response (session=%s, attempt=%s, len=%s): %s",
                    session_id[-6:],
                    attempt,
                    len(response_text),
                    e,
                )
                can_continue = True
                if new_message_id <= 0:
                    new_message_id = int(qwen_api.last_message_id or message_id or 0)
                break

            if stream_already_started:
                logging.warning(
                    "Continue stream interrupted after activity; will not resend continue request "
                    "(session=%s, attempt=%s, thinking_len=%s, chunks=%s): %s",
                    session_id[-6:],
                    attempt,
                    len(thinking_text),
                    chunks_count,
                    e,
                )
                recovered_thinking, recovered_response, recovered_message_id = recover_response_from_history(
                    session_id=session_id,
                    min_message_id=max(0, message_id),
                    attempts_override=max(
                        int(config.get("history_recovery_attempts", default_history_recovery_attempts)),
                        20,
                    ),
                    interval_override=max(
                        float(config.get("history_recovery_interval_sec", default_history_recovery_interval_sec)),
                        1.5,
                    ),
                )
                if recovered_response.strip():
                    thinking_text = recovered_thinking or thinking_text
                    response_text = recovered_response
                    if recovered_message_id > 0:
                        new_message_id = recovered_message_id
                        qwen_api.last_message_id = recovered_message_id
                    else:
                        new_message_id = int(qwen_api.last_message_id or message_id or 0)
                    can_continue = False
                    logging.warning(
                        "Recovered active continue stream from history: session=%s, attempt=%s, recovered_len=%s",
                        session_id[-6:],
                        attempt,
                        len(response_text),
                    )
                    break

                raise QwenProviderError(
                    "Qwen continue stream was interrupted after generation started; "
                    "history recovery did not return a completed response."
                )

            if attempt <= max_retries:
                backoff = provider_retry_backoff(min(5.0, 1.0 * attempt))
                logging.warning(
                    "Transient continue error before provider activity, retrying "
                    "(session=%s, attempt=%s/%s, backoff=%.1fs): %s",
                    session_id[-6:],
                    attempt,
                    max_retries + 1,
                    backoff,
                    e,
                )
                time.sleep(backoff)
                continue

            recovered_thinking, recovered_response, recovered_message_id = recover_response_from_history(
                session_id=session_id,
                min_message_id=max(0, message_id),
            )
            if recovered_response.strip():
                thinking_text = recovered_thinking or thinking_text
                response_text = recovered_response
                if recovered_message_id > 0:
                    new_message_id = recovered_message_id
                    qwen_api.last_message_id = recovered_message_id
                else:
                    new_message_id = int(qwen_api.last_message_id or message_id or 0)
                can_continue = False
                logging.warning(
                    "Recovered continue from history after stream failure: session=%s, attempt=%s, recovered_len=%s",
                    session_id[-6:],
                    attempt,
                    len(response_text),
                )
                break

            logging.error(f"Error during continue: {e}")
            raise
        except (QwenRequestEndedError, QwenChatInProgressError, QwenInternalStreamError, QwenProviderError) as e:
            recovered_thinking, recovered_response, recovered_message_id = recover_response_from_history(
                session_id=session_id,
                min_message_id=max(0, message_id),
            )
            if recovered_response.strip():
                thinking_text = recovered_thinking or thinking_text
                response_text = recovered_response
                if recovered_message_id > 0:
                    new_message_id = recovered_message_id
                    qwen_api.last_message_id = recovered_message_id
                else:
                    new_message_id = int(qwen_api.last_message_id or message_id or 0)
                can_continue = False
                logging.warning(
                    "Recovered continue after provider error from history: session=%s, attempt=%s, recovered_len=%s",
                    session_id[-6:],
                    attempt,
                    len(response_text),
                )
                break

            if isinstance(e, QwenChatInProgressError):
                backoff = min(5.0, 1.0 * attempt)
                logging.warning(
                    "Chat still in progress during continue; waiting for history instead of resending "
                    "(session=%s, attempt=%s/%s, backoff=%.1fs): %s",
                    session_id[-6:],
                    attempt,
                    max_retries + 1,
                    backoff,
                    e,
                )
                time.sleep(backoff)

                recovered_thinking, recovered_response, recovered_message_id = recover_response_from_history(
                    session_id=session_id,
                    min_message_id=max(0, message_id),
                    attempts_override=max(
                        int(config.get("history_recovery_attempts", default_history_recovery_attempts)),
                        12,
                    ),
                    interval_override=max(
                        float(config.get("history_recovery_interval_sec", default_history_recovery_interval_sec)),
                        1.5,
                    ),
                )
                if recovered_response.strip():
                    thinking_text = recovered_thinking or thinking_text
                    response_text = recovered_response
                    if recovered_message_id > 0:
                        new_message_id = recovered_message_id
                        qwen_api.last_message_id = recovered_message_id
                    else:
                        new_message_id = int(qwen_api.last_message_id or message_id or 0)
                    can_continue = False
                    logging.warning(
                        "Recovered in-progress continue from history: session=%s, attempt=%s, recovered_len=%s",
                        session_id[-6:],
                        attempt,
                        len(response_text),
                    )
                    break

                if attempt <= max_retries:
                    continue

                raise QwenProviderError(
                    "Qwen provider is still processing the previous continue request; "
                    "history recovery did not return a completed response."
                )

            logging.warning(
                "Stopping continue due to provider terminal state (session=%s, attempt=%s): %s",
                session_id[-6:],
                attempt,
                e,
            )
            can_continue = False
            if new_message_id <= 0:
                new_message_id = int(qwen_api.last_message_id or message_id or 0)
            break
        except Exception as e:
            logging.error(f"Error during continue: {e}")
            raise

    if not response_text.strip() and new_message_id <= 0:
        raise QwenProviderError("Qwen provider returned an empty continue response without message_id")

    return thinking_text, response_text, new_message_id, can_continue
