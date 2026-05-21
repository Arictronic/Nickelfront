"""Source routing, query adaptation, fallback chains, and health persistence."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from parsers_pkg.sources import SourceMetadata, SourceRegistry
from parsers_pkg.translate import get_shared_query_translator


@dataclass(frozen=True)
class RoutedSource:
    source: str
    adapted_query: str
    reason: str
    priority_score: float


@dataclass(frozen=True)
class SourceRunTelemetry:
    source: str
    success: bool
    parsed_count: int
    raw_count: int
    degraded: bool
    error: str | None = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_SOURCE_QUERY_REWRITE: dict[str, dict[str, str]] = {
    "arXiv": {
        "никель": "nickel",
        "никеля": "nickel",
        "никелевый": "nickel",
        "никелевая": "nickel",
        "никелевое": "nickel",
        "никелевые": "nickel",
        "никелевых": "nickel",
        "железо": "iron",
        "медь": "copper",
        "алюминий": "aluminum",
        "кобальт": "cobalt",
        "металл": "metal",
        "металлы": "metals",
        "металлургия": "metallurgy",
        "сплав": "alloy",
        "сплава": "alloy",
        "сплавы": "alloys",
        "сплавов": "alloys",
        "суперсплав": "superalloy",
        "суперсплавы": "superalloys",
        "суперсплавов": "superalloys",
        "жаропрочный": "heat-resistant",
        "жаропрочная": "heat-resistant",
        "жаропрочное": "heat-resistant",
        "жаропрочные": "heat-resistant",
        "жаропрочных": "heat-resistant",
        "коррозия": "corrosion",
        "коррозии": "corrosion",
        "патент": "patent",
        "патенты": "patents",
        "патентов": "patents",
    },
    "CORE": {},
    "OpenAlex": {},
    "Crossref": {},
    "EuropePMC": {},
    "PATENTSCOPE": {},
}


_ENGLISH_QUERY_SOURCES = {"arXiv", "CORE", "OpenAlex", "Crossref", "EuropePMC", "PATENTSCOPE"}


def _rewrite_tokens_for_source(source: str, query: str) -> tuple[str, bool]:
    mapping = _SOURCE_QUERY_REWRITE.get(source, {})
    if not mapping:
        return query, False

    tokens = query.split()
    replaced_any = False
    rewritten: list[str] = []
    for token in tokens:
        replacement = mapping.get(token.lower())
        if replacement:
            rewritten.append(replacement)
            replaced_any = True
        else:
            rewritten.append(token)
    return " ".join(rewritten), replaced_any


def _contains_non_ascii(text: str) -> bool:
    return any(ord(ch) > 127 for ch in text)


def source_prefers_english_query(source: str) -> bool:
    """Return True for sources where non-ASCII queries should be translated to English."""
    return source in _ENGLISH_QUERY_SOURCES


def adapt_query_for_source(source: str, query: str, *, allow_translation: bool = True) -> tuple[str, str]:
    raw = " ".join(query.split())
    if not raw:
        return raw, "empty_query"

    normalized = raw
    reason = "identity"

    if source in {
        "OpenAlex",
        "Crossref",
        "EuropePMC",
        "arXiv",
        "CORE",
        "CyberLeninka",
        "eLibrary",
        "Rospatent",
        "FreePatent",
        "PATENTSCOPE",
    }:
        reason = "identity"

    rewritten, replaced_any = _rewrite_tokens_for_source(source, normalized)
    if replaced_any:
        normalized = rewritten
        reason = "ru_to_en_token_rewrite"

    if source_prefers_english_query(source) and _contains_non_ascii(normalized):
        if not allow_translation:
            return normalized, f"{reason}|translation_skipped"
        translator = get_shared_query_translator()
        translated = translator.translate(normalized, target_lang="en", source_lang="auto")
        if translated.translated:
            return translated.translated_text, f"translation:{translated.used_engine}"

    return normalized, reason


def _default_fallback_chain(source: str) -> list[str]:
    if source == "EuropePMC":
        return ["EuropePMC", "Crossref", "OpenAlex"]
    if source == "Crossref":
        return ["Crossref", "OpenAlex", "EuropePMC"]
    if source == "OpenAlex":
        return ["OpenAlex", "Crossref", "EuropePMC"]
    if source == "CORE":
        return ["CORE", "OpenAlex", "Crossref"]
    if source == "arXiv":
        return ["arXiv", "OpenAlex", "Crossref"]
    if source == "PATENTSCOPE":
        return ["PATENTSCOPE", "Rospatent", "FreePatent"]
    if source == "Rospatent":
        return ["Rospatent", "PATENTSCOPE", "FreePatent"]
    if source == "FreePatent":
        return ["FreePatent", "PATENTSCOPE", "Rospatent"]
    if source == "eLibrary":
        return ["eLibrary", "CyberLeninka", "OpenAlex"]
    if source == "CyberLeninka":
        return ["CyberLeninka", "eLibrary", "OpenAlex"]
    return [source]


class SourceHealthStore:
    def __init__(self, path: Path):
        self.path = path
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"sources": {}, "updated_at": None}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"sources": {}, "updated_at": None}

    def save(self) -> None:
        """Persist source health atomically.

        Several parser subprocesses can run in parallel from different Celery workers.
        A direct write can leave a half-written JSON file if a process is killed while
        saving telemetry, which later breaks routing/fallback decisions.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state["updated_at"] = _utc_now_iso()
        payload = json.dumps(self._state, ensure_ascii=False, indent=2)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(self.path.parent)) as tmp:
            tmp.write(payload)
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.path)

    def get(self, source: str) -> dict[str, Any]:
        return dict(self._state.get("sources", {}).get(source, {}))

    def score_penalty(self, source: str) -> float:
        state = self.get(source)
        runs = int(state.get("runs", 0))
        failures = int(state.get("failures", 0))
        degraded_runs = int(state.get("degraded_runs", 0))
        if runs == 0:
            return 0.0

        fail_ratio = failures / runs
        degraded_ratio = degraded_runs / runs
        return round((fail_ratio * 60.0) + (degraded_ratio * 20.0), 3)

    def record(self, telemetry: SourceRunTelemetry) -> None:
        sources = self._state.setdefault("sources", {})
        entry = sources.setdefault(
            telemetry.source,
            {
                "runs": 0,
                "successes": 0,
                "failures": 0,
                "degraded_runs": 0,
                "last_error": None,
                "last_run_at": None,
                "last_success_at": None,
                "last_parsed_count": 0,
                "last_raw_count": 0,
            },
        )

        entry["runs"] += 1
        if telemetry.success:
            entry["successes"] += 1
            entry["last_success_at"] = _utc_now_iso()
        else:
            entry["failures"] += 1
        if telemetry.degraded:
            entry["degraded_runs"] += 1

        entry["last_error"] = telemetry.error
        entry["last_run_at"] = _utc_now_iso()
        entry["last_parsed_count"] = telemetry.parsed_count
        entry["last_raw_count"] = telemetry.raw_count


