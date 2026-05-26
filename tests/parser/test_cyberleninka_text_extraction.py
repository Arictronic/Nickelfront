from __future__ import annotations

import unittest

from parsers_pkg.russian.cyberleninka_client import CyberLeninkaClient


class TestCyberLeninkaTextExtraction(unittest.TestCase):
    def test_extracts_nested_ocr_block_without_truncation(self):
        html = """
        <html>
          <body>
            <div class="full">
              <div class="ocr">
                <div><p>Первый абзац научного текста с достаточной длиной для проверки извлечения.</p></div>
                <div><p>Второй абзац научного текста, который в regex-версии мог обрезаться на первом закрывающем div.</p></div>
                <div><p>Третий абзац для гарантии, что итоговая длина больше 200 символов и возвращается как full text.</p></div>
              </div>
            </div>
          </body>
        </html>
        """

        extracted = CyberLeninkaClient._extract_main_text(html)
        self.assertIsNotNone(extracted)
        assert extracted is not None
        self.assertIn("Первый абзац", extracted)
        self.assertIn("Второй абзац", extracted)
        self.assertIn("Третий абзац", extracted)
        self.assertGreater(len(extracted), 200)


class TestCyberLeninkaUrlNormalization(unittest.TestCase):
    def test_api_result_with_absolute_article_url_keeps_clean_source_id_and_pdf(self):
        data = {
            "articles": [
                {
                    "link": "https://cyberleninka.ru/article/n/nikel-test",
                    "name": "Никелевый сплав",
                    "authors": "Иванов И.И.; Петров П.П.",
                    "year": 2024,
                }
            ]
        }

        records = CyberLeninkaClient()._parse_api_results(data, limit=1)

        self.assertEqual(records[0]["source_id"], "article/n/nikel-test")
        self.assertEqual(records[0]["url"], "https://cyberleninka.ru/article/n/nikel-test")
        self.assertEqual(records[0]["pdf_url"], "https://cyberleninka.ru/article/n/nikel-test/pdf")
        self.assertEqual(records[0]["authors"], ["Иванов И.И.", "Петров П.П."])

    def test_api_result_with_external_url_is_skipped(self):
        data = {
            "articles": [
                {
                    "link": "https://example.com/not-cyberleninka",
                    "name": "Bad mirror",
                }
            ]
        }

        records = CyberLeninkaClient()._parse_api_results(data, limit=1)

        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()


class TestCyberLeninkaRound13Robustness(unittest.IsolatedAsyncioTestCase):
    def test_api_result_accepts_single_article_dict_and_dict_authors(self):
        data = {
            "articles": {
                "link": "/article/n/nikel-dict-authors",
                "name": "Никелевый сплав",
                "authors": [{"name": "Иванов И.И."}, {"fullName": "Петров П.П."}],
                "year": 2024,
            }
        }

        records = CyberLeninkaClient()._parse_api_results(data, limit=1)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["authors"], ["Иванов И.И.", "Петров П.П."])
        self.assertNotIn("{'name'", " ".join(records[0]["authors"]))

    def test_api_result_non_dict_payload_is_empty_not_exception(self):
        records = CyberLeninkaClient()._parse_api_results(["bad"], limit=1)

        self.assertEqual(records, [])
