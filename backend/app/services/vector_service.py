"""Сервис векторного поиска с использованием ChromaDB."""

import os
from typing import Optional
from dataclasses import dataclass
from loguru import logger

from app.core.config import settings

try:
    import chromadb
    from chromadb.config import Settings
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
    doi: Optional[str]
    similarity: float
    metadata: dict


class ChromaVectorService:
    """
    Сервис для векторного поиска с использованием ChromaDB.
    
    ChromaDB - векторная база данных для хранения и поиска эмбеддингов.
    Поддерживает фильтрацию по метаданным и косинусное сходство.
    """
    
    COLLECTION_NAME = "papers"
    CHROMA_PERSIST_DIR = "./chroma_db"
    
    def __init__(self):
        self._client = None
        self._collection = None
        self.CHROMA_PERSIST_DIR = settings.resolve_path(settings.CHROMA_DB_PATH)
    
    @property
    def client(self):
        """Ленивая инициализация клиента ChromaDB."""
        if not CHROMADB_AVAILABLE:
            logger.warning("ChromaDB не установлен. Векторный поиск недоступен.")
            return None
        
        if self._client is None:
            try:
                # Создаем директорию для персистентного хранения
                os.makedirs(self.CHROMA_PERSIST_DIR, exist_ok=True)
                
                # Инициализируем персистентный клиент
                self._client = chromadb.PersistentClient(
                    path=self.CHROMA_PERSIST_DIR,
                    settings=Settings(
                        anonymized_telemetry=False,
                        allow_reset=True,
                    )
                )
                logger.info(f"ChromaDB инициализирован: {self.CHROMA_PERSIST_DIR}")
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
        doi: Optional[str] = None,
        publication_date: Optional[str] = None,
        journal: Optional[str] = None,
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
    
    def search(
        self,
        query_embedding: list[float],
        limit: int = 10,
        source: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
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
            # Формируем фильтр где
            where = {}
            if source:
                where["source"] = source
            
            # ChromaDB поддерживает простые фильтры where
            # Для сложных фильтров по дате нужна постобработка
            
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
    
    def rebuild_index(self, papers: list[dict]) -> int:
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
            except:
                pass
            
            # Создаем новую
            self._collection = None  # Сбрасываем кэш
            
            count = 0
            for paper in papers:
                if paper.get("embedding"):
                    if self.add_paper(
                        paper_id=paper["id"],
                        embedding=paper["embedding"],
                        title=paper["title"],
                        source=paper["source"],
                        doi=paper.get("doi"),
                        publication_date=paper.get("publication_date"),
                        journal=paper.get("journal"),
                    ):
                        count += 1
            
            logger.info(f"Перестроено {count} статей в векторной базе")
            return count
            
        except Exception as e:
            logger.error(f"Ошибка перестройки индекса: {e}")
            return 0
    
    def get_stats(self) -> dict:
        """Получить статистику векторной базы."""
        if not self.collection:
            return {"count": 0, "available": False}
        
        try:
            count = self.collection.count()
            return {
                "count": count,
                "available": True,
                "collection": self.COLLECTION_NAME,
            }
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return {"count": 0, "available": False}


# Глобальный экземпляр сервиса
_vector_service: Optional[ChromaVectorService] = None


def get_vector_service() -> ChromaVectorService:
    """Получить экземпляр ChromaVectorService (singleton)."""
    global _vector_service
    if _vector_service is None:
        _vector_service = ChromaVectorService()
    return _vector_service
