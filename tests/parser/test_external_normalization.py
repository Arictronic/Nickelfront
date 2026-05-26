from __future__ import annotations

import unittest

from parsers_pkg.external.client import CrossrefClient, ELibraryClient, PatentScopeClient, RosPatentClient
from parsers_pkg.external.parser import ExternalParser
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


class TestArxivFullTextUrl(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_category_id_is_preserved(self):
        from parsers_pkg.arxiv.client import ArxivClient

        self.assertEqual(
            await ArxivClient().get_full_text("http://arxiv.org/abs/cond-mat/0601001v2"),
            "https://arxiv.org/pdf/cond-mat/0601001.pdf",
        )


if __name__ == "__main__":
    unittest.main()
