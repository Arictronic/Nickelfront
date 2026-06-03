"""Provider concurrency/throttling helpers for qwen_service.service.

The module is runtime-light: callers pass service state such as config,
semaphores and locks explicitly. This keeps Qwen transport/routes out of the
helper layer while making throttling/backoff logic testable in isolation.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any

LoggerLike = Any


def _bounded_int(value: Any, default: int, *, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def _bounded_float(value: Any, default: float, *, min_value: float, max_value: float) -> float:
    try:
        parsed = float(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def current_max_active_sessions(config: dict[str, Any], default: int) -> int:
    return _bounded_int(config.get("max_active_sessions"), default, min_value=1, max_value=500)


def current_provider_concurrency(config: dict[str, Any], default: int) -> int:
    return _bounded_int(config.get("provider_max_concurrent_requests"), default, min_value=1, max_value=50)


def current_provider_start_throttle_enabled(config: dict[str, Any], default: bool) -> bool:
    return bool(config.get("provider_start_throttle_enabled", default))


def current_provider_start_interval_sec(config: dict[str, Any], default: float) -> float:
    return _bounded_float(config.get("provider_start_interval_sec"), default, min_value=0.0, max_value=10.0)


def current_provider_start_jitter_sec(config: dict[str, Any], default: float) -> float:
    return _bounded_float(config.get("provider_start_jitter_sec"), default, min_value=0.0, max_value=10.0)


def current_provider_retry_jitter_enabled(config: dict[str, Any], default: bool) -> bool:
    return bool(config.get("provider_retry_jitter_enabled", default))


def current_provider_retry_jitter_bounds(
    config: dict[str, Any],
    *,
    default_min_sec: float,
    default_max_sec: float,
) -> tuple[float, float]:
    min_sec = _bounded_float(config.get("provider_retry_jitter_min_sec"), default_min_sec, min_value=0.0, max_value=30.0)
    max_sec = _bounded_float(config.get("provider_retry_jitter_max_sec"), default_max_sec, min_value=0.0, max_value=30.0)
    if max_sec < min_sec:
        max_sec = min_sec
    return min_sec, max_sec


def wait_provider_start_spacing(
    operation: str,
    *,
    config: dict[str, Any],
    default_enabled: bool,
    default_interval_sec: float,
    default_jitter_sec: float,
    start_lock: Any,
    next_start_at: float,
    logger: LoggerLike | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
    random_uniform: Callable[[float, float], float] = random.uniform,
) -> float:
    """Throttle provider request start time and return updated next-start timestamp."""
    if not operation:
        return next_start_at
    if not current_provider_start_throttle_enabled(config, default_enabled):
        return next_start_at

    interval = current_provider_start_interval_sec(config, default_interval_sec)
    jitter = current_provider_start_jitter_sec(config, default_jitter_sec)
    if interval <= 0 and jitter <= 0:
        return next_start_at

    with start_lock:
        now = monotonic_fn()
        start_at = max(now, next_start_at)
        wait_for = max(0.0, start_at - now)
        updated_next_start_at = start_at + interval + random_uniform(0.0, jitter)

    if wait_for > 0:
        if logger is not None:
            logger.info("Qwen provider start throttle: operation=%s wait=%.2fs", operation, wait_for)
        sleep_fn(wait_for)
    return updated_next_start_at


def provider_retry_backoff(
    base: float,
    *,
    config: dict[str, Any],
    default_enabled: bool,
    default_min_sec: float,
    default_max_sec: float,
    random_uniform: Callable[[float, float], float] = random.uniform,
) -> float:
    if not current_provider_retry_jitter_enabled(config, default_enabled):
        return base
    min_sec, max_sec = current_provider_retry_jitter_bounds(
        config,
        default_min_sec=default_min_sec,
        default_max_sec=default_max_sec,
    )
    if max_sec <= 0:
        return base
    return base + random_uniform(min_sec, max_sec)


def run_with_provider_slot(
    operation: str,
    fn: Callable[[], Any],
    *,
    semaphore: Any,
    timeout_sec: float,
    provider_error_cls: type[Exception],
) -> Any:
    acquired = semaphore.acquire(timeout=timeout_sec)
    if not acquired:
        raise provider_error_cls(f"Qwen provider queue timeout while waiting for {operation}")
    try:
        return fn()
    finally:
        semaphore.release()


def rate_limited_error(message: str | None) -> bool:
    value = str(message or "").lower()
    return "too many requests" in value or "rate limit" in value or "частот" in value
