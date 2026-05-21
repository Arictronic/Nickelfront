"""Source execution layer for creating clients/parsers and running searches."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

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

def _apply_retry_config(client: Any, retry_config: RetryConfig) -> None:
    """Apply runtime retry settings to both old and new client implementations."""
    setattr(client, "_retry_config", retry_config)
    if hasattr(client, "MAX_RETRIES"):
        setattr(client, "MAX_RETRIES", retry_config.max_retries)
    if hasattr(client, "RETRY_BACKOFF_BASE"):
        setattr(client, "RETRY_BACKOFF_BASE", retry_config.backoff_base)
    if hasattr(client, "RETRY_BASE_DELAY"):
        setattr(client, "RETRY_BASE_DELAY", retry_config.base_delay)


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
        return raw, papers

    if source == "CORE":
        artifacts.client = COREClient(timeout=runtime_config.timeout)
        _apply_retry_config(artifacts.client, retry_config)
        artifacts.parser = COREParser()
        raw = await artifacts.client.search(query=query, limit=limit, full_text_only=False)
        papers = await _parse_with_parser(artifacts.parser, raw)
        return raw, papers

    if source == "CyberLeninka":
        artifacts.client = CyberLeninkaClient(timeout=runtime_config.timeout)
        _apply_retry_config(artifacts.client, retry_config)
        artifacts.parser = CyberLeninkaParser()
        raw = await artifacts.client.search(query=query, limit=limit)
        papers = await _parse_with_parser(artifacts.parser, raw)
        return raw, papers

    if source in AVAILABLE_EXTERNAL_SOURCES:
        client_cls = AVAILABLE_EXTERNAL_SOURCES[source]
        artifacts.client = client_cls(timeout=runtime_config.timeout)
        _apply_retry_config(artifacts.client, retry_config)
        artifacts.parser = ExternalParser(source=source)
        raw = await artifacts.client.search(query=query, limit=limit)
        papers = await _parse_with_parser(artifacts.parser, raw)
        return raw, papers

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
        diagnostics: dict[str, Any] = {}
        if artifacts.parser is not None and hasattr(artifacts.parser, "diagnostics"):
            parser_diagnostics = getattr(artifacts.parser, "diagnostics")
            if hasattr(parser_diagnostics, "as_dict"):
                diagnostics = parser_diagnostics.as_dict()

        raw_items = _coerce_raw_list(raw)
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
