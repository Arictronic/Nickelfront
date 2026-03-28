"""
Тесты для парсера PDF.
"""

import tempfile
from pathlib import Path

import pytest

from app.services.parser_service import PDFParser, WebScraper, pdf_parser


class TestPDFParser:
    """Тесты для PDF парсера."""

    @pytest.fixture
    def parser(self):
        """Фикстура с PDF парсером."""
        return PDFParser(chunk_size=500, chunk_overlap=50)

    @pytest.fixture
    def sample_pdf_path(self):
        """Фикстура с путём к тестовому PDF."""
        # Создание простого текстового файла для теста
        # В реальном проекте здесь был бы настоящий PDF
        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False,
        ) as tmp:
            # Заглушка - в реальности нужен настоящий PDF
            tmp.write(b"%PDF-1.4\n")  # PDF header
            tmp_path = tmp.name

        yield tmp_path

        # Очистка
        Path(tmp_path).unlink(missing_ok=True)

    def test_parser_initialization(self, parser):
        """Проверка инициализации парсера."""
        assert parser.chunk_size == 500
        assert parser.chunk_overlap == 50

    def test_extract_text_file_not_found(self, parser):
        """Проверка обработки несуществующего файла."""
        with pytest.raises(FileNotFoundError):
            parser.extract_text_from_file("nonexistent.pdf")

    def test_parse_to_documents_empty(self, parser):
        """Проверка парсинга пустого файла."""
        # Создаём пустой файл
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # Пустой файл должен вернуть пустой список или выбросить ошибку
            docs = parser.parse_to_documents(tmp_path)
            assert isinstance(docs, list)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_parse_with_metadata(self, parser):
        """Проверка добавления метаданных."""
        # Создаём файл с минимальным содержимым
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(b"%PDF-1.4\n")
            tmp_path = tmp.name

        try:
            docs = parser.parse_to_documents(
                tmp_path,
                metadata={"custom_field": "test_value"},
            )

            # Проверка метаданных в документах
            for doc in docs:
                assert "custom_field" in doc.metadata
                assert doc.metadata["custom_field"] == "test_value"
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class TestWebScraper:
    """Тесты для веб-скрапера."""

    def test_scraper_initial(self):
        """Проверка инициализации скрапера."""
        scraper = WebScraper(headless=True)
        assert scraper.headless is True
        assert scraper._driver is None

    def test_scraper_context_manager(self):
        """Проверка контекстного менеджера."""
        with WebScraper(headless=True) as scraper:
            assert scraper is not None
        # После выхода драйвер должен быть закрыт
        assert scraper._driver is None

    def test_scraper_close_without_init(self):
        """Проверка закрытия без инициализации."""
        scraper = WebScraper()
        scraper.close()  # Не должно вызывать ошибку
        assert scraper._driver is None


class TestParserIntegration:
    """Интеграционные тесты для парсера."""

    def test_parse_pdf_function(self):
        """Проверка функции parse_pdf_to_documents."""
        # Создаём временный файл
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(b"%PDF-1.4\n")
            tmp_path = tmp.name

        try:
            docs = pdf_parser.parse_to_documents(tmp_path)
            assert isinstance(docs, list)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
