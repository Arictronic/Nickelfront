from __future__ import annotations

import unittest
from unittest.mock import patch

from parsers_pkg.external.client import CrossrefClient, EuropePMCClient, OpenAlexClient, RosPatentClient
from parsers_pkg.sources import build_default_source_registry


class TestExternalClientEdgeCases(unittest.IsolatedAsyncioTestCase):
    async def test_crossref_extracts_name_author_subjects_and_pdf_link(self):
        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Nickel alloy processing"],
                        "author": [
                            {"given": "Alice", "family": "Smith"},
                            {"name": "The Materials Consortium"},
                        ],
                        "issued": {"date-parts": [[2024, 5, 2]]},
                        "container-title": "Journal of Alloys",
                        "DOI": "10.1000/NICKEL.1",
                        "subject": "metallurgy",
                        "URL": "https://doi.org/10.1000/NICKEL.1",
                        "link": [
                            {"URL": "https://publisher.example/article", "content-type": "text/html"},
                            {"URL": "https://publisher.example/article.pdf", "content-type": "application/pdf"},
                        ],
                    }
                ]
            }
        }

        client = CrossrefClient()

        async def fake_request_json(path: str, params: dict):
            return payload

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source_id"], "10.1000/nickel.1")
        self.assertEqual(records[0]["authors"], ["Alice Smith", "The Materials Consortium"])
        self.assertEqual(records[0]["keywords"], ["metallurgy"])
        self.assertEqual(records[0]["journal"], "Journal of Alloys")
        self.assertEqual(records[0]["pdf_url"], "https://publisher.example/article.pdf")

    async def test_crossref_accepts_single_author_dict(self):
        client = CrossrefClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "message": {
                    "items": [
                        {
                            "title": "Nickel patent review",
                            "author": {"given": "Ivan", "family": "Petrov"},
                            "issued": {"date-parts": [2023]},
                            "URL": "https://doi.org/10.1000/example",
                        }
                    ]
                }
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["authors"], ["Ivan Petrov"])
        self.assertEqual(records[0]["title"], "Nickel patent review")

    async def test_openalex_uses_best_oa_location_when_primary_location_is_empty(self):
        client = OpenAlexClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W123",
                        "display_name": "Open nickel alloys",
                        "doi": "https://doi.org/10.1000/open.1",
                        "publication_date": "2024-01-01",
                        "authorships": [{"author": {"display_name": "A. Author"}}],
                        "primary_location": None,
                        "best_oa_location": {
                            "pdf_url": "https://repo.example/open.pdf",
                            "landing_page_url": "https://repo.example/open",
                            "source": {"display_name": "Repository"},
                        },
                        "locations": [],
                    }
                ]
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["pdf_url"], "https://repo.example/open.pdf")
        self.assertEqual(records[0]["url"], "https://repo.example/open")
        self.assertEqual(records[0]["journal"], "Repository")

    async def test_europepmc_accepts_single_fulltext_url_dict(self):
        client = EuropePMCClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "resultList": {
                    "result": [
                        {
                            "id": "12345",
                            "source": "PMC",
                            "title": "PMC nickel paper",
                            "pubYear": "2024",
                            "fullTextUrlList": {
                                "fullTextUrl": {
                                    "documentStyle": "pdf",
                                    "url": "https://pmc.example/paper.pdf",
                                }
                            },
                        }
                    ]
                }
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["source_id"], "PMC:12345")
        self.assertEqual(records[0]["pdf_url"], "https://pmc.example/paper.pdf")


class TestExternalSourceMetadata(unittest.TestCase):
    def test_pdf_capabilities_match_new_extractors(self):
        registry = build_default_source_registry()
        self.assertTrue(registry.get("OpenAlex").capabilities.pdf_url)
        self.assertTrue(registry.get("Crossref").capabilities.pdf_url)


