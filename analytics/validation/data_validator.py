"""
Валидация данных.

Модуль для проверки корректности данных статей и патентов:
- Проверка обязательных полей
- Валидация форматов (DOI, даты, URL)
- Проверка на дубликаты
- Оценка качества данных
"""

from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field
import re
import sys
from pathlib import Path

# Добавляем корень проекта в PATH
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))


@dataclass
class ValidationResult:
    """Результат валидации."""
    
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    quality_score: float = 100.0
    
    def add_error(self, message: str):
        """Добавить ошибку."""
        self.errors.append(message)
        self.is_valid = False
        self.quality_score -= 20
    
    def add_warning(self, message: str):
        """Добавить предупреждение."""
        self.warnings.append(message)
        self.quality_score -= 5
    
    def to_dict(self) -> dict:
        """Преобразовать в словарь."""
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "quality_score": max(0, self.quality_score),
        }


class PaperValidator:
    """Валидатор данных статей."""
    
    # DOI паттерн
    DOI_PATTERN = re.compile(r'^10\.\d{4,9}/[-._;()/:A-Z0-9]+$', re.IGNORECASE)
    
    # URL паттерн
    URL_PATTERN = re.compile(
        r'^https?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE
    )
    
    def validate(self, paper: dict) -> ValidationResult:
        """
        Валидировать статью.
        
        Args:
            paper: Словарь с данными статьи
            
        Returns:
            ValidationResult с результатами валидации
        """
        result = ValidationResult()
        
        # Проверка обязательных полей
        self._check_required_fields(paper, result)
        
        # Валидация DOI
        self._validate_doi(paper, result)
        
        # Валидация URL
        self._validate_url(paper, result)
        
        # Валидация даты публикации
        self._validate_publication_date(paper, result)
        
        # Проверка на пустые поля
        self._check_empty_fields(paper, result)
        
        # Оценка качества
        self._assess_quality(paper, result)
        
        return result
    
    def _check_required_fields(self, paper: dict, result: ValidationResult):
        """Проверить обязательные поля."""
        required_fields = ["title"]
        
        for field_name in required_fields:
            if not paper.get(field_name):
                result.add_error(f"Обязательное поле '{field_name}' отсутствует")
    
    def _validate_doi(self, paper: dict, result: ValidationResult):
        """Валидировать DOI."""
        doi = paper.get("doi")
        
        if doi:
            if not self.DOI_PATTERN.match(doi):
                result.add_warning(f"Некорректный формат DOI: {doi}")
    
    def _validate_url(self, paper: dict, result: ValidationResult):
        """Валидировать URL."""
        url = paper.get("url")
        
        if url:
            if not self.URL_PATTERN.match(url):
                result.add_warning(f"Некорректный формат URL: {url}")
    
    def _validate_publication_date(self, paper: dict, result: ValidationResult):
        """Валидировать дату публикации."""
        pub_date = paper.get("publication_date")
        
        if pub_date:
            try:
                if isinstance(pub_date, str):
                    datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                result.add_warning(f"Некорректный формат даты публикации: {pub_date}")
    
    def _check_empty_fields(self, paper: dict, result: ValidationResult):
        """Проверить на пустые поля."""
        empty_fields = []
        
        for field_name, value in paper.items():
            if value is None or value == "":
                empty_fields.append(field_name)
            elif isinstance(value, list) and len(value) == 0:
                empty_fields.append(field_name)
        
        if empty_fields:
            result.add_warning(f"Пустые поля: {', '.join(empty_fields)}")
    
    def _assess_quality(self, paper: dict, result: ValidationResult):
        """Оценить качество данных."""
        quality_fields = [
            "title",
            "authors",
            "publication_date",
            "journal",
            "doi",
            "abstract",
            "keywords",
            "full_text",
        ]
        
        filled_count = 0
        for field_name in quality_fields:
            value = paper.get(field_name)
            if value:
                if isinstance(value, list) and len(value) > 0:
                    filled_count += 1
                elif isinstance(value, str) and len(value) > 0:
                    filled_count += 1
        
        if quality_fields:
            fill_rate = (filled_count / len(quality_fields)) * 100
            result.quality_score = min(100, max(0, result.quality_score + (fill_rate - 50) * 0.5))


