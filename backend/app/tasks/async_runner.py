"""Shared async runner for Celery sync tasks.

Keeps one event loop per worker process to avoid cross-loop issues with async DB pools.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

T = TypeVar("T")

_worker_loop: asyncio.AbstractEventLoop | None = None


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop


def run_async(coro: Awaitable[T]) -> T:
    loop = _get_worker_loop()
    return loop.run_until_complete(coro)

