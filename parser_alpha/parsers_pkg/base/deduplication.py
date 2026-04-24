"""Multi-key deduplication and merge strategies for parser outputs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from parsers_pkg.base.normalization import clean_text, normalize_doi

TITLE_SIMILARITY_THRESHOLD = 0.9
TITLE_YEAR_SIMILARITY_THRESHOLD = 0.86

SOURCE_TRUST = {
    "arXiv": 0.9,
    "CORE": 0.85,
    "OpenAlex": 0.85,
    "Crossref": 0.9,
    "EuropePMC": 0.9,
}

PATENT_SOURCES = {
    "freepatent",
    "patentscope",
    "rospatent",
}


def is_patent_record(paper: dict[str, Any]) -> bool:
    source = str(paper.get("source") or "").strip().lower()
    journal = str(paper.get("journal") or "").strip().lower()
    return source in PATENT_SOURCES or journal in PATENT_SOURCES


@dataclass
class DeduplicationResult:
    is_duplicate: bool
    confidence: float
    reason: str
    matched_existing_id: int | None = None


@dataclass
class MergedRecord:
    record: dict[str, Any]
    confidence: float
    provenance: dict[str, str] = field(default_factory=dict)
    merged_from: list[str] = field(default_factory=list)


class TextNormalizer:
    @staticmethod
    def normalize(text: str | None) -> str:
        cleaned = clean_text(text)
        if not cleaned:
            return ""
        lowered = cleaned.lower()
        lowered = re.sub(r"[^\w\s]", " ", lowered)
        return re.sub(r"\s+", " ", lowered).strip()


class Deduplicator:
    DOI_MATCH_THRESHOLD = 1.0

    def __init__(self, existing_papers: list[dict[str, Any]] | None = None):
        self.existing_papers = existing_papers or []

    def check_duplicate(
        self,
        title: str,
        doi: str | None = None,
        source_id: str | None = None,
        abstract: str | None = None,
        publication_year: int | None = None,
        source: str | None = None,
        journal: str | None = None,
    ) -> DeduplicationResult:
        if doi:
            result = self._check_by_doi(doi)
            if result.is_duplicate:
                return result

        if source_id:
            result = self._check_by_source_id(source_id)
            if result.is_duplicate:
                return result

        if is_patent_record({"source": source, "journal": journal}):
            return DeduplicationResult(
                is_duplicate=False,
                confidence=0.0,
                reason="Patent duplicate check is limited to DOI/source_id",
            )

        result = self._check_by_title_and_year(title=title, publication_year=publication_year)
        if result.is_duplicate:
            return result

        result = self._check_by_title_similarity(title)
        if result.is_duplicate:
            return result

        if abstract:
            result = self._check_by_content_similarity(title, abstract)
            if result.is_duplicate:
                return result

        return DeduplicationResult(is_duplicate=False, confidence=0.0, reason="No duplicate found")

    # Backward-compatible API used by old pipeline code.
    def is_duplicate(self, paper: dict[str, Any]) -> tuple[bool, str]:
        publication_year = None
        publication_date = paper.get("publication_date")
        if hasattr(publication_date, "year"):
            publication_year = publication_date.year
        elif isinstance(publication_date, str) and len(publication_date) >= 4 and publication_date[:4].isdigit():
            publication_year = int(publication_date[:4])

        result = self.check_duplicate(
            title=paper.get("title", ""),
            doi=paper.get("doi"),
            source_id=paper.get("source_id"),
            abstract=paper.get("abstract"),
            publication_year=publication_year,
            source=paper.get("source"),
            journal=paper.get("journal"),
        )
        return result.is_duplicate, result.reason

    def add_paper(self, paper: dict[str, Any]) -> None:
        self.add_existing_paper(paper)

    def merge_records(self, incoming: dict[str, Any], existing: dict[str, Any]) -> MergedRecord:
        merged = dict(existing)
        provenance: dict[str, str] = {}

        incoming_source = incoming.get("source") or "unknown"
        existing_source = existing.get("source") or "unknown"
        incoming_trust = SOURCE_TRUST.get(incoming_source, 0.5)
        existing_trust = SOURCE_TRUST.get(existing_source, 0.5)

        for field, incoming_value in incoming.items():
            existing_value = merged.get(field)
            if existing_value in (None, "", [], {}):
                if incoming_value not in (None, "", [], {}):
                    merged[field] = incoming_value
                    provenance[field] = incoming_source
                continue

            if incoming_value in (None, "", [], {}):
                provenance.setdefault(field, existing_source)
                continue

            if field == "doi":
                in_doi = normalize_doi(str(incoming_value))
                ex_doi = normalize_doi(str(existing_value))
                if in_doi and not ex_doi:
                    merged[field] = in_doi
                    provenance[field] = incoming_source
                else:
                    provenance.setdefault(field, existing_source)
                continue

            if incoming_trust > existing_trust:
                merged[field] = incoming_value
                provenance[field] = incoming_source
            else:
                provenance.setdefault(field, existing_source)

        confidence = min(1.0, 0.5 + abs(incoming_trust - existing_trust) * 0.5)
        merged_from = [source for source in {incoming_source, existing_source} if source]

        return MergedRecord(record=merged, confidence=confidence, provenance=provenance, merged_from=merged_from)

    def _check_by_doi(self, doi: str) -> DeduplicationResult:
        doi_normalized = normalize_doi(doi)
        if not doi_normalized:
            return DeduplicationResult(is_duplicate=False, confidence=0.0, reason="Invalid DOI for duplicate check")

        for paper in self.existing_papers:
            existing_doi = normalize_doi(str(paper.get("doi", "")))
            if existing_doi and existing_doi == doi_normalized:
                return DeduplicationResult(
                    is_duplicate=True,
                    confidence=1.0,
                    reason="Exact DOI match",
                    matched_existing_id=paper.get("id"),
                )

        return DeduplicationResult(is_duplicate=False, confidence=0.0, reason="DOI not found in existing papers")

    def _check_by_source_id(self, source_id: str) -> DeduplicationResult:
        source_id = str(source_id).strip()
        for paper in self.existing_papers:
            existing_source_id = str(paper.get("source_id", "")).strip()
            if existing_source_id and existing_source_id == source_id:
                return DeduplicationResult(
                    is_duplicate=True,
                    confidence=1.0,
                    reason="Exact source_id match",
                    matched_existing_id=paper.get("id"),
                )
        return DeduplicationResult(is_duplicate=False, confidence=0.0, reason="Source ID not found in existing papers")

    def _check_by_title_and_year(self, title: str, publication_year: int | None) -> DeduplicationResult:
        if not title or publication_year is None:
            return DeduplicationResult(is_duplicate=False, confidence=0.0, reason="No title/year for duplicate check")

        best_confidence = 0.0
        best_match: dict[str, Any] | None = None

        for paper in self.existing_papers:
            if is_patent_record(paper):
                continue
            existing_title = paper.get("title", "")
            if not existing_title:
                continue

            existing_year = None
            value = paper.get("publication_date")
            if hasattr(value, "year"):
                existing_year = value.year
            elif isinstance(value, str) and len(value) >= 4 and value[:4].isdigit():
                existing_year = int(value[:4])

            if existing_year != publication_year:
                continue

            confidence = self._calculate_title_similarity(title, existing_title)
            if confidence > best_confidence:
                best_confidence = confidence
                best_match = paper

        if best_confidence >= TITLE_YEAR_SIMILARITY_THRESHOLD:
            return DeduplicationResult(
                is_duplicate=True,
                confidence=best_confidence,
                reason=f"Title+year similarity: {best_confidence:.2f}",
                matched_existing_id=best_match.get("id") if best_match else None,
            )

        return DeduplicationResult(
            is_duplicate=False,
            confidence=best_confidence,
            reason=f"Title+year similarity below threshold: {best_confidence:.2f}",
        )

    def _check_by_title_similarity(self, title: str) -> DeduplicationResult:
        if not title or not self.existing_papers:
            return DeduplicationResult(is_duplicate=False, confidence=0.0, reason="No title or existing papers")

        best_match = None
        best_confidence = 0.0

        for paper in self.existing_papers:
            if is_patent_record(paper):
                continue
            existing_title = paper.get("title", "")
            if not existing_title:
                continue

            confidence = self._calculate_title_similarity(title, existing_title)
            if confidence > best_confidence:
                best_confidence = confidence
                best_match = paper

        if best_confidence >= TITLE_SIMILARITY_THRESHOLD:
            return DeduplicationResult(
                is_duplicate=True,
                confidence=best_confidence,
                reason=f"Title similarity: {best_confidence:.2f}",
                matched_existing_id=best_match.get("id") if best_match else None,
            )

        return DeduplicationResult(
            is_duplicate=False,
            confidence=best_confidence,
            reason=f"Title similarity below threshold: {best_confidence:.2f}",
        )

    def _check_by_content_similarity(self, title: str, abstract: str) -> DeduplicationResult:
        if not title or not abstract or not self.existing_papers:
            return DeduplicationResult(is_duplicate=False, confidence=0.0, reason="No content or existing papers")

        best_match = None
        best_confidence = 0.0

        for paper in self.existing_papers:
            if is_patent_record(paper):
                continue
            existing_title = paper.get("title", "")
            existing_abstract = paper.get("abstract", "")
            if not existing_title or not existing_abstract:
                continue

            title_sim = self._calculate_title_similarity(title, existing_title)
            abstract_sim = self._calculate_content_similarity(abstract, existing_abstract)
            confidence = (title_sim * 0.4) + (abstract_sim * 0.6)

            if confidence > best_confidence:
                best_confidence = confidence
                best_match = paper

        if best_confidence >= 0.75:
            return DeduplicationResult(
                is_duplicate=True,
                confidence=best_confidence,
                reason=f"Content similarity: {best_confidence:.2f}",
                matched_existing_id=best_match.get("id") if best_match else None,
            )

        return DeduplicationResult(
            is_duplicate=False,
            confidence=best_confidence,
            reason=f"Content similarity below threshold: {best_confidence:.2f}",
        )

    def _calculate_title_similarity(self, title1: str, title2: str) -> float:
        norm1 = TextNormalizer.normalize(title1)
        norm2 = TextNormalizer.normalize(title2)
        if not norm1 or not norm2:
            return 0.0
        return SequenceMatcher(None, norm1, norm2).ratio()

    def _calculate_content_similarity(self, text1: str, text2: str) -> float:
        words1 = set(TextNormalizer.normalize(text1).split())
        words2 = set(TextNormalizer.normalize(text2).split())
        if not words1 or not words2:
            return 0.0
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        return intersection / union if union > 0 else 0.0

    def add_existing_paper(self, paper: dict[str, Any]) -> None:
        self.existing_papers.append(paper)

    def clear_existing_papers(self) -> None:
        self.existing_papers.clear()


def check_duplicate(
    title: str,
    doi: str | None = None,
    source_id: str | None = None,
    abstract: str | None = None,
    existing_papers: list[dict[str, Any]] | None = None,
    publication_year: int | None = None,
    source: str | None = None,
    journal: str | None = None,
) -> DeduplicationResult:
    deduplicator = Deduplicator(existing_papers)
    return deduplicator.check_duplicate(title, doi, source_id, abstract, publication_year, source, journal)
