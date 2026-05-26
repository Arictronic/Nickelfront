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

        client._request_text = fake_request_text

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

        client._request_text = fake_request_text

        records = await client.search("никелевый сплав", limit=5)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source_id"], "patents/2459000")
        self.assertEqual(records[0]["url"], "https://www.freepatent.ru/patents/2459000")

    async def test_patent_page_enriches_search_result_with_pdf_and_full_text(self):
        search_html = """
        <li class="b-serp-item">
          <a class="b-serp-item__title-link" href="https://www.freepatent.ru/patents/2459000">Result</a>
          <div class="b-serp-item__text">Snippet only</div>
        </li>
        """
        detail_html = """
        <html><body>
          <h1>Nickel alloy patent details</h1>
          <div class="abstract">Detailed patent abstract about nickel alloys.</div>
          <article>{body}</article>
          <a href="/download/2459000.pdf">PDF</a>
        </body></html>
        """.format(body="Technical description of nickel alloy. " * 20)

        client = FreePatentClient()

        async def fake_request_text(path: str, params=None) -> str:
            return search_html if path == "/search/site/" else detail_html

        client._request_text = fake_request_text
        records = await client.search("nickel", limit=1)

        self.assertEqual(records[0]["abstract"], "Detailed patent abstract about nickel alloys.")
        self.assertGreater(len(records[0]["full_text"]), 200)
        self.assertEqual(records[0]["pdf_url"], "https://www.freepatent.ru/download/2459000.pdf")

    async def test_realistic_patent_page_without_pdf_returns_document_text_and_metadata(self):
        record = {
            "title": "Result title",
            "authors": [],
            "published_date": None,
            "abstract": None,
            "source": "FreePatent",
            "source_id": "patents/2017851",
            "url": "https://www.freepatent.ru/patents/2017851",
            "pdf_url": None,
        }
        detail_html = """
        <html><body>
          <h1>Сплав на основе никеля</h1>
          <p>Автор(ы): Еременко В.И. , Рудницкий Е.Н. Патентообладатель(и): Институт</p>
          <p>подача заявки: 1992-03-18 публикация патента: 15.08.1994</p>
          <p>Изобретение относится к металлургии, в частности к металлургии жаропрочных
             никелевых сплавов, предназначенных для деталей газотурбинных двигателей.
             Сущность изобретения состоит в новом составе сплава.</p>
          <h2>Формула изобретения</h2>
          <p>{body}</p>
          <h2>Описание изобретения к патенту</h2>
          <p>{body}</p>
        </body></html>
        """.format(body="Подробное описание состава и свойств сплава. " * 20)
        client = FreePatentClient()

        async def fake_request_text(path: str, params=None) -> str:
            return detail_html

        client._request_text = fake_request_text
        enriched = await client._enrich_patent_record(record)

        self.assertGreater(len(enriched["full_text"]), 500)
        self.assertEqual(enriched["authors"], ["Еременко В.И.", "Рудницкий Е.Н."])
        self.assertEqual(enriched["published_date"], "1994-08-15")


if __name__ == "__main__":
    unittest.main()
