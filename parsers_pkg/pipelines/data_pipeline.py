"""
Data pipelines для обработки статей.

Конвейеры обработки:
- Очистка данных
- Валидация
- Обогащение метаданными
- Дедупликация
- Сохранение
"""

from typing import List, Optional, Callable, Awaitable, Any
from dataclasses import dataclass, field
from datetime import datetime
import logging

from shared.schemas.paper import Paper
from parsers_pkg.base.deduplication import Deduplicator, DeduplicationResult

logger = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    """Контекст конвейера."""
    papers: List[Paper] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None


@dataclass
class PipelineResult:
    """Результат выполнения конвейера."""
    success: bool
    papers: List[Paper]
    errors: List[str]
    stats: dict
    duration_seconds: float


class PipelineStage:
    """Базовый класс этапа конвейера."""
    
    def __init__(self, name: str):
        self.name = name
    
    async def process(self, context: PipelineContext) -> PipelineContext:
        """
        Обработать контекст.
        
        Args:
            context: Контекст конвейера
            
        Returns:
            Обновлённый контекст
        """
        raise NotImplementedError


class CleaningStage(PipelineStage):
    """Этап очистки данных."""
    
    def __init__(self):
        super().__init__("cleaning")
    
    async def process(self, context: PipelineContext) -> PipelineContext:
        """Очистить данные статей."""
        cleaned_papers = []
        
        for paper in context.papers:
            try:
                # Очистка заголовка
                if paper.title:
                    paper.title = self._clean_text(paper.title)
                
                # Очистка аннотации
                if paper.abstract:
                    paper.abstract = self._clean_text(paper.abstract)
                
                # Очистка полного текста
                if paper.full_text:
                    paper.full_text = self._clean_text(paper.full_text)
                
                # Очистка авторов
                if paper.authors:
                    paper.authors = [
                        self._clean_text(author) 
                        for author in paper.authors 
                        if self._clean_text(author)
                    ]
                
                # Очистка ключевых слов
                if paper.keywords:
                    paper.keywords = [
                        self._clean_text(kw) 
                        for kw in paper.keywords 
                        if self._clean_text(kw)
                    ]
                
                cleaned_papers.append(paper)
                
            except Exception as e:
                context.errors.append(f"Error cleaning paper '{paper.title[:50]}...': {e}")
        
        context.papers = cleaned_papers
        context.stats["cleaned_count"] = len(cleaned_papers)
        
        return context
    
    def _clean_text(self, text: str) -> str:
        """Очистить текст."""
        if not text:
            return ""
        
        # Удалить лишние пробелы
        text = " ".join(text.split())
        
        # Удалить control characters
        text = "".join(char for char in text if ord(char) >= 32 or char in '\n\r\t')
        
        # Исправить распространённые проблемы с кодировкой
        text = text.replace('â€"', "'").replace('â€"', "'")
        text = text.replace('â€"', '"').replace('â€"', '"')
        text = text.replace('â€"', '"').replace('â€"', '"')
        text = text.replace('â€"', '-').replace('â€"', '-')
        
        return text.strip()


class ValidationStage(PipelineStage):
    """Этап валидации данных."""
    
    def __init__(self, required_fields: Optional[List[str]] = None):
        super().__init__("validation")
        self.required_fields = required_fields or ["title", "source"]
    
    async def process(self, context: PipelineContext) -> PipelineContext:
        """Валидировать данные статей."""
        valid_papers = []
        
        for paper in context.papers:
            is_valid, errors = self._validate_paper(paper)
            
            if is_valid:
                valid_papers.append(paper)
            else:
                for error in errors:
                    context.errors.append(f"Validation error for '{paper.title[:50]}...': {error}")
        
        context.papers = valid_papers
        context.stats["valid_count"] = len(valid_papers)
        context.stats["invalid_count"] = len(context.papers) - len(valid_papers)
        
        return context
    
    def _validate_paper(self, paper: Paper) -> tuple[bool, List[str]]:
        """Валидировать статью."""
        errors = []
        
        # Проверка обязательных полей
        for field_name in self.required_fields:
            value = getattr(paper, field_name, None)
            if not value:
                errors.append(f"Missing required field: {field_name}")
        
        # Проверка DOI (если есть)
        if paper.doi:
            if not self._is_valid_doi(paper.doi):
                errors.append(f"Invalid DOI format: {paper.doi}")
        
        # Проверка URL (если есть)
        if paper.url:
            if not self._is_valid_url(paper.url):
                errors.append(f"Invalid URL format: {paper.url}")
        
        # Проверка даты публикации
        if paper.publication_date:
            if not self._is_valid_date(paper.publication_date):
                errors.append(f"Invalid publication date: {paper.publication_date}")
        
        return len(errors) == 0, errors
    
    def _is_valid_doi(self, doi: str) -> bool:
        """Проверить DOI."""
        import re
        pattern = r'^10\.\d{4,9}/[-._;()/:A-Z0-9]+$'
        return bool(re.match(pattern, doi, re.IGNORECASE))
    
    def _is_valid_url(self, url: str) -> bool:
        """Проверить URL."""
        import re
        pattern = r'^https?://[^\s]+$'
        return bool(re.match(pattern, url, re.IGNORECASE))
    
    def _is_valid_date(self, date) -> bool:
        """Проверить дату."""
        from datetime import datetime
        if isinstance(date, datetime):
            return True
        if isinstance(date, str):
            try:
                datetime.fromisoformat(date.replace("Z", "+00:00"))
                return True
            except ValueError:
                return False
        return False


