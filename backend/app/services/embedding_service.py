"""Сервис для генерации эмбеддингов с использованием sentence-transformers."""

from typing import Optional
from pathlib import Path
from functools import lru_cache
from loguru import logger

from app.core.config import settings

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    SentenceTransformer = None


class EmbeddingService:
    """
    Сервис для генерации векторных эмбеддингов текста.
    
    Использует предобученную модель sentence-transformers для создания
    векторных представлений текста, которые захватывают семантический смысл.
    """
    
    # Модель для генерации эмбеддингов
    # all-MiniLM-L6-v2 - быстрая и легкая модель (384 измерения)
    # all-mpnet-base-v2 - более качественная модель (768 измерений)
    MODEL_NAME = "all-MiniLM-L6-v2"
    EMBEDDING_DIM = 384
    
    def __init__(self):
        self._model: Optional[SentenceTransformer] = None
        self.MODEL_NAME = settings.EMBEDDING_MODEL
        self.EMBEDDING_DIM = settings.EMBEDDING_DIM
    
    @property
    def model(self) -> Optional[SentenceTransformer]:
        """Ленивая загрузка модели."""
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            logger.warning("sentence-transformers не установлен. Эмбеддинги недоступны.")
            return None

        if self._model is None:
            cache_dir = settings.EMBEDDING_CACHE_DIR
            cache_dir = settings.resolve_path(cache_dir) if cache_dir else None
            if cache_dir:
                Path(cache_dir).mkdir(parents=True, exist_ok=True)
            local_only = settings.EMBEDDING_LOCAL_ONLY

            logger.info(
                f"Инициализация модели эмбеддингов: {self.MODEL_NAME} (local_only={local_only})"
            )
            try:
                self._model = SentenceTransformer(
                    self.MODEL_NAME,
                    cache_folder=cache_dir,
                    local_files_only=local_only,
                )
                logger.info(f"Модель {self.MODEL_NAME} успешно загружена")
            except TypeError:
                # Старая версия sentence-transformers не поддерживает local_files_only
                try:
                    self._model = SentenceTransformer(self.MODEL_NAME, cache_folder=cache_dir)
                    logger.info(f"Модель {self.MODEL_NAME} успешно загружена")
                except Exception as e:
                    logger.error(f"Ошибка загрузки модели: {e}")
                    return None
            except Exception as e:
                logger.error(f"Ошибка загрузки модели: {e}")
                if local_only:
                    logger.error(
                        "Модель не найдена локально. "
                        "Попробуйте установить EMBEDDING_LOCAL_ONLY=false."
                    )
                return None
        return self._model
    
    def get_embedding(self, text: str) -> Optional[list[float]]:
        """
        Получить векторный эмбеддинг для текста.
        
        Args:
            text: Текст для генерации эмбеддинга
            
        Returns:
            Вектор размерности EMBEDDING_DIM или None если ошибка
        """
        if not self.model:
            return None
        
        if not text or not text.strip():
            return None
        
        try:
            # Генерируем эмбеддинг
            embedding = self.model.encode(
                text,
                convert_to_numpy=True,
                normalize_embeddings=True,  # Нормализация для косинусного сходства
                show_progress_bar=False,
            )
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Ошибка генерации эмбеддинга: {e}")
            return None
    
    def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Получить эмбеддинги для списка текстов (пакетная обработка).
        
        Args:
            texts: Список текстов
            
        Returns:
            Список векторов
        """
        if not self.model:
            return []
        
        # Фильтруем пустые тексты
        valid_texts = [t for t in texts if t and t.strip()]
        if not valid_texts:
            return []
        
        try:
            embeddings = self.model.encode(
                valid_texts,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=True,
                batch_size=32,
            )
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"Ошибка пакетной генерации эмбеддингов: {e}")
            return []
    
    def get_paper_embedding_text(self, title: str, abstract: str, keywords: list[str]) -> str:
        """
        Подготовить текст статьи для генерации эмбеддинга.
        
        Args:
            title: Заголовок статьи
            abstract: Аннотация
            keywords: Ключевые слова
            
        Returns:
            Объединенный текст для эмбеддинга
        """
        parts = []
        
        if title and title.strip():
            parts.append(f"Title: {title}")
        
        if abstract and abstract.strip():
            parts.append(f"Abstract: {abstract}")
        
        if keywords and len(keywords) > 0:
            parts.append(f"Keywords: {', '.join(keywords)}")
        
        return " | ".join(parts) if parts else ""


# Глобальный экземпляр сервиса
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Получить экземпляр EmbeddingService (singleton)."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
