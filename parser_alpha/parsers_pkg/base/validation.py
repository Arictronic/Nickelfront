from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from parsers_pkg.base.normalization import normalize_datetime, normalize_doi, normalize_url
from shared.schemas.paper import Paper

ValidationSeverity = Literal["soft", "hard"]


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    code: str
    message: str
    severity: ValidationSeverity


def validate_paper_fields(paper: Paper, source: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if not paper.title or not paper.title.strip():
        issues.append(ValidationIssue(field="title", code="missing_title", message="Missing title", severity="hard"))

    if not paper.source:
        issues.append(ValidationIssue(field="source", code="missing_source", message="Missing source", severity="hard"))

    if not paper.url:
        issues.append(
            ValidationIssue(
                field="url",
                code="missing_article_url",
                message="Missing article URL",
                severity="hard",
            )
        )

    if paper.doi and normalize_doi(paper.doi) is None:
        issues.append(
            ValidationIssue(
                field="doi",
                code="invalid_doi",
                message=f"Invalid DOI format: {paper.doi}",
                severity="soft",
            )
        )

    if paper.url and normalize_url(paper.url) is None:
        issues.append(
            ValidationIssue(
                field="url",
                code="invalid_url",
                message=f"Invalid URL format: {paper.url}",
                severity="soft",
            )
        )

    if paper.publication_date:
        parsed = normalize_datetime(paper.publication_date)
        if parsed is None:
            issues.append(
                ValidationIssue(
                    field="publication_date",
                    code="invalid_date",
                    message=f"Invalid publication date: {paper.publication_date}",
                    severity="soft",
                )
            )
        elif isinstance(parsed, datetime) and parsed.year < 1800:
            issues.append(
                ValidationIssue(
                    field="publication_date",
                    code="date_out_of_range",
                    message=f"Publication date year is suspicious: {parsed.year}",
                    severity="soft",
                )
            )

    return issues


def split_issues(issues: list[ValidationIssue]) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
    hard = [issue for issue in issues if issue.severity == "hard"]
    soft = [issue for issue in issues if issue.severity == "soft"]
    return hard, soft
