"""Source routing, query adaptation, fallback chains, and health persistence."""

from __future__ import annotations

import json
import logging
import re
import tempfile
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from parsers_pkg.sources import SourceMetadata, SourceRegistry
from parsers_pkg.translate import get_shared_query_translator


logger = logging.getLogger(__name__)


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


def _safe_int_counter(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _sources_state(state: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    sources = state.get("sources")
    return sources if isinstance(sources, dict) else {}


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
    "GooglePatents": {},
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
        "GooglePatents",
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


_PATENT_PUBLICATION_QUERY_RE = re.compile(r"^[A-Z]{0,3}\d{4,}[A-Z]?\d?$", re.IGNORECASE)


def _is_patent_publication_lookup(query: str) -> bool:
    raw = " ".join(str(query or "").split()).strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    if (
        parsed.scheme in {"http", "https"}
        and "patents.google.com" in parsed.netloc.lower()
        and "/patent/" in parsed.path.lower()
    ):
        return True
    normalized = re.sub(r"[\s,.:/\-]+", "", raw).upper()
    return bool(_PATENT_PUBLICATION_QUERY_RE.fullmatch(normalized))


def _default_fallback_chain(source: str, query: str = "") -> list[str]:
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
        chain = ["PATENTSCOPE", "Rospatent", "FreePatent"]
        return [chain[0], "GooglePatents", *chain[1:]] if _is_patent_publication_lookup(query) else chain
    if source == "GooglePatents":
        return ["GooglePatents"]
    if source == "Rospatent":
        chain = ["Rospatent", "PATENTSCOPE", "FreePatent"]
        return [chain[0], "GooglePatents", *chain[1:]] if _is_patent_publication_lookup(query) else chain
    if source == "FreePatent":
        chain = ["FreePatent", "PATENTSCOPE", "Rospatent"]
        return [chain[0], "GooglePatents", *chain[1:]] if _is_patent_publication_lookup(query) else chain
    if source == "eLibrary":
        return ["eLibrary", "CyberLeninka", "OpenAlex"]
    if source == "CyberLeninka":
        return ["CyberLeninka", "eLibrary", "OpenAlex"]
    return [source]


class SourceHealthStore:
    def __init__(self, path: Path):
        self.path = path
        self._state = self._load()
        self._base_state = deepcopy(self._state)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"sources": {}, "updated_at": None}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"sources": {}, "updated_at": None}

    def _merge_with_current_disk_state(self) -> dict[str, Any]:
        """Merge in-process telemetry deltas with the latest on-disk state.

        Atomic replace prevents half-written JSON, but without merging the last writer
        can still overwrite counters saved by another parser subprocess. Track deltas
        against the state loaded at object creation and add them to the current file.
        """
        disk_state = self._load() if self.path.exists() else {"sources": {}, "updated_at": None}
        merged_sources = dict(_sources_state(disk_state))

        base_sources = _sources_state(self._base_state)
        current_sources = _sources_state(self._state)
        counters = ("runs", "successes", "failures", "degraded_runs")
        last_fields = ("last_error", "last_run_at", "last_success_at", "last_parsed_count", "last_raw_count")

        for source, current_entry in current_sources.items():
            if not isinstance(current_entry, dict):
                continue
            base_entry = base_sources.get(source, {}) if isinstance(base_sources.get(source, {}), dict) else {}
            merged_entry = merged_sources.get(source)
            if not isinstance(merged_entry, dict):
                merged_entry = deepcopy(base_entry) if base_entry else {}
                merged_sources[source] = merged_entry

            for key in counters:
                current_value = _safe_int_counter(current_entry.get(key, 0))
                base_value = _safe_int_counter(base_entry.get(key, 0))
                delta = current_value - base_value
                if delta:
                    merged_entry[key] = _safe_int_counter(merged_entry.get(key, 0)) + delta
                else:

                    merged_entry[key] = _safe_int_counter(merged_entry.get(key, current_value))

            for key in last_fields:
                if current_entry.get(key) != base_entry.get(key):
                    merged_entry[key] = current_entry.get(key)
                else:
                    merged_entry.setdefault(key, current_entry.get(key))

        merged_state = {
            "sources": merged_sources,
            "updated_at": _utc_now_iso(),
        }
        return merged_state

    def _acquire_save_lock(self, *, timeout: float = 10.0, stale_after: float = 60.0) -> Path:
        """Acquire a small cross-process lock for source_health.json writes.

        Atomic replace protects against half-written JSON, but two parser subprocesses
        can still read the same old file and overwrite each other's merged counters.
        A directory lock works on Windows and Linux without extra dependencies.
        """
        lock_path = self.path.with_name(f"{self.path.name}.lock")
        deadline = time.monotonic() + max(0.5, timeout)

        while True:
            try:
                lock_path.mkdir(parents=True, exist_ok=False)
                return lock_path
            except FileExistsError:
                try:
                    age = time.time() - lock_path.stat().st_mtime
                    if age > stale_after:
                        lock_path.rmdir()
                        continue
                except FileNotFoundError:
                    continue
                except OSError:
                    pass

                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for source health lock: {lock_path}")
                time.sleep(0.05)

    @staticmethod
    def _release_save_lock(lock_path: Path | None) -> None:
        if lock_path is None:
            return
        try:
            lock_path.rmdir()
        except FileNotFoundError:
            return

    def save(self) -> None:
        """Persist source health atomically and preserve concurrent updates.

        Source health is telemetry, not parser payload. A stale lock or temporary
        filesystem issue must not turn an otherwise successful parser run into a
        failed Celery task.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path: Path | None = None
        tmp_path: Path | None = None
        try:
            lock_path = self._acquire_save_lock()
            merged_state = self._merge_with_current_disk_state()
            payload = json.dumps(merged_state, ensure_ascii=False, indent=2)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(self.path.parent)) as tmp:
                tmp.write(payload)
                tmp_path = Path(tmp.name)
            tmp_path.replace(self.path)
            self._state = merged_state
            self._base_state = deepcopy(merged_state)
        except Exception as exc:
            logger.warning("Failed to save parser source health to %s: %s", self.path, exc)
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
        finally:
            self._release_save_lock(lock_path)

    def get(self, source: str) -> dict[str, Any]:
        entry = _sources_state(self._state).get(source, {})
        return dict(entry) if isinstance(entry, dict) else {}

    def score_penalty(self, source: str) -> float:
        state = self.get(source)
        runs = _safe_int_counter(state.get("runs", 0))
        failures = _safe_int_counter(state.get("failures", 0))
        degraded_runs = _safe_int_counter(state.get("degraded_runs", 0))
        if runs == 0:
            return 0.0

        fail_ratio = failures / runs
        degraded_ratio = degraded_runs / runs
        return round((fail_ratio * 60.0) + (degraded_ratio * 20.0), 3)

    def record(self, telemetry: SourceRunTelemetry) -> None:
        sources = _sources_state(self._state)
        if not sources:
            self._state["sources"] = sources

        default_entry = {
            "runs": 0,
            "successes": 0,
            "failures": 0,
            "degraded_runs": 0,
            "last_error": None,
            "last_run_at": None,
            "last_success_at": None,
            "last_parsed_count": 0,
            "last_raw_count": 0,
        }
        existing = sources.get(telemetry.source)
        entry = existing if isinstance(existing, dict) else dict(default_entry)
        for key in ("runs", "successes", "failures", "degraded_runs"):
            entry[key] = _safe_int_counter(entry.get(key, 0))
        sources[telemetry.source] = entry

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
        names = _default_fallback_chain(requested, query)
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
