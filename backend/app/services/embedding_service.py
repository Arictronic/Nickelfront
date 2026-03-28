"""
Сервис для генерации эмбеддингов с использованием sentence-transformers.

Предоставляет функции для создания векторных представлений текста,
пакетной обработки и кэширования моделей.
"""

from typing import Optional, List, Dict, Any
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

    Особенности:
    - Ленивая загрузка модели
    - Кэширование в памяти (lru_cache)
    - Пакетная обработка
    - Нормализация эмбеддингов
    """

    # Модель по умолчанию
    # all-MiniLM-L6-v2 - быстрая и легкая модель (384 измерения)
    # all-mpnet-base-v2 - более качественная модель (768 измерений)
    DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"
    DEFAULT_EMBEDDING_DIM = 384
    DEFAULT_BATCH_SIZE = 32

    def __init__(
        self,
        model_name: Optional[str] = None,
        embedding_dim: Optional[int] = None,
        cache_dir: Optional[str] = None,
        local_only: bool = False,
    ):
        """
        Инициализация сервиса эмбеддингов.

        Args:
            model_name: Название модели. По умолчанию из настроек.
            embedding_dim: Размерность эмбеддингов. По умолчанию из настроек.
            cache_dir: Директория для кэширования моделей.
            local_only: Загружать модели только локально (без скачивания).
        """
        self._model: Optional[SentenceTransformer] = None
        self.MODEL_NAME = model_name or settings.EMBEDDING_MODEL
        self.EMBEDDING_DIM = embedding_dim or settings.EMBEDDING_DIM
        self._cache_dir = cache_dir or settings.EMBEDDING_CACHE_DIR
        self._local_only = local_only or settings.EMBEDDING_LOCAL_ONLY

        logger.info(
            f"Инициализация EmbeddingService: model={self.MODEL_NAME}, "
            f"dim={self.EMBEDDING_DIM}"
        )

    @property
    def model(self) -> Optional[SentenceTransformer]:
        """Ленивая загрузка модели."""
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            logger.warning("sentence-transformers не установлен. Эмбеддинги недоступны.")
            return None

        if self._model is None:
            cache_dir = self._cache_dir
            cache_dir = settings.resolve_path(cache_dir) if cache_dir else None
            if cache_dir:
                Path(cache_dir).mkdir(parents=True, exist_ok=True)

            logger.info(
                f"Загрузка модели эмбеддингов: {self.MODEL_NAME} (local_only={self._local_only})"
            )
            try:
                self._model = SentenceTransformer(
                    self.MODEL_NAME,
                    cache_folder=cache_dir,
                    local_files_only=self._local_only,
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
                if self._local_only:
                    logger.error(
                        "Модель не найдена локально. "
                        "Попробуйте установить EMBEDDING_LOCAL_ONLY=false."
                    )
                return None
        return self._model

    def get_embedding(self, text: str) -> Optional[List[float]]:
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

    @lru_cache(maxsize=1000)
    def get_embedding_cached(self, text: str) -> Optional[List[float]]:
        """
        Получить эмбеддинг с кэшированием результатов.

        Args:
            text: Текст для генерации эмбеддинга

        Returns:
            Вектор размерности EMBEDDING_DIM или None
        """
        return self.get_embedding(text)

    def get_embeddings_batch(
        self,
        texts: List[str],
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> List[List[float]]:
        """
        Получить эмбеддинги для списка текстов (пакетная обработка).

        Args:
            texts: Список текстов
            batch_size: Размер пакета для обработки

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
                batch_size=batch_size,
            )
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"Ошибка пакетной генерации эмбеддингов: {e}")
            return []

    def get_paper_embedding_text(
        self,
        title: str,
        abstract: str,
        keywords: List[str],
    ) -> str:
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

    def get_stats(self) -> Dict[str, Any]:
        """
        Получить статистику сервиса эмбеддингов.

        Returns:
            Словарь со статистикой:
                - available: Доступность сервиса
                - model: Название модели
                - embedding_dim: Размерность эмбеддингов
                - cache_info: Информация о кэше (если доступен)
        """
        stats = {
            "available": self.model is not None,
            "model": self.MODEL_NAME if self.model else None,
            "embedding_dim": self.EMBEDDING_DIM if self.model else None,
            "cache_dir": self._cache_dir,
            "local_only": self._local_only,
        }

        # Информация о кэше lru_cache
        if hasattr(self.get_embedding_cached, 'cache_info'):
            stats["cache_info"] = str(self.get_embedding_cached.cache_info())

        return stats

    def is_available(self) -> bool:
        """
        Проверяет доступность сервиса эмбеддингов.

        Returns:
            True если модель загружена и готова к работе.
        """
        return self.model is not None


# Глобальный экземпляр сервиса
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """
    Получить экземпляр EmbeddingService (singleton).

    Returns:
        EmbeddingService: Глобальный экземпляр сервиса.
    """
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
