"""
Сервис векторного поиска с использованием ChromaDB.

Предоставляет функции для инициализации хранилища, добавления документов,
поиска похожих документов и управления коллекцией статей.
Включает пакетные операции и расширенную статистику.
"""

import os
from dataclasses import dataclass
from typing import Any

from loguru import logger

from app.core.config import settings

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    chromadb = None


@dataclass
class VectorSearchResult:
    """Результат векторного поиска."""
    paper_id: int
    title: str
    source: str
    doi: str | None
    similarity: float
    metadata: dict


class ChromaVectorService:
    """
    Сервис для векторного поиска с использованием ChromaDB.

    ChromaDB - векторная база данных для хранения и поиска эмбеддингов.
    Поддерживает фильтрацию по метаданным и косинусное сходство.

    Особенности:
    - Пакетное добавление документов (batch_size=32)
    - Поиск с оценками релевантности
    - Расширенная статистика
    - Очистка индекса
    - Перестройка индекса
    """

    COLLECTION_NAME = "papers"
    DEFAULT_BATCH_SIZE = 32

    def __init__(self, persist_directory: str | None = None):
        """
        Инициализация сервиса векторного поиска.

        Args:
            persist_directory: Путь к директории для постоянного хранения.
                Если не указан, используется путь из настроек.
        """
        self._client = None
        self._collection = None
        self._persist_directory = persist_directory or settings.resolve_path(
            settings.CHROMA_DB_PATH
        )

        logger.info(f"Инициализация ChromaVectorService: {self._persist_directory}")

    @property
    def client(self):
        """Ленивая инициализация клиента ChromaDB."""
        if not CHROMADB_AVAILABLE:
            logger.warning("ChromaDB не установлен. Векторный поиск недоступен.")
            return None

        if self._client is None:
            try:
                # Создаем директорию для персистентного хранения
                os.makedirs(self._persist_directory, exist_ok=True)

                # Инициализируем персистентный клиент
                self._client = chromadb.PersistentClient(
                    path=self._persist_directory,
                    settings=ChromaSettings(
                        anonymized_telemetry=False,
                        allow_reset=True,
                    )
                )
                logger.info(f"ChromaDB инициализирован: {self._persist_directory}")
            except Exception as e:
                logger.error(f"Ошибка инициализации ChromaDB: {e}")
                return None

        return self._client

    @property
    def collection(self):
        """Получить коллекцию для статей."""
        if not self.client:
            return None

        if self._collection is None:
            try:
                # Получаем или создаем коллекцию
                self._collection = self.client.get_or_create_collection(
                    name=self.COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},  # Косинусное сходство
                )
                logger.info(f"Коллекция {self.COLLECTION_NAME} готова")
            except Exception as e:
                logger.error(f"Ошибка создания коллекции: {e}")
                return None

        return self._collection

    def add_paper(
        self,
        paper_id: int,
        embedding: list[float],
        title: str,
        source: str,
        doi: str | None = None,
        publication_date: str | None = None,
        journal: str | None = None,
    ) -> bool:
        """
        Добавить статью в векторную базу.

        Args:
            paper_id: ID статьи в БД
            embedding: Векторный эмбеддинг
            title: Заголовок статьи
            source: Источник (CORE, arXiv)
            doi: DOI статьи
            publication_date: Дата публикации
            journal: Журнал

        Returns:
            True если успешно
        """
        if not self.collection:
            return False

        if not embedding:
            logger.warning(f"Пустой эмбеддинг для статьи {paper_id}")
            return False

        try:
            # Формируем метаданные для фильтрации
            metadata = {
                "paper_id": paper_id,
                "title": title[:500],  # Ограничение длины
                "source": source,
            }

            if doi:
                metadata["doi"] = doi[:200]

            if publication_date:
                metadata["publication_date"] = publication_date[:20]

            if journal:
                metadata["journal"] = journal[:500]

            # Добавляем в коллекцию
            self.collection.add(
                ids=[f"paper_{paper_id}"],
                embeddings=[embedding],
                metadatas=[metadata],
                documents=[title],  # Документ для контекста
            )

            logger.debug(f"Статья {paper_id} добавлена в векторную базу")
            return True

        except Exception as e:
            logger.error(f"Ошибка добавления статьи {paper_id} в ChromaDB: {e}")
            return False

    def add_documents_batch(
        self,
        documents: list[dict[str, Any]],
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> tuple[int, int]:
        """
        Пакетное добавление документов в векторную базу.

        Args:
            documents: Список документов с полями:
                - paper_id: int
                - embedding: List[float]
                - title: str
                - source: str
                - doi: Optional[str]
                - publication_date: Optional[str]
                - journal: Optional[str]
            batch_size: Размер пакета для добавления

        Returns:
            Кортеж (успешно добавлено, ошибок)
        """
        if not self.collection:
            return 0, len(documents)

        if not documents:
            logger.warning("Попытка добавить пустой список документов")
            return 0, 0

        total_docs = len(documents)
        success_count = 0
        error_count = 0

        logger.info(f"Пакетное добавление {total_docs} документов (batch_size={batch_size})")

        try:
            # Добавление пакетами для экономии памяти
            for i in range(0, total_docs, batch_size):
                batch = documents[i : i + batch_size]
                batch_success = 0

                for doc in batch:
                    if not doc.get("embedding"):
                        error_count += 1
                        continue

                    if self.add_paper(
                        paper_id=doc["paper_id"],
                        embedding=doc["embedding"],
                        title=doc["title"],
                        source=doc["source"],
                        doi=doc.get("doi"),
                        publication_date=doc.get("publication_date"),
                        journal=doc.get("journal"),
                    ):
                        batch_success += 1
                        success_count += 1
                    else:
                        error_count += 1

                logger.debug(
                    f"Добавлен пакет {i // batch_size + 1}: "
                    f"{batch_success}/{len(batch)} успешно"
                )

            logger.info(f"Пакетное добавление завершено: {success_count} успешно, {error_count} ошибок")
            return success_count, error_count

        except Exception as e:
            logger.error(f"Ошибка при пакетном добавлении: {e}")
            return success_count, error_count + (total_docs - success_count)

    def search(
        self,
        query_embedding: list[float],
        limit: int = 10,
        source: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[VectorSearchResult]:
        """
        Векторный поиск статей по эмбеддингу запроса.

        Args:
            query_embedding: Эмбеддинг поискового запроса
            limit: Макс. количество результатов
            source: Фильтр по источнику
            date_from: Фильтр по дате (от)
            date_to: Фильтр по дате (до)

        Returns:
            Список результатов поиска
        """
        if not self.collection:
            return []

        if not query_embedding:
            return []

        try:
            # Формируем фильтр where
            where = {}
            if source:
                where["source"] = source

            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=limit * 2,  # Берем с запасом для фильтрации
                where=where if where else None,
                include=["metadatas", "distances"],
            )

            # Обрабатываем результаты
            search_results = []
            if results and results["ids"] and len(results["ids"][0]) > 0:
                for i, paper_id_str in enumerate(results["ids"][0]):
                    metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                    distance = results["distances"][0][i] if results["distances"] else 0

                    # Конвертируем дистанцию в сходство (cosine similarity)
                    # distance = 1 - similarity для косинусного расстояния
                    similarity = 1 - distance

                    # Фильтрация по дате (постобработка)
                    pub_date = metadata.get("publication_date", "")
                    if date_from and pub_date and pub_date < date_from:
                        continue
                    if date_to and pub_date and pub_date > date_to:
                        continue

                    search_results.append(
                        VectorSearchResult(
                            paper_id=metadata.get("paper_id", 0),
                            title=metadata.get("title", ""),
                            source=metadata.get("source", ""),
                            doi=metadata.get("doi"),
                            similarity=similarity,
                            metadata=metadata,
                        )
                    )

                    if len(search_results) >= limit:
                        break

            return search_results

        except Exception as e:
            logger.error(f"Ошибка векторного поиска: {e}")
            return []

    def search_with_scores(
        self,
        query_embedding: list[float],
        limit: int = 10,
    ) -> list[tuple[VectorSearchResult, float]]:
        """
        Векторный поиск с возвратом оценок релевантности.

        Args:
            query_embedding: Эмбеддинг поискового запроса
            limit: Макс. количество результатов

        Returns:
            Список кортежей (результат, оценка)
        """
        results = self.search(query_embedding, limit)
        return [(r, r.similarity) for r in results]

    def delete_paper(self, paper_id: int) -> bool:
        """
        Удалить статью из векторной базы.

        Args:
            paper_id: ID статьи

        Returns:
            True если успешно
        """
        if not self.collection:
            return False

        try:
            self.collection.delete(ids=[f"paper_{paper_id}"])
            logger.debug(f"Статья {paper_id} удалена из векторной базы")
            return True
        except Exception as e:
            logger.error(f"Ошибка удаления статьи {paper_id} из ChromaDB: {e}")
            return False

    def clear(self) -> bool:
        """
        Очищает векторное хранилище (удаляет все документы).

        Returns:
            True если очистка успешна, False в случае ошибки.

        Warning:
            Эта операция необратима! Все документы будут удалены.
        """
        logger.warning("Очистка векторного хранилища")

        if not self.client:
            return False

        try:
            if self._collection is not None:
                self.client.delete_collection(self.COLLECTION_NAME)
                self._collection = None
                logger.info("Векторное хранилище очищено")
                return True
        except Exception as e:
            logger.error(f"Ошибка при очистке хранилища: {e}")

        return False

    def rebuild_index(self, papers: list[dict[str, Any]]) -> int:
        """
        Перестроить индекс заново.

        Args:
            papers: Список статей с эмбеддингами

        Returns:
            Количество добавленных статей
        """
        if not self.client:
            return 0

        try:
            # Удаляем старую коллекцию
            try:
                self.client.delete_collection(self.COLLECTION_NAME)
            except Exception:
                pass

            # Создаем новую
            self._collection = None  # Сбрасываем кэш

            # Пакетное добавление документов
            count, _ = self.add_documents_batch(papers)

            logger.info(f"Перестроено {count} статей в векторной базе")
            return count

        except Exception as e:
            logger.error(f"Ошибка перестройки индекса: {e}")
            return 0

    def get_stats(self) -> dict[str, Any]:
        """
        Получить статистику векторной базы.

        Returns:
            Словарь со статистикой:
                - count: Количество документов
                - available: Доступность сервиса
                - collection: Название коллекции
                - persist_directory: Путь к хранилищу
        """
        if not self.collection:
            return {
                "count": 0,
                "available": False,
                "collection": self.COLLECTION_NAME,
                "persist_directory": self._persist_directory,
            }

        try:
            count = self.collection.count()
            return {
                "count": count,
                "available": True,
                "collection": self.COLLECTION_NAME,
                "persist_directory": self._persist_directory,
            }
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return {
                "count": 0,
                "available": False,
                "collection": self.COLLECTION_NAME,
                "persist_directory": self._persist_directory,
            }


# Глобальный экземпляр сервиса
_vector_service: ChromaVectorService | None = None


def get_vector_service() -> ChromaVectorService:
    """
    Получить экземпляр ChromaVectorService (singleton).

    Returns:
        ChromaVectorService: Глобальный экземпляр сервиса.
    """
    global _vector_service
    if _vector_service is None:
        _vector_service = ChromaVectorService()
    return _vector_service