class TestMetadataFirstSearchPolicies(unittest.IsolatedAsyncioTestCase):
    async def test_openalex_does_not_require_pdf_content(self):
        client = OpenAlexClient()
        params_seen: dict = {}

        async def fake_request_json(path: str, params: dict):
            params_seen.update(params)
            return {"results": []}

        client._request_json = fake_request_json
        await client.search("nickel", limit=1)

        self.assertNotIn("filter", params_seen)

    async def test_crossref_does_not_require_pdf_full_text_links(self):
        client = CrossrefClient()
        params_seen: dict = {}

        async def fake_request_json(path: str, params: dict):
            params_seen.update(params)
            return {"message": {"items": []}}

        client._request_json = fake_request_json
        await client.search("nickel", limit=1)

        self.assertNotIn("filter", params_seen)

    async def test_europepmc_does_not_require_open_pdf_records(self):
        client = EuropePMCClient()
        params_seen: dict = {}

        async def fake_request_json(path: str, params: dict):
            params_seen.update(params)
            return {"resultList": {"result": []}}

        client._request_json = fake_request_json
        await client.search("nickel", limit=1)

        self.assertEqual(params_seen["query"], "nickel")

    async def test_openalex_uses_official_content_url_without_persisting_key(self):
        with patch.dict("os.environ", {"OPENALEX_API_KEY": "secret-key"}):
            client = OpenAlexClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W123",
                        "display_name": "Official content paper",
                        "has_content": {"pdf": True},
                        "best_oa_location": {"pdf_url": "https://repo.example/fallback.pdf"},
                    }
                ]
            }

        client._request_json = fake_request_json
        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["pdf_url"], "https://content.openalex.org/works/W123.pdf")
        self.assertNotIn("secret-key", records[0]["pdf_url"])
        self.assertIn("pdf_url_via_openalex_content_api", records[0]["quality_flags"])


class TestExternalClientRound11Robustness(unittest.IsolatedAsyncioTestCase):
    async def test_openalex_uses_open_access_oa_url_pdf_as_pdf_not_article_url(self):
        client = OpenAlexClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W999",
                        "display_name": "OA PDF only",
                        "open_access": {"oa_url": "https://repo.example/paper.pdf"},
                    }
                ]
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["pdf_url"], "https://repo.example/paper.pdf")
        self.assertEqual(records[0]["url"], "https://openalex.org/W999")

    async def test_crossref_accepts_non_string_abstract_payload(self):
        client = CrossrefClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "message": {
                    "items": [
                        {
                            "title": ["Dict abstract"],
                            "abstract": {"value": "<jats:p>Nickel alloy abstract</jats:p>"},
                            "URL": "https://doi.org/10.1000/dict.abstract",
                        }
                    ]
                }
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["abstract"], "Nickel alloy abstract")

    async def test_europepmc_semicolon_authors_keep_comma_inside_name(self):
        client = EuropePMCClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "resultList": {
                    "result": [
                        {
                            "id": "123",
                            "source": "MED",
                            "title": "Author delimiter drift",
                            "authorString": "Smith, John; Doe, Jane",
                        }
                    ]
                }
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["authors"], ["Smith, John", "Doe, Jane"])

class TestExternalClientRound12Robustness(unittest.IsolatedAsyncioTestCase):
    async def test_europepmc_without_source_id_uses_doi_url_not_fake_article_url(self):
        client = EuropePMCClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "resultList": {
                    "result": [
                        {
                            "source": "MED",
                            "title": "DOI only EuropePMC row",
                            "doi": "10.1000/EPMC.DOI",
                        }
                    ]
                }
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertIsNone(records[0]["source_id"])
        self.assertEqual(records[0]["url"], "https://doi.org/10.1000/epmc.doi")

    async def test_europepmc_accepts_dict_abstract_text(self):
        client = EuropePMCClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "resultList": {
                    "result": [
                        {
                            "id": "123",
                            "source": "MED",
                            "title": "Dict abstract EuropePMC",
                            "abstractText": {"value": "<p>Nickel abstract</p>"},
                        }
                    ]
                }
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["abstract"], "Nickel abstract")


class TestExternalClientMalformedPayloads(unittest.IsolatedAsyncioTestCase):
    async def test_openalex_handles_none_authorships_and_concepts(self):
        client = OpenAlexClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W999",
                        "display_name": "Sparse OpenAlex row",
                        "doi": None,
                        "publication_date": "2024-01-01",
                        "authorships": [None, {"author": None}, {"author_display_name": "Fallback Name"}],
                        "concepts": None,
                        "locations": [],
                    }
                ]
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["authors"], ["Fallback Name"])
        self.assertEqual(records[0]["keywords"], [])
        self.assertEqual(records[0]["source_id"], "W999")

    async def test_openalex_get_full_text_uses_best_oa_location(self):
        client = OpenAlexClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "primary_location": None,
                "best_oa_location": {"pdf_url": "https://repo.example/best.pdf"},
            }

        client._request_json = fake_request_json

        self.assertEqual(await client.get_full_text("W123"), "https://repo.example/best.pdf")

    async def test_crossref_ignores_non_dict_message_without_crashing(self):
        client = CrossrefClient()

        async def fake_request_json(path: str, params: dict):
            return {"message": []}

        client._request_json = fake_request_json

        self.assertEqual(await client.search("nickel", limit=1), [])

