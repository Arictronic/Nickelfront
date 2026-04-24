from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from parsers_pkg.base import Deduplicator, derive_article_url, normalize_url
from parsers_pkg.errors import MisconfigurationError, SourceError
from parsers_pkg.source_config import SourceRuntimeConfig, load_source_runtime_config_with_metadata
from parsers_pkg.source_executor import execute_source_search
from parsers_pkg.source_routing import RoutedSource, SourceHealthStore, SourceRunTelemetry, resolve_route
from parsers_pkg.sources import SourceMetadata, build_default_source_registry
from parsers_pkg.translate import get_shared_query_translator

logger = logging.getLogger(__name__)

SOURCE_REGISTRY = build_default_source_registry()
FALLBACK_ENABLED = False


def _contains_non_ascii(text: str) -> bool:
    return any(ord(ch) > 127 for ch in text)


def _translate_query_for_fallback(query: str) -> tuple[str | None, str]:
    translator = get_shared_query_translator()
    result = translator.translate(query, target_lang="en", source_lang="auto")
    if result.translated and result.translated_text != query:
        return result.translated_text, f"translation_fallback:{result.used_engine}"
    return None, f"translation_fallback_skipped:{result.reason}"


def _paper_to_dict(paper: Any) -> dict[str, Any]:
    if hasattr(paper, "model_dump"):
        return paper.model_dump(mode="json")
    if hasattr(paper, "dict"):
        return paper.dict()
    return dict(paper)


@dataclass(frozen=True)
class ParseAttemptResult:
    source: str
    adapted_query: str
    route_reason: str
    parsed_count: int
    raw_count: int
    duration_seconds: float
    diagnostics: dict[str, Any]
    source_health: dict[str, Any]
    raw_samples: list[dict[str, Any]]
    error: str | None = None


@dataclass(frozen=True)
class ParseRunResult:
    out_path: Path
    parsed_count: int
    raw_count: int
    duration_seconds: float
    diagnostics: dict[str, Any]
    source_health: dict[str, Any]
    attempts: list[ParseAttemptResult]
    info_summary: dict[str, Any]


def _route_mode(source: str) -> str:
    requested = source.strip()
    if requested.lower() == "auto":
        return "auto_single"
    if "," in requested:
        return "explicit_order_single"
    return "single"


def _classify_attempt_status(attempt: ParseAttemptResult) -> str:
    if attempt.error:
        msg = attempt.error.lower()
        if "api key" in msg and ("missing" in msg or "required" in msg):
            return "api_key_required"
        if "429" in msg or "rate limit" in msg:
            return "rate_limited"
        if "timeout" in msg or "timed out" in msg or "503" in msg or "unavailable" in msg or "no response" in msg:
            return "server_no_response"
        if "playwright_not_installed" in msg or "selenium_not_installed" in msg or "webdriver_manager_not_installed" in msg:
            return "dependency_missing"
        return "failed"

    degraded = bool(attempt.source_health.get("degraded", False))
    reasons = [str(item).lower() for item in attempt.diagnostics.get("degraded_reasons", [])]
    if any("api" in reason and "key" in reason for reason in reasons):
        return "api_key_required"
    if any("rate" in reason for reason in reasons):
        return "rate_limited"
    if any("timeout" in reason or "unavailable" in reason or "server" in reason for reason in reasons):
        return "server_no_response"
    if attempt.parsed_count > 0:
        return "worked_with_warnings" if degraded else "worked"
    if attempt.raw_count > 0:
        return "parsed_zero"
    return "no_data"


def _source_matches_attempt(record_source: str | None, attempt_source: str) -> bool:
    if not record_source:
        return False
    normalized_record = record_source.strip().lower()
    normalized_attempt = attempt_source.strip().lower()
    if normalized_record == normalized_attempt:
        return True
    return False


