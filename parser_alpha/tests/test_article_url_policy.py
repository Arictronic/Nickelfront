from __future__ import annotations

import unittest

from parsers_pkg.base.normalization import derive_article_url


class TestArticleUrlPolicy(unittest.TestCase):
    def test_derive_url_by_doi(self):
        self.assertEqual(
            derive_article_url(source="Crossref", url=None, doi="10.1000/ABC.1", source_id=None),
            "https://doi.org/10.1000/abc.1",
        )

    def test_derive_source_specific_urls(self):
        self.assertEqual(
            derive_article_url(source="OpenAlex", url=None, doi=None, source_id="W12345"),
            "https://openalex.org/W12345",
        )
        self.assertEqual(
            derive_article_url(source="CORE", url=None, doi=None, source_id="123456"),
            "https://core.ac.uk/works/123456",
        )

    def test_unknown_source_without_url_or_doi(self):
        self.assertIsNone(
            derive_article_url(source="Unknown", url=None, doi=None, source_id="abc")
        )


if __name__ == "__main__":
    unittest.main()