class TestExternalClientRobustPayloadsRound8(unittest.IsolatedAsyncioTestCase):
    async def test_crossref_accepts_non_dict_indexed_and_normalizes_doi(self):
        client = CrossrefClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "message": {
                    "items": [
                        {
                            "title": ["DOI normalization"],
                            "author": [],
                            "issued": {"date-parts": [[2024]]},
                            "DOI": "DOI: 10.1000/ABC.1.",
                            "indexed": "not-a-dict",
                            "URL": ["https://doi.org/10.1000/ABC.1"],
                        }
                    ]
                }
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["doi"], "10.1000/abc.1")
        self.assertEqual(records[0]["source_id"], "10.1000/abc.1")
        self.assertEqual(records[0]["url"], "https://doi.org/10.1000/ABC.1")

    async def test_europepmc_accepts_single_result_dict_and_author_list(self):
        client = EuropePMCClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "resultList": {
                    "result": {
                        "id": "98765",
                        "source": "MED",
                        "title": ["Nickel toxicity"],
                        "authorString": ["Ivanov I.I.", "Petrov P.P."],
                        "pubYear": "2023",
                        "doi": "https://doi.org/10.1000/EPMC.2",
                        "abstractText": "<p>Abstract text</p>",
                    }
                }
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["authors"], ["Ivanov I.I.", "Petrov P.P."])
        self.assertEqual(records[0]["doi"], "10.1000/epmc.2")
        self.assertEqual(records[0]["source_id"], "MED:98765")
        self.assertEqual(records[0]["abstract"], "Abstract text")

    async def test_europepmc_ignores_malformed_result_list_without_crashing(self):
        client = EuropePMCClient()

        async def fake_request_json(path: str, params: dict):
            return {"resultList": []}

        client._request_json = fake_request_json

        self.assertEqual(await client.search("nickel", limit=1), [])

    async def test_rospatent_ignores_non_dict_nested_payloads(self):
        from parsers_pkg.external.client import RosPatentClient

        client = RosPatentClient()

        async def fake_request_json_post(path: str, payload: dict):
            return {
                "hits": [
                    {
                        "id": "RU123456",
                        "common": ["bad"],
                        "biblio": "bad",
                        "snippet": {"title": "Nickel alloy patent", "description": "nickel alloy"},
                        "meta": {"source": "bad"},
                        "dataset": "inventions_db",
                    }
                ]
            }

        async def fake_fetch_doc_payload(source_id: str):
            return {"abstract": "bad", "biblio": []}

        client._request_json_post = fake_request_json_post
        client._fetch_doc_payload = fake_fetch_doc_payload

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["source_id"], "RU123456")
        self.assertEqual(records[0]["title"], "Nickel alloy patent")

class TestExternalClientRound9Robustness(unittest.IsolatedAsyncioTestCase):
    async def test_openalex_accepts_numeric_id_and_string_positions_in_abstract_index(self):
        client = OpenAlexClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "results": [
                    {
                        "id": 123456,
                        "display_name": ["Numeric OpenAlex id"],
                        "publication_date": ["2024-01-02"],
                        "abstract_inverted_index": {
                            "Nickel": ["0"],
                            "alloy": [1],
                            "study": "2",
                            "bad": ["x"],
                        },
                    }
                ]
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["source_id"], "123456")
        self.assertEqual(records[0]["title"], "Numeric OpenAlex id")
        self.assertEqual(records[0]["published_date"], "2024-01-02")
        self.assertEqual(records[0]["abstract"], "Nickel alloy study")

    async def test_rospatent_resolves_media_path_from_list_dict_shape(self):
        from parsers_pkg.external.client import RosPatentClient

        client = RosPatentClient()
        seen_paths: list[str] = []

        async def fake_request_media_file_list(media_path: str):
            seen_paths.append(media_path)
            return ["main.pdf"]

        client._request_media_file_list = fake_request_media_file_list

        url = await client._resolve_pdf_url_from_doc({"ex_media_list": [{"path": "/media/RU123"}]})

        self.assertEqual(seen_paths, ["/media/RU123"])
        self.assertEqual(url, "https://searchplatform.rospatent.gov.ru/media/RU123/main.pdf")

