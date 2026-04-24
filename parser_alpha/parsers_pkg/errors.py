"""Typed source-level errors for parser orchestration."""

from __future__ import annotations


class SourceError(Exception):
    """Base error for source-related failures."""

    def __init__(self, source: str, message: str):
        self.source = source
        self.message = message
        super().__init__(f"[{source}] {message}")


class SourceUnavailableError(SourceError):
    """Source is temporarily unavailable or returned an unrecoverable response."""


class RateLimitedError(SourceError):
    """Source rejected request because of rate limits."""


class AuthenticationError(SourceError):
    """Source requires authentication or credentials are invalid."""


class ParsingError(SourceError):
    """Raw payload was received but could not be parsed into schema."""


class SchemaChangedError(SourceError):
    """Source response shape changed and parsing contract is outdated."""


class AntiBotBlockedError(SourceError):
    """Source blocked request with anti-bot or challenge page."""


class SourceTimeoutError(SourceError):
    """Source did not respond within timeout budget."""


class EmptyResultError(SourceError):
    """Source returned no results for a query."""


class MisconfigurationError(SourceError):
    """Local parser/source configuration is invalid."""

