from __future__ import annotations

import unittest

from parsers_pkg.external.client import CrossrefClient, ELibraryClient, PatentScopeClient, RosPatentClient
from parsers_pkg.external.parser import ExternalParser
from parsers_pkg.errors import SourceUnavailableError
from parsers_pkg.russian.cyberleninka_client import CyberLeninkaClient
from parsers_pkg.russian.cyberleninka_parser import CyberLeninkaParser


class TestExternalParserNormalization(unittest.IsolatedAsyncioTestCase):
    async def test_string_authors_and_keywords_are_not_split_into_characters(self):
        parser = ExternalParser(source="OpenAlex")

        papers = await parser.parse_search_results([
            {
                "title": "Nickel alloy oxidation",
                "authors": "Alice Smith; Bob Jones",
                "keywords": "nickel, oxidation; superalloy",
                "published_date": "2024-01-02",
                "source": "OpenAlex",
                "source_id": "W123",
                "url": "https://openalex.org/W123",
            }
        ])

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].authors, ["Alice Smith", "Bob Jones"])
        self.assertEqual(papers[0].keywords, ["nickel", "oxidation", "superalloy"])

    async def test_author_list_items_with_commas_are_preserved(self):
        parser = ExternalParser(source="Crossref")

        papers = await parser.parse_search_results([
            {
                "title": "Nickel alloy authors",
                "authors": ["Smith, John", "Doe, Jane"],
                "keywords": ["nickel, oxidation", "superalloy"],
                "source": "Crossref",
                "source_id": "10.1000/authors.1",
                "doi": "10.1000/authors.1",
            }
        ])

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].authors, ["Smith, John", "Doe, Jane"])
        self.assertEqual(papers[0].keywords, ["nickel", "oxidation", "superalloy"])

    async def test_object_authors_and_scalar_fields_are_unwrapped(self):
        parser = ExternalParser(source="Crossref")

        papers = await parser.parse_search_results([
            {
                "title": {"value": "Nickel alloy object title"},
                "authors": [{"name": "Smith, John"}, {"fullName": "Doe, Jane"}],
                "keywords": [{"name": "nickel"}, {"value": "oxidation, corrosion"}],
                "published_date": {"value": "2024-03-01"},
                "journal": {"name": "Journal of Objects"},
                "doi": {"value": "10.1000/OBJ.1"},
                "abstract": {"text": "<p>Object abstract</p>"},
                "source": {"name": "Crossref"},
                "source_id": {"value": "10.1000/OBJ.1"},
                "url": {"url": "https://doi.org/10.1000/OBJ.1"},
            }
        ])

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].title, "Nickel alloy object title")
        self.assertEqual(papers[0].authors, ["Smith, John", "Doe, Jane"])
        self.assertEqual(papers[0].keywords, ["nickel", "oxidation", "corrosion"])
        self.assertEqual(papers[0].journal, "Journal of Objects")
        self.assertEqual(papers[0].doi, "10.1000/obj.1")
        self.assertEqual(papers[0].abstract, "Object abstract")


class TestCrossrefClientNormalization(unittest.IsolatedAsyncioTestCase):
    async def test_crossref_string_title_is_not_truncated_to_first_character(self):
        client = CrossrefClient()

        async def fake_request_json(path, params):
            return {
                "message": {
                    "items": [
                        {
                            "title": "Nickel superalloy corrosion study",
                            "container-title": "Journal of Alloys",
                            "issued": {"date-parts": [2024, 5, 1]},
                            "author": [{"given": "Alice", "family": "Smith"}],
                            "DOI": "10.1000/ABC.1",
                            "URL": "https://doi.org/10.1000/ABC.1",
                            "subject": ["nickel"],
                        }
                    ]
                }
            }

        client._request_json = fake_request_json
        rows = await client.search("nickel", limit=1)

        self.assertEqual(rows[0]["title"], "Nickel superalloy corrosion study")
        self.assertEqual(rows[0]["journal"], "Journal of Alloys")
        self.assertEqual(rows[0]["published_date"], "2024-05-01T00:00:00")


class TestCyberLeninkaNormalization(unittest.IsolatedAsyncioTestCase):
    async def test_client_and_parser_keep_string_authors_as_names(self):
        raw = {
            "articles": [
                {
                    "link": "/article/n/nickel-alloy",
                    "name": "Никелевые сплавы",
                    "authors": "Иванов И.И.; Петров П.П.",
                    "annotation": "Аннотация",
                    "journal": "Журнал",
                    "year": 2024,
                }
            ]
        }
        rows = CyberLeninkaClient()._parse_api_results(raw, limit=1)
        self.assertEqual(rows[0]["authors"], ["Иванов И.И.", "Петров П.П."])

        parser = CyberLeninkaParser()
        papers = await parser.parse_search_results(rows)
        self.assertEqual(papers[0].authors, ["Иванов И.И.", "Петров П.П."])


