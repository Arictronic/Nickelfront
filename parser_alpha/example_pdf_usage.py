"""Пример использования модуля обработки PDF."""

import asyncio
from pathlib import Path
from parsers_pkg.pdf_processor import pdf_processor
from shared.schemas.paper import Paper


def example_basic_extraction():
    """Базовый пример извлечения текста из PDF."""
    print("=== Пример 1: Базовое извлечение текста ===\n")
    
    # Путь к PDF файлу
    pdf_path = "example_paper.pdf"
    
    # Извлечение текста
    text = pdf_processor.extract_text_from_pdf(pdf_path)
    
    if text:
        print(f"Извлечено {len(text)} символов")
        print(f"Первые 200 символов:\n{text[:200]}...\n")
    else:
        print("Не удалось извлечь текст из PDF\n")


def example_full_processing():
    """Полный пример обработки PDF с метаданными."""
    print("=== Пример 2: Полная обработка PDF ===\n")
    
    # Метаданные статьи
    metadata = {
        "title": "Nickel-based superalloys for turbine blades",
        "authors": ["Smith J.", "Johnson A."],
        "publication_date": "2024-01-15",
    }
    
    # Полная обработка
    result = pdf_processor.process_paper_pdf(
        pdf_path="example_paper.pdf",
        metadata=metadata,
        create_translation=True
    )
    
    # Вывод результатов
    if result["full_text"]:
        print(f"✓ Текст извлечен: {len(result['full_text'])} символов")
    
    if result["summary_ru"]:
        print(f"\nКраткая выжимка:\n{result['summary_ru']}\n")
    
    if result["analysis_ru"]:
        print(f"Анализ:\n{result['analysis_ru']}\n")
    
    if result["translation_ru"]:
        print(f"Перевод:\n{result['translation_ru']}\n")


def example_with_paper_object():
    """Пример обогащения объекта Paper данными из PDF."""
    print("=== Пример 3: Обогащение объекта Paper ===\n")
    
    # Создаем объект Paper (обычно получается из парсера)
    paper = Paper(
        title="Example Paper on Nickel Alloys",
        authors=["Author 1", "Author 2"],
        source="arXiv",
        publication_date="2024-01-01",
    )
    
    print(f"До обработки PDF:")
    print(f"  - full_text: {paper.full_text}")
    print(f"  - summary_ru: {paper.summary_ru}")
    print(f"  - analysis_ru: {paper.analysis_ru}\n")
    
    # Обработка PDF
    pdf_result = pdf_processor.process_paper_pdf(
        pdf_path="example_paper.pdf",
        metadata={
            "title": paper.title,
            "authors": paper.authors,
            "publication_date": paper.publication_date,
        }
    )
    
    # Обновление объекта Paper
    paper.full_text = pdf_result["full_text"]
    paper.summary_ru = pdf_result["summary_ru"]
    paper.analysis_ru = pdf_result["analysis_ru"]
    paper.translation_ru = pdf_result["translation_ru"]
    paper.processing_status = "completed" if pdf_result["full_text"] else "failed"
    
    print(f"После обработки PDF:")
    print(f"  - full_text: {'Да' if paper.full_text else 'Нет'}")
    print(f"  - summary_ru: {'Да' if paper.summary_ru else 'Нет'}")
    print(f"  - analysis_ru: {'Да' if paper.analysis_ru else 'Нет'}")
    print(f"  - processing_status: {paper.processing_status}\n")


def example_batch_processing():
    """Пример пакетной обработки нескольких PDF."""
    print("=== Пример 4: Пакетная обработка ===\n")
    
    pdf_dir = Path("downloads/pdfs")
    
    # Проверяем существование директории
    if not pdf_dir.exists():
        print(f"Директория {pdf_dir} не существует")
        print("Создайте директорию и поместите туда PDF файлы\n")
        return
    
    # Обработка всех PDF в директории
    pdf_files = list(pdf_dir.glob("*.pdf"))
    print(f"Найдено {len(pdf_files)} PDF файлов\n")
    
    for pdf_file in pdf_files:
        print(f"Обработка: {pdf_file.name}")
        
        result = pdf_processor.process_paper_pdf(
            pdf_path=pdf_file,
            metadata={"title": pdf_file.stem}
        )
        
        if result["full_text"]:
            # Сохранение результата
            output_file = pdf_dir / f"{pdf_file.stem}_processed.txt"
            output_file.write_text(result["full_text"], encoding="utf-8")
            print(f"  ✓ Сохранено в {output_file.name}")
        else:
            print(f"  ✗ Ошибка извлечения текста")
        print()


if __name__ == "__main__":
    print("=" * 60)
    print("ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ МОДУЛЯ ОБРАБОТКИ PDF")
    print("=" * 60)
    print()
    
    # Запуск примеров
    # Раскомментируйте нужный пример:
    
    # example_basic_extraction()
    # example_full_processing()
    # example_with_paper_object()
    # example_batch_processing()
    
    print("\nДля запуска примеров:")
    print("1. Раскомментируйте нужную функцию в main")
    print("2. Убедитесь, что файл example_paper.pdf существует")
    print("3. Установите зависимости: pip install PyPDF2 pdfplumber")
    print("4. Запустите: python example_pdf_usage.py")