"""
RAG Vector Store — векторное хранилище для RAG.

Использует ChromaDB через LangChain для хранения и поиска документов.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_community.vectorstores import Chroma

from app.core.config import settings
from app.services.embedding_service import get_embedding_service

logger = logging.getLogger(__name__)


class RAGVectorStore:
    """
    Менеджер векторного хранилища для RAG.

    Управляет жизненным циклом векторной базы данных:
    - Инициализация
    - Добавление документов
    - Поиск
    - Очистка
    """

    def __init__(self, persist_directory: Optional[str] = None):
        """
        Инициализация менеджера векторного хранилища.

        Args:
            persist_directory: Путь к директории для постоянного хранения.
        """
        self.persist_directory = persist_directory or str(
            Path(settings.CHROMA_DB_PATH) / "rag"
        )
        self._vector_store: Optional[Chroma] = None
        self._client: Optional[chromadb.Client] = None
        self._collection_name = "rag_documents"

        logger.info(f"Инициализация RAGVectorStore: {self.persist_directory}")

    def _init_client(self) -> chromadb.Client:
        """Создать клиент ChromaDB."""
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

    def _get_or_create_collection(self, client: chromadb.Client):
        """Получить или создать коллекцию."""
        logger.debug(f"Получение или создание коллекции: {self._collection_name}")
        return client.get_or_create_collection(
            name=self._collection_name,
            metadata={"description": "Документы для RAG"},
        )

    def get_vector_store(self) -> Optional[Chroma]:
        """Возвращает инициализированное векторное хранилище."""
        if self._vector_store is None:
            logger.info("Инициализация векторного хранилища LangChain")

            embedding_service = get_embedding_service()
            if not embedding_service.model:
                logger.error("Модель эмбеддингов недоступна")
                return None

            client = self._init_client()
            collection = self._get_or_create_collection(client)

            # Обёртка эмбеддингов для LangChain
            from langchain.embeddings.base import Embeddings

            class SentenceTransformerEmbeddings(Embeddings):
                def __init__(self, model):
                    self.model = model

                def embed_documents(self, texts: List[str]) -> List[List[float]]:
                    embeddings = self.model.encode(
                        texts,
                        convert_to_numpy=True,
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    )
                    return embeddings.tolist()

                def embed_query(self, text: str) -> List[float]:
                    embedding = self.model.encode(
                        text,
                        convert_to_numpy=True,
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    )
                    return embedding.tolist()

            embeddings = SentenceTransformerEmbeddings(embedding_service.model)

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
        documents: List[Any],  # LangChain Document
        batch_size: int = 32,
    ) -> List[str]:
        """
        Добавить документы в векторное хранилище.

        Args:
            documents: Список документов LangChain.
            batch_size: Размер пакета.

        Returns:
            List[str]: ID добавленных документов.
        """
        if not documents:
            logger.warning("Попытка добавить пустой список документов")
            return []

        vector_store = self.get_vector_store()
        if vector_store is None:
            logger.error("Векторное хранилище не инициализировано")
            return []

        total_docs = len(documents)
        added_ids: List[str] = []

        logger.info(f"Добавление {total_docs} документов в векторное хранилище")

        try:
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
            return []

    def similarity_search(
        self,
        query: str,
        k: int = 4,
    ) -> List[Any]:
        """
        Поиск похожих документов.

        Args:
            query: Текст запроса.
            k: Количество документов.

        Returns:
            List[Document]: Найденные документы.
        """
        vector_store = self.get_vector_store()
        if vector_store is None:
            return []

        try:
            documents = vector_store.similarity_search(query=query, k=k)
            logger.debug(f"Найдено {len(documents)} документов")
            return documents
        except Exception as e:
            logger.error(f"Ошибка при поиске документов: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику хранилища."""
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
        Очистить векторное хранилище.

        Returns:
            bool: True если успешно.
        """
        logger.warning("Очистка векторного хранилища RAG")

        try:
            if self._vector_store is not None:
                client = self._init_client()
                collection = self._get_or_create_collection(client)
                collection.delete(where={})
                self._vector_store = None
                logger.info("Векторное хранилище RAG очищено")
                return True
        except Exception as e:
            logger.error(f"Ошибка при очистке хранилища: {e}")

        return False


# Глобальный экземпляр
from pathlib import Path

_rag_vector_store: Optional[RAGVectorStore] = None


def get_rag_vector_store() -> RAGVectorStore:
    """Получить экземпляр RAGVectorStore (singleton)."""
    global _rag_vector_store
    if _rag_vector_store is None:
        _rag_vector_store = RAGVectorStore()
    return _rag_vector_store
