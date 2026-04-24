"""
Base module for parsers.

Modules:
- base_client: Base class for API clients
- base_parser: Base class for parsers
- scraper_client: Base class for scraper HTTP clients
- deduplication: Deduplication and merge service
"""

from .base_client import BaseAPIClient
from .base_parser import BaseParser
from .deduplication import DeduplicationResult, Deduplicator, MergedRecord, check_duplicate
from .normalization import (
    clean_text,
    derive_article_url,
    iso_utc,
    normalize_authors,
    normalize_datetime,
    normalize_doi,
    normalize_url,
)
from .retry_policy import RetryConfig, RetryDecision, decide_for_exception, decide_for_status
from .scraper_client import BaseScraperClient
from .validation import ValidationIssue, split_issues, validate_paper_fields

__all__ = [
    "BaseAPIClient",
    "BaseParser",
    "BaseScraperClient",
    "RetryConfig",
    "RetryDecision",
    "decide_for_status",
    "decide_for_exception",
    "Deduplicator",
    "DeduplicationResult",
    "MergedRecord",
    "check_duplicate",
    "clean_text",
    "derive_article_url",
    "normalize_authors",
    "normalize_datetime",
    "normalize_url",
    "normalize_doi",
    "iso_utc",
    "ValidationIssue",
    "validate_paper_fields",
    "split_issues",
]
