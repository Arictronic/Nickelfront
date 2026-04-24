"""
eLibrary.ru (РИНЦ) API Client

Клиент для работы с Российским индексом научного цитирования (РИНЦ).
Использует web scraping, так как официальный API требует регистрации.
"""

import aiohttp
from typing import Dict, List, Optional, Any
from bs4 import BeautifulSoup
import asyncio
from urllib.parse import urlencode, quote_plus


class ELibraryClient:
    """Клиент для работы с eLibrary.ru"""
    
    BASE_URL = "https://www.elibrary.ru"
    SEARCH_URL = f"{BASE_URL}/query_results.asp"
    
    def __init__(self, timeout: int = 30):
        """
        Инициализация клиента
        
        Args:
            timeout: Таймаут запросов в секундах
        """
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session: Optional[aiohttp.ClientSession] = None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
    
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(
            timeout=self.timeout,
            headers=self.headers
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
    
    async def close(self):
        """Закрыть сессию"""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def search(
        self,
        query: str,
        limit: int = 10,
        sort_by: str = "relevance"
    ) -> List[Dict[str, Any]]:
        """
        Поиск статей в eLibrary
        
        Args:
            query: Поисковый запрос
            limit: Максимальное количество результатов
            sort_by: Сортировка ('relevance', 'date', 'citations')
        
        Returns:
            Список словарей с данными статей
        """
        if not self.session:
            self.session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers=self.headers
            )
        
        # Параметры поиска
        params = {
            'queryid': '1',
            'query_from': 'advanced',
            'query': query,
            'sortorder': '0' if sort_by == 'relevance' else '1',
            'pagenum': '1',
        }
        
        results = []
        
        try:
            # Выполнить поиск
            url = f"{self.SEARCH_URL}?{urlencode(params)}"
            
            async with self.session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"HTTP {response.status}: {await response.text()}")
                
                html = await response.text()
                soup = BeautifulSoup(html, 'lxml')
                
                # Найти результаты поиска
                items = soup.find_all('table', {'id': lambda x: x and x.startswith('restab')})
                
                for item in items[:limit]:
                    try:
                        result = self._parse_search_item(item)
                        if result:
                            results.append(result)
                    except Exception as e:
                        print(f"Ошибка парсинга элемента: {e}")
                        continue
            
            # Задержка для предотвращения блокировки
            await asyncio.sleep(1)
            
        except Exception as e:
            print(f"Ошибка поиска в eLibrary: {e}")
        
        return results
    
    def _parse_search_item(self, item: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """
        Парсинг элемента результата поиска
        
        Args:
            item: BeautifulSoup элемент
        
        Returns:
            Словарь с данными статьи или None
        """
        try:
            result = {}
            
            # Заголовок и ссылка
            title_elem = item.find('b')
            if title_elem:
                link = title_elem.find('a')
                if link:
                    result['title'] = link.get_text(strip=True)
                    result['url'] = self.BASE_URL + link.get('href', '')
                    
                    # ID статьи из URL
                    if 'id=' in result['url']:
                        result['elibrary_id'] = result['url'].split('id=')[1].split('&')[0]
            
            # Авторы
            authors_elem = item.find('i')
            if authors_elem:
                authors_text = authors_elem.get_text(strip=True)
                result['authors'] = [a.strip() for a in authors_text.split(',')]
            
            # Журнал и год
            font_elems = item.find_all('font', {'color': 'darkgreen'})
            for font in font_elems:
                text = font.get_text(strip=True)
                if text:
                    # Попытка извлечь год
                    import re
                    year_match = re.search(r'\b(19|20)\d{2}\b', text)
                    if year_match:
                        result['year'] = year_match.group(0)
                    result['source'] = text
            
            # Аннотация
            abstract_elem = item.find('font', {'color': 'black'})
            if abstract_elem:
                result['abstract'] = abstract_elem.get_text(strip=True)
            
            # Метрики цитирования (если есть)
            metrics = item.find_all('font', {'color': 'blue'})
            for metric in metrics:
                text = metric.get_text(strip=True)
                if 'цитирований' in text.lower():
                    import re
                    citations = re.search(r'\d+', text)
                    if citations:
                        result['citations'] = int(citations.group(0))
            
            return result if result.get('title') else None
            
        except Exception as e:
            print(f"Ошибка парсинга элемента: {e}")
            return None
    
    async def get_article_details(self, article_id: str) -> Optional[Dict[str, Any]]:
        """
        Получить детальную информацию о статье
        
        Args:
            article_id: ID статьи в eLibrary
        
        Returns:
            Словарь с детальными данными или None
        """
        if not self.session:
            self.session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers=self.headers
            )
        
        try:
            url = f"{self.BASE_URL}/item.asp?id={article_id}"
            
            async with self.session.get(url) as response:
                if response.status != 200:
                    return None
                
                html = await response.text()
                soup = BeautifulSoup(html, 'lxml')
                
                details = {
                    'elibrary_id': article_id,
                    'url': url
                }
                
                # Заголовок
                title = soup.find('h2')
                if title:
                    details['title'] = title.get_text(strip=True)
                
                # Авторы
                authors_section = soup.find('div', {'id': 'authors'})
                if authors_section:
                    authors = authors_section.find_all('a')
                    details['authors'] = [a.get_text(strip=True) for a in authors]
                
                # Аннотация
                abstract = soup.find('div', {'id': 'abstract'})
                if abstract:
                    details['abstract'] = abstract.get_text(strip=True)
                
                # Ключевые слова
                keywords = soup.find('div', {'id': 'keywords'})
                if keywords:
                    kw_text = keywords.get_text(strip=True)
                    details['keywords'] = [k.strip() for k in kw_text.split(',')]
                
                # DOI
                doi_elem = soup.find('a', href=lambda x: x and 'doi.org' in x)
                if doi_elem:
                    details['doi'] = doi_elem.get('href').split('doi.org/')[-1]
                
                # Метрики
                citations = soup.find('div', {'id': 'citations'})
                if citations:
                    import re
                    cit_match = re.search(r'\d+', citations.get_text())
                    if cit_match:
                        details['citations'] = int(cit_match.group(0))
                
                return details
                
        except Exception as e:
            print(f"Ошибка получения деталей статьи: {e}")
            return None