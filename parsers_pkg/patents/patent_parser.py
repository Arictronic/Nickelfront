"""
Парсер патентов.

Поддерживаемые источники:
- Google Patents
- Espacenet (EPO)
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx
from bs4 import BeautifulSoup

from parsers_pkg.base import BaseParser
from shared.schemas.paper import Paper

logger = logging.getLogger(__name__)


@dataclass
class PatentConfig:
    """Конфигурация для патентного парсера."""
    timeout: float = 30.0
    max_results: int = 50


class PatentParser(BaseParser):
    """Парсер для патентов."""

    # Google Patents API (через web scraping)
    GOOGLE_PATENTS_URL = "https://patents.google.com"

    # Espacenet API
    ESPACENET_URL = "https://worldwide.espacenet.com"

    def __init__(self, config: PatentConfig | None = None):
        """
        Инициализация парсера.

        Args:
            config: Конфигурация парсера
        """
        super().__init__(source="Patents")
        self.config = config or PatentConfig()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Получить HTTP клиент."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
        source: str = "google",  # google или espacenet
    ) -> list[dict[str, Any]]:
        """
        Поиск патентов.

        Args:
            query: Поисковый запрос
            limit: Максимум результатов
            source: Источник (google или espacenet)

        Returns:
            Список словарей с результатами
        """
        if source == "google":
            return await self._search_google(query, limit)
        else:
            return await self._search_espacenet(query, limit)

    async def _search_google(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Поиск на Google Patents."""
        client = await self._get_client()
        results = []

        try:
            # Google Patents search URL
            search_url = f"{self.GOOGLE_PATENTS_URL}/?q={query.replace(' ', '%20')}"

            logger.info(f"Searching Google Patents: {query}")
            response = await client.get(search_url)

            if response.status_code != 200:
                logger.warning(f"Got status {response.status_code}")
                return results

            soup = BeautifulSoup(response.text, 'html.parser')

            # Найти элементы патентов
            patent_elements = soup.select("patent-search-result")

            for elem in patent_elements[:limit]:
                patent_data = await self._parse_google_patent(elem)
                if patent_data:
                    results.append(patent_data)

            logger.info(f"Found {len(results)} patents on Google Patents")

        except Exception as e:
            logger.error(f"Google Patents search failed: {e}")

        return results

    async def _search_espacenet(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Поиск на Espacenet."""
        client = await self._get_client()
        results = []

        try:
            # Espacenet search URL
            search_url = f"{self.ESPACENET_URL}/patentsearch/family.json?q={query.replace(' ', '%20')}"

            logger.info(f"Searching Espacenet: {query}")
            response = await client.get(search_url)

            if response.status_code != 200:
                logger.warning(f"Got status {response.status_code}")
                return results

            data = response.json()

            # Распарсить JSON ответ
            if "results" in data:
                for item in data["results"][:limit]:
                    patent_data = self._parse_espacenet_patent(item)
                    if patent_data:
                        results.append(patent_data)

            logger.info(f"Found {len(results)} patents on Espacenet")

        except Exception as e:
            logger.error(f"Espacenet search failed: {e}")

        return results

    async def _parse_google_patent(self, element) -> dict[str, Any] | None:
        """
        Распарсить патент с Google Patents.

        Args:
            element: BeautifulSoup элемент

        Returns:
            Словарь с данными патента
        """
        try:
            data = {
                "source": "Google Patents",
            }

            # Номер патента
            number_elem = element.select_one(".patent-number")
            if number_elem:
                data["patent_number"] = number_elem.get_text(strip=True)
                data["source_id"] = data["patent_number"]

            # Заголовок
            title_elem = element.select_one(".patent-title")
            if title_elem:
                data["title"] = title_elem.get_text(strip=True)

            # Заявители
            applicants_elem = element.select_one(".applicant")
            if applicants_elem:
                data["applicants"] = [
                    a.get_text(strip=True)
                    for a in applicants_elem.select("a")
                ]

            # Изобретатели
            inventors_elem = element.select_one(".inventor")
            if inventors_elem:
                data["inventors"] = [
                    i.get_text(strip=True)
                    for i in inventors_elem.select("a")
                ]

            # Дата публикации
            date_elem = element.select_one(".publication-date")
            if date_elem:
                data["publication_date"] = date_elem.get_text(strip=True)

            # IPC классы
            ipc_elem = element.select_one(".ipc-class")
            if ipc_elem:
                data["ipc_classes"] = [
                    ipc.get_text(strip=True)
                    for ipc in ipc_elem.select("a")
                ]

            # URL
            link_elem = element.select_one("a[href^='/patent/']")
            if link_elem:
                data["url"] = f"{self.GOOGLE_PATENTS_URL}{link_elem.get('href')}"

            # Аннотация
            abstract_elem = element.select_one(".abstract")
            if abstract_elem:
                data["abstract"] = abstract_elem.get_text(strip=True)

            return data

        except Exception as e:
            logger.error(f"Error parsing Google patent: {e}")
            return None

    def _parse_espacenet_patent(self, item: dict) -> dict[str, Any] | None:
        """
        Распарсить патент с Espacenet.

        Args:
            item: JSON объект патента

        Returns:
            Словарь с данными патента
        """
        try:
            data = {
                "source": "Espacenet",
                "source_id": item.get("docNumber"),
                "patent_number": item.get("docNumber"),
                "title": item.get("title", ""),
                "publication_date": item.get("publicationDate", ""),
                "url": f"{self.ESPACENET_URL}/patentsearch/family/{item.get('docNumber')}",
            }

            # Заявители
            if "applicant" in item:
                data["applicants"] = [item["applicant"]] if isinstance(item["applicant"], str) else item["applicant"]

            # Изобретатели
            if "inventor" in item:
                data["inventors"] = [item["inventor"]] if isinstance(item["inventor"], str) else item["inventor"]

            # IPC классы
            if "classification" in item:
                data["ipc_classes"] = [item["classification"]] if isinstance(item["classification"], str) else item["classification"]

            return data

        except Exception as e:
            logger.error(f"Error parsing Espacenet patent: {e}")
            return None

    async def parse_search_results(self, data: list[dict[str, Any]]) -> list[Paper]:
        """
        Распарсить результаты поиска в список Paper.

        Для патентов используем адаптированную модель Paper.

        Args:
            data: Список словарей с результатами

        Returns:
            Список Paper
        """
        papers = []

        for item in data:
            # Адаптировать патент к модели Paper
            paper = Paper(
                title=item.get("title", ""),
                authors=item.get("inventors", []) or item.get("applicants", []),
                publication_date=item.get("publication_date"),
                journal=item.get("source"),  # Источник патента
                doi=item.get("patent_number"),  # Номер патента как DOI
                abstract=item.get("abstract"),
                source=item.get("source", self.source),
                source_id=item.get("source_id"),
                url=item.get("url"),
                keywords=item.get("ipc_classes", []),  # IPC классы как keywords
            )

            # Нормализовать
            paper = self.normalize_paper(paper)

            # Валидировать
            is_valid, errors = self.validate_paper(paper)
            if is_valid:
                papers.append(paper)
            else:
                logger.warning(f"Invalid patent: {errors}")

        return papers

    async def parse_full_text(self, url: str, metadata: dict[str, Any]) -> Paper | None:
        """
        Распарсить полный текст патента.

        Args:
            url: URL патента
            metadata: Метаданные патента

        Returns:
            Paper с полным текстом
        """
        client = await self._get_client()

        try:
            response = await client.get(url)

            if response.status_code != 200:
                logger.warning(f"Got status {response.status_code}")
                return None

            soup = BeautifulSoup(response.text, 'html.parser')

            # Полный текст патента
            full_text = ""

            # Описание
            description_elem = soup.select_one(".description")
            if description_elem:
                full_text = description_elem.get_text(strip=True)

            #Claims (формула изобретения)
            claims_elem = soup.select_one(".claims")
            if claims_elem:
                metadata["claims"] = claims_elem.get_text(strip=True)

            # Обновить метаданные
            abstract_elem = soup.select_one(".abstract")
            if abstract_elem:
                metadata["abstract"] = abstract_elem.get_text(strip=True)

            paper = Paper(
                title=metadata.get("title", ""),
                authors=metadata.get("inventors", []) or metadata.get("applicants", []),
                publication_date=metadata.get("publication_date"),
                journal=metadata.get("source"),
                doi=metadata.get("patent_number"),
                abstract=metadata.get("abstract"),
                full_text=full_text,
                keywords=metadata.get("ipc_classes", []),
                source=metadata.get("source", self.source),
                url=url,
            )

            return self.normalize_paper(paper)

        except Exception as e:
            logger.error(f"Error parsing patent full text: {e}")
            return None

    async def extract_keywords(self, paper: Paper) -> list[str]:
        """
        Извлечь ключевые слова из патента.

        Для патентов используем IPC классы.

        Args:
            paper: Патент

        Returns:
            Список ключевых слов
        """
        if paper.keywords:
            return paper.keywords

        # Извлечь IPC классы из текста
        keywords = []

        if paper.abstract or paper.full_text:
            text = (paper.abstract or "") + " " + (paper.full_text or "")

            # Найти IPC классы (формат: A61K31/00)
            ipc_pattern = r'\b[A-H]\d{2}[A-Z]\d{1,4}/\d{2,4}\b'
            matches = re.findall(ipc_pattern, text, re.IGNORECASE)
            keywords.extend(matches[:10])

        return keywords


async def parse_patents(
    query: str,
    limit: int = 20,
    source: str = "google",
) -> list[Paper]:
    """
    Быстрый парсинг патентов.

    Args:
        query: Поисковый запрос
        limit: Максимум результатов
        source: Источник (google или espacenet)

    Returns:
        Список Paper
    """
    parser = PatentParser()

    try:
        results = await parser.search(query, limit, source)
        papers = await parser.parse_search_results(results)
        return papers
    finally:
        await parser.close()


if __name__ == "__main__":
    # Пример использования
    import asyncio

    async def main():
        papers = await parse_patents("nickel alloy", limit=5, source="google")
        print(f"Found {len(papers)} patents")

        for paper in papers:
            print(f"- {paper.title} ({paper.doi})")

    asyncio.run(main())
