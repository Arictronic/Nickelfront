from types import SimpleNamespace

import pytest

from app.tasks import parse_tasks


def test_candidate_scan_window_is_bounded_by_global_limit() -> None:
    assert parse_tasks._candidate_scan_limit(10, {"max_limit": 100}) == 40
    assert parse_tasks._candidate_scan_limit(30, {"max_limit": 100}) == 100


@pytest.mark.asyncio
async def test_parse_fills_target_after_existing_candidates(monkeypatch) -> None:
    parser_limits: list[int] = []

    async def fake_parser_settings():
        return {
            "enabled": True,
            "max_limit": 100,
            "source_limits": {"OpenAlex": 20},
            "enabled_sources": {"OpenAlex": True},
        }

    async def fake_run_parser_alpha(**kwargs):
        parser_limits.append(kwargs["limit"])
        papers = [
            {"title": f"Old {index}", "source": "OpenAlex", "source_id": f"old-{index}"}
            for index in range(10)
        ]
        papers.extend(
            {"title": f"New {index}", "source": "OpenAlex", "source_id": f"new-{index}"}
            for index in range(20)
        )
        return {"raw_count": len(papers)}, papers

    async def fake_postprocess_settings():
        return {}

    class FakeSession:
        async def rollback(self):
            return None

    class FakeSessionContext:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakePaperService:
        def __init__(self, _db):
            pass

        async def create_paper(self, paper):
            created = not str(paper.source_id).startswith("old-")
            return SimpleNamespace(
                id=1,
                source=paper.source,
                source_id=paper.source_id,
                url=paper.url,
                pdf_url=paper.pdf_url,
                processing_status="pending",
                content_task_id=None,
                _nickelfront_created=created,
                _nickelfront_updated=False,
            )

    monkeypatch.setattr(parse_tasks, "_get_runtime_parser_settings", fake_parser_settings)
    monkeypatch.setattr(parse_tasks, "_run_parser_alpha", fake_run_parser_alpha)
    monkeypatch.setattr(parse_tasks, "_get_runtime_postprocess_settings", fake_postprocess_settings)
    monkeypatch.setattr(parse_tasks, "async_session_maker", lambda: FakeSessionContext())
    monkeypatch.setattr(parse_tasks, "PaperService", FakePaperService)

    result = await parse_tasks._parse_async(
        SimpleNamespace(),
        query="nickel",
        limit=10,
        source="OpenAlex",
    )

    assert parser_limits == [40]
    assert result["candidate_limit"] == 40
    assert result["examined_count"] == 20
    assert result["duplicate_count"] == 10
    assert result["saved_count"] == 10
    assert result["refill_exhausted"] is False