class DeduplicationStage(PipelineStage):
    """Этап дедупликации."""
    
    def __init__(self, existing_papers: Optional[List[dict]] = None):
        super().__init__("deduplication")
        self.deduplicator = Deduplicator(existing_papers or [])
    
    async def process(self, context: PipelineContext) -> PipelineContext:
        """Удалить дубликаты."""
        unique_papers = []
        duplicates_count = 0
        
        for paper in context.papers:
            result = self.deduplicator.check_duplicate(
                title=paper.title,
                doi=paper.doi,
                source_id=paper.source_id,
                abstract=paper.abstract,
            )
            
            if result.is_duplicate:
                duplicates_count += 1
                logger.info(
                    f"Duplicate found: '{paper.title[:50]}...' - {result.reason}"
                )
            else:
                unique_papers.append(paper)
                # Добавить в список существующих для последующих проверок
                self.deduplicator.add_existing_paper({
                    "title": paper.title,
                    "doi": paper.doi,
                    "source_id": paper.source_id,
                    "abstract": paper.abstract,
                })
        
        context.papers = unique_papers
        context.stats["duplicates_removed"] = duplicates_count
        context.stats["unique_count"] = len(unique_papers)
        
        return context


class EnrichmentStage(PipelineStage):
    """Этап обогащения метаданными."""
    
    def __init__(self, source: str):
        super().__init__("enrichment")
        self.source = source
    
    async def process(self, context: PipelineContext) -> PipelineContext:
        """Обогатить статьи метаданными."""
        for paper in context.papers:
            # Установить источник если не указан
            if not paper.source:
                paper.source = self.source
            
            # Установить текущую дату если не указана дата создания
            if not paper.created_at:
                paper.created_at = datetime.now()
        
        context.stats["enriched_count"] = len(context.papers)
        
        return context


class DataPipeline:
    """Конвейер обработки данных."""
    
    def __init__(self, name: str = "default"):
        self.name = name
        self.stages: List[PipelineStage] = []
    
    def add_stage(self, stage: PipelineStage):
        """Добавить этап конвейера."""
        self.stages.append(stage)
        return self
    
    async def process(self, papers: List[Paper]) -> PipelineResult:
        """
        Обработать статьи через конвейер.
        
        Args:
            papers: Список статей для обработки
            
        Returns:
            PipelineResult с результатом обработки
        """
        context = PipelineContext(papers=papers)
        
        logger.info(f"Starting pipeline '{self.name}' with {len(papers)} papers")
        
        try:
            for stage in self.stages:
                logger.info(f"Running stage '{stage.name}'")
                context = await stage.process(context)
                
                if context.errors:
                    logger.warning(f"Stage '{stage.name}' produced {len(context.errors)} errors")
            
            context.end_time = datetime.now()
            duration = (context.end_time - context.start_time).total_seconds()
            
            logger.info(
                f"Pipeline '{self.name}' completed in {duration:.2f}s. "
                f"Result: {len(context.papers)} papers, {len(context.errors)} errors"
            )
            
            return PipelineResult(
                success=len(context.papers) > 0,
                papers=context.papers,
                errors=context.errors,
                stats=context.stats,
                duration_seconds=duration,
            )
            
        except Exception as e:
            logger.error(f"Pipeline '{self.name}' failed: {e}")
            context.errors.append(f"Pipeline error: {e}")
            
            return PipelineResult(
                success=False,
                papers=[],
                errors=context.errors,
                stats=context.stats,
                duration_seconds=0,
            )


def create_default_pipeline(
    source: str = "unknown",
    existing_papers: Optional[List[dict]] = None,
    required_fields: Optional[List[str]] = None,
) -> DataPipeline:
    """
    Создать конвейер по умолчанию.
    
    Args:
        source: Источник статей
        existing_papers: Существующие статьи для дедупликации
        required_fields: Обязательные поля для валидации
        
    Returns:
        Настроенный DataPipeline
    """
    pipeline = DataPipeline(name=f"default_{source}")
    
    pipeline.add_stage(CleaningStage())
    pipeline.add_stage(ValidationStage(required_fields))
    pipeline.add_stage(DeduplicationStage(existing_papers))
    pipeline.add_stage(EnrichmentStage(source))
    
    return pipeline


async def process_papers(
    papers: List[Paper],
    source: str = "unknown",
    existing_papers: Optional[List[dict]] = None,
) -> PipelineResult:
    """
    Быстрая обработка статей через конвейер по умолчанию.
    
    Args:
        papers: Список статей
        source: Источник
        existing_papers: Существующие статьи
        
    Returns:
        PipelineResult с результатом обработки
    """
    pipeline = create_default_pipeline(source, existing_papers)
    return await pipeline.process(papers)


if __name__ == "__main__":
    # Пример использования
    from shared.schemas.paper import Paper
    
    papers = [
        Paper(
            title="  Nickel-based superalloys  ",
            authors=["  John Smith  ", "  Jane Doe  "],
            abstract="This paper presents...",
            keywords=["  nickel  ", "  superalloys  ", ""],
            source="CORE",
        ),
        Paper(
            title="",  # Неверная статья
            source="CORE",
        ),
    ]
    
    import asyncio
    
    result = asyncio.run(process_papers(papers, source="CORE"))
    
    print(f"Success: {result.success}")
    print(f"Processed: {len(result.papers)} papers")
    print(f"Errors: {len(result.errors)}")
    print(f"Stats: {result.stats}")
