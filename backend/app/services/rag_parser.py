"""
Сервис парсинга документов для RAG.

Предоставляет функции для извлечения текста из PDF-файлов
и разбиения на чанки для векторизации.
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

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
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        """
        Инициализация PDF парсера.

        Args:
            chunk_size: Размер чанка для разбиения текста.
            chunk_overlap: Перекрытие между чанками.
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

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
        """
        import pdfplumber

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
        tables: list[list[list[str | None]]],
        page_num: int,
    ) -> str:
        """
        Форматирует извлечённые таблицы в текстовый вид.

        Args:
            tables: Список таблиц.
            page_num: Номер страницы.

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
                cleaned_row = [
                    str(cell).strip() if cell is not None else ""
                    for cell in row
                ]

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
        metadata: dict[str, Any] | None = None,
    ) -> list[Document]:
        """
        Парсит PDF файл и возвращает список документов LangChain.

        Разбивает извлечённый текст на чанки и создаёт документы
        с метаданными для каждого чанка.

        Args:
            file_path: Путь к PDF файлу.
            metadata: Дополнительные метаданные для документов.

        Returns:
            List[Document]: Список документов LangChain.
        """
        logger.info(f"Парсинг PDF в документы: {file_path}")

        full_text = self.extract_text_from_file(file_path)

        if not full_text.strip():
            logger.warning("PDF файл не содержит текста")
            return []

        chunks = self._text_splitter.split_text(full_text)
        logger.info(f"Текст разбит на {len(chunks)} чанков")

        base_metadata = {
            "source": Path(file_path).name,
            "file_path": str(Path(file_path).absolute()),
            "type": "patent_pdf",
        }
        if metadata:
            base_metadata.update(metadata)

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
        metadata: dict[str, Any] | None = None,
    ) -> list[Document]:
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
                for doc in docs:
                    doc.metadata["source"] = filename
            finally:
                os.unlink(tmp_path)

            return docs

        except Exception as e:
            logger.error(f"Ошибка при парсинге PDF данных: {e}")
            return []


# Глобальный экземпляр PDF парсера
pdf_parser = PDFParser(
    chunk_size=1000,
    chunk_overlap=200,
)
