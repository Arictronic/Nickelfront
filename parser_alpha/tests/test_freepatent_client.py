from __future__ import annotations

import unittest

from parsers_pkg.external.client import FreePatentClient


class TestFreePatentClient(unittest.IsolatedAsyncioTestCase):
    async def test_mpk_result_expands_to_patent_links(self):
        search_html = """
        <html><body>
          <li class="b-serp-item">
            <a class="b-serp-item__title-link" href="http://www.freepatent.ru/MPK/C/C22/C22C/C22C23/C22C2304">C22C 23/04</a>
            <div class="b-serp-item__text">category snippet</div>
          </li>
        </body></html>
        """
        mpk_html = """
        <html><body>
          <a href="/patents/2459000">ЛИСТ ИЗ МАГНИЕВОГО СПЛАВА</a>
          <a href="/patents/2445401">СТАЛЬНОЙ МАТЕРИАЛ С ПОКРЫТИЕМ ИЗ СПЛАВА НА ОСНОВЕ Mg</a>
        </body></html>
        """

        client = FreePatentClient()
        calls = {"count": 0}

        async def fake_request_text(path: str, params=None) -> str:
            calls["count"] += 1
            if calls["count"] == 1:
                return search_html
            return mpk_html

        client._request_text = fake_request_text  # type: ignore[method-assign]

        records = await client.search("nickel-based superalloys", limit=10)

        self.assertGreaterEqual(len(records), 2)
        self.assertTrue(all("/patents/" in (r.get("url") or "") for r in records))
        self.assertTrue(all("MPK/" not in (r.get("url") or "") for r in records))
        self.assertEqual(records[0]["source_id"], "patents/2459000")

    def test_yandex_redirect_link_is_unwrapped(self):
        encoded = "https%3A%2F%2Fwww.freepatent.ru%2Fpatents%2F2459000"
        href = f"/clck/jsredir?from=yandex.ru&url={encoded}&text=nickel"

        self.assertEqual(
            FreePatentClient._unwrap_yandex_result_url(href),
            "https://www.freepatent.ru/patents/2459000",
        )

    async def test_yandex_redirect_result_is_parsed_as_patent(self):
        search_html = """
        <html><body>
          <li class="b-serp-item">
            <a class="b-serp-item__title-link"
               href="/clck/jsredir?url=https%3A%2F%2Fwww.freepatent.ru%2Fpatents%2F2459000">
              Патент на никелевый сплав
            </a>
            <div class="b-serp-item__text">Описание патента</div>
          </li>
        </body></html>
        """

        client = FreePatentClient()

        async def fake_request_text(path: str, params=None) -> str:
            return search_html

        client._request_text = fake_request_text  # type: ignore[method-assign]

        records = await client.search("никелевый сплав", limit=5)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source_id"], "patents/2459000")
        self.assertEqual(records[0]["url"], "https://www.freepatent.ru/patents/2459000")


if __name__ == "__main__":
    unittest.main()