def resolve_route(
    *,
    requested_source: str,
    registry: SourceRegistry,
    query: str,
    health_store: SourceHealthStore,
    disable_fragile_sources: bool,
    api_only: bool,
    stable_only: bool = False,
    allow_experimental: bool = True,
    max_sources: int = 3,
    allow_translation: bool = True,
) -> list[RoutedSource]:
    requested = requested_source.strip()
    preserve_input_order = False

    if requested.lower() == "auto":
        candidates = registry.list_sources()
    elif "," in requested:
        ordered_names = [part.strip() for part in requested.split(",") if part.strip()]
        candidates = [registry.get(name) for name in ordered_names]
        preserve_input_order = True
    else:
        names = _default_fallback_chain(requested)
        candidates = [registry.get(name) for name in names if registry.is_supported(name)]
        preserve_input_order = True

    routed: list[RoutedSource] = []
    seen: set[str] = set()

    for source_meta in candidates:
        if source_meta.name in seen:
            continue
        seen.add(source_meta.name)

        if disable_fragile_sources and source_meta.is_fragile:
            continue
        if api_only and source_meta.source_type != "api":
            continue
        if stable_only and source_meta.maturity != "stable":
            continue
        if not allow_experimental and source_meta.maturity == "experimental":
            continue

        adapted_query, reason = adapt_query_for_source(
            source_meta.name,
            query,
            allow_translation=allow_translation,
        )
        penalty = health_store.score_penalty(source_meta.name)
        score = float(source_meta.priority) + penalty
        routed.append(
            RoutedSource(
                source=source_meta.name,
                adapted_query=adapted_query,
                reason=reason,
                priority_score=score,
            )
        )

    if not preserve_input_order:
        routed.sort(key=lambda item: item.priority_score)
    return routed[: max(1, max_sources)]
