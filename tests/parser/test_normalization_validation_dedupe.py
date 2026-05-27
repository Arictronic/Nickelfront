from __future__ import annotations

from datetime import datetime
import unittest

from parsers_pkg.base.deduplication import Deduplicator, normalize_patent_identifier
from parsers_pkg.base.normalization import clean_text, derive_article_url, normalize_authors, normalize_datetime, normalize_doi, normalize_url
from parsers_pkg.base.validation import split_issues, validate_paper_fields
from shared.schemas.paper import Paper


class TestNormalizationValidationDedupe(unittest.TestCase):
    def test_normalization_helpers(self):
        self.assertEqual(clean_text("  Nickel\u00a0alloy   "), "Nickel alloy")
        self.assertEqual(normalize_authors([" Alice ", "alice", "Bob"]), ["Alice", "Bob"])
        self.assertEqual(normalize_authors("Alice Smith; Bob Jones"), ["Alice Smith", "Bob Jones"])
        self.assertEqual(normalize_authors("Smith, John"), ["Smith, John"])
        self.assertEqual(
            normalize_authors([{"name": "Smith, John"}, {"fullName": "Doe, Jane"}]),
            ["Smith, John", "Doe, Jane"],
        )
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

    def test_paper_schema_coerces_legacy_list_and_metadata_values(self):
        paper = Paper(
            title="Nickel alloy",
            authors='["A", "B"]',
            keywords="nickel; alloy",
            quality_flags="low_confidence, no_pdf",
            provenance='{"title": "OpenAlex"}',
            parse_confidence="85",
            source="OpenAlex",
            url="https://openalex.org/W1",
        )

        self.assertEqual(paper.authors, ["A", "B"])
        self.assertEqual(paper.keywords, ["nickel", "alloy"])
        self.assertEqual(paper.quality_flags, ["low_confidence", "no_pdf"])
        self.assertEqual(paper.provenance, {"title": "OpenAlex"})
        self.assertEqual(paper.parse_confidence, 0.85)

        comma_name = Paper(
            title="Nickel alloy",
            authors="Smith, John; Doe, Jane",
            keywords="nickel, alloy",
            quality_flags="low_confidence, no_pdf",
            source="Crossref",
        )
        self.assertEqual(comma_name.authors, ["Smith, John", "Doe, Jane"])
        self.assertEqual(comma_name.keywords, ["nickel", "alloy"])
        self.assertEqual(comma_name.quality_flags, ["low_confidence", "no_pdf"])

        object_values = Paper(
            title="Nickel alloy",
            authors=[{"name": "Smith, John"}, {"fullName": "Doe, Jane"}],
            keywords=[{"name": "nickel"}, {"value": "oxidation, corrosion"}],
            quality_flags=[{"value": "low_confidence"}],
            source="OpenAlex",
        )
        self.assertEqual(object_values.authors, ["Smith, John", "Doe, Jane"])
        self.assertEqual(object_values.keywords, ["nickel", "oxidation", "corrosion"])
        self.assertEqual(object_values.quality_flags, ["low_confidence"])

        nested_provenance = Paper(
            title="Nickel alloy",
            authors=[],
            source="OpenAlex",
            provenance={"url": {"url": "https://openalex.org/W1"}, "title": {"value": "Crossref"}},
        )
        self.assertEqual(nested_provenance.provenance, {"url": "https://openalex.org/W1", "title": "Crossref"})

        scalar_values = Paper(
            title={"value": "<p>Nickel scalar title</p>"},
            authors=[],
            journal={"name": "Journal scalar"},
            doi={"value": "DOI: 10.1000/SCALAR.1"},
            abstract={"text": "<jats:p>Scalar abstract</jats:p>"},
            source={"name": "Crossref"},
            source_id={"value": "10.1000/SCALAR.1"},
            url={"url": "https://doi.org/10.1000/SCALAR.1"},
            schema_version={"value": "2.1"},
        )
        self.assertEqual(scalar_values.title, "Nickel scalar title")
        self.assertEqual(scalar_values.journal, "Journal scalar")
        self.assertEqual(scalar_values.doi, "10.1000/scalar.1")
        self.assertEqual(scalar_values.abstract, "Scalar abstract")
        self.assertEqual(scalar_values.source, "Crossref")
        self.assertEqual(scalar_values.source_id, "10.1000/SCALAR.1")
        self.assertEqual(scalar_values.url, "https://doi.org/10.1000/SCALAR.1")
        self.assertEqual(scalar_values.schema_version, "2.1")

    def test_derive_article_url_percent_encodes_path_identifiers(self):
        self.assertEqual(
            derive_article_url(source="PATENTSCOPE", url=None, doi=None, source_id="PCT/US2024/000001"),
            "https://patentscope.wipo.int/search/en/detail.jsf?docId=PCT%2FUS2024%2F000001",
        )
        self.assertEqual(
            derive_article_url(source="EuropePMC", url=None, doi=None, source_id="MED:123/456"),
            "https://europepmc.org/article/MED/123%2F456",
        )

    def test_patent_dedupe_uses_canonical_source_id_not_title_similarity(self):
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

        self.assertEqual(normalize_patent_identifier("patents/123456", source="FreePatent"), "RU123456")
        self.assertEqual(normalize_patent_identifier("RU123456C1", source="Rospatent"), "RU123456")
        self.assertEqual(
            normalize_patent_identifier(
                "https://patentscope.wipo.int/search/en/detail.jsf?docId=WO2020123456",
                source="PATENTSCOPE",
            ),
            "WO2020123456",
        )
        self.assertEqual(
            normalize_patent_identifier(
                "https://patents.google.com/patent/WO2020123456A1/en",
                source="GooglePatents",
            ),
            "WO2020123456A1",
        )

        by_title = deduplicator.check_duplicate(
            title="Device for producing nickel alloy powder",
            doi=None,
            source_id="patents/654321",
            abstract="Same patent abstract",
            publication_year=2024,
            source="FreePatent",
            journal="FreePatent",
        )
        self.assertFalse(by_title.is_duplicate)
        self.assertEqual(by_title.reason, "Patent duplicate check is limited to DOI/source_id")

        by_canonical_source_id = deduplicator.check_duplicate(
            title="Different title",
            doi=None,
            source_id="patents/123456",
            abstract=None,
            publication_year=2024,
            source="FreePatent",
        )
        self.assertTrue(by_canonical_source_id.is_duplicate)
        self.assertEqual(by_canonical_source_id.reason, "Canonical patent source_id match")
        self.assertIs(deduplicator.find_duplicate_record({
            "source": "FreePatent",
            "journal": "FreePatent",
            "source_id": "patents/123456",
        }), existing[0])

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
