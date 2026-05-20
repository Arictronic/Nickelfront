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


if __name__ == "__main__":
    unittest.main()
