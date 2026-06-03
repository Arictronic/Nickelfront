"""High-level Qwen message endpoint orchestration.

This module keeps FastAPI route wrappers in ``service.py`` thin while preserving
existing Qwen transport, stream retry and continuation behavior. Callers inject
runtime callbacks/state explicitly so this split does not change public API or
provider calls.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

try:
    from .continuation import (
        can_auto_continue as _state_can_auto_continue,
        reset_continuation_tracker as _state_reset_continuation_tracker,
        should_auto_continue as _state_should_auto_continue,
        track_continuation as _state_track_continuation,
    )
    from .defaults import DEFAULT_AUTO_CONTINUE_ENABLED, DEFAULT_MAX_CONTINUES
    from .error_payload import raise_provider_http_error
except ImportError:  # pragma: no cover - direct script compatibility
    from continuation import (
        can_auto_continue as _state_can_auto_continue,
        reset_continuation_tracker as _state_reset_continuation_tracker,
        should_auto_continue as _state_should_auto_continue,
        track_continuation as _state_track_continuation,
    )
    from defaults import DEFAULT_AUTO_CONTINUE_ENABLED, DEFAULT_MAX_CONTINUES
    from error_payload import raise_provider_http_error


LoggerLike = Any



async def send_message_payload_from_state(
    request: Any,
    *,
    state: Any,
    new_qwen_api: Callable[[], Any],
    provider_error_cls: type[Exception],
    run_with_provider_slot: Callable[[str, Callable[[], Any]], Any],
    send_message_sync: Callable[..., tuple[str, str, int, bool]],
    continue_message_sync: Callable[..., tuple[str, str, int, bool]],
    logger: LoggerLike = logging,
) -> dict[str, Any]:
    """Run ``POST /messages`` using the shared runtime state container."""
    return await send_message_payload(
        request,
        config=state.config,
        default_auto_continue=DEFAULT_AUTO_CONTINUE_ENABLED,
        get_session_lock=state.get_session_lock,
        get_session_qwen_api=lambda session_id: state.get_session_client(
            session_id,
            client_factory=new_qwen_api,
            provider_error_cls=provider_error_cls,
        ),
        current_qwen_client=state.current_qwen_client,
        run_with_provider_slot=run_with_provider_slot,
        reset_continuation_tracker=lambda session_id: _state_reset_continuation_tracker(
            state.auto_continue_tracker, session_id
        ),
        send_message_sync=send_message_sync,
        continue_message_sync=continue_message_sync,
        should_auto_continue=_state_should_auto_continue,
        can_auto_continue=lambda session_id: _state_can_auto_continue(
            config=state.config,
            tracker_store=state.auto_continue_tracker,
            session_id=session_id,
            default_enabled=DEFAULT_AUTO_CONTINUE_ENABLED,
            default_max_continues=DEFAULT_MAX_CONTINUES,
        ),
        track_continuation=lambda session_id, message_id: _state_track_continuation(
            state.auto_continue_tracker, session_id, message_id
        ),
        touch_active_session=getattr(state, "touch_active_session", None),
        logger=logger,
    )


async def continue_message_payload_from_state(
    request: Any,
    auto_continue: bool | None = None,
    *,
    state: Any,
    new_qwen_api: Callable[[], Any],
    provider_error_cls: type[Exception],
    continue_message_sync: Callable[..., tuple[str, str, int, bool]],
    logger: LoggerLike = logging,
) -> dict[str, Any]:
    """Run ``POST /messages/continue`` using the shared runtime state container."""
    return await continue_message_payload(
        request,
        auto_continue,
        config=state.config,
        default_auto_continue=DEFAULT_AUTO_CONTINUE_ENABLED,
        get_session_lock=state.get_session_lock,
        get_session_qwen_api=lambda session_id: state.get_session_client(
            session_id,
            client_factory=new_qwen_api,
            provider_error_cls=provider_error_cls,
        ),
        current_qwen_client=state.current_qwen_client,
        reset_continuation_tracker=lambda session_id: _state_reset_continuation_tracker(
            state.auto_continue_tracker, session_id
        ),
        continuation_tracker=state.auto_continue_tracker,
        continue_message_sync=continue_message_sync,
        should_auto_continue=_state_should_auto_continue,
        can_auto_continue=lambda session_id: _state_can_auto_continue(
            config=state.config,
            tracker_store=state.auto_continue_tracker,
            session_id=session_id,
            default_enabled=DEFAULT_AUTO_CONTINUE_ENABLED,
            default_max_continues=DEFAULT_MAX_CONTINUES,
        ),
        track_continuation=lambda session_id, message_id: _state_track_continuation(
            state.auto_continue_tracker, session_id, message_id
        ),
        touch_active_session=getattr(state, "touch_active_session", None),
        logger=logger,
    )


def send_message_sync_impl(
    request: Any,
    *,
    config: dict[str, Any],
    default_auto_continue: bool,
    reset_continuation_tracker: Callable[[str], None],
    send_message_sync: Callable[..., tuple[str, str, int, bool]],
    continue_message_sync: Callable[..., tuple[str, str, int, bool]],
    should_auto_continue: Callable[[str, bool], bool],
    can_auto_continue: Callable[[str], bool],
    track_continuation: Callable[[str, int], None],
    logger: LoggerLike = logging,
) -> dict[str, Any]:
    """Synchronous implementation of ``POST /messages``.

    Caller is responsible for selecting the per-session Qwen client and holding
    the per-session lock.
    """
    try:
        reset_continuation_tracker(request.session_id)

        auto_continue = request.auto_continue
        if auto_continue is None:
            auto_continue = config.get("auto_continue_enabled", default_auto_continue)

        thinking_text, response_text, message_id, can_continue = send_message_sync(
            session_id=request.session_id,
            message=request.message,
            thinking_enabled=request.thinking_enabled,
            search_enabled=request.search_enabled,
            ref_file_ids=request.file_ids,
        )

        logger.info(
            "Message sent: session=%s, message_id=%s, can_continue=%s",
            request.session_id[-6:],
            message_id,
            can_continue,
        )

        if not response_text.strip() and message_id > 0:
            logger.warning(
                "Initial response is empty, forcing one continue attempt: session=%s, message_id=%s",
                request.session_id[-6:],
                message_id,
            )
            forced_thinking, forced_response, forced_message_id, forced_can_continue = continue_message_sync(
                session_id=request.session_id,
                message_id=message_id,
                thinking_enabled=request.thinking_enabled,
            )
            if forced_thinking:
                thinking_text = forced_thinking
            if forced_response:
                response_text = forced_response
            if forced_message_id > 0:
                message_id = forced_message_id
            can_continue = forced_can_continue

        continue_count = 0
        all_thinking_parts = [thinking_text] if thinking_text else []
        all_response_parts = [response_text] if response_text else []
        last_message_id = message_id
        last_response_text = response_text
        no_progress_streak = 0

        need_continue = bool(auto_continue) and should_auto_continue(last_response_text, can_continue)

        while need_continue and can_auto_continue(request.session_id):
            continue_count += 1
            track_continuation(request.session_id, last_message_id)

            logger.info(
                "Auto-continue #%s for session=%s, message_id=%s",
                continue_count,
                request.session_id[-6:],
                last_message_id,
            )

            cont_thinking, cont_response, new_message_id, new_can_continue = continue_message_sync(
                session_id=request.session_id,
                message_id=last_message_id,
                thinking_enabled=request.thinking_enabled,
            )

            if cont_thinking:
                all_thinking_parts.append(cont_thinking)
            if cont_response:
                all_response_parts.append(cont_response)

            if not (cont_response or "").strip() and new_message_id == last_message_id:
                no_progress_streak += 1
                logger.warning(
                    "Auto-continue stopped due to no progress: session=%s, message_id=%s, continue_count=%s",
                    request.session_id[-6:],
                    last_message_id,
                    continue_count,
                )
                if no_progress_streak >= 1:
                    can_continue = False
                    break
            else:
                no_progress_streak = 0

            last_message_id = new_message_id
            last_response_text = cont_response or last_response_text
            can_continue = new_can_continue
            need_continue = bool(auto_continue) and should_auto_continue(last_response_text, can_continue)

            logger.info(
                "Continue #%s done: new_message_id=%s, can_continue=%s, need_continue=%s",
                continue_count,
                new_message_id,
                can_continue,
                need_continue,
            )

        full_thinking = "\n\n".join(filter(None, all_thinking_parts))
        full_response = "\n\n".join(filter(None, all_response_parts))

        return {
            "session_id": request.session_id,
            "message": request.message,
            "response": full_response,
            "thinking": full_thinking,
            "thinking_enabled": request.thinking_enabled,
            "search_enabled": request.search_enabled,
            "auto_continue_performed": continue_count > 0,
            "continue_count": continue_count,
            "can_continue": can_continue,
            "message_id": last_message_id,
            "last_message_id": last_message_id,
            "auto_continue_reason": "API flag" if can_continue else "content analysis" if continue_count > 0 else "none",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error sending message: %s", exc)
        raise_provider_http_error(exc, operation="send_message")


async def send_message_payload(
    request: Any,
    *,
    config: dict[str, Any],
    default_auto_continue: bool,
    get_session_lock: Callable[[str], Any],
    get_session_qwen_api: Callable[[str], Any],
    current_qwen_client: Any,
    run_with_provider_slot: Callable[[str, Callable[[], Any]], Any],
    reset_continuation_tracker: Callable[[str], None],
    send_message_sync: Callable[..., tuple[str, str, int, bool]],
    continue_message_sync: Callable[..., tuple[str, str, int, bool]],
    should_auto_continue: Callable[[str, bool], bool],
    can_auto_continue: Callable[[str], bool],
    track_continuation: Callable[[str, int], None],
    touch_active_session: Callable[..., Any] | None = None,
    logger: LoggerLike = logging,
) -> dict[str, Any]:
    """Run ``POST /messages`` under session lock/provider slot."""
    started = time.monotonic()
    session_tail = request.session_id[-8:]
    logger.info(
        "Qwen message received: session=%s chars=%s thinking=%s search=%s auto_continue=%s files=%s",
        session_tail,
        len(request.message or ""),
        request.thinking_enabled,
        request.search_enabled,
        request.auto_continue,
        len(request.file_ids or []),
    )

    session_lock = get_session_lock(request.session_id)
    client = get_session_qwen_api(request.session_id)

    def _run_for_session() -> dict[str, Any]:
        with session_lock:
            token = current_qwen_client.set(client)
            try:
                client.session_id = request.session_id
                return run_with_provider_slot(
                    "send_message",
                    lambda: send_message_sync_impl(
                        request,
                        config=config,
                        default_auto_continue=default_auto_continue,
                        reset_continuation_tracker=reset_continuation_tracker,
                        send_message_sync=send_message_sync,
                        continue_message_sync=continue_message_sync,
                        should_auto_continue=should_auto_continue,
                        can_auto_continue=can_auto_continue,
                        track_continuation=track_continuation,
                        logger=logger,
                    ),
                )
            finally:
                current_qwen_client.reset(token)

    try:
        result = await run_in_threadpool(_run_for_session)
        elapsed = time.monotonic() - started
        logger.info(
            "Qwen message finished: session=%s elapsed=%.2fs response_chars=%s thinking_chars=%s message_id=%s can_continue=%s",
            session_tail,
            elapsed,
            len(str(result.get("response") or "")),
            len(str(result.get("thinking") or "")),
            result.get("message_id") or result.get("last_message_id"),
            result.get("can_continue"),
        )
        if touch_active_session is not None:
            try:
                touch_active_session(request.session_id, source="message")
            except Exception:
                logger.warning("Cannot persist Qwen session last-used metadata: %s", session_tail)
        return result
    except Exception:
        elapsed = time.monotonic() - started
        logger.exception("Qwen message failed: session=%s elapsed=%.2fs", session_tail, elapsed)
        raise


def continue_message_sync_impl(
    request: Any,
    auto_continue: bool | None = None,
    *,
    config: dict[str, Any],
    default_auto_continue: bool,
    reset_continuation_tracker: Callable[[str], None],
    continuation_tracker: dict[str, Any],
    continue_message_sync: Callable[..., tuple[str, str, int, bool]],
    should_auto_continue: Callable[[str, bool], bool],
    can_auto_continue: Callable[[str], bool],
    track_continuation: Callable[[str, int], None],
    logger: LoggerLike = logging,
) -> dict[str, Any]:
    """Synchronous implementation of ``POST /messages/continue``.

    Caller is responsible for selecting the per-session Qwen client and holding
    the per-session lock.
    """
    try:
        do_auto_continue = auto_continue
        if do_auto_continue is None:
            do_auto_continue = config.get("auto_continue_enabled", default_auto_continue)

        if request.session_id not in continuation_tracker:
            reset_continuation_tracker(request.session_id)

        all_thinking_parts: list[str] = []
        all_response_parts: list[str] = []
        last_message_id = request.message_id
        continue_count = 0
        can_continue = True
        last_response_text = ""
        no_progress_streak = 0

        cont_thinking, cont_response, new_message_id, new_can_continue = continue_message_sync(
            session_id=request.session_id,
            message_id=last_message_id,
            thinking_enabled=request.thinking_enabled,
        )

        if cont_thinking:
            all_thinking_parts.append(cont_thinking)
        if cont_response:
            all_response_parts.append(cont_response)

        last_message_id = new_message_id
        last_response_text = cont_response or ""
        can_continue = new_can_continue
        continue_count = 1

        need_continue = bool(do_auto_continue) and should_auto_continue(last_response_text, can_continue)

        while need_continue and can_auto_continue(request.session_id):
            continue_count += 1
            track_continuation(request.session_id, last_message_id)

            logger.info(
                "Auto-continue #%s for session=%s, message_id=%s",
                continue_count,
                request.session_id[-6:],
                last_message_id,
            )

            cont_thinking, cont_response, new_message_id, new_can_continue = continue_message_sync(
                session_id=request.session_id,
                message_id=last_message_id,
                thinking_enabled=request.thinking_enabled,
            )

            if cont_thinking:
                all_thinking_parts.append(cont_thinking)
            if cont_response:
                all_response_parts.append(cont_response)

            if not (cont_response or "").strip() and new_message_id == last_message_id:
                no_progress_streak += 1
                logger.warning(
                    "Auto-continue stopped due to no progress: session=%s, message_id=%s, continue_count=%s",
                    request.session_id[-6:],
                    last_message_id,
                    continue_count,
                )
                if no_progress_streak >= 1:
                    can_continue = False
                    break
            else:
                no_progress_streak = 0

            last_message_id = new_message_id
            last_response_text = cont_response or last_response_text
            can_continue = new_can_continue
            need_continue = bool(do_auto_continue) and should_auto_continue(last_response_text, can_continue)

            logger.info(
                "Continue #%s done: new_message_id=%s, can_continue=%s, need_continue=%s",
                continue_count,
                new_message_id,
                can_continue,
                need_continue,
            )

        full_thinking = "\n\n".join(filter(None, all_thinking_parts))
        full_response = "\n\n".join(filter(None, all_response_parts))

        return {
            "session_id": request.session_id,
            "message_id": last_message_id,
            "response": full_response,
            "thinking": full_thinking,
            "auto_continue_performed": continue_count > 0,
            "continue_count": continue_count,
            "can_continue": can_continue,
            "last_message_id": last_message_id,
            "auto_continue_reason": "API flag" if can_continue else "content analysis" if continue_count > 1 else "none",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error continuing message: %s", exc)
        raise_provider_http_error(exc, operation="continue_message")


async def continue_message_payload(
    request: Any,
    auto_continue: bool | None = None,
    *,
    config: dict[str, Any],
    default_auto_continue: bool,
    get_session_lock: Callable[[str], Any],
    get_session_qwen_api: Callable[[str], Any],
    current_qwen_client: Any,
    reset_continuation_tracker: Callable[[str], None],
    continuation_tracker: dict[str, Any],
    continue_message_sync: Callable[..., tuple[str, str, int, bool]],
    should_auto_continue: Callable[[str, bool], bool],
    can_auto_continue: Callable[[str], bool],
    track_continuation: Callable[[str, int], None],
    touch_active_session: Callable[..., Any] | None = None,
    logger: LoggerLike = logging,
) -> dict[str, Any]:
    """Run ``POST /messages/continue`` under session lock."""
    session_lock = get_session_lock(request.session_id)
    client = get_session_qwen_api(request.session_id)

    def _run_for_session() -> dict[str, Any]:
        with session_lock:
            token = current_qwen_client.set(client)
            try:
                client.session_id = request.session_id
                return continue_message_sync_impl(
                    request,
                    auto_continue,
                    config=config,
                    default_auto_continue=default_auto_continue,
                    reset_continuation_tracker=reset_continuation_tracker,
                    continuation_tracker=continuation_tracker,
                    continue_message_sync=continue_message_sync,
                    should_auto_continue=should_auto_continue,
                    can_auto_continue=can_auto_continue,
                    track_continuation=track_continuation,
                    logger=logger,
                )
            finally:
                current_qwen_client.reset(token)

    result = await run_in_threadpool(_run_for_session)
    if touch_active_session is not None:
        try:
            touch_active_session(request.session_id, source="continue_message")
        except Exception:
            logger.warning("Cannot persist Qwen session continue metadata: %s", request.session_id[-8:])
    return result
