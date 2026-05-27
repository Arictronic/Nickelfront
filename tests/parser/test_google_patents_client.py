from __future__ import annotations

import unittest

from parsers_pkg.external.client import GooglePatentsClient


class TestGooglePatentsClient(unittest.IsolatedAsyncioTestCase):
    def test_publication_id_is_read_from_id_or_detail_url(self):
        self.assertEqual(GooglePatentsClient._publication_id_from_query("US 10,597,755 B2"), "US10597755B2")
        self.assertEqual(
            GooglePatentsClient._publication_id_from_query(
                "https://patents.google.com/patent/WO2020123456A1/en"
            ),
            "WO2020123456A1",
        )
        self.assertIsNone(GooglePatentsClient._publication_id_from_query("nickel alloy"))

    def test_detail_html_extracts_metadata_text_and_pdf(self):
        html = """
        <html><head>
          <meta name="DC.title" content="Nickel alloy component">
          <meta name="DC.description" content="Patent abstract">
          <meta name="DC.contributor" scheme="inventor" content="Alice Smith">
          <meta name="DC.contributor" scheme="assignee" content="Example Inc">
          <meta name="DC.date" scheme="issue" content="2024-05-02">
          <meta name="citation_pdf_url" content="https://patentimages.example/patent.pdf">
        </head><body>
          <section itemprop="description">{description}</section>
          <section itemprop="claims">{claims}</section>
        </body></html>
        """.format(
            description="Detailed description of nickel alloy processing. " * 10,
            claims="What is claimed is a nickel alloy component. " * 10,
        )

        record = GooglePatentsClient._parse_detail_html(html, "US123456B2")

        self.assertEqual(record["title"], "Nickel alloy component")
        self.assertEqual(record["authors"], ["Alice Smith"])
        self.assertEqual(record["published_date"], "2024-05-02")
        self.assertEqual(record["abstract"], "Patent abstract")
        self.assertEqual(record["pdf_url"], "https://patentimages.example/patent.pdf")
        self.assertGreater(len(record["full_text"]), 200)

    def test_extract_publication_ids_from_search_html(self):
        html = """
        <html><body>
          <a href="/patent/US10597755B2/en">one</a>
          <a href="https://patents.google.com/patent/WO2020123456A1/en">two</a>
          <a href="/patent/US10597755B2/en?oq=dup">dup</a>
          <a href="/not-a-patent/path">skip</a>
        </body></html>
        """
        ids = GooglePatentsClient._extract_publication_ids_from_search_html(html)
        self.assertEqual(ids, ["US10597755B2", "WO2020123456A1"])

    def test_extract_publication_ids_from_internal_search_payload(self):
        payload = {
            "results": {
                "cluster": [
                    {"result": [{"id": "patent/US10597755B2/en"}, {"id": "patent/WO2020123456A1/en"}]}
                ]
            }
        }

        ids = GooglePatentsClient._extract_publication_ids_from_search_payload(payload)
        self.assertEqual(ids, ["US10597755B2", "WO2020123456A1"])

    async def test_search_reads_detail_page_for_publication_number(self):
        client = GooglePatentsClient()
        paths: list[str] = []

        async def fake_request_text(path: str, params=None) -> str:
            paths.append(path)
            return '<meta name="DC.title" content="Patent title">'

        client._request_text = fake_request_text

        records = await client.search("US10597755B2", limit=1)

        self.assertEqual(paths, ["/patent/US10597755B2/en"])
        self.assertEqual(records[0]["source"], "GooglePatents")
        self.assertEqual(records[0]["source_id"], "US10597755B2")

    async def test_search_keyword_query_uses_search_page_and_detail_pages(self):
        client = GooglePatentsClient()
        calls: list[tuple[str, dict | None]] = []

        async def fake_request_json(path: str, params=None) -> dict:
            calls.append((path, params))
            return {
                "results": {
                    "cluster": [
                        {"result": [{"id": "patent/US10597755B2/en"}, {"id": "patent/WO2020123456A1/en"}]}
                    ]
                }
            }

        async def fake_request_text(path: str, params=None) -> str:
            if path == "/patent/US10597755B2/en":
                return '<meta name="DC.title" content="US patent title">'
            if path == "/patent/WO2020123456A1/en":
                return '<meta name="DC.title" content="WO patent title">'
            return ""

        client._request_json = fake_request_json
        client._request_text = fake_request_text
        records = await client.search("title:(battery) abstract:(solid-state)", limit=2, offset=0)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["source_id"], "US10597755B2")
        self.assertEqual(records[1]["source_id"], "WO2020123456A1")
        self.assertEqual(calls[0][0], "/xhr/query")
        self.assertEqual(
            calls[0][1],
            {
                "url": "q=title%3A%28battery%29+abstract%3A%28solid-state%29&num=100&page=0&hl=en",
            },
        )


if __name__ == "__main__":
    unittest.main()