class TestExternalClientRound10Robustness(unittest.IsolatedAsyncioTestCase):
    async def test_crossref_get_full_text_requires_valid_doi(self):
        client = CrossrefClient()

        self.assertEqual(await client.get_full_text("DOI: 10.1000/ABC.1."), "https://doi.org/10.1000/abc.1")
        self.assertIsNone(await client.get_full_text("2024-01-01T00:00:00"))

    async def test_crossref_subject_dict_does_not_become_python_repr_keyword(self):
        client = CrossrefClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "message": {
                    "items": [
                        {
                            "title": ["Dict subject"],
                            "subject": [{"name": "Metallurgy"}, {"display_name": "Nickel alloys"}],
                            "URL": "https://doi.org/10.1000/dict.subject",
                        }
                    ]
                }
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["keywords"], ["Metallurgy", "Nickel alloys"])
        self.assertNotIn("{'name':", " ".join(records[0]["keywords"]))

    async def test_openalex_get_full_text_accepts_full_work_url(self):
        client = OpenAlexClient()
        requested_paths: list[str] = []

        async def fake_request_json(path: str, params: dict):
            requested_paths.append(path)
            return {"best_oa_location": {"landing_page_url": "https://repo.example/work"}}

        client._request_json = fake_request_json

        self.assertEqual(await client.get_full_text("https://openalex.org/W123456"), "https://repo.example/work")
        self.assertEqual(requested_paths, ["/works/W123456"])

    async def test_rospatent_media_file_list_accepts_dict_payload(self):
        from parsers_pkg.external.client import RosPatentClient

        client = RosPatentClient()

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"files": [{"name": "main.pdf"}, {"filename": "extra.txt"}]}

        class FakeClient:
            async def get(self, path, headers=None):
                return FakeResponse()

        async def fake_get_client():
            return FakeClient()

        client._get_client = fake_get_client

        self.assertEqual(await client._request_media_file_list("/media/RU123"), ["main.pdf", "extra.txt"])


class TestExternalClientRound13Robustness(unittest.IsolatedAsyncioTestCase):
    async def test_patentscope_unquotes_doc_id_and_does_not_double_encode(self):
        from parsers_pkg.external.client import PatentScopeClient

        client = PatentScopeClient()
        seen_doc_ids: list[str] = []

        async def fake_resolve_documents_pdf_url(doc_id: str):
            seen_doc_ids.append(doc_id)
            return None

        class FakeResponse:
            url = "https://patentscope.wipo.int/search/en/detail.jsf?docId=PCT%2FUS2024%2F000001"
            text = "<html><head><title>WIPO - Search</title></head><body></body></html>"

            def raise_for_status(self):
                return None

        class FakeClient:
            async def get(self, *args, **kwargs):
                return FakeResponse()

        async def fake_get_client():
            return FakeClient()

        client._get_client = fake_get_client
        client._resolve_documents_pdf_url = fake_resolve_documents_pdf_url

        records = await client.search("PCT/US2024/000001", limit=1)

        self.assertEqual(seen_doc_ids, ["PCT/US2024/000001"])
        self.assertEqual(records[0]["source_id"], "PCT/US2024/000001")
        self.assertIn("docId=PCT%2FUS2024%2F000001", records[0]["url"])
        self.assertNotIn("%252F", records[0]["url"])
        self.assertEqual(
            await client.get_full_text("PCT%2FUS2024%2F000001"),
            "https://patentscope.wipo.int/search/en/detail.jsf?docId=PCT%2FUS2024%2F000001",
        )

    async def test_rospatent_accepts_elasticsearch_hits_shape_and_dict_inventor(self):
        from parsers_pkg.external.client import RosPatentClient

        client = RosPatentClient()

        async def fake_request_json_post(path: str, payload: dict):
            return {
                "hits": {
                    "total": {"value": 1},
                    "hits": [
                        {
                            "id": "RU987654",
                            "common": {"document_number": "RU987654", "publication_date": "2024.05.01"},
                            "biblio": {"ru": {"title": "Никелевый сплав", "inventor": {"name": "Иванов И.И."}}},
                            "snippet": {"description": "никелевый сплав"},
                            "dataset": "inventions_db",
                        }
                    ],
                }
            }

        async def fake_fetch_doc_payload(source_id: str):
            return None

        client._request_json_post = fake_request_json_post
        client._fetch_doc_payload = fake_fetch_doc_payload

        records = await client.search("никелевый сплав", limit=1)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source_id"], "RU987654")
        self.assertEqual(records[0]["authors"], ["Иванов И.И."])


