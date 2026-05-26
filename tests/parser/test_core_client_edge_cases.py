from __future__ import annotations

import unittest

from parsers_pkg.core.client import COREClient


class TestCOREClientEdgeCases(unittest.IsolatedAsyncioTestCase):
    async def test_get_full_text_accepts_source_fulltext_url_dict(self):
        client = COREClient(api_key="test")

        async def fake_get_article(article_id: str):
            return {"sourceFulltextUrls": {"url": "https://repo.example/core.pdf"}}

        client.get_article = fake_get_article

        self.assertEqual(await client.get_full_text("123"), "https://repo.example/core.pdf")

    async def test_get_full_text_accepts_source_fulltext_url_string(self):
        client = COREClient(api_key="test")

        async def fake_get_article(article_id: str):
            return {"sourceFulltextUrls": "https://repo.example/core-fulltext"}

        client.get_article = fake_get_article

        self.assertEqual(await client.get_full_text("123"), "https://repo.example/core-fulltext")


if __name__ == "__main__":
    unittest.main()
