from __future__ import annotations

import unittest

from parsers_pkg.core.parser import COREParser


class TestCOREParserEdgeCases(unittest.IsolatedAsyncioTestCase):
    async def test_core_parser_accepts_dict_and_string_shapes(self):
        parser = COREParser()
        records = await parser.parse_search_results(
            [
                {
                    "id": 123,
                    "title": "Nickel alloy CORE record",
                    "authors": {"name": "Alice Smith"},
                    "publishedDate": "2024-02-03",
                    "topics": "nickel alloys",
                    "fieldOfStudy": {"name": "metallurgy"},
                    "journals": {"title": "CORE Journal"},
                    "sourceFulltextUrls": {"url": "https://repo.example/core.pdf"},
                    "links": {"type": "reader", "url": "https://core.ac.uk/reader/123"},
                }
            ]
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].authors, ["Alice Smith"])
        self.assertEqual(records[0].keywords, ["nickel alloys", "metallurgy"])
        self.assertEqual(records[0].journal, "CORE Journal")
        self.assertEqual(records[0].pdf_url, "https://repo.example/core.pdf")
        self.assertEqual(records[0].url, "https://core.ac.uk/reader/123")

    async def test_core_parser_accepts_single_link_dict(self):
        parser = COREParser()
        records = await parser.parse_search_results(
            [
                {
                    "id": "abc",
                    "title": "Reader URL survives",
                    "authors": ["Bob Brown"],
                    "links": {"type": "download", "url": "https://core.ac.uk/download/abc.pdf"},
                }
            ]
        )

        self.assertEqual(records[0].url, "https://core.ac.uk/works/abc")
        self.assertEqual(records[0].pdf_url, "https://core.ac.uk/download/abc.pdf")

    async def test_core_parser_keeps_rows_with_list_title_and_missing_id(self):
        parser = COREParser()
        records = await parser.parse_search_results(
            [
                {
                    "id": None,
                    "title": ["Nickel list title"],
                    "abstract": {"value": "<p>CORE abstract</p>"},
                    "doi": {"value": "10.1000/CORE.1"},
                    "publishedDate": {"value": "2024-03-04"},
                }
            ]
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].title, "Nickel list title")
        self.assertEqual(records[0].abstract, "CORE abstract")
        self.assertEqual(records[0].doi, "10.1000/core.1")
        self.assertIsNone(records[0].source_id)
        self.assertEqual(records[0].url, "https://doi.org/10.1000/core.1")

    async def test_core_parser_preserves_inline_full_text_and_does_not_treat_landing_as_pdf(self):
        parser = COREParser()
        records = await parser.parse_search_results(
            [
                {
                    "id": "inline-1",
                    "title": "Full text record",
                    "fullText": "Body text " * 40,
                    "sourceFulltextUrls": ["https://repo.example/article-page"],
                }
            ]
        )

        self.assertGreater(len(records[0].full_text or ""), 200)
        self.assertEqual(records[0].url, "https://repo.example/article-page")
        self.assertIsNone(records[0].pdf_url)

    async def test_core_parser_drops_public_api_full_text_placeholder(self):
        parser = COREParser()
        records = await parser.parse_search_results(
            [
                {
                    "id": "restricted-1",
                    "title": "Metadata-only record",
                    "fullText": "Not available for public API users.",
                }
            ]
        )

        self.assertIsNone(records[0].full_text)


if __name__ == "__main__":
    unittest.main()