class TestExternalClientRound15Robustness(unittest.IsolatedAsyncioTestCase):
    async def test_rospatent_unwraps_elasticsearch_source_hit(self):
        from parsers_pkg.external.client import RosPatentClient

        client = RosPatentClient()

        async def fake_request_json_post(path: str, payload: dict):
            return {
                "hits": {
                    "hits": [
                        {
                            "_id": "RU555777",
                            "_source": {
                                "common": {
                                    "document_number": {"value": "RU555777"},
                                    "publication_date": {"value": "2024.05.01"},
                                    "kind": {"value": "C1"},
                                },
                                "biblio": {
                                    "ru": {
                                        "title": {"value": "Никелевый жаропрочный сплав"},
                                        "inventor": {"name": "Иванов И.И."},
                                    }
                                },
                                "snippet": {"description": {"text": "никелевый жаропрочный сплав"}},
                                "dataset": {"value": "inventions_db"},
                            },
                        }
                    ]
                }
            }

        async def fake_fetch_doc_payload(source_id: str):
            return None

        client._request_json_post = fake_request_json_post
        client._fetch_doc_payload = fake_fetch_doc_payload

        records = await client.search("никелевый сплав", limit=1)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source_id"], "RU555777")
        self.assertEqual(records[0]["title"], "Никелевый жаропрочный сплав")
        self.assertEqual(records[0]["authors"], ["Иванов И.И."])
        self.assertEqual(records[0]["published_date"], "2024-05-01T00:00:00")
        self.assertIn("C1", records[0]["keywords"])

    async def test_openalex_accepts_object_urls_and_string_source_name(self):
        client = OpenAlexClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W777",
                        "display_name": {"value": "Object-shaped OpenAlex row"},
                        "primary_location": {
                            "pdf_url": {"url": "https://repo.example/paper.pdf"},
                            "landing_page_url": {"url": "https://repo.example/paper"},
                            "source": "Repository Name",
                        },
                    }
                ]
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["title"], "Object-shaped OpenAlex row")
        self.assertEqual(records[0]["pdf_url"], "https://repo.example/paper.pdf")
        self.assertEqual(records[0]["url"], "https://repo.example/paper")
        self.assertEqual(records[0]["journal"], "Repository Name")

    async def test_crossref_and_europepmc_do_not_stringify_object_urls(self):
        crossref = CrossrefClient()

        async def fake_crossref_json(path: str, params: dict):
            return {
                "message": {
                    "items": [
                        {
                            "title": [{"value": "Object URL Crossref"}],
                            "URL": {"url": "https://doi.org/10.1000/object.url"},
                            "link": {"URL": {"url": "https://publisher.example/paper.pdf"}, "content-type": "application/pdf"},
                        }
                    ]
                }
            }

        crossref._request_json = fake_crossref_json
        crossref_records = await crossref.search("nickel", limit=1)

        self.assertEqual(crossref_records[0]["title"], "Object URL Crossref")
        self.assertEqual(crossref_records[0]["url"], "https://doi.org/10.1000/object.url")
        self.assertEqual(crossref_records[0]["pdf_url"], "https://publisher.example/paper.pdf")
        self.assertNotIn("{'url'", crossref_records[0]["pdf_url"])

        europepmc = EuropePMCClient()

        async def fake_europepmc_json(path: str, params: dict):
            return {
                "resultList": {
                    "result": [
                        {
                            "id": "123",
                            "source": "PMC",
                            "title": {"value": "Object URL EuropePMC"},
                            "fullTextUrlList": {
                                "fullTextUrl": {
                                    "documentStyle": "pdf",
                                    "url": {"value": "https://pmc.example/object.pdf"},
                                }
                            },
                        }
                    ]
                }
            }

        europepmc._request_json = fake_europepmc_json
        epmc_records = await europepmc.search("nickel", limit=1)

        self.assertEqual(epmc_records[0]["title"], "Object URL EuropePMC")
        self.assertEqual(epmc_records[0]["pdf_url"], "https://pmc.example/object.pdf")
        self.assertNotIn("{'value'", epmc_records[0]["pdf_url"])

