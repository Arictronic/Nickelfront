from __future__ import annotations

import unittest

from parsers_pkg.source_executor import (
    _coerce_raw_list,
    _coerce_raw_records,
    _enrich_content_access,
    _quality_candidate_limit,
    _safe_event_dicts,
)
from parsers_pkg.contracts import ParserDiagnostics
from shared.schemas.paper import Paper


class TestSourceExecutorRobustness(unittest.TestCase):
    def test_safe_event_dicts_ignores_non_dict_events(self):
        events = _safe_event_dicts({"events": [None, "bad", {"severity": "warning"}]})
        self.assertEqual(events, [{"severity": "warning"}])

    def test_coerce_raw_list_wraps_single_payloads(self):
        self.assertEqual(_coerce_raw_list(None), [])
        self.assertEqual(_coerce_raw_list({"one": 1}), [{"one": 1}])
        self.assertEqual(_coerce_raw_list((1, 2)), [1, 2])

    def test_coerce_raw_records_filters_parser_unsafe_values(self):
        self.assertEqual(_coerce_raw_records({"one": 1}), [{"one": 1}])
        self.assertEqual(_coerce_raw_records(({"ok": True}, "bad", None)), [{"ok": True}])
        self.assertEqual(_coerce_raw_records("not a row"), [])

    def test_metadata_first_search_keeps_requested_candidate_limit(self):
        self.assertEqual(_quality_candidate_limit("OpenAlex", 2), 2)
        self.assertEqual(_quality_candidate_limit("Crossref", 1), 1)
        self.assertEqual(_quality_candidate_limit("EuropePMC", 2), 2)


class TestSameSourceContentAccessEnrichment(unittest.IsolatedAsyncioTestCase):
    async def test_missing_pdf_is_resolved_from_same_source_detail_method(self):
        paper = Paper(
            title="Nickel alloy",
            source="CORE",
            source_id="123",
            url="https://core.ac.uk/works/123",
        )

        class Client:
            async def get_full_text(self, item_id: str):
                self.item_id = item_id
                return "https://repo.example/paper.pdf"

        client = Client()
        papers = await _enrich_content_access(client, [paper])

        self.assertEqual(client.item_id, "123")
        self.assertEqual(papers[0].pdf_url, "https://repo.example/paper.pdf")
        self.assertIn("pdf_url_resolved_from_detail", papers[0].quality_flags)

    async def test_detail_text_is_kept_when_pdf_is_unavailable(self):
        paper = Paper(
            title="Patent",
            source="FreePatent",
            source_id="patents/1",
            url="https://www.freepatent.ru/patents/1",
        )
        body = "Full patent description " * 20

        class Client:
            async def get_full_text(self, item_id: str):
                return body

        papers = await _enrich_content_access(Client(), [paper])

        self.assertEqual(papers[0].full_text, body.strip())
        self.assertIn("full_text_extracted_from_detail", papers[0].quality_flags)

    async def test_article_page_without_pdf_or_text_is_kept_as_metadata(self):
        paper = Paper(
            title="Metadata only",
            source="Repository",
            source_id="metadata-only",
            url="https://repo.example/article",
        )

        papers = await _enrich_content_access(object(), [paper])

        self.assertEqual(papers, [paper])
        self.assertIn("content_access_unresolved", paper.quality_flags)

    async def test_ambiguous_pdf_candidate_must_be_verified(self):
        paper = Paper(
            title="Repository candidate",
            source="OpenAlex",
            source_id="W1",
            url="https://openalex.org/W1",
            pdf_url="https://repo.example/download/1",
        )

        class Client:
            detail_calls = 0

            async def verify_pdf_url(self, url: str):
                return None

            async def get_full_text(self, item_id: str):
                self.detail_calls += 1
                return None

        client = Client()
        diagnostics = ParserDiagnostics(source="OpenAlex")
        papers = await _enrich_content_access(client, [paper], diagnostics=diagnostics)

        self.assertEqual(papers, [paper])
        self.assertIn("pdf_url_unverified", paper.quality_flags)
        self.assertIn("content_access_unresolved", paper.quality_flags)
        self.assertEqual(client.detail_calls, 1)
        self.assertEqual(diagnostics.events[0].reason, "pdf_url_unverified")
        self.assertEqual(diagnostics.events[1].reason, "content_access_unresolved")
        self.assertEqual(len(diagnostics.events), 2)

    async def test_html_source_can_add_full_text_when_pdf_is_already_known(self):
        paper = Paper(
            title="HTML-backed article",
            source="CyberLeninka",
            source_id="article/demo",
            url="https://cyberleninka.ru/article/demo",
            pdf_url="https://cyberleninka.ru/article/demo/pdf",
        )
        body = "Extracted article text " * 20

        class Client:
            ENRICH_FULL_TEXT_WITH_PDF = True

            async def get_full_text(self, item_id: str):
                return body

        papers = await _enrich_content_access(Client(), [paper])

        self.assertEqual(papers[0].full_text, body.strip())
        self.assertIn("pdf_url_available", paper.quality_flags)
        self.assertIn("full_text_extracted_from_detail", paper.quality_flags)

    async def test_verified_download_endpoint_is_kept_as_pdf(self):
        paper = Paper(
            title="Publisher PDF",
            source="Crossref",
            source_id="10.1/a",
            url="https://doi.org/10.1/a",
            pdf_url="https://publisher.example/download/1",
        )

        class Client:
            async def verify_pdf_url(self, url: str):
                return "https://publisher.example/download/1"

        papers = await _enrich_content_access(Client(), [paper])

        self.assertEqual(len(papers), 1)
        self.assertIn("pdf_url_verified", paper.quality_flags)

    async def test_candidate_verification_stops_after_requested_results(self):
        papers = [
            Paper(
                title=f"Paper {index}",
                source="Crossref",
                source_id=str(index),
                url=f"https://publisher.example/article/{index}",
                pdf_url=f"https://publisher.example/download/{index}",
            )
            for index in range(3)
        ]

        class Client:
            calls = 0

            async def verify_pdf_url(self, url: str):
                self.calls += 1
                return url

        client = Client()
        results = await _enrich_content_access(client, papers, max_results=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(client.calls, 1)


if __name__ == "__main__":
    unittest.main()