class TestELibrarySessionCookieNormalization(unittest.TestCase):
    def test_browser_cookie_list_export_builds_cookie_header(self):
        payload = [
            {"name": "SID", "value": "abc", "domain": ".elibrary.ru"},
            {"name": "OTHER", "value": "skip", "domain": ".example.com"},
            {"name": "session", "value": "xyz"},
        ]

        self.assertEqual(
            ELibraryClient._cookie_header_from_cookie_payload(payload),
            "SID=abc; session=xyz",
        )

    def test_item_detail_html_exposes_metadata_without_pdf_requirement(self):
        html = """
        <html><head>
          <meta name="citation_title" content="Nickel alloy article">
          <meta name="citation_author" content="Ivanov I.I.">
          <meta name="citation_author" content="Petrov P.P.">
          <meta name="citation_publication_date" content="2024-05-02">
          <meta name="citation_journal_title" content="Metallurgy Journal">
          <meta name="citation_doi" content="10.1000/ELIB.1">
          <meta name="citation_keywords" content="nickel; oxidation">
        </head><body><div id="abstract">Article abstract.</div></body></html>
        """

        details = ELibraryClient._parse_item_detail_metadata(
            html,
            "https://www.elibrary.ru/item.asp?id=1",
        )

        self.assertEqual(details["title"], "Nickel alloy article")
        self.assertEqual(details["authors"], ["Ivanov I.I.", "Petrov P.P."])
        self.assertEqual(details["doi"], "10.1000/elib.1")
        self.assertEqual(details["abstract"], "Article abstract.")
        self.assertEqual(details["keywords"], ["nickel", "oxidation"])


class TestELibrarySessionFailures(unittest.IsolatedAsyncioTestCase):
    async def test_page_error_redirect_is_reported_as_unavailable_session(self):
        client = ELibraryClient()

        async def fake_submit(query: str):
            return "<html><body>error</body></html>", "https://www.elibrary.ru/page_error.asp"

        client._submit_quick_search_form = fake_submit

        with self.assertRaises(SourceUnavailableError):
            await client.search("nickel", limit=1)

    async def test_search_timeout_is_reported_with_source_context(self):
        import httpx

        client = ELibraryClient()

        class FakeHTTPClient:
            async def get(self, *args, **kwargs):
                raise httpx.ReadTimeout("timed out")

        async def fake_get_client():
            return FakeHTTPClient()

        client._get_client = fake_get_client

        with self.assertRaisesRegex(SourceUnavailableError, "did not respond before timeout"):
            await client.search("nickel", limit=1)


class TestPatentScopePdfUrlNormalization(unittest.IsolatedAsyncioTestCase):
    async def test_documents_tab_url_is_not_returned_as_pdf_url(self):
        client = PatentScopeClient()

        async def fake_request_text(path, params=None):
            return "<html><body><a href='detail.jsf?docId=WO123&tab=DOCUMENTS'>Documents</a></body></html>"

        client._request_text = fake_request_text

        self.assertIsNone(await client._resolve_documents_pdf_url("WO123"))

    async def test_real_pdf_link_is_returned(self):
        client = PatentScopeClient()

        async def fake_request_text(path, params=None):
            return "<html><body><a href='../download/PCT/WO123.pdf'>PDF</a></body></html>"

        client._request_text = fake_request_text

        self.assertEqual(
            await client._resolve_documents_pdf_url("WO123"),
            "https://patentscope.wipo.int/search/download/PCT/WO123.pdf",
        )

class TestRospatentPdfUrlNormalization(unittest.IsolatedAsyncioTestCase):
    async def test_full_media_path_is_not_prefixed_with_base_url(self):
        client = RosPatentClient()

        async def fake_request_media_file_list(media_path):
            self.assertEqual(media_path, "https://media.example/documents/RU123")
            return ["main.pdf"]

        client._request_media_file_list = fake_request_media_file_list

        self.assertEqual(
            await client._resolve_pdf_url_from_doc({"ex_media_list": "https://media.example/documents/RU123"}),
            "https://media.example/documents/RU123/main.pdf",
        )

    async def test_xml_description_and_claims_are_extracted_as_full_text(self):
        payload = {
            "description": {"ru": "<pat:Description><p>" + ("Nickel alloy description. " * 12) + "</p></pat:Description>"},
            "claims": {"ru": "<pat:Claims><p>" + ("Nickel alloy claim. " * 8) + "</p></pat:Claims>"},
        }

        text = RosPatentClient._extract_full_text(payload)

        self.assertIsNotNone(text)
        self.assertIn("Nickel alloy description", text)
        self.assertIn("Nickel alloy claim", text)


class TestArxivFullTextUrl(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_category_id_is_preserved(self):
        from parsers_pkg.arxiv.client import ArxivClient

        self.assertEqual(
            await ArxivClient().get_full_text("http://arxiv.org/abs/cond-mat/0601001v2"),
            "https://arxiv.org/pdf/cond-mat/0601001.pdf",
        )

    async def test_search_identifies_application_to_api(self):
        from parsers_pkg.arxiv.client import ArxivClient

        client = ArxivClient(rate_limit=False)
        captured_headers: dict[str, str] = {}

        class FakeResponse:
            status_code = 200
            headers: dict[str, str] = {}
            text = "<feed xmlns='http://www.w3.org/2005/Atom'></feed>"

        class FakeClient:
            async def get(self, url, params=None, headers=None):
                captured_headers.update(headers or {})
                return FakeResponse()

        async def fake_get_client():
            return FakeClient()

        client._get_client = fake_get_client
        await client.search("nickel", limit=1)

        self.assertEqual(captured_headers["User-Agent"], client.USER_AGENT)


if __name__ == "__main__":
    unittest.main()
