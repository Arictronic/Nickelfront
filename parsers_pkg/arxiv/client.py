"""arXiv API клиент.

arXiv - репозиторий препринтов по физике, математике, computer science, materials science.
API документация: https://arxiv.org/help/api
"""

import asyncio
import random
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

import httpx
from loguru import logger

from parsers_pkg.base import BaseAPIClient

# Поисковые запросы для тематики никелевых сплавов
ARXIV_SEARCH_QUERIES = [
    "nickel-based alloys",
    "superalloys",
    "heat resistant alloys",
    "nickel superalloys",
    "nickel alloys high temperature",
    "Ni-based superalloys",
    "inconel",
    "hastelloy",
]

# Категории arXiv для материаловедения
ARXIV_CATEGORIES = [
    "cond-mat.mtrl-sci",
    "physics.chem-ph",
    "physics.app-ph",
]


class ArxivClient(BaseAPIClient):
    """Клиент для arXiv API."""

    BASE_URL = "https://export.arxiv.org/api/query"
    RATE_LIMIT_DELAY = 3.0
    MAX_RETRIES = 4
    RETRY_BACKOFF_BASE = 2.0

    def __init__(self, timeout: float = 30.0, rate_limit: bool = True):
        """
        Инициализация клиента.

        Args:
            timeout: Таймаут запросов в секундах
            rate_limit: Включить rate limiting (рекомендуется)
        """
        super().__init__(base_url="", api_key=None, timeout=timeout)
        self.rate_limit = rate_limit
        self._last_request_time: datetime | None = None

    async def _apply_rate_limit(self):
        """Применить rate limiting между запросами."""
        if not self.rate_limit:
            return

        if self._last_request_time:
            elapsed = (datetime.now() - self._last_request_time).total_seconds()
            if elapsed < self.RATE_LIMIT_DELAY:
                await asyncio.sleep(self.RATE_LIMIT_DELAY - elapsed)

        self._last_request_time = datetime.now()

    async def search(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0,
        categories: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Поиск статей в arXiv.

        Args:
            query: Поисковый запрос
            limit: Макс. количество результатов (1-100)
            offset: Смещение для пагинации
            categories: Фильтр по категориям arXiv

        Returns:
            Список статей
        """
        await self._apply_rate_limit()
        client = await self._get_client()

        search_query = f"all:{query}"

        if categories:
            category_filter = " OR ".join(f"cat:{cat}" for cat in categories)
            search_query = f"({search_query}) AND ({category_filter})"

        params = {
            "search_query": search_query,
            "start": offset,
            "max_results": min(limit, 100),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        logger.info(f"arXiv: поиск по запросу '{query}', limit={limit}")

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = await client.get(self.BASE_URL, params=params)

                if response.status_code == 429:
                    if attempt >= self.MAX_RETRIES:
                        logger.error(
                            "arXiv API rate limit (429) exhausted after {} attempts for query='{}'",
                            attempt,
                            query,
                        )
                        return []

                    retry_after_raw = response.headers.get("Retry-After")
                    retry_after = 0.0
                    if retry_after_raw:
                        try:
                            retry_after = float(retry_after_raw)
                        except ValueError:
                            retry_after = 0.0
                    backoff = self.RATE_LIMIT_DELAY * (self.RETRY_BACKOFF_BASE ** (attempt - 1))
                    sleep_for = max(retry_after, backoff) + random.uniform(0.0, 0.8)
                    logger.warning(
                        "arXiv API 429 for query='{}' (attempt {}/{}), sleeping {:.1f}s",
                        query,
                        attempt,
                        self.MAX_RETRIES,
                        sleep_for,
                    )
                    await asyncio.sleep(sleep_for)
                    continue

                if 500 <= response.status_code < 600:
                    if attempt >= self.MAX_RETRIES:
                        response.raise_for_status()
                    sleep_for = (self.RATE_LIMIT_DELAY / 2.0) * (self.RETRY_BACKOFF_BASE ** (attempt - 1))
                    logger.warning(
                        "arXiv API {} for query='{}' (attempt {}/{}), retry in {:.1f}s",
                        response.status_code,
                        query,
                        attempt,
                        self.MAX_RETRIES,
                        sleep_for,
                    )
                    await asyncio.sleep(sleep_for)
                    continue

                response.raise_for_status()
                results = self._parse_xml_response(response.text)
                logger.info(f"arXiv: найдено {len(results)} статей")
                return results

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if attempt >= self.MAX_RETRIES:
                    logger.error(f"arXiv API network error: {e}")
                    return []
                sleep_for = (self.RATE_LIMIT_DELAY / 2.0) * (self.RETRY_BACKOFF_BASE ** (attempt - 1))
                logger.warning(
                    "arXiv API transient error for query='{}' (attempt {}/{}): {}. Retry in {:.1f}s",
                    query,
                    attempt,
                    self.MAX_RETRIES,
                    str(e),
                    sleep_for,
                )
                await asyncio.sleep(sleep_for)
            except httpx.HTTPError as e:
                logger.error(f"arXiv API error: {e}")
                return []
            except Exception as e:
                logger.error(f"arXiv search error: {e}")
                return []

        return []

    def _parse_xml_response(self, xml_text: str) -> list[dict[str, Any]]:
        """Распарсить XML ответ от arXiv."""
        results = []

        try:
            namespaces = {
                'atom': 'http://www.w3.org/2005/Atom',
                'arxiv': 'http://arxiv.org/schemas/atom',
            }

            root = ET.fromstring(xml_text)
            entries = root.findall('atom:entry', namespaces)

            for entry in entries:
                article = self._parse_entry(entry, namespaces)
                if article:
                    results.append(article)

        except ET.ParseError as e:
            logger.error(f"XML parse error: {e}")

        return results

    def _parse_entry(
        self,
        entry: ET.Element,
        namespaces: dict[str, str],
    ) -> dict[str, Any] | None:
        """Распарсить одну статью из XML."""
        try:
            # ID
            id_elem = entry.find('atom:id', namespaces)
            arxiv_id = id_elem.text.strip() if id_elem is not None and id_elem.text else None

            # Title
            title_elem = entry.find('atom:title', namespaces)
            title = title_elem.text.strip() if title_elem is not None and title_elem.text else "Без названия"
            title = ' '.join(title.split())

            # Авторы
            authors = []
            for author_elem in entry.findall('atom:author', namespaces):
                name_elem = author_elem.find('atom:name', namespaces)
                if name_elem is not None and name_elem.text:
                    authors.append(name_elem.text.strip())

            # Дата публикации
            published_elem = entry.find('atom:published', namespaces)
            published_date = None
            if published_elem is not None and published_elem.text:
                try:
                    # Удаляем timezone информацию для совместимости с SQLite
                    pub_date_str = published_elem.text.strip().replace('Z', '')
                    if '+' in pub_date_str:
                        pub_date_str = pub_date_str.split('+')[0]
                    if 'T' not in pub_date_str:
                        pub_date_str += 'T00:00:00'
                    published_date = pub_date_str
                except Exception:
                    pass

            # Категории
            categories = []
            for cat_elem in entry.findall('atom:category', namespaces):
                term = cat_elem.get('term')
                if term:
                    categories.append(term)

            # Аннотация
            summary_elem = entry.find('atom:summary', namespaces)
            abstract = None
            if summary_elem is not None and summary_elem.text:
                abstract = ' '.join(summary_elem.text.strip().split())

            return {
                'arxiv_id': arxiv_id,
                'title': title,
                'authors': authors,
                'published_date': published_date,
                'categories': categories,
                'abstract': abstract,
                'url': arxiv_id,
                'source': 'arXiv',
            }
        except Exception as e:
            logger.warning(f"Error parsing arXiv entry: {e}")
            return None

    async def get_full_text(self, item_id: str) -> str | None:
        """Получить URL на PDF статьи."""
        clean_id = item_id
        if clean_id.startswith('arXiv:'):
            clean_id = clean_id[6:]
        clean_id = clean_id.split('/')[-1].split('v')[0]
        return f"https://arxiv.org/pdf/{clean_id}.pdf"

    async def close(self):
        """Закрыть соединение."""
        await super().close()
        self._last_request_time = None
