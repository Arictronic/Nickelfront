"""
Модуль работы с векторной базой данных ChromaDB.

Предоставляет функции для инициализации хранилища, добавления документов,
поиска похожих документов и управления коллекцией патентов.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain.schema import Document
from langchain_community.vectorstores import Chroma

from app.config import settings
from app.core.embeddings import get_embeddings_model

logger = logging.getLogger(__name__)


class VectorStoreManager:
    """
    Менеджер векторного хранилища для работы с ChromaDB.

    Управляет жизненным циклом векторной базы данных: инициализация,
    добавление документов, поиск и получение статистики.
    Все данные сохраняются на диск для постоянного хранения.
    """

    def __init__(self, persist_directory: Optional[str] = None):
        """
        Инициализация менеджера векторного хранилища.

        Args:
            persist_directory: Путь к директории для постоянного хранения.
                Если не указан, используется путь из настроек.
        """
        self.persist_directory = persist_directory or str(settings.db_dir)
        self._vector_store: Optional[Chroma] = None
        self._client: Optional[chromadb.Client] = None
        self._collection_name = "patents_collection"

        logger.info(f"Инициализация VectorStoreManager с путем: {self.persist_directory}")

    def _init_client(self) -> chromadb.Client:
        """
        Создаёт и возвращает клиент ChromaDB с настройками постоянного хранения.

        Returns:
            chromadb.Client: Инициализированный клиент ChromaDB.
        """
        if self._client is None:
            logger.debug("Создание нового клиента ChromaDB")
            self._client = chromadb.Client(
                ChromaSettings(
                    persist_directory=self.persist_directory,
                    is_persistent=True,
                    anonymized_telemetry=False,
                )
            )
        return self._client

    def _get_or_create_collection(self, client: chromadb.Client) -> chromadb.api.models.Collection.Collection:
        """
        Получает или создаёт коллекцию для хранения патентов.

        Args:
            client: Клиент ChromaDB для работы с коллекциями.

        Returns:
            Collection: Коллекция для хранения векторных представлений патентов.
        """
        logger.debug(f"Получение или создание коллекции: {self._collection_name}")
        return client.get_or_create_collection(
            name=self._collection_name,
            metadata={"description": "Коллекция патентов на суперсплавы"},
        )

    def get_vector_store(self) -> Chroma:
        """
        Возвращает инициализированное векторное хранилище LangChain.

        Создаёт хранилище при первом вызове и кэширует для последующих
        обращений. Использует модель эмбеддингов из настроек.

        Returns:
            Chroma: Инициализированное векторное хранилище.

        Note:
            Функция лениво инициализирует хранилище при первом вызове.
        """
        if self._vector_store is None:
            logger.info("Инициализация векторного хранилища LangChain")

            embeddings = get_embeddings_model()
            client = self._init_client()
            collection = self._get_or_create_collection(client)

            self._vector_store = Chroma(
                client=client,
                collection_name=self._collection_name,
                embedding_function=embeddings,
                persist_directory=self.persist_directory,
            )

            logger.info("Векторное хранилище успешно инициализировано")

        return self._vector_store

    def add_documents(
        self,
        documents: List[Document],
        batch_size: int = 32,
    ) -> List[str]:
        """
        Добавляет документы в векторное хранилище.

        Разбивает документы на пакеты для экономии памяти и добавляет
        в векторную базу с генерацией уникальных идентификаторов.

        Args:
            documents: Список документов LangChain для добавления.
            batch_size: Размер пакета для добавления (оптимизация памяти).

        Returns:
            List[str]: Список идентификаторов добавленных документов.

        Raises:
            ValueError: Если список документов пуст.
            RuntimeError: Если произошла ошибка при добавлении документов.

        Example:
            >>> from langchain.schema import Document
            >>> docs = [Document(page_content="Текст патента", metadata={"source": "patent.pdf"})]
            >>> ids = vector_store.add_documents(docs)
        """
        if not documents:
            logger.warning("Попытка добавить пустой список документов")
            return []

        vector_store = self.get_vector_store()
        total_docs = len(documents)
        added_ids: List[str] = []

        logger.info(f"Добавление {total_docs} документов в векторное хранилище")

        try:
            # Добавление документами для экономии памяти
            for i in range(0, total_docs, batch_size):
                batch = documents[i : i + batch_size]
                batch_ids = [str(uuid.uuid4()) for _ in batch]

                vector_store.add_documents(documents=batch, ids=batch_ids)
                added_ids.extend(batch_ids)

                logger.debug(f"Добавлен пакет документов {i // batch_size + 1}")

            logger.info(f"Успешно добавлено {len(added_ids)} документов")
            return added_ids

        except Exception as e:
            logger.error(f"Ошибка при добавлении документов: {e}")
            raise RuntimeError(f"Не удалось добавить документы в хранилище: {e}")

    def similarity_search(
        self,
        query: str,
        k: Optional[int] = None,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """
        Выполняет поиск похожих документов по запросу.

        Осуществляет семантический поиск документов в векторной базе
        на основе схожести эмбеддингов запроса и документов.

        Args:
            query: Текст поискового запроса.
            k: Количество документов для возврата. По умолчанию из настроек.
            filter_metadata: Опциональный фильтр по метаданным.

        Returns:
            List[Document]: Список найденных документов, отсортированных
                по релевантности.

        Note:
            Если база данных пуста, возвращается пустой список.

        Example:
            >>> results = vector_store.similarity_search("состав суперсплава", k=3)
            >>> for doc in results:
            ...     print(doc.page_content[:100])
        """
        k = k or settings.search_k
        vector_store = self.get_vector_store()

        # Проверка на пустую базу
        try:
            client = self._init_client()
            collection = self._get_or_create_collection(client)
            count = collection.count()
            if count == 0:
                logger.warning("Векторная база данных пуста")
                return []
        except Exception as e:
            logger.warning(f"Не удалось проверить размер базы: {e}")
            return []

        logger.debug(f"Поиск {k} документов по запросу: {query[:50]}...")

        try:
            where_filter = None
            if filter_metadata:
                where_filter = {
                    k: {"$eq": v} for k, v in filter_metadata.items()
                }

            documents = vector_store.similarity_search(
                query=query,
                k=k,
                filter=where_filter,
            )

            logger.debug(f"Найдено {len(documents)} документов")
            return documents

        except Exception as e:
            logger.error(f"Ошибка при поиске документов: {e}")
            return []

    def similarity_search_with_score(
        self,
        query: str,
        k: Optional[int] = None,
    ) -> List[Tuple[Document, float]]:
        """
        Выполняет поиск похожих документов с оценкой релевантности.

        Args:
            query: Текст поискового запроса.
            k: Количество документов для возврата.

        Returns:
            List[Tuple[Document, float]]: Список кортежей (документ, оценка).
                Оценка — расстояние косинусной схожести (меньше = лучше).
        """
        k = k or settings.search_k
        vector_store = self.get_vector_store()

        try:
            client = self._init_client()
            collection = self._get_or_create_collection(client)
            if collection.count() == 0:
                return []
        except Exception:
            return []

        logger.debug(f"Поиск с оценкой для запроса: {query[:50]}...")

        try:
            results = vector_store.similarity_search_with_score(query=query, k=k)
            logger.debug(f"Найдено {len(results)} документов с оценками")
            return results
        except Exception as e:
            logger.error(f"Ошибка при поиске с оценкой: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """
        Возвращает статистику векторного хранилища.

        Returns:
            Dict[str, Any]: Словарь со статистикой:
                - total_documents: Общее количество документов
                - collection_name: Название коллекции
                - persist_directory: Путь к хранилищу

        Example:
            >>> stats = vector_store.get_stats()
            >>> print(f"Документов в базе: {stats['total_documents']}")
        """
        try:
            client = self._init_client()
            collection = self._get_or_create_collection(client)
            count = collection.count()
        except Exception as e:
            logger.warning(f"Не удалось получить статистику: {e}")
            count = 0

        return {
            "total_documents": count,
            "collection_name": self._collection_name,
            "persist_directory": self.persist_directory,
        }

    def clear(self) -> bool:
        """
        Очищает векторное хранилище (удаляет все документы).

        Returns:
            bool: True если очистка успешна, False в случае ошибки.

        Warning:
            Эта операция необратима! Все документы будут удалены.
        """
        logger.warning("Очистка векторного хранилища")

        try:
            if self._vector_store is not None:
                client = self._init_client()
                collection = self._get_or_create_collection(client)
                collection.delete(where={})
                self._vector_store = None
                logger.info("Векторное хранилище очищено")
                return True
        except Exception as e:
            logger.error(f"Ошибка при очистке хранилища: {e}")

        return False


# Глобальный экземпляр менеджера векторного хранилища
vector_store_manager = VectorStoreManager()
