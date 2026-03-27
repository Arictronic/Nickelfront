"""
Парсер для ResearchGate.

Парсинг статей с researchgate.net
"""

import asyncio
from typing import Any, Optional, List
from dataclasses import dataclass
import logging
import re

import httpx
from bs4 import BeautifulSoup

from parsers_pkg.base import BaseParser
from shared.schemas.paper import Paper

logger = logging.getLogger(__name__)


@dataclass
class ResearchGateConfig:
    """Конфигурация для ResearchGate парсера."""
    timeout: float = 30.0
    max_pages: int = 5
    results_per_page: int = 20


class ResearchGateParser(BaseParser):
    """Парсер для ResearchGate."""
    
    BASE_URL = "https://www.researchgate.net"
    SEARCH_URL = f"{BASE_URL}/search/publications"
    
    def __init__(self, config: Optional[ResearchGateConfig] = None):
        """
        Инициализация парсера.
        
        Args:
            config: Конфигурация парсера
        """
        super().__init__(source="ResearchGate")
        self.config = config or ResearchGateConfig()
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Получить HTTP клиент."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                },
                timeout=self.config.timeout,
                follow_redirects=True,
            )
        return self._client
    
    async def close(self):
        """Закрыть соединение."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def search(
        self,
        query: str,
        limit: int = 20,
    ) -> List[dict[str, Any]]:
        """
        Поиск статей на ResearchGate.
        
        Args:
            query: Поисковый запрос
            limit: Максимум результатов
            
        Returns:
            Список словарей с результатами
        """
        client = await self._get_client()
        results = []
        
        try:
            # ResearchGate использует JavaScript для рендеринга,
            # поэтому используем их API напрямую
            page = 1
            total_pages = min(self.config.max_pages, (limit // self.config.results_per_page) + 1)
            
            while page <= total_pages and len(results) < limit:
                search_url = f"{self.SEARCH_URL}?q={query.replace(' ', '%20')}&page={page}"
                logger.info(f"Fetching page {page}: {search_url}")
                
                response = await client.get(search_url)
                
                if response.status_code != 200:
                    logger.warning(f"Got status {response.status_code}")
                    break
                
                # Распарсить HTML
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Найти элементы результатов
                # ResearchGate часто меняет структуру, используем общие селекторы
                result_elements = soup.select("li[data-testid]")
                
                if not result_elements:
                    # Альтернативный селектор
                    result_elements = soup.select(".publication-item")
                
                logger.info(f"Found {len(result_elements)} results on page {page}")
                
                for element in result_elements:
                    if len(results) >= limit:
                        break
                    
                    paper_data = await self._parse_result_element(element)
                    if paper_data:
                        results.append(paper_data)
                
                page += 1
                await asyncio.sleep(1)  # Rate limiting
            
            logger.info(f"Successfully collected {len(results)} results")
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
        
        return results
    
    async def _parse_result_element(self, element) -> Optional[dict[str, Any]]:
        """
        Распарсить элемент результата.
        
        Args:
            element: BeautifulSoup элемент
            
        Returns:
            Словарь с данными статьи
        """
        try:
            data = {
                "source": self.source,
            }
            
            # Заголовок
            title_elem = element.select_one("a[data-testid='title']")
            if not title_elem:
                title_elem = element.select_one(".title a")
            
            if title_elem:
                data["title"] = title_elem.get_text(strip=True)
                href = title_elem.get("href")
                if href:
                    data["url"] = f"{self.BASE_URL}{href}"
                    data["source_id"] = href.split("/")[-1] if href else None
            else:
                logger.warning("No title found")
                return None
            
            # Авторы
            authors = []
            author_elems = element.select("a[data-testid='author']")
            if not author_elems:
                author_elems = element.select(".author a")
            
            for author_elem in author_elems:
                author_text = author_elem.get_text(strip=True)
                if author_text:
                    authors.append(author_text)
            
            data["authors"] = authors
            
            # Журнал/Источник
            journal_elem = element.select_one(".publication-source")
            if not journal_elem:
                journal_elem = element.select_one("[data-testid='journal']")
            
            data["journal"] = journal_elem.get_text(strip=True) if journal_elem else None
            
            # Дата публикации
            date_elem = element.select_one(".publication-date")
            if not date_elem:
                date_elem = element.select_one("[data-testid='date']")
            
            if date_elem:
                date_str = date_elem.get_text(strip=True)
                data["publication_date"] = self._parse_date(date_str)
            
            # Аннотация
            abstract_elem = element.select_one(".abstract")
            if not abstract_elem:
                abstract_elem = element.select_one("[data-testid='abstract']")
            
            data["abstract"] = abstract_elem.get_text(strip=True) if abstract_elem else None
            
            # Тип публикации
            type_elem = element.select_one(".publication-type")
            if type_elem:
                data["publication_type"] = type_elem.get_text(strip=True)
            
            return data
            
        except Exception as e:
            logger.error(f"Error parsing element: {e}")
            return None
    
    def _parse_date(self, date_str: str) -> Optional[str]:
        """Распарсить дату из строки."""
        if not date_str:
            return None
        
        # Пример: "Jan 2024" или "2024"
        months = {
            'jan': '01', 'feb': '02', 'mar': '03',
            'apr': '04', 'may': '05', 'jun': '06',
            'jul': '07', 'aug': '08', 'sep': '09',
            'oct': '10', 'nov': '11', 'dec': '12',
        }
        
        date_str = date_str.lower().strip()
        
        # Попробовать формат "Jan 2024"
        match = re.match(r'(\w{3})\s+(\d{4})', date_str)
        if match:
            month, year = match.groups()
            month_num = months.get(month[:3], '01')
            return f"{year}-{month_num}-01"
        
        # Попробовать формат "2024"
        match = re.match(r'(\d{4})', date_str)
        if match:
            year = match.group(1)
            return f"{year}-01-01"
        
        return None
    
    async def parse_search_results(self, data: List[dict[str, Any]]) -> List[Paper]:
        """
        Распарсить результаты поиска в список Paper.
        
        Args:
            data: Список словарей с результатами
            
        Returns:
            Список Paper
        """
        papers = []
        
        for item in data:
            paper = Paper(
                title=item.get("title", ""),
                authors=item.get("authors", []),
                publication_date=item.get("publication_date"),
                journal=item.get("journal"),
                abstract=item.get("abstract"),
                source=item.get("source", self.source),
                source_id=item.get("source_id"),
                url=item.get("url"),
            )
            
            # Нормализовать
            paper = self.normalize_paper(paper)
            
            # Валидировать
            is_valid, errors = self.validate_paper(paper)
            if is_valid:
                papers.append(paper)
            else:
                logger.warning(f"Invalid paper: {errors}")
        
        return papers
    
    async def parse_full_text(self, url: str, metadata: dict[str, Any]) -> Optional[Paper]:
        """
        Распарсить полный текст статьи.
        
        Args:
            url: URL статьи
            metadata: Метаданные статьи
            
        Returns:
            Paper с полным текстом
        """
        client = await self._get_client()
        
        try:
            response = await client.get(url)
            
            if response.status_code != 200:
                logger.warning(f"Got status {response.status_code} for {url}")
                return None
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Полный текст на ResearchGate часто недоступен без регистрации
            # Пытаемся получить то, что доступно
            
            full_text = ""
            
            # Заголовок
            title_elem = soup.select_one("h1")
            if title_elem:
                metadata["title"] = title_elem.get_text(strip=True)
            
            # Аннотация
            abstract_elem = soup.select_one("[data-testid='abstract']")
            if not abstract_elem:
                abstract_elem = soup.select_one(".abstract")
            
            if abstract_elem:
                metadata["abstract"] = abstract_elem.get_text(strip=True)
            
            # Основной текст (если доступен)
            content_elems = soup.select("article p, .content p")
            if content_elems:
                full_text = "\n\n".join([
                    elem.get_text(strip=True) 
                    for elem in content_elems 
                    if elem.get_text(strip=True)
                ])
            
            # Ключевые слова
            keywords = []
            keyword_elems = soup.select("[data-testid='keyword'] a")
            if keyword_elems:
                keywords = [elem.get_text(strip=True) for elem in keyword_elems]
            
            paper = Paper(
                title=metadata.get("title", ""),
                authors=metadata.get("authors", []),
                publication_date=metadata.get("publication_date"),
                journal=metadata.get("journal"),
                doi=metadata.get("doi"),
                abstract=metadata.get("abstract"),
                full_text=full_text,
                keywords=keywords,
                source=self.source,
                url=url,
            )
            
            return self.normalize_paper(paper)
            
        except Exception as e:
            logger.error(f"Error parsing full text: {e}")
            return None
    
    async def extract_keywords(self, paper: Paper) -> List[str]:
        """
        Извлечь ключевые слова из статьи.
        
        Args:
            paper: Статья
            
        Returns:
            Список ключевых слов
        """
        if paper.keywords:
            return paper.keywords
        
        keywords = []
        
        if paper.abstract:
            # Простая эвристика
            important_terms = [
                "research", "study", "analysis", "method",
                "results", "data", "experiment", "model",
            ]
            
            abstract_lower = paper.abstract.lower()
            for term in important_terms:
                if term in abstract_lower:
                    keywords.append(term)
        
        return keywords


async def parse_researchgate(
    query: str,
    limit: int = 20,
) -> List[Paper]:
    """
    Быстрый парсинг ResearchGate.
    
    Args:
        query: Поисковый запрос
        limit: Максимум результатов
        
    Returns:
        Список Paper
    """
    parser = ResearchGateParser()
    
    try:
        results = await parser.search(query, limit)
        papers = await parser.parse_search_results(results)
        return papers
    finally:
        await parser.close()


if __name__ == "__main__":
    # Пример использования
    import asyncio
    
    async def main():
        papers = await parse_researchgate("nickel-based superalloys", limit=5)
        print(f"Found {len(papers)} papers")
        
        for paper in papers:
            print(f"- {paper.title}")
    
    asyncio.run(main())
