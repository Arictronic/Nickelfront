"""Shared async runner for Celery sync tasks.

Celery tasks in Nickelfront are synchronous functions, while the backend services
use async SQLAlchemy/asyncpg. With ``pool=threads`` several Celery task threads
can call async code at the same time. Running ``loop.run_until_complete()`` from
those threads creates cross-loop failures with asyncpg.

This module keeps one dedicated asyncio loop thread per worker process and
submits all coroutines to that loop.
"""

from __future__ import annotations

import asyncio
import atexit
import threading
from collections.abc import Awaitable
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import TypeVar

T = TypeVar("T")

_worker_loop: asyncio.AbstractEventLoop | None = None
_worker_loop_thread: threading.Thread | None = None
_worker_loop_started: threading.Event | None = None
_worker_loop_lock = threading.Lock()


def _run_loop_forever(loop: asyncio.AbstractEventLoop, started: threading.Event) -> None:
    asyncio.set_event_loop(loop)
    started.set()
    loop.run_forever()


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    global _worker_loop, _worker_loop_thread, _worker_loop_started

    with _worker_loop_lock:
        if _worker_loop is not None and _worker_loop.is_running() and not _worker_loop.is_closed():
            return _worker_loop

        loop = asyncio.new_event_loop()
        started = threading.Event()
        thread = threading.Thread(
            target=_run_loop_forever,
            args=(loop, started),
            name="celery-asyncio-loop",
            daemon=True,
        )
        thread.start()
        started.wait(timeout=5.0)

        _worker_loop = loop
        _worker_loop_thread = thread
        _worker_loop_started = started
        return loop


def run_async(coro: Awaitable[T], timeout: float | None = None) -> T:
    """Run async code from a synchronous Celery task.

    Safe for Celery ``pool=threads`` because all async DB work is executed on one
    stable event loop per worker process.
    """
    loop = _get_worker_loop()

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop is loop:
        raise RuntimeError("run_async() cannot be called from the Celery async runner loop")

    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError:
        future.cancel()
        raise


def _stop_worker_loop() -> None:
    loop = _worker_loop
    if loop is not None and loop.is_running() and not loop.is_closed():
        loop.call_soon_threadsafe(loop.stop)


atexit.register(_stop_worker_loop)
