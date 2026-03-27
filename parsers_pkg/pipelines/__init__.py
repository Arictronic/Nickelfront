"""
Pipelines module.

Модули:
- data_pipeline: Конвейеры обработки данных
"""

from .data_pipeline import (
    PipelineContext,
    PipelineResult,
    PipelineStage,
    CleaningStage,
    ValidationStage,
    DeduplicationStage,
    EnrichmentStage,
    DataPipeline,
    create_default_pipeline,
    process_papers,
)

__all__ = [
    "PipelineContext",
    "PipelineResult",
    "PipelineStage",
    "CleaningStage",
    "ValidationStage",
    "DeduplicationStage",
    "EnrichmentStage",
    "DataPipeline",
    "create_default_pipeline",
    "process_papers",
]
