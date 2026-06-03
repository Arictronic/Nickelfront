"""Runtime helpers for QwenAPI client creation and locked calls.

This module intentionally stays transport-agnostic: it does not know about
FastAPI routes, upload protocol, HAR refresh or service endpoints. It only
wraps QwenAPI object creation/proxying and lock-safe calls used by
qwen_service.service.
"""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any

from fastapi.concurrency import run_in_threadpool


def new_qwen_api(
    *,
    config: dict[str, Any],
    qwen_api_cls: type[Any],
    default_user_agent: str,
    default_model: str,
    logger_fn: Callable[[str], None],
) -> Any | None:
    """Create a QwenAPI client from runtime config, or None if token is empty."""
    token = str(config.get("token", "") or "").strip()
    if not token:
        return None
    return qwen_api_cls(
        token=token,
        logger=logger_fn,
        user_agent=str(config.get("user_agent", default_user_agent) or default_user_agent or "").strip() or None,
        default_model=str(config.get("model", default_model)),
    )


def ensure_control_qwen_api(
    current_client: Any | None,
    *,
    config: dict[str, Any],
    client_factory: Callable[[], Any | None],
) -> Any | None:
    """Return the control QwenAPI client, creating it lazily when token exists."""
    if current_client is None and str(config.get("token", "") or "").strip():
        return client_factory()
    return current_client


class QwenApiProxy:
    """Compatibility proxy for code that references a global qwen_api object."""

    def __init__(self, target_factory: Callable[[], Any | None], provider_error_cls: type[Exception]) -> None:
        object.__setattr__(self, "_target_factory", target_factory)
        object.__setattr__(self, "_provider_error_cls", provider_error_cls)

    def _target(self) -> Any:
        client = self._target_factory()
        if client is None:
            raise self._provider_error_cls("Qwen API is not initialized")
        return client

    def __bool__(self) -> bool:
        return self._target_factory() is not None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._target(), name, value)


def call_qwen_locked(lock: RLock, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a Qwen control/list/config operation under a small control lock."""
    with lock:
        return fn(*args, **kwargs)


async def run_qwen_locked(lock: RLock, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a locked Qwen operation without blocking the FastAPI event loop."""
    return await run_in_threadpool(call_qwen_locked, lock, fn, *args, **kwargs)
