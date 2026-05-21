from __future__ import annotations

import unittest
from unittest.mock import patch

import run_parser


class TestRunParserUrlResolution(unittest.TestCase):
    @patch("run_parser._resolve_doi_redirect", return_value="https://publisher.example/paper.pdf")
    def test_doi_redirect_to_pdf_moves_pdf_to_pdf_url(self, _mock_resolve):
        records = [
            {
                "source": "Crossref",
                "doi": "10.1000/ABC.1",
                "source_id": "10.1000/ABC.1",
                "url": "https://doi.org/10.1000/ABC.1",
                "pdf_url": None,
            }
        ]

        normalized, dropped, doi_resolved, pdf_promoted = run_parser._enforce_article_url(records)

        self.assertEqual(dropped, 0)
        self.assertEqual(doi_resolved, 1)
        self.assertEqual(pdf_promoted, 1)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["url"], "https://doi.org/10.1000/ABC.1")
        self.assertEqual(normalized[0]["pdf_url"], "https://publisher.example/paper.pdf")

    @patch(
        "run_parser._resolve_doi_redirect",
        return_value="https://europepmc.org/articles/PMC13080576?pdf=render",
    )
    def test_europepmc_pdf_query_is_split_into_article_and_pdf(self, _mock_resolve):
        records = [
            {
                "source": "EuropePMC",
                "doi": "10.1111/cod.70140",
                "source_id": "PMC:PMC13080576",
                "url": "https://europepmc.org/articles/PMC13080576?pdf=render",
                "pdf_url": None,
            }
        ]

        normalized, dropped, doi_resolved, pdf_promoted = run_parser._enforce_article_url(records)

        self.assertEqual(dropped, 0)
        self.assertEqual(doi_resolved, 0)
        self.assertEqual(pdf_promoted, 1)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["url"], "https://europepmc.org/articles/PMC13080576")
        self.assertEqual(normalized[0]["pdf_url"], "https://europepmc.org/articles/PMC13080576?pdf=render")

    def test_merge_records_by_dedupe_uses_canonical_patent_id(self):
        records = [
            {
                "source": "Rospatent",
                "journal": "Rospatent",
                "source_id": "RU123456",
                "title": "Состав никелевого сплава",
                "url": "https://searchplatform.rospatent.gov.ru/doc/RU123456",
                "abstract": None,
            },
            {
                "source": "FreePatent",
                "journal": "FreePatent",
                "source_id": "patents/123456",
                "title": "Патент 123456",
                "url": "https://www.freepatent.ru/patents/123456",
                "abstract": "Описание патента",
            },
        ]

        merged = run_parser._merge_records_by_dedupe(records, limit=10)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source_id"], "RU123456")
        self.assertEqual(merged[0]["abstract"], "Описание патента")


if __name__ == "__main__":
    unittest.main()

class TestRunParserDiagnosticsRobustness(unittest.TestCase):
    def test_diagnostic_event_dicts_filters_non_dict_events(self):
        events = run_parser._diagnostic_event_dicts({"events": [None, "bad", {"stage": "parse"}]})
        self.assertEqual(events, [{"stage": "parse"}])

    def test_diagnostic_list_field_ignores_non_list_values(self):
        self.assertEqual(run_parser._diagnostic_list_field({"degraded_reasons": "bad"}, "degraded_reasons"), [])
        self.assertEqual(run_parser._diagnostic_list_field({"degraded_reasons": ["rate_limited"]}, "degraded_reasons"), ["rate_limited"])
