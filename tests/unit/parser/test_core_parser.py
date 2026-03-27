"""Unit тесты для CORE парсера."""

import pytest
from datetime import datetime
from parsers_pkg.core.parser import COREParser
from shared.schemas.paper import Paper


class TestCOREParser:
    """Тесты для COREParser."""

    @pytest.fixture
    def parser(self):
        """Создать парсер."""
        return COREParser()

    @pytest.fixture
    def sample_core_data(self):
        """Пример данных из CORE API."""
        return [
            {
                "id": 123456,
                "title": "Nickel-based superalloys for high temperature applications",
                "authors": [{"name": "John Smith"}, {"name": "Jane Doe"}],
                "published_date": "2024-01-15",
                "journal": {"name": "Journal of Materials Science"},
                "doi": "10.1234/test.2024.001",
                "abstract": "This paper studies nickel-based superalloys...",
                "topics": ["nickel", "superalloys", "high temperature"],
                "source_fulltext_url": "https://example.com/paper",
                "has_full_text": True,
            }
        ]

    @pytest.mark.asyncio
    async def test_parse_search_results(self, parser, sample_core_data):
        """Тест парсинга результатов поиска."""
        papers = await parser.parse_search_results(sample_core_data)

        assert len(papers) == 1
        paper = papers[0]

        assert paper.title == "Nickel-based superalloys for high temperature applications"
        assert len(paper.authors) == 2
        assert "John Smith" in paper.authors
        assert "Jane Doe" in paper.authors
        assert paper.doi == "10.1234/test.2024.001"
        assert paper.abstract == "This paper studies nickel-based superalloys..."
        assert paper.source == "CORE"
        assert paper.source_id == "123456"
        assert paper.url == "https://example.com/paper"
        assert len(paper.keywords) == 3

    @pytest.mark.asyncio
    async def test_parse_empty_results(self, parser):
        """Тест парсинга пустых результатов."""
        papers = await parser.parse_search_results([])
        assert len(papers) == 0

    @pytest.mark.asyncio
    async def test_parse_missing_authors(self, parser):
        """Тест парсинга без авторов."""
        data = [
            {
                "id": 789,
                "title": "Paper without authors",
                "authors": [],
                "doi": "10.1234/test.2024.002",
            }
        ]
        papers = await parser.parse_search_results(data)
        assert len(papers) == 1
        assert papers[0].authors == []

    @pytest.mark.asyncio
    async def test_parse_missing_title(self, parser):
        """Тест парсинга без названия (должно быть значение по умолчанию)."""
        data = [
            {
                "id": 789,
                "authors": ["Author Name"],
            }
        ]
        papers = await parser.parse_search_results(data)
        assert len(papers) == 1
        assert papers[0].title == "Без названия"

    @pytest.mark.asyncio
    async def test_parse_date_formats(self, parser):
        """Тест парсинга разных форматов даты."""
        # YYYY-MM-DD
        data1 = [{"id": 1, "title": "Test", "published_date": "2024-01-15"}]
        papers1 = await parser.parse_search_results(data1)
        assert papers1[0].publication_date.year == 2024
        assert papers1[0].publication_date.month == 1
        assert papers1[0].publication_date.day == 15

        # YYYY-MM
        data2 = [{"id": 1, "title": "Test", "published_date": "2024-01"}]
        papers2 = await parser.parse_search_results(data2)
        assert papers2[0].publication_date.year == 2024
        assert papers2[0].publication_date.month == 1

        # YYYY
        data3 = [{"id": 1, "title": "Test", "published_date": "2024"}]
        papers3 = await parser.parse_search_results(data3)
        assert papers3[0].publication_date.year == 2024

    @pytest.mark.asyncio
    async def test_extract_keywords_from_abstract(self, parser):
        """Тест извлечения ключевых слов из аннотации."""
        paper = Paper(
            title="Test Paper",
            abstract="Nickel alloys are used in high temperature applications. "
                     "Superalloys provide excellent corrosion resistance.",
            source="CORE",
        )
        keywords = await parser.extract_keywords(paper)
        assert len(keywords) > 0
        assert "nickel" in keywords or "alloys" in keywords

    @pytest.mark.asyncio
    async def test_extract_keywords_existing(self, parser):
        """Тест извлечения ключевых слов (уже есть)."""
        paper = Paper(
            title="Test Paper",
            keywords=["existing", "keywords"],
            source="CORE",
        )
        keywords = await parser.extract_keywords(paper)
        assert keywords == ["existing", "keywords"]

    @pytest.mark.asyncio
    async def test_parse_full_text(self, parser, sample_core_data):
        """Тест парсинга полного текста."""
        metadata = sample_core_data[0]
        full_text = "This is the full text of the paper..."

        paper = await parser.parse_full_text(full_text, metadata)

        assert paper.full_text == full_text
        assert paper.title == metadata["title"]
        assert paper.doi == metadata["doi"]
