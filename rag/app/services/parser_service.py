"""
Модуль парсинга документов.

Предоставляет функции для извлечения текста из PDF-файлов
и заготовку для веб-парсинга патентных баз данных через Selenium.
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pdfplumber
from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter

from app.config import settings

logger = logging.getLogger(__name__)


class PDFParser:
    """
    Парсер для извлечения текста и таблиц из PDF-файлов.

    Использует библиотеку pdfplumber для извлечения текста с сохранением
    структуры документа. Поддерживает извлечение простых таблиц и
    обработку многостраничных документов.
    """

    def __init__(
        self,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ):
        """
        Инициализация PDF парсера.

        Args:
            chunk_size: Размер чанка для разбиения текста. По умолчанию из настроек.
            chunk_overlap: Перекрытие между чанками. По умолчанию из настроек.
        """
        self.chunk_size = chunk_size or settings.max_chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap

        self._text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

        logger.info(
            f"Инициализация PDFParser: chunk_size={self.chunk_size}, "
            f"chunk_overlap={self.chunk_overlap}"
        )

    def extract_text_from_file(self, file_path: str) -> str:
        """
        Извлекает текст из PDF файла.

        Args:
            file_path: Путь к PDF файлу.

        Returns:
            str: Извлечённый текст документа.

        Raises:
            FileNotFoundError: Если файл не найден.
            RuntimeError: Если произошла ошибка при чтении файла.

        Example:
            >>> parser = PDFParser()
            >>> text = parser.extract_text_from_file("patent.pdf")
        """
        file_path = Path(file_path)

        if not file_path.exists():
            logger.error(f"Файл не найден: {file_path}")
            raise FileNotFoundError(f"Файл не найден: {file_path}")

        logger.info(f"Извлечение текста из файла: {file_path.name}")

        try:
            text_parts = []

            with pdfplumber.open(file_path) as pdf:
                logger.debug(f"Всего страниц в PDF: {len(pdf.pages)}")

                for page_num, page in enumerate(pdf.pages, 1):
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        text_parts.append(f"[Страница {page_num}]\n{page_text}")

                    # Попытка извлечь таблицы со страницы
                    tables = page.extract_tables()
                    if tables:
                        table_text = self._format_tables(tables, page_num)
                        if table_text:
                            text_parts.append(table_text)

            full_text = "\n\n".join(text_parts)
            logger.info(f"Извлечено {len(full_text)} символов")

            return full_text

        except Exception as e:
            logger.error(f"Ошибка при извлечении текста из PDF: {e}")
            raise RuntimeError(f"Не удалось извлечь текст из PDF: {e}")

    def _format_tables(
        self,
        tables: List[List[List[Optional[str]]]],
        page_num: int,
    ) -> str:
        """
        Форматирует извлечённые таблицы в текстовый вид.

        Args:
            tables: Список таблиц (список строк, каждая строка — список ячеек).
            page_num: Номер страницы для метаданных.

        Returns:
            str: Отформатированный текст таблиц.
        """
        formatted_parts = []
        formatted_parts.append(f"\n[Таблицы со страницы {page_num}]")

        for table_idx, table in enumerate(tables, 1):
            if not table:
                continue

            formatted_parts.append(f"\n[Таблица {table_idx}]")

            for row_idx, row in enumerate(table):
                # Очистка ячеек от None и лишних пробелов
                cleaned_row = [
                    str(cell).strip() if cell is not None else ""
                    for cell in row
                ]

                # Форматирование строки таблицы
                if cleaned_row:
                    row_text = " | ".join(cleaned_row)
                    formatted_parts.append(f"Строка {row_idx + 1}: {row_text}")

        return "\n".join(formatted_parts)

    def extract_text_from_bytes(self, file_bytes: bytes) -> str:
        """
        Извлекает текст из PDF данных в памяти.

        Args:
            file_bytes: Байты PDF файла.

        Returns:
            str: Извлечённый текст документа.

        Raises:
            RuntimeError: Если произошла ошибка при чтении данных.
        """
        logger.info("Извлечение текста из PDF данных (bytes)")

        try:
            with tempfile.NamedTemporaryFile(
                suffix=".pdf",
                delete=False,
            ) as tmp_file:
                tmp_file.write(file_bytes)
                tmp_path = tmp_file.name

            try:
                text = self.extract_text_from_file(tmp_path)
            finally:
                os.unlink(tmp_path)

            return text

        except Exception as e:
            logger.error(f"Ошибка при извлечении текста из bytes: {e}")
            raise RuntimeError(f"Не удалось извлечь текст из PDF данных: {e}")

    def parse_to_documents(
        self,
        file_path: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """
        Парсит PDF файл и возвращает список документов LangChain.

        Разбивает извлечённый текст на чанки и создаёт документы
        с метаданными для каждого чанка.

        Args:
            file_path: Путь к PDF файлу.
            metadata: Дополнительные метаданные для документов.

        Returns:
            List[Document]: Список документов LangChain.

        Example:
            >>> parser = PDFParser()
            >>> docs = parser.parse_to_documents("patent.pdf", {"source": "patents.db"})
        """
        logger.info(f"Парсинг PDF в документы: {file_path}")

        # Извлечение текста
        full_text = self.extract_text_from_file(file_path)

        if not full_text.strip():
            logger.warning("PDF файл не содержит текста")
            return []

        # Разбиение на чанки
        chunks = self._text_splitter.split_text(full_text)
        logger.info(f"Текст разбит на {len(chunks)} чанков")

        # Базовые метаданные
        base_metadata = {
            "source": Path(file_path).name,
            "file_path": str(Path(file_path).absolute()),
            "type": "patent_pdf",
        }
        if metadata:
            base_metadata.update(metadata)

        # Создание документов
        documents = []
        for i, chunk in enumerate(chunks):
            doc_metadata = base_metadata.copy()
            doc_metadata["chunk_index"] = i
            doc_metadata["total_chunks"] = len(chunks)

            doc = Document(
                page_content=chunk,
                metadata=doc_metadata,
            )
            documents.append(doc)

        logger.info(f"Создано {len(documents)} документов")
        return documents

    def parse_bytes_to_documents(
        self,
        file_bytes: bytes,
        filename: str = "unknown.pdf",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """
        Парсит PDF данные и возвращает список документов LangChain.

        Args:
            file_bytes: Байты PDF файла.
            filename: Имя файла для метаданных.
            metadata: Дополнительные метаданные.

        Returns:
            List[Document]: Список документов LangChain.
        """
        logger.info(f"Парсинг PDF данных в документы: {filename}")

        try:
            with tempfile.NamedTemporaryFile(
                suffix=".pdf",
                delete=False,
            ) as tmp_file:
                tmp_file.write(file_bytes)
                tmp_path = tmp_file.name

            try:
                docs = self.parse_to_documents(
                    tmp_path,
                    metadata=metadata,
                )
                # Обновление метаданных с правильным именем файла
                for doc in docs:
                    doc.metadata["source"] = filename
            finally:
                os.unlink(tmp_path)

            return docs

        except Exception as e:
            logger.error(f"Ошибка при парсинге PDF данных: {e}")
            return []


class WebScraper:
    """
    Заготовка для веб-парсинга патентных баз данных.

    Предоставляет инфраструктуру для будущего парсинга сайтов
    с патентами через Selenium с использованием Chromium.

    Note:
        Данный класс является скелетом для будущей реализации.
        Для активации функциональности необходимо настроить
        WebDriver и указать целевые URL патентных баз.
    """

    def __init__(self, headless: bool = True):
        """
        Инициализация веб-скрапера.

        Args:
            headless: Запускать ли браузер в безголовом режиме.
        """
        self.headless = headless
        self._driver = None

        logger.info(f"Инициализация WebScraper (headless={headless})")

    def _init_driver(self):
        """
        Инициализирует WebDriver для Chromium.

        Note:
            Требует установки webdriver-manager и наличия Chrome/Chromium.
        """
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.options import Options

            logger.debug("Инициализация WebDriver для Chromium")

            options = Options()
            if self.headless:
                options.add_argument("--headless=new")

            # Оптимизация для экономии памяти
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-infobars")

            service = Service(ChromeDriverManager().install())
            self._driver = webdriver.Chrome(service=service, options=options)

            logger.info("WebDriver успешно инициализирован")

        except ImportError as e:
            logger.error(f"Необходимые библиотеки Selenium не установлены: {e}")
            raise RuntimeError(
                "Для веб-парсинга установите: pip install selenium webdriver-manager"
            )
        except Exception as e:
            logger.error(f"Ошибка при инициализации WebDriver: {e}")
            raise RuntimeError(f"Не удалось инициализировать WebDriver: {e}")

    def scrape_page(self, url: str) -> Optional[str]:
        """
        Загружает и извлекает текст с веб-страницы.

        Args:
            url: URL целевой страницы.

        Returns:
            Optional[str]: Извлечённый текст страницы или None при ошибке.

        Example:
            >>> scraper = WebScraper()
            >>> text = scraper.scrape_page("https://patents.google.com/...")
        """
        logger.info(f"Загрузка страницы: {url}")

        try:
            if self._driver is None:
                self._init_driver()

            self._driver.get(url)

            # Ожидание загрузки контента (можно расширить)
            self._driver.implicitly_wait(5)

            # Извлечение текста
            text = self._driver.find_element("tag name", "body").text

            logger.info(f"Извлечено {len(text)} символов со страницы")
            return text

        except Exception as e:
            logger.error(f"Ошибка при загрузке страницы {url}: {e}")
            return None

    def scrape_patent(
        self,
        url: str,
        patent_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Заготовка для парсинга страницы патента.

        Args:
            url: URL страницы патента.
            patent_id: Идентификатор патента (опционально).

        Returns:
            Optional[Dict[str, Any]]: Словарь с данными патента или None.

        Note:
            Метод является заготовкой. Требуется реализация под конкретную
            патентную базу данных (Google Patents, Espacenet, FIIPS и т.д.).
        """
        logger.info(f"Парсинг патента: {url}")

        # TODO: Реализовать парсинг под конкретную патентную базу
        # Пример структуры возвращаемых данных:
        # {
        #     "patent_id": "...",
        #     "title": "...",
        #     "abstract": "...",
        #     "claims": [...],
        #     "description": "...",
        #     "inventors": [...],
        #     "filing_date": "...",
        #     "pdf_url": "...",
        # }

        text = self.scrape_page(url)
        if text:
            return {
                "patent_id": patent_id or "unknown",
                "url": url,
                "raw_text": text,
                "parsed": False,  # Требуется реализация парсера
            }

        return None

    def close(self):
        """Закрывает WebDriver и освобождает ресурсы."""
        if self._driver is not None:
            logger.debug("Закрытие WebDriver")
            self._driver.quit()
            self._driver = None

    def __enter__(self):
        """Контекстный менеджер: вход."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Контекстный менеджер: выход."""
        self.close()


# Глобальный экземпляр PDF парсера
pdf_parser = PDFParser()