def _collect_runtime_validation_issues(
    source: str,
    source_meta: SourceMetadata,
    runtime_config: SourceRuntimeConfig,
) -> list[str]:
    issues: list[str] = []
    if runtime_config.timeout <= 0:
        issues.append("timeout_must_be_positive")
    if runtime_config.max_retries < 1:
        issues.append("max_retries_must_be_at_least_1")
    if runtime_config.retry_base_delay <= 0:
        issues.append("retry_base_delay_must_be_positive")
    if runtime_config.retry_backoff_base <= 1:
        issues.append("retry_backoff_base_must_be_greater_than_1")
    if runtime_config.retry_jitter_max < 0:
        issues.append("retry_jitter_max_must_be_non_negative")

    if source_meta.requires_browser and runtime_config.browser_enabled:
        if importlib.util.find_spec("playwright") is None and importlib.util.find_spec("selenium") is None:
            issues.append("browser_automation_dependency_missing")

    if runtime_config.require_api_key and not source_meta.api_key_env:
        issues.append("require_api_key_enabled_but_source_has_no_api_key_env")

    return issues


def _ensure_valid_runtime_configuration(
    source: str,
    source_meta: SourceMetadata,
    runtime_config: SourceRuntimeConfig,
) -> None:
    issues = _collect_runtime_validation_issues(source, source_meta, runtime_config)
    if issues:
        raise MisconfigurationError(
            source=source,
            message=f"Runtime config validation failed: {', '.join(issues)}",
        )


def _check_source_allowed(
    *,
    source: str,
    source_meta: SourceMetadata,
    runtime_config: SourceRuntimeConfig,
    disable_fragile_sources: bool,
    api_only: bool,
) -> None:
    if not runtime_config.enabled:
        raise MisconfigurationError(source=source, message="Source disabled by runtime config")
    if disable_fragile_sources and source_meta.is_fragile:
        raise MisconfigurationError(
            source=source,
            message="Source is marked as fragile and disabled by --disable-fragile-sources",
        )
    if api_only and source_meta.source_type != "api":
        raise MisconfigurationError(
            source=source,
            message="Source is not API-backed and disabled by --api-only",
        )
    if source_meta.requires_browser and not runtime_config.browser_enabled:
        raise MisconfigurationError(
            source=source,
            message="Source requires browser automation but browser is disabled in runtime config",
        )

    expected_api_env = source_meta.api_key_env
    if runtime_config.require_api_key and expected_api_env and not os.getenv(expected_api_env):
        raise MisconfigurationError(
            source=source,
            message=f"Required API key is missing: set env {expected_api_env}",
        )


def _merge_records_by_dedupe(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    deduplicator = Deduplicator([])
    merged: list[dict[str, Any]] = []

    for record in records:
        is_duplicate, _ = deduplicator.is_duplicate(record)
        if not is_duplicate:
            deduplicator.add_paper(record)
            merged.append(record)
        else:
            existing = next(
                (
                    item
                    for item in deduplicator.existing_papers
                    if (item.get("doi") and item.get("doi") == record.get("doi"))
                    or (item.get("source_id") and item.get("source_id") == record.get("source_id"))
                ),
                None,
            )
            if existing is not None:
                merged_record = deduplicator.merge_records(record, existing)
                existing.update(merged_record.record)
                existing["provenance"] = merged_record.provenance
                existing["parse_confidence"] = merged_record.confidence

        if len(merged) >= limit:
            break

    return merged[:limit]


def _resolve_doi_redirect(url: str, timeout_seconds: float = 10.0) -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host not in {"doi.org", "dx.doi.org"}:
        return url

    try:
        with httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "NickelfrontParser/1.0 DOI-Resolver"},
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            resolved = str(response.url)
            return normalize_url(resolved) or url
    except Exception:
        return url


def _is_probable_pdf_url(url: str | None) -> bool:
    normalized = normalize_url(url)
    if not normalized:
        return False
    parsed = urlparse(normalized)
    path = (parsed.path or "").lower()
    query = (parsed.query or "").lower()
    if path.endswith(".pdf"):
        return True
    if "pdf=render" in query or "format=pdf" in query or "download=pdf" in query:
        return True
    return False


def _strip_pdf_query(url: str | None) -> str | None:
    normalized = normalize_url(url)
    if not normalized:
        return None
    if not _is_probable_pdf_url(normalized):
        return normalized
    parsed = urlparse(normalized)
    path = parsed.path or ""
    if path.lower().endswith(".pdf"):
        return None
    return normalize_url(f"{parsed.scheme}://{parsed.netloc}{path}")


