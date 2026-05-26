
"""Manual/external checks for Russian sources (CyberLeninka and eLibrary).

These tests use live external sites, so they are marked as ``external`` and are skipped
by the default pytest configuration. Run explicitly with: ``pytest -m external``.
"""

import asyncio
import json
from pathlib import Path

import pytest

from parsers_pkg.source_config import load_source_runtime_config_with_metadata
from parsers_pkg.source_executor import execute_source_search
from parsers_pkg.sources import build_default_source_registry

pytestmark = pytest.mark.external


def _dump_paper(paper):
    if hasattr(paper, "model_dump"):
        return paper.model_dump(mode="json")
    if hasattr(paper, "dict"):
        return paper.dict()
    return paper


async def _run_source(source: str, query: str, limit: int = 5):
    registry = build_default_source_registry()
    metadata = registry.get(source)
    runtime_config = load_source_runtime_config_with_metadata(source, metadata)
    return await execute_source_search(
        query=query,
        source=source,
        limit=limit,
        runtime_config=runtime_config,
    )


async def test_cyberleninka():
    query = "машинное обучение"
    result = await _run_source("CyberLeninka", query=query, limit=5)
    assert result.source == "CyberLeninka"
    assert isinstance(result.papers, list)

    Path("test_cyberleninka_results.json").write_text(
        json.dumps([_dump_paper(p) for p in result.papers], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def test_elibrary():
    query = "искусственный интеллект"
    result = await _run_source("eLibrary", query=query, limit=5)
    assert result.source == "eLibrary"
    assert isinstance(result.papers, list)

    Path("test_elibrary_results.json").write_text(
        json.dumps([_dump_paper(p) for p in result.papers], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def main():
    for source, query in [
        ("CyberLeninka", "машинное обучение"),
        ("eLibrary", "искусственный интеллект"),
    ]:
        result = await _run_source(source, query=query, limit=5)
        print(f"{source}: raw={result.raw_count}, parsed={len(result.papers)}")
        if result.papers:
            first = _dump_paper(result.papers[0])
            print(json.dumps(first, ensure_ascii=False, indent=2)[:2000])


if __name__ == "__main__":
    asyncio.run(main())
