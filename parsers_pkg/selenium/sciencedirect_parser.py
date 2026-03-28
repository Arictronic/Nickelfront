"""
Selenium парсер для ScienceDirect.

Обход защиты и парсинг статей с scienceirect.com
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC  # noqa: N812
from selenium.webdriver.support.ui import WebDriverWait

from parsers_pkg.base import BaseParser
from shared.schemas.paper import Paper

logger = logging.getLogger(__name__)


@dataclass
class ScienceDirectConfig:
    """Конфигурация для ScienceDirect парсера."""
    headless: bool = True
    timeout: int = 30
    max_scroll_pause: int = 3
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class ScienceDirectParser(BaseParser):
    """Парсер для ScienceDirect с использованием Selenium."""

    BASE_URL = "https://www.sciencedirect.com"
    SEARCH_URL = f"{BASE_URL}/search"

    def __init__(self, config: ScienceDirectConfig | None = None):
        """
        Инициализация парсера.

        Args:
            config: Конфигурация парсера
        """
        super().__init__(source="ScienceDirect")
        self.config = config or ScienceDirectConfig()
        self.driver: webdriver.Chrome | None = None

    async def _get_driver(self) -> webdriver.Chrome:
        """Получить WebDriver."""
        if self.driver is None:
            options = Options()

            if self.config.headless:
                options.add_argument("--headless=new")

            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument(f"--user-agent={self.config.user_agent}")
            options.add_argument("--window-size=1920,1080")

            self.driver = webdriver.Chrome(options=options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        return self.driver

    async def close(self):
        """Закрыть соединение."""
        if self.driver:
            self.driver.quit()
            self.driver = None

    async def search(
        self,
        query: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Поиск статей на ScienceDirect.

        Args:
            query: Поисковый запрос
            limit: Максимум результатов

        Returns:
            Список словарей с результатами
        """
        driver = await self._get_driver()
        results = []

        try:
            # Перейти на страницу поиска
            search_url = f"{self.SEARCH_URL}?qs={query.replace(' ', '%20')}"
            logger.info(f"Navigating to: {search_url}")

            driver.get(search_url)

            # Подождать загрузки результатов
            wait = WebDriverWait(driver, self.config.timeout)

            try:
                wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "[data-testid='search-result-item']")
                ))
            except TimeoutException:
                logger.warning("No search results found")
                return results

            # Прокрутить страницу для загрузки всех результатов
            await self._scroll_page(driver)

            # Получить элементы результатов
            result_elements = driver.find_elements(
                By.CSS_SELECTOR, "[data-testid='search-result-item']"
            )

            logger.info(f"Found {len(result_elements)} results")

            # Распарсить каждый результат
            for element in result_elements[:limit]:
                try:
                    paper_data = await self._parse_result_element(element)
                    if paper_data:
                        results.append(paper_data)
                except Exception as e:
                    logger.error(f"Error parsing result: {e}")

            logger.info(f"Successfully parsed {len(results)} papers")

        except Exception as e:
            logger.error(f"Search failed: {e}")

        return results

    async def _scroll_page(self, driver: webdriver.Chrome):
        """Прокрутить страницу для загрузки контента."""
        last_height = driver.execute_script("return document.body.scrollHeight")

        for _ in range(3):  # Максимум 3 прокрутки
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            await asyncio.sleep(self.config.max_scroll_pause)

            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

    async def _parse_result_element(self, element) -> dict[str, Any] | None:
        """
        Распарсить элемент результата.

        Args:
            element: WebElement результата

        Returns:
            Словарь с данными статьи
        """
        try:
            data = {
                "source": self.source,
            }

            # Заголовок
            try:
                title_elem = element.find_element(By.CSS_SELECTOR, "a[data-testid='result-link']")
                data["title"] = title_elem.text.strip()
                data["url"] = title_elem.get_attribute("href")
            except NoSuchElementException:
                logger.warning("No title found")
                return None

            # Авторы
            try:
                authors_elem = element.find_element(By.CSS_SELECTOR, "[data-testid='authors']")
                data["authors"] = [
                    a.text.strip()
                    for a in authors_elem.find_elements(By.CSS_SELECTOR, "a")
                ]
            except NoSuchElementException:
                data["authors"] = []

            # Журнал
            try:
                journal_elem = element.find_element(By.CSS_SELECTOR, "[data-testid='publication-title']")
                data["journal"] = journal_elem.text.strip()
            except NoSuchElementException:
                data["journal"] = None

            # Дата публикации
            try:
                date_elem = element.find_element(By.CSS_SELECTOR, "[data-testid='publication-date']")
                date_str = date_elem.text.strip()
                data["publication_date"] = self._parse_date(date_str)
            except NoSuchElementException:
                data["publication_date"] = None

            # Аннотация (краткое описание)
            try:
                desc_elem = element.find_element(By.CSS_SELECTOR, "[data-testid='description']")
                data["abstract"] = desc_elem.text.strip()
            except NoSuchElementException:
                data["abstract"] = None

            return data

        except Exception as e:
            logger.error(f"Error parsing element: {e}")
            return None

    def _parse_date(self, date_str: str) -> str | None:
        """Распарсить дату из строки."""
        import re

        # Пример: "Available online 15 January 2024"
        match = re.search(r'(\d{1,2})\s+(\w+)\s+(\d{4})', date_str)
        if match:
            day, month, year = match.groups()
            months = {
                'January': '01', 'February': '02', 'March': '03',
                'April': '04', 'May': '05', 'June': '06',
                'July': '07', 'August': '08', 'September': '09',
                'October': '10', 'November': '11', 'December': '12',
            }
            month_num = months.get(month, '01')
            return f"{year}-{month_num}-{day.zfill(2)}"

        return None

    async def parse_search_results(self, data: list[dict[str, Any]]) -> list[Paper]:
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

    async def parse_full_text(self, url: str, metadata: dict[str, Any]) -> Paper | None:
        """
        Распарсить полный текст статьи.

        Args:
            url: URL статьи
            metadata: Метаданные статьи

        Returns:
            Paper с полным текстом
        """
        driver = await self._get_driver()

        try:
            driver.get(url)
            wait = WebDriverWait(driver, self.config.timeout)

            # Подождать загрузки контента
            try:
                wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "article")
                ))
            except TimeoutException:
                logger.warning("Article content not loaded")
                return None

            # Получить полный текст
            full_text = ""

            # Заголовок
            try:
                title_elem = driver.find_element(By.CSS_SELECTOR, "h1")
                metadata["title"] = title_elem.text.strip()
            except NoSuchElementException:
                pass

            # Аннотация
            try:
                abstract_elem = driver.find_element(By.CSS_SELECTOR, "[data-testid='abstract']")
                metadata["abstract"] = abstract_elem.text.strip()
            except NoSuchElementException:
                pass

            # Основной текст
            try:
                content_elems = driver.find_elements(By.CSS_SELECTOR, "article p")
                full_text = "\n\n".join([elem.text.strip() for elem in content_elems if elem.text.strip()])
            except NoSuchElementException:
                pass

            # Ключевые слова
            keywords = []
            try:
                keywords_elem = driver.find_element(By.CSS_SELECTOR, "[data-testid='keywords']")
                keywords = [
                    kw.text.strip()
                    for kw in keywords_elem.find_elements(By.TAG_NAME, "a")
                ]
            except NoSuchElementException:
                pass

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

    async def extract_keywords(self, paper: Paper) -> list[str]:
        """
        Извлечь ключевые слова из статьи.

        Args:
            paper: Статья

        Returns:
            Список ключевых слов
        """
        # Если ключевые слова уже есть, вернуть их
        if paper.keywords:
            return paper.keywords

        # Извлечь из аннотации
        keywords = []

        if paper.abstract:
            # Простая эвристика - найти важные термины
            important_terms = [
                "nickel", "superalloy", "alloy", "temperature",
                "corrosion", "strength", "microstructure",
            ]

            abstract_lower = paper.abstract.lower()
            for term in important_terms:
                if term in abstract_lower:
                    keywords.append(term)

        return keywords


async def parse_sciencedirect(
    query: str,
    limit: int = 20,
) -> list[Paper]:
    """
    Быстрый парсинг ScienceDirect.

    Args:
        query: Поисковый запрос
        limit: Максимум результатов

    Returns:
        Список Paper
    """
    parser = ScienceDirectParser()

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
        papers = await parse_sciencedirect("nickel-based superalloys", limit=5)
        print(f"Found {len(papers)} papers")

        for paper in papers:
            print(f"- {paper.title}")

    asyncio.run(main())
