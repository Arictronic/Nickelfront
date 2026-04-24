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
        artifacts.client._retry_config = retry_config
        artifacts.parser = ArxivParser()
        raw = await artifacts.client.search(query=query, limit=limit)
        papers = await artifacts.parser.parse_search_results(raw)
        return raw, papers

    if source == "CORE":
        artifacts.client = COREClient(timeout=runtime_config.timeout)
        artifacts.client._retry_config = retry_config
        artifacts.parser = COREParser()
        raw = await artifacts.client.search(query=query, limit=limit, full_text_only=False)
        papers = await artifacts.parser.parse_search_results(raw)
        return raw, papers

    if source == "CyberLeninka":
        artifacts.client = CyberLeninkaClient(timeout=runtime_config.timeout)
        artifacts.client._retry_config = retry_config
        artifacts.parser = CyberLeninkaParser()
        raw = await artifacts.client.search(query=query, limit=limit)
        papers = await artifacts.parser.parse_search_results(raw)
        return raw, papers

    if source in AVAILABLE_EXTERNAL_SOURCES:
        client_cls = AVAILABLE_EXTERNAL_SOURCES[source]
        artifacts.client = client_cls(timeout=runtime_config.timeout)
        artifacts.client._retry_config = retry_config
        artifacts.parser = ExternalParser(source=source)
        raw = await artifacts.client.search(query=query, limit=limit)
        papers = await artifacts.parser.parse_search_results(raw)
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

        raw_count = len(raw)
        parsed_count = len(papers)
        source_health = {
            "success_rate": round((parsed_count / raw_count), 3) if raw_count else 0.0,
            "empty_result_rate": 1.0 if raw_count == 0 else 0.0,
            "parse_error_rate": round(
                (
                    sum(
                        1
                        for item in diagnostics.get("events", [])
                        if item.get("stage") == "parse" and item.get("severity") == "error"
                    )
                    / max(1, raw_count)
                ),
                3,
            ),
            "drift_detected_count": sum(
                1
                for item in diagnostics.get("events", [])
                if "drift" in str(item.get("reason", "")).lower()
            ),
            "warnings_count": sum(
                1
                for item in diagnostics.get("events", [])
                if item.get("severity") == "warning"
            ),
            "degraded": bool(diagnostics.get("degraded", False)),
        }

        return SourceExecutionResult(
            papers=papers,
            raw_count=raw_count,
            diagnostics=diagnostics,
            source_health=source_health,
            raw_samples=raw[: max(1, sample_limit)],
        )
    finally:
        await _close_resource(artifacts.parser)
        await _close_resource(artifacts.client)
