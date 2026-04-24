"""Base parser abstractions and shared normalization/validation helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from parsers_pkg.base.normalization import (
    clean_text,
    derive_article_url,
    normalize_authors,
    normalize_datetime,
    normalize_doi,
    normalize_url,
)
from parsers_pkg.base.validation import split_issues, validate_paper_fields
from parsers_pkg.contracts import ParserDiagnostics
from shared.schemas.paper import Paper


class BaseParser(ABC):
    """Base class for parser implementations."""

    def __init__(self, source: str = "unknown"):
        self.source = source
        self.diagnostics = ParserDiagnostics(source=source)

    def reset_diagnostics(self) -> None:
        self.diagnostics = ParserDiagnostics(source=self.source)

    @abstractmethod
    async def parse_search_results(self, data: list[dict[str, Any]]) -> list[Paper]:
        """Parse source-specific search payload into normalized papers."""
        raise NotImplementedError

    async def parse_full_text(self, text: str, metadata: dict[str, Any]) -> Paper:
        """Default full text parser for sources that only return text blobs."""
        return self.normalize_paper(
            Paper(
                title=metadata.get("title", "Untitled"),
                authors=metadata.get("authors", []),
                publication_date=metadata.get("publication_date"),
                journal=metadata.get("journal"),
                doi=metadata.get("doi"),
                abstract=metadata.get("abstract"),
                full_text=text,
                keywords=metadata.get("keywords", []),
                source=metadata.get("source", self.source),
                source_id=metadata.get("source_id"),
                url=metadata.get("url"),
                parse_confidence=metadata.get("parse_confidence"),
                provenance=metadata.get("provenance", {}),
                quality_flags=metadata.get("quality_flags", []),
            )
        )

    async def extract_keywords(self, paper: Paper) -> list[str]:
        return paper.keywords or []

    def normalize_paper(self, paper: Paper) -> Paper:
        paper.title = clean_text(paper.title) or "Untitled"
        paper.authors = normalize_authors(paper.authors)
        paper.abstract = clean_text(paper.abstract)
        paper.full_text = clean_text(paper.full_text)
        paper.keywords = normalize_authors(paper.keywords)
        paper.journal = clean_text(paper.journal)
        paper.source = clean_text(paper.source) or self.source
        paper.source_id = clean_text(paper.source_id)
        paper.url = derive_article_url(
            source=paper.source,
            url=paper.url,
            doi=paper.doi,
            source_id=paper.source_id,
        )
        paper.url = normalize_url(paper.url)
        paper.doi = normalize_doi(paper.doi)
        paper.publication_date = normalize_datetime(paper.publication_date)

        if paper.schema_version is None:
            paper.schema_version = "2.0"

        return paper

    def _clean_text(self, text: str | None) -> str:
        return clean_text(text) or ""

    def validate_paper(self, paper: Paper) -> tuple[bool, list[str]]:
        issues = validate_paper_fields(paper, source=self.source)
        hard, soft = split_issues(issues)

        for issue in soft:
            self.diagnostics.add(
                stage="validation",
                reason=issue.code,
                severity="warning",
                record_id=paper.source_id,
                details={"field": issue.field, "message": issue.message},
            )

        for issue in hard:
            self.diagnostics.add(
                stage="validation",
                reason=issue.code,
                severity="error",
                record_id=paper.source_id,
                details={"field": issue.field, "message": issue.message},
            )

        return len(hard) == 0, [issue.message for issue in issues]