class PatentValidator:
    """Валидатор данных патентов."""
    
    def validate(self, patent: dict) -> ValidationResult:
        """
        Валидировать патент.
        
        Args:
            patent: Словарь с данными патента
            
        Returns:
            ValidationResult с результатами валидации
        """
        result = ValidationResult()
        
        # Проверка обязательных полей
        self._check_required_fields(patent, result)
        
        # Валидация номера патента
        self._validate_patent_number(patent, result)
        
        # Валидация даты
        self._validate_dates(patent, result)
        
        # Проверка IPC классов
        self._validate_ipc_classes(patent, result)
        
        return result
    
    def _check_required_fields(self, patent: dict, result: ValidationResult):
        """Проверить обязательные поля."""
        required_fields = ["title", "patent_number"]
        
        for field_name in required_fields:
            if not patent.get(field_name):
                result.add_error(f"Обязательное поле '{field_name}' отсутствует")
    
    def _validate_patent_number(self, patent: dict, result: ValidationResult):
        """Валидировать номер патента."""
        patent_number = patent.get("patent_number")
        
        if patent_number and len(str(patent_number)) < 5:
            result.add_warning(f"Подозрительно короткий номер патента: {patent_number}")
    
    def _validate_dates(self, patent: dict, result: ValidationResult):
        """Валидировать даты."""
        for date_field in ["filing_date", "publication_date", "grant_date"]:
            date_value = patent.get(date_field)
            if date_value:
                try:
                    if isinstance(date_value, str):
                        datetime.fromisoformat(date_value.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    result.add_warning(f"Некорректный формат даты {date_field}: {date_value}")
    
    def _validate_ipc_classes(self, patent: dict, result: ValidationResult):
        """Валидировать IPC классы."""
        ipc_classes = patent.get("ipc_classes", [])
        
        if isinstance(ipc_classes, list):
            for ipc in ipc_classes:
                if not self._is_valid_ipc(ipc):
                    result.add_warning(f"Некорректный IPC класс: {ipc}")
    
    def _is_valid_ipc(self, ipc: str) -> bool:
        """
        Проверить корректность IPC класса.
        
        IPC формат: [A-H][0-9]{2}[A-Z][0-9]{1,4}/[0-9]{2,4}
        """
        if not ipc or len(ipc) < 4:
            return False
        
        # Простая проверка формата
        section = ipc[0]
        if section not in "ABCDEFGH":
            return False
        
        return True


class DataQualityReport:
    """Отчёт о качестве данных."""
    
    def __init__(self):
        self.paper_validator = PaperValidator()
        self.patent_validator = PatentValidator()
    
    def validate_papers(self, papers: list[dict]) -> dict:
        """
        Валидировать список статей.
        
        Args:
            papers: Список статей
            
        Returns:
            Dict с отчётом о валидации
        """
        if not papers:
            return {
                "total": 0,
                "valid": 0,
                "invalid": 0,
                "avg_quality_score": 0,
                "errors": [],
                "warnings": [],
            }
        
        total = len(papers)
        valid = 0
        invalid = 0
        total_quality = 0
        all_errors = []
        all_warnings = []
        
        for paper in papers:
            result = self.paper_validator.validate(paper)
            
            if result.is_valid:
                valid += 1
            else:
                invalid += 1
            
            total_quality += result.quality_score
            all_errors.extend([(paper.get("title", "Unknown"), e) for e in result.errors])
            all_warnings.extend([(paper.get("title", "Unknown"), w) for w in result.warnings])
        
        return {
            "total": total,
            "valid": valid,
            "invalid": invalid,
            "valid_percent": round((valid / total) * 100, 2) if total > 0 else 0,
            "avg_quality_score": round(total_quality / total, 2) if total > 0 else 0,
            "errors_count": len(all_errors),
            "warnings_count": len(all_warnings),
            "sample_errors": all_errors[:10],
            "sample_warnings": all_warnings[:10],
        }
    
    def validate_patents(self, patents: list[dict]) -> dict:
        """
        Валидировать список патентов.
        
        Args:
            patents: Список патентов
            
        Returns:
            Dict с отчётом о валидации
        """
        if not patents:
            return {
                "total": 0,
                "valid": 0,
                "invalid": 0,
                "avg_quality_score": 0,
                "errors": [],
                "warnings": [],
            }
        
        total = len(patents)
        valid = 0
        invalid = 0
        total_quality = 0
        all_errors = []
        all_warnings = []
        
        for patent in patents:
            result = self.patent_validator.validate(patent)
            
            if result.is_valid:
                valid += 1
            else:
                invalid += 1
            
            total_quality += result.quality_score
            all_errors.extend([(patent.get("title", "Unknown"), e) for e in result.errors])
            all_warnings.extend([(patent.get("title", "Unknown"), w) for w in result.warnings])
        
        return {
            "total": total,
            "valid": valid,
            "invalid": invalid,
            "valid_percent": round((valid / total) * 100, 2) if total > 0 else 0,
            "avg_quality_score": round(total_quality / total, 2) if total > 0 else 0,
            "errors_count": len(all_errors),
            "warnings_count": len(all_warnings),
            "sample_errors": all_errors[:10],
            "sample_warnings": all_warnings[:10],
        }


def validate_paper(paper: dict) -> ValidationResult:
    """Валидировать статью."""
    validator = PaperValidator()
    return validator.validate(paper)


def validate_patent(patent: dict) -> ValidationResult:
    """Валидировать патент."""
    validator = PatentValidator()
    return validator.validate(patent)


def check_duplicates(items: list[dict], key_field: str = "doi") -> list[tuple[int, int]]:
    """
    Проверить на дубликаты.
    
    Args:
        items: Список элементов
        key_field: Поле для проверки
        
    Returns:
        Список кортежей с индексами дубликатов
    """
    duplicates = []
    seen = {}
    
    for idx, item in enumerate(items):
        key_value = item.get(key_field)
        
        if key_value:
            if key_value in seen:
                duplicates.append((seen[key_value], idx))
            else:
                seen[key_value] = idx
    
    return duplicates


if __name__ == "__main__":
    # Пример использования
    sample_paper = {
        "title": "Test Paper",
        "authors": ["Author A"],
        "publication_date": "2024-01-15",
        "journal": "Materials Science",
        "doi": "10.1234/test",
        "abstract": "Test abstract",
    }
    
    result = validate_paper(sample_paper)
    print(f"Valid: {result.is_valid}")
    print(f"Quality Score: {result.quality_score}")
    print(f"Errors: {result.errors}")
    print(f"Warnings: {result.warnings}")