class TestExternalClientRound17Robustness(unittest.IsolatedAsyncioTestCase):
    async def test_openalex_accepts_object_open_access_oa_url_pdf(self):
        client = OpenAlexClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W1717",
                        "display_name": "Object open access PDF",
                        "open_access": {"oa_url": {"url": "https://repo.example/object-oa.pdf"}},
                    }
                ]
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["pdf_url"], "https://repo.example/object-oa.pdf")
        self.assertEqual(records[0]["url"], "https://openalex.org/W1717")
        self.assertNotIn("{'url'", records[0]["pdf_url"])

    async def test_europepmc_extracts_nested_author_list(self):
        client = EuropePMCClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "resultList": {
                    "result": [
                        {
                            "id": "1717",
                            "source": "MED",
                            "title": "Nested EuropePMC authorList",
                            "authorList": {
                                "author": [
                                    {"fullName": "Smith, John"},
                                    {"firstName": "Jane", "lastName": "Doe", "fullName": "Doe, Jane"},
                                ]
                            },
                        }
                    ]
                }
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["authors"], ["Smith, John", "Doe, Jane"])
        self.assertNotIn("{'author'", " ".join(records[0]["authors"]))

    async def test_crossref_author_name_parts_can_be_object_wrapped(self):
        client = CrossrefClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "message": {
                    "items": [
                        {
                            "title": "Object wrapped Crossref authors",
                            "author": [
                                {"given": {"value": "Alice"}, "family": {"value": "Smith"}},
                                {"organization": {"name": "Nickel Research Group"}},
                            ],
                        }
                    ]
                }
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["authors"], ["Alice Smith", "Nickel Research Group"])
        self.assertNotIn("{'value'", " ".join(records[0]["authors"]))

    async def test_crossref_zero_month_day_keeps_year_date(self):
        client = CrossrefClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "message": {
                    "items": [
                        {
                            "title": "Partial Crossref date",
                            "issued": {"date-parts": [[2024, 0, 0]]},
                        }
                    ]
                }
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["published_date"], "2024-01-01T00:00:00")

    async def test_get_full_text_keeps_full_urls_for_legacy_source_ids(self):
        from parsers_pkg.external.client import ELibraryClient, FreePatentClient, RosPatentClient

        self.assertEqual(
            await FreePatentClient().get_full_text("https://www.freepatent.ru/patents/123"),
            "https://www.freepatent.ru/patents/123",
        )
        self.assertEqual(
            await ELibraryClient().get_full_text("https://www.elibrary.ru/item.asp?id=123"),
            "https://www.elibrary.ru/item.asp?id=123",
        )
        self.assertEqual(
            await RosPatentClient().get_full_text("https://searchplatform.rospatent.gov.ru/doc/RU123"),
            "https://searchplatform.rospatent.gov.ru/doc/RU123",
        )


if __name__ == "__main__":
    unittest.main()

class TestExternalClientDateDriftRound19(unittest.IsolatedAsyncioTestCase):
    async def test_crossref_uses_published_online_when_issued_missing(self):
        client = CrossrefClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "message": {
                    "items": [
                        {
                            "title": ["Published online date"],
                            "published-online": {"date-parts": [[2025, 0, 0]]},
                            "DOI": "10.1000/CROSS.DATE",
                            "URL": "https://doi.org/10.1000/CROSS.DATE",
                        }
                    ]
                }
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["published_date"], "2025-01-01T00:00:00")

    async def test_europepmc_parses_month_name_pubdate(self):
        client = EuropePMCClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "resultList": {
                    "result": [
                        {
                            "id": "12345",
                            "source": "MED",
                            "title": "Month date EuropePMC",
                            "pubDate": "2024 Apr 10",
                        }
                    ]
                }
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["published_date"], "2024-04-10T00:00:00")

