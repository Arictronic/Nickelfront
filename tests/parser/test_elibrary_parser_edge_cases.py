from __future__ import annotations

import unittest

from parsers_pkg.russian.elibrary_parser import ELibraryParser
from shared.schemas.paper import Paper


class TestELibraryParserEdgeCases(unittest.TestCase):
    def test_parser_unwraps_object_fields_without_python_repr(self):
        parser = ELibraryParser()

        paper = parser._parse_single_result(
            {
                "title": {"value": "<b>Никелевый сплав</b>"},
                "authors": [{"name": "Иванов, Иван"}, {"fullName": "Петров П.П."}],
                "source_id": {"value": "123456"},
                "url": {"url": "https://www.elibrary.ru/item.asp?id=123456"},
                "abstract": {"text": "<p>Аннотация</p>"},
                "doi": {"value": "DOI: 10.1000/ELIB.1"},
                "pdf_url": {"url": "https://www.elibrary.ru/download/elibrary_123456.pdf"},
                "keywords": [{"name": "никель, сплав"}],
                "journal": {"name": "Журнал сплавов"},
                "year": {"year": 2024},
                "citations": 5,
            }
        )

        self.assertIsNotNone(paper)
        assert paper is not None
        self.assertEqual(paper.title, "Никелевый сплав")
        self.assertEqual(paper.authors, ["Иванов, Иван", "Петров П.П."])
        self.assertEqual(paper.source_id, "123456")
        self.assertEqual(paper.doi, "10.1000/elib.1")
        self.assertEqual(paper.pdf_url, "https://www.elibrary.ru/download/elibrary_123456.pdf")
        self.assertIn("никель", paper.keywords)
        self.assertIn("сплав", paper.keywords)
        self.assertNotIn("{'", " ".join([paper.title, *(paper.authors or []), *(paper.keywords or [])]))

    def test_enrich_paper_with_details_unwraps_objects(self):
        parser = ELibraryParser()
        paper = Paper(title="Base", authors=[], source="eLibrary", url="https://www.elibrary.ru/item.asp?id=1")

        enriched = parser.enrich_paper_with_details(
            paper,
            {
                "abstract": {"text": "<p>Детальная аннотация</p>"},
                "keywords": {"value": "никель, коррозия"},
                "doi": {"value": "10.1000/DETAIL.1"},
                "pdf_url": {"url": "https://www.elibrary.ru/file.pdf"},
                "elibrary_id": {"value": "1"},
            },
        )

        self.assertEqual(enriched.abstract, "Детальная аннотация")
        self.assertEqual(enriched.keywords, ["никель", "коррозия"])
        self.assertEqual(enriched.doi, "10.1000/detail.1")
        self.assertEqual(enriched.pdf_url, "https://www.elibrary.ru/file.pdf")


if __name__ == "__main__":
    unittest.main()
