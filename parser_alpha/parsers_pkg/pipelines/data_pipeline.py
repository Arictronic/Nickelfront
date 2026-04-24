"""Data pipeline with stage-level diagnostics and partial failure semantics."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from parsers_pkg.base import Deduplicator
from parsers_pkg.base.base_parser import BaseParser
from parsers_pkg.base.validation import split_issues, validate_paper_fields
from parsers_pkg.contracts import ParserDiagnostics
from shared.schemas.paper import Paper

logger = logging.getLogger(__name__)


class _PipelineTextCleaner(BaseParser):
    def __init__(self):
        super().__init__(source="pipeline")

    async def parse_search_results(self, data: list[dict[str, Any]]) -> list[Paper]:
        raise NotImplementedError


_TEXT_CLEANER = _PipelineTextCleaner()


@dataclass
class PipelineContext:
    papers: list[Paper] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    stage_diagnostics: dict[str, list[str]] = field(default_factory=dict)
    parser_diagnostics: ParserDiagnostics = field(default_factory=lambda: ParserDiagnostics(source="pipeline"))
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None


@dataclass
class PipelineResult:
    success: bool
    papers: list[Paper]
    errors: list[str]
    stats: dict[str, Any]
    duration_seconds: float
    diagnostics: dict[str, Any]


class PipelineStage:
    def __init__(self, name: str):
        self.name = name

    async def process(self, context: PipelineContext) -> PipelineContext:
        raise NotImplementedError


class CleaningStage(PipelineStage):
    def __init__(self):
        super().__init__("cleaning")

    async def process(self, context: PipelineContext) -> PipelineContext:
        cleaned_papers: list[Paper] = []
        stage_errors: list[str] = []

        for paper in context.papers:
            try:
                paper.title = _TEXT_CLEANER._clean_text(paper.title)
                paper.abstract = _TEXT_CLEANER._clean_text(paper.abstract)
                paper.full_text = _TEXT_CLEANER._clean_text(paper.full_text)
                paper.journal = _TEXT_CLEANER._clean_text(paper.journal)
                paper.authors = [_TEXT_CLEANER._clean_text(a) for a in paper.authors if _TEXT_CLEANER._clean_text(a)]
                paper.keywords = [_TEXT_CLEANER._clean_text(k) for k in paper.keywords if _TEXT_CLEANER._clean_text(k)]
                cleaned_papers.append(paper)
            except Exception as exc:
                msg = f"Error cleaning paper '{(paper.title or '<empty>')[:50]}...': {exc}"
                stage_errors.append(msg)
                context.parser_diagnostics.add(stage=self.name, reason="cleaning_failure", severity="warning")

        context.papers = cleaned_papers
        context.stats["cleaned_count"] = len(cleaned_papers)
        context.stage_diagnostics[self.name] = stage_errors
        context.errors.extend(stage_errors)
        return context


class ValidationStage(PipelineStage):
    def __init__(self, required_fields: list[str] | None = None):
        super().__init__("validation")
        self.required_fields = required_fields or ["title", "source"]

    async def process(self, context: PipelineContext) -> PipelineContext:
        valid_papers: list[Paper] = []
        invalid_count = 0
        stage_errors: list[str] = []

        for paper in context.papers:
            issues = validate_paper_fields(paper, source=paper.source or "unknown")
            hard, soft = split_issues(issues)
            errors = [issue.message for issue in issues]
            is_valid = len(hard) == 0
            if soft:
                context.parser_diagnostics.add(
                    stage=self.name,
                    reason="soft_validation_issue",
                    severity="warning",
                    details={"count": len(soft), "source": paper.source},
                )
            if is_valid:
                valid_papers.append(paper)
                continue

            invalid_count += 1
            for error in errors:
                msg = f"Validation error for '{(paper.title or '<empty>')[:50]}...': {error}"
                stage_errors.append(msg)

        context.papers = valid_papers
        context.stats["valid_count"] = len(valid_papers)
        context.stats["invalid_count"] = invalid_count
        context.stage_diagnostics[self.name] = stage_errors
        context.errors.extend(stage_errors)
        if stage_errors:
            context.parser_diagnostics.add(stage=self.name, reason="validation_errors", severity="warning")
        return context


class DeduplicationStage(PipelineStage):
    def __init__(self, existing_papers: list[dict[str, Any]] | None = None, enable_merge: bool = True):
        super().__init__("deduplication")
        self.deduplicator = Deduplicator(existing_papers or [])
        self.enable_merge = enable_merge

    async def process(self, context: PipelineContext) -> PipelineContext:
        unique_papers: list[Paper] = []
        duplicates_count = 0
        merged_count = 0
        stage_errors: list[str] = []

        for paper in context.papers:
            paper_dict = paper.model_dump() if hasattr(paper, "model_dump") else paper.dict()
            is_duplicate, reason = self.deduplicator.is_duplicate(paper_dict)

            if not is_duplicate:
                unique_papers.append(paper)
                self.deduplicator.add_paper(paper_dict)
                continue

            duplicates_count += 1
            if self.enable_merge:
                existing = next(
                    (
                        item for item in self.deduplicator.existing_papers
                        if item.get("doi") == paper_dict.get("doi")
                        or item.get("source_id") == paper_dict.get("source_id")
                    ),
                    None,
                )
                if existing is not None:
                    merged = self.deduplicator.merge_records(paper_dict, existing)
                    existing.update(merged.record)
                    existing["provenance"] = merged.provenance
                    existing["parse_confidence"] = merged.confidence
                    merged_count += 1
                    continue

            stage_errors.append(f"Duplicate paper '{(paper.title or '<empty>')[:50]}...': {reason}")

        context.papers = unique_papers
        context.stats["unique_count"] = len(unique_papers)
        context.stats["duplicates_count"] = duplicates_count
        context.stats["merged_count"] = merged_count
        context.stage_diagnostics[self.name] = stage_errors
        context.errors.extend(stage_errors)
        return context


class EnrichmentStage(PipelineStage):
    def __init__(self, add_keywords: bool = True, add_summary: bool = False):
        super().__init__("enrichment")
        self.add_keywords = add_keywords
        self.add_summary = add_summary

    async def process(self, context: PipelineContext) -> PipelineContext:
        enriched_count = 0
        stage_errors: list[str] = []

        for paper in context.papers:
            try:
                if self.add_keywords and not paper.keywords:
                    paper.keywords = self._extract_keywords(paper)
                if self.add_summary and not paper.summary_ru:
                    paper.summary_ru = self._generate_summary(paper)
                enriched_count += 1
            except Exception as exc:
                msg = f"Error enriching paper '{(paper.title or '<empty>')[:50]}...': {exc}"
                stage_errors.append(msg)

        context.stats["enriched_count"] = enriched_count
        context.stage_diagnostics[self.name] = stage_errors
        context.errors.extend(stage_errors)
        return context

    def _extract_keywords(self, paper: Paper) -> list[str]:
        import re

        text_parts = [part for part in [paper.title, paper.abstract] if part]
        if not text_parts:
            return []

        text = " ".join(text_parts).lower()
        words = re.findall(r"\b[a-zа-я]{4,}\b", text)
        stopwords = {
            "this", "that", "with", "from", "have", "were", "been",
            "это", "для", "как", "что", "при", "или", "без", "под",
            "using", "based", "study", "analysis", "approach", "method",
        }

        freq: dict[str, int] = {}
        for word in words:
            if word not in stopwords:
                freq[word] = freq.get(word, 0) + 1

        return [word for word, _ in sorted(freq.items(), key=lambda item: item[1], reverse=True)[:10]]

    def _generate_summary(self, paper: Paper) -> str:
        if paper.abstract:
            return paper.abstract[:500] + "..." if len(paper.abstract) > 500 else paper.abstract
        return f"Статья '{paper.title}' из источника {paper.source}"


class DataPipeline:
    def __init__(self, continue_on_stage_error: bool = True):
        self.stages: list[PipelineStage] = []
        self.continue_on_stage_error = continue_on_stage_error

    def add_stage(self, stage: PipelineStage) -> None:
        self.stages.append(stage)

    async def run(self, papers: list[Paper]) -> PipelineResult:
        context = PipelineContext(papers=papers.copy())
        logger.info("Starting pipeline with %s papers", len(papers))

        success = True
        for stage in self.stages:
            logger.info("Running stage: %s", stage.name)
            try:
                context = await stage.process(context)
            except Exception as exc:
                success = False
                msg = f"Stage '{stage.name}' failed: {exc}"
                context.errors.append(msg)
                context.stage_diagnostics.setdefault(stage.name, []).append(msg)
                context.parser_diagnostics.add(stage=stage.name, reason="stage_exception", severity="error")
                logger.exception(msg)
                if not self.continue_on_stage_error:
                    break
            logger.info("Stage %s completed: %s papers", stage.name, len(context.papers))

        context.end_time = datetime.now()
        duration = (context.end_time - context.start_time).total_seconds()

        return PipelineResult(
            success=success or self.continue_on_stage_error,
            papers=context.papers,
            errors=context.errors,
            stats=context.stats,
            duration_seconds=duration,
            diagnostics={
                "stage_diagnostics": context.stage_diagnostics,
                "parser": context.parser_diagnostics.as_dict(),
                "summary": context.parser_diagnostics.summary(),
            },
        )


def create_default_pipeline(
    enable_cleaning: bool = True,
    enable_validation: bool = True,
    enable_deduplication: bool = True,
    enable_enrichment: bool = False,
    existing_papers: list[dict[str, Any]] | None = None,
    continue_on_stage_error: bool = True,
) -> DataPipeline:
    pipeline = DataPipeline(continue_on_stage_error=continue_on_stage_error)

    if enable_cleaning:
        pipeline.add_stage(CleaningStage())
    if enable_validation:
        pipeline.add_stage(ValidationStage())
    if enable_deduplication:
        pipeline.add_stage(DeduplicationStage(existing_papers))
    if enable_enrichment:
        pipeline.add_stage(EnrichmentStage())

    return pipeline


async def process_papers(
    papers: list[Paper],
    *,
    enable_cleaning: bool = True,
    enable_validation: bool = True,
    enable_deduplication: bool = True,
    enable_enrichment: bool = False,
    existing_papers: list[dict[str, Any]] | None = None,
    continue_on_stage_error: bool = True,
) -> PipelineResult:
    pipeline = create_default_pipeline(
        enable_cleaning=enable_cleaning,
        enable_validation=enable_validation,
        enable_deduplication=enable_deduplication,
        enable_enrichment=enable_enrichment,
        existing_papers=existing_papers,
        continue_on_stage_error=continue_on_stage_error,
    )
    return await pipeline.run(papers)