class TestExternalClientRound20Robustness(unittest.IsolatedAsyncioTestCase):
    async def test_openalex_unwraps_object_author_and_concept_names(self):
        client = OpenAlexClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W2020",
                        "display_name": "Object OpenAlex names",
                        "authorships": [
                            {"author": {"display_name": {"value": "Smith, John"}}},
                            {"author_display_name": {"name": "Doe, Jane"}},
                        ],
                        "concepts": [
                            {"display_name": {"value": "Nickel alloys"}},
                            {"name": "Oxidation"},
                        ],
                    }
                ]
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["authors"], ["Smith, John", "Doe, Jane"])
        self.assertEqual(records[0]["keywords"], ["Nickel alloys", "Oxidation"])
        self.assertNotIn("{'value'", " ".join(records[0]["authors"] + records[0]["keywords"]))

    async def test_rospatent_keeps_hit_authors_when_doc_payload_has_no_authors(self):
        from parsers_pkg.external.client import RosPatentClient

        client = RosPatentClient()

        async def fake_request_json_post(path: str, payload: dict):
            return {
                "hits": [
                    {
                        "id": "RU202020",
                        "common": {
                            "document_number": "RU202020",
                            "publication_date": "2024.05",
                            "kind": "C1",
                        },
                        "biblio": {"ru": {"title": "Никелевый сплав", "inventor": {"name": {"value": "Иванов И.И."}}}},
                        "snippet": {"description": "никелевый сплав"},
                        "dataset": "inventions_db",
                    }
                ]
            }

        async def fake_fetch_doc_payload(source_id: str):
            return {
                "abstract": {"ru": {"value": "Описание из карточки"}},
                "biblio": {"ru": {}},
            }

        client._request_json_post = fake_request_json_post
        client._fetch_doc_payload = fake_fetch_doc_payload

        records = await client.search("никелевый сплав", limit=1)

        self.assertEqual(records[0]["authors"], ["Иванов И.И."])
        self.assertEqual(records[0]["published_date"], "2024-05-01T00:00:00")
        self.assertEqual(records[0]["abstract"], "Описание из карточки")
        self.assertNotIn("{'value'", " ".join(records[0]["authors"]))


class TestExternalClientRound21DataLoss(unittest.IsolatedAsyncioTestCase):
    async def test_openalex_uses_publication_year_and_raw_author_name(self):
        client = OpenAlexClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W777",
                        "display_name": "OpenAlex year fallback",
                        "publication_year": 2026,
                        "authorships": [{"raw_author_name": {"value": "Smith, John"}}],
                    }
                ]
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["authors"], ["Smith, John"])
        self.assertEqual(records[0]["published_date"], "2026")

    async def test_crossref_accepts_lowercase_doi_url_and_short_title(self):
        client = CrossrefClient()

        async def fake_request_json(path: str, params: dict):
            return {
                "message": {
                    "items": [
                        {
                            "short-title": ["Lowercase DOI row"],
                            "doi": "DOI: 10.1000/LOWER.1",
                            "url": {"url": "https://doi.org/10.1000/LOWER.1"},
                        }
                    ]
                }
            }

        client._request_json = fake_request_json

        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["title"], "Lowercase DOI row")
        self.assertEqual(records[0]["doi"], "10.1000/lower.1")
        self.assertEqual(records[0]["source_id"], "10.1000/lower.1")
        self.assertEqual(records[0]["url"], "https://doi.org/10.1000/LOWER.1")

    async def test_rospatent_uses_media_payload_from_search_hit_when_detail_has_no_media(self):
        client = RosPatentClient()

        async def fake_request_json_post(path: str, payload: dict):
            return {
                "hits": {
                    "hits": [
                        {
                            "_id": "RU777",
                            "_source": {
                                "id": "RU777",
                                "common": {"document_number": "RU777", "publication_date": "2024.05.10"},
                                "snippet": {"title": "Никелевый сплав", "description": "никелевый сплав"},
                                "media": {"path": "/media/RU777"},
                            },
                        }
                    ]
                }
            }

        async def fake_fetch_doc_payload(source_id: str):
            return {"biblio": {"ru": {}}}

        async def fake_request_media_file_list(media_path: str):
            self.assertEqual(media_path, "/media/RU777")
            return ["main.pdf"]

        client._request_json_post = fake_request_json_post
        client._fetch_doc_payload = fake_fetch_doc_payload
        client._request_media_file_list = fake_request_media_file_list

        records = await client.search("никелевый", limit=1)

        self.assertEqual(records[0]["pdf_url"], "https://searchplatform.rospatent.gov.ru/media/RU777/main.pdf")
