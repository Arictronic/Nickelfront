"""Shared retry policy matrix for HTTP sources."""

from __future__ import annotations

import random
from dataclasses import dataclass

import httpx

from parsers_pkg.errors import (
    AuthenticationError,
    RateLimitedError,
    SourceError,
    SourceTimeoutError,
    SourceUnavailableError,
)


@dataclass(frozen=True)
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.5
    backoff_base: float = 2.0
    jitter_max: float = 0.7


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    delay_seconds: float = 0.0
    error: SourceError | None = None


def _exp_delay(config: RetryConfig, attempt: int) -> float:
    # attempt is 1-based.
    return config.base_delay * (config.backoff_base ** (attempt - 1)) + random.uniform(0.0, config.jitter_max)


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = float(value)
        return max(0.0, parsed)
    except (TypeError, ValueError):
        return None


def decide_for_status(
    *,
    source: str,
    status_code: int,
    attempt: int,
    config: RetryConfig,
    retry_after_header: str | None = None,
) -> RetryDecision:
    transient_statuses = {408, 500, 502, 503, 504}
    retry_after = _parse_retry_after(retry_after_header)

    if status_code == 429:
        if attempt < config.max_retries:
            return RetryDecision(retry=True, delay_seconds=max(retry_after or 0.0, _exp_delay(config, attempt)))
        return RetryDecision(
            retry=False,
            error=RateLimitedError(
                source=source,
                message=f"Rate limit (429) exhausted after {attempt} attempts",
            ),
        )

    if status_code in transient_statuses:
        if attempt < config.max_retries:
            return RetryDecision(retry=True, delay_seconds=_exp_delay(config, attempt))
        if status_code == 408:
            return RetryDecision(
                retry=False,
                error=SourceTimeoutError(source=source, message="Request timed out (HTTP 408)"),
            )
        return RetryDecision(
            retry=False,
            error=SourceUnavailableError(source=source, message=f"Upstream unavailable (HTTP {status_code})"),
        )

    if status_code in {401, 403}:
        return RetryDecision(
            retry=False,
            error=AuthenticationError(source=source, message=f"Access denied (HTTP {status_code})"),
        )

    if 400 <= status_code < 500:
        return RetryDecision(
            retry=False,
            error=SourceUnavailableError(source=source, message=f"Client error (HTTP {status_code})"),
        )

    return RetryDecision(retry=False)


def decide_for_exception(
    *,
    source: str,
    exc: Exception,
    attempt: int,
    config: RetryConfig,
) -> RetryDecision:
    if isinstance(exc, SourceError):
        return RetryDecision(retry=False, error=exc)

    if isinstance(exc, httpx.TimeoutException):
        if attempt < config.max_retries:
            return RetryDecision(retry=True, delay_seconds=_exp_delay(config, attempt))
        return RetryDecision(
            retry=False,
            error=SourceTimeoutError(source=source, message=f"Network timeout: {exc}"),
        )

    if isinstance(exc, httpx.NetworkError):
        if attempt < config.max_retries:
            return RetryDecision(retry=True, delay_seconds=_exp_delay(config, attempt))
        return RetryDecision(
            retry=False,
            error=SourceUnavailableError(source=source, message=f"Network error: {exc}"),
        )

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else 0
        return RetryDecision(
            retry=False,
            error=SourceUnavailableError(source=source, message=f"HTTP status error: {status}"),
        )

    if isinstance(exc, httpx.HTTPError):
        return RetryDecision(
            retry=False,
            error=SourceUnavailableError(source=source, message=f"HTTP error: {exc}"),
        )

    return RetryDecision(
        retry=False,
        error=SourceUnavailableError(source=source, message=f"Unhandled request failure: {exc}"),
    )

