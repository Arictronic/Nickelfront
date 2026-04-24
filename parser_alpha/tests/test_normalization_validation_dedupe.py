from __future__ import annotations

from datetime import datetime
import unittest

from parsers_pkg.base.deduplication import Deduplicator
from parsers_pkg.base.normalization import clean_text, normalize_authors, normalize_doi, normalize_url
from parsers_pkg.base.validation import split_issues, validate_paper_fields
from shared.schemas.paper import Paper


class TestNormalizationValidationDedupe(unittest.TestCase):
    def test_normalization_helpers(self):
        self.assertEqual(clean_text("  Nickel\u00a0alloy   "), "Nickel alloy")
        self.assertEqual(normalize_authors([" Alice ", "alice", "Bob"]), ["Alice", "Bob"])
        self.assertEqual(normalize_doi("https://doi.org/10.1000/ABC.1"), "10.1000/abc.1")
        self.assertEqual(normalize_url("https://example.org/paper"), "https://example.org/paper")

    def test_validation_soft_hard(self):
        paper = Paper(
            title="",
            authors=["A"],
            source="OpenAlex",
            publication_date=datetime(2024, 1, 1),
            url="invalid-url",
        )
        issues = validate_paper_fields(paper, source="OpenAlex")
        hard, soft = split_issues(issues)

        self.assertTrue(any(issue.code == "missing_title" for issue in hard))
        self.assertFalse(any(issue.code == "missing_article_url" for issue in hard))
        self.assertTrue(any(issue.code == "invalid_url" for issue in soft))

    def test_patent_dedupe_only_by_doi_or_source_id(self):
        existing = [
            {
                "id": 20,
                "title": "Device for producing nickel alloy powder",
                "doi": None,
                "source_id": "RU123456",
                "source": "Rospatent",
                "journal": "Rospatent",
                "publication_date": datetime(2024, 1, 1),
                "abstract": "Same patent abstract",
            }
        ]
        deduplicator = Deduplicator(existing)

        by_title = deduplicator.check_duplicate(
            title="Device for producing nickel alloy powder",
            doi=None,
            source_id="RU654321",
            abstract="Same patent abstract",
            publication_year=2024,
            source="FreePatent",
            journal="FreePatent",
        )
        self.assertFalse(by_title.is_duplicate)
        self.assertEqual(by_title.reason, "Patent duplicate check is limited to DOI/source_id")

        by_source_id = deduplicator.check_duplicate(
            title="Different title",
            doi=None,
            source_id="RU123456",
            abstract=None,
            publication_year=2024,
            source="PATENTSCOPE",
        )
        self.assertTrue(by_source_id.is_duplicate)

        by_doi = deduplicator.check_duplicate(
            title="Different title",
            doi="10.1000/patent.1",
            source_id="WO123456",
            abstract=None,
            publication_year=2024,
            source="Rospatent",
        )
        self.assertFalse(by_doi.is_duplicate)

        existing[0]["doi"] = "10.1000/patent.1"
        by_doi = deduplicator.check_duplicate(
            title="Different title",
            doi="https://doi.org/10.1000/PATENT.1",
            source_id="WO123456",
            abstract=None,
            publication_year=2024,
            source="Rospatent",
        )
        self.assertTrue(by_doi.is_duplicate)

    def test_multi_key_dedupe_and_merge(self):
        existing = [
            {
                "id": 10,
                "title": "Nickel superalloy oxidation at high temperature",
                "doi": "10.1000/xyz.1",
                "source_id": "R123",
                "source": "Crossref",
                "publication_date": datetime(2024, 1, 1),
                "abstract": "A",
            }
        ]
        deduplicator = Deduplicator(existing)

        by_doi = deduplicator.check_duplicate(
            title="Another",
            doi="10.1000/xyz.1",
            source_id=None,
            abstract=None,
            publication_year=2024,
        )
        self.assertTrue(by_doi.is_duplicate)

        by_title_year = deduplicator.check_duplicate(
            title="Nickel superalloy oxidation at high temperature",
            doi=None,
            source_id=None,
            abstract="B",
            publication_year=2024,
        )
        self.assertTrue(by_title_year.is_duplicate)

        incoming = {
            "title": "Nickel superalloy oxidation at high temperature",
            "doi": "10.1000/xyz.1",
            "source": "OpenAlex",
            "url": "https://openalex.org/W12345",
        }
        merged = deduplicator.merge_records(incoming=incoming, existing=existing[0])
        self.assertIn("url", merged.record)
        self.assertIn("title", merged.provenance)
        self.assertGreaterEqual(merged.confidence, 0.5)


if __name__ == "__main__":
    unittest.main()
