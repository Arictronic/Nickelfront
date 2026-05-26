"""Deprecated compatibility module.

Nickelfront no longer uses thematic relevance gates to skip PDF parsing, Qwen,
or embeddings. All papers that have processable content must go through the
normal content pipeline regardless of topic.
"""
from __future__ import annotations

from typing import Any


def evaluate_nickel_alloy_relevance(**_: Any) -> dict[str, Any]:
    """Return a neutral compatibility payload for old callers.

    This function is intentionally non-blocking and must not be used to decide
    whether PDF/Qwen/RAG processing should run.
    """
    return {
        "version": "disabled",
        "level": "not_evaluated",
        "score": 0,
        "quality_flags": [],
    }


def paper_should_skip_heavy_pipeline(_: Any) -> bool:
    """Compatibility stub: relevance never skips the content pipeline."""
    return False
