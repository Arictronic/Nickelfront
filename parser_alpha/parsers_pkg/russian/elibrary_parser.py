"""
eLibrary.ru Parser

Парсер для обработки результатов поиска из eLibrary.ru (РИНЦ).
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from parsers_pkg.models import Paper


class ELibraryParser:
    """Парсер для результатов eLibrary.ru"""
    
    def __init__(self):
        """Инициализация парсера"""
        self.source_name = "eLibrary"
    
    async def parse_search_results(
        self,
        results: List[Dict[str, Any]]
    ) -> List[Paper]:
        """
        Парсинг результатов поиска
        
        Args:
            results: Список словарей с результатами поиска
        
        Returns:
            Список объектов Paper
        """
        papers = []
        
        for result in results:
            try:
                paper = self._parse_single_result(result)
                if paper:
                    papers.append(paper)
            except Exception as e:
                print(f"Ошибка парсинга результата: {e}")
                continue
        
        return papers
    
    def _parse_single_result(self, result: Dict[str, Any]) -> Optional[Paper]:
        """
        Парсинг одного результата
        
        Args:
            result: Словарь с данными статьи
        
        Returns:
            Объект Paper или None
        """
        try:
            # Обязательные поля
            if not result.get('title') or not result.get('url'):
                return None
            
            # Создать объект Paper
            paper = Paper(
                title=result['title'],
                authors=result.get('authors', []),
                abstract=result.get('abstract', ''),
                url=result['url'],
                source=self.source_name,
                published_date=self._parse_date(result.get('year')),
                doi=result.get('doi'),
                pdf_url=None,  # eLibrary обычно не предоставляет прямые PDF ссылки
                keywords=result.get('keywords', []),
                citations=result.get('citations', 0),
                metadata={
                    'elibrary_id': result.get('elibrary_id'),
                    'source_info': result.get('source', ''),
                    'year': result.get('year'),
                }
            )
            
            return paper
            
        except Exception as e:
            print(f"Ошибка создания Paper объекта: {e}")
            return None
    
    def _parse_date(self, year: Optional[str]) -> Optional[str]:
        """
        Парсинг даты из года
        
        Args:
            year: Год публикации
        
        Returns:
            Дата в формате ISO или None
        """
        if not year:
            return None
        
        try:
            # Попытка создать дату из года
            year_int = int(year)
            if 1900 <= year_int <= datetime.now().year:
                return f"{year_int}-01-01"
        except (ValueError, TypeError):
            pass
        
        return None
    
    async def parse_article_details(
        self,
        details: Dict[str, Any]
    ) -> Optional[Paper]:
        """
        Парсинг детальной информации о статье
        
        Args:
            details: Словарь с детальными данными
        
        Returns:
            Объект Paper или None
        """
        return self._parse_single_result(details)
    
    def enrich_paper_with_details(
        self,
        paper: Paper,
        details: Dict[str, Any]
    ) -> Paper:
        """
        Обогащение объекта Paper детальной информацией
        
        Args:
            paper: Существующий объект Paper
            details: Словарь с дополнительными данными
        
        Returns:
            Обновленный объект Paper
        """
        # Обновить поля, если они отсутствуют
        if not paper.abstract and details.get('abstract'):
            paper.abstract = details['abstract']
        
        if not paper.keywords and details.get('keywords'):
            paper.keywords = details['keywords']
        
        if not paper.doi and details.get('doi'):
            paper.doi = details['doi']
        
        if not paper.citations and details.get('citations'):
            paper.citations = details['citations']
        
        # Обновить метаданные
        if paper.metadata is None:
            paper.metadata = {}
        
        paper.metadata.update({
            'elibrary_id': details.get('elibrary_id'),
            'source_info': details.get('source', ''),
            'year': details.get('year'),
        })
        
        return paper