"""Source execution layer for creating clients/parsers and running searches."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any
from urllib.parse import urlparse

from parsers_pkg.base import RetryConfig
from parsers_pkg.arxiv.client import ArxivClient
from parsers_pkg.arxiv.parser import ArxivParser
from parsers_pkg.core.client import COREClient
from parsers_pkg.core.parser import COREParser
from parsers_pkg.errors import (
    MisconfigurationError,
    SourceError,
    SourceTimeoutError,
    SourceUnavailableError,
)
from parsers_pkg.external import AVAILABLE_EXTERNAL_SOURCES, ExternalParser
from parsers_pkg.russian import CyberLeninkaClient, CyberLeninkaParser
from parsers_pkg.source_config import SourceRuntimeConfig


@dataclass
class SourceExecutionResult:
    papers: list[Any]
    raw_count: int
    diagnostics: dict[str, Any]
    source_health: dict[str, Any]
    raw_samples: list[dict[str, Any]]


@dataclass
class SourceExecutionArtifacts:
    client: Any = None
    parser: Any = None


async def _close_resource(resource: Any) -> None:
    if resource is None or not hasattr(resource, "close"):
        return

    close_fn = getattr(resource, "close")
    if asyncio.iscoroutinefunction(close_fn):
        await close_fn()
        return

    result = close_fn()
    if asyncio.iscoroutine(result):
        await result




def _safe_event_dicts(diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    events = diagnostics.get("events", []) if isinstance(diagnostics, dict) else []
    if not isinstance(events, list):
        return []
    return [item for item in events if isinstance(item, dict)]


def _coerce_raw_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, tuple):
        return list(raw)
    return [raw]




def _coerce_raw_records(raw: Any) -> list[dict[str, Any]]:
    """Return only dict records safe to feed into parser implementations.

    Some clients or tests may drift from the expected list[dict] contract and
    return a single object, tuple, None, or even a scalar error payload.  Feeding
    those values directly into parser loops can make the whole source fail on
    ``item.get`` or iterate dictionary keys instead of records.
    """
    return [item for item in _coerce_raw_list(raw) if isinstance(item, dict)]


async def _parse_with_parser(parser: Any, raw: Any) -> list[Any]:
    return await parser.parse_search_results(_coerce_raw_records(raw))


def _looks_like_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _looks_like_pdf_url(value: Any) -> bool:
    if not _looks_like_http_url(value):
        return False
    parsed = urlparse(str(value))
    path = parsed.path.lower()
    query = parsed.query.lower()
    return (
        path.endswith(".pdf")
        or path.endswith("/pdf")
        or "/pdf/" in path
        or "pdf=render" in query
        or "format=pdf" in query
        or "download=pdf" in query
    )


def _add_quality_flag(paper: Any, flag: str) -> None:
    flags = getattr(paper, "quality_flags", None)
    if not isinstance(flags, list):
        flags = []
        setattr(paper, "quality_flags", flags)
    if flag not in flags:
        flags.append(flag)


def _set_provenance(paper: Any, field_name: str, origin: str) -> None:
    provenance = getattr(paper, "provenance", None)
    if not isinstance(provenance, dict):
        provenance = {}
    provenance[field_name] = origin
    paper.provenance = provenance


def _add_metadata_quality_flags(paper: Any) -> None:
    for field_name, flag in (
        ("authors", "metadata_missing_authors"),
        ("publication_date", "metadata_missing_publication_date"),
        ("abstract", "metadata_missing_abstract"),
        ("source_id", "metadata_missing_source_id"),
    ):
        if getattr(paper, field_name, None) in (None, "", [], {}):
            _add_quality_flag(paper, flag)


def _set_default_parse_confidence(paper: Any) -> None:
    if getattr(paper, "parse_confidence", None) is not None:
        return
    signals = (
        bool(getattr(paper, "title", None) and paper.title != "Untitled"),
        bool(getattr(paper, "authors", None)),
        bool(getattr(paper, "publication_date", None)),
        bool(getattr(paper, "abstract", None)),
        bool(getattr(paper, "source_id", None)),
        bool(getattr(paper, "url", None)),
        bool(getattr(paper, "pdf_url", None) or getattr(paper, "full_text", None)),
    )
    paper.parse_confidence = round(sum(signals) / len(signals), 3)


async def _enrich_content_access(
    client: Any,
    papers: list[Any],
    max_results: int | None = None,
    diagnostics: Any = None,
) -> list[Any]:
    """Add same-source content when available while preserving searchable metadata."""
    enriched: list[Any] = []
    enrich_text_with_pdf = bool(getattr(client, "ENRICH_FULL_TEXT_WITH_PDF", False))
    for paper in papers:
        pdf_url = getattr(paper, "pdf_url", None)
        full_text = str(getattr(paper, "full_text", None) or "").strip()
        content_available = False

        if _looks_like_http_url(pdf_url):
            if _looks_like_pdf_url(pdf_url):
                _add_quality_flag(paper, "pdf_url_available")
                content_available = True
            else:
                verifier = getattr(client, "verify_pdf_url", None)
                verified_url = None
                if callable(verifier):
                    try:
                        verified_url = await verifier(pdf_url)
                    except Exception:
                        verified_url = None
                if _looks_like_http_url(verified_url):
                    paper.pdf_url = verified_url
                    _set_provenance(paper, "pdf_url", f"{paper.source}:verified")
                    _add_quality_flag(paper, "pdf_url_verified")
                    content_available = True
                else:
                    paper.pdf_url = None
                    _add_quality_flag(paper, "pdf_url_unverified")
                    if diagnostics is not None and hasattr(diagnostics, "add"):
                        diagnostics.add(
                            stage="content_access",
                            reason="pdf_url_unverified",
                            severity="info",
                            record_id=getattr(paper, "source_id", None),
                            details={"url": str(pdf_url)},
                        )
        if full_text:
            _add_quality_flag(paper, "full_text_available")
            content_available = True

        resolver = getattr(client, "get_full_text", None)
        source_id = getattr(paper, "source_id", None)
        article_url = getattr(paper, "url", None)
        locator = source_id or article_url
        candidate = None
        should_resolve = not full_text and (not content_available or enrich_text_with_pdf)
        if locator and callable(resolver) and should_resolve:
            try:
                candidate = await resolver(locator)
            except Exception:
                candidate = None

        if _looks_like_pdf_url(candidate):
            if not content_available:
                paper.pdf_url = candidate
                _set_provenance(paper, "pdf_url", f"{paper.source}:detail")
                _add_quality_flag(paper, "pdf_url_resolved_from_detail")
            content_available = True
        elif isinstance(candidate, str) and not _looks_like_http_url(candidate) and len(candidate.strip()) >= 200:
            paper.full_text = candidate.strip()
            _set_provenance(paper, "full_text", f"{paper.source}:detail")
            _add_quality_flag(paper, "full_text_extracted_from_detail")
            content_available = True
        if not content_available:
            _add_quality_flag(paper, "content_access_unresolved")
            if diagnostics is not None and hasattr(diagnostics, "add"):
                diagnostics.add(
                    stage="content_access",
                    reason="content_access_unresolved",
                    severity="info",
                    record_id=getattr(paper, "source_id", None),
                )
        _add_metadata_quality_flags(paper)
        _set_default_parse_confidence(paper)
        enriched.append(paper)
        if max_results and len(enriched) >= max_results:
            break

    return enriched


def _apply_retry_config(client: Any, retry_config: RetryConfig) -> None:
    """Apply runtime retry settings to both old and new client implementations."""
    setattr(client, "_retry_config", retry_config)
    if hasattr(client, "MAX_RETRIES"):
        setattr(client, "MAX_RETRIES", retry_config.max_retries)
    if hasattr(client, "RETRY_BACKOFF_BASE"):
        setattr(client, "RETRY_BACKOFF_BASE", retry_config.backoff_base)
    if hasattr(client, "RETRY_BASE_DELAY"):
        setattr(client, "RETRY_BASE_DELAY", retry_config.base_delay)


def _quality_candidate_limit(source: str, requested_limit: int) -> int:
    """Metadata-first parsing does not need an oversized PDF candidate pool."""
    return requested_limit


async def _execute_source(
    source: str,
    query: str,
    limit: int,
    runtime_config: SourceRuntimeConfig,
    artifacts: SourceExecutionArtifacts,
) -> tuple[list[dict[str, Any]], list[Any]]:
    retry_config = RetryConfig(
        max_retries=runtime_config.max_retries,
        base_delay=runtime_config.retry_base_delay,
        backoff_base=runtime_config.retry_backoff_base,
        jitter_max=runtime_config.retry_jitter_max,
    )

    if source == "arXiv":
        artifacts.client = ArxivClient(timeout=runtime_config.timeout, rate_limit=True)
        _apply_retry_config(artifacts.client, retry_config)
        artifacts.parser = ArxivParser()
        raw = await artifacts.client.search(query=query, limit=limit)
        papers = await _parse_with_parser(artifacts.parser, raw)
        papers = await _enrich_content_access(
            artifacts.client, papers, max_results=limit, diagnostics=artifacts.parser.diagnostics
        )
        return raw, papers

    if source == "CORE":
        artifacts.client = COREClient(timeout=runtime_config.timeout)
        _apply_retry_config(artifacts.client, retry_config)
        artifacts.parser = COREParser()
        raw = await artifacts.client.search(query=query, limit=limit, full_text_only=False)
        papers = await _parse_with_parser(artifacts.parser, raw)
        papers = await _enrich_content_access(
            artifacts.client, papers, max_results=limit, diagnostics=artifacts.parser.diagnostics
        )
        return raw, papers

    if source == "CyberLeninka":
        artifacts.client = CyberLeninkaClient(timeout=runtime_config.timeout)
        _apply_retry_config(artifacts.client, retry_config)
        artifacts.parser = CyberLeninkaParser()
        raw = await artifacts.client.search(query=query, limit=limit)
        papers = await _parse_with_parser(artifacts.parser, raw)
        papers = await _enrich_content_access(
            artifacts.client, papers, max_results=limit, diagnostics=artifacts.parser.diagnostics
        )
        return raw, papers

    if source in AVAILABLE_EXTERNAL_SOURCES:
        client_cls = AVAILABLE_EXTERNAL_SOURCES[source]
        artifacts.client = client_cls(timeout=runtime_config.timeout)
        _apply_retry_config(artifacts.client, retry_config)
        artifacts.parser = ExternalParser(source=source)
        raw = await artifacts.client.search(query=query, limit=_quality_candidate_limit(source, limit))
        papers = await _parse_with_parser(artifacts.parser, raw)
        papers = await _enrich_content_access(
            artifacts.client, papers, max_results=limit, diagnostics=artifacts.parser.diagnostics
        )
        return raw, papers[:limit]

    raise MisconfigurationError(
        source=source,
        message=f"No parser binding configured for source '{source}'",
    )


async def execute_source_search(
    source: str,
    query: str,
    limit: int,
    runtime_config: SourceRuntimeConfig,
    sample_limit: int = 5,
) -> SourceExecutionResult:
    artifacts = SourceExecutionArtifacts()
    started_at = monotonic()
    try:
        try:
            raw, papers = await _execute_source(
                source=source,
                query=query,
                limit=limit,
                runtime_config=runtime_config,
                artifacts=artifacts,
            )
        except asyncio.TimeoutError as exc:
            raise SourceTimeoutError(source=source, message=str(exc) or "Operation timed out") from exc
        except SourceError:
            raise
        except Exception as exc:
            raise SourceUnavailableError(source=source, message=str(exc)) from exc
        raw_items = _coerce_raw_list(raw)
        elapsed_seconds = monotonic() - started_at
        if (
            not raw_items
            and elapsed_seconds >= max(10.0, runtime_config.timeout)
            and artifacts.parser is not None
            and hasattr(artifacts.parser, "diagnostics")
        ):
            parser_diagnostics = getattr(artifacts.parser, "diagnostics")
            if hasattr(parser_diagnostics, "add"):
                parser_diagnostics.add(
                    stage="fetch",
                    reason="slow_empty_response",
                    severity="warning",
                    details={"duration_seconds": round(elapsed_seconds, 3)},
                )
        if raw_items and not papers and artifacts.parser is not None and hasattr(artifacts.parser, "diagnostics"):
            parser_diagnostics = getattr(artifacts.parser, "diagnostics")
            if hasattr(parser_diagnostics, "add"):
                parser_diagnostics.add(
                    stage="parse",
                    reason="no_normalized_records",
                    severity="warning",
                    details={"raw_count": len(raw_items)},
                )
        if artifacts.parser is not None and hasattr(artifacts.parser, "validate_paper"):
            valid_papers: list[Any] = []
            for paper in papers:
                valid, _ = artifacts.parser.validate_paper(paper)
                if valid:
                    valid_papers.append(paper)
            papers = valid_papers

        diagnostics: dict[str, Any] = {}
        if artifacts.parser is not None and hasattr(artifacts.parser, "diagnostics"):
            parser_diagnostics = getattr(artifacts.parser, "diagnostics")
            if hasattr(parser_diagnostics, "as_dict"):
                diagnostics = parser_diagnostics.as_dict()

        diagnostic_events = _safe_event_dicts(diagnostics)
        raw_count = len(raw_items)
        parsed_count = len(papers)
        source_health = {
            "success_rate": round((parsed_count / raw_count), 3) if raw_count else 0.0,
            "empty_result_rate": 1.0 if raw_count == 0 else 0.0,
            "parse_error_rate": round(
                (
                    sum(
                        1
                        for item in diagnostic_events
                        if item.get("stage") == "parse" and item.get("severity") == "error"
                    )
                    / max(1, raw_count)
                ),
                3,
            ),
            "drift_detected_count": sum(
                1
                for item in diagnostic_events
                if "drift" in str(item.get("reason", "")).lower()
            ),
            "warnings_count": sum(
                1
                for item in diagnostic_events
                if item.get("severity") == "warning"
            ),
            "degraded": bool(diagnostics.get("degraded", False)),
        }

        return SourceExecutionResult(
            papers=papers,
            raw_count=raw_count,
            diagnostics=diagnostics,
            source_health=source_health,
            raw_samples=[item for item in raw_items[: max(1, sample_limit)] if isinstance(item, dict)],
        )
    finally:
        await _close_resource(artifacts.parser)
        await _close_resource(artifacts.client)