def _select_article_url(
    *,
    source: str,
    source_id: str | None,
    doi: str | None,
    original_url: str | None,
    resolved_url: str | None,
) -> str | None:
    candidates = [
        _strip_pdf_query(resolved_url),
        _strip_pdf_query(original_url),
        normalize_url(original_url),
        derive_article_url(source=source, url=None, doi=doi, source_id=source_id),
    ]
    for candidate in candidates:
        normalized = normalize_url(candidate)
        if normalized and not _is_probable_pdf_url(normalized):
            return normalized
    return None


def _enforce_article_url(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int, int]:
    normalized: list[dict[str, Any]] = []
    dropped = 0
    doi_resolved_count = 0
    pdf_promoted_count = 0

    for record in records:
        source = str(record.get("source") or "")
        source_id = record.get("source_id")
        doi = record.get("doi")
        url = derive_article_url(
            source=source,
            url=record.get("url"),
            doi=doi,
            source_id=source_id,
        )
        url = normalize_url(url)
        if not url:
            dropped += 1
            continue

        resolved = _resolve_doi_redirect(url)
        if resolved != url:
            doi_resolved_count += 1
            record["_url_resolved_from_doi"] = True
            record["_url_before_resolution"] = url
        else:
            record["_url_resolved_from_doi"] = False

        final_url = normalize_url(resolved) or url
        if _is_probable_pdf_url(final_url):
            article_url = _select_article_url(
                source=source,
                source_id=source_id,
                doi=doi,
                original_url=url,
                resolved_url=final_url,
            )
            if not article_url:
                dropped += 1
                continue
            if not normalize_url(record.get("pdf_url")):
                record["pdf_url"] = final_url
                pdf_promoted_count += 1
            record["_url_moved_to_pdf"] = True
            record["url"] = article_url
        else:
            record["_url_moved_to_pdf"] = False
            record["url"] = final_url
        normalized.append(record)

    return normalized, dropped, doi_resolved_count, pdf_promoted_count


async def _execute_routed_source(
    *,
    routed: RoutedSource,
    limit: int,
    disable_fragile_sources: bool,
    api_only: bool,
    fixture_sample_size: int,
) -> tuple[ParseAttemptResult, list[dict[str, Any]]]:
    started = time.perf_counter()
    source = routed.source
    source_meta = SOURCE_REGISTRY.get(source)
    runtime_config = load_source_runtime_config_with_metadata(source=source, source_meta=source_meta)

    _ensure_valid_runtime_configuration(source=source, source_meta=source_meta, runtime_config=runtime_config)
    _check_source_allowed(
        source=source,
        source_meta=source_meta,
        runtime_config=runtime_config,
        disable_fragile_sources=disable_fragile_sources,
        api_only=api_only,
    )

    if source_meta.is_fragile and source_meta.notes:
        logger.warning("Using fragile source %s: %s", source, source_meta.notes)

    attempted_query = routed.adapted_query
    route_reason = routed.reason

    try:
        execution = await execute_source_search(
            source=source,
            query=attempted_query,
            limit=limit,
            runtime_config=runtime_config,
            sample_limit=fixture_sample_size,
        )
    except SourceError as first_exc:
        if not _contains_non_ascii(attempted_query):
            raise
        translated_query, fallback_reason = _translate_query_for_fallback(attempted_query)
        if not translated_query:
            raise
        logger.warning(
            "Source %s failed for non-ASCII query '%s'; retry with translated query '%s'",
            source,
            attempted_query,
            translated_query,
        )
        execution = await execute_source_search(
            source=source,
            query=translated_query,
            limit=limit,
            runtime_config=runtime_config,
            sample_limit=fixture_sample_size,
        )
        attempted_query = translated_query
        route_reason = f"{route_reason}|{fallback_reason}|retry_after_error:{type(first_exc).__name__}"

    if len(execution.papers) == 0 and _contains_non_ascii(attempted_query):
        translated_query, fallback_reason = _translate_query_for_fallback(attempted_query)
        if translated_query and translated_query != attempted_query:
            logger.info(
                "Source %s returned zero parsed items for non-ASCII query '%s'; retry with translated query '%s'",
                source,
                attempted_query,
                translated_query,
            )
            translated_execution = await execute_source_search(
                source=source,
                query=translated_query,
                limit=limit,
                runtime_config=runtime_config,
                sample_limit=fixture_sample_size,
            )
            execution = translated_execution
            attempted_query = translated_query
            route_reason = f"{route_reason}|{fallback_reason}|retry_after_zero_results"

    attempt = ParseAttemptResult(
        source=source,
        adapted_query=attempted_query,
        route_reason=route_reason,
        parsed_count=len(execution.papers),
        raw_count=execution.raw_count,
        duration_seconds=time.perf_counter() - started,
        diagnostics=execution.diagnostics,
        source_health=execution.source_health,
        raw_samples=execution.raw_samples,
    )
    papers = [_paper_to_dict(item) for item in execution.papers]
    return attempt, papers


