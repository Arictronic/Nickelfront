"""Unit тесты для arXiv парсера."""

import pytest
from parsers_pkg.arxiv.parser import ArxivParser
from shared.schemas.paper import Paper


class TestArxivParser:
    """Тесты для ArxivParser."""

    @pytest.fixture
    def parser(self):
        """Создать парсер."""
        return ArxivParser()

    @pytest.fixture
    def sample_arxiv_data(self):
        """Пример данных из arXiv API."""
        return [{
            "arxiv_id": "2101.12345",
            "title": "Nickel-based superalloys for high temperature applications",
            "authors": ["John Smith", "Jane Doe"],
            "published_date": "2024-01-15T10:00:00Z",
            "categories": ["cond-mat.mtrl-sci"],
            "abstract": "This paper studies nickel-based superalloys.",
            "url": "https://arxiv.org/abs/2101.12345",
            "source": "arXiv",
        }]

    @pytest.mark.asyncio
    async def test_parse_search_results(self, parser, sample_arxiv_data):
        """Тест парсинга результатов поиска."""
        papers = await parser.parse_search_results(sample_arxiv_data)
        assert len(papers) == 1
        
        paper = papers[0]
        assert paper.title == "Nickel-based superalloys for high temperature applications"
        assert len(paper.authors) == 2
        assert paper.source == "arXiv"
        assert paper.keywords == ["cond-mat.mtrl-sci"]

    @pytest.mark.asyncio
    async def test_parse_empty_results(self, parser):
        """Тест парсинга пустых результатов."""
        papers = await parser.parse_search_results([])
        assert len(papers) == 0

    @pytest.mark.asyncio
    async def test_parse_missing_title(self, parser):
        """Тест парсинга без названия."""
        data = [{"arxiv_id": "1", "authors": ["Author"]}]
        papers = await parser.parse_search_results(data)
        assert len(papers) == 1
        assert papers[0].title == "Без названия"

    @pytest.mark.asyncio
    async def test_extract_keywords_from_abstract(self, parser):
        """Тест извлечения ключевых слов из аннотации."""
        paper = Paper(
            title="Test",
            abstract="Nickel superalloys are used in high temperature applications. "
                     "These alloys provide excellent corrosion resistance.",
            source="arXiv",
        )
        keywords = await parser.extract_keywords(paper)
        assert len(keywords) > 0
        assert "nickel" in keywords or "superalloys" in keywords

    @pytest.mark.asyncio
    async def test_parse_full_text(self, parser, sample_arxiv_data):
        """Тест парсинга полного текста."""
        paper = await parser.parse_full_text("Full text...", sample_arxiv_data[0])
        assert paper.full_text == "Full text..."
        assert paper.source == "arXiv"