async def run_parse(
    source: str,
    query: str,
    limit: int,
    out_dir: Path,
    disable_fragile_sources: bool = False,
    api_only: bool = False,
    stable_only: bool = False,
    allow_experimental: bool = True,
    max_fallback_sources: int = 3,
    strict_source: bool = False,
    record_fixtures: bool = False,
    fixture_sample_size: int = 5,
) -> ParseRunResult:
    started = time.perf_counter()
    out_dir.mkdir(parents=True, exist_ok=True)

    health_store = SourceHealthStore(out_dir / "source_health.json")
    effective_max_sources = 1 if not FALLBACK_ENABLED else (1 if strict_source else max_fallback_sources)
    route = resolve_route(
        requested_source=source,
        registry=SOURCE_REGISTRY,
        query=query,
        health_store=health_store,
        disable_fragile_sources=disable_fragile_sources,
        api_only=api_only,
        stable_only=stable_only,
        allow_experimental=allow_experimental,
        max_sources=effective_max_sources,
    )

    if not route:
        raise MisconfigurationError(source=source, message="No eligible sources for provided flags and route policy")

    attempts: list[ParseAttemptResult] = []
    all_records: list[dict[str, Any]] = []

    for routed in route:
        remaining = max(1, limit - len(all_records))
        try:
            attempt, papers = await _execute_routed_source(
                routed=routed,
                limit=remaining,
                disable_fragile_sources=disable_fragile_sources,
                api_only=api_only,
                fixture_sample_size=fixture_sample_size,
            )
            attempts.append(attempt)

            health_store.record(
                SourceRunTelemetry(
                    source=attempt.source,
                    success=attempt.parsed_count > 0,
                    parsed_count=attempt.parsed_count,
                    raw_count=attempt.raw_count,
                    degraded=bool(attempt.source_health.get("degraded", False)),
                )
            )

            if attempt.parsed_count > 0:
                all_records.extend(papers)

            if len(all_records) >= limit:
                break
        except SourceError as exc:
            attempt = ParseAttemptResult(
                source=routed.source,
                adapted_query=routed.adapted_query,
                route_reason=routed.reason,
                parsed_count=0,
                raw_count=0,
                duration_seconds=0.0,
                diagnostics={"source": routed.source, "events": [], "degraded": True, "degraded_reasons": ["source_error"]},
                source_health={
                    "success_rate": 0.0,
                    "empty_result_rate": 1.0,
                    "parse_error_rate": 0.0,
                    "drift_detected_count": 0,
                    "warnings_count": 0,
                    "degraded": True,
                },
                raw_samples=[],
                error=str(exc),
            )
            attempts.append(attempt)
            health_store.record(
                SourceRunTelemetry(
                    source=routed.source,
                    success=False,
                    parsed_count=0,
                    raw_count=0,
                    degraded=True,
                    error=str(exc),
                )
            )
            logger.warning("Route source %s failed: %s", routed.source, exc)

    health_store.save()

    if record_fixtures:
        fixtures_dir = out_dir / "runtime_fixtures"
        fixtures_dir.mkdir(parents=True, exist_ok=True)
        for attempt in attempts:
            if not attempt.raw_samples:
                continue
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            fixture_path = fixtures_dir / f"{attempt.source}_{ts}.json"
            fixture_payload = {
                "source": attempt.source,
                "adapted_query": attempt.adapted_query,
                "route_reason": attempt.route_reason,
                "recorded_at": datetime.now().isoformat(),
                "raw_samples": attempt.raw_samples[: max(1, fixture_sample_size)],
                "diagnostics_summary": {
                    "degraded": attempt.diagnostics.get("degraded", False),
                    "degraded_reasons": attempt.diagnostics.get("degraded_reasons", []),
                    "events_count": len(attempt.diagnostics.get("events", [])),
                },
            }
            fixture_path.write_text(json.dumps(fixture_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    merged = _merge_records_by_dedupe(all_records, limit=limit)
    merged, dropped_missing_url, doi_resolved_count, pdf_promoted_count = _enforce_article_url(merged)

    route_mode = _route_mode(source)
    source_attempts_info = [
        {
            "source": item.source,
            "adapted_query": item.adapted_query,
            "status": _classify_attempt_status(item),
            "parsed_count": item.parsed_count,
            "raw_count": item.raw_count,
            "duration_seconds": round(item.duration_seconds, 3),
            "error": item.error,
            "degraded": bool(item.source_health.get("degraded", False)),
        }
        for item in attempts
    ]
    fallback_used = len(attempts) > 1 and any(item.parsed_count > 0 for item in attempts[1:])

    info_summary = {
        "requested_source": source,
        "route_mode": route_mode,
        "strict_source": strict_source,
        "fallback_used": fallback_used,
        "dropped_missing_url": dropped_missing_url,
        "doi_resolved_count": doi_resolved_count,
        "pdf_promoted_count": pdf_promoted_count,
        "attempts": source_attempts_info,
    }

    for record in merged:
        effective_source = str(record.get("source") or "")
        matched_attempt = next(
            (attempt for attempt in attempts if _source_matches_attempt(effective_source, attempt.source)),
            None,
        )
        record["info"] = {
            "requested_source": source,
            "route_mode": route_mode,
            "strict_source": strict_source,
            "effective_source": effective_source or None,
            "fallback_used": fallback_used or (
                FALLBACK_ENABLED
                and
                route_mode != "auto"
                and bool(effective_source)
                and effective_source.strip().lower() != source.strip().lower()
            ),
            "parser_status": _classify_attempt_status(matched_attempt) if matched_attempt else "worked",
            "attempt_source": matched_attempt.source if matched_attempt else None,
            "attempt_error": matched_attempt.error if matched_attempt else None,
            "url_resolved_from_doi": bool(record.pop("_url_resolved_from_doi", False)),
            "url_before_resolution": record.pop("_url_before_resolution", None),
            "url_moved_to_pdf_field": bool(record.pop("_url_moved_to_pdf", False)),
        }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_source = source.replace(" ", "_").replace(",", "_")
    out_path = out_dir / f"{safe_source}_{ts}.json"
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    total_raw = sum(item.raw_count for item in attempts)
    total_parsed = len(merged)
    parse_errors = sum(
        1
        for attempt in attempts
        for event in attempt.diagnostics.get("events", [])
        if event.get("stage") == "parse" and event.get("severity") == "error"
    )
    drift_count = sum(int(attempt.source_health.get("drift_detected_count", 0)) for attempt in attempts)
    warnings_count = sum(int(attempt.source_health.get("warnings_count", 0)) for attempt in attempts)

    diagnostics = {
        "route": [
            {
                "source": item.source,
                "adapted_query": item.adapted_query,
                "reason": item.reason,
                "priority_score": item.priority_score,
            }
            for item in route
        ],
        "attempts": [
            {
                "source": item.source,
                "adapted_query": item.adapted_query,
                "route_reason": item.route_reason,
                "parsed_count": item.parsed_count,
                "raw_count": item.raw_count,
                "duration_seconds": round(item.duration_seconds, 3),
                "error": item.error,
                "diagnostics": item.diagnostics,
            }
            for item in attempts
        ],
    }
    source_health = {
        "success_rate": round((total_parsed / total_raw), 3) if total_raw else 0.0,
        "empty_result_rate": 1.0 if total_raw == 0 else 0.0,
        "parse_error_rate": round(parse_errors / max(1, total_raw), 3),
        "drift_detected_count": drift_count,
        "warnings_count": warnings_count,
        "degraded": any(bool(item.source_health.get("degraded", False)) for item in attempts),
    }

    logger.info(
        "Saved %s merged parsed items (raw=%s) for route=%s to %s",
        total_parsed,
        total_raw,
        [item.source for item in attempts],
        out_path,
    )

    return ParseRunResult(
        out_path=out_path,
        parsed_count=total_parsed,
        raw_count=total_raw,
        duration_seconds=time.perf_counter() - started,
        diagnostics=diagnostics,
        source_health=source_health,
        attempts=attempts,
        info_summary=info_summary,
    )


def _build_dry_run_plan(
    source: str,
    query: str,
    limit: int,
    disable_fragile_sources: bool,
    api_only: bool,
    stable_only: bool,
    allow_experimental: bool,
    out_dir: str,
    max_fallback_sources: int,
    strict_source: bool,
) -> dict[str, Any]:
    temp_store = SourceHealthStore(Path(out_dir) / "source_health.json")
    effective_max_sources = 1 if not FALLBACK_ENABLED else (1 if strict_source else max_fallback_sources)
    route = resolve_route(
        requested_source=source,
        registry=SOURCE_REGISTRY,
        query=query,
        health_store=temp_store,
        disable_fragile_sources=disable_fragile_sources,
        api_only=api_only,
        stable_only=stable_only,
        allow_experimental=allow_experimental,
        max_sources=effective_max_sources,
    )

    route_plan: list[dict[str, Any]] = []
    for routed in route:
        source_meta = SOURCE_REGISTRY.get(routed.source)
        runtime_config = load_source_runtime_config_with_metadata(source=routed.source, source_meta=source_meta)
        validation_issues = _collect_runtime_validation_issues(
            source=routed.source,
            source_meta=source_meta,
            runtime_config=runtime_config,
        )

        blocked_reasons: list[str] = []
        if validation_issues:
            blocked_reasons.extend(validation_issues)
        if not runtime_config.enabled:
            blocked_reasons.append("blocked_by_runtime_config_disabled")
        if disable_fragile_sources and source_meta.is_fragile:
            blocked_reasons.append("blocked_by_disable_fragile_sources")
        if api_only and source_meta.source_type != "api":
            blocked_reasons.append("blocked_by_api_only")
        if source_meta.requires_browser and not runtime_config.browser_enabled:
            blocked_reasons.append("blocked_by_browser_disabled")

        expected_api_env = source_meta.api_key_env
        if runtime_config.require_api_key and expected_api_env and not os.getenv(expected_api_env):
            blocked_reasons.append("blocked_by_missing_required_api_key")

        route_plan.append(
            {
                "source": source_meta.name,
                "adapted_query": routed.adapted_query,
                "route_reason": routed.reason,
                "priority_score": routed.priority_score,
                "source_type": source_meta.source_type,
                "stability": source_meta.stability,
                "maturity": source_meta.maturity,
                "access_mode": source_meta.access_mode,
                "capabilities": source_meta.capabilities.__dict__,
                "compliance_notes": source_meta.compliance_notes,
                "runtime_config": {
                    "enabled": runtime_config.enabled,
                    "timeout": runtime_config.timeout,
                    "max_retries": runtime_config.max_retries,
                    "retry_base_delay": runtime_config.retry_base_delay,
                    "retry_backoff_base": runtime_config.retry_backoff_base,
                    "retry_jitter_max": runtime_config.retry_jitter_max,
                    "browser_enabled": runtime_config.browser_enabled,
                    "require_api_key": runtime_config.require_api_key,
                    "headless": runtime_config.headless,
                    "headers_profile": runtime_config.headers_profile,
                },
                "api_key_env": expected_api_env,
                "validation_issues": validation_issues,
                "will_execute": not blocked_reasons,
                "blocked_reasons": blocked_reasons,
                "notes": source_meta.notes,
            }
        )

    return {
        "query": query,
        "limit": limit,
        "out_dir": out_dir,
        "requested_source": source,
        "route_mode": _route_mode(source),
        "route_count": len(route_plan),
        "flags": {
                "disable_fragile_sources": disable_fragile_sources,
                "api_only": api_only,
                "stable_only": stable_only,
                "allow_experimental": allow_experimental,
                "max_fallback_sources": max_fallback_sources,
                "strict_source": strict_source,
            },
        "route_plan": route_plan,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    available_sources = ", ".join(SOURCE_REGISTRY.list_names())
    p = argparse.ArgumentParser(description="Standalone parser runner (no DB, JSON output)")
    p.add_argument(
        "--source",
        required=True,
        help=(
            "Source name, 'auto', or comma-separated list for explicit fallback order. "
            f"Available sources: {available_sources}"
        ),
    )
    p.add_argument("--query", required=True, help="Search query")
    p.add_argument("--limit", type=int, default=20, help="Max number of merged results")
    p.add_argument("--out", default="data", help="Output directory for JSON files")
    p.add_argument(
        "--max-fallback-sources",
        type=int,
        default=3,
        help="Maximum number of routed sources to try in auto/fallback mode",
    )
    p.add_argument(
        "--strict-source",
        action="store_true",
        help="Disable fallback and run only the requested source",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print execution route plan and source metadata without network calls or output files",
    )
    p.add_argument(
        "--explain",
        action="store_true",
        help="Print machine-readable execution report after run",
    )
    p.add_argument(
        "--disable-fragile-sources",
        action="store_true",
        help="Skip low-stability and non-API sources (scraper/browser automation)",
    )
    p.add_argument(
        "--api-only",
        action="store_true",
        help="Allow only API-backed sources",
    )
    p.add_argument(
        "--stable-only",
        action="store_true",
        help="Route only sources with maturity='stable'",
    )
    p.add_argument(
        "--no-experimental",
        action="store_true",
        help="Exclude experimental sources from routing",
    )
    p.add_argument(
        "--record-fixtures",
        action="store_true",
        help="Capture runtime raw sample fixtures for routed sources",
    )
    p.add_argument(
        "--fixture-sample-size",
        type=int,
        default=5,
        help="Max raw samples per source to store when --record-fixtures is enabled",
    )
    p.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity",
    )
    return p


def main() -> None:
    args = _build_arg_parser().parse_args()
    if not FALLBACK_ENABLED:
        args.strict_source = True
        args.max_fallback_sources = 1
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    if args.dry_run:
        plan = _build_dry_run_plan(
            source=args.source,
            query=args.query,
            limit=args.limit,
            disable_fragile_sources=args.disable_fragile_sources,
            api_only=args.api_only,
            stable_only=args.stable_only,
            allow_experimental=not args.no_experimental,
            out_dir=args.out,
            max_fallback_sources=args.max_fallback_sources,
            strict_source=args.strict_source,
        )
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return

    try:
        result = asyncio.run(
            run_parse(
                source=args.source,
                query=args.query,
                limit=args.limit,
                out_dir=Path(args.out),
                disable_fragile_sources=args.disable_fragile_sources,
                api_only=args.api_only,
                stable_only=args.stable_only,
                allow_experimental=not args.no_experimental,
                max_fallback_sources=args.max_fallback_sources,
                strict_source=args.strict_source,
                record_fixtures=args.record_fixtures,
                fixture_sample_size=max(1, args.fixture_sample_size),
            )
        )
    except SourceError as exc:
        logger.error("Source execution failed: %s", exc)
        raise SystemExit(2) from exc

    if args.explain:
        report = {
            "requested_source": args.source,
            "query": args.query,
            "limit": args.limit,
            "raw_count": result.raw_count,
            "parsed_count": result.parsed_count,
            "duration_seconds": round(result.duration_seconds, 3),
            "out_path": str(result.out_path),
            "diagnostics": result.diagnostics,
            "source_health": result.source_health,
            "info": result.info_summary,
            "attempts": [
                {
                    "source": item.source,
                    "adapted_query": item.adapted_query,
                    "route_reason": item.route_reason,
                    "parsed_count": item.parsed_count,
                    "raw_count": item.raw_count,
                    "duration_seconds": round(item.duration_seconds, 3),
                    "error": item.error,
                }
                for item in result.attempts
            ],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print(result.out_path)


if __name__ == "__main__":
    main()
